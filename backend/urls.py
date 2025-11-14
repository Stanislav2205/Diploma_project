from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    BasketView,
    ContactViewSet,
    CurrentUserView,
    EmailConfirmationView,
    OrderConfirmView,
    OrderStatusUpdateView,
    OrderViewSet,
    PartnerImportView,
    PartnerOrdersView,
    PartnerProfileView,
    ProductViewSet,
    RegistrationView,
)

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="product")
router.register(r"contacts", ContactViewSet, basename="contact")
router.register(r"orders", OrderViewSet, basename="order")

urlpatterns = [
    path("auth/register/", RegistrationView.as_view(), name="auth-register"),
    path("auth/confirm/", EmailConfirmationView.as_view(), name="auth-confirm"),
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", CurrentUserView.as_view(), name="auth-me"),
    path("cart/", BasketView.as_view(), name="cart"),
    path("orders/confirm/", OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/<int:pk>/status/", OrderStatusUpdateView.as_view(), name="order-status-update"),
    path("partner/profile/", PartnerProfileView.as_view(), name="partner-profile"),
    path("partner/import/", PartnerImportView.as_view(), name="partner-import"),
    path("partner/orders/", PartnerOrdersView.as_view(), name="partner-orders"),
    path("", include(router.urls)),
]