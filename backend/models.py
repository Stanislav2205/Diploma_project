import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Пользовательский менеджер, использующий электронную почту в качестве уникального идентификатора."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("The email address must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)

class User(AbstractUser):
    """Пользователь приложения, который аутентифицируется по адресу электронной почты."""

    class Role(models.TextChoices):
        BUYER = "buyer", _("Покупатель")
        SHOP = "shop", _("Поставщик")

    username = None
    email = models.EmailField(_("email address"), unique=True)
    role = models.CharField(
        _("Тип пользователя"),
        max_length=16,
        choices=Role.choices,
        default=Role.BUYER,
    )
    company = models.CharField(_("Компания"), max_length=80, blank=True)
    position = models.CharField(_("Должность"), max_length=80, blank=True)
    email_verified = models.BooleanField(_("Email подтверждён"), default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    def __str__(self) -> str:
        return self.get_full_name() or self.email


class Shop(models.Model):
    """Розничный партнер, поставляющий продукцию."""

    owner = models.ForeignKey(
        User,
        verbose_name=_("Владелец"),
        related_name="shops",
        on_delete=models.CASCADE,
    )
    name = models.CharField(_("Название"), max_length=128, unique=True)
    url = models.URLField(_("Ссылка на прайс"), blank=True)
    is_active = models.BooleanField(_("Принимает заказы"), default=True)
    created_at = models.DateTimeField(_("Создан"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Обновлён"), auto_now=True)

    class Meta:
        verbose_name = _("Магазин")
        verbose_name_plural = _("Магазины")

    def __str__(self) -> str:
        return self.name


class Category(models.Model):
    name = models.CharField(_("Название категории"), max_length=128, unique=True)
    shops = models.ManyToManyField(
        Shop,
        verbose_name=_("Магазины"),
        related_name="categories",
        blank=True,
    )

    class Meta:
        verbose_name = _("Категория")
        verbose_name_plural = _("Категории")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        verbose_name=_("Категория"),
        related_name="products",
        on_delete=models.CASCADE,
    )
    name = models.CharField(_("Название"), max_length=256)
    description = models.TextField(_("Описание"), blank=True)

    class Meta:
        verbose_name = _("Товар")
        verbose_name_plural = _("Товары")
        unique_together = (("category", "name"),)
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ProductInfo(models.Model):
    product = models.ForeignKey(
        Product,
        verbose_name=_("Товар"),
        related_name="infos",
        on_delete=models.CASCADE,
    )
    shop = models.ForeignKey(
        Shop,
        verbose_name=_("Магазин"),
        related_name="product_infos",
        on_delete=models.CASCADE,
    )
    external_id = models.PositiveIntegerField(_("Внешний идентификатор"))
    model = models.CharField(_("Модель"), max_length=128, blank=True)
    name = models.CharField(_("Название позиции"), max_length=256, blank=True)
    price = models.DecimalField(
        _("Цена"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.0"))],
    )
    price_rrc = models.DecimalField(
        _("РРЦ"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.0"))],
    )
    quantity = models.PositiveIntegerField(_("Количество на складе"), default=0)

    class Meta:
        verbose_name = _("Информация о товаре")
        verbose_name_plural = _("Информация о товарах")
        constraints = [
            models.UniqueConstraint(
                fields=("shop", "external_id"),
                name="unique_shop_external_product",
            )
        ]

    def __str__(self) -> str:
        return f"{self.product.name} @ {self.shop.name}"


class Parameter(models.Model):
    name = models.CharField(_("Название характеристики"), max_length=64, unique=True)

    class Meta:
        verbose_name = _("Характеристика")
        verbose_name_plural = _("Характеристики")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ProductParameter(models.Model):
    product_info = models.ForeignKey(
        ProductInfo,
        verbose_name=_("Товар"),
        related_name="parameters",
        on_delete=models.CASCADE,
    )
    parameter = models.ForeignKey(
        Parameter,
        verbose_name=_("Характеристика"),
        related_name="product_values",
        on_delete=models.CASCADE,
    )
    value = models.CharField(_("Значение"), max_length=256)

    class Meta:
        verbose_name = _("Значение характеристики")
        verbose_name_plural = _("Значения характеристик")
        unique_together = (("product_info", "parameter"),)

    def __str__(self) -> str:
        return f"{self.parameter.name}: {self.value}"


class Contact(models.Model):
    user = models.ForeignKey(
        User,
        verbose_name=_("Пользователь"),
        related_name="contacts",
        on_delete=models.CASCADE,
    )
    first_name = models.CharField(_("Имя"), max_length=64)
    last_name = models.CharField(_("Фамилия"), max_length=64)
    patronymic = models.CharField(_("Отчество"), max_length=64, blank=True)
    email = models.EmailField(_("Email"))
    phone = models.CharField(_("Телефон"), max_length=32)
    city = models.CharField(_("Город"), max_length=64)
    street = models.CharField(_("Улица"), max_length=128)
    house = models.CharField(_("Дом"), max_length=32)
    structure = models.CharField(_("Корпус"), max_length=32, blank=True)
    building = models.CharField(_("Строение"), max_length=32, blank=True)
    apartment = models.CharField(_("Квартира"), max_length=32, blank=True)
    created_at = models.DateTimeField(_("Создан"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Обновлён"), auto_now=True)

    class Meta:
        verbose_name = _("Контакт")
        verbose_name_plural = _("Контакты")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.last_name} {self.first_name}, {self.city}"


class Order(models.Model):
    class Status(models.TextChoices):
        CART = "cart", _("Корзина")
        NEW = "new", _("Новый")
        CONFIRMED = "confirmed", _("Подтверждён")
        ASSEMBLED = "assembled", _("Собран")
        SHIPPED = "shipped", _("Отгружен")
        COMPLETED = "completed", _("Завершён")
        CANCELLED = "cancelled", _("Отменён")

    user = models.ForeignKey(
        User,
        verbose_name=_("Пользователь"),
        related_name="orders",
        on_delete=models.CASCADE,
    )
    contact = models.ForeignKey(
        Contact,
        verbose_name=_("Контакт"),
        related_name="orders",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    status = models.CharField(
        _("Статус"),
        max_length=16,
        choices=Status.choices,
        default=Status.CART,
    )
    comment = models.TextField(_("Комментарий"), blank=True)
    created_at = models.DateTimeField(_("Создан"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Обновлён"), auto_now=True)

    class Meta:
        verbose_name = _("Заказ")
        verbose_name_plural = _("Заказы")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Order #{self.pk} ({self.get_status_display()})"

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items.all())

    @property
    def total_cost(self) -> Decimal:
        return sum((item.total_price for item in self.items.all()), Decimal("0"))


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        verbose_name=_("Заказ"),
        related_name="items",
        on_delete=models.CASCADE,
    )
    product_info = models.ForeignKey(
        ProductInfo,
        verbose_name=_("Позиция товара"),
        related_name="order_items",
        on_delete=models.PROTECT,
    )
    quantity = models.PositiveIntegerField(
        _("Количество"),
        validators=[MinValueValidator(1)],
    )
    price = models.DecimalField(
        _("Цена за единицу"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.0"))],
    )
    created_at = models.DateTimeField(_("Добавлено"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Обновлено"), auto_now=True)

    class Meta:
        verbose_name = _("Позиция заказа")
        verbose_name_plural = _("Позиции заказа")
        unique_together = (("order", "product_info"),)

    @property
    def total_price(self) -> Decimal:
        return self.price * self.quantity

    def __str__(self) -> str:
        return f"{self.product_info} x {self.quantity}"


class EmailConfirmationToken(models.Model):
    user = models.ForeignKey(
        User,
        verbose_name=_("Пользователь"),
        related_name="email_tokens",
        on_delete=models.CASCADE,
    )
    token = models.CharField(_("Токен"), max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(_("Создан"), auto_now_add=True)
    expires_at = models.DateTimeField(_("Истекает"), editable=False)
    is_used = models.BooleanField(_("Использован"), default=False)

    class Meta:
        verbose_name = _("Токен подтверждения email")
        verbose_name_plural = _("Токены подтверждения email")
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def mark_as_used(self):
        self.is_used = True
        self.save(update_fields=["is_used"])

    def __str__(self) -> str:
        return f"Token for {self.user.email}"
