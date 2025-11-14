from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from django.db import transaction

from backend.models import (
    Category,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
)


@dataclass
class ImportResult:
    categories_created: int = 0
    products_created: int = 0
    product_infos_created: int = 0
    parameters_created: int = 0


class CatalogImporter:
    """Утилита, загружающая полезную нагрузку каталога на уровень сохранения."""

    def __init__(self, shop: Shop):
        self.shop = shop

    def _to_decimal(self, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise ValueError(f"Cannot convert value `{value}` to decimal.")

    @transaction.atomic
    def import_payload(self, payload: dict[str, Any]) -> ImportResult:
        result = ImportResult()

        categories = payload.get("categories", [])
        goods = payload.get("goods", [])

        category_map: dict[int, Category] = {}

        for category_data in categories:
            name = category_data.get("name")
            external_id = category_data.get("id")
            if not name:
                continue
            category, created = Category.objects.get_or_create(name=name)
            if created:
                result.categories_created += 1
            category_map[external_id] = category
            self.shop.categories.add(category)

        processed_external_ids: set[int] = set()
        for item in goods:
            category_ext_id = item.get("category")
            category = category_map.get(category_ext_id)
            if not category:
                continue

            product, product_created = Product.objects.get_or_create(
                category=category,
                name=item.get("name", item.get("model", "Без названия")),
                defaults={"description": item.get("description", "")},
            )
            if product_created:
                result.products_created += 1

            external_id = item.get("id", 0)
            defaults = {
                "model": item.get("model", ""),
                "name": item.get("name", ""),
                "price": self._to_decimal(item.get("price", 0)),
                "price_rrc": self._to_decimal(item.get("price_rrc", item.get("price", 0))),
                "quantity": int(item.get("quantity", 0)),
            }
            info, created = ProductInfo.objects.update_or_create(
                product=product,
                shop=self.shop,
                external_id=external_id,
                defaults=defaults,
            )
            if created:
                result.product_infos_created += 1
            processed_external_ids.add(info.external_id)
            info.parameters.all().delete()

            for param_name, value in self._iter_parameters(item):
                parameter, created = Parameter.objects.get_or_create(name=param_name)
                if created:
                    result.parameters_created += 1
                ProductParameter.objects.create(
                    product_info=info,
                    parameter=parameter,
                    value=str(value),
                )

        if processed_external_ids:
            ProductInfo.objects.filter(shop=self.shop).exclude(external_id__in=processed_external_ids).update(
                quantity=0
            )

        return result

    def _iter_parameters(self, item: dict[str, Any]) -> Iterable[tuple[str, Any]]:
        parameters = item.get("parameters", {})
        if isinstance(parameters, dict):
            return parameters.items()
        return []

