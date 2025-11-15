from copy import deepcopy

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient, APIRequestFactory

from backend.models import (
    Category,
    Contact,
    EmailConfirmationToken,
    Order,
    Parameter,
    Product,
    ProductInfo,
    Shop,
    User,
    OrderItem,
)
from backend.services.importer import CatalogImporter
from backend.serializers import (
    BacketSerializer,
    OrderItemSerializer,
    PartherImportSerializer,
)


CATALOG_PAYLOAD = {
    "categories": [
        {"id": 1, "name": "Смартфоны"},
        {"id": 2, "name": "Аксессуары"},
    ],
    "goods": [
        {
            "id": 100,
            "category": 1,
            "model": "apple/iphone/xs",
            "name": "iPhone XS",
            "price": 100000,
            "price_rrc": 110000,
            "quantity": 5,
            "parameters": {"Цвет": "золотой", "Память": "64"},
        },
        {
            "id": 101,
            "category": 2,
            "model": "apple/case-xs",
            "name": "Чехол iPhone XS",
            "price": 3000,
            "price_rrc": 3990,
            "quantity": 10,
            "parameters": {"Цвет": "черный"},
        },
    ],
}

class CatalogImporterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="supplier@example.com",
            password="Password123!",
            role=User.Role.SHOP,
        )
        self.shop = Shop.objects.create(owner=self.user, name="Test Shop")

    def test_import_payload_creates_entities(self):
        importer = CatalogImporter(self.shop)
        result = importer.import_payload(CATALOG_PAYLOAD)
        self.assertEqual(result.categories_created, 2)
        self.assertEqual(result.products_created, 2)
        self.assertEqual(result.product_infos_created, 2)
        self.assertEqual(Parameter.objects.count(), 2)
        self.assertEqual(ProductInfo.objects.filter(shop=self.shop).count(), 2)
        self.assertSetEqual(
            set(Category.objects.values_list("name", flat=True)),
            {"Смартфоны", "Аксессуары"},
        )

    def test_reimport_replaces_previous_entries(self):
        importer = CatalogImporter(self.shop)
        importer.import_payload(CATALOG_PAYLOAD)

        payload = deepcopy(CATALOG_PAYLOAD)
        payload["goods"] = [{**payload["goods"][0], "quantity": 1}]
        importer.import_payload(payload)

        infos = ProductInfo.objects.filter(shop=self.shop)
        self.assertEqual(infos.count(), 2)
        self.assertEqual(
            infos.get(external_id=CATALOG_PAYLOAD["goods"][0]["id"]).quantity,
            1,
        )
        self.assertEqual(
            infos.get(external_id=CATALOG_PAYLOAD["goods"][1]["id"]).quantity,
            0,
        )
        self.assertEqual(Product.objects.count(), 2)

    def test_decimal_conversion_and_invalid_input(self):
        importer = CatalogImporter(self.shop)
        self.assertEqual(importer._to_decimal(Decimal("1.23")), Decimal("1.23"))
        with self.assertRaises(ValueError):
            importer._to_decimal(object())
    
    def test_goods_without_category_are_skipped(self):
        importer = CatalogImporter(self.shop)
        payload = {
            "categories": [],
            "goods": [{"id": 999, "category": 123, "name": "Ghost product"}],
        }
        result = importer.import_payload(payload)
        self.assertEqual(result.products_created, 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ApiFlowTests(APITestCase):
    def setUp(self):
        self.password = "Password123!"
        self.user_email = "buyer@example.com"
        supplier = User.objects.create_user(
            email="supplier@example.com",
            password="Supplier123!",
            role=User.Role.SHOP,
            first_name="Test",
            last_name="Supplier",
        )
        self.shop = Shop.objects.create(owner=supplier, name="Test Shop")
        CatalogImporter(self.shop).import_payload(CATALOG_PAYLOAD)

    def authenticate_user(self):
        register_payload = {
            "email": self.user_email,
            "password": self.password,
            "first_name": "Buyer",
            "last_name": "User",
            "role": User.Role.BUYER,
        }
        response = self.client.post(reverse("auth-register"), register_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)

        token = EmailConfirmationToken.objects.get(user__email=self.user_email)
        confirm_response = self.client.post(
            reverse("auth-confirm"),
            {"email": self.user_email, "token": token.token},
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)

        token_response = self.client.post(
            reverse("token-obtain"),
            {"email": self.user_email, "password": self.password},
        )
        self.assertEqual(token_response.status_code, status.HTTP_200_OK)
        return token_response.json()
    def create_order(self, quantity=2):
        tokens = self.authenticate_user()
        access = tokens["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(orders_response.json()["count"], 1)

        product_info = ProductInfo.objects.first()
        self.client.post(
            reverse("cart"),
            {"product_info": product_info.id, "quantity": quantity},
            format="json",
        )
        contact_response = self.client.post(
            reverse("contact-list"),
            {
                "first_name": "Иван",
                "last_name": "Иванов",
                "patronymic": "Иванович",
                "email": self.user_email,
                "phone": "+79999999999",
                "city": "Москва",
                "street": "Тверская",
                "house": "1",
            },
            format="json",
        )
        self.assertEqual(contact_response.status_code, status.HTTP_201_CREATED)
        contact_id = contact_response.json()["id"]
        self.assertTrue(Contact.objects.filter(id=contact_id).exists())

        confirm_response = self.client.post(
            reverse("order-confirm"),
            {"contact_id": contact_id, "comment": "Побыстрее"},
            format="json",
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_201_CREATED)

        order = Order.objects.exclude(status=Order.Status.CART).get(user__email=self.user_email)
        self.assertEqual(order.status, Order.Status.NEW)
        self.assertEqual(order.total_quantity, 2)
        self.assertEqual(order.items.count(), 1)

        orders_response = self.client.get(reverse("order-list"))
        self.assertEqual(orders_response.status_code, status.HTTP_200_OK)
        self.assertEqual(orders_response.json()["count"], 1)