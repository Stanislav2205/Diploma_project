from copy import deepcopy
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

import requests
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.test import APIClient, APITestCase, APIRequestFactory

from backend.models import (
    Category,
    Contact,
    EmailConfirmationToken,
    Order,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
    User,
    OrderItem,
)
from backend.services.importer import CatalogImporter
from backend.serializers import (
    BasketSerializer,
    OrderItemSerializer,
    PartnerImportSerializer,
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

    def test_category_without_name_is_ignored(self):
        importer = CatalogImporter(self.shop)
        payload = {
            "categories": [{"id": 10}],
            "goods": [],
        }
        result = importer.import_payload(payload)
        self.assertEqual(result.categories_created, 0)

    def test_iter_parameters_handles_non_dict(self):
        importer = CatalogImporter(self.shop)
        self.assertEqual(list(importer._iter_parameters({"parameters": []})), [])


class ModelRepresentationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            password="UserPass123!",
            first_name="Test",
            last_name="User",
        )
        self.shop = Shop.objects.create(owner=self.user, name="Shop Name")
        self.category = Category.objects.create(name="Category")
        self.product = Product.objects.create(category=self.category, name="Product", description="Desc")
        self.product_info = ProductInfo.objects.create(
            product=self.product,
            shop=self.shop,
            external_id=1,
            model="model-x",
            name="Product info",
            price=Decimal("10.00"),
            price_rrc=Decimal("12.00"),
            quantity=5,
        )
        self.parameter = Parameter.objects.create(name="Color")
        ProductParameter.objects.create(product_info=self.product_info, parameter=self.parameter, value="Red")
        self.contact = Contact.objects.create(
            user=self.user,
            first_name="Test",
            last_name="User",
            patronymic="Middle",
            email="user@example.com",
            phone="+70000000000",
            city="City",
            street="Street",
            house="1",
        )
        self.order = Order.objects.create(user=self.user, contact=self.contact, status=Order.Status.NEW)
        self.order_item = OrderItem.objects.create(
            order=self.order,
            product_info=self.product_info,
            quantity=2,
            price=Decimal("10.00"),
        )
        self.token = EmailConfirmationToken.objects.create(user=self.user)

    def test_string_representations(self):
        self.assertEqual(str(self.user), "Test User")
        self.assertEqual(str(self.shop), "Shop Name")
        self.assertEqual(str(self.category), "Category")
        self.assertEqual(str(self.product), "Product")
        self.assertIn("Product", str(self.product_info))
        self.assertEqual(str(self.parameter), "Color")
        self.assertIn("Color", str(self.product_info.parameters.first()))
        self.assertIn("City", str(self.contact))
        self.assertIn("Order", str(self.order))
        self.assertIn("x 2", str(self.order_item))
        self.assertIn(self.user.email, str(self.token))

    def test_order_totals_and_token_mark_used(self):
        self.assertEqual(self.order.total_quantity, 2)
        self.assertEqual(self.order.total_cost, Decimal("20.00"))
        self.assertFalse(self.token.is_used)
        self.token.mark_as_used()
        self.assertTrue(self.token.is_used)

    def test_user_manager_validations(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="123")
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="admin1@example.com",
                password="Admin123!",
                is_staff=False,
            )
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="admin2@example.com",
                password="Admin123!",
                is_superuser=False,
            )


class SerializerValidationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            email="buyer2@example.com",
            password="BuyerPass123!",
            first_name="Buyer",
            last_name="Two",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="Other123!",
            first_name="Other",
            last_name="User",
        )
        self.shop = Shop.objects.create(owner=self.other_user, name="Another Shop")
        self.category = Category.objects.create(name="Other Category")
        self.product = Product.objects.create(category=self.category, name="Another product")
        self.product_info = ProductInfo.objects.create(
            product=self.product,
            shop=self.shop,
            external_id=5,
            price=Decimal("5"),
            price_rrc=Decimal("6"),
            quantity=10,
        )
        self.contact = Contact.objects.create(
            user=self.other_user,
            first_name="Other",
            last_name="User",
            email="other@example.com",
            phone="+79999999991",
            city="City",
            street="Street",
            house="2",
        )
        self.order = Order.objects.create(user=self.user)
        OrderItem.objects.create(
            order=self.order,
            product_info=self.product_info,
            quantity=2,
            price=Decimal("5"),
        )

    def test_order_item_serializer_quantity_validation(self):
        serializer = OrderItemSerializer(
            data={"product_info_id": self.product_info.id, "quantity": 0},
            context={"order": self.order},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("quantity", serializer.errors)
        with self.assertRaises(serializers.ValidationError):
            OrderItemSerializer().validate_quantity(0)
        self.assertEqual(OrderItemSerializer().validate_quantity(1), 1)

    def test_partner_import_serializer_requires_payload(self):
        serializer = PartnerImportSerializer(
            data={},
            context={"request_files": None},
        )
        self.assertFalse(serializer.is_valid())

    def test_basket_serializer_totals(self):
        serializer = BasketSerializer(self.order)
        data = serializer.data
        self.assertEqual(data["total_quantity"], 2)
        self.assertEqual(Decimal(str(data["total_cost"])), Decimal("10"))


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

        product_info = ProductInfo.objects.first()
        add_response = self.client.post(
            reverse("cart"),
            {"product_info": product_info.id, "quantity": quantity},
            format="json",
        )
        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)

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

        confirm_response = self.client.post(
            reverse("order-confirm"),
            {"contact_id": contact_id, "comment": "Побыстрее"},
            format="json",
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_201_CREATED)

        order = Order.objects.exclude(status=Order.Status.CART).get(user__email=self.user_email)
        return order, tokens, contact_id, product_info

    def test_product_catalog_available(self):
        response = self.client.get(reverse("product-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.json()["count"], 1)

    def test_complete_order_flow(self):
        order, tokens, contact_id, product_info = self.create_order(quantity=2)

        self.assertTrue(Contact.objects.filter(id=contact_id).exists())
        self.assertEqual(order.status, Order.Status.NEW)
        self.assertEqual(order.total_quantity, 2)
        self.assertEqual(order.items.count(), 1)

        orders_response = self.client.get(reverse("order-list"))
        self.assertEqual(orders_response.status_code, status.HTTP_200_OK)
        self.assertEqual(orders_response.json()["count"], 1)

    def test_email_confirmation_invalid_token(self):
        email = "another@example.com"
        password = "StrongPass123!"
        register_payload = {
            "email": email,
            "password": password,
            "first_name": "Another",
            "last_name": "User",
            "role": User.Role.BUYER,
        }
        response = self.client.post(reverse("auth-register"), register_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        invalid_response = self.client.post(
            reverse("auth-confirm"),
            {"email": email, "token": "wrong-token"},
        )
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_confirmation_requires_fields_and_expiration(self):
        empty_response = self.client.post(reverse("auth-confirm"), {})
        self.assertEqual(empty_response.status_code, status.HTTP_400_BAD_REQUEST)

        email = "expired@example.com"
        password = "StrongPass123!"
        register_payload = {
            "email": email,
            "password": password,
            "first_name": "Expired",
            "last_name": "User",
            "role": User.Role.BUYER,
        }
        self.client.post(reverse("auth-register"), register_payload)
        token = EmailConfirmationToken.objects.get(user__email=email)
        token.expires_at = timezone.now() - timedelta(minutes=5)
        token.save(update_fields=["expires_at"])
        expired_response = self.client.post(
            reverse("auth-confirm"),
            {"email": email, "token": token.token},
        )
        self.assertEqual(expired_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cart_validation_update_and_delete(self):
        tokens = self.authenticate_user()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        product_info = ProductInfo.objects.first()
        too_much = self.client.post(
            reverse("cart"),
            {"product_info": product_info.id, "quantity": product_info.quantity + 100},
            format="json",
        )
        self.assertEqual(too_much.status_code, status.HTTP_400_BAD_REQUEST)

        add_response = self.client.post(
            reverse("cart"),
            {"product_info": product_info.id, "quantity": 1},
            format="json",
        )
        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)

        get_response = self.client.get(reverse("cart"))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        patch_response = self.client.patch(
            reverse("cart"),
            {"product_info": product_info.id, "quantity": 3},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(f"{reverse('cart')}?product_info={product_info.id}")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        missing_response = self.client.delete(reverse("cart"))
        self.assertEqual(missing_response.status_code, status.HTTP_400_BAD_REQUEST)

        not_found_response = self.client.delete(f"{reverse('cart')}?product_info=999999")
        self.assertEqual(not_found_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_contact_list_update_delete(self):
        order, tokens, contact_id, _ = self.create_order(quantity=1)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        list_response = self.client.get(reverse("contact-list"))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.json()["count"], 1)

        patch_response = self.client.patch(
            reverse("contact-detail", args=[contact_id]),
            {"city": "Санкт-Петербург"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(reverse("contact-detail", args=[contact_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Contact.objects.filter(id=contact_id).exists())

    def test_order_confirm_requires_non_empty_cart(self):
        tokens = self.authenticate_user()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        response = self.client.post(reverse("order-confirm"), {"contact_id": 1}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_order_confirm_rejects_foreign_contact(self):
        tokens = self.authenticate_user()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        product_info = ProductInfo.objects.first()
        self.client.post(
            reverse("cart"),
            {"product_info": product_info.id, "quantity": 1},
            format="json",
        )
        foreign_user = User.objects.create_user(
            email="foreign@example.com",
            password="Foreign123!",
            first_name="For",
            last_name="Eigner",
        )
        foreign_contact = Contact.objects.create(
            user=foreign_user,
            first_name="For",
            last_name="Eigner",
            email="foreign@example.com",
            phone="+79999999998",
            city="City",
            street="Street",
            house="5",
        )
        response = self.client.post(
            reverse("order-confirm"),
            {"contact_id": foreign_contact.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_current_user_and_token_refresh(self):
        tokens = self.authenticate_user()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        me_response = self.client.get(reverse("auth-me"))
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.json()["email"], self.user_email)

        refresh_response = self.client.post(
            reverse("token-refresh"),
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_response.json())

    def test_product_detail_and_order_detail(self):
        order, tokens, contact_id, product_info = self.create_order(quantity=1)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        product_detail = self.client.get(reverse("product-detail", args=[product_info.product_id]))
        self.assertEqual(product_detail.status_code, status.HTTP_200_OK)

        order_detail = self.client.get(reverse("order-detail", args=[order.id]))
        self.assertEqual(order_detail.status_code, status.HTTP_200_OK)

    def test_partner_profile_import_and_orders(self):
        order, _, _, _ = self.create_order(quantity=1)
        self.client.credentials()  # reset headers

        partner_login = self.client.post(
            reverse("token-obtain"),
            {"email": "supplier@example.com", "password": "Supplier123!"},
        )
        self.assertEqual(partner_login.status_code, status.HTTP_200_OK)
        partner_tokens = partner_login.json()

        partner_client = APIClient()
        partner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {partner_tokens['access']}")

        profile_response = partner_client.get(reverse("partner-profile"))
        self.assertEqual(profile_response.status_code, status.HTTP_200_OK)

        patch_response = partner_client.patch(
            reverse("partner-profile"),
            {"name": "Updated Shop", "is_active": False},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertFalse(patch_response.json()["is_active"])

        import_response = partner_client.post(
            reverse("partner-import"),
            {"data": CATALOG_PAYLOAD},
            format="json",
        )
        self.assertEqual(import_response.status_code, status.HTTP_200_OK)

        orders_response = partner_client.get(reverse("partner-orders"))
        self.assertEqual(orders_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(orders_response.json()["count"], 1)

    def test_partner_import_invalid_cases(self):
        self.create_order(quantity=1)
        self.client.credentials()
        partner_login = self.client.post(
            reverse("token-obtain"),
            {"email": "supplier@example.com", "password": "Supplier123!"},
        )
        partner_tokens = partner_login.json()
        partner_client = APIClient()
        partner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {partner_tokens['access']}")

        with patch("backend.views.requests.get", side_effect=requests.RequestException("boom")):
            response = partner_client.post(
                reverse("partner-import"),
                {"url": "http://example.com/catalog.yaml"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        class DummyResponse:
            text = ": invalid yaml"

            def raise_for_status(self):
                return None

        with patch("backend.views.requests.get", return_value=DummyResponse()):
            response = partner_client.post(
                reverse("partner-import"),
                {"url": "http://example.com/catalog.yaml"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        invalid_file = SimpleUploadedFile("bad.yaml", b": invalid yaml", content_type="text/yaml")
        response = partner_client.post(reverse("partner-import"), {"file": invalid_file})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = partner_client.post(
            reverse("partner-import"),
            {"data": ["not", "dict"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_can_update_order_status(self):
        order, tokens, _, _ = self.create_order(quantity=1)
        self.client.credentials()

        admin_email = "admin@example.com"
        admin_password = "Admin123!"
        User.objects.create_superuser(
            email=admin_email,
            password=admin_password,
            first_name="Admin",
            last_name="User",
        )
        admin_login = self.client.post(
            reverse("token-obtain"),
            {"email": admin_email, "password": admin_password},
        )
        self.assertEqual(admin_login.status_code, status.HTTP_200_OK)
        admin_tokens = admin_login.json()

        admin_client = APIClient()
        admin_client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_tokens['access']}")

        response = admin_client.patch(
            reverse("order-status-update", args=[order.id]),
            {"status": Order.Status.CONFIRMED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CONFIRMED)