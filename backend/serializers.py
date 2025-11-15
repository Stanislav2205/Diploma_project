from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import (
    Category,
    Contact,
    Order,
    OrderItem,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
)

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "role",
            "company",
            "position",
        )

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "company",
            "position",
            "email_verified",
        )

class EmailConfirmationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    token = serializers.CharField()

class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shop
        fields = ("id", "name", "url", "is_active")


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name")


class ParameterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parameter
        fields = ("id", "name")


class ProductParameterSerializer(serializers.ModelSerializer):
    parameter = ParameterSerializer()

    class Meta:
        model = ProductParameter
        fields = ("parameter", "value")


class ProductInfoSerializer(serializers.ModelSerializer):
    shop = ShopSerializer()
    parameters = ProductParameterSerializer(many=True)

    class Meta:
        model = ProductInfo
        fields = (
            "id",
            "external_id",
            "model",
            "name",
            "price",
            "price_rrc",
            "quantity",
            "shop",
            "parameters",
        )


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer()
    infos = ProductInfoSerializer(many=True)

    class Meta:
        model = Product
        fields = ("id", "name", "description", "category", "infos")


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = (
            "id",
            "first_name",
            "last_name",
            "patronymic",
            "email",
            "phone",
            "city",
            "street",
            "house",
            "structure",
            "building",
            "apartment",
        )

    def create(self, validated_data):
        user = self.context["request"].user
        return Contact.objects.create(user=user, **validated_data)


class OrderItemSerializer(serializers.ModelSerializer):
    product_info = ProductInfoSerializer(read_only=True)
    product_info_id = serializers.PrimaryKeyRelatedField(
        queryset=ProductInfo.objects.all(), source="product_info", write_only=True
    )
    total_price = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ("id", "product_info", "product_info_id", "quantity", "price", "total_price")
        read_only_fields = ("price", "total_price")

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError(_("Количество должно быть больше нуля."))
        return value

    def get_total_price(self, obj: OrderItem) -> Decimal:
        return obj.total_price


class BasketItemUpdateSerializer(serializers.Serializer):
    product_info = serializers.PrimaryKeyRelatedField(queryset=ProductInfo.objects.all())
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        product_info: ProductInfo = attrs["product_info"]
        quantity: int = attrs["quantity"]
        if quantity > product_info.quantity:
            raise serializers.ValidationError(_("Запрошенное количество превышает остаток на складе."))
        return attrs

    def save(self, **kwargs):
        order: Order = self.context["order"]
        product_info = self.validated_data["product_info"]
        quantity = self.validated_data["quantity"]
        item, _ = OrderItem.objects.update_or_create(
            order=order,
            product_info=product_info,
            defaults={
                "quantity": quantity,
                "price": product_info.price,
            },
        )
        return item


class BasketSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    total_quantity = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("id", "status", "items", "total_quantity", "total_cost")

    def get_total_quantity(self, obj: Order) -> int:
        return obj.total_quantity

    def get_total_cost(self, obj: Order) -> Decimal:
        return obj.total_cost


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    total_quantity = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()
    contact = ContactSerializer(read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "status",
            "created_at",
            "updated_at",
            "comment",
            "contact",
            "total_quantity",
            "total_cost",
            "items",
        )

    def get_total_quantity(self, obj: Order) -> int:
        return obj.total_quantity

    def get_total_cost(self, obj: Order) -> Decimal:
        return obj.total_cost


class OrderConfirmSerializer(serializers.Serializer):
    contact_id = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.all(), source="contact")
    comment = serializers.CharField(required=False, allow_blank=True)

    def validate_contact(self, contact: Contact):
        request = self.context["request"]
        if contact.user != request.user:
            raise serializers.ValidationError(_("Контакт принадлежит другому пользователю."))
        return contact

    def save(self, **kwargs):
        order: Order = self.context["order"]
        order.contact = self.validated_data["contact"]
        order.comment = self.validated_data.get("comment", "")
        order.status = Order.Status.NEW
        order.save(update_fields=["contact", "comment", "status", "updated_at"])
        return order


class OrderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ("status",)


class PartnerOrderItemSerializer(serializers.ModelSerializer):
    order = serializers.PrimaryKeyRelatedField(read_only=True)
    product_info = ProductInfoSerializer()
    total_price = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ("order", "product_info", "quantity", "price", "total_price")

    def get_total_price(self, obj: OrderItem) -> Decimal:
        return obj.total_price


class PartnerOrderSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("id", "status", "created_at", "items")

    def get_items(self, obj: Order):
        shop = self.context.get("shop")
        queryset = obj.items.all()
        if shop is not None:
            queryset = queryset.filter(product_info__shop=shop)
        serializer = PartnerOrderItemSerializer(queryset, many=True, context = self.context)
        return serializer.data

class PartnerImportSerializer(serializers.Serializer):
    url = serializers.URLField(required=False)
    data = serializers.JSONField(required=False)
    file = serializers.FileField(required=False)

    def validate(self, attrs):
        if not attrs.get("url") and not attrs.get("data") and "file" not in self.context.get("request_data", {}):
            raise serializers.ValidationError(_("Нужно предоставить url, data или file."))
        return attrs

