from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

User = get_user_model()


class IsBuyer(BasePermission):
    """Предоставляет доступ только покупателям."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.BUYER
        )


class IsShop(BasePermission):
    """Предоставляет доступ только пользователям-поставщикам."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.SHOP
        )


class IsEmailVerified(BasePermission):
    """Разрешить только пользователям с подтвержденными адресами электронной почты."""

    message = "Email адрес требует подтверждения."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.email_verified)
