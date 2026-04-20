import json
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timezone import now
from django.db import connection



def create_notification(user_id, message, email_subject=None):
    """
    Stores the notification in the database and sends an email if an email_subject is provided.
    """
    timestamp = now()

    # Store notification in the database
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO notifications (user_id, message, created_at, is_read)
            VALUES (%s, %s, %s, %s)
        """, [user_id, message, timestamp, False])

    # Fetch user email for email notification
    if email_subject:
        with connection.cursor() as cursor:
            cursor.execute("SELECT email FROM users WHERE id = %s", [user_id])
            user_email = cursor.fetchone()[0]

        # Send email notification
        send_mail(
            subject=email_subject,
            message=message,
            from_email="zincoauctions14@gmail.com",  # Replace with your email
            recipient_list=[user_email],
            fail_silently=True,
        )

def send_email_notification(recipient_email, subject, message):
    """
    Sends an emai notification using Django's email backend.
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

    with connection.cursor() as cursor:
        cursor.execute("SELECT id, email FROM users")
        users = cursor.fetchall()

    for user in users:
        target_user_id = user[0]
        target_email = user[1]
        notify_user(target_user_id, target_email, message, subject=subject, extra_data={'auction_id': auction_id})