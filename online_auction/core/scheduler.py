import time
import re
import threading
from datetime import datetime, timedelta
from .notifications import notify_user, notify_all_users_for_new_auction,create_notification
from django.db import connection, transaction
import uuid
import logging
from django.core.mail import send_mail
from django.conf import settings
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, TimeoutError
from decimal import Decimal
from django.utils import timezone
from django.utils.timezone import make_aware,now
import random


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def select_regular_auction_winners():
    """
    Select winners for regular auctions:
      - Only unprocessed auctions (checked = 0 AND winner_user_id IS NULL) are considered.
      - Auctions must have ended (plus a 1-minute grace period).
      - A winner is selected only if the highest bid meets or exceeds the reserve price.
      - Once processed, even if no winner is found, the auction is marked as checked.
      - For a valid winner:
          • Insert an order with shipping_status as "Pending" and payment_status as "Pending".
          • Send in-app and email notifications to both the winner and the seller.
    """
    now_time = datetime.now()

    with transaction.atomic():
        with connection.cursor() as cursor:
            # Select auctions not yet processed (checked = 0) that have ended
            query = """
                SELECT id, title, reserve_price, user_id
                FROM auctions
                WHERE DATE_ADD(end_date, INTERVAL 1 MINUTE) <= %s
                  AND winner_user_id IS NULL
                  AND checked = 0
                FOR UPDATE
            """
            cursor.execute(query, [now_time])
            auctions = cursor.fetchall()

            for auction in auctions:
                auction_id, title, reserve_price, seller_id = auction

                # Handle case where reserve_price might be None (optional field)
                reserve_price = float(reserve_price) if reserve_price is not None else 0.0

                # Get the highest bid for this auction
                cursor.execute("""
                    SELECT user_id, amount
                    FROM bids
                    WHERE auction_id = %s
                    ORDER BY amount DESC
                    LIMIT 1
                """, [auction_id])
                bid = cursor.fetchone()

                if bid:
                    winner_id, highest_bid = bid
                    # Ensure highest_bid is a float, though it should always be numeric from bids table
                    highest_bid = float(highest_bid)

                    if highest_bid >= reserve_price:
                        # Valid winner: update auction record with winner and mark as checked
                        cursor.execute("""
                            UPDATE auctions
                            SET winner_user_id = %s, checked = 1
                            WHERE id = %s
                        """, [winner_id, auction_id])

                        # Insert order record with shipping_status set to "Pending" and payment_status as "Pending"
                        cursor.execute("""
                            INSERT INTO orders (auction_id, user_id, invoice_id, payment_status, payment_amount, shipping_status, order_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, [auction_id, winner_id, None, "Pending", highest_bid, "Pending", now_time])

                        # Fetch winner and seller details
                        cursor.execute("SELECT email, username FROM users WHERE id = %s", [winner_id])
                        winner_info = cursor.fetchone()  # (winner_email, winner_username)
                        cursor.execute("SELECT email, username FROM users WHERE id = %s", [seller_id])
                        seller_info = cursor.fetchone()  # (seller_email, seller_username)

                        if winner_info and seller_info:
                            winner_email, winner_username = winner_info
                            seller_email, seller_username = seller_info

                            # Notification message for winner
                            winner_message = f"""
                            **🎉 Congratulations, {winner_username}! 🎉**

                            You have won the auction for **"{title}"** with a bid of **${highest_bid:.2f}**!
                            Your order has been created with a shipping status of **Pending**.
                            Please proceed to give the shipping details.

                            Click the link below to view your order details:
                            🔗 [View Order](your_order_dashboard_link_here)

                            Thank you for participating in the auction!
                            **The ZinCo Auction Team**
                            """

                            # Notification message for seller
                            seller_message = f"""
                            **📢 New Order Received, {seller_username}!**  

                            Your auction **"{title}"** has ended and a winner has been selected.
                            The winning bid was **${highest_bid:.2f}**.
                            An order has been generated with a shipping status of **Pending**.

                            Please check your seller dashboard for order details and proceed with fulfillment.

                            🔗 [View Order](your_order_dashboard_link_here)

                            Thank you for listing with AuctionPro!
                            **The ZinCo Auction Team**
                            """

                            # Send notifications
                            notify_user(winner_id, winner_email, winner_message, subject="🎉 You Won the Auction!")
                            notify_user(seller_id, seller_email, seller_message, subject="📢 New Order Received!")

                            print(
                                f"✅ Auction {auction_id}: Winner selected (User {winner_id}) with bid ${highest_bid:.2f}. Notifications sent.")
                        else:
                            print(f"⚠️ Auction {auction_id}: Winner or seller details not found.")
                    else:
                        # Highest bid did not meet reserve price: mark auction as checked
                        cursor.execute("""
                            UPDATE auctions
                            SET checked = 1
                            WHERE id = %s
                        """, [auction_id])
                        print(
                            f"⚠️ Auction {auction_id}: Highest bid ${highest_bid:.2f} did not meet reserve price ${reserve_price:.2f}. Marked as checked.")
                else:
                    # No bids found: mark auction as checked
                    cursor.execute("""
                        UPDATE auctions
                        SET checked = 1
                        WHERE id = %s
                    """, [auction_id])
                    print(f"❌ Auction {auction_id}: No bids found. Marked as checked.")

    print("✅ Regular auction winner selection and order processing completed.")


def select_sealed_bid_winners():
    """
    Select winners for sealed bid auctions:
      - The auction winner is selected if the winner_selection_date <= now.
      - Winner is only selected if the highest bid >= reserve_price.
      - Once a winner is determined, update the auction, create an order with a pending payment status,
        and send notifications (both in-app and email) to the winner and the seller.
      - If no bid meets the reserve price, mark the auction as checked but assign no winner.
    """
    # Use current datetime for selection
    now_dt = datetime.now()

    with transaction.atomic():
        with connection.cursor() as cursor:
            # Select sealed auctions where winner_selection_date <= now
            # and no winner has been assigned yet, including reserve_price
            cursor.execute("""
                SELECT a.id, a.title, a.user_id, a.reserve_price
                FROM auctions a
                JOIN sealed_bid_details s ON a.id = s.auction_id
                WHERE s.winner_selection_date <= %s
                  AND a.winner_user_id IS NULL
            """, [now_dt])
            auctions = cursor.fetchall()

            for auction in auctions:
                auction_id, title, seller_id, reserve_price = auction

                # Retrieve the highest bid for this auction
                cursor.execute("""
                    SELECT user_id, amount 
                    FROM bids 
                    WHERE auction_id = %s 
                    ORDER BY amount DESC 
                    LIMIT 1
                """, [auction_id])
                bid = cursor.fetchone()

                if bid:
                    winner_id, highest_bid = bid

                    # Check if the highest bid meets or exceeds the reserve price
                    if highest_bid >= reserve_price:
                        # Update the auction to mark the winner and mark as processed
                        cursor.execute("""
                            UPDATE auctions 
                            SET winner_user_id = %s, checked = 1
                            WHERE id = %s
                        """, [winner_id, auction_id])

                        # Create an order record with shipping_status and payment_status as "Pending"
                        cursor.execute("""
                            INSERT INTO orders (auction_id, user_id, invoice_id, payment_status, payment_amount, shipping_status, order_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, [auction_id, winner_id, None, "Pending", highest_bid, "Pending", now_dt])

                        # Fetch winner and seller details for notifications
                        cursor.execute("SELECT email, username FROM users WHERE id = %s", [winner_id])
                        winner_info = cursor.fetchone()  # (winner_email, winner_username)
                        cursor.execute("SELECT email, username FROM users WHERE id = %s", [seller_id])
                        seller_info = cursor.fetchone()  # (seller_email, seller_username)

                        if winner_info and seller_info:
                            winner_email, winner_username = winner_info
                            seller_email, seller_username = seller_info

                            # Notification message for the winner
                            winner_message = f"""
**🎉 Congratulations, {winner_username}! 🎉**

You have won the sealed bid auction for **"{title}"** with a bid of **${float(highest_bid):.2f}**!
Your order has been created with a shipping status of **Pending**.
Please proceed with the next steps to complete your purchase.

Click the link below to view your order details:
🔗 [View Order](your_order_dashboard_link_here)

Thank you for participating in the auction!
**The ZinCo Auction Team**
                            """

                            # Notification message for the seller
                            seller_message = f"""
**📢 Your Auction Has a Winner, {seller_username}!**  

Your sealed bid auction **"{title}"** has ended, and a winner has been selected.
The winning bid was **${float(highest_bid):.2f}**.
An order has been generated with a shipping status of **Pending**.

Please check your seller dashboard for order details and proceed with fulfillment.

🔗 [View Order](your_order_dashboard_link_here)

Thank you for listing with ZinCo Auctions!
**The ZinCo Auction Team**
                            """

                            # Send notifications (in-app and email)
                            notify_user(winner_id, winner_email, winner_message, subject="🎉 You Won the Auction!")
                            notify_user(seller_id, seller_email, seller_message, subject="📢 Your Auction Has a Winner!")

                            print(f"✅ Sealed Bid Auction {auction_id}: Winner selected (User {winner_id}) with bid ${float(highest_bid):.2f} (Reserve: ${float(reserve_price):.2f}). Notifications sent.")
                        else:
                            print(f"⚠️ Sealed Bid Auction {auction_id}: Winner or seller details not found.")
                    else:
                        # If highest bid is below reserve price, mark as checked but no winner
                        cursor.execute("""
                            UPDATE auctions 
                            SET checked = 1 
                            WHERE id = %s
                        """, [auction_id])
                        print(f"❌ Sealed Bid Auction {auction_id}: Highest bid ${float(highest_bid):.2f} below reserve price ${float(reserve_price):.2f}. No winner selected.")
                else:
                    # If no bids are found, mark auction as checked
                    cursor.execute("""
                        UPDATE auctions 
                        SET checked = 1 
                        WHERE id = %s
                    """, [auction_id])
                    print(f"❌ Sealed Bid Auction {auction_id}: No bids found. Marked as checked.")

    print("✅ Sealed bid auction winner selection and notifications completed.")




def generate_invoices():
    """
    Generate invoices for all orders with order_status = 'Confirmed' and no existing invoice.
    Sets invoice status to 'Pending' and sends an email/in-app notification to the buyer.
    In development environment, due date is set to 5 minutes from now for testing.
    """
    print("🔄 Running invoice generation process...")
    now = timezone.now()  # Use the current aware datetime
    print(f"🔍 DEBUG: Current timestamp (now): {now}")

    # Set due date 5 minutes later for development environment
    due_date = now + timedelta(minutes=5)
    print(f"🔍 DEBUG: Due date set to: {due_date} (5 minutes from now for development)")

    # Fetch orders that need invoices
    with connection.cursor() as cursor:
        # First, fetch all confirmed orders to debug
        cursor.execute("""
            SELECT order_id, auction_id, user_id, invoice_id, payment_amount, order_status
            FROM orders
            WHERE order_status = 'Confirmed'
        """)
        confirmed_orders = cursor.fetchall()
        print(f"🔍 DEBUG: Found {len(confirmed_orders)} confirmed orders: {confirmed_orders}")

        # Main query to find orders needing invoices
        cursor.execute("""
            SELECT o.order_id, o.auction_id, o.user_id, a.user_id AS seller_id, o.payment_amount, o.order_status
            FROM orders o
            JOIN auctions a ON o.auction_id = a.id
            WHERE o.order_status = 'Confirmed'
              AND o.invoice_id IS NULL
            GROUP BY o.order_id, o.auction_id, o.user_id, a.user_id, o.payment_amount, o.order_status
        """)
        orders = cursor.fetchall()

    if not orders:
        print("✅ No new invoices to generate. Checking reasons...")
        # Additional debugging
        with connection.cursor() as cursor:
            # Check orders with invoice_id IS NULL
            cursor.execute("""
                SELECT order_id, auction_id, user_id, invoice_id, order_status
                FROM orders
                WHERE order_status = 'Confirmed' AND invoice_id IS NULL
            """)
            orders_without_invoice = cursor.fetchall()
            print(f"🔍 DEBUG: Confirmed orders without invoice: {len(orders_without_invoice)} - {orders_without_invoice}")

            # Check if auctions exist for these orders
            if orders_without_invoice:
                auction_ids = [order[1] for order in orders_without_invoice]
                cursor.execute("""
                    SELECT id, user_id
                    FROM auctions
                    WHERE id IN %s
                """, [tuple(auction_ids)])
                related_auctions = cursor.fetchall()
                print(f"🔍 DEBUG: Related auctions: {related_auctions}")

        return

    print(f"🔍 DEBUG: Found {len(orders)} orders needing invoices: {orders}")

    for order_id, auction_id, buyer_id, seller_id, amount, order_status in orders:
        try:
            # Double-check order data
            print(f"🔍 DEBUG: Processing Order {order_id} - Auction: {auction_id}, Buyer: {buyer_id}, Seller: {seller_id}, Amount: {amount}, Order Status: {order_status}")

            # Double-check that no invoice exists for this order
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM invoices WHERE auction_id = %s", [auction_id])
                existing_invoice_count = cursor.fetchone()[0]
                print(f"🔍 DEBUG: Existing invoice count for Auction {auction_id}: {existing_invoice_count}")

            if existing_invoice_count > 0:
                print(f"⚠️ Invoice already exists for Auction {auction_id}. Skipping.")
                logger.warning(f"Invoice already exists for Auction {auction_id}. Skipping.")
                continue

            # Generate a unique invoice ID
            invoice_id = str(uuid.uuid4())
            print(f"🔍 DEBUG: Generated invoice_id={invoice_id} for order {order_id}")

            # Insert invoice record with status explicitly set to 'Pending'
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO invoices (id, auction_id, buyer_id, seller_id, amount_due, issue_date, due_date, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, [invoice_id, auction_id, buyer_id, seller_id, amount, now, due_date, "Pending"])
                print(f"✅ DEBUG: Inserted invoice {invoice_id} with status 'Pending' and issue_date {now}")

                # Verify the status immediately after insertion
                cursor.execute("SELECT status FROM invoices WHERE id = %s", [invoice_id])
                inserted_status = cursor.fetchone()[0]
                print(f"🔍 DEBUG: Verified invoice {invoice_id} status: {inserted_status}")
                if inserted_status != "Pending":
                    print(f"❌ [ERROR] Invoice {invoice_id} status is {inserted_status}, expected 'Pending'!")
                    logger.error(f"Invoice {invoice_id} status is {inserted_status}, expected 'Pending'!")

                # Update the corresponding order record to set the invoice_id
                cursor.execute("""
                    UPDATE orders
                    SET invoice_id = %s
                    WHERE order_id = %s AND order_status = 'Confirmed'
                """, [invoice_id, order_id])
                affected_rows = cursor.rowcount
                if affected_rows == 0:
                    print(f"⚠️ WARNING: No order updated for order_id {order_id}. Possible data inconsistency.")
                    logger.warning(f"No order updated for order_id {order_id}. Possible data inconsistency.")
                else:
                    print(f"✅ DEBUG: Updated order {order_id} with invoice {invoice_id}")

            # Fetch user email and details for buyer and seller
            with connection.cursor() as cursor:
                cursor.execute("SELECT email, username FROM users WHERE id = %s", [buyer_id])
                buyer_info = cursor.fetchone()
                cursor.execute("SELECT email, username FROM users WHERE id = %s", [seller_id])
                seller_info = cursor.fetchone()

            if not buyer_info or not seller_info:
                print(f"⚠️ WARNING: Missing user info - Buyer: {buyer_info}, Seller: {seller_info} for order {order_id}")
                logger.warning(f"Missing user info for order {order_id} - Buyer: {buyer_info}, Seller: {seller_info}")
                continue

            buyer_email, buyer_username = buyer_info
            seller_email, seller_username = seller_info
            print(f"🔍 DEBUG: Buyer: {buyer_username} ({buyer_email}), Seller: {seller_username} ({seller_email})")

            # Invoice notification message
            payment_link = "http://localhost:8000/pay/" + invoice_id  # Use localhost for development
            invoice_message = f"""
Dear {buyer_username},

Congratulations! You have won the auction for an item with a final bid of ₹{amount:.2f}.

Please complete your payment by {due_date.strftime('%B %d, %Y %H:%M:%S')} to finalize your purchase.

Invoice Details:
- Invoice ID: {invoice_id}
- Auction ID: {auction_id}
- Total Amount Due: ₹{amount:.2f}
- Seller: {seller_username}
- Payment Due Date: {due_date.strftime('%B %d, %Y %H:%M:%S')}

[Click here to pay now]({payment_link})

Thank you for participating in our auction!

Best regards,
The ZinCo Auction Team
            """

            # Notify the buyer using notification.py
            try:
                notify_user(buyer_id, buyer_email, invoice_message, subject="Invoice for Your Auction Purchase")
                print(f"✅ DEBUG: Notified buyer {buyer_id} at {buyer_email}.")
            except Exception as notify_error:
                print(f"❌ [ERROR] Failed to notify buyer {buyer_id} at {buyer_email}: {str(notify_error)}")
                logger.error(f"Failed to notify buyer {buyer_id}: {str(notify_error)}")

            print(f"✅ Invoice {invoice_id} created for Order {order_id} (Buyer: {buyer_id}, Amount: ₹{amount:.2f})")

        except Exception as e:
            print(f"❌ [ERROR] Failed to generate invoice for Order {order_id}: {str(e)}")
            logger.error(f"Failed to generate invoice for Order {order_id}: {str(e)}")
            continue  # Continue to the next order instead of stopping

    print("✅ Invoice generation completed.")



def notify_new_auctions():
    """
    Checks for auctions with global_notified = 0 and that are still active (end_date > now),
    sends notifications to all users about these newly created auctions,
    and then updates the auction to mark it as notified.
    """
    from datetime import datetime
    print("Checking for new auctions...")
    with connection.cursor() as cursor:
        # Only select auctions that haven't ended and haven't been notified.
        cursor.execute("""
            SELECT id, title FROM auctions 
            WHERE global_notified = 0 
              AND end_date > %s
        """, [datetime.now()])
        auctions = cursor.fetchall()

        if not auctions:
            print("No new auctions found.")
            return

        print(f"Found {len(auctions)} new auction(s).")
        for auction in auctions:
            auction_id, title = auction
            print(f"Processing auction ID: {auction_id}, Title: {title}")
            notify_all_users_for_new_auction(auction_id, title)
            cursor.execute("""
                UPDATE auctions
                SET global_notified = 1
                WHERE id = %s
            """, [auction_id])
            print(f"Notified all users for auction ID: {auction_id}")



def remove_emojis(text):
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F700-\U0001F77F"  # alchemical symbols
        u"\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        u"\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        u"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        u"\U0001FA00-\U0001FA6F"  # Chess Symbols, Symbols for Legacy Computing
        u"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)  # Remove emojis



def notify_premium_expiry_soon():
    """
    Sends a reminder email to premium users whose subscriptions are expiring in 2 days.
    Ensures each user receives only one reminder.
    """
    print("Scheduler ran: Checking for expiring premium subscriptions...")

    now = datetime.now()
    expiry_threshold = now + timedelta(days=2)

    with connection.cursor() as cursor:
        # Fetch users whose premium is expiring AND haven't received a reminder
        cursor.execute("""
            SELECT u.id, u.email, u.username, p.premium_end_date 
            FROM users u
            JOIN premium_users p ON u.id = p.user_id
            WHERE u.premium = 1 
              AND p.premium_end_date BETWEEN %s AND %s
              AND p.reminder_sent = 0  -- Ensures email is only sent once
        """, [now, expiry_threshold])

        expiring_users = cursor.fetchall()

    for user in expiring_users:
        user_id, email, username, end_date = user
        formatted_end_date = end_date.strftime("%B %d, %Y")

        message = f"""
        🌟 **Reminder: Your Premium Subscription is Expiring Soon, {username}!** 🌟  

        Your premium access will end on **{formatted_end_date}**.  
        Don't lose your exclusive benefits:  

        🔹 **Priority Listings** – More exposure for your auctions  
        🔹 **Increased Visibility** – Stand out among sellers  
        🔹 **Premium Support** – Fast-track assistance  

        **Renew now to continue enjoying these perks without interruption!**  

        🔗 [Renew Your Subscription](your_renewal_link_here)  

        Best regards,  
        **The ZinCo Auction Team**  
        """

        notify_user(user_id, email, message, subject="🚨 Your Premium Subscription is Expiring Soon!")

        # **Mark that the reminder has been sent**
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE premium_users 
                SET reminder_sent = 1 
                WHERE user_id = %s
            """, [user_id])

    print("Scheduler execution completed.")

def remove_expired_premium_users():
    """
    Checks for users whose premium subscriptions have expired and revokes their premium status.
    Sends an email and web notification to affected users only once.
    """
    now = datetime.now()

    with connection.cursor() as cursor:
        # Find users whose premium_end_date has passed and who haven't been notified
        cursor.execute("""
            SELECT u.id, u.email, u.username 
            FROM users u
            JOIN premium_users p ON u.id = p.user_id
            WHERE u.premium = 1 AND p.premium_end_date <= %s AND p.notified = 0
        """, [now])

        expired_users = cursor.fetchall()

    for user in expired_users:
        user_id, email, username = user
        print(f"Removing premium status for user {user_id} ({username})")

        # Update user's premium status to 0
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE users 
                SET premium = 0 
                WHERE id = %s
            """, [user_id])

        # Notification message (emoji-free)
        message = f"""
        **Your Premium Subscription Has Expired, {username}!**  

        We loved having you as a premium member, and we don’t want you to miss out on the exclusive perks you enjoyed!  

        - **Priority Listings** – Get your auctions seen first  
        - **Enhanced Visibility** – Attract more bidders  
        - **Premium Support** – Fast and dedicated assistance  

        **💡 Renew your subscription now and continue enjoying these amazing benefits!**  

        Click below to renew and stay ahead in the auction game!  
        🔗 [Renew Now](your_renewal_link_here)  

        If you have any questions, our support team is happy to help.  

        **See you back at the top!**  

        Best regards,  
        **The Zinco Auction Team**  
        """

        # Remove emojis before storing in database
        message_cleaned = remove_emojis(message)

        # Send both web and email notifications
        notify_user(
            user_id=user_id,
            recipient_email=email,
            message=message_cleaned,
            subject="Your Premium Subscription Has Expired – Renew Now!"
        )

        # **Mark that the user has been notified**
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE premium_users 
                SET notified = 1 
                WHERE user_id = %s
            """, [user_id])

    print("Expired premium users have been updated and notified.")



def update_overdue_invoices():
    """
    1. Marks unpaid invoices as 'Overdue' if past the due date.
    2. Applies a late fee (5%) only once when an invoice first becomes overdue.
    3. Sends email and notification alerts to the buyer.
    """
    try:
        print("[INFO] Checking for overdue invoices...")
        now = timezone.now()  # Get the current aware datetime

        with connection.cursor() as cursor:
            # Select all invoices that are overdue (i.e. due_date < now) and whose status is either 'Pending' or 'Overdue'
            cursor.execute("""
                SELECT id, buyer_id, amount_due, late_fee, due_date, status
                FROM invoices 
                WHERE status IN ('Pending', 'Overdue') AND due_date < %s
            """, [now])
            overdue_invoices = cursor.fetchall()

            if not overdue_invoices:
                print("[✅ INFO] No overdue invoices found.")
                return

            print(f"[INFO] Found {len(overdue_invoices)} overdue invoices. Processing...")

            for invoice_id, buyer_id, amount_due, late_fee, due_date, status in overdue_invoices:
                print(f"[DEBUG] Processing Invoice #{invoice_id} | Buyer ID: {buyer_id}")

                # Ensure amount_due is a float for arithmetic
                amount_due = float(amount_due) if isinstance(amount_due, Decimal) else amount_due

                # Apply late fee (5%) only if not already applied (i.e. late_fee is None or 0)
                if late_fee is None or late_fee == 0:
                    late_fee_amount = round(amount_due * 0.05, 2)  # Calculate 5% late fee
                    new_total_due = amount_due + late_fee_amount

                    if status == 'Pending':
                        # Mark the invoice as 'Overdue' and set the late fee
                        cursor.execute("""
                            UPDATE invoices 
                            SET status = 'Overdue', late_fee = %s
                            WHERE id = %s
                        """, [late_fee_amount, invoice_id])
                        print(f"[✅ INFO] Invoice #{invoice_id} marked as 'Overdue'. Late fee: ₹{late_fee_amount:.2f}")
                    else:
                        # If already 'Overdue' but with no fee, update the late_fee
                        cursor.execute("""
                            UPDATE invoices 
                            SET late_fee = %s
                            WHERE id = %s
                        """, [late_fee_amount, invoice_id])
                        print(f"[✅ INFO] Invoice #{invoice_id} updated with late fee: ₹{late_fee_amount:.2f}")

                    # Fetch buyer's email for notification
                    cursor.execute("SELECT email FROM users WHERE id = %s", [buyer_id])
                    buyer_email_row = cursor.fetchone()
                    buyer_email = buyer_email_row[0] if buyer_email_row else None

                    if buyer_email:
                        print(f"[📧 INFO] Sending email to Buyer ID {buyer_id} ({buyer_email})")
                        email_subject = "🚨 Overdue Invoice Notice – Late Fee Applied"
                        email_body = f"""
Dear User,

Invoice #{invoice_id} is now overdue.

Original Amount Due: ₹{amount_due:.2f}
Late Fee Applied: ₹{late_fee_amount:.2f}
Total Due Now: ₹{new_total_due:.2f}

Please make your payment immediately to avoid further penalties.

[Pay Now](your_payment_link_here)

Thank you,  
ZinCo Auction Team
"""
                        send_mail(email_subject, email_body, settings.DEFAULT_FROM_EMAIL, [buyer_email])
                        print(f"[✅ INFO] Email sent to {buyer_email} for Invoice #{invoice_id}.")
                    else:
                        print(f"[⚠️ WARNING] Buyer email not found for Buyer ID {buyer_id}.")
                else:
                    print(f"[INFO] Invoice #{invoice_id} already has a late fee applied. Skipping additional fees.")

        print(f"[✅ SUCCESS] Processed {len(overdue_invoices)} overdue invoices.")

    except Exception as e:
        print(f"[❌ ERROR] Failed to process overdue invoices: {str(e)}")
        logger.error(f"[ERROR] Overdue invoice processing failed: {str(e)}")



def send_winner_selection_reminders():
    """Send email reminders and in-app notifications to bidders 1 day before the winner selection date."""

    reminder_date = (datetime.now() + timedelta(days=1)).date()  # Tomorrow's date
    print(f"🔍 [DEBUG] Checking for auctions with winner selection date: {reminder_date}")

    try:
        with connection.cursor() as cursor:
            # Fetch sealed bid auctions where the winner selection happens tomorrow
            cursor.execute("""
                SELECT sb.auction_id, a.user_id AS seller_id, sb.winner_selection_date
                FROM sealed_bid_details sb
                JOIN auctions a ON sb.auction_id = a.id
                WHERE sb.winner_selection_date = %s
            """, [reminder_date])

            auctions = cursor.fetchall()
            print(f"✅ [DEBUG] Found {len(auctions)} auctions with winner selection tomorrow.")

            for auction_id, seller_id, winner_selection_date in auctions:
                print(f"🔹 [DEBUG] Processing Auction ID: {auction_id}")

                # Fetch seller's email
                cursor.execute("SELECT email FROM users WHERE id = %s", [seller_id])
                seller_email_data = cursor.fetchone()
                seller_email = seller_email_data[0] if seller_email_data else None

                # Fetch unique bidders who placed a bid on this auction
                cursor.execute("""
                    SELECT DISTINCT u.id, u.email 
                    FROM bids b
                    JOIN users u ON b.user_id = u.id
                    WHERE b.auction_id = %s
                """, [auction_id])
                bidder_data = cursor.fetchall()
                bidders = [{'id': row[0], 'email': row[1]} for row in bidder_data]

                print(f"📧 [DEBUG] Seller Email: {seller_email}")
                print(f"📢 [DEBUG] Bidders: {bidders}")

                # Email subject
                subject = "⏳ Reminder: Winner Selection for Your Sealed Bid Auction"

                # Seller email content
                seller_message = f"""
                Hello,

                This is a reminder that the **sealed bid auction** (Auction ID: {auction_id}) 
                will have a winner selected on **{winner_selection_date}**.

                Please review the bids before the selection.

                🔗 [Review Auction](your_seller_dashboard_link_here)

                **Best regards,**  
                ZinCo Auction Team
                """

                # Buyer email content
                buyer_message = f"""
                Hello,

                This is a reminder that the **sealed bid auction** (Auction ID: {auction_id})  
                you participated in will have a winner selected on **{winner_selection_date}**.

                Stay tuned to see if you win!

                🔗 [View Auction Details](your_bid_history_link_here)

                **Best regards,**  
                ZinCo Auction Team
                """

                # Send email to seller
                if seller_email:
                    send_mail(subject, seller_message, settings.DEFAULT_FROM_EMAIL, [seller_email])
                    print(f"✅ [DEBUG] Email sent to seller {seller_id} ({seller_email})")

                # Send email + in-app notification to all bidders
                for bidder in bidders:
                    bidder_id, bidder_email = bidder['id'], bidder['email']

                    # Send email
                    send_mail(subject, buyer_message, settings.DEFAULT_FROM_EMAIL, [bidder_email])
                    print(f"✅ [DEBUG] Email sent to bidder ({bidder_email})")

                    # Create in-app notification using your function
                    create_notification(
                        user_id=bidder_id,
                        message=f"Reminder: The winner for Auction ID {auction_id} will be selected on {winner_selection_date}.",
                        notification_type="auction_reminder"
                    )
                    print(f"🔔 [DEBUG] In-app notification sent to bidder ID: {bidder_id}")

    except Exception as e:
        print(f"❌ [ERROR] Failed to send winner selection reminders: {str(e)}")



def process_fund_distributions():
    """
    Process pending fund distributions by transferring the seller's share and logging the payout.
    Funds are distributed only if the corresponding order's shipping_status is 'Delivered'.
    Sends an email to the seller confirming the funds have been credited to their bank or PayPal.
    """
    print("🔄 [DEBUG] Checking for pending fund distributions for delivered orders...")

    try:
        with connection.cursor() as cursor:
            # Fetch all pending fund distributions where the associated order has shipping_status = 'Delivered'
            cursor.execute("""
                SELECT fd.id, fd.invoice_id, fd.auction_id, fd.seller_id, 
                       fd.platform_share, fd.seller_share, u.bank_account_number, u.paypal_email
                FROM fund_distribution fd
                JOIN users u ON fd.seller_id = u.id
                JOIN orders o ON fd.invoice_id = o.invoice_id
                WHERE fd.status = 'Pending' AND o.shipping_status = 'Delivered'
            """)
            pending_distributions = cursor.fetchall()

            if not pending_distributions:
                print("✅ [DEBUG] No pending fund distributions for delivered orders found.")
                return

            for distribution in pending_distributions:
                fund_id, invoice_id, auction_id, seller_id, platform_share, seller_share, bank_account, paypal_email = distribution

                try:
                    # Fetch payment_date from the payment_details table for the corresponding invoice
                    cursor.execute("""
                        SELECT payment_date FROM payment_details WHERE invoice_id = %s
                    """, [invoice_id])
                    payment_data = cursor.fetchone()

                    if not payment_data:
                        print(f"❌ [ERROR] No payment data found for Invoice ID {invoice_id}. Skipping fund distribution.")
                        continue

                    payment_date = payment_data[0]

                    # Make payment_date aware if it is naive
                    if timezone.is_naive(payment_date):
                        from django.utils.timezone import make_aware
                        payment_date = make_aware(payment_date)

                    # Check if 1 hour has passed since the payment date (adjust as needed)
                    if payment_date + timedelta(minutes=1) > timezone.now():
                        print(f"⏳ [DEBUG] Payment for Invoice {invoice_id} is less than 1 hour old. Delaying fund distribution.")
                        continue  # Skip this fund distribution, it will be checked in the next run.

                    # Proceed with fund distribution after 1 hour
                    with transaction.atomic():  # Ensure atomicity
                        # Check seller's payout method
                        if bank_account:
                            payment_method = f"Bank Transfer to {bank_account}"
                            credited_to = f"bank account ending in {bank_account[-4:]}"
                        elif paypal_email:
                            payment_method = f"PayPal Transfer to {paypal_email}"
                            credited_to = f"PayPal account ({paypal_email})"
                        else:
                            print(f"❌ [ERROR] No payout method found for Seller ID {seller_id}. Skipping transfer.")
                            continue

                        # Generate a transaction ID
                        transaction_id = f"TXN-{uuid.uuid4().hex[:10].upper()}"

                        # Mark the fund distribution as transferred
                        cursor.execute("""
                            UPDATE fund_distribution 
                            SET status = 'Transferred', distribution_date = NOW() 
                            WHERE id = %s
                        """, [fund_id])

                        # Store payout record
                        cursor.execute("""
                            INSERT INTO seller_payouts (seller_id, auction_id, invoice_id, payout_amount, payout_method, transaction_id, payout_status, payout_date)
                            VALUES (%s, %s, %s, %s, %s, %s, 'Completed', NOW())
                        """, (seller_id, auction_id, invoice_id, seller_share, payment_method, transaction_id))

                        print(f"✅ [DEBUG] Fund transferred for Auction {auction_id} using {payment_method}")

                        # Fetch seller's email
                        cursor.execute("SELECT email FROM users WHERE id = %s", [seller_id])
                        seller_email_data = cursor.fetchone()
                        seller_email = seller_email_data[0] if seller_email_data else None

                        # Fetch platform admin email from settings
                        platform_email = settings.DEFAULT_FROM_EMAIL

                        # Notify the seller via in-app notification and email
                        if seller_email:
                            seller_message = (
                                f"Your funds for Auction ID {auction_id} have been credited to your {credited_to}.\n"
                                f"Amount Credited: ₹{seller_share:.2f}\n"
                                f"Platform Commission: ₹{platform_share:.2f}\n"
                                f"Transaction ID: {transaction_id}\n"
                                f"Payment Method: {payment_method}\n"
                                f"Date: {timezone.now().strftime('%B %d, %Y %H:%M:%S')}"
                            )
                            notify_user(seller_id, seller_email, seller_message, subject="Funds Credited for Your Auction")
                            print(f"✅ [DEBUG] Email sent to seller {seller_id} ({seller_email})")

                        # Notify the platform admin
                        admin_message = (
                            f"Fund distribution processed for Auction ID: {auction_id}.\n"
                            f"Seller's Share: ₹{seller_share:.2f}\n"
                            f"Platform Commission: ₹{platform_share:.2f}\n"
                            f"Seller ID: {seller_id}\n"
                            f"Payment Method: {payment_method}\n"
                            f"Transaction ID: {transaction_id}"
                        )
                        send_mail("Fund Distribution Processed", admin_message, platform_email, [platform_email])
                        print("✅ [DEBUG] Fund distribution email sent to platform admin.")

                except Exception as e:
                    print(f"❌ [ERROR] Failed to process fund distribution for Auction {auction_id}: {str(e)}")

    except Exception as e:
        print(f"❌ [ERROR] Error in processing fund distributions: {str(e)}")

def send_invoice_due_reminders():
    """
    Send email reminders to buyers 1 day before the invoice due date, but only once.
    """
    reminder_date = (datetime.now() + timedelta(days=1)).date()
    print(f"[DEBUG] Checking for invoices due on: {reminder_date}")

    try:
        with connection.cursor() as cursor:
            # Fetch pending invoices due tomorrow that haven't received a reminder
            query = """
                SELECT id, auction_id, amount_due, due_date, buyer_id 
                FROM invoices
                WHERE status = 'Pending' AND DATE(due_date) = %s AND reminder_sent = 0
            """
            cursor.execute(query, [reminder_date])
            pending_invoices = cursor.fetchall()

            print(f"[DEBUG] Found {len(pending_invoices)} invoices due tomorrow without reminders sent.")

            if not pending_invoices:
                return  # No invoices to process

            for invoice in pending_invoices:
                invoice_id, auction_id, amount_due, due_date, buyer_id = invoice

                print(f"[DEBUG] Processing Invoice ID: {invoice_id} | Buyer ID: {buyer_id} | Due Date: {due_date}")

                # Fetch buyer's email
                cursor.execute("SELECT email FROM users WHERE id = %s", [buyer_id])
                buyer_email_row = cursor.fetchone()
                buyer_email = buyer_email_row[0] if buyer_email_row else None

                if buyer_email:
                    subject = f"Reminder: Invoice #{invoice_id} Due Tomorrow"
                    message = f"""Dear Buyer,

This is a reminder that your invoice (Invoice ID: {invoice_id}) for Auction #{auction_id}, amounting to ${amount_due:.2f}, is due tomorrow ({due_date.strftime('%Y-%m-%d')}).

If the payment is not completed by the due date, your winning bid may be cancelled, and your account could be restricted, leading to loss of bidding privileges and potential auction relisting.

Please ensure that you complete your payment promptly to avoid these consequences.

Thank you,
AuctionPro Team
"""
                    try:
                        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [buyer_email])
                        print(f"[✅ DEBUG] Invoice due reminder sent to buyer {buyer_id} for Invoice {invoice_id}")

                        # Mark invoice reminder as sent
                        cursor.execute("UPDATE invoices SET reminder_sent = 1 WHERE id = %s", [invoice_id])
                        print(f"[✅ DEBUG] Marked Invoice {invoice_id} as reminder sent.")

                    except Exception as email_error:
                        print(f"[❌ ERROR] Failed to send email to {buyer_email}: {email_error}")
                        logger.error(f"Email error: {email_error}")

                else:
                    print(f"[⚠️ WARNING] Buyer email not found for Buyer ID {buyer_id}")

    except Exception as e:
        print(f"[❌ ERROR] Failed to send invoice due reminders: {str(e)}")
        logger.error(f"Database error: {e}")


def get_user_email(user_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT email FROM users WHERE id = %s", [user_id])
        result = cursor.fetchone()
        return result[0] if result else None


def update_order_shipping_statuses():
    """
    Updates shipping statuses for orders with payment_status 'paid' and specific shipping statuses:
    - 'processing' -> 'Picked Up' (progress 50) after 5 minutes, sets delivery_date if not set.
    - 'picked up' -> 'Shipped' (progress 60) after 5 minutes.
    - 'shipped' -> 'Out for Delivery' (progress 75) after 5 minutes.
    - 'out for delivery' -> 'Delivered' (progress 100) after 5 minutes.

    Only updates orders that either have shipping details in the shipping_details table
    OR a valid shipping_address (not 'n/a') in the orders table.
    Sends an email to the buyer only once per status change.
    Skips orders with shipping_status 'cancelled'.
    """
    now = datetime.now()
    threshold = timedelta(minutes=5)  # Update after 5 minutes

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Initialize shipping_updated_at for all relevant statuses if not set
                cursor.execute("""
                    UPDATE orders
                    SET shipping_updated_at = order_date
                    WHERE LOWER(shipping_status) IN ('processing', 'picked up', 'shipped', 'out for delivery')
                      AND shipping_updated_at IS NULL
                      AND LOWER(payment_status) = 'paid'
                """)
                print(f"Initialized shipping_updated_at for eligible orders, rows affected: {cursor.rowcount}")

                # Fetch orders in the statuses we want to update, with either shipping_details OR valid shipping_address
                cursor.execute("""
                    SELECT order_id, LOWER(shipping_status) AS shipping_status, shipping_updated_at, 
                           user_id, last_notification_status, delivery_date, shipping_address
                    FROM orders
                    WHERE LOWER(shipping_status) IN ('processing', 'picked up', 'shipped', 'out for delivery')
                      AND LOWER(payment_status) = 'paid'
                      AND (
                          EXISTS (SELECT 1 FROM shipping_details sd WHERE sd.order_id = orders.order_id)
                          OR LOWER(shipping_address) != 'n/a'
                      )
                """)
                orders = cursor.fetchall()

                if not orders:
                    print("No orders found to update.")
                    return

                for order in orders:
                    order_id, status, last_update, user_id, last_notif, delivery_date, shipping_address = order

                    # Check why the order qualifies for update (for debugging)
                    has_shipping_details = False
                    cursor.execute("""
                        SELECT 1
                        FROM shipping_details sd
                        WHERE sd.order_id = %s
                    """, [order_id])
                    if cursor.fetchone():
                        has_shipping_details = True

                    has_valid_shipping_address = (shipping_address.lower() != 'n/a') if shipping_address else False
                    qualification_reason = "Qualified because: "
                    if has_shipping_details and has_valid_shipping_address:
                        qualification_reason += "has shipping_details and valid shipping_address"
                    elif has_shipping_details:
                        qualification_reason += "has shipping_details"
                    else:
                        qualification_reason += "has valid shipping_address"

                    # Validate last_update
                    if not last_update:
                        print(f"Order {order_id}: shipping_updated_at is NULL after initialization, skipping.")
                        continue

                    elapsed = now - last_update
                    print(f"Order {order_id}: Status = {status}, Last Update = {last_update}, Elapsed = {elapsed}, "
                          f"Delivery Date = {delivery_date}, Shipping Address = {shipping_address}, {qualification_reason}")

                    update_needed = False
                    new_status = None
                    progress = None
                    email_subject = ""
                    email_body = ""

                    # Transition logic based on current status
                    if status == 'processing' and elapsed >= threshold:
                        new_status = 'Picked Up'
                        progress = 50
                        # Generate a random delivery_date (3 to 7 days from now) if not already set
                        if not delivery_date:
                            delivery_date = now + timedelta(days=random.randint(3, 7))
                            print(f"Order {order_id}: Generated new delivery_date: {delivery_date}")
                        else:
                            print(f"Order {order_id}: Using existing delivery_date: {delivery_date}")
                        email_subject = "Your Order Has Been Picked Up!"
                        email_body = f"Dear Customer,\n\nYour order has been picked up. Estimated delivery date: {delivery_date.strftime('%Y-%m-%d')}."
                        update_needed = True

                    elif status == 'picked up' and elapsed >= threshold:
                        new_status = 'Shipped'
                        progress = 60
                        # Ensure delivery_date is set
                        if not delivery_date:
                            delivery_date = now + timedelta(days=random.randint(3, 7))
                            print(f"Order {order_id}: Generated new delivery_date for 'Shipped': {delivery_date}")
                        email_subject = "Your Order Has Shipped!"
                        email_body = f"Dear Customer,\n\nYour order has been shipped. Estimated delivery date: {delivery_date.strftime('%Y-%m-%d')}."
                        update_needed = True

                    elif status == 'shipped' and elapsed >= threshold:
                        new_status = 'Out for Delivery'
                        progress = 75
                        email_subject = "Your Order is Out for Delivery!"
                        email_body = "Dear Customer,\n\nYour order is now out for delivery and will reach you soon."
                        update_needed = True

                    elif status == 'out for delivery' and elapsed >= threshold:
                        new_status = 'Delivered'
                        progress = 100
                        email_subject = "Your Order Has Been Delivered!"
                        email_body = "Dear Customer,\n\nWe are happy to inform you that your order has been delivered."
                        update_needed = True
                    else:
                        print(f"Order {order_id}: No update required (status: {status}, elapsed: {elapsed}).")
                        continue

                    if update_needed:
                        try:
                            # Update the order
                            if status in ['processing', 'picked up']:
                                # Update delivery_date if needed
                                cursor.execute("""
                                    UPDATE orders
                                    SET shipping_status = %s,
                                        progress = %s,
                                        shipping_updated_at = %s,
                                        delivery_date = %s
                                    WHERE order_id = %s
                                """, [new_status, progress, now, delivery_date, order_id])
                            else:
                                cursor.execute("""
                                    UPDATE orders
                                    SET shipping_status = %s,
                                        progress = %s,
                                        shipping_updated_at = %s
                                    WHERE order_id = %s
                                """, [new_status, progress, now, order_id])
                            print(f"Order {order_id} updated to {new_status} with progress {progress}. Rows affected: {cursor.rowcount}")

                            # Send email only if we haven't already notified for this new status
                            last_notif = last_notif if last_notif else ''
                            if last_notif != new_status:
                                buyer_email = get_user_email(user_id)
                                if buyer_email:
                                    try:
                                        send_mail(
                                            email_subject,
                                            email_body,
                                            settings.DEFAULT_FROM_EMAIL,
                                            [buyer_email],
                                            fail_silently=False
                                        )
                                        # Update last_notification_status to new_status
                                        cursor.execute("""
                                            UPDATE orders
                                            SET last_notification_status = %s
                                            WHERE order_id = %s
                                        """, [new_status, order_id])
                                        print(f"Email sent for Order {order_id} status change to {new_status}.")
                                    except Exception as e:
                                        print(f"Failed to send email for Order {order_id}: {e}")
                                else:
                                    print(f"Order {order_id}: No email found for user_id {user_id}.")
                            else:
                                print(f"Order {order_id}: Notification already sent for status {new_status}.")
                        except Exception as e:
                            print(f"Error updating Order {order_id}: {e}")
                            continue

    except Exception as e:
        print(f"Error in update_order_shipping_statuses: {e}")
        raise

    print("✅ Order shipping statuses updated successfully.")

def expire_old_offers():
    """
    Expires offers based on their status:
    - Pending offers older than 10 minutes are set to 'expired'.
    - Accepted offers older than 1 hour are set to 'expired'.
    For each expired offer, sends notifications:
      - Buyer: "Your offer for auction ID {auction_id} has expired as it is older than [10 minutes/1 hour]. Please submit a new offer."
      - Seller: "An offer on auction ID {auction_id} has expired as it is older than [10 minutes/1 hour]."
    """
    current_time = timezone.now()
    # Convert current time to naive datetime if it's aware (assuming DB stores naive UTC datetimes)
    current_time_naive = timezone.make_naive(current_time) if timezone.is_aware(current_time) else current_time
    pending_expiration_threshold = current_time_naive - timedelta(minutes=10)  # 10 minutes for pending
    accepted_expiration_threshold = current_time_naive - timedelta(hours=1)    # 1 hour for accepted

    logger.debug(f"expire_old_offers - Current time (naive): {current_time_naive}")
    logger.debug(f"expire_old_offers - Pending expiration threshold (10 minutes ago): {pending_expiration_threshold}")
    logger.debug(f"expire_old_offers - Accepted expiration threshold (1 hour ago): {accepted_expiration_threshold}")

    try:
        with connection.cursor() as cursor:
            # Update pending offers older than 10 minutes and accepted offers older than 1 hour to 'expired'
            cursor.execute("""
                UPDATE offers
                SET status = 'expired'
                WHERE (
                    (status = 'pending' AND created_at < %s) OR
                    (status = 'accepted' AND created_at < %s)
                ) AND status != 'expired'
            """, [pending_expiration_threshold, accepted_expiration_threshold])
            expired_count = cursor.rowcount
            logger.info(f"expire_old_offers - Expired {expired_count} offers (pending > 10 min, accepted > 1 hr).")

            # Fetch details of expired offers for sending notifications
            cursor.execute("""
                SELECT o.id, o.auction_id, o.buyer_id, u_b.email AS buyer_email, 
                       a.user_id AS seller_id, u_s.email AS seller_email, o.status
                FROM offers o
                JOIN auctions a ON o.auction_id = a.id
                JOIN users u_b ON o.buyer_id = u_b.id
                JOIN users u_s ON a.user_id = u_s.id
                WHERE o.status = 'expired' 
                AND (
                    (o.status = 'pending' AND o.created_at < %s) OR
                    (o.status = 'accepted' AND o.created_at < %s)
                )
            """, [pending_expiration_threshold, accepted_expiration_threshold])
            expired_offers = cursor.fetchall()

            for offer in expired_offers:
                offer_id, auction_id, buyer_id, buyer_email, seller_id, seller_email, status = offer
                # Determine expiration duration based on the original status
                expiration_duration = "10 minutes" if status == 'pending' else "1 hour"
                buyer_message = (
                    f"Your offer for auction ID {auction_id} has expired as it is older than {expiration_duration}. "
                    "Please submit a new offer."
                )
                seller_message = (
                    f"An offer on auction ID {auction_id} has expired as it is older than {expiration_duration}."
                )
                logger.debug(f"expire_old_offers - Notifying for expired offer {offer_id} (original status: {status})")

                if buyer_email:
                    notify_user(buyer_id, buyer_email, buyer_message, subject="Offer Expired")
                    logger.debug(f"expire_old_offers - Notified buyer {buyer_id} ({buyer_email}) for offer {offer_id}")
                else:
                    logger.warning(f"expire_old_offers - No email found for buyer {buyer_id} of offer {offer_id}")

                if seller_email:
                    notify_user(seller_id, seller_email, seller_message, subject="Offer Expired")
                    logger.debug(f"expire_old_offers - Notified seller {seller_id} ({seller_email}) for offer {offer_id}")
                else:
                    logger.warning(f"expire_old_offers - No email found for seller {seller_id} of offer {offer_id}")

    except Exception as e:
        logger.error(f"expire_old_offers - Exception while expiring offers: {str(e)}")


def handle_overdue_invoices():
    """
    Scheduled task to process overdue invoices for auctions with non-paying winners.
    For each overdue invoice (status 'Overdue', due_date < now, and reminder_sent = 0):
      - Restrict the defaulter's bidding rights and notify them once.
      - Look for the second highest bidder.
      - If found, and no pending offer exists for that bidder on the auction, and the
        second highest bid is greater than the reserve price, insert a pending offer with
        the message:
          "You have been selected as the winner for auction ID {auction_id} due to non-payment by the previous winner. Do you accept this offer?"
        The new offer is flagged as a second winner offer so that it is only visible to that buyer.
      - Notify the new (second highest) bidder via email and in-app notification.
      - Notify the seller that a pending offer has been sent.
      - If no second bidder is found, notify the seller to relist the auction (only once).
      - Mark the invoice as notified (reminder_sent = 1) so this process is run only once.
    """
    current_time = timezone.now()
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Select overdue invoices (that haven't been processed yet)
                cursor.execute("""
                    SELECT id, auction_id, buyer_id
                    FROM invoices
                    WHERE status = 'Overdue'
                      AND due_date < %s
                      AND reminder_sent = 0
                """, [current_time])
                overdue_invoices = cursor.fetchall()
                logger.debug(f"handle_overdue_invoices - Found overdue invoices: {overdue_invoices}")

                if not overdue_invoices:
                    logger.info("handle_overdue_invoices - No overdue invoices found")
                    return

                for invoice in overdue_invoices:
                    invoice_id, auction_id, defaulter_id = invoice
                    logger.info(f"Processing Invoice {invoice_id} for Auction {auction_id} (defaulter: {defaulter_id})")

                    # Check if defaulter has already been notified about restriction
                    cursor.execute("SELECT restriction_notified FROM users WHERE id = %s", [defaulter_id])
                    restriction_notified_row = cursor.fetchone()
                    restriction_notified = restriction_notified_row[0] if restriction_notified_row else 0

                    # Restrict the defaulter's bidding rights
                    cursor.execute("""
                        UPDATE users
                        SET bidding_restricted = 1, restriction_notified = 1
                        WHERE id = %s AND restriction_notified = 0
                    """, [defaulter_id])
                    if cursor.rowcount > 0:  # Only notify if restriction was applied
                        cursor.execute("SELECT email FROM users WHERE id = %s", [defaulter_id])
                        defaulter_email_row = cursor.fetchone()
                        defaulter_email = defaulter_email_row[0] if defaulter_email_row else None
                        if defaulter_email:
                            restriction_msg = (
                                f"Your bidding rights have been restricted due to non-payment of an invoice for auction ID {auction_id}. "
                                "For further information, please contact the admin."
                            )
                            notify_user(defaulter_id, defaulter_email, restriction_msg, subject="Bidding Rights Restricted")
                            logger.info(f"handle_overdue_invoices - Notified defaulter {defaulter_id} about bidding restriction.")
                        else:
                            logger.warning(f"handle_overdue_invoices - Email not found for defaulter {defaulter_id}.")
                    logger.info(f"handle_overdue_invoices - Restricted defaulter {defaulter_id}")

                    # Identify the second highest bidder (using OFFSET 1)
                    cursor.execute("""
                        SELECT user_id, amount
                        FROM bids
                        WHERE auction_id = %s
                        ORDER BY amount DESC
                        LIMIT 1 OFFSET 1
                    """, [auction_id])
                    second_bidder = cursor.fetchone()
                    if not second_bidder:
                        # Check if seller has already been notified about relisting
                        cursor.execute("SELECT relist_notified, user_id FROM auctions WHERE id = %s", [auction_id])
                        relist_info = cursor.fetchone()
                        relist_notified, seller_id = relist_info[0], relist_info[1] if relist_info else (0, None)
                        if relist_notified:
                            logger.info(f"handle_overdue_invoices - Seller already notified for relisting auction {auction_id}.")
                        elif seller_id:
                            cursor.execute("SELECT email FROM users WHERE id = %s", [seller_id])
                            seller_email_row = cursor.fetchone()
                            seller_email = seller_email_row[0] if seller_email_row else None
                            if seller_email:
                                relist_msg = (
                                    f"No second bidder was found for auction ID {auction_id}. "
                                    "Please consider relisting the auction."
                                )
                                notify_user(seller_id, seller_email, relist_msg, subject="Auction Relist Required")
                                logger.info(f"handle_overdue_invoices - Notified seller {seller_id} to relist auction {auction_id}.")
                                # Mark auction as relist notified
                                cursor.execute("""
                                    UPDATE auctions
                                    SET relist_notified = 1
                                    WHERE id = %s
                                """, [auction_id])
                            else:
                                logger.warning(f"handle_overdue_invoices - Seller email not found for auction {auction_id}.")
                        else:
                            logger.warning(f"handle_overdue_invoices - Seller not found for auction {auction_id}.")
                        # Mark invoice as processed even if no second bidder
                        cursor.execute("""
                            UPDATE invoices
                            SET reminder_sent = 1
                            WHERE id = %s
                        """, [invoice_id])
                        logger.info(f"handle_overdue_invoices - Marked invoice {invoice_id} as notified.")
                        continue

                    new_bidder_id, new_bid_amount = second_bidder
                    logger.info(f"handle_overdue_invoices - Second highest bidder for auction {auction_id} is {new_bidder_id} with bid {new_bid_amount}")

                    # Check if reserve price condition is met
                    cursor.execute("SELECT reserve_price FROM auctions WHERE id = %s", [auction_id])
                    reserve_row = cursor.fetchone()
                    if reserve_row:
                        reserve_price = reserve_row[0]
                        logger.info(f"handle_overdue_invoices - Reserve price for auction {auction_id} is {reserve_price}")
                        if new_bid_amount < reserve_price:
                            logger.info(f"handle_overdue_invoices - Second highest bid {new_bid_amount} is less than reserve price {reserve_price}. Not sending offer.")
                            # Mark invoice as processed
                            cursor.execute("""
                                UPDATE invoices
                                SET reminder_sent = 1
                                WHERE id = %s
                            """, [invoice_id])
                            logger.info(f"handle_overdue_invoices - Marked invoice {invoice_id} as notified.")
                            continue

                    # Check if a pending offer already exists for this auction and the new bidder
                    cursor.execute("""
                        SELECT id FROM offers
                        WHERE auction_id = %s AND buyer_id = %s AND status = 'pending'
                    """, [auction_id, new_bidder_id])
                    existing_offer = cursor.fetchone()
                    if existing_offer:
                        logger.info(f"handle_overdue_invoices - Pending offer already exists for auction {auction_id} and buyer {new_bidder_id}.")
                    else:
                        # Insert a new pending offer for the second highest bidder
                        offer_message = (
                            f"You have been selected as the winner for auction ID {auction_id} due to non-payment by the previous winner. "
                            "Do you accept this offer?"
                        )
                        cursor.execute("""
                            INSERT INTO offers (auction_id, buyer_id, offer_price, offer_message, status, created_at, second_winner_offer)
                            VALUES (%s, %s, %s, %s, 'pending', %s, TRUE)
                        """, [auction_id, new_bidder_id, new_bid_amount, offer_message, current_time])
                        logger.info(f"handle_overdue_invoices - Inserted pending offer for auction {auction_id} for buyer {new_bidder_id} flagged as second winner offer.")

                        # Notify the new bidder
                        cursor.execute("SELECT email FROM users WHERE id = %s", [new_bidder_id])
                        buyer_email_row = cursor.fetchone()
                        new_bidder_email = buyer_email_row[0] if buyer_email_row else None
                        if new_bidder_email:
                            buyer_notification_msg = (
                                f"Congratulations! You have been selected as the potential winner for auction ID {auction_id} "
                                "due to non-payment by the previous winner. Please log in and confirm or reject this offer."
                            )
                            notify_user(new_bidder_id, new_bidder_email, buyer_notification_msg, subject="New Auction Winner Offer")
                            logger.info(f"handle_overdue_invoices - Notified new bidder {new_bidder_id} via email/in-app.")
                        else:
                            logger.warning(f"handle_overdue_invoices - Email not found for buyer {new_bidder_id}.")

                        # Notify the seller that a pending offer has been sent
                        cursor.execute("SELECT user_id FROM auctions WHERE id = %s", [auction_id])
                        seller_id_row = cursor.fetchone()
                        seller_id = seller_id_row[0] if seller_id_row else None
                        if seller_id:
                            cursor.execute("SELECT email FROM users WHERE id = %s", [seller_id])
                            seller_email_row = cursor.fetchone()
                            seller_email = seller_email_row[0] if seller_email_row else None
                            if seller_email:
                                seller_notification_msg = (
                                    f"A pending offer has been sent to the second highest bidder for auction ID {auction_id}. "
                                    "Please wait for their response. If they reject the offer, you will be notified to relist the auction."
                                )
                                notify_user(seller_id, seller_email, seller_notification_msg, subject="Auction Offer Reassignment")
                                logger.info(f"handle_overdue_invoices - Notified seller {seller_id} for auction {auction_id}.")
                            else:
                                logger.warning(f"handle_overdue_invoices - Seller email not found for auction {auction_id}.")
                        else:
                            logger.warning(f"handle_overdue_invoices - Seller not found for auction {auction_id}.")

                    # Mark the invoice as processed
                    cursor.execute("""
                        UPDATE invoices
                        SET reminder_sent = 1
                        WHERE id = %s
                    """, [invoice_id])
                    logger.info(f"handle_overdue_invoices - Marked invoice {invoice_id} as notified.")

    except Exception as e:
        logger.error(f"handle_overdue_invoices - Error processing overdue invoices: {str(e)}")

# Global stop flag
stop_scheduler = threading.Event()  # Flag to stop the scheduler
global_stop_flag = True  # Global flag to stop all tasks

# Control flags for individual tasks
task_flags = {
    "select_regular_auction_winners": True,
    "select_sealed_bid_winners": True,
    "notify_new_auctions": False,
    "remove_expired_premium_users": False,
    "notify_premium_expiry_soon": False,
    "generate_invoices": True,
    "update_overdue_invoices": True,
    "send_winner_selection_reminders": False,
    "send_invoice_due_reminders": False,
    "process_fund_distributions": False,
    "update_order_shipping_statuses": True,
    "expire_old_offers":False,
    "handle_overdue_invoices":True
}

# Task function mappings
TASK_FUNCTIONS = {
    "select_regular_auction_winners": select_regular_auction_winners,
    "select_sealed_bid_winners": select_sealed_bid_winners,
    "notify_new_auctions": notify_new_auctions,
    "remove_expired_premium_users": remove_expired_premium_users,
    "notify_premium_expiry_soon": notify_premium_expiry_soon,
    "generate_invoices": generate_invoices,
    "update_overdue_invoices": update_overdue_invoices,
    "send_winner_selection_reminders": send_winner_selection_reminders,
    "send_invoice_due_reminders": send_invoice_due_reminders,
    "process_fund_distributions": process_fund_distributions,
    "update_order_shipping_statuses": update_order_shipping_statuses,
    "expire_old_offers":expire_old_offers,
    "handle_overdue_invoices":handle_overdue_invoices
}


def run_scheduler():
    """
    Runs the scheduler in an infinite loop, executing enabled tasks sequentially.
    Stops immediately when global_stop_flag is set to True.
    """
    global global_stop_flag
    logger.info("🚀 Scheduler started!")

    cycle_delay = 10  # Scheduler cycle delay in seconds

    while not global_stop_flag:
        logger.info(f"🔄 Scheduler cycle started at {datetime.now()}")

        # Execute enabled tasks sequentially
        for task_name, task_func in TASK_FUNCTIONS.items():
            if global_stop_flag:  # Check stop flag before running any task
                logger.info("🛑 Stopping scheduler immediately.")
                return

            if task_flags[task_name]:  # Only execute enabled tasks
                try:
                    logger.info(f"▶ Running task: {task_name}")
                    task_func()  # Execute task function
                    logger.info(f"✅ Task '{task_name}' completed successfully.")
                except Exception as e:
                    logger.error(f"❌ Error in task '{task_name}': {str(e)}")

        # Wait before starting the next cycle
        logger.info("⏳ Waiting for the next cycle...")
        if stop_scheduler.wait(cycle_delay):
            break  # Stop scheduler immediately if stop signal is received

    logger.info("🛑 Scheduler stopped.")


def stop_scheduler_manually():
    """Stops the entire scheduler immediately, regardless of task flags."""
    global global_stop_flag
    global_stop_flag = True  # Stop the entire scheduler
    stop_scheduler.set()  # Ensure immediate stop
    logger.info("⏹️ Scheduler will stop immediately.")


def toggle_task(task_name, enable=True):
    """Enable or disable a specific task dynamically."""
    if task_name in task_flags:
        task_flags[task_name] = enable
        state = "enabled" if enable else "disabled"
        logger.info(f"🔧 Task '{task_name}' has been {state}.")
    else:
        logger.warning(f"⚠️ Task '{task_name}' not found!")

# To start the scheduler, uncomment the line below:
# run_scheduler()

# Example usage:
# toggle_task("notify_new_auctions", False)  # Stops notifying new auctions
# toggle_task("notify_new_auctions", True)   # Restarts notifying new auctions
# stop_scheduler_manually()  # Stops the entire scheduler globally
