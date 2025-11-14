from django.conf import settings
from django.core.mail import send_mail

def send_registration_confirmation(user, token: str):
    subject = "Подтверждение регистрации"
    message = (
        f"Здравствуйте, {user.first_name or user.email}!\n\n"
        "Спасибо за регистрацию в сервисе автоматизации закупок.\n"
        "Для подтверждения email используйте следующий токен:\n\n"
        f"{token}\n\n"
        "Или перейдите по ссылке вашего фронтенда, передав токен.\n"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])


def send_order_confirmation_to_customer(order):
    subject = f"Заказ №{order.pk} принят"
    message = (
        f"Здравствуйте, {order.user.first_name or order.user.email}!\n"
        f"Ваш заказ №{order.pk} принят и находится в статусе '{order.get_status_display()}'.\n"
        f"Общее количество товаров: {order.total_quantity}\n"
        f"Сумма к оплате: {order.total_cost}.\n"
        "Спасибо, что выбираете наш сервис."
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [order.user.email])


def notify_admin_about_order(order):
    subject = f"Новый заказ №{order.pk}"
    message_lines = [
        f"Поступил новый заказ #{order.pk} от {order.user.email}.",
        f"Статус: {order.get_status_display()}",
        f"Количество товаров: {order.total_quantity}",
        f"Сумма: {order.total_cost}",
        "",
        "Состав заказа:",
    ]
    for item in order.items.all():  
        message_lines.append(
            f"- {item.product_info.product.name} ({item.product_info.shop.name}) x {item.quantity} = {item.total_price}"
        )
    send_mail(
        subject,
        "\n".join(message_lines),
        settings.DEFAULT_FROM_EMAIL,
        [settings.ORDER_NOTIFICATION_EMAIL],
    )

def send_password_reset_email(user, reset_token):
    subject = "Сброс пароля"
    message = f"Для сброса пароля используйте токен: {reset_token}"
    send_mail(subject, message, "noreply@example.com", [user.email])