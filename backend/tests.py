from django.test import TestCase
from backend.models import Category, Parameter, Product, ProductInfo, Shop, User
from backend.services.importer import CatalogImporter

SAMPLE_PAYLOAD = {
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
        result = importer.import_payload(SAMPLE_PAYLOAD)

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
        importer.import_payload(SAMPLE_PAYLOAD)
        payload = SAMPLE_PAYLOAD.copy()
        payload["goods"] = [
            {
                **SAMPLE_PAYLOAD["goods"][0],
                "quantity": 1,
            }
        ]
        importer.import_payload(payload)

        infos = ProductInfo.objects.filter(shop=self.shop)
        self.assertEqual(infos.count(), 1)
        self.assertEqual(infos.first().quantity, 1)
        self.assertEqual(Product.objects.count(), 2)