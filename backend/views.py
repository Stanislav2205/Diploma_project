import io
from typing import Any

import requests
import yaml
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Contact,
    EmailConfirmationToken,
    Order,
    OrderItem,
    Product,
    Shop,
)
from .permissions import IsBuyer, IsEmailVerified, IsShop
from .serializers import (
    BasketItemUpdateSerializer,
    BasketSerializer,
    ContactSerializer,
    OrderConfirmSerializer,
    OrderSerializer,
    OrderStatusSerializer,
    PartnerOrderSerializer,
    ProductSerializer,
    ShopSerializer,
    UserRegistrationSerializer,
    UserSerializer,
)
from .services.emails import (
    notify_admin_about_order,
    send_order_confirmation_to_customer,
    send_registration_confirmation,
)
from .services.importer import CatalogImporter

User = get_user_model()


def get_user_cart(user: User) -> Order:
    cart, _ = Order.objects.get_or_create(user=user, status=Order.Status.CART)
    return cart


class RegistrationView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        user = serializer.save()
        token = EmailConfirmationToken.objects.create(user=user)
        send_registration_confirmation(user, token.token)


class EmailConfirmationView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        token_value = request.data.get("token")
        if not email or not token_value:
            return Response(
                {"detail": "Необходимо указать email и token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = get_object_or_404(User, email=email)
        try:
            token = user.email_tokens.get(token=token_value, is_used=False)
        except EmailConfirmationToken.DoesNotExist:
            return Response({"detail": "Неверный токен."}, status=status.HTTP_400_BAD_REQUEST)

        if token.expires_at < timezone.now():
            return Response({"detail": "Срок действия токена истёк."}, status=status.HTTP_400_BAD_REQUEST)

        token.mark_as_used()
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        return Response({"detail": "Email успешно подтверждён."})


class CurrentUserView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.all().prefetch_related("infos__shop", "infos__parameters__parameter")
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    filterset_fields = ("category__id", "category__name","infos__shop__id")
    search_fields = ("name", "description", "infos__model")
    ordering_fields = ("name", "infos__price")


class BasketView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsBuyer, IsEmailVerified]

    def get(self, request, *args, **kwargs):
        order = get_user_cart(request.user)
        serializer = BasketSerializer(order)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        cart = get_user_cart(request.user)
        serializer = BasketItemUpdateSerializer(data=request.data, context={"order": cart})
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response({"detail": "Товар добавлен", "item_id": item.id}, status=status.HTTP_201_CREATED)

    def patch(self, request, *args, **kwargs):
        cart = get_user_cart(request.user)
        serializer = BasketItemUpdateSerializer(data=request.data, context={"order": cart})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Корзина обновлена."})

    def delete(self, request, *args, **kwargs):
        cart = get_user_cart(request.user)
        product_info_id = request.data.get("product_info") or request.query_params.get("product_info")
        if not product_info_id:
            return Response({"detail": "Необходимо указать product_info."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            item = cart.items.get(product_info_id=product_info_id)
        except OrderItem.DoesNotExist:
            return Response({"detail": "Товар не найден в корзине."}, status=status.HTTP_404_NOT_FOUND)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [permissions.IsAuthenticated, IsBuyer]

    def get_queryset(self):
        return Contact.objects.filter(user=self.request.user)


class OrderConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsBuyer, IsEmailVerified]

    def post(self, request, *args, **kwargs):
        cart = get_user_cart(request.user)
        if not cart.items.exists():
            return Response({"detail": "Нельзя подтвердить пустую корзину."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = OrderConfirmSerializer(
            data=request.data,
            context={"request": request, "order": cart},
        )
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        notify_admin_about_order(order)
        send_order_confirmation_to_customer(order)
        return Response({"detail": f"Заказ №{order.pk} создан."}, status=status.HTTP_201_CREATED)


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Order.objects.filter(user=self.request.user).exclude(status=Order.Status.CART)
        return queryset.prefetch_related("items__product_info__product", "items__product_info__shop", "contact")


class OrderStatusUpdateView(generics.UpdateAPIView):
    queryset = Order.objects.all()
    serializer_class = OrderStatusSerializer
    permission_classes = [permissions.IsAdminUser]

    def perform_update(self, serializer):
        order = serializer.save()
        if order.status == Order.Status.CANCELLED:
            pass


class PartnerProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ShopSerializer
    permission_classes = [permissions.IsAuthenticated, IsShop]

    def get_object(self):
        shop, _ = Shop.objects.get_or_create(owner=self.request.user, defaults={"name": self.request.user.company or self.request.user.email})
        return shop


class PartnerImportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShop]

    def post(self, request, *args, **kwargs):
        payload = request.data
        if "url" in payload:
            try:
                response = requests.get(payload["url"], timeout=10)
                response.raise_for_status()
            except requests.RequestException as exc:
                return Response({"detail": f"Ошибка загрузки данных: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
            payload = yaml.safe_load(response.text)
        elif "file" in request.FILES:
            uploaded = request.FILES["file"]
            payload = yaml.safe_load(uploaded.read())
        elif "data" in payload:
            payload = payload["data"]

        if not isinstance(payload, dict):
            return Response({"detail": "Неверный формат данных для импорта."}, status=status.HTTP_400_BAD_REQUEST)

        shop = Shop.objects.get(owner=request.user)
        importer = CatalogImporter(shop)
        result = importer.import_payload(payload)
        
        return Response(
            {
                "detail": "Импорт завершён успешно.",
                "created": {
                    "categories": result.categories_created,
                    "products": result.products_created,
                    "product_infos": result.product_infos_created,
                    "parameters": result.parameters_created,
                },
                "debug_info": str(payload)
            }
        )


class PartnerOrdersView(generics.ListAPIView):
    serializer_class = PartnerOrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsShop]
    
    def get_queryset(self):
        return Order.objects.filter(items__product_info__shop__owner=self.request.user).distinct()
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "orders": serializer.data,
            "count": len(serializer.data)
        })


def test_function():
    pass