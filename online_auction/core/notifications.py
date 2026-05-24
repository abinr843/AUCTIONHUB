import json
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timezone import now
from .models import Notification, User



def create_notification(user_id, message, email_subject=None):
    """
    Stores the notification in the database and sends an email if an email_subject is provided.
    """
    # Store notification in the database using Django ORM
    Notification.objects.create(
        user_id=user_id,
        message=message,
        is_read=False,
        created_at=now()
    )

    # Fetch user email for email notification
    if email_subject:
        try:
            user = User.objects.get(id=user_id)
            # Send email notification
            send_mail(
                subject=email_subject,
                message=message,
                from_email="zincoauctions14@gmail.com",  # Replace with your email
                recipient_list=[user.email],
                fail_silently=True,
            )
        except User.DoesNotExist:
            pass

def send_email_notification(recipient_email, subject, message):
    """
    Sends an email notification using Django's email backend.
    """
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [recipient_email])

def notify_user(user_id, recipient_email, message, subject="Auction Notification", extra_data=None):
    """
    Create an in-app notification and send an email notification.
    """
    create_notification(user_id, message, extra_data)
    send_email_notification(recipient_email, subject, message)



def notify_all_users_for_new_auction(auction_id, title):
    """
    Notify all users that a new auction has been created.
    """
    message = f"A new auction '{title}' has been created! Check it out now."
    subject = "New Auction Alert from AuctionPro"

    users = User.objects.values_list('id', 'email')
    for user_id, email in users:
        notify_user(user_id, email, message, subject=subject, extra_data={'auction_id': auction_id})