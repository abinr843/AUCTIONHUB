from django.core.cache import cache
cache.clear()  # Clear the cache
from .notifications import create_notification,send_email_notification,notify_user
import traceback
from django.http import HttpResponseBadRequest,HttpResponseForbidden
from django.views.decorators.http import require_POST,require_GET
import os
from django.conf import settings
import logging
from django.http import  Http404,HttpResponse
from django.utils import timezone
from django.utils.timezone import is_naive
import random
from django.core.files.storage import default_storage,FileSystemStorage
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from datetime import  timedelta
import hashlib
from django.db import transaction
from django.contrib.humanize.templatetags.humanize import naturaltime
from collections import defaultdict
import json
import re
import base64
import uuid
from urllib.parse import urlparse
from datetime import datetime, date, time
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection,DatabaseError
from django.utils.timezone import now, make_aware
from django.shortcuts import render, redirect
from django.contrib import messages
from uuid import uuid4
from decimal import Decimal
import csv
from .chatbot import Chatbot
import string
# Create a logger instance
logger = logging.getLogger(__name__)


def home(request):
    # Check if the user is logged in
    user_id = request.session.get('user_id')
    username = request.session.get('username')
    is_authenticated = False

    if user_id:
        # Fetch user authentication status from the database
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_authenticated, username FROM users WHERE id = %s",
                [user_id]
            )
            user_data = cursor.fetchone()

        if user_data:
            is_authenticated, db_username = user_data
            # Update username if not set in session
            username = username or db_username
        else:
            # User not found; clear session to prevent stale data
            request.session.flush()
            is_authenticated = False
            username = None

    # Define the query to fetch auction data
    auctions_query = """
        SELECT id, title, description, start_date, end_date, auction_type
        FROM auctions
        ORDER BY start_date DESC
    """

    # Execute the auction query
    with connection.cursor() as cursor:
        cursor.execute(auctions_query)
        auctions = cursor.fetchall()

    # Transform auction results into dictionaries
    auction_list = []
    for auction in auctions:
        auction_dict = {
            'id': auction[0],
            'title': auction[1],
            'description': auction[2],
            'start_date': auction[3],
            'end_date': auction[4],
            'auction_type': auction[5],
        }
        auction_list.append(auction_dict)

    # Prepare context
    context = {
        'user_id': user_id,
        'username': username,
        'is_authenticated': is_authenticated,
        'auctions': auction_list,
        'now': datetime.now(),
    }

    # Render the home template with context
    return render(request, 'home.html', context)
def banned_page(request):
    return render(request, 'banned.html', {'message': 'You have been banned by the admin.'})

def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def bidding_restricted(request):
    return render(request, 'bidding_restricted.html')

def about(request):
    # Check if the user is authenticated based on session
    is_authenticated = request.user.is_authenticated
    user = request.user if is_authenticated else None
    context = {
        'is_authenticated': is_authenticated,
        'user': user,
    }
    return render(request, 'about.html', context)

def terms_conditions(request):
    return render(request, 'terms_conditions.html')
def auth_page(request):
    return render(request, 'auth_page.html')  # Render the combined template

@require_GET
def adash(request):
    # Ensure only admins can access this view
    if request.session.get('role') != 'admin':
        return redirect('/')  # Redirect non-admins to the homepage

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with connection.cursor() as cursor:
        # Fetch total number of users
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        # Fetch total active auctions
        cursor.execute("""
            SELECT COUNT(*) FROM auctions 
            WHERE start_date <= %s AND end_date >= %s AND status = 'active'
        """, [current_time, current_time])
        active_auctions = cursor.fetchone()[0]

    # Fetch new questions count for context
    new_questions_count = 0
    try:
        new_questions_file = os.path.join(os.path.dirname(__file__), 'new_questions.json')
        with open(new_questions_file, 'r', encoding='utf-8') as f:
            new_questions = json.load(f)
        new_questions_count = len([q for q in new_questions['questions'] if not q.get('answered', False)])
    except Exception as e:
        print(f"Error loading new questions: {e}")

    # AJAX request for chart data
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        with connection.cursor() as cursor:
            # Auction trend data (last 6 months based on start_date)
            auction_trend = {'labels': [], 'data': []}
            for i in range(5, -1, -1):  # Last 6 months, including current
                month_start = (datetime.now().replace(day=1) - timedelta(days=i*30)).strftime('%Y-%m-01 00:00:00')
                month_end = (datetime.now().replace(day=1) - timedelta(days=(i-1)*30)).strftime('%Y-%m-01 00:00:00')
                cursor.execute("""
                    SELECT COUNT(*) FROM auctions 
                    WHERE start_date >= %s AND start_date < %s
                """, [month_start, month_end])
                count = cursor.fetchone()[0]
                auction_trend['labels'].append((datetime.now().replace(day=1) - timedelta(days=i*30)).strftime('%b'))
                auction_trend['data'].append(count)

            # User distribution data
            cursor.execute("""
                SELECT role, COUNT(*) FROM users 
                GROUP BY role
            """)
            user_dist_raw = cursor.fetchall()
            user_dist = {'labels': [], 'data': []}
            role_map = {'buyer': 'Buyers', 'seller': 'Sellers', 'admin': 'Admins', 'guest': 'Guests'}
            for role, count in user_dist_raw:
                label = role_map.get(role, role.capitalize())
                user_dist['labels'].append(label)
                user_dist['data'].append(count)
            for role, label in role_map.items():
                if label not in user_dist['labels']:
                    user_dist['labels'].append(label)
                    user_dist['data'].append(0)

        return JsonResponse({
            'total_users': total_users,
            'active_auctions': active_auctions,
            'auction_trend': auction_trend,
            'user_distribution': user_dist
        })

    context = {
        'total_users': total_users,
        'active_auctions': active_auctions,
        'pending_disputes': 0,  # Hardcoded since disputes table doesn’t exist
        'new_questions_count': new_questions_count  # Add count of new questions
    }
    return render(request, 'adash.html', context)
def signup(request):
    if request.method == "POST":
        username = request.POST.get('username')
        email = request.POST.get('email', '')
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return render(request, "auth_page.html")

        with connection.cursor() as cursor:
            # Check if username or email already exists
            cursor.execute("SELECT id FROM users WHERE username = %s", [username])
            if cursor.fetchone():
                messages.error(request, "Username already exists!")
                return render(request, "auth_page.html")

            cursor.execute("SELECT id FROM users WHERE email = %s", [email])
            if cursor.fetchone():
                messages.error(request, "Email is already registered! Please log in or use a different email.")
                return render(request, "auth_page.html")

        # Generate a random salt and hash the password
        salt = get_random_string(12)
        hashed_password = hashlib.sha256((password + salt).encode()).hexdigest()
        role = "user"  # Default role

        try:
            with connection.cursor() as cursor:
                # Insert user into the database
                cursor.execute("""
                    INSERT INTO users (username, email, password_hash, salt, created_at, role, email_verified, premium)
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s)
                """, [username, email, hashed_password, salt, role, 0, 0])
                connection.commit()

                # Fetch the newly created user ID
                cursor.execute("SELECT LAST_INSERT_ID()")
                user_id = cursor.fetchone()[0]

                # ✅ Store email in session for OTP verification
                request.session['email'] = email

                # Generate OTP
                otp = random.randint(100000, 999999)

                # Store OTP in the database with a 5-minute expiration
                cursor.execute("""
                    INSERT INTO user_otp (user_id, otp, created_at, expires_at)
                    VALUES (%s, %s, NOW(), NOW() + INTERVAL 5 MINUTE)
                """, [user_id, otp])
                connection.commit()

            # Send OTP email
            subject = "Email Verification"
            message = f"Your OTP for email verification is {otp}. This OTP will expire in 5 minutes."
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

            messages.success(request, "Account created successfully! Please verify your email.")
            return redirect('otp_verify')  # Redirect to OTP verification page

        except Exception as e:
            logger.error(f"Error during signup: {e}")
            messages.error(request, "An error occurred. Please try again.")

    return render(request, "auth_page.html")
def otp_verify(request):
    # Retrieve email from session
    email = request.session.get('email')

    if not email:
        messages.error(request, "Session expired. Please sign up or log in again!")
        return redirect('login')  # Redirect to login if session expired

    if request.method == "POST":
        otp = request.POST.get('otp', '').strip()

        if not otp.isdigit():
            messages.error(request, "Invalid OTP format. Please enter a valid numeric OTP.")
            return redirect('otp_verify')

        # Check if OTP is valid and not expired
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT user_id FROM user_otp 
                WHERE user_id = (SELECT id FROM users WHERE email = %s) 
                AND otp = %s 
                AND expires_at > NOW()
            """, [email, otp])
            valid_otp = cursor.fetchone()

            if valid_otp:
                try:
                    # Mark email as verified
                    cursor.execute("""
                        UPDATE users SET email_verified = 1 WHERE email = %s
                    """, [email])

                    if cursor.rowcount > 0:
                        # Delete OTP after successful verification
                        cursor.execute("""
                            DELETE FROM user_otp WHERE user_id = (SELECT id FROM users WHERE email = %s)
                        """, [email])
                        messages.success(request, "Email verified successfully!")

                        # Store user in session after successful verification
                        cursor.execute("SELECT id, username FROM users WHERE email = %s", [email])
                        user_data = cursor.fetchone()

                        if user_data:
                            request.session['user_id'] = user_data[0]
                            request.session['username'] = user_data[1]

                    else:
                        messages.error(request, "Email verification failed. Please try again.")

                except Exception as e:
                    logger.error(f"Error during email verification: {e}")
                    messages.error(request, "An error occurred during email verification.")

                return redirect('login')  # Redirect to user dashboard after successful verification
            else:
                messages.error(request, "Invalid or expired OTP. Please try again.")

    messages.info(request, "Please check your email for OTP verification.")
    return render(request, 'otp_verify.html')
def generate_otp(length=6):
    """Generate a random OTP of specified length."""
    return ''.join(random.choices(string.digits, k=length))

@csrf_exempt
def check_otp_status(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            email = data.get('email')
            if not email:
                return JsonResponse({'success': False, 'message': 'Email is required.'}, status=400)

            # Check if user exists
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION time_zone = '+05:30'")
                cursor.execute(
                    "SELECT id, email_verified, created_at FROM users WHERE email = %s",
                    [email]
                )
                user = cursor.fetchone()
                if not user:
                    return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

                user_id, email_verified, user_created_at = user
                if timezone.is_naive(user_created_at):
                    user_created_at = timezone.make_aware(user_created_at, timezone.get_default_timezone())
                logger.info(f"User {email}: email_verified={email_verified}, created_at={user_created_at}")

                if email_verified:
                    return JsonResponse({
                        'success': True,
                        'has_valid_otp': False,
                        'email_verified': True,
                        'can_request_new_otp': False,
                        'message': 'Email already verified.'
                    })

                # Check for valid OTP
                current_time = timezone.now()
                cursor.execute(
                    """
                    SELECT created_at, expires_at FROM user_otp
                    WHERE user_id = %s AND expires_at > %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    [user_id, current_time]
                )
                otp_result = cursor.fetchone()
                has_valid_otp = bool(otp_result)
                can_request_new_otp = True
                otp_message = 'No valid OTP found. Request a new one.'

                if has_valid_otp:
                    otp_created_at, otp_expires_at = otp_result
                    if timezone.is_naive(otp_created_at):
                        otp_created_at = timezone.make_aware(otp_created_at, timezone.get_default_timezone())
                    if timezone.is_naive(otp_expires_at):
                        otp_expires_at = timezone.make_aware(otp_expires_at, timezone.get_default_timezone())
                    logger.info(f"OTP for {email}: created_at={otp_created_at}, expires_at={otp_expires_at}")
                    time_diff = (current_time - otp_created_at).total_seconds() / 60  # Time since OTP creation
                    logger.info(f"Time diff for {email} since OTP creation: {time_diff} minutes")

                    if time_diff <= 5:
                        can_request_new_otp = False
                        otp_message = 'Give already received OTP or request a new OTP after 5 minutes.'
                    else:
                        can_request_new_otp = True
                        otp_message = 'The previous OTP has expired. Request a new one.'

            return JsonResponse({
                'success': True,
                'has_valid_otp': has_valid_otp,
                'email_verified': False,
                'can_request_new_otp': can_request_new_otp,
                'message': otp_message
            })

        except Exception as e:
            logger.error(f"Error in check_otp_status: {str(e)}")
            return JsonResponse({'success': False, 'message': 'An error occurred. Please try again.'}, status=500)

    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)

@csrf_exempt
def resend_otp(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            email = data.get('email')
            if not email:
                return JsonResponse({'success': False, 'message': 'Email is required.'}, status=400)

            # Check if user exists
            with connection.cursor() as cursor:
                # Set session timezone to match application and system
                cursor.execute("SET SESSION time_zone = '+05:30'")
                cursor.execute(
                    "SELECT id, email_verified, created_at FROM users WHERE email = %s",
                    [email]
                )
                user = cursor.fetchone()
                if not user:
                    return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

                user_id, email_verified, user_created_at = user
                if timezone.is_naive(user_created_at):
                    user_created_at = timezone.make_aware(user_created_at, timezone.get_default_timezone())
                logger.info(f"Resend OTP for {email}: email_verified={email_verified}, created_at={user_created_at}")

                if email_verified:
                    return JsonResponse({
                        'success': False,
                        'message': 'Email already verified. No OTP needed.'
                    }, status=400)

                # Check for valid OTP
                current_time = timezone.now()
                logger.info(f"Current time at start: {current_time}")
                cursor.execute(
                    """
                    SELECT created_at FROM user_otp
                    WHERE user_id = %s AND expires_at > %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    [user_id, current_time]
                )
                otp_result = cursor.fetchone()
                if otp_result:
                    otp_created_at = otp_result[0]
                    if timezone.is_naive(otp_created_at):
                        otp_created_at = timezone.make_aware(otp_created_at, timezone.get_default_timezone())
                    time_diff = (current_time - otp_created_at).total_seconds() / 60
                    logger.info(f"Existing OTP for {email}: created_at={otp_created_at}, time_diff={time_diff} minutes")

                    if time_diff <= 5:
                        return JsonResponse({
                            'success': False,
                            'message': 'Please use the existing OTP or try again after 5 minutes.'
                        }, status=429)

                # Delete all existing OTPs for the user
                cursor.execute(
                    """
                    DELETE FROM user_otp WHERE user_id = %s
                    """,
                    [user_id]
                )
                logger.info(f"Deleted all OTPs for user_id={user_id}")

                # Generate new OTP
                import random
                new_otp = str(random.randint(100000, 999999))
                expires_at = current_time + timedelta(minutes=10)

                # Use timezone-aware datetime and convert to session timezone
                current_time_local = timezone.localtime(current_time)
                expires_at_local = current_time_local + timedelta(minutes=10)

                # Insert new OTP within a transaction
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO user_otp (user_id, otp, created_at, expires_at)
                            VALUES (%s, %s, %s, %s)
                            """,
                            [user_id, new_otp, current_time_local, expires_at_local]
                        )
                        # Verify the inserted record
                        cursor.execute(
                            """
                            SELECT created_at, expires_at FROM user_otp WHERE id = LAST_INSERT_ID()
                            """
                        )
                        inserted_created_at, inserted_expires_at = cursor.fetchone()
                        # Ensure inserted values are aware for comparison
                        if timezone.is_naive(inserted_created_at):
                            inserted_created_at = timezone.make_aware(inserted_created_at,
                                                                      timezone.get_default_timezone())
                        if timezone.is_naive(inserted_expires_at):
                            inserted_expires_at = timezone.make_aware(inserted_expires_at,
                                                                      timezone.get_default_timezone())
                        if inserted_created_at != current_time_local:
                            logger.warning(
                                f"Inserted created_at {inserted_created_at} does not match intended {current_time_local}")
                        logger.info(
                            f"Verified inserted OTP: created_at={inserted_created_at}, expires_at={inserted_expires_at}")

                logger.info(
                    f"Inserted OTP for user_id={user_id}: otp={new_otp}, created_at={current_time_local}, expires_at={expires_at_local}")

                # Send OTP via email
                subject = 'Your OTP for Email Verification'
                message = f'Your OTP is {new_otp}. It will expire at {expires_at_local.strftime("%Y-%m-%d %H:%M:%S %Z")}.'
                from_email = settings.DEFAULT_FROM_EMAIL
                recipient_list = [email]

                try:
                    send_mail(subject, message, from_email, recipient_list, fail_silently=False)
                    logger.info(f"OTP email sent to {email} with OTP {new_otp}")
                except Exception as e:
                    logger.error(f"Failed to send OTP email to {email}: {str(e)}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Failed to send OTP email. Please try again.'
                    }, status=500)

                # Commit transaction (handled by atomic context)
                logger.info(f"New OTP generated for {email}: {new_otp}, expires_at={expires_at_local}")

            return JsonResponse({
                'success': True,
                'message': 'A new OTP has been sent to your email.',
                'can_request_new_otp': False
            })

        except Exception as e:
            logger.error(f"Error in resend_otp: {str(e)}")
            return JsonResponse({'success': False, 'message': 'An error occurred. Please try again.'}, status=500)

    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)

@csrf_exempt
def verify_email_profile(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            email = data.get('email')
            otp = data.get('otp')

            logger.info(f"Received verify_email_profile request: email={email}, otp={otp}")

            if not email or not otp:
                return JsonResponse({'success': False, 'message': 'Email and OTP are required.'}, status=400)

            # Check if user exists
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION time_zone = '+05:30'")
                cursor.execute("SELECT id, email_verified FROM users WHERE email = %s", [email])
                user = cursor.fetchone()
                if not user:
                    return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)
                user_id, email_verified = user

                if email_verified:
                    return JsonResponse({'success': True, 'message': 'Email already verified.'})

                # Check for valid OTP
                current_time = timezone.now()
                cursor.execute(
                    """
                    SELECT otp, created_at, expires_at FROM user_otp
                    WHERE user_id = %s AND expires_at > %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    [user_id, current_time]
                )
                otp_record = cursor.fetchone()
                logger.info(f"OTP records for user_id={user_id}: {otp_record}")

                if not otp_record:
                    return JsonResponse({'success': False, 'message': 'No valid OTP found. Please request a new one.'},
                                        status=400)

                stored_otp, created_at, expires_at = otp_record
                if timezone.is_naive(created_at):
                    created_at = timezone.make_aware(created_at, timezone.get_default_timezone())
                if timezone.is_naive(expires_at):
                    expires_at = timezone.make_aware(expires_at, timezone.get_default_timezone())
                # Convert both to local timezone for comparison
                current_time_local = timezone.localtime(current_time)
                expires_at_local = timezone.localtime(expires_at)
                logger.info(
                    f"Comparing OTP: stored={stored_otp}, provided={otp}, created_at={created_at}, expires_at={expires_at_local}, current_time={current_time_local}")

                if expires_at_local < current_time_local:
                    return JsonResponse({'success': False, 'message': 'OTP has expired. Please request a new one.'},
                                        status=400)
                if stored_otp != otp:
                    return JsonResponse({'success': False, 'message': 'Invalid OTP.'}, status=400)

                # OTP is valid, update email_verified
                cursor.execute(
                    "UPDATE users SET email_verified = %s WHERE id = %s",
                    [True, user_id]
                )

                # Delete used OTP
                cursor.execute(
                    "DELETE FROM user_otp WHERE user_id = %s",
                    [user_id]
                )

            return JsonResponse({'success': True, 'message': 'Email verified successfully.'})

        except Exception as e:
            logger.error(f"Error in verify_email_profile: {str(e)}")
            return JsonResponse({'success': False, 'message': 'An error occurred. Please try again.'}, status=500)

    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)
def login(request):
    if request.method == "POST":
        email = request.POST.get('email')
        password = request.POST.get('password')

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, email, password_hash, salt, email_verified, 
                       is_authenticated, bidding_restricted, role, account_status
                FROM users
                WHERE email = %s
            """, [email])
            user = cursor.fetchone()

        if user:
            user_id, db_username, db_email, stored_hash, salt, email_verified, is_authenticated, bidding_restricted, role, account_status = user

            # Check if user is banned
            if account_status == 'banned':
                messages.error(request, "Your account has been banned by the admin.")
                return redirect('banned_page')  # Redirect to banned page

            # Hash the provided password with the stored salt
            hashed_password = hashlib.sha256((password + salt).encode()).hexdigest()

            if hashed_password == stored_hash:
                # Store user data in the session
                request.session['user_id'] = user_id
                request.session['username'] = db_username
                request.session['role'] = role  # Store role in session
                request.session.set_expiry(3600)  # Session expires in 1 hour for security

                # Log the login activity into the user_activity table
                new_activity = "User logged in"
                with connection.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO user_activity (user_id, description)
                        VALUES (%s, %s)
                    """, [user_id, new_activity])

                # Update authentication status in the users table
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE users
                        SET is_authenticated = 1
                        WHERE id = %s
                    """, [user_id])

                logging.info(f"User {db_username} (ID: {user_id}) logged in successfully.")

                # Redirect based on role
                if role == 'admin':
                    return redirect('adash')  # Redirect admin to Admin Dashboard
                else:
                    return redirect('udash')  # Redirect regular users to User Dashboard

            else:
                messages.error(request, "Invalid email or password.")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, 'auth_page.html')



def logout(request):
    # Get the user_id from the session if available.
    user_id = request.session.get('user_id')
    if user_id:
        # Update the is_authenticated field in the users table to indicate the user is logged out.
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE users
                SET is_authenticated = 0
                WHERE id = %s
            """, [user_id])

    request.session.flush()  # Clear the session
    messages.success(request, "Logged out successfully!")
    return redirect('auth_page')  # Redirect to the login page



def fopass(request):
    if request.method == "POST":
        email = request.POST.get('email')

        if not email:
            messages.error(request, "Please provide your email.")
            return render(request, 'fopass.html')

        # Check if the email exists in the database
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s", [email])
            user = cursor.fetchone()

        if user:
            user_id = user[0]

            # Generate a 6-digit OTP
            otp = str(random.randint(100000, 999999))

            # OTP expiry time (5 minutes from now)
            otp_expiry_time = timezone.now() + timedelta(minutes=5)

            # Store the OTP in the user_otp table
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_otp (user_id, otp, created_at, expires_at)
                    VALUES (%s, %s, NOW(), %s)
                """, [user_id, otp, otp_expiry_time])

            # Send OTP via email
            subject = "Password Reset OTP"
            message = f"Your OTP for password reset is {otp}. It is valid for 5 minutes."
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

            messages.success(request, "OTP has been sent to your email.")
            return redirect('repass')  # Redirect to the OTP verification page

        else:
            messages.error(request, "No account found with this email.")
            return render(request, 'fopass.html')

    return render(request, 'fopass.html')



def repass(request):
    if request.method == "POST":
        otp = request.POST.get('otp')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not otp or not new_password or not confirm_password:
            messages.error(request, "All fields are required!")
            return render(request, 'repass.html')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return render(request, 'repass.html')

        # Verify the OTP
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT user_id 
                FROM user_otp 
                WHERE otp = %s AND expires_at > %s
            """, [otp, timezone.now()])
            valid_otp = cursor.fetchone()

        if valid_otp:
            user_id = valid_otp[0]

            # Hash the new password
            salt = get_random_string(12)  # Generate a random salt
            hashed_password = hashlib.sha256((new_password + salt).encode()).hexdigest()

            # Update the user's password
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET password_hash = %s, salt = %s 
                    WHERE id = %s
                """, [hashed_password, salt, user_id])

            # Delete the used OTP
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM user_otp WHERE user_id = %s", [user_id])

            messages.success(request, "Password has been reset successfully!")
            return redirect('auth_page')
        else:
            messages.error(request, "Invalid or expired OTP. Please try again.")
            return render(request, 'repass.html')

    return render(request, 'repass.html')

def udash(request):
    user_id = request.session.get('user_id')
    logger.debug(f"udash - User ID from session: {user_id}")

    if not user_id:
        messages.error(request, "You must be logged in to view your dashboard.")
        logger.warning("udash - No user_id in session, redirecting to login")
        return redirect('login')

    try:
        with connection.cursor() as cursor:
            # Fetch user details
            cursor.execute("""
                SELECT username, premium, account_status, 
                       phone, address, pincode, bank_account_number, id_proof
                FROM users 
                WHERE id = %s
            """, [user_id])
            result = cursor.fetchone()
            logger.debug(f"udash - User query result: {result}")

            if result is None:
                messages.error(request, "User not found.")
                logger.error(f"udash - No user found for user_id: {user_id}")
                return redirect('login')

            username, is_premium, account_status, phone, address, pincode, bank_account_number, id_proof = result

            # Check if profile is incomplete
            profile_incomplete = (
                not phone or phone.strip() == '' or
                not address or address.strip() == '' or
                not pincode or pincode.strip() == '' or
                not bank_account_number or bank_account_number.strip() == '' or
                not id_proof or id_proof.strip() == ''
            )
            logger.debug(f"udash - Profile incomplete: {profile_incomplete}")

    except Exception as e:
        messages.error(request, "Error loading dashboard. Please try again later.")
        logger.error(f"udash - Database error: {str(e)}")
        return redirect('home')

    return render(request, 'udash.html', {
        'username': username,
        'user_id': user_id,
        'is_premium': is_premium,
        'account_status': account_status,
        'profile_incomplete': profile_incomplete
    })


def now():
    return timezone.now()

def create_auction(request):
    if not request.session.get('user_id'):  # Check if the user is logged in
        return redirect('auth_page')  # Redirect to login if not logged in

    user_id = request.session['user_id']  # Fetch user ID from session
    cursor = connection.cursor()
    locked = False
    user_auction_count = 0
    premium = False

    # Check user's premium status and auction count
    cursor.execute("""
        SELECT premium, (
            SELECT COUNT(*) 
            FROM auctions a 
            WHERE a.user_id = %s 
            AND (a.auction_type = 'regular' OR a.auction_type = 'buy_it_now' OR a.auction_type = 'sealed_bid')
        ) as auction_count
        FROM users 
        WHERE id = %s
    """, [user_id, user_id])
    result = cursor.fetchone()
    if result:
        premium = bool(result[0])
        user_auction_count = result[1] or 0

    if user_auction_count >= 1 and not premium:
        locked = True

    if request.method == 'POST' and not locked:
        auction_type = request.POST.get('auction_type')

        item_condition = request.POST.get('item_condition', '')
        condition_description = request.POST.get('condition_description', '')

        current_time = now()
        default_start_date = current_time
        default_end_date = current_time + timedelta(days=7)

        # Regular auction processing
        if auction_type == 'regular':
            title = request.POST['title']
            description = request.POST['description']
            category = request.POST['category']
            starting_price = float(request.POST.get('starting_price', 0))
            reserve_price = float(request.POST.get('reserve_price', 0))
            bid_increment = float(request.POST.get('bid_increment', 1))
            start_date = request.POST.get('start_date') or default_start_date
            end_date = request.POST.get('end_date') or default_end_date
            images = request.FILES.getlist('regular_images')

            cursor.execute("""
                INSERT INTO auctions (user_id, title, description, category, starting_price, reserve_price, bid_increment, start_date, end_date, auction_type, `condition`, condition_description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [user_id, title, description, category, starting_price, reserve_price, bid_increment, start_date, end_date, auction_type, item_condition, condition_description])

            cursor.execute("SELECT LAST_INSERT_ID()")
            auction_id = cursor.fetchone()[0]

            for image in images:
                unique_filename = f"{uuid.uuid4().hex}_{image.name}"
                image_path = os.path.join(settings.MEDIA_ROOT, 'auction_images', unique_filename)
                os.makedirs(os.path.dirname(image_path), exist_ok=True)

                cursor.execute("""
                    INSERT INTO auction_images (auction_id, image_path)
                    VALUES (%s, %s)
                """, [auction_id, unique_filename])

                with open(image_path, 'wb+') as destination:
                    for chunk in image.chunks():
                        destination.write(chunk)

            cursor.execute("""
                INSERT INTO user_activity (user_id, description)
                VALUES (%s, %s)
            """, [user_id, "Created a regular auction."])

            return redirect('my_auc')

        # Buy it now auction processing
        elif auction_type == 'buy_it_now':
            title = request.POST['title']
            description = request.POST['description']
            category = request.POST['category']
            buy_it_now_price = float(request.POST.get('buy_it_now_price', 0))
            is_make_offer_enabled = 'is_make_offer_enabled' in request.POST
            start_date = request.POST.get('start_date') or default_start_date
            end_date = request.POST.get('end_date') or default_end_date
            images = request.FILES.getlist('buy_it_now_images')

            is_make_offer_enabled = 1 if is_make_offer_enabled else 0

            cursor.execute("""
                INSERT INTO auctions (user_id, title, description, category, buy_it_now_price, is_make_offer_enabled, start_date, end_date, auction_type, `condition`, condition_description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [user_id, title, description, category, buy_it_now_price, is_make_offer_enabled, start_date, end_date, auction_type, item_condition, condition_description])

            cursor.execute("SELECT LAST_INSERT_ID()")
            auction_id = cursor.fetchone()[0]

            for image in images:
                unique_filename = f"{uuid.uuid4().hex}_{image.name}"
                image_path = os.path.join(settings.MEDIA_ROOT, 'auction_images', unique_filename)
                os.makedirs(os.path.dirname(image_path), exist_ok=True)

                cursor.execute("""
                    INSERT INTO auction_images (auction_id, image_path)
                    VALUES (%s, %s)
                """, [auction_id, unique_filename])

                with open(image_path, 'wb+') as destination:
                    for chunk in image.chunks():
                        destination.write(chunk)

            cursor.execute("""
                INSERT INTO user_activity (user_id, description)
                VALUES (%s, %s)
            """, [user_id, "Created a Buy It Now auction."])

            return redirect('my_auc')

        # Sealed bid auction processing
        elif auction_type == 'sealed_bid':
            title = request.POST['title']
            description = request.POST['description']
            category = request.POST['category']
            start_date = request.POST.get('start_date') or default_start_date
            end_date = request.POST.get('end_date') or default_end_date
            winner_selection_date = request.POST.get('winner_selection_date') or default_end_date
            reserve_price = float(request.POST.get('sealed_reserve_price', 0))

            cursor.execute("""
                INSERT INTO auctions (user_id, title, description, category, reserve_price, start_date, end_date, auction_type, `condition`, condition_description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [user_id, title, description, category, reserve_price, start_date, end_date, auction_type, item_condition, condition_description])

            cursor.execute("SELECT LAST_INSERT_ID()")
            auction_id = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO sealed_bid_details (auction_id, winner_selection_date)
                VALUES (%s, %s)
            """, [auction_id, winner_selection_date])

            images = request.FILES.getlist('sealed_bid_images')
            for image in images:
                unique_filename = f"{uuid.uuid4().hex}_{image.name}"
                image_path = os.path.join(settings.MEDIA_ROOT, 'auction_images', unique_filename)
                os.makedirs(os.path.dirname(image_path), exist_ok=True)

                cursor.execute("""
                    INSERT INTO auction_images (auction_id, image_path)
                    VALUES (%s, %s)
                """, [auction_id, unique_filename])

                with open(image_path, 'wb+') as destination:
                    for chunk in image.chunks():
                        destination.write(chunk)

            cursor.execute("""
                INSERT INTO user_activity (user_id, description)
                VALUES (%s, %s)
            """, [user_id, "Created a Sealed Bid auction."])

            return redirect('my_auc')

    context = {
        'locked': locked,
        'premium': premium,
        'user_auction_count': user_auction_count
    }
    return render(request, 'create_auction.html', context)
def my_auc(request):
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to view your auctions.")
        return redirect('login')

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT a.id, a.title, a.description, a.starting_price, a.end_date,
                       a.buy_it_now_price, a.is_make_offer_enabled, a.auction_type,
                       a.status,
                       (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url,
                       (SELECT MAX(b.amount) FROM bids b WHERE b.auction_id = a.id) AS current_bid
                FROM auctions a
                WHERE a.user_id = %s
                ORDER BY a.created_at DESC
            """, [user_id])
            auctions = [
                {
                    "id": row[0],
                    "title": row[1],
                    "description": row[2],
                    "starting_price": float(row[3]) if row[3] is not None else 0.0,  # Default to 0.0 if None
                    "end_date": row[4].strftime('%Y-%m-%d %H:%M:%S') if row[4] else None,
                    "buy_it_now_price": float(row[5]) if row[5] is not None else None,  # Keep None if null
                    "is_make_offer_enabled": row[6],
                    "type": row[7],
                    "status": row[8],
                    "image_url": f"/media/auction_images/{row[9]}" if row[9] else "/static/images/placeholder.png",
                    "current_bid": float(row[10]) if row[10] is not None else (float(row[3]) if row[3] is not None else 0.0),  # Fallback to starting_price or 0.0
                }
                for row in cursor.fetchall()
            ]
    except Exception as e:
        auctions = []
        messages.error(request, f"Error fetching auctions: {e}")
        print(f"Error fetching auctions: {e}")

    # Handle AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({"auctions": auctions})

    # Handle initial page load
    return render(request, 'my_auc.html', {"auctions": auctions})


def my_bids(request):
    # Ensure the user is logged in
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to view your bids.")
        return redirect('login')

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT  
                    a.id, 
                    a.title, 
                    a.description, 
                    a.starting_price, 
                    a.end_date,
                    a.buy_it_now_price, 
                    a.is_make_offer_enabled, 
                    a.auction_type,
                    (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url,
                    (SELECT MAX(b.amount) FROM bids b WHERE b.auction_id = a.id) AS current_bid,
                    (SELECT COUNT(b.id) FROM bids b WHERE b.auction_id = a.id AND b.user_id = %s) AS bid_count
                FROM auctions a
                JOIN bids b ON a.id = b.auction_id
                WHERE b.user_id = %s
                GROUP BY a.id
                ORDER BY a.end_date DESC
            """, [user_id, user_id])
            rows = cursor.fetchall()

        auctions = []
        for row in rows:
            auctions.append({
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "starting_price": row[3],
                "end_date": row[4],
                "buy_it_now_price": row[5] if row[5] else None,
                "is_make_offer_enabled": row[6],
                "auction_type": row[7],
                "image_url": f"/media/auction_images/{row[8]}" if row[8] else "/static/images/placeholder.png",
                "current_bid": row[9] if row[9] else row[3],  # If no bids, display starting price
                "bid_count": row[10],  # Number of bids user placed
            })
    except Exception as e:
        auctions = []
        messages.error(request, f"Error fetching auctions: {e}")
        print(f"Error fetching auctions: {e}")

    # Pass current time to the template for comparison (for expired auctions)
    context = {
        "auctions": auctions,
        "now": datetime.now(),
    }
    return render(request, 'my_bids.html', context)


def delete_auc(request, auction_id):
    """
    Deletes an auction and its related records (watchlist, sealed_bid_details, fund_distribution,
    seller_payouts, invoices) if the user is the auction's owner and there are no bids.
    Redirects to 'my_auc' with success or error messages.
    """
    logger.debug(f"Initiating deletion for auction id: {auction_id}")

    user_id = request.session.get('user_id')
    if not user_id:
        logger.debug("No user_id found in session.")
        messages.error(request, "You must be logged in to delete an auction.")
        return redirect('auth_page')

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Check ownership and get auction status
                cursor.execute("""
                    SELECT a.auction_type, a.end_date < NOW() as has_ended,
                           (SELECT COUNT(*) FROM bids WHERE auction_id = %s) as bid_count
                    FROM auctions a
                    WHERE a.id = %s AND a.user_id = %s
                """, [auction_id, auction_id, user_id])

                auction_data = cursor.fetchone()

                if not auction_data:
                    logger.debug(f"Auction id {auction_id} not found or user {user_id} not authorized.")
                    messages.error(request, "Auction not found or unauthorized.")
                    return redirect('my_auc')

                auction_type, has_ended, bid_count = auction_data
                logger.debug(f"Auction type: {auction_type}, has_ended: {has_ended}, bid_count: {bid_count}")

                # Prevent deletion if there are any bids
                if bid_count > 0:
                    logger.debug(f"Auction id {auction_id} has bids, deletion aborted.")
                    messages.error(request, "You cannot delete an auction with bids.")
                    return redirect('my_auc')

                # Delete related records
                cursor.execute("DELETE FROM watchlist WHERE auction_id = %s", [auction_id])
                logger.debug(f"Deleted watchlist records for auction id: {auction_id}")

                if auction_type == "sealed_bid":
                    cursor.execute("DELETE FROM sealed_bid_details WHERE auction_id = %s", [auction_id])
                    logger.debug(f"Deleted sealed_bid_details for auction id: {auction_id}")

                cursor.execute("DELETE FROM fund_distribution WHERE auction_id = %s", [auction_id])
                logger.debug(f"Deleted fund_distribution for auction id: {auction_id}")

                # Delete seller_payouts before invoices to avoid foreign key constraint
                cursor.execute("DELETE FROM seller_payouts WHERE invoice_id IN (SELECT id FROM invoices WHERE auction_id = %s)", [auction_id])
                logger.debug(f"Deleted seller_payouts for auction id: {auction_id}")

                cursor.execute("DELETE FROM invoices WHERE auction_id = %s", [auction_id])
                logger.debug(f"Deleted invoices for auction id: {auction_id}")

                cursor.execute("DELETE FROM auctions WHERE id = %s", [auction_id])
                logger.debug(f"Deleted auction record for auction id: {auction_id}")

                # Log activity
                cursor.execute("""
                    INSERT INTO user_activity (user_id, description)
                    VALUES (%s, %s)
                """, [user_id, f"Deleted {auction_type} auction #{auction_id}"])
                logger.debug(f"Logged activity for user {user_id}: Deleted {auction_type} auction #{auction_id}")

                messages.success(request, "Auction deleted successfully!")

    except Exception as e:
        logger.error(f"Error deleting auction id {auction_id}: {str(e)}")
        messages.error(request, "An error occurred while deleting the auction.")
        return redirect('my_auc')

    logger.debug(f"Auction id {auction_id} deleted successfully.")
    return redirect('my_auc')


def edit_auction(request, auction_id):
    user_id = request.session.get('user_id')  # Get logged-in user ID from session

    # Fetch the auction details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, title, description, category, starting_price, bid_increment, reserve_price, 
                   auction_type, buy_it_now_price, user_id
            FROM auctions
            WHERE id = %s
        """, [auction_id])
        auction = cursor.fetchone()

    if not auction:
        raise Http404("Auction not found.")

    # Map auction data
    auction_data = {
        'id': auction[0],
        'title': auction[1],
        'description': auction[2],
        'category': auction[3],
        'starting_price': auction[4],
        'bid_increment': auction[5],
        'reserve_price': auction[6],
        'auction_type': auction[7],
        'buy_it_now_price': auction[8],
        'user_id': auction[9],
    }

    # Ensure only the owner can edit
    if auction_data['user_id'] != user_id:
        return redirect('home')

    # Fetch winner selection date from the sealed bid details table (if applicable)
    winner_selection_date = None
    if auction_data['auction_type'] == 'sealed':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT winner_selection_date 
                FROM sealed_bid_details 
                WHERE auction_id = %s
            """, [auction_id])
            sealed_data = cursor.fetchone()
            if sealed_data:
                winner_selection_date = sealed_data[0]

    # Fetch auction images
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT image_path FROM auction_images WHERE auction_id = %s
        """, [auction_id])
        auction_images = cursor.fetchall()

    auction_image_paths = [f"/media/auction_images/{img[0]}" for img in auction_images]

    # Handle form submission
    if request.method == 'POST':
        title = request.POST['title']
        description = request.POST['description']

        # Convert empty string to None for numeric fields
        def clean_numeric(value):
            return float(value) if value.strip() else None

        starting_price = clean_numeric(request.POST.get('starting_price', ''))
        bid_increment = clean_numeric(request.POST.get('bid_increment', ''))
        reserve_price = clean_numeric(request.POST.get('reserve_price', ''))
        buy_now_price = clean_numeric(request.POST.get('buy_now_price', ''))
        winner_selection_date = request.POST.get('winner_selection_date', None)

        # Update auction details
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE auctions 
                SET title = %s, description = %s, starting_price = %s, bid_increment = %s, 
                    reserve_price = %s, buy_it_now_price = %s
                WHERE id = %s
            """, [title, description, starting_price, bid_increment, reserve_price, buy_now_price, auction_id])

        # Update winner selection date if auction is sealed
        if auction_data['auction_type'] == 'sealed' and winner_selection_date:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE sealed_bid_details 
                    SET winner_selection_date = %s
                    WHERE auction_id = %s
                """, [winner_selection_date, auction_id])

        # Handle Image Uploads (but do NOT allow deletions)
        if 'images' in request.FILES:
            uploaded_files = request.FILES.getlist('images')
            for file in uploaded_files:
                file_name = f"auction_{auction_id}_{file.name}"
                file_path = os.path.join(settings.MEDIA_ROOT, "auction_images", file_name)

                # Save file
                with default_storage.open(file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

                # Store image in the database
                with connection.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO auction_images (auction_id, image_path) 
                        VALUES (%s, %s)
                    """, [auction_id, file_name])

        return redirect('my_auc')

    return render(request, 'edit_auction.html', {
        'auction': auction_data,
        'winner_selection_date': winner_selection_date,
        'auction_image_paths': auction_image_paths,
    })


def relist_auction(request, auction_id):
    """
    Relist an auction if conditions are met.
    This view clears the winner of the auction, extends the end date, flags the auction as relisted,
    marks any second-winner offers as expired, deletes all previous bids, deletes the associated invoice
    and order records, sets the 'checked' flag to 0, updates the status to 'active', resets the current bid
    to the auction's starting price, and sends an email notification to the seller.
    Only the seller (owner of the auction) is allowed to relist.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to relist an auction.")
        return redirect('login')

    try:
        with connection.cursor() as cursor:
            # Fetch auction details and ensure the auction belongs to the logged-in seller.
            # Also fetch starting_price for resetting the current bid.
            cursor.execute("""
                SELECT user_id, winner_user_id, auction_type, end_date, starting_price
                FROM auctions
                WHERE id = %s
            """, [auction_id])
            auction = cursor.fetchone()
            if not auction:
                messages.error(request, "Auction not found.")
                return redirect('my_auc')  # Redirect to the seller's auctions listing.

            seller_id, winner_user_id, auction_type, end_date, starting_price = auction
            if seller_id != user_id:
                messages.error(request, "You are not authorized to relist this auction.")
                return redirect('my_auc')

            # Calculate a new end date (for testing, extend by 1 day; adjust as needed for production)
            new_end_date = timezone.now() + timedelta(days=1)
            logger.debug(f"Relisting auction {auction_id}: new end date set to {new_end_date}")

            # Update the auction: clear the winner, update the end date, flag as relisted, reset checked,
            # set status to 'active', and update current_bid to the starting price.
            cursor.execute("""
                UPDATE auctions
                SET winner_user_id = NULL, end_date = %s, is_relisted = 1, checked = 0, status = 'active', current_bid = %s
                WHERE id = %s
            """, [new_end_date, starting_price, auction_id])
            logger.info(f"Auction {auction_id} relisted by seller {user_id}")

            # Mark any second-winner offers as expired (so they don't show to buyers)
            cursor.execute("""
                UPDATE offers
                SET status = 'expired'
                WHERE auction_id = %s AND second_winner_offer = 1
            """, [auction_id])
            logger.info(f"Marked second-winner offers as expired for auction {auction_id}")

            # Delete all previous bids for this auction.
            cursor.execute("DELETE FROM bids WHERE auction_id = %s", [auction_id])
            logger.info(f"Deleted all bids for auction {auction_id}")

            # Delete the associated invoice for this auction.
            cursor.execute("DELETE FROM invoices WHERE auction_id = %s", [auction_id])
            logger.info(f"Deleted invoice(s) for auction {auction_id}")

            # Delete the associated order for this auction.
            cursor.execute("DELETE FROM orders WHERE auction_id = %s", [auction_id])
            logger.info(f"Deleted orders for auction {auction_id}")

            # Fetch seller details to send notification.
            cursor.execute("SELECT email, username FROM users WHERE id = %s", [seller_id])
            seller_info = cursor.fetchone()
            if seller_info:
                seller_email, seller_username = seller_info
                email_subject = "Auction Relisted Successfully"
                email_body = (
                    f"Dear {seller_username},\n\n"
                    f"Your auction (ID: {auction_id}) has been successfully relisted. "
                    f"The new end date is {new_end_date.strftime('%Y-%m-%d %H:%M:%S')}.\n\n"
                    "All previous bids, invoices, and orders for this auction have been removed, "
                    "and the auction has been reset for further bidding.\n\n"
                    "Thank you,\nAuction Platform Team"
                )
                send_email_notification(seller_email, email_subject, email_body)
                logger.info(f"Sent relisting email to seller {seller_email} for auction {auction_id}")
            else:
                logger.warning(f"Seller details not found for seller_id {seller_id}")

        messages.success(request, "Auction relisted successfully.")
        return redirect('myauc_deta', auction_id=auction_id)

    except Exception as e:
        logger.error(f"Error relisting auction {auction_id}: {str(e)}")
        messages.error(request, "An error occurred while relisting the auction.")
        return redirect('my_auc')





def myauc_deta(request, auction_id):
    # Fetch user ID from session
    user_id = request.session.get('user_id')
    if not user_id:
        raise Http404("Unauthorized access. Please log in.")

    # Fetch auction details, including winner_user_id and status
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                a.id, 
                a.title, 
                a.description, 
                a.category, 
                a.starting_price, 
                a.current_bid, 
                a.bid_increment, 
                a.reserve_price,
                a.start_date, 
                a.end_date, 
                a.user_id, 
                a.auction_type, 
                a.winner_user_id,
                (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url,
                a.buy_it_now_price, 
                a.is_make_offer_enabled,
                a.status,
                a.updated_at  -- Assuming this tracks when the status was last changed
            FROM auctions a
            WHERE a.id = %s
        """, [auction_id])
        auction = cursor.fetchone()

    if not auction:
        raise Http404("Auction not found.")

    # Ensure the auction belongs to the logged-in seller
    if auction[10] != user_id:
        raise Http404("You do not have permission to view this auction.")

    # Organize fetched auction data
    auction_data = {
        'id': auction[0],
        'title': auction[1],
        'description': auction[2],
        'category': auction[3],
        'starting_price': auction[4],
        'current_bid': auction[5],
        'bid_increment': auction[6],
        'reserve_price': auction[7],
        'start_date': auction[8],
        'end_date': auction[9],
        'user_id': auction[10],
        'auction_type': auction[11],
        'winner_user_id': auction[12],
        'image_url': f"/media/auction_images/{auction[13]}" if auction[13] else "/static/images/placeholder.png",
        'buy_it_now_price': auction[14],
        'is_make_offer_enabled': auction[15],
        'status': auction[16],
        'updated_at': auction[17],  # Time of last update (e.g., when stopped)
    }

    # Fetch seller details from the session
    with connection.cursor() as cursor:
        cursor.execute("SELECT username, email FROM users WHERE id = %s", [user_id])
        user = cursor.fetchone()

    auction_data['user'] = {
        'username': user[0] if user else "Unknown User",
        'email': user[1] if user else "No Email",
    }

    # Initialize winner details
    winner = None
    winner_available = False

    # Check if the auction has ended and has a winner
    if datetime.now() > auction_data['end_date'] and auction_data.get('winner_user_id'):
        winner_available = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT username, email FROM users WHERE id = %s", [auction_data['winner_user_id']])
            winner_data = cursor.fetchone()
        if winner_data:
            winner = {
                'user_id': auction_data['winner_user_id'],
                'username': winner_data[0],
                'email': winner_data[1],
                'final_price': auction_data['current_bid']
            }

    auction_data['winner'] = winner
    auction_data['winner_available'] = winner_available

    # Fetch last bid (to update current_bid if needed)
    with connection.cursor() as cursor:
        cursor.execute("SELECT amount FROM bids WHERE auction_id = %s ORDER BY created_at DESC LIMIT 1", [auction_data['id']])
        last_bid = cursor.fetchone()
    auction_data['current_bid'] = last_bid[0] if last_bid else auction_data['starting_price']

    # Fetch all images for the auction
    with connection.cursor() as cursor:
        cursor.execute("SELECT image_path FROM auction_images WHERE auction_id = %s", [auction_data['id']])
        images = cursor.fetchall()
    auction_data['images'] = [f"/media/auction_images/{img[0]}" for img in images]

    # Fetch winner selection date for sealed bid auctions
    if auction_data['auction_type'] == 'sealed_bid':
        with connection.cursor() as cursor:
            cursor.execute("SELECT winner_selection_date FROM sealed_bid_details WHERE auction_id = %s", [auction_data['id']])
            sealed_bid = cursor.fetchone()
        if sealed_bid:
            auction_data['sealed_bid_details'] = {'winner_selection_date': sealed_bid[0]}

        # Fetch winner details for sealed bid
        if auction_data.get('winner_user_id'):
            with connection.cursor() as cursor:
                cursor.execute("SELECT username, email FROM users WHERE id = %s", [auction_data['winner_user_id']])
                sealed_winner = cursor.fetchone()
            if sealed_winner:
                auction_data['winner'] = {
                    'user_id': auction_data['winner_user_id'],
                    'username': sealed_winner[0],
                    'email': sealed_winner[1],
                }
                auction_data['winner_available'] = True

    # Fetch bid history
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT b.amount, b.created_at, u.username, u.email
            FROM bids b
            JOIN users u ON b.user_id = u.id
            WHERE b.auction_id = %s
            ORDER BY b.created_at DESC
        """, [auction_data['id']])
        bid_history = cursor.fetchall()

    auction_data['bid_history'] = [
        {
            'amount': bid[0],
            'created_at': bid[1],
            'bidder_username': bid[2],
            'bidder_email': bid[3],
        }
        for bid in bid_history
    ]

    # Determine if the "Relist Auction" button should be available
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM offers
            WHERE auction_id = %s AND second_winner_offer = 1 AND status = 'pending'
        """, [auction_id])
        pending_offer_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) 
            FROM offers
            WHERE auction_id = %s AND second_winner_offer = 1 AND status IN ('rejected', 'expired')
        """, [auction_id])
        rejected_or_expired_offer_count = cursor.fetchone()[0]
        relist_offer_condition = rejected_or_expired_offer_count > 0

        cursor.execute("""
            SELECT amount 
            FROM bids 
            WHERE auction_id = %s 
            ORDER BY amount DESC 
            LIMIT 1 OFFSET 1
        """, [auction_id])
        second_bid = cursor.fetchone()
        second_bid_amount = second_bid[0] if second_bid else None

    reserve_price = auction_data['reserve_price'] or 0
    second_bid_condition = (second_bid_amount is None or second_bid_amount <= reserve_price)

    if auction_data['winner_user_id'] is not None:
        relist_available = relist_offer_condition
    else:
        if pending_offer_count > 0:
            relist_available = False
        else:
            relist_available = relist_offer_condition or second_bid_condition

    return render(request, 'myauc_deta.html', {
        'auction': auction_data,
        'now': datetime.now(),
        'relist_available': relist_available,
    })








def bidding_history(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    with connection.cursor() as cursor:
        # Fetch auction and bid data
        cursor.execute("""
            SELECT 
                a.id AS auction_id,
                a.title AS auction_title,
                b.amount AS bid_amount,
                b.bid_time,
                a.current_bid,
                a.reserve_price,
                a.end_date,
                a.winner_user_id
            FROM auctions a
            JOIN bids b ON a.id = b.auction_id
            WHERE b.user_id = %s
            ORDER BY a.id DESC, b.bid_time DESC
        """, [user_id])

        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    # Process data in Python
    auctions = defaultdict(lambda: {
        'auction_id': None,
        'auction_title': None,
        'current_bid': 0,
        'reserve_price': 0,
        'end_date': None,
        'winner_user_id': None,
        'bid_history': [],
        'user_max_bid': 0,
        'status': 'Pending',
        'last_bid_time': None,
    })

    for row in rows:
        auction_id = row[columns.index('auction_id')]
        auction = auctions[auction_id]

        # Set auction details if not already set
        if not auction['auction_id']:
            auction['auction_id'] = row[columns.index('auction_id')]
            auction['auction_title'] = row[columns.index('auction_title')]
            auction['current_bid'] = row[columns.index('current_bid')]
            auction['reserve_price'] = row[columns.index('reserve_price')]
            auction['end_date'] = row[columns.index('end_date')]
            auction['winner_user_id'] = row[columns.index('winner_user_id')]

            # Ensure end_date is timezone-aware
            if auction['end_date'] and not timezone.is_aware(auction['end_date']):
                auction['end_date'] = timezone.make_aware(auction['end_date'])

            # Determine auction status
            if auction['end_date'] and auction['end_date'] > timezone.now():
                auction['status'] = 'Pending'
            elif auction['winner_user_id'] == user_id:
                auction['status'] = 'Won'
            else:
                auction['status'] = 'Lost'

        # Track user's maximum bid
        bid_amount = row[columns.index('bid_amount')]
        if bid_amount > auction['user_max_bid']:
            auction['user_max_bid'] = bid_amount

        # Ensure bid_time is timezone-aware
        bid_time = row[columns.index('bid_time')]
        if not timezone.is_aware(bid_time):
            bid_time = timezone.make_aware(bid_time)

        # Add bid to history
        auction['bid_history'].append({
            'amount': bid_amount,
            'time': bid_time,
            'is_winner': auction['winner_user_id'] == user_id and bid_amount == auction['current_bid']
        })

        # Track last bid time
        if not auction['last_bid_time'] or bid_time > auction['last_bid_time']:
            auction['last_bid_time'] = bid_time

    # Convert defaultdict to list and calculate time differences
    auction_list = []
    for auction in auctions.values():
        auction['difference'] = auction['user_max_bid'] - auction['current_bid']
        auction['time_since_last'] = naturaltime(auction['last_bid_time'])

        # Sort bid history by time (most recent first)
        auction['bid_history'] = sorted(
            auction['bid_history'],
            key=lambda x: x['time'],
            reverse=True
        )

        # Add time_ago to each bid
        for bid in auction['bid_history']:
            bid['time_ago'] = naturaltime(bid['time'])

        auction_list.append(auction)

    return render(request, 'bidding_history.html', {'auctions': auction_list})

def update_winner(auction_id, winning_user_id):
    with connection.cursor() as cursor:
        # Set is_winner = 1 for the winner's bid
        cursor.execute("""
            UPDATE bidding_history
            SET is_winner = 1
            WHERE auction_id = %s AND user_id = %s
        """, [auction_id, winning_user_id])


def make_offer(request, auction_id):
    print("DEBUG: make_offer got auction_id =", auction_id)
    buyer_id = request.session.get('user_id')
    if not buyer_id:
        print("DEBUG: Buyer not logged in; redirecting to auth_page.")
        messages.error(request, "Please log in to make an offer.")
        return redirect('auth_page')

    # Fetch auction details (including seller id)
    with connection.cursor() as cursor:
        print("DEBUG: Executing auction details query for auction_id =", auction_id)
        cursor.execute("""
            SELECT 
                a.id, 
                a.title, 
                a.description, 
                a.condition, 
                a.condition_description, 
                a.category,
                a.buy_it_now_price,
                a.user_id,           -- seller id
                a.status, 
                a.start_date, 
                a.end_date,
                (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url
            FROM auctions a
            WHERE a.id = %s
        """, [auction_id])
        auction = cursor.fetchone()
        print("DEBUG: Auction query result:", auction)

    if not auction:
        print("DEBUG: No auction found for auction_id =", auction_id)
        messages.error(request, "Auction not found.")
        return redirect('auct_list')

    auction_data = {
        'id': auction[0],
        'title': auction[1],
        'description': auction[2],
        'condition': auction[3],
        'condition_description': auction[4],
        'category': auction[5],
        'buy_it_now_price': auction[6],
        'seller_id': auction[7],
        'status': auction[8],
        'start_date': auction[9],
        'end_date': auction[10],
        'image_url': f"/media/auction_images/{auction[11]}" if auction[11] else "/static/images/placeholder.png",
    }
    print("DEBUG: Auction data mapped:", auction_data)

    if request.method == "POST":
        print("DEBUG: POST request received")
        offer_price_raw = request.POST.get('offer_price')
        print("DEBUG: Raw offer price:", offer_price_raw)
        if not offer_price_raw:
            print("DEBUG: offer_price is missing")
            messages.error(request, "Please enter a valid offer price.")
            return render(request, 'make_offer.html', {'auction_id': auction_id, 'auction': auction_data})
        try:
            offer_price = float(offer_price_raw)
            print("DEBUG: Parsed offer price:", offer_price)
        except (ValueError, TypeError):
            print("DEBUG: offer_price parsing failed")
            messages.error(request, "Please enter a valid offer price.")
            return render(request, 'make_offer.html', {'auction_id': auction_id, 'auction': auction_data})
        if offer_price <= 0:
            print("DEBUG: offer_price is not greater than zero")
            messages.error(request, "Please enter a valid offer price greater than zero.")
            return render(request, 'make_offer.html', {'auction_id': auction_id, 'auction': auction_data})

        with connection.cursor() as cursor:
            print("DEBUG: Inserting offer into offers table")
            cursor.execute("""
                INSERT INTO offers (auction_id, buyer_id, offer_price, offer_message, status, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, [auction_id, buyer_id, offer_price, request.POST.get('offer_message', ''), 'pending'])
            print("DEBUG: Offer inserted successfully")
        messages.success(request, "Your offer has been submitted.")

        # Notify seller: fetch seller email
        with connection.cursor() as cursor:
            print("DEBUG: Fetching seller email for seller_id =", auction_data['seller_id'])
            cursor.execute("SELECT email FROM users WHERE id = %s", [auction_data['seller_id']])
            row = cursor.fetchone()
            seller_email = row[0] if row else None
            print("DEBUG: Seller email fetched:", seller_email)

        # Build notification message for the seller
        seller_message = f"A new offer of ₹{offer_price} has been submitted on your auction '{auction_data['title']}'."
        # Notify the seller (using your helper function)
        notify_user(auction_data['seller_id'], seller_email, seller_message, subject="New Offer Received")
        print("DEBUG: Seller notification sent")

        print("DEBUG: Redirecting to auction details page with auction_id =", auction_id)
        return redirect('auct_deta', auction_id=auction_id)

    print("DEBUG: Rendering make_offer.html with auction data and auction_id =", auction_id)
    return render(request, 'make_offer.html', {
        "auction": auction_data,
        "auction_id": auction_id
    })


def view_offers(request):
    """
    View offers for the logged-in user.
    - Received Offers: Offers for auctions where the user is the seller (excluding second winner offers).
    - Sent Offers: Offers the user has submitted (excluding second winner offers).
    - Auction Offers: Offers made on auctions of type 'regular' or 'sealed_bid', including second winner offers for the buyer.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to view your offers.")
        return redirect('login')

    received_offers = []
    sent_offers = []
    auction_offers = []

    with connection.cursor() as cursor:
        # Received Offers: Offers where the current user is the seller, excluding second winner offers.
        cursor.execute("""
            SELECT 
                o.id AS offer_id,
                o.auction_id,
                o.offer_price,
                o.offer_message,
                o.status,
                o.created_at,
                a.title,
                a.buy_it_now_price,
                u.id AS buyer_id,
                u.username AS buyer_username,
                u.email AS buyer_email,
                (
                    SELECT COUNT(*) 
                    FROM offers o2 
                    WHERE o2.auction_id = a.id 
                      AND o2.status = 'accepted'
                ) AS accepted_count
            FROM offers o
            JOIN auctions a ON o.auction_id = a.id
            JOIN users u ON o.buyer_id = u.id
            WHERE a.user_id = %s AND o.second_winner_offer = 0
            ORDER BY o.created_at DESC
        """, [user_id])
        rows = cursor.fetchall()
        for row in rows:
            offer = {
                "offer_id": row[0],
                "auction_id": row[1],
                "offer_price": float(row[2]),
                "offer_message": row[3],
                "status": row[4],
                "created_at": row[5],
                "auction_title": row[6],
                "buy_it_now_price": row[7],
                "buyer_id": row[8],
                "buyer_username": row[9],
                "buyer_email": row[10],
                "accepted_count": row[11],
            }
            received_offers.append(offer)
            logger.debug(f"view_offers - Received offer mapped: {offer}")

        # Sent Offers: Offers submitted by the current user, excluding second winner offers.
        cursor.execute("""
            SELECT 
                o.id AS offer_id,
                o.auction_id,
                o.offer_price,
                o.offer_message,
                o.status,
                o.created_at,
                a.title,
                a.buy_it_now_price,
                a.user_id AS seller_id,
                s.username AS seller_username,
                s.email AS seller_email
            FROM offers o
            JOIN auctions a ON o.auction_id = a.id
            JOIN users s ON a.user_id = s.id
            WHERE o.buyer_id = %s AND o.second_winner_offer = 0
            ORDER BY o.created_at DESC
        """, [user_id])
        rows2 = cursor.fetchall()
        for row in rows2:
            offer = {
                "offer_id": row[0],
                "auction_id": row[1],
                "offer_price": float(row[2]),
                "offer_message": row[3],
                "status": row[4],
                "created_at": row[5],
                "auction_title": row[6],
                "buy_it_now_price": row[7],
                "seller_id": row[8],
                "seller_username": row[9],
                "seller_email": row[10],
            }
            sent_offers.append(offer)
            logger.debug(f"view_offers - Sent offer mapped: {offer}")

        # Auction Offers: Offers on 'regular' or 'sealed_bid' auctions, including second winner offers for the buyer.
        cursor.execute("""
            SELECT 
                o.id AS offer_id,
                o.auction_id,
                o.offer_price,
                o.offer_message,
                o.status,
                o.created_at,
                a.title,
                a.buy_it_now_price,
                a.auction_type,
                u.username AS buyer_username,
                u.email AS buyer_email,
                (
                    SELECT COUNT(*) 
                    FROM offers o2 
                    WHERE o2.auction_id = a.id 
                      AND o2.status = 'accepted'
                ) AS accepted_count
            FROM offers o
            JOIN auctions a ON o.auction_id = a.id
            JOIN users u ON o.buyer_id = u.id
            WHERE a.auction_type IN ('regular', 'sealed_bid')
              AND (o.second_winner_offer = 0 OR (o.second_winner_offer = 1 AND o.buyer_id = %s))
            ORDER BY o.created_at DESC
        """, [user_id])
        rows3 = cursor.fetchall()
        for row in rows3:
            offer = {
                "offer_id": row[0],
                "auction_id": row[1],
                "offer_price": float(row[2]),
                "offer_message": row[3],
                "status": row[4],
                "created_at": row[5],
                "auction_title": row[6],
                "buy_it_now_price": row[7],
                "auction_type": row[8],
                "buyer_username": row[9],
                "buyer_email": row[10],
                "accepted_count": row[11],
            }
            auction_offers.append(offer)
            logger.debug(f"view_offers - Auction offer mapped: {offer}")

    total_offers = len(received_offers) + len(sent_offers) + len(auction_offers)
    completed_offers = len([o for o in sent_offers if o['status'] == 'accepted'])

    context = {
        "offers": received_offers,
        "sent_offers": sent_offers,
        "auction_offers": auction_offers,
        "total_offers": total_offers,
        "completed_offers": completed_offers,
    }
    return render(request, "view_offers.html", context)


def accept_offer(request, offer_id):
    print(f"🔍 DEBUG: accept_offer called with offer_id={offer_id}")

    user_id = request.session.get('user_id')
    print(f"✅ DEBUG: User ID from session: {user_id}")

    if not user_id:
        messages.error(request, "You must be logged in to perform this action.")
        logger.error("❌ ERROR: User not logged in.")
        return redirect('login')

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        print(f"❌ DEBUG: Invalid request method: {request.method}")
        return redirect('view_offers')

    try:
        # Fetch auction_id from POST data
        auction_id = request.POST.get('auction_id')
        buyer_email = request.POST.get('buyer_email')  # Used for notifications

        print(f"✅ DEBUG: Received Data -> auction_id={auction_id}, buyer_email={buyer_email}")

        if not auction_id:
            messages.error(request, "Missing required auction ID.")
            logger.error("❌ ERROR: Missing auction_id.")
            return redirect('view_offers')

        # Fetch auction details including auction_type
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id, auction_type FROM auctions WHERE id = %s", [auction_id])
            auction_row = cursor.fetchone()

        print(f"✅ DEBUG: Auction Query Result: {auction_row}")

        if not auction_row:
            messages.error(request, "Auction not found.")
            logger.error(f"❌ ERROR: Auction ID {auction_id} not found.")
            return redirect('view_offers')

        seller_id, auction_type = auction_row
        print(f"✅ DEBUG: Auction Type: {auction_type}, Seller ID: {seller_id}")

        # Allow action only for Buy It Now auctions.
        if auction_type.lower() != "buy_it_now":
            messages.error(request, "This action is only available for Buy It Now auctions.")
            logger.error(f"❌ ERROR: Auction type is '{auction_type}', not Buy It Now.")
            return redirect('view_offers')

        # Verify offer exists and is pending
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT status, buyer_id 
                FROM offers 
                WHERE id = %s AND auction_id = %s
            """, [offer_id, auction_id])
            offer_row = cursor.fetchone()

        print(f"✅ DEBUG: Offer Query Result: {offer_row}")

        if not offer_row or offer_row[0] != 'pending':
            messages.error(request, "Offer not found or not pending.")
            logger.error(f"❌ ERROR: Offer {offer_id} not found or status is {offer_row[0] if offer_row else 'None'}.")
            return redirect('view_offers')

        offer_status, offer_buyer_id = offer_row

        # Verify that the logged-in user is the seller.
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id FROM auctions WHERE id = %s", [auction_id])
            auction_seller_row = cursor.fetchone()
            if not auction_seller_row or auction_seller_row[0] != seller_id:
                messages.error(request, "You are not authorized to accept this offer.")
                logger.error(f"❌ ERROR: User {user_id} not authorized for auction {auction_id}.")
                return redirect('view_offers')

        # For Buy It Now auctions, update the offer status to accepted.
        with connection.cursor() as cursor:
            cursor.execute("UPDATE offers SET status = 'accepted' WHERE id = %s", [offer_id])
        print(f"✅ DEBUG: Offer {offer_id} accepted for Buy It Now auction.")
        notify_user(offer_buyer_id, buyer_email,
                    f"Your offer on auction ID {auction_id} has been accepted.",
                    subject="Offer Accepted")
        messages.success(request, "Offer accepted successfully.")

        return redirect('view_offers')

    except Exception as e:
        logger.error(f"❌ ERROR: accept_offer - Exception: {str(e)}")
        print(f"❌ DEBUG: Exception Occurred -> {str(e)}")
        traceback.print_exc()
        messages.error(request, "Error processing the offer.")
        return redirect('view_offers')


def reject_offer(request, offer_id):
    print(f"🔍 DEBUG: reject_offer called with offer_id={offer_id}")

    seller_id = request.session.get('user_id')
    print(f"✅ DEBUG: User ID from session: {seller_id}")

    if not seller_id:
        messages.error(request, "You must be logged in to perform this action.")
        logger.warning("reject_offer - No user_id in session, redirecting to login")
        return redirect('login')

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        logger.warning(f"reject_offer - Invalid method for offer {offer_id}")
        print(f"❌ DEBUG: Invalid request method: {request.method}")
        return redirect('view_offers')

    try:
        # Fetch details from POST data
        auction_id = request.POST.get('auction_id')
        buyer_id = request.POST.get('buyer_id')
        buyer_email = request.POST.get('buyer_email')
        print(f"✅ DEBUG: Received Data -> auction_id={auction_id}, buyer_id={buyer_id}, buyer_email={buyer_email}")

        if not all([auction_id, buyer_id, buyer_email]):
            messages.error(request, "Missing required offer details.")
            logger.error(f"reject_offer - Missing POST data for offer {offer_id}")
            return redirect('view_offers')

        # Fetch auction details to check auction type.
        with connection.cursor() as cursor:
            cursor.execute("SELECT auction_type FROM auctions WHERE id = %s", [auction_id])
            auction_row = cursor.fetchone()
            if not auction_row:
                messages.error(request, "Auction not found.")
                return redirect('view_offers')
            auction_type = auction_row[0]
        print(f"✅ DEBUG: Auction Type: {auction_type}")

        # Allow action only for Buy It Now auctions.
        if auction_type.lower() != "buy_it_now":
            messages.error(request, "This action is only available for Buy It Now auctions.")
            logger.error(f"❌ ERROR: Auction type is '{auction_type}', not Buy It Now.")
            return redirect('view_offers')

        # Verify the offer exists and is pending.
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT status, auction_id
                FROM offers
                WHERE id = %s AND auction_id = %s
            """, [offer_id, auction_id])
            result = cursor.fetchone()
            print(f"✅ DEBUG: Offer Query Result: {result}")
            if not result or result[0] != 'pending':
                messages.error(request, "Offer not found or not pending.")
                logger.warning(f"reject_offer - Offer {offer_id} not found or status is {result[0] if result else 'None'}.")
                return redirect('view_offers')

        # Verify that the logged-in user is the seller.
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id FROM auctions WHERE id = %s", [auction_id])
            auction_seller_row = cursor.fetchone()
            if not auction_seller_row or auction_seller_row[0] != seller_id:
                messages.error(request, "You are not authorized to reject this offer.")
                logger.warning(f"reject_offer - User {seller_id} not authorized for auction {auction_id}.")
                return redirect('view_offers')

        # For Buy It Now auctions, update the offer status to rejected.
        with connection.cursor() as cursor:
            cursor.execute("UPDATE offers SET status = 'rejected' WHERE id = %s", [offer_id])
            logger.debug(f"reject_offer - Offer {offer_id} updated to rejected")

        messages.success(request, "Offer rejected successfully.")
        notify_user(buyer_id, buyer_email, f"Your offer on auction ID {auction_id} has been rejected.", subject="Offer Rejected")
        logger.info(f"reject_offer - Notified buyer {buyer_id} for auction {auction_id}")

        return redirect('view_offers')

    except Exception as e:
        logger.error(f"reject_offer - Exception for offer {offer_id}: {str(e)}")
        print(f"❌ DEBUG: Exception Occurred -> {str(e)}")
        traceback.print_exc()
        messages.error(request, "Error processing the offer.")
        return redirect('view_offers')


def accept_second_winner_offer(request, offer_id):
    """
    Allows the second highest bidder to accept a second winner offer.
    Updates related tables, removes shipping details, and notifies both buyer and seller upon acceptance.
    Includes debugging logs for troubleshooting.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to accept an offer.")
        logger.error("User not logged in while attempting to accept offer.")
        return redirect('login')

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        logger.error(f"Invalid request method: {request.method}")
        return redirect('view_offers')

    try:
        # Debug: Log entry into the function
        logger.debug(f"Starting accept_second_winner_offer for offer_id: {offer_id}, user_id: {user_id}")

        # Verify the offer is a second winner offer and belongs to the user
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT auction_id, buyer_id, status, second_winner_offer
                FROM offers
                WHERE id = %s
            """, [offer_id])
            offer_row = cursor.fetchone()

        if not offer_row:
            messages.error(request, "Offer not found.")
            logger.error(f"Offer ID {offer_id} not found.")
            return redirect('view_offers')

        auction_id, buyer_id, status, is_second_winner = offer_row
        logger.debug(f"Offer details - auction_id: {auction_id}, buyer_id: {buyer_id}, status: {status}, is_second_winner: {is_second_winner}")

        # Check conditions
        if status != 'pending':
            messages.error(request, "This offer is not pending.")
            logger.error(f"Offer {offer_id} status is {status}, not pending.")
            return redirect('view_offers')
        if is_second_winner != 1:
            messages.error(request, "This is not a second winner offer.")
            logger.error(f"Offer {offer_id} is not a second winner offer.")
            return redirect('view_offers')
        if buyer_id != user_id:
            messages.error(request, "You are not authorized to accept this offer.")
            logger.error(f"User {user_id} not authorized to accept offer {offer_id} (buyer_id: {buyer_id}).")
            return redirect('view_offers')

        # Fetch buyer and seller emails for notifications
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT u.email
                FROM users u
                WHERE u.id = %s
            """, [user_id])
            buyer_email_row = cursor.fetchone()
            buyer_email = buyer_email_row[0] if buyer_email_row else None
            logger.debug(f"Buyer email for user_id {user_id}: {buyer_email}")

            cursor.execute("""
                SELECT u.id, u.email
                FROM auctions a
                JOIN users u ON a.user_id = u.id
                WHERE a.id = %s
            """, [auction_id])
            seller_row = cursor.fetchone()
            seller_id, seller_email = seller_row if seller_row else (None, None)
            logger.debug(f"Seller details for auction_id {auction_id}: seller_id={seller_id}, seller_email={seller_email}")

        # Debug: Log before performing updates
        logger.debug(f"Preparing to update tables for offer_id {offer_id}")

        # Perform updates in a transaction
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Update offers table
                cursor.execute("""
                    UPDATE offers
                    SET status = 'accepted'
                    WHERE id = %s
                """, [offer_id])
                logger.debug(f"Updated offers table: status set to 'accepted' for offer_id {offer_id}")

                # Update auctions table
                cursor.execute("""
                    UPDATE auctions
                    SET winner_user_id = %s
                    WHERE id = %s
                """, [user_id, auction_id])
                logger.debug(f"Updated auctions table: winner_user_id set to {user_id} for auction_id {auction_id}")

                # Update invoices table
                cursor.execute("""
                    UPDATE invoices
                    SET buyer_id = %s,
                        status = 'pending',
                        late_fee = 0,
                        issue_date = NOW(),
                        due_date = NOW() + INTERVAL 2 DAY
                    WHERE auction_id = %s
                """, [user_id, auction_id])
                logger.debug(f"Updated invoices table: buyer_id={user_id}, status='pending' for auction_id {auction_id}")

                # Update orders table and fetch order_id
                cursor.execute("""
                    UPDATE orders
                    SET user_id = %s,
                        shipping_address = NULL
                    WHERE auction_id = %s
                    RETURNING id
                """, [user_id, auction_id])
                order_row = cursor.fetchone()
                order_id = order_row[0] if order_row else None
                logger.debug(f"Updated orders table: user_id set to {user_id}, order_id={order_id} for auction_id {auction_id}")

                # Delete shipping details for the order_id
                if order_id:
                    cursor.execute("""
                        DELETE FROM shipping_details
                        WHERE order_id = %s
                    """, [order_id])
                    logger.debug(f"Deleted shipping details for order_id {order_id}")
                else:
                    logger.debug(f"No order found for auction_id {auction_id}, no shipping details deleted")

        # Debug: Log before sending notifications
        logger.debug(f"Preparing to send notifications for offer_id {offer_id}")

        # Notify buyer (second highest bidder)
        if buyer_email:
            due_date = timezone.now() + timedelta(days=2)
            send_email_notification(
                buyer_email,
                "Second Winner Offer Accepted",
                f"You have successfully accepted the second winner offer for auction ID {auction_id}. Please complete payment by {due_date:%Y-%m-%d %H:%M:%S}."
            )
            logger.debug(f"Sent email to buyer {buyer_email} for offer_id {offer_id}")
            notify_user(
                user_id,
                buyer_email,
                f"You accepted the second winner offer for auction ID {auction_id}. Complete the payment in the payment due section, thank you."
            )
            logger.debug(f"Sent in-app notification to buyer user_id {user_id} for offer_id {offer_id}")
        else:
            logger.warning(f"No email found for buyer user_id {user_id}")

        # Notify seller (email and in-app notification)
        if seller_id and seller_email:
            send_email_notification(
                seller_email,
                "Second Winner Offer Accepted",
                f"The second winner has accepted the offer for auction ID {auction_id}."
            )
            logger.debug(f"Sent email to seller {seller_email} for offer_id {offer_id}")
            notify_user(
                seller_id,
                seller_email,
                f"The second winner accepted the offer for auction ID {auction_id}."
            )
            logger.debug(f"Sent in-app notification to seller user_id {seller_id} for offer_id {offer_id}")
        else:
            logger.warning(f"No email or ID found for seller of auction {auction_id}.")

        messages.success(request, "Offer accepted successfully.")
        logger.info(f"User {user_id} accepted second winner offer {offer_id} for auction {auction_id}.")
        return redirect('view_offers')

    except Exception as e:
        logger.error(f"Error accepting second winner offer {offer_id}: {str(e)}")
        messages.error(request, "An error occurred while processing your request.")
        return redirect('view_offers')


def reject_second_winner_offer(request, offer_id):
    """
    Allows the second highest bidder to reject a second winner offer.
    Updates the offer status to 'rejected' and notifies both buyer and seller.
    Includes debugging logs for troubleshooting.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to reject an offer.")
        logger.error("User not logged in while attempting to reject offer.")
        return redirect('login')

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        logger.error(f"Invalid request method: {request.method}")
        return redirect('view_offers')

    try:
        # Debug: Log entry into the function
        logger.debug(f"Starting reject_second_winner_offer for offer_id: {offer_id}, user_id: {user_id}")

        # Verify the offer is a second winner offer and belongs to the user
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT auction_id, buyer_id, status, second_winner_offer
                FROM offers
                WHERE id = %s
            """, [offer_id])
            offer_row = cursor.fetchone()

        if not offer_row:
            messages.error(request, "Offer not found.")
            logger.error(f"Offer ID {offer_id} not found.")
            return redirect('view_offers')

        auction_id, buyer_id, status, is_second_winner = offer_row
        logger.debug(f"Offer details - auction_id: {auction_id}, buyer_id: {buyer_id}, status: {status}, is_second_winner: {is_second_winner}")

        # Check conditions
        if status != 'pending':
            messages.error(request, "This offer is not pending.")
            logger.error(f"Offer {offer_id} status is {status}, not pending.")
            return redirect('view_offers')
        if is_second_winner != 1:
            messages.error(request, "This is not a second winner offer.")
            logger.error(f"Offer {offer_id} is not a second winner offer.")
            return redirect('view_offers')
        if buyer_id != user_id:
            messages.error(request, "You are not authorized to reject this offer.")
            logger.error(f"User {user_id} not authorized to reject offer {offer_id} (buyer_id: {buyer_id}).")
            return redirect('view_offers')

        # Fetch buyer and seller emails for notifications
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT u.email
                FROM users u
                WHERE u.id = %s
            """, [user_id])
            buyer_email_row = cursor.fetchone()
            buyer_email = buyer_email_row[0] if buyer_email_row else None
            logger.debug(f"Buyer email for user_id {user_id}: {buyer_email}")

            cursor.execute("""
                SELECT u.id, u.email
                FROM auctions a
                JOIN users u ON a.user_id = u.id
                WHERE a.id = %s
            """, [auction_id])
            seller_row = cursor.fetchone()
            seller_id, seller_email = seller_row if seller_row else (None, None)
            logger.debug(f"Seller details for auction_id {auction_id}: seller_id={seller_id}, seller_email={seller_email}")

        # Debug: Log before performing update
        logger.debug(f"Preparing to update offers table for offer_id {offer_id}")

        # Update offers table
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE offers
                SET status = 'rejected'
                WHERE id = %s
            """, [offer_id])
            logger.debug(f"Updated offers table: status set to 'rejected' for offer_id {offer_id}")

        # Debug: Log before sending notifications
        logger.debug(f"Preparing to send notifications for offer_id {offer_id}")

        # Notify buyer (second highest bidder)
        if buyer_email:
            send_email_notification(
                buyer_email,
                "Second Winner Offer Rejected",
                f"You have rejected the second winner offer for auction ID {auction_id}."
            )
            logger.debug(f"Sent email to buyer {buyer_email} for offer_id {offer_id}")
            notify_user(
                user_id,
                buyer_email,
                f"You rejected the second winner offer for auction ID {auction_id}."
            )
            logger.debug(f"Sent in-app notification to buyer user_id {user_id} for offer_id {offer_id}")
        else:
            logger.warning(f"No email found for buyer user_id {user_id}")

        # Notify seller
        if seller_id and seller_email:
            send_email_notification(
                seller_email,
                "Second Winner Offer Rejected",
                f"The second winner has rejected the offer for auction ID {auction_id}."
            )
            logger.debug(f"Sent email to seller {seller_email} for offer_id {offer_id}")
            notify_user(
                seller_id,
                seller_email,
                f"The second winner rejected the offer for auction ID {auction_id}."
            )
            logger.debug(f"Sent in-app notification to seller user_id {seller_id} for offer_id {offer_id}")
        else:
            logger.warning(f"No email or ID found for seller of auction {auction_id}.")

        messages.success(request, "Offer rejected successfully.")
        logger.info(f"User {user_id} rejected second winner offer {offer_id} for auction {auction_id}.")
        return redirect('view_offers')

    except Exception as e:
        logger.error(f"Error rejecting second winner offer {offer_id}: {str(e)}")
        messages.error(request, "An error occurred while processing your request.")
        return redirect('view_offers')



def checkout_offer(request, offer_id):
    """
    This view is used when a buyer clicks on "Proceed to Check Out" based on an accepted offer.
    It retrieves the accepted offer details and the associated auction details,
    then overrides the auction price with the offer price and renders the payment page.
    """
    print("DEBUG: checkout_offer view called with offer_id =", offer_id)

    # Fetch offer details from the offers table
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT auction_id, offer_price, status
            FROM offers
            WHERE id = %s
        """, [offer_id])
        offer = cursor.fetchone()

    if not offer:
        messages.error(request, "Offer not found.")
        return redirect('view_offers')

    auction_id, offer_price, offer_status = offer
    print("DEBUG: Offer details fetched:", offer)

    # Ensure the offer is accepted before proceeding
    if offer_status != 'accepted':
        messages.error(request, "Offer is not accepted; cannot proceed to checkout.")
        return redirect('view_offers')

    # Fetch auction details from the auctions table
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.title, a.description, a.condition, a.condition_description, 
                   a.category, a.buy_it_now_price, a.user_id
            FROM auctions a
            WHERE a.id = %s AND a.auction_type = 'buy_it_now'
        """, [auction_id])
        auction = cursor.fetchone()
        print("DEBUG: Auction details fetched:", auction)

    if not auction:
        messages.error(request, "Auction not found.")
        return redirect('auct_list')

    # Prepare item data for the payment page
    # Override the auction price with the accepted offer price.
    item = {
        "id": auction[0],
        "title": auction[1],
        "description": auction[2],
        "condition": auction[3],
        "condition_description": auction[4],
        "category": auction[5],
        "price": float(offer_price),
        "seller_id": auction[7],
        "image_url": None,
    }

    # Fetch auction image (if available)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT image_path FROM auction_images 
            WHERE auction_id = %s 
            LIMIT 1
        """, [auction_id])
        image = cursor.fetchone()
        if image:
            item["image_url"] = f"/media/auction_images/{image[0]}"
        else:
            item["image_url"] = "/static/images/placeholder.png"

    print("DEBUG: Item for checkout:", item)

    # Calculate tax and total amount (1% tax)
    tax_rate = Decimal('0.01')
    price_decimal = Decimal(str(item["price"]))
    item["tax"] = price_decimal * tax_rate
    item["total_amount"] = price_decimal + item["tax"]
    print("DEBUG: Price:", price_decimal, "Tax:", item["tax"], "Total Amount:", item["total_amount"])

    # Render the buy_it_now_payment template with the updated item details
    return render(request, 'buy_it_now_payment.html', {"item": item})

def offer_checkout(request, offer_id):
    """Handle payment for a second winner offer with invoice and order reuse."""
    print("DEBUG: Starting offer_checkout view for offer_id:", offer_id)

    # Check if user is logged in
    user_id = request.session.get('user_id')
    if not user_id:
        print("DEBUG: No user_id found in session")
        messages.error(request, "You must be logged in to complete this offer.")
        return redirect('login')

    # Fetch offer details
    try:
        with connection.cursor() as cursor:
            print("DEBUG: Fetching offer details for offer_id:", offer_id)
            cursor.execute("""
                SELECT o.auction_id, o.buyer_id, o.offer_price, o.offer_message, o.status, 
                       o.second_winner_offer, a.title
                FROM offers o
                LEFT JOIN auctions a ON o.auction_id = a.id
                WHERE o.id = %s
            """, [offer_id])
            offer = cursor.fetchone()
            print("DEBUG: Offer fetched:", offer)
    except Exception as ex:
        print("DEBUG: Error fetching offer details")
        traceback.print_exc()
        messages.error(request, "Error fetching offer details.")
        return redirect('auct_list')

    if not offer:
        print("DEBUG: Offer not found for offer_id:", offer_id)
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, status, second_winner_offer, auction_id
                    FROM offers
                    WHERE auction_id = (SELECT auction_id FROM offers WHERE id = %s LIMIT 1)
                """, [offer_id])
                related_offers = cursor.fetchall()
                print("DEBUG: Related offers for auction:", related_offers)
        except:
            print("DEBUG: Could not fetch related offers")
        messages.error(request, "Invalid or unavailable offer.")
        return redirect('auct_list')

    auction_id, buyer_id, offer_price, offer_message, offer_status, second_winner_offer, auction_title = offer
    if offer_status != 'accepted' or not second_winner_offer:
        print("DEBUG: Offer invalid: status =", offer_status, ", second_winner_offer =", second_winner_offer)
        messages.error(request, "Invalid or unavailable offer.")
        return redirect('auct_list')

    if buyer_id != user_id:
        print("DEBUG: User_id does not match offer buyer_id:", user_id, buyer_id)
        messages.error(request, "You are not authorized to complete this offer.")
        return redirect('auct_list')

    # Fetch auction details (optional, for full data)
    auction = None
    try:
        with connection.cursor() as cursor:
            print("DEBUG: Fetching auction details for auction_id:", auction_id)
            cursor.execute("""
                SELECT a.id, a.title, a.description, a.condition, a.condition_description, 
                       a.category, a.user_id, a.status
                FROM auctions a
                WHERE a.id = %s
            """, [auction_id])
            auction = cursor.fetchone()
            print("DEBUG: Auction fetched:", auction)
            if not auction:
                cursor.execute("SELECT id, title, status FROM auctions LIMIT 10")
                all_auctions = cursor.fetchall()
                print("DEBUG: Sample auctions in database:", all_auctions)
    except Exception as ex:
        print("DEBUG: Error fetching auction details")
        traceback.print_exc()

    # Fetch auction image
    image_url = None
    try:
        with connection.cursor() as cursor:
            print("DEBUG: Fetching auction image for auction_id:", auction_id)
            cursor.execute("""
                SELECT image_path FROM auction_images 
                WHERE auction_id = %s 
                LIMIT 1
            """, [auction_id])
            image = cursor.fetchone()
            if image and image[0]:
                if image[0].startswith("/media/"):
                    image_url = image[0]
                else:
                    image_url = f"/media/auction_images/{image[0]}"
                print("DEBUG: Image URL fetched:", image_url)
            else:
                image_url = "/static/images/placeholder.png"
                print("DEBUG: No image found for auction, using placeholder")
    except Exception as ex:
        print("DEBUG: Error fetching auction image")
        traceback.print_exc()
        image_url = "/static/images/placeholder.png"

    # Prepare item data for template
    if auction:
        item = {
            "id": auction[0],
            "title": auction[1],
            "description": auction[2],
            "condition": auction[3],
            "condition_description": auction[4],
            "category": auction[5],
            "price": float(offer_price),
            "seller_id": auction[6],
            "image_url": image_url,
            "offer_id": offer_id
        }
    else:
        # Fallback for missing auction
        item = {
            "id": auction_id,
            "title": auction_title or f"Auction {auction_id}",
            "description": "Details unavailable",
            "condition": "Unknown",
            "condition_description": "Details unavailable",
            "category": "Unknown",
            "price": float(offer_price),
            "seller_id": buyer_id,  # Use buyer_id as fallback; adjust if seller_id is stored elsewhere
            "image_url": image_url,
            "offer_id": offer_id
        }
    print("DEBUG: Item prepared:", item)

    # Calculate tax and total amount (1% tax)
    tax_rate = Decimal('0.01')
    price_decimal = Decimal(str(item["price"]))
    item["tax"] = price_decimal * tax_rate
    item["total_amount"] = price_decimal + item["tax"]
    print("DEBUG: Price:", price_decimal, "Tax:", item["tax"], "Total Amount:", item["total_amount"])

    if request.method == "POST":
        print("DEBUG: POST request received")
        payment_method = request.POST.get('payment_method')
        print("DEBUG: Payment method selected:", payment_method)

        # Get shipping details from POST
        full_name = request.POST.get("full_name")
        phone = request.POST.get("phone")
        address = request.POST.get("address")
        city = request.POST.get("city")
        state = request.POST.get("state")
        zip_code = request.POST.get("zip")
        country = request.POST.get("country")
        shipping_details = f"{full_name} {phone} {address} {city} {state} {zip_code} {country}"
        print("DEBUG: Shipping details received:", shipping_details)

        # Validate shipping details
        if not all([full_name, phone, address, city, state, zip_code, country]):
            print("DEBUG: Incomplete shipping details")
            messages.error(request, "Please provide complete shipping details.")
            return render(request, 'second_winner_payment.html', {"item": item})

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Check for existing invoice
                    print("DEBUG: Checking for existing invoice for auction_id:", auction_id, "buyer_id:", user_id)
                    cursor.execute("""
                        SELECT id, status FROM invoices 
                        WHERE auction_id = %s AND buyer_id = %s AND status IN ('Pending', 'Overdue')
                    """, [auction_id, user_id])
                    existing_invoice = cursor.fetchone()
                    print("DEBUG: Existing invoice:", existing_invoice)

                    issue_date = timezone.now()
                    due_date = issue_date
                    invoice_id = None

                    if existing_invoice:
                        # Update existing invoice
                        invoice_id, invoice_status = existing_invoice
                        print("DEBUG: Updating existing invoice with id:", invoice_id)
                        cursor.execute("""
                            UPDATE invoices 
                            SET amount_due = %s, issue_date = %s, due_date = %s, status = 'Pending'
                            WHERE id = %s
                        """, [float(item["total_amount"]), issue_date, due_date, invoice_id])
                        print("DEBUG: Invoice updated successfully")
                    else:
                        # Create new invoice
                        invoice_id = uuid4().hex[:16]
                        print("DEBUG: Creating new invoice with id:", invoice_id)
                        cursor.execute("""
                            INSERT INTO invoices (id, auction_id, buyer_id, seller_id, amount_due, issue_date, due_date, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending')
                        """, [invoice_id, auction_id, user_id, item["seller_id"], float(item["total_amount"]), issue_date, due_date])
                        print("DEBUG: Invoice created successfully")

                    # Process payment
                    transaction_id = uuid4().hex[:16]
                    payment_date = timezone.now()
                    payment_amount = float(item["total_amount"])
                    print("DEBUG: Processing payment. Transaction ID:", transaction_id)

                    if payment_method == "credit_card":
                        print("DEBUG: Inserting credit card payment details")
                        cursor.execute("""
                            INSERT INTO payment_details (
                                user_id, invoice_id, auction_id, payment_method, 
                                payment_status, transaction_id, payment_amount,
                                credit_card_number, payment_date
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [user_id, invoice_id, auction_id, payment_method, 'Completed', transaction_id, payment_amount, request.POST.get("card_number"), payment_date])
                    elif payment_method == "paypal":
                        print("DEBUG: Inserting PayPal payment details")
                        cursor.execute("""
                            INSERT INTO payment_details (
                                user_id, invoice_id, auction_id, payment_method,
                                payment_status, transaction_id, payment_amount,
                                paypal_email, payment_date
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [user_id, invoice_id, auction_id, payment_method, 'Completed', transaction_id, payment_amount, request.POST.get("paypal_email"), payment_date])
                    elif payment_method == "bank_transfer":
                        print("DEBUG: Inserting bank transfer payment details")
                        cursor.execute("""
                            INSERT INTO payment_details (
                                user_id, invoice_id, auction_id, payment_method,
                                payment_status, transaction_id, payment_amount,
                                bank_account_number, bank_routing_number, payment_date
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [user_id, invoice_id, auction_id, payment_method, 'Completed', transaction_id, payment_amount, request.POST.get("iban"), request.POST.get("bic"), payment_date])
                    else:
                        raise ValueError("Invalid payment method selected")

                    print("DEBUG: Payment details inserted successfully")

                    # Update invoice status to 'Paid'
                    print("DEBUG: Updating invoice status to 'Paid'")
                    cursor.execute("""
                        UPDATE invoices 
                        SET status = 'Paid' 
                        WHERE id = %s
                    """, [invoice_id])

                    # Confirm offer status as 'accepted'
                    print("DEBUG: Confirming offer status as 'accepted'")
                    cursor.execute("""
                        UPDATE offers
                        SET status = 'accepted'
                        WHERE id = %s
                    """, [offer_id])

                    # Fetch commission percentage
                    print("DEBUG: Fetching commission percentage")
                    cursor.execute("""
                        SELECT commission_percentage FROM platform_commission 
                        WHERE auction_type = 'standard'
                        ORDER BY effective_date DESC LIMIT 1
                    """)
                    commission_row = cursor.fetchone()
                    commission_percentage = float(commission_row[0]) if commission_row else 5.00
                    print("DEBUG: Commission percentage:", commission_percentage)

                    # Calculate fund distribution amounts
                    platform_share = (commission_percentage / 100) * payment_amount
                    seller_share = payment_amount - platform_share
                    print("DEBUG: Platform share:", platform_share, "Seller share:", seller_share)

                    cursor.execute("""
                        INSERT INTO fund_distribution (invoice_id, auction_id, seller_id, platform_share, 
                                                       seller_share, status, distribution_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, [invoice_id, auction_id, item["seller_id"], platform_share, seller_share, 'Pending', payment_date])
                    print("DEBUG: Fund distribution record inserted")

                    # Check for existing order
                    print("DEBUG: Checking for existing order for auction_id:", auction_id, "user_id:", user_id, "invoice_id:", invoice_id)
                    cursor.execute("""
                        SELECT id FROM orders 
                        WHERE auction_id = %s AND user_id = %s AND invoice_id = %s
                    """, [auction_id, user_id, invoice_id])
                    existing_order = cursor.fetchone()
                    print("DEBUG: Existing order:", existing_order)

                    tracking_id = uuid4().hex[:16]
                    order_id = None

                    if existing_order:
                        # Update existing order
                        order_id = existing_order[0]
                        print("DEBUG: Updating existing order with id:", order_id)
                        cursor.execute("""
                            UPDATE orders 
                            SET payment_status = %s, payment_amount = %s, shipping_status = %s, 
                                tracking_number = %s, order_date = %s, order_status = %s, progress = %s
                            WHERE id = %s
                        """, ['paid', payment_amount, 'processing', tracking_id, payment_date, 'Confirmed', 30, order_id])
                        print("DEBUG: Order updated successfully")
                    else:
                        # Create new order
                        print("DEBUG: Inserting new order with tracking id:", tracking_id)
                        cursor.execute("""
                            INSERT INTO orders (auction_id, user_id, invoice_id, payment_status, payment_amount, 
                                                shipping_status, tracking_number, order_date, order_status, progress)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [auction_id, user_id, invoice_id, 'paid', payment_amount, 'processing', tracking_id, payment_date, 'Confirmed', 30])
                        cursor.execute("SELECT LAST_INSERT_ID()")
                        order_id = cursor.fetchone()[0]
                        print("DEBUG: Order inserted with order_id:", order_id)

                    # Insert or update shipping details
                    print("DEBUG: Checking for existing shipping details for order_id:", order_id)
                    cursor.execute("""
                        SELECT id FROM shipping_details 
                        WHERE order_id = %s AND invoice_id = %s
                    """, [order_id, invoice_id])
                    existing_shipping = cursor.fetchone()

                    if existing_shipping:
                        # Update existing shipping details
                        print("DEBUG: Updating existing shipping details for order_id:", order_id)
                        cursor.execute("""
                            UPDATE shipping_details 
                            SET full_name = %s, phone = %s, address = %s, city = %s, state = %s, 
                                zip_code = %s, country = %s, shipping_date = %s
                            WHERE order_id = %s AND invoice_id = %s
                        """, [full_name, phone, address, city, state, zip_code, country, payment_date, order_id, invoice_id])
                        print("DEBUG: Shipping details updated successfully")
                    else:
                        # Insert new shipping details
                        print("DEBUG: Inserting new shipping details")
                        cursor.execute("""
                            INSERT INTO shipping_details (order_id, invoice_id, buyer_id, full_name, phone, address, city, state, zip_code, country, shipping_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [order_id, invoice_id, user_id, full_name, phone, address, city, state, zip_code, country, payment_date])
                        print("DEBUG: Shipping details inserted successfully")

                    # Notify seller
                    print("DEBUG: Notifying seller")
                    cursor.execute("SELECT email FROM users WHERE id = %s", [item["seller_id"]])
                    seller_email = cursor.fetchone()[0]
                    seller_message = f"A payment of ₹{payment_amount:.2f} has been received for auction (ID: {auction_id}) from the second winner."
                    notify_user(item["seller_id"], seller_email, seller_message, subject="Second Winner Payment Received")

                    print("DEBUG: Payment processing completed successfully")
                    messages.success(request, "Offer payment successful!")
                    return redirect('view_orders', order_id=order_id)

        except Exception as e:
            print("DEBUG: Payment processing failed.")
            traceback.print_exc()
            messages.error(request, f"Payment processing failed: {str(e)}")
            return render(request, 'second_winner_payment.html', {"item": item})

    print("DEBUG: Rendering payment page with item:", item)
    return render(request, 'second_winner_payment.html', {"item": item})



def auct_list(request):
    category_filter = request.GET.get('category')
    price_min = request.GET.get('price_min')
    price_max = request.GET.get('price_max')
    search_keywords = request.GET.get('search')
    ending_soon = request.GET.get('ending_soon')

    logged_in_user_id = request.session.get('user_id')
    two_hours_ago = timezone.now() - timedelta(hours=2)  # Fixed: Use timezone.now()

    query = """
    SELECT 
      a.id, 
      a.title, 
      a.description, 
      a.starting_price, 
      a.end_date, 
      a.user_id, 
      a.buy_it_now_price, 
      a.is_make_offer_enabled, 
      a.auction_type,
      (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url,
      (SELECT COALESCE(MAX(b.amount), a.starting_price) 
       FROM bids b 
       WHERE b.auction_id = a.id) AS current_bid,
      u.premium
    FROM auctions a
    LEFT JOIN users u ON a.user_id = u.id
    WHERE a.end_date >= %s
      AND a.user_id != %s
      AND a.status != 'stopped'  -- Exclude stopped auctions
    """
    params = [two_hours_ago, logged_in_user_id or -1]

    if category_filter:
        query += " AND a.category_id = %s"
        params.append(category_filter)
    if price_min:
        query += " AND a.starting_price >= %s"
        params.append(price_min)
    if price_max:
        query += " AND a.starting_price <= %s"
        params.append(price_max)
    if search_keywords:
        query += " AND (a.title LIKE %s OR a.description LIKE %s)"
        params.append(f'%{search_keywords}%')
        params.append(f'%{search_keywords}%')
    if ending_soon:
        query += " ORDER BY a.end_date ASC, u.premium DESC"
    else:
        query += " ORDER BY u.premium DESC, a.id DESC"

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            auctions = []
            current_time = timezone.now()  # Use timezone.now() for consistency
            for row in cursor.fetchall():
                # row indices:
                # 0: id, 1: title, 2: description, 3: starting_price,
                # 4: end_date, 5: user_id, 6: buy_it_now_price, 7: is_make_offer_enabled,
                # 8: auction_type, 9: image_url, 10: current_bid, 11: premium
                starting_price = row[3] if row[3] is not None else 0.0
                current_bid = row[10] if row[10] is not None else starting_price
                end_date = row[4]
                if timezone.is_naive(end_date):
                    end_date = timezone.make_aware(end_date, timezone.get_current_timezone())

                auction = {
                    "id": row[0],
                    "title": row[1],
                    "description": row[2],
                    "starting_price": float(starting_price),
                    "end_date": end_date,
                    "user_id": row[5],
                    "buy_it_now_price": float(row[6]) if row[6] is not None else None,
                    "is_make_offer_enabled": bool(row[7]),
                    "auction_type": row[8],
                    "image_url": f"/media/auction_images/{row[9]}" if row[9] else "/static/images/placeholder.png",
                    "current_bid": float(current_bid),
                    "is_own_auction": False,  # Auctions created by the user are excluded
                    "is_ended": end_date <= current_time,
                }
                auctions.append(auction)
    except Exception as e:
        auctions = []
        messages.error(request, f"Error fetching auctions: {e}")
        print(f"Error fetching auctions: {e}")

    # Fetch categories
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name FROM categories")
            categories = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    except Exception as e:
        categories = []
        messages.error(request, f"Error fetching categories: {e}")
        print(f"Error fetching categories: {e}")

    return render(request, 'auct_list.html', {
        "auctions": auctions,
        "category_filter": category_filter,
        "price_min": price_min,
        "price_max": price_max,
        "search_keywords": search_keywords,
        "ending_soon": ending_soon,
        "categories": categories
    })




def place_bid(request, auction_id):
    """Handle bid placement with user restrictions, notifications, and automatic proxy bidding."""
    logger.debug(f"place_bid called with auction_id: {auction_id}")

    user_id = request.session.get('user_id')
    if not user_id:
        logger.debug("User not logged in. Redirecting to login.")
        return redirect('login')

    # Check if user is restricted
    with connection.cursor() as cursor:
        cursor.execute("SELECT bidding_restricted, premium, membership_plan_id FROM users WHERE id = %s", [user_id])
        user_status = cursor.fetchone()
    if user_status and user_status[0]:
        logger.debug(f"User {user_id} is restricted from bidding.")
        return render(request, 'bidding_restricted.html', {})

    # Determine if user can access proxy bidding (only for premium users with membership_plan_id 2 or 3)
    is_premium_proxy_eligible = user_status and user_status[1] and user_status[2] in [2, 3]

    # Fetch auction details, including reserve_price
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, title, description, starting_price, bid_increment, end_date, current_bid, user_id, reserve_price
            FROM auctions
            WHERE id = %s
        """, [auction_id])
        auction_data = cursor.fetchone()
    if not auction_data:
        logger.error(f"Auction {auction_id} not found.")
        raise Http404("Auction not found.")

    # Validate starting_price, bid_increment, and reserve_price
    if auction_data[3] is None or auction_data[4] is None or auction_data[8] is None:
        logger.error(f"Auction {auction_id} has invalid starting_price, bid_increment, or reserve_price.")
        return render(request, 'place_bid.html', {
            'auction': {'id': auction_id},
            'error': "This auction is invalid due to missing pricing information.",
            'is_premium_proxy_eligible': is_premium_proxy_eligible
        })

    auction = {
        "id": auction_data[0],
        "title": auction_data[1],
        "description": auction_data[2],
        "starting_price": float(auction_data[3]),
        "bid_increment": float(auction_data[4]),
        "end_date": auction_data[5],
        "current_bid": float(auction_data[6]) if auction_data[6] is not None else None,
        "user_id": auction_data[7],  # Seller
        "reserve_price": float(auction_data[8]),
    }

    # Fetch wallet balance
    with connection.cursor() as cursor:
        cursor.execute("SELECT balance FROM wallets WHERE user_id = %s", [user_id])
        wallet_data = cursor.fetchone()
        wallet_balance = float(wallet_data[0]) if wallet_data else 0.0

    # Check reserve price and wallet balance requirements
    reserve_price = auction["reserve_price"]
    required_balance = 0
    if reserve_price >= 20000:
        required_balance = 4000
    elif reserve_price >= 15000:
        required_balance = 3000
    elif reserve_price >= 10000:
        required_balance = 2000
    elif reserve_price >= 5000:
        required_balance = 1000

    if required_balance > 0 and wallet_balance < required_balance:
        logger.debug(f"User {user_id} has insufficient wallet balance ({wallet_balance}) .")
        return render(request, 'place_bid.html', {
            'auction': auction,
            'current_bid': auction["current_bid"],
            'min_bid': auction["current_bid"] + auction["bid_increment"] if auction["current_bid"] else auction["starting_price"] + auction["bid_increment"],
            'error': f"This auction requires a minimum wallet balance of ₹{required_balance:.2f} . Your current balance is ₹{wallet_balance:.2f}.",
            'show_reserve_wallet_error': True,
            'is_premium_proxy_eligible': is_premium_proxy_eligible
        })

    # Get current highest bidder and their email
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT user_id, (SELECT email FROM users WHERE id = bids.user_id)
            FROM bids
            WHERE auction_id = %s
            ORDER BY amount DESC
            LIMIT 1
        """, [auction_id])
        highest_bidder_data = cursor.fetchone()
    current_highest_bidder_id = highest_bidder_data[0] if highest_bidder_data else None
    current_highest_bidder_email = highest_bidder_data[1] if highest_bidder_data else None

    # Prevent consecutive bids
    if current_highest_bidder_id == user_id:
        logger.debug(f"User {user_id} attempted consecutive bidding.")
        return render(request, 'place_bid.html', {
            'auction': auction,
            'current_bid': auction["current_bid"],
            'min_bid': auction["current_bid"] + auction["bid_increment"] if auction["current_bid"] else auction["starting_price"] + auction["bid_increment"],
            'error': "You cannot place consecutive bids.",
            'disable_bid': True,
            'is_premium_proxy_eligible': is_premium_proxy_eligible
        })

    # Calculate minimum bid amount
    current_bid = auction["current_bid"] if auction["current_bid"] is not None else auction["starting_price"]
    min_bid = current_bid + auction["bid_increment"]

    # Check if auction has ended
    end_date = make_aware(auction["end_date"]) if is_naive(auction["end_date"]) else auction["end_date"]
    if end_date < timezone.now():
        logger.debug(f"Auction {auction_id} has ended.")
        return render(request, 'place_bid.html', {
            'auction': auction,
            'min_bid': min_bid,
            'current_bid': current_bid,
            'error': "This auction has ended.",
            'is_premium_proxy_eligible': is_premium_proxy_eligible
        })

    # Fetch current user's email
    with connection.cursor() as cursor:
        cursor.execute("SELECT email FROM users WHERE id = %s", [user_id])
        current_user_email = cursor.fetchone()[0]

    # Fetch seller's email
    with connection.cursor() as cursor:
        cursor.execute("SELECT email FROM users WHERE id = %s", [auction["user_id"]])
        seller_email = cursor.fetchone()[0]

    if request.method == 'POST':
        bid_amount_str = request.POST.get('bid_amount')
        enable_auto_bid = request.POST.get('enable_auto_bid') == 'on'
        proxy_bid_str = request.POST.get('proxy_bid')

        try:
            # Fetch all existing proxy bids (excluding the current user)
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT user_id, proxy_max_amount, amount, (SELECT email FROM users WHERE id = bids.user_id)
                    FROM bids
                    WHERE auction_id = %s AND is_proxy = TRUE AND user_id != %s
                    ORDER BY created_at ASC
                """, [auction_id, user_id])
                proxy_bids = [(row[0], float(row[1]), float(row[2]), row[3]) for row in cursor.fetchall()]

            # Handle proxy bid (only for eligible users)
            if enable_auto_bid and proxy_bid_str:
                if not is_premium_proxy_eligible:
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': min_bid,
                        'current_bid': current_bid,
                        'error': "Proxy bidding is available only for Standard or Premium plan members. Upgrade to access this feature.",
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })

                try:
                    proxy_bid = float(proxy_bid_str)
                except ValueError:
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': min_bid,
                        'current_bid': current_bid,
                        'error': "Invalid maximum proxy bid amount. Please enter a number.",
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })

                # Check wallet balance for proxy bid
                if proxy_bid > wallet_balance:
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': min_bid,
                        'current_bid': current_bid,
                        'error': f"Your maximum proxy bid of ₹{proxy_bid:.2f} exceeds your wallet balance of ₹{wallet_balance:.2f}. Please add funds to your wallet.",
                        'show_wallet_error': True,
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })

                if proxy_bid < min_bid:
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': min_bid,
                        'current_bid': current_bid,
                        'error': f"Your maximum bid must be at least ₹{min_bid:.2f}.",
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })

                # Determine initial bid amount considering existing bids/proxies
                if not proxy_bids and auction["current_bid"] is None:
                    # No prior bids: start with starting_price + bid_increment
                    new_bid_amount = min(auction["starting_price"] + auction["bid_increment"], proxy_bid)
                else:
                    # Existing bids: compete with highest proxy or current bid
                    highest_competing = max([pb[1] for pb in proxy_bids] + [current_bid], default=auction["starting_price"])
                    new_bid_amount = min(highest_competing + auction["bid_increment"], proxy_bid)

                with connection.cursor() as cursor:
                    # Insert new proxy bid
                    cursor.execute("""
                        INSERT INTO bids (auction_id, user_id, amount, is_proxy, proxy_max_amount)
                        VALUES (%s, %s, %s, %s, %s)
                    """, [auction_id, user_id, new_bid_amount, True, proxy_bid])
                    # Update auction's current bid
                    cursor.execute("""
                        UPDATE auctions
                        SET current_bid = %s
                        WHERE id = %s
                    """, [new_bid_amount, auction_id])
                    # Fetch updated current_bid to ensure accuracy
                    cursor.execute("SELECT current_bid FROM auctions WHERE id = %s", [auction_id])
                    updated_current_bid = float(cursor.fetchone()[0])

                # Notify previous highest bidder
                if current_highest_bidder_id and current_highest_bidder_id != user_id:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT username FROM users WHERE id = %s", [user_id])
                        new_bidder_username = cursor.fetchone()[0]
                    outbid_message = f"You have been outbid on auction '{auction['title']}' by {new_bidder_username}. New bid: ₹{new_bid_amount:.2f}."
                    notify_user(current_highest_bidder_id, current_highest_bidder_email, outbid_message, "Outbid Alert")
                    try:
                        send_mail(
                            "Outbid Alert",
                            outbid_message,
                            settings.DEFAULT_FROM_EMAIL,
                            [current_highest_bidder_email],
                            fail_silently=False
                        )
                    except Exception as e:
                        logger.error(f"Failed to send outbid email to {current_highest_bidder_email}: {str(e)}")

                # Notify seller
                seller_message = f"A proxy bid up to ₹{proxy_bid:.2f} was placed on auction '{auction['title']}'. Current bid: ₹{new_bid_amount:.2f}."
                notify_user(auction["user_id"], seller_email, seller_message, "New Bid Alert")
                try:
                    send_mail(
                        "New Bid Alert",
                        seller_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [seller_email],
                        fail_silently=False
                    )
                except Exception as e:
                    logger.error(f"Failed to send new bid email to seller {seller_email}: {str(e)}")

                logger.debug(f"Proxy bid placed. New current_bid: {updated_current_bid}")
                return render(request, 'place_bid.html', {
                    'auction': auction,
                    'min_bid': updated_current_bid + auction["bid_increment"],
                    'current_bid': updated_current_bid,
                    'success': f"Your maximum bid of ₹{proxy_bid:.2f} has been set. Current bid is ₹{new_bid_amount:.2f}.",
                    'is_premium_proxy_eligible': is_premium_proxy_eligible
                })

            # Handle regular bid
            elif bid_amount_str and not enable_auto_bid:
                try:
                    bid_amount = float(bid_amount_str)
                except ValueError:
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': min_bid,
                        'current_bid': current_bid,
                        'error': "Invalid bid amount. Please enter a number.",
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })

                if bid_amount < min_bid:
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': min_bid,
                        'current_bid': current_bid,
                        'error': f"Your bid must be at least ₹{min_bid:.2f}.",
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })

                # Simulate bidding war with proxy bids
                bids_to_insert = [(user_id, bid_amount, False, None, current_user_email)]
                latest_bid = bid_amount
                active_proxy_users = set(pb[0] for pb in proxy_bids)

                while True:
                    # Find the highest proxy that can outbid the latest bid
                    next_proxy = None
                    for proxy_user_id, proxy_max, proxy_amount, proxy_email in proxy_bids:
                        if proxy_max > latest_bid and proxy_user_id not in [b[0] for b in bids_to_insert]:
                            next_proxy = (proxy_user_id, proxy_max, proxy_amount, proxy_email)
                            break

                    if not next_proxy:
                        break

                    proxy_user_id, proxy_max, _, proxy_email = next_proxy
                    new_proxy_bid = min(latest_bid + auction["bid_increment"], proxy_max)
                    bids_to_insert.append((proxy_user_id, new_proxy_bid, True, proxy_max, proxy_email))
                    latest_bid = new_proxy_bid
                    active_proxy_users.add(proxy_user_id)

                with connection.cursor() as cursor:
                    for bid_user_id, amount, is_proxy, proxy_max, email in bids_to_insert:
                        if is_proxy and proxy_max:
                            cursor.execute("""
                                INSERT INTO bids (auction_id, user_id, amount, is_proxy, proxy_max_amount)
                                VALUES (%s, %s, %s, %s, %s)
                            """, [auction_id, bid_user_id, amount, True, proxy_max])
                        else:
                            cursor.execute("""
                                INSERT INTO bids (auction_id, user_id, amount, is_proxy)
                                VALUES (%s, %s, %s, %s)
                            """, [auction_id, bid_user_id, amount, False])
                    cursor.execute("""
                        UPDATE auctions
                        SET current_bid = %s
                        WHERE id = %s
                    """, [latest_bid, auction_id])
                    # Fetch updated current_bid to ensure accuracy
                    cursor.execute("SELECT current_bid FROM auctions WHERE id = %s", [auction_id])
                    updated_current_bid = float(cursor.fetchone()[0])

                # In the regular bid branch, if the final bid is from a proxy (i.e., user was outbid)
                if bids_to_insert[-1][0] != user_id:
                    outbid_message = f"Your bid of ₹{bid_amount:.2f} on '{auction['title']}' was outbid by an auto-bid. New bid: ₹{latest_bid:.2f}."
                    notify_user(user_id, current_user_email, outbid_message, "Outbid Alert")
                    try:
                        send_mail(
                            "Outbid Alert",
                            outbid_message,
                            settings.DEFAULT_FROM_EMAIL,
                            [current_user_email],
                            fail_silently=False
                        )
                    except Exception as e:
                        logger.error(f"Failed to send outbid email to {current_user_email}: {str(e)}")
                    seller_message = f"A bid of ₹{bid_amount:.2f} was outbid by an auto-bid on '{auction['title']}'. New bid: ₹{latest_bid:.2f}."
                    notify_user(auction["user_id"], seller_email, seller_message, "New Bid Alert")
                    try:
                        send_mail(
                            "New Bid Alert",
                            seller_message,
                            settings.DEFAULT_FROM_EMAIL,
                            [seller_email],
                            fail_silently=False
                        )
                    except Exception as e:
                        logger.error(f"Failed to send new bid email to seller {seller_email}: {str(e)}")
                    logger.debug(f"Regular bid outbid. New current_bid: {updated_current_bid}")
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': updated_current_bid + auction["bid_increment"],
                        'current_bid': updated_current_bid,
                        'error': f"Your bid of ₹{bid_amount:.2f} was outbid by an auto-bid. New bid is ₹{latest_bid:.2f}.",
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })
                else:
                    if current_highest_bidder_id and current_highest_bidder_id != user_id:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT username FROM users WHERE id = %s", [user_id])
                            new_bidder_username = cursor.fetchone()[0]
                        outbid_message = f"You have been outbid on '{auction['title']}' by {new_bidder_username}. New bid: ₹{bid_amount:.2f}."
                        notify_user(current_highest_bidder_id, current_highest_bidder_email, outbid_message, "Outbid Alert")
                        try:
                            send_mail(
                                "Outbid Alert",
                                outbid_message,
                                settings.DEFAULT_FROM_EMAIL,
                                [current_highest_bidder_email],
                                fail_silently=False
                            )
                        except Exception as e:
                            logger.error(f"Failed to send outbid email to {current_highest_bidder_email}: {str(e)}")
                    seller_message = f"A bid of ₹{bid_amount:.2f} was placed on '{auction['title']}'."
                    notify_user(auction["user_id"], seller_email, seller_message, "New Bid Alert")
                    try:
                        send_mail(
                            "New Bid Alert",
                            seller_message,
                            settings.DEFAULT_FROM_EMAIL,
                            [seller_email],
                            fail_silently=False
                        )
                    except Exception as e:
                        logger.error(f"Failed to send new bid email to seller {seller_email}: {str(e)}")
                    logger.debug(f"Regular bid placed. New current_bid: {updated_current_bid}")
                    return render(request, 'place_bid.html', {
                        'auction': auction,
                        'min_bid': updated_current_bid + auction["bid_increment"],
                        'current_bid': updated_current_bid,
                        'success': f"Your bid of ₹{bid_amount:.2f} was placed.",
                        'is_premium_proxy_eligible': is_premium_proxy_eligible
                    })

            else:
                return render(request, 'place_bid.html', {
                    'auction': auction,
                    'min_bid': min_bid,
                    'current_bid': current_bid,
                    'error': "Please enter a bid amount or a maximum proxy bid.",
                    'is_premium_proxy_eligible': is_premium_proxy_eligible
                })

        except Exception as e:
            logger.error(f"Bid processing failed: {str(e)}")
            return render(request, 'place_bid.html', {
                'auction': auction,
                'min_bid': min_bid,
                'current_bid': current_bid,
                'error': "Error placing bid.",
                'is_premium_proxy_eligible': is_premium_proxy_eligible
            })

    # For the initial GET request, re-fetch the current bid from the auctions table
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_bid FROM auctions WHERE id = %s", [auction_id])
        refreshed = cursor.fetchone()
    refreshed_current_bid = float(refreshed[0]) if refreshed and refreshed[0] is not None else auction["starting_price"]
    # Update the values accordingly
    current_bid = refreshed_current_bid
    min_bid = current_bid + auction["bid_increment"]
    auction["current_bid"] = current_bid

    logger.debug(f"Initial render. Current bid: {current_bid}")
    return render(request, 'place_bid.html', {
        'auction': auction,
        'min_bid': min_bid,
        'current_bid': current_bid,
        'is_premium_proxy_eligible': is_premium_proxy_eligible
    })

def place_sealed_bid(request, auction_id):
    """Handles placing a sealed bid with user restrictions and seller notifications."""
    print(f"[DEBUG] place_sealed_bid called with auction_id: {auction_id}")

    # Check if the user is logged in
    user_id = request.session.get('user_id')
    if not user_id:
        print("[DEBUG] User not logged in. Redirecting to login.")
        messages.error(request, "You must be logged in to place a bid.")
        return redirect('auth_page')

    # Check for existing bid by the user for this auction
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM bids WHERE auction_id = %s AND user_id = %s
        """, [auction_id, user_id])
        bid_count = cursor.fetchone()[0]
    if bid_count > 0:
        messages.error(request, "You have already placed a bid for this auction. Only one bid per user is allowed.")
        return render(request, 'place_sealed_bid.html', {
            'auction_id': auction_id,
            'error': "You have already placed a bid for this auction. Only one bid per user is allowed."
        })

    # Fetch auction details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT user_id, starting_price, bid_increment, end_date
            FROM auctions
            WHERE id = %s
        """, [auction_id])
        auction_data = cursor.fetchone()
    if not auction_data:
        print(f"[ERROR] Auction {auction_id} not found.")
        messages.error(request, "Auction not found.")
        return redirect('auct_deta', auction_id=auction_id)

    # Set defaults for starting_price and bid_increment if None
    starting_price = float(auction_data[1]) if auction_data[1] is not None else 0.0
    bid_increment = float(auction_data[2]) if auction_data[2] is not None else 1.0

    auction = {
        "user_id": auction_data[0],  # Seller ID
        "starting_price": starting_price,
        "bid_increment": bid_increment,
        "end_date": auction_data[3],
    }

    # Check if auction has ended
    end_date = timezone.make_aware(auction["end_date"]) if timezone.is_naive(auction["end_date"]) else auction["end_date"]
    if end_date < timezone.now():
        print(f"[DEBUG] Auction {auction_id} has ended.")
        messages.error(request, "This auction has ended.")
        return render(request, 'place_sealed_bid.html', {
            'auction_id': auction_id,
            'error': "This auction has ended."
        })

    # Fetch seller's email
    with connection.cursor() as cursor:
        cursor.execute("SELECT email FROM users WHERE id = %s", [auction["user_id"]])
        seller_email_data = cursor.fetchone()
    seller_email = seller_email_data[0] if seller_email_data else None

    # Calculate minimum bid amount (optional, kept for context but not enforced)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT MAX(amount) FROM bids WHERE auction_id = %s
        """, [auction_id])
        max_bid = cursor.fetchone()[0]
    current_bid = float(max_bid) if max_bid is not None else None
    min_bid = (current_bid + auction["bid_increment"]) if current_bid is not None else auction["starting_price"]

    if request.method == 'POST':
        amount_str = request.POST.get('amount')

        try:
            current_timestamp = timezone.now()

            # Handle regular bid
            if amount_str:
                try:
                    amount = float(amount_str)
                    if amount <= 0:
                        messages.error(request, "Bid amount must be a positive number.")
                        return render(request, 'place_sealed_bid.html', {
                            'auction_id': auction_id,
                            'error': "Bid amount must be a positive number.",
                            'current_bid': current_bid,
                            'min_bid': min_bid
                        })
                except ValueError:
                    messages.error(request, "Invalid bid amount. Please enter a number.")
                    return render(request, 'place_sealed_bid.html', {
                        'auction_id': auction_id,
                        'error': "Invalid bid amount. Please enter a number.",
                        'current_bid': current_bid,
                        'min_bid': min_bid
                    })

                # For regular sealed bids, allow any positive amount (no minimum bid requirement)
                with connection.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO bids (auction_id, user_id, amount, is_proxy, bid_time, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, [auction_id, user_id, amount, False, current_timestamp, current_timestamp])

                # Notify seller
                if seller_email:
                    notification_message = f"A new sealed bid of ${amount:.2f} has been placed on your auction (ID: {auction_id})."
                    # Assuming create_notification is defined elsewhere
                    create_notification(auction["user_id"], notification_message, email_subject="New Sealed Bid Alert")
                    email_subject = "New Sealed Bid Alert"
                    email_message = (
                        f"Hello,\n\n"
                        f"A new sealed bid of ${amount:.2f} has been placed on your auction (ID: {auction_id}).\n\n"
                        f"Best regards,\nZinCo Auction Team"
                    )
                    try:
                        send_mail(email_subject, email_message, settings.DEFAULT_FROM_EMAIL, [seller_email])
                    except Exception as e:
                        logger.error(f"Failed to send bid email to {seller_email}: {str(e)}")

                messages.success(request, f"Your bid of ${amount:.2f} has been placed successfully!")
                print(f"[DEBUG] Regular bid placed. New bid: {amount}")
                return redirect('sealed_thanks', auction_id=auction_id)
            else:
                messages.error(request, "Please enter a bid amount.")
                return render(request, 'place_sealed_bid.html', {
                    'auction_id': auction_id,
                    'error': "Please enter a bid amount.",
                    'current_bid': current_bid,
                    'min_bid': min_bid
                })

        except Exception as e:
            print(f"[ERROR] Failed to place sealed bid: {e}")
            messages.error(request, "An error occurred while placing your bid. Please try again.")
            return render(request, 'place_sealed_bid.html', {
                'auction_id': auction_id,
                'error': "An error occurred while placing your bid. Please try again.",
                'current_bid': current_bid,
                'min_bid': min_bid
            })

    # If GET request, render the bid form
    return render(request, 'place_sealed_bid.html', {
        'auction_id': auction_id,
        'current_bid': current_bid,
        'min_bid': min_bid
    })

def auct_deta(request, auction_id):
    # Store sender ID in session if user is authenticated
    if request.user.is_authenticated:
        request.session['sender_id'] = request.user.id

    # Initialize or get viewed auctions from session
    viewed_auctions = request.session.get('viewed_auctions', [])

    # Fetch auction details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                a.id, 
                a.title, 
                a.description, 
                a.category, 
                a.starting_price, 
                a.current_bid, 
                a.bid_increment, 
                a.reserve_price,
                a.start_date, 
                a.end_date, 
                a.user_id, 
                a.auction_type, 
                a.winner_user_id,
                (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url,
                a.buy_it_now_price, 
                a.is_make_offer_enabled,
                a.status,
                a.condition,
                a.condition_description,
                a.views_count,
                u.premium
            FROM auctions a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE a.id = %s
        """, [auction_id])
        auction = cursor.fetchone()

    if not auction:
        raise Http404("Auction not found.")

    # Map auction data
    auction_data = {
        'id': auction[0],
        'title': auction[1],
        'description': auction[2],
        'category': auction[3],
        'starting_price': auction[4],
        'current_bid': auction[5],  # Directly use current_bid from auctions table
        'bid_increment': auction[6],
        'reserve_price': auction[7],
        'start_date': auction[8],
        'end_date': auction[9],
        'user_id': auction[10],
        'auction_type': auction[11],
        'winner_user_id': auction[12],
        'image_url': f"/media/auction_images/{auction[13]}" if auction[13] else "/static/images/placeholder.png",
        'buy_it_now_price': auction[14],
        'is_make_offer_enabled': auction[15],
        'status': auction[16],
        'condition': auction[17],
        'condition_description': auction[18],
        'views_count': auction[19],
        'premium': auction[20],  # Fetch premium status directly from the query
    }

    # Debug: Print current_bid to verify
    print(f"Fetching current_bid for auction {auction_id}: {auction_data['current_bid']}")

    # Increment views_count only if the user hasn't viewed this auction before
    if auction_id not in viewed_auctions:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE auctions SET views_count = views_count + 1 WHERE id = %s", [auction_id])
            cursor.execute("SELECT views_count FROM auctions WHERE id = %s", [auction_id])
            auction_data['views_count'] = cursor.fetchone()[0]
        viewed_auctions.append(auction_id)
        request.session['viewed_auctions'] = viewed_auctions
        request.session.modified = True

    # Make datetimes timezone-aware
    if timezone.is_naive(auction_data['start_date']):
        auction_data['start_date'] = timezone.make_aware(auction_data['start_date'], timezone.get_current_timezone())
    if timezone.is_naive(auction_data['end_date']):
        auction_data['end_date'] = timezone.make_aware(auction_data['end_date'], timezone.get_current_timezone())

    # Update auction status to "Closed" if past end date (unless stopped or closed)
    current_time = timezone.now()
    if current_time > auction_data['end_date'] and auction_data['status'].lower() not in ['closed', 'stopped']:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE auctions SET status = 'closed' WHERE id = %s", [auction_id])
        auction_data['status'] = "closed"

    # Fetch seller details
    with connection.cursor() as cursor:
        cursor.execute("SELECT username, email, profile_picture FROM users WHERE id = %s", [auction_data['user_id']])
        user = cursor.fetchone()

    profile_picture_path = user[2] if user and user[2] else ""
    if profile_picture_path:
        if profile_picture_path.startswith("/") or profile_picture_path.startswith("http"):
            final_profile_picture = profile_picture_path
        else:
            final_profile_picture = f"/media/{profile_picture_path}"
    else:
        final_profile_picture = "/static/images/default_profile.png"

    auction_data['user'] = {
        'username': user[0] if user else "Unknown User",
        'email': user[1] if user else "No Email",
        'profile_picture': final_profile_picture,
    }

    # Initialize winner details
    winner = None
    winner_available = False

    if current_time > auction_data['end_date'] and auction_data.get('winner_user_id') and auction_data['status'] == 'closed':
        winner_available = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT username, email, profile_picture FROM users WHERE id = %s", [auction_data['winner_user_id']])
            winner_data = cursor.fetchone()
        if winner_data:
            winner_profile = winner_data[2] if winner_data[2] else ""
            if winner_profile:
                if winner_profile.startswith("/") or winner_profile.startswith("http"):
                    final_winner_profile = winner_profile
                else:
                    final_winner_profile = f"/media/{winner_profile}"
            else:
                final_winner_profile = "/static/images/default_profile.png"
            winner = {
                'user_id': auction_data['winner_user_id'],
                'username': winner_data[0],
                'email': winner_data[1],
                'profile_picture': final_winner_profile,
                'final_price': auction_data['current_bid']
            }

    auction_data['winner'] = winner
    auction_data['winner_available'] = winner_available

    # Fetch all images
    with connection.cursor() as cursor:
        cursor.execute("SELECT image_path FROM auction_images WHERE auction_id = %s", [auction_data['id']])
        images = cursor.fetchall()
    auction_data['images'] = [f"/media/auction_images/{img[0]}" for img in images if img and img[0]]

    # Add flag for stopped status
    is_stopped = auction_data['status'].lower() == 'stopped'

    return render(request, 'auct_deta.html', {
        'auction': auction_data,
        'now': current_time,
        'sender_id': request.session.get('sender_id'),
        'is_stopped': is_stopped,
    })
# For example, in your views.py or a similar Python file
def add_to_watchlist(request, auction_id):
    user_id = request.session.get('user_id')  # Fetch the user ID from the session
    if not user_id:
        return redirect('auth_page')  # Redirect to login if the user is not logged in

    # Insert into the watchlist table
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO watchlist (user_id, auction_id, auction_type)
            SELECT %s, %s, a.auction_type
            FROM auctions a
            WHERE a.id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM watchlist
                  WHERE user_id = %s AND auction_id = %s
              )
        """, [user_id, auction_id, auction_id, user_id, auction_id])

    return redirect('watchlist')  # Redirect to the watchlist page

# Display watchlist
def watchlist(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('auth_page')  # Redirect to login if the user is not logged in

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                a.id, 
                a.title, 
                a.description, 
                a.category, 
                a.starting_price, 
                a.current_bid, 
                a.bid_increment, 
                a.reserve_price,
                a.start_date, 
                a.end_date, 
                a.user_id, 
                a.auction_type, 
                a.winner_user_id,
                (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url,
                a.buy_it_now_price, 
                a.is_make_offer_enabled,
                a.status,
                a.condition,
                a.condition_description,
                CASE 
                    WHEN a.end_date < NOW() THEN 'Expired'
                    ELSE 'Active'
                END AS auction_status
            FROM watchlist w
            INNER JOIN auctions a ON w.auction_id = a.id
            WHERE w.user_id = %s
            ORDER BY a.end_date DESC
        """, [user_id])
        items = cursor.fetchall()

    # Map the rows into a list of dictionaries.
    watchlist_items = []
    for row in items:
        auction_data = {
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'category': row[3],
            'starting_price': row[4],
            'current_bid': row[5],
            'bid_increment': row[6],
            'reserve_price': row[7],
            'start_date': row[8],
            'end_date': row[9],
            'user_id': row[10],
            'auction_type': row[11],
            'winner_user_id': row[12],
            'image_url': f"/media/auction_images/{row[13]}" if row[13] else "/static/images/placeholder.png",
            'buy_it_now_price': row[14],
            'is_make_offer_enabled': row[15],
            'status': row[16],
            'condition': row[17],
            'condition_description': row[18],
            'auction_status': row[19],
        }
        watchlist_items.append(auction_data)

    return render(request, 'watchlist.html', {'items': watchlist_items})

def remove_from_watchlist(request, auction_id):
    """
    Remove an auction from the user's watchlist.
    Only allows removal via POST requests.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to remove an item from your watchlist.")
        return redirect('auth_page')  # Change to your login URL name if needed

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect('watchlist')  # Change to your watchlist URL name if needed

    try:
        with connection.cursor() as cursor:
            # Delete the watchlist entry where both auction_id and user_id match.
            cursor.execute("""
                DELETE FROM watchlist
                WHERE auction_id = %s AND user_id = %s
            """, [auction_id, user_id])
        messages.success(request, "Auction removed from your watchlist successfully.")
    except Exception as e:
        messages.error(request, "An error occurred while removing the auction from your watchlist.")
        # Optionally log the exception:
        # logger.error(f"Error removing auction {auction_id} from watchlist for user {user_id}: {str(e)}")
    return redirect('watchlist')


def profman(request):
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to manage your profile.")
        logger.error("Unauthorized access attempt to profman view: No user_id in session.")
        return redirect('login')

    logger.debug(f"User ID: {user_id} accessing profman view.")

    if request.method == "POST":
        logger.info(f"Received POST request for user ID: {user_id}")

        # Handle selfie-only submission
        if 'selfie_submit' in request.POST:
            logger.debug("Processing selfie-only submission.")
            selfie_data = request.POST.get('selfie')
            logger.debug(f"Selfie data present: {bool(selfie_data)}")

            if not selfie_data:
                logger.error("No selfie data provided in selfie_submit.")
                messages.error(request, "Please capture a selfie before submitting.")
                return redirect('profman')

            # Save selfie
            try:
                selfie_filename = f"{uuid.uuid4().hex}_selfie.jpg"
                selfie_relative_path = os.path.join('selfies', selfie_filename)
                upload_folder = os.path.join(settings.MEDIA_ROOT, 'selfies')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                full_file_path = os.path.join(settings.MEDIA_ROOT, selfie_relative_path)
                logger.debug(f"Saving selfie to: {full_file_path}")

                selfie_data = selfie_data.split(',')[1]  # Remove data:image/jpeg;base64,
                with open(full_file_path, 'wb') as destination:
                    destination.write(base64.b64decode(selfie_data))
                selfie_relative_path = selfie_relative_path.replace("\\", "/")
                logger.debug(f"Selfie saved successfully at: {selfie_relative_path}")

                # Update database
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE users
                        SET selfie = %s, account_status = 'pending'
                        WHERE id = %s
                    """, [selfie_relative_path, user_id])
                    cursor.execute("""
                        INSERT INTO user_activity (user_id, description)
                        VALUES (%s, 'Submitted selfie for verification.')
                    """, [user_id])
                logger.info(f"Selfie submitted successfully for user ID: {user_id}")
                messages.success(request, "Selfie submitted for verification. Awaiting admin approval.")
            except Exception as e:
                logger.error(f"Error processing selfie submission for user ID: {user_id}: {str(e)}")
                messages.error(request, "An error occurred while submitting the selfie. Please try again.")
            return redirect('profman')

        # Handle ID proof and selfie submission
        if 'id_proof_submit' in request.POST:
            logger.debug("Processing ID proof and selfie submission.")
            id_proof = request.FILES.get('id_proof')
            selfie_data = request.POST.get('selfie')
            logger.debug(f"ID proof present: {bool(id_proof)}, Selfie data present: {bool(selfie_data)}")

            if not id_proof or not selfie_data:
                logger.error("Missing ID proof or selfie data in id_proof_submit.")
                messages.error(request, "Please upload both ID proof and selfie for verification.")
                return redirect('profman')

            # Save ID proof
            try:
                id_proof_filename = f"{uuid.uuid4().hex}_{id_proof.name}"
                id_proof_relative_path = os.path.join('id_proofs', id_proof_filename)
                upload_folder = os.path.join(settings.MEDIA_ROOT, 'id_proofs')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                full_file_path = os.path.join(settings.MEDIA_ROOT, id_proof_relative_path)
                logger.debug(f"Saving ID proof to: {full_file_path}")
                with open(full_file_path, 'wb+') as destination:
                    for chunk in id_proof.chunks():
                        destination.write(chunk)
                id_proof_relative_path = id_proof_relative_path.replace("\\", "/")
                logger.debug(f"ID proof saved successfully at: {id_proof_relative_path}")

                # Save selfie
                selfie_filename = f"{uuid.uuid4().hex}_selfie.jpg"
                selfie_relative_path = os.path.join('selfies', selfie_filename)
                upload_folder = os.path.join(settings.MEDIA_ROOT, 'selfies')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                full_file_path = os.path.join(settings.MEDIA_ROOT, selfie_relative_path)
                logger.debug(f"Saving selfie to: {full_file_path}")
                selfie_data = selfie_data.split(',')[1]  # Remove data:image/jpeg;base64,
                with open(full_file_path, 'wb') as destination:
                    destination.write(base64.b64decode(selfie_data))
                selfie_relative_path = selfie_relative_path.replace("\\", "/")
                logger.debug(f"Selfie saved successfully at: {selfie_relative_path}")

                # Update database
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE users
                        SET id_proof = %s, selfie = %s, account_status = 'pending'
                        WHERE id = %s
                    """, [id_proof_relative_path, selfie_relative_path, user_id])
                    cursor.execute("""
                        INSERT INTO user_activity (user_id, description)
                        VALUES (%s, 'Submitted ID proof and selfie for verification.')
                    """, [user_id])
                logger.info(f"ID proof and selfie submitted successfully for user ID: {user_id}")
                messages.success(request, "ID proof and selfie submitted for verification. Awaiting admin approval.")
            except Exception as e:
                logger.error(f"Error processing ID proof and selfie submission for user ID: {user_id}: {str(e)}")
                messages.error(request, "An error occurred while submitting ID proof and selfie. Please try again.")
            return redirect('profman')

        # Handle full profile update (including optional ID proof and selfie)
        else:
            logger.debug("Processing full profile update.")
            # Fetch current data to preserve unchanged fields
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT username, email, phone, address, pincode,
                           email_notifications, sms_notifications,
                           bank_account_number, paypal_email, profile_picture, id_proof, selfie
                    FROM users WHERE id = %s
                """, [user_id])
                current_data = cursor.fetchone()

            username = request.POST.get('username', current_data[0])
            email = request.POST.get('email', current_data[1])
            phone = request.POST.get('phone', current_data[2])
            address = request.POST.get('address', current_data[3])
            pincode = request.POST.get('pincode', current_data[4] or '')
            email_notifications = 1 if request.POST.get('email_notifications') == 'on' else (0 if request.POST.get('email_notifications') == 'off' else current_data[5])
            sms_notifications = 1 if request.POST.get('sms_notifications') == 'on' else (0 if request.POST.get('sms_notifications') == 'off' else current_data[6])
            bank_account_number = request.POST.get('bank_account_number', current_data[7])
            paypal_email = request.POST.get('paypal_email', current_data[8])

            # Handle profile picture upload
            profile_picture = request.FILES.get('profile_picture')
            profile_pic_relative_path = current_data[9]
            if profile_picture:
                unique_filename = f"{uuid.uuid4().hex}_{profile_picture.name}"
                profile_pic_relative_path = os.path.join('profile_pictures', unique_filename)
                upload_folder = os.path.join(settings.MEDIA_ROOT, 'profile_pictures')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                full_file_path = os.path.join(settings.MEDIA_ROOT, profile_pic_relative_path)
                logger.debug(f"Saving profile picture to: {full_file_path}")
                with open(full_file_path, 'wb+') as destination:
                    for chunk in profile_picture.chunks():
                        destination.write(chunk)
                profile_pic_relative_path = profile_pic_relative_path.replace("\\", "/")
                logger.debug(f"Profile picture saved successfully at: {profile_pic_relative_path}")

            # Handle ID proof upload (optional)
            id_proof = request.FILES.get('id_proof')
            id_proof_relative_path = current_data[10]
            if id_proof:
                if current_data[10]:
                    old_file_path = os.path.join(settings.MEDIA_ROOT, current_data[10])
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                        logger.debug(f"Removed old ID proof: {old_file_path}")
                unique_filename = f"{uuid.uuid4().hex}_{id_proof.name}"
                id_proof_relative_path = os.path.join('id_proofs', unique_filename)
                upload_folder = os.path.join(settings.MEDIA_ROOT, 'id_proofs')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                full_file_path = os.path.join(settings.MEDIA_ROOT, id_proof_relative_path)
                logger.debug(f"Saving ID proof to: {full_file_path}")
                with open(full_file_path, 'wb+') as destination:
                    for chunk in id_proof.chunks():
                        destination.write(chunk)
                id_proof_relative_path = id_proof_relative_path.replace("\\", "/")
                logger.debug(f"ID proof saved successfully at: {id_proof_relative_path}")
                messages.success(request, "ID proof submitted for verification. Awaiting admin approval.")

            # Handle selfie upload (optional)
            selfie_data = request.POST.get('selfie')
            selfie_relative_path = current_data[11]
            if selfie_data:
                if current_data[11]:
                    old_file_path = os.path.join(settings.MEDIA_ROOT, current_data[11])
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                        logger.debug(f"Removed old selfie: {old_file_path}")
                selfie_filename = f"{uuid.uuid4().hex}_selfie.jpg"
                selfie_relative_path = os.path.join('selfies', selfie_filename)
                upload_folder = os.path.join(settings.MEDIA_ROOT, 'selfies')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                full_file_path = os.path.join(settings.MEDIA_ROOT, selfie_relative_path)
                logger.debug(f"Saving selfie to: {full_file_path}")
                selfie_data = selfie_data.split(',')[1]
                with open(full_file_path, 'wb') as destination:
                    destination.write(base64.b64decode(selfie_data))
                selfie_relative_path = selfie_relative_path.replace("\\", "/")
                logger.debug(f"Selfie saved successfully at: {selfie_relative_path}")
                messages.success(request, "Selfie submitted for verification. Awaiting admin approval.")

            # Update the database
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE users
                        SET username = %s, email = %s, phone = %s, address = %s, pincode = %s,
                            email_notifications = %s, sms_notifications = %s,
                            bank_account_number = %s, paypal_email = %s,
                            profile_picture = %s,
                            id_proof = %s,
                            selfie = %s,
                            account_status = CASE
                                WHEN %s IS NOT NULL OR %s IS NOT NULL THEN 'pending'
                                ELSE account_status
                            END
                        WHERE id = %s
                    """, [
                        username, email, phone, address, pincode,
                        email_notifications, sms_notifications,
                        bank_account_number, paypal_email,
                        profile_pic_relative_path,
                        id_proof_relative_path,
                        selfie_relative_path,
                        id_proof if id_proof else None,
                        selfie_data if selfie_data else None,
                        user_id
                    ])
                    cursor.execute("""
                        INSERT INTO user_activity (user_id, description)
                        VALUES (%s, 'Updated profile information.')
                    """, [user_id])
                logger.info(f"Profile updated successfully for user ID: {user_id}")
                messages.success(request, "Profile updated successfully!")
            except Exception as e:
                logger.error(f"Error updating profile for user ID: {user_id}: {str(e)}")
                messages.error(request, "An error occurred while updating the profile. Please try again.")
            return redirect('profman')

    # Fetch user data for pre-filling the form
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT username, email, phone, address,
                       email_notifications, sms_notifications,
                       bank_account_number, paypal_email,
                       bidding_restricted, is_authenticated,
                       premium, email_verified,
                       profile_picture, pincode, created_at, account_status, id_proof, selfie
                FROM users WHERE id = %s
            """, [user_id])
            user_data = cursor.fetchone()
        logger.debug(f"User data fetched for user ID: {user_id}")
    except Exception as e:
        logger.error(f"Error fetching user data for user ID: {user_id}: {str(e)}")
        messages.error(request, "An error occurred while fetching user data.")
        return redirect('login')

    # Fetch recent activities
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT description, date FROM user_activity WHERE user_id = %s ORDER BY date DESC
            """, [user_id])
            activities_data = cursor.fetchall()
        logger.debug(f"Activities fetched for user ID: {user_id}")
    except Exception as e:
        logger.error(f"Error fetching activities for user ID: {user_id}: {str(e)}")
        activities_data = []

    if user_data:
        user = {
            'username': user_data[0] if user_data[0] else '',
            'email': user_data[1] if user_data[1] else '',
            'phone': user_data[2] if user_data[2] else '',
            'address': user_data[3] if user_data[3] else '',
            'email_notifications': bool(user_data[4]),
            'sms_notifications': bool(user_data[5]),
            'bank_account_number': user_data[6] if user_data[6] else '',
            'paypal_email': user_data[7] if user_data[7] else '',
            'bidding_restricted': bool(user_data[8]),
            'is_authenticated': bool(user_data[9]),
            'premium': bool(user_data[10]),
            'email_verified': bool(user_data[11]),
            'profile_picture_url': f"{settings.MEDIA_URL}{user_data[12]}" if user_data[12] else None,
            'pincode': user_data[13] if user_data[13] else '',
            'created_at': user_data[14],
            'account_status': user_data[15] if user_data[15] else 'unverified',
            'id_proof_url': f"{settings.MEDIA_URL}{user_data[16]}" if user_data[16] else None,
            'id_proof_path': user_data[16] if user_data[16] else '',
            'selfie_url': f"{settings.MEDIA_URL}{user_data[17]}" if user_data[17] else None,
        }
        activities = [{'description': row[0], 'date': row[1]} for row in activities_data]
        return render(request, 'profman.html', {'user': user, 'activities': activities})
    else:
        logger.error(f"No user data found for user ID: {user_id}")
        messages.error(request, "User not found.")
        return redirect('login')


def luhn_check(card_number):
    """Validate a card number using the Luhn algorithm."""
    digits = [int(d) for d in card_number if d.isdigit()]
    if not digits:
        return False
    checksum = 0
    is_even = False
    for digit in digits[::-1]:
        if is_even:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
        is_even = not is_even
    return checksum % 10 == 0



def luhn_check(card_number):
    """Validate a card number using the Luhn algorithm."""
    digits = [int(d) for d in card_number if d.isdigit()]
    if not digits:
        return False
    checksum = 0
    is_even = False
    for digit in digits[::-1]:
        if is_even:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
        is_even = not is_even
    return checksum % 10 == 0

def upgrade(request):
    # Check if the user is logged in
    user_id = request.session.get('user_id')
    if not user_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "User not logged in or session expired."}, status=401)
        messages.error(request, "User not logged in or session expired.")
        return redirect('login')

    context = {'user_id': user_id}

    # Check if user already has a membership plan
    with connection.cursor() as cursor:
        cursor.execute("SELECT membership_plan_id, premium FROM users WHERE id = %s", [user_id])
        user_membership = cursor.fetchone()

    if user_membership and user_membership[0] is not None:
        # User already has a membership, fetch latest subscription details
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT pu.premium_start_date, pu.premium_end_date, mp.plan_name
                FROM premium_users pu
                JOIN membership_plans mp ON pu.plan_id = mp.plan_id
                WHERE pu.user_id = %s
                ORDER BY pu.premium_end_date DESC
                LIMIT 1
            """, [user_id])
            premium_details = cursor.fetchone()

        if premium_details:
            premium_start, premium_end, plan_name = premium_details
            context.update({
                'premium': True,
                'plan_type': plan_name,
                'expiration_date': premium_end,
                'start_date': premium_start,
            })
            return render(request, 'upgrade.html', context)

    # If user is not premium, show the upgrade form on GET
    if request.method == "GET":
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT plan_id, plan_name, price, regular_auction_limit, sealed_bid_limit, wallet_credit
                FROM membership_plans
            """)
            plans_raw = cursor.fetchall()
        plans = [{
            "id": row[0],
            "plan_name": row[1],
            "price": row[2],
            "regular_limit": row[3],
            "sealed_limit": row[4],
            "wallet_amount": row[5],
        } for row in plans_raw]
        context.update({
            'premium': False,
            'plans': plans,
        })
        return render(request, 'upgrade.html', context)

    # Handle POST request for upgrading to premium membership
    premium_type = request.POST.get("premium_type")
    payment_method = request.POST.get("payment_method")

    # Map premium_type to plan_id
    plan_mapping = {
        "basic": "1",
        "standard": "2",
        "premium": "3"
    }
    plan_id = plan_mapping.get(premium_type.lower() if premium_type else None)
    if not plan_id:
        return JsonResponse({"success": False, "error": "Invalid membership plan selected."}, status=400)

    # Fetch membership plan details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT plan_name, price, regular_auction_limit, sealed_bid_limit, wallet_credit
            FROM membership_plans
            WHERE plan_id = %s
        """, [plan_id])
        plan = cursor.fetchone()
    if not plan:
        return JsonResponse({"success": False, "error": "Membership plan not found."}, status=400)

    plan_name, price, regular_limit, sealed_limit, wallet_amount = plan

    # Subscription duration based on plan_id
    start_date = timezone.now()
    if plan_id == "1":
        end_date = start_date + timedelta(days=60)  # 2 months
    elif plan_id == "2":
        end_date = start_date + timedelta(days=180)  # 6 months
    elif plan_id == "3":
        end_date = start_date + timedelta(days=365)  # 1 year

    # Validate payment method and details
    if not payment_method:
        return JsonResponse({"success": False, "error": "Payment method is required."}, status=400)

    payment_details = {
        "debit_card_number": request.POST.get("debit_card_number"),
        "debit_card_expiry": request.POST.get("debit_card_expiry"),
        "debit_card_cvc": request.POST.get("debit_card_cvc"),
        "credit_card_number": request.POST.get("credit_card_number"),
        "credit_card_expiry": request.POST.get("credit_card_expiry"),
        "credit_card_cvc": request.POST.get("credit_card_cvc"),
        "paypal_email": request.POST.get("paypal_email"),
        "bank_account_number": request.POST.get("bank_account_number"),
        "bank_routing_number": request.POST.get("bank_routing_number"),
    }

    # Real-world payment validation
    if payment_method in ["debit", "credit"]:
        card_number = payment_details[f"{payment_method}_card_number"]
        card_expiry = payment_details[f"{payment_method}_card_expiry"]
        card_cvc = payment_details[f"{payment_method}_card_cvc"]

        # Card number validation (16 digits + Luhn check)
        if not card_number or not re.match(r"^\d{16}$", card_number.replace(" ", "")):
            return JsonResponse({"success": False, "error": "Card number must be 16 digits."}, status=400)
        if not luhn_check(card_number.replace(" ", "")):
            return JsonResponse({"success": False, "error": "Invalid card number (Luhn check failed)."}, status=400)

        # Expiry date validation (MM/YY, not expired)
        if not card_expiry or not re.match(r"^(0[1-9]|1[0-2])\/\d{2}$", card_expiry):
            return JsonResponse({"success": False, "error": "Expiry date must be in MM/YY format."}, status=400)
        try:
            exp_month, exp_year = map(int, card_expiry.split("/"))
            current_year = timezone.now().year % 100
            current_month = timezone.now().month
            if exp_year < current_year or (exp_year == current_year and exp_month < current_month):
                return JsonResponse({"success": False, "error": "Card is expired."}, status=400)
        except ValueError:
            return JsonResponse({"success": False, "error": "Invalid expiry date format."}, status=400)

        # CVC validation (3-4 digits, per schema)
        if not card_cvc or not re.match(r"^\d{3,4}$", card_cvc):
            return JsonResponse({"success": False, "error": "CVC must be 3 or 4 digits."}, status=400)

    elif payment_method == "paypal":
        paypal_email = payment_details["paypal_email"]
        if not paypal_email or not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", paypal_email):
            return JsonResponse({"success": False, "error": "Invalid PayPal email."}, status=400)

    elif payment_method == "bank_transfer":
        account_number = payment_details["bank_account_number"]
        routing_number = payment_details["bank_routing_number"]
        if not account_number or not re.match(r"^\d+$", account_number):
            return JsonResponse({"success": False, "error": "Bank account number must be numeric."}, status=400)
        if not routing_number or not re.match(r"^\d{9}$", routing_number):
            return JsonResponse({"success": False, "error": "Routing number must be 9 digits."}, status=400)

    else:
        return JsonResponse({"success": False, "error": "Invalid payment method."}, status=400)

    # Insert payment details
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO payment_details (
                user_id, premium_type, payment_method, payment_amount, payment_status, 
                transaction_id, payment_date, debit_card_number, debit_card_expiry, debit_card_cvc, 
                credit_card_number, credit_card_expiry, credit_card_cvc, paypal_email, 
                bank_account_number, bank_routing_number
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            plan_name,
            payment_method,
            price,
            "completed",  # Assuming payment is successful for this example
            str(uuid.uuid4()),  # Generate a unique transaction ID
            start_date,
            payment_details["debit_card_number"] or None,
            payment_details["debit_card_expiry"] or None,
            payment_details["debit_card_cvc"] or None,
            payment_details["credit_card_number"] or None,
            payment_details["credit_card_expiry"] or None,
            payment_details["credit_card_cvc"] or None,
            payment_details["paypal_email"] or None,
            payment_details["bank_account_number"] or None,
            payment_details["bank_routing_number"] or None
        ))

    # Insert premium subscription details
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO premium_users (user_id, plan_id, premium_start_date, premium_end_date)
            VALUES (%s, %s, %s, %s)
        """, [user_id, plan_id, start_date, end_date])

    # Update user's membership_plan_id and premium flag
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE users 
            SET premium = 1, membership_plan_id = %s
            WHERE id = %s
        """, [plan_id, user_id])

    # Update or create wallet
    with connection.cursor() as cursor:
        cursor.execute("SELECT balance FROM wallets WHERE user_id = %s", [user_id])
        wallet_row = cursor.fetchone()
        if wallet_row:
            cursor.execute("UPDATE wallets SET balance = balance + %s WHERE user_id = %s", [wallet_amount, user_id])
        else:
            cursor.execute("INSERT INTO wallets (user_id, balance) VALUES (%s, %s)", [user_id, wallet_amount])

    # Fetch user's email for notification
    with connection.cursor() as cursor:
        cursor.execute("SELECT email FROM users WHERE id = %s", [user_id])
        user_email_row = cursor.fetchone()
        user_email = user_email_row[0] if user_email_row else None

    # Fetch admin email
    with connection.cursor() as cursor:
        cursor.execute("SELECT email FROM users WHERE role = 'admin' LIMIT 1")
        admin_email_row = cursor.fetchone()
        admin_email = admin_email_row[0] if admin_email_row else "admin@example.com"

    if user_email:
        email_subject = "🎉 Premium Membership Activated – Welcome to Exclusive Benefits!"
        email_body = (
            f"Dear Valued Member,\n\n"
            f"Congratulations! Your {plan_name} Plan has been successfully activated.\n\n"
            f"Subscription Details:\n"
            f" - Start Date: {start_date.strftime('%B %d, %Y %H:%M:%S')}\n"
            f" - End Date: {end_date.strftime('%B %d, %Y %H:%M:%S')}\n"
            f" - Regular Auctions Allowed: {'Unlimited' if regular_limit == 0 else regular_limit}\n"
            f" - Sealed Bid Auctions Allowed: {sealed_limit}\n"
            f" - Wallet Credit: ₹{wallet_amount:.2f}\n\n"
            f"Enjoy your new premium features, including enhanced bidding, priority support, and more!\n\n"
            f"Best regards,\n"
            f"The AuctionPro Team"
        )
        send_mail(email_subject, email_body, admin_email, [user_email])

    # Return success response for AJAX
    return JsonResponse({
        "success": True,
        "message": "Your premium membership has been activated successfully!",
        "plan_name": plan_name,
        "start_date": start_date.strftime('%B %d, %Y %H:%M:%S'),
        "end_date": end_date.strftime('%B %d, %Y %H:%M:%S'),
    })





def sealed_thanks(request, auction_id):
    # Fetch the winner selection date for the provided auction ID
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT winner_selection_date FROM sealed_bid_details WHERE auction_id = %s",
            [auction_id],
        )
        row = cursor.fetchone()
        winner_selection_date = row[0] if row else None

    # Handle cases where no winner selection date is found
    if not winner_selection_date:
        return render(request, 'error.html', {'message': 'Winner selection date not found for this auction.'})

    # Pass the auction ID and winner selection date to the template
    context = {
        'auction_id': auction_id,
        'winner_selection_date': winner_selection_date,
    }
    return render(request, 'sealed_thanks.html', context)


def get_winner_details(request, auction_id):
    # Fetch winner details from the auction_winners table
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT w.user_id, u.username, u.email
                FROM auction_winners w
                JOIN users u ON w.user_id = u.id
                WHERE w.auction_id = %s
            """, [auction_id])
            winner = cursor.fetchone()

        if winner:
            winner_details = {
                'username': winner[1],
                'email': winner[2],
            }
        else:
            winner_details = None

        return JsonResponse({'winner': winner_details}, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def notifications_page(request):
    user_id = request.session.get('user_id')  # Get logged-in user ID
    if not user_id:
        return redirect('login')  # Redirect to login if not authenticated
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, message, is_read FROM notifications WHERE user_id = %s ORDER BY created_at DESC",
            [user_id]
        )
        notifications = [
            {"id": row[0], "message": row[1], "is_read": row[2]} for row in cursor.fetchall()
        ]
    return render(request, "notifications.html", {"notifications": notifications})

@csrf_exempt
def mark_notification_read(request, notification_id):
    if request.method == "POST":
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s",
                [notification_id, user_id]
            )
            if cursor.rowcount == 0:
                return JsonResponse({"success": False, "error": "Notification not found or not authorized"}, status=404)
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Invalid request method"}, status=400)

@csrf_exempt
def mark_all_notifications_read(request):
    user_id = request.session.get('user_id')
    if request.method == "POST" and user_id:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE notifications SET is_read = TRUE WHERE user_id = %s",
                [user_id]
            )
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Not authenticated or invalid request method"}, status=400)

@csrf_exempt
def delete_notification(request, notification_id):
    if request.method == "POST":
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM notifications WHERE id = %s AND user_id = %s",
                [notification_id, user_id]
            )
            if cursor.rowcount == 0:
                return JsonResponse({"success": False, "error": "Notification not found or not authorized"}, status=404)
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Invalid request method"}, status=400)

@csrf_exempt
def delete_all_notifications(request):
    if request.method == "POST":
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM notifications WHERE user_id = %s",
                [user_id]
            )
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Invalid request method"}, status=400)

def luhn_check(card_number):
    """
    Performs the Luhn algorithm check on the card number.
    Returns True if valid, False otherwise.
    """
    card_number = card_number.replace(" ", "")
    total = 0
    reverse_digits = card_number[::-1]
    for i, digit in enumerate(reverse_digits):
        n = int(digit)
        if i % 2 == 1:  # Double every second digit from the right
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0

def validate_credit_card_bank(card_number, card_expiry, card_cvc, card_holder, bank_name):
    """
    Validates credit card details, including cardholder name and bank name, against the bank_cards table.
    Returns a tuple: (is_valid: bool, message: str).
    """
    normalized_card = card_number.replace(" ", "")
    # Validate bank name format
    if not bank_name or not re.match(r'^[A-Za-z\s]{2,}$', bank_name):
        return False, "Invalid bank name format."

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT card_holder, expiration_date, cvv, status 
            FROM bank_cards
            WHERE REPLACE(card_number, ' ', '') = %s AND cvv = %s
        """, [normalized_card, card_cvc])
        result = cursor.fetchone()

    if not result:
        return False, "Credit card not found or CVV mismatch."

    stored_name, db_expiration, stored_cvv, status = result

    # Check cardholder name (case-insensitive and stripped)
    if card_holder.strip().lower() != stored_name.strip().lower():
        return False, "Cardholder name does not match."

    # Validate expiration date format
    try:
        user_expiry = datetime.strptime(card_expiry, "%m/%y")
    except ValueError:
        return False, "Invalid expiration date format. Use MM/YY."

    # Compare month and year
    if user_expiry.month != db_expiration.month or user_expiry.year != db_expiration.year:
        return False, "Expiration date does not match."

    # Check card status
    if status.lower() != "active":
        return False, "Credit card is not active."

    # Check if the card is expired
    if db_expiration < datetime.now().date():
        return False, "Credit card is expired."

    return True, "Credit card validated successfully."

# ----- Helper Validation Functions -----

def validate_paypal_email(paypal_email):
    """Mock validation for PayPal email existence (replace with real API call)."""
    if not paypal_email or not re.match(r"[^@]+@[^@]+\.[^@]+", paypal_email):
        return False, "Invalid PayPal email format."

    mock_valid_emails = {
        "testuser123@paypal.com": "Test User",
        "buyer_demo@paypal.com": "Demo Buyer",
        "verified_seller@paypal.com": "Verified Seller",
        "business_account@paypal.com": "Business Account",
        "john.doe@paypal.com": "John Doe",
        "secure.payment@paypal.com": "Secure PayPal User",
    }

    account_name = mock_valid_emails.get(paypal_email.lower())
    if account_name:
        return True, f"PayPal email verified: {account_name}"
    return False, "PayPal email does not exist."

def validate_bank_transfer_details(iban, bic, bank_name):
    """Mock validation for IBAN, BIC, and bank name existence (replace with real bank API)."""
    if not iban or not re.match(r'^[A-Z0-9]{15,34}$', iban):
        return False, "Invalid IBAN format."
    if not bic or not re.match(r'^[A-Z0-9]{8,11}$', bic):
        return False, "Invalid BIC/SWIFT code format."
    if not bank_name or not re.match(r'^[A-Za-z\s]{2,}$', bank_name):
        return False, "Invalid bank name format."

    mock_valid_ibans = {
        "DE89370400440532013000": "Deutsche Bank - Germany",
        "GB29NWBK60161331926819": "NatWest Bank - UK",
        "FR7630006000011234567890189": "BNP Paribas - France",
        "IT60X0542811101000000123456": "Intesa Sanpaolo - Italy",
    }
    mock_valid_bics = {
        "DEUTDEFFXXX": "Deutsche Bank - Germany",
        "NWBKGB2LXXX": "NatWest Bank - UK",
        "BNPAFRPPXXX": "BNP Paribas - France",
        "BCITITMMXXX": "Intesa Sanpaolo - Italy",
    }

    bank_name_from_iban = mock_valid_ibans.get(iban)
    if bank_name_from_iban and bic in mock_valid_bics and bank_name.lower() in bank_name_from_iban.lower():
        return True, f"Bank details verified: {bank_name}, BIC: {bic}"
    return False, "Bank details do not exist or are invalid."

def validate_crypto_wallet(wallet_address, crypto_type):
    """Mock validation for crypto wallet address existence (replace with blockchain API)."""
    if not wallet_address:
        return False, "Wallet address is required."

    wallet_patterns = {
        "ETH": r"^(0x)?[0-9a-fA-F]{40}$",
        "BTC": r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$",
        "LTC": r"^[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}$",
        "DOGE": r"^D{1}[5-9A-HJ-NP-U]{1}[A-HJ-NP-Za-km-z1-9]{32,33}$",
        "XRP": r"^r[0-9a-zA-Z]{24,34}$",
    }

    if crypto_type.upper() not in wallet_patterns:
        return False, "Unsupported cryptocurrency type."

    pattern = wallet_patterns[crypto_type.upper()]
    if not re.match(pattern, wallet_address):
        return False, f"Invalid {crypto_type.upper()} wallet address format."

    mock_valid_addresses = {
        "ETH": [
            "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
            "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "0x281055afc982d96fab65b3a49cac8b878184cb16"
        ],
        "BTC": [
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080",
            "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
        ]
    }

    if wallet_address in mock_valid_addresses.get(crypto_type.upper(), []):
        return True, f"{crypto_type.upper()} wallet address verified."
    return False, f"{crypto_type.upper()} wallet address does not exist or is invalid."

# ----- Helper Validation Functions -----

def validate_card_data(data):
    """Validates credit card data, including cardholder name and bank name."""
    errors = []
    card_number = data.get('card_number', '').replace(' ', '')
    card_expiry = data.get('card_expiry', '')
    card_cvc = data.get('card_cvc', '')
    card_holder = data.get('card_holder', '')
    bank_name = data.get('bank_name', '')

    if not card_number:
        errors.append("Card number is required.")
    elif not luhn_check(card_number):
        errors.append("Invalid card number structure.")
    if not card_expiry:
        errors.append("Expiry date is required.")
    if not card_cvc:
        errors.append("CVC is required.")
    if not card_holder:
        errors.append("Cardholder name is required.")
    if not bank_name:
        errors.append("Bank name is required.")

    if not errors:
        valid, message = validate_credit_card_bank(card_number, card_expiry, card_cvc, card_holder, bank_name)
        if not valid:
            errors.append(message)

    return errors if errors else None

def validate_paypal_data(data):
    """Validates PayPal email and checks existence."""
    errors = []
    paypal_email = data.get('paypal_email', '')
    if not paypal_email:
        errors.append("PayPal email is required.")
    else:
        valid, message = validate_paypal_email(paypal_email)
        if not valid:
            errors.append(message)
    return errors if errors else None

def validate_bank_transfer_data(data):
    """Validates IBAN, BIC, and bank name and checks existence."""
    errors = []
    iban = data.get('iban', '')
    bic = data.get('bic', '')
    bank_name = data.get('bank_name', '')
    if not iban:
        errors.append("IBAN is required.")
    if not bic:
        errors.append("BIC/SWIFT code is required.")
    if not bank_name:
        errors.append("Bank name is required.")
    if iban and bic and bank_name:
        valid, message = validate_bank_transfer_details(iban, bic, bank_name)
        if not valid:
            errors.append(message)
    return errors if errors else None

def validate_crypto_data(data):
    """Validates crypto wallet address and checks existence."""
    errors = []
    wallet_address = data.get('wallet_address', '')
    crypto_type = data.get('crypto_type', '')
    if not wallet_address:
        errors.append("Wallet address is required.")
    if not crypto_type:
        errors.append("Cryptocurrency type is required.")
    if wallet_address and crypto_type:
        valid, message = validate_crypto_wallet(wallet_address, crypto_type)
        if not valid:
            errors.append(message)
    return errors if errors else None

# ----- Real-Time Validation Endpoints -----

@csrf_exempt
def validate_card_data_view(request):
    """Validates credit card details in real time."""
    if request.method != 'POST':
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        logger.debug(f"Received card data: {data}")
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {request.body}")
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    errors = validate_card_data(data)
    if errors:
        return JsonResponse({"status": "failed", "errors": errors}, status=400)
    return JsonResponse({"status": "validated", "message": "Card Verified"}, status=200)

@csrf_exempt
def validate_payment(request):
    """Validates full payment details during form submission."""
    if request.method != 'POST':
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
        logger.debug(f"Received payment data: {data}")
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {request.body}")
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    payment_method = data.get('payment_method', '').strip()
    errors = []
    if payment_method == "credit_card":
        errors = validate_card_data(data)
    elif payment_method == "paypal":
        errors = validate_paypal_data(data)
    elif payment_method == "bank_transfer":
        errors = validate_bank_transfer_data(data)
    elif payment_method == "crypto":
        errors = validate_crypto_data(data)
    else:
        errors.append(f"Unsupported payment method: {payment_method}")

    if errors:
        logger.error(f"Validation errors: {errors}")
        return JsonResponse({"status": "failed", "errors": errors}, status=400)
    return JsonResponse({"status": "validated"}, status=200)

@csrf_exempt
def validate_paypal_view(request):
    """Validates PayPal email in real time."""
    if request.method != 'POST':
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
        logger.debug(f"Received PayPal data: {data}")
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {request.body}")
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    errors = validate_paypal_data(data)
    if errors:
        return JsonResponse({"status": "failed", "errors": errors}, status=400)
    return JsonResponse({"status": "validated", "message": "PayPal email verified"}, status=200)

@csrf_exempt
def validate_bank_transfer_view(request):
    """Validates bank transfer details in real time."""
    if request.method != 'POST':
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
        logger.debug(f"Received bank transfer data: {data}")
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {request.body}")
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    errors = validate_bank_transfer_data(data)
    if errors:
        return JsonResponse({"status": "failed", "errors": errors}, status=400)
    return JsonResponse({"status": "validated", "message": "Bank details verified"}, status=200)

@csrf_exempt
def validate_crypto_view(request):
    """Validates cryptocurrency wallet address in real time."""
    if request.method != 'POST':
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
        logger.debug(f"Received crypto data: {data}")
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {request.body}")
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    errors = validate_crypto_data(data)
    if errors:
        return JsonResponse({"status": "failed", "errors": errors}, status=400)
    return JsonResponse({"status": "validated", "message": "Wallet address verified"}, status=200)

# ----- Existing Payment Processing View -----

def payment_page(request):
    """Handle payment processing and invoice display with a 10-minute grace period for overdue invoices."""
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to access payments.")
        return redirect('login')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT i.id, i.auction_id, i.amount_due, i.issue_date, i.due_date, i.status, 
                   i.seller_id, i.late_fee, o.second_winner_offer
            FROM invoices i
            LEFT JOIN offers o ON i.auction_id = o.auction_id AND o.status = 'accepted'
            WHERE i.buyer_id = %s
        """, [user_id])
        invoices = cursor.fetchall()

    current_datetime = timezone.now()
    pending_invoices, paid_invoices, overdue_invoices = [], [], []

    for invoice in invoices:
        due_date = invoice[4]
        if isinstance(due_date, datetime) and due_date.tzinfo is None:
            due_date = make_aware(due_date)

        second_winner_offer = invoice[8] if invoice[8] is not None else False

        invoice_data = {
            "id": str(invoice[0]),
            "auction_id": invoice[1],
            "amount_due": float(invoice[2]),
            "issue_date": invoice[3],
            "due_date": due_date,
            "status": invoice[5],
            "seller_id": invoice[6],
            "late_fee": float(invoice[7]) if invoice[7] else 0.00,
            "can_pay": True
        }

        if invoice_data["status"] == "Paid":
            paid_invoices.append(invoice_data)
        elif invoice_data["status"] == "Overdue":
            if not second_winner_offer:
                grace_period = timedelta(minutes=10)
                invoice_data["can_pay"] = current_datetime <= due_date + grace_period
                overdue_invoices.append(invoice_data)
        else:
            if not second_winner_offer:
                pending_invoices.append(invoice_data)

    if request.method == "POST":
        invoice_id = request.POST.get('invoice_id')
        payment_method = request.POST.get('payment_method', '').strip()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT i.id, i.auction_id, i.amount_due, i.seller_id, i.issue_date, 
                           i.due_date, i.late_fee, i.status, o.second_winner_offer
                    FROM invoices i
                    LEFT JOIN offers o ON i.auction_id = o.auction_id AND o.status = 'accepted'
                    WHERE i.id = %s AND i.buyer_id = %s
                """, [invoice_id, user_id])
                invoice = cursor.fetchone()
                if not invoice:
                    messages.error(request, "Invalid invoice selected.")
                    return redirect('payment_page')

                invoice_status = invoice[7]
                due_date = invoice[5]
                if isinstance(due_date, datetime) and due_date.tzinfo is None:
                    due_date = make_aware(due_date)

                second_winner_offer = invoice[8] if invoice[8] is not None else False
                if second_winner_offer and invoice_status != 'Paid':
                    messages.error(request, "Second winner invoices cannot be paid here.")
                    return redirect('payment_page')

                grace_period = timedelta(minutes=10)
                if invoice_status == 'Overdue' and current_datetime > due_date + grace_period:
                    messages.error(request, "The grace period for this overdue invoice has expired.")
                    return redirect('payment_page')

                transaction_id = str(uuid4())[:16]
                payment_date = timezone.now()
                payment_amount = float(invoice[2]) + float(invoice[6])
                auction_id = invoice[1]
                seller_id = invoice[3]

                if payment_method == "credit_card":
                    cursor.execute("""
                        INSERT INTO payment_details (
                            user_id, invoice_id, auction_id, payment_method, 
                            payment_status, transaction_id, payment_amount,
                            credit_card_number, payment_notes, payment_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        user_id, invoice_id, auction_id, payment_method,
                        'Completed', transaction_id, payment_amount,
                        request.POST.get("card_number"), request.POST.get("bank_name"), payment_date
                    ])
                elif payment_method == "paypal":
                    cursor.execute("""
                        INSERT INTO payment_details (
                            user_id, invoice_id, auction_id, payment_method,
                            payment_status, transaction_id, payment_amount,
                            paypal_email, payment_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        user_id, invoice_id, auction_id, payment_method,
                        'Completed', transaction_id, payment_amount,
                        request.POST.get("paypal_email"), payment_date
                    ])
                elif payment_method == "bank_transfer":
                    cursor.execute("""
                        INSERT INTO payment_details (
                            user_id, invoice_id, auction_id, payment_method,
                            payment_status, transaction_id, payment_amount,
                            bank_account_number, bank_routing_number, payment_notes, payment_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        user_id, invoice_id, auction_id, payment_method,
                        'Completed', transaction_id, payment_amount,
                        request.POST.get("iban"), request.POST.get("bic"), request.POST.get("bank_name"), payment_date
                    ])
                elif payment_method == "crypto":
                    cursor.execute("""
                        INSERT INTO payment_details (
                            user_id, invoice_id, auction_id, payment_method,
                            payment_status, transaction_id, payment_amount,
                            wallet_address, crypto_type, payment_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        user_id, invoice_id, auction_id, payment_method,
                        'Completed', transaction_id, payment_amount,
                        request.POST.get("wallet_address"), request.POST.get("crypto_type"), payment_date
                    ])
                else:
                    raise ValueError(f"Invalid payment method: {payment_method}")

                cursor.execute("""
                    UPDATE invoices 
                    SET status = 'Paid' 
                    WHERE id = %s
                """, [invoice_id])

                cursor.execute("""
                    SELECT commission_percentage FROM platform_commission 
                    WHERE auction_type = (SELECT auction_type FROM auctions WHERE id = %s) 
                    AND status = 'active' 
                    ORDER BY effective_date DESC LIMIT 1
                """, [auction_id])
                commission_percentage = cursor.fetchone()
                commission_percentage = float(commission_percentage[0]) if commission_percentage else 5.00

                platform_share = (commission_percentage / 100) * payment_amount
                seller_share = payment_amount - platform_share

                cursor.execute("""
                    INSERT INTO fund_distribution (invoice_id, auction_id, seller_id, platform_share, 
                                                   seller_share, status, distribution_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, [invoice_id, auction_id, seller_id, platform_share, seller_share, 'Pending', payment_date])

                tracking_id = str(uuid4())[:10]
                cursor.execute("""
                    UPDATE orders 
                    SET shipping_status = 'processing', progress = 30, payment_status = 'paid', tracking_number = %s
                    WHERE invoice_id = %s
                """, [tracking_id, invoice_id])

                cursor.execute("""
                    UPDATE auctions
                    SET status = 'sold'
                    WHERE id = %s
                """, [auction_id])

                # Notify Seller
                try:
                    cursor.execute("SELECT email FROM users WHERE id = %s", [seller_id])
                    seller_email = cursor.fetchone()[0]
                    seller_message = f"A payment of ₹{payment_amount:.2f} has been received for auction (ID: {auction_id}). The auction status is now sold."
                    notify_user(seller_id, seller_email, seller_message, subject="Auction Sold")
                except Exception as e:
                    logger.error(f"Failed to notify seller (ID: {seller_id}): {str(e)}")

                # Notify Buyer
                try:
                    cursor.execute("SELECT email FROM users WHERE id = %s", [user_id])
                    buyer_email = cursor.fetchone()[0]
                    buyer_message = f"Your payment of ₹{payment_amount:.2f} for invoice (ID: {invoice_id}) and auction (ID: {auction_id}) has been successfully processed."
                    notify_user(user_id, buyer_email, buyer_message, subject="Payment Confirmation")
                except Exception as e:
                    logger.error(f"Failed to notify buyer (ID: {user_id}): {str(e)}")

                messages.success(request, "Payment processed successfully!")
                return redirect('payment_page')
        except Exception as e:
            logger.error(f"Payment Error: {str(e)}")
            messages.error(request, "Payment processing failed.")
            return redirect('payment_page')

    return render(request, 'payment.html', {
        "pending_invoices": pending_invoices,
        "paid_invoices": paid_invoices,
        "overdue_invoices": overdue_invoices
    })

def buy_it_now_payment(request, auction_id):
    """Handle Buy It Now payment processing with detailed debug logging."""
    print("DEBUG: Starting buy_it_now_payment view for auction_id:", auction_id)

    # Check if user is logged in
    user_id = request.session.get('user_id')
    if not user_id:
        print("DEBUG: No user_id found in session")
        messages.error(request, "You must be logged in to make a purchase.")
        return redirect('login')

    # Fetch auction details
    try:
        with connection.cursor() as cursor:
            print("DEBUG: Fetching auction details for auction_id:", auction_id)
            cursor.execute("""
                SELECT a.id, a.title, a.description, a.condition, a.condition_description, 
                       a.category, a.buy_it_now_price, a.user_id
                FROM auctions a
                WHERE a.id = %s AND a.auction_type = 'buy_it_now' AND a.status != 'sold'
            """, [auction_id])
            auction = cursor.fetchone()
            print("DEBUG: Auction fetched:", auction)
    except Exception as ex:
        print("DEBUG: Error fetching auction details")
        traceback.print_exc()
        messages.error(request, "Error fetching auction details.")
        return redirect('auct_list')

    if not auction:
        print("DEBUG: Auction not found, invalid, or already sold")
        messages.error(request, "Invalid, unavailable, or already sold auction.")
        return redirect('auct_list')

    # Fetch auction image correctly
    image_url = None
    try:
        with connection.cursor() as cursor:
            print("DEBUG: Fetching auction image for auction_id:", auction_id)
            cursor.execute("""
                SELECT image_path FROM auction_images 
                WHERE auction_id = %s 
                LIMIT 1
            """, [auction_id])
            image = cursor.fetchone()
            if image and image[0]:
                if image[0].startswith("/media/"):
                    image_url = image[0]
                else:
                    image_url = f"/media/auction_images/{image[0]}"
                print("DEBUG: Image URL fetched:", image_url)
            else:
                image_url = "/static/images/placeholder.png"
                print("DEBUG: No image found for auction, using placeholder")
    except Exception as ex:
        print("DEBUG: Error fetching auction image")
        traceback.print_exc()
        image_url = "/static/images/placeholder.png"

    # Prepare item data for template
    item = {
        "id": auction[0],
        "title": auction[1],
        "description": auction[2],
        "condition": auction[3],
        "condition_description": auction[4],
        "category": auction[5],
        "price": float(auction[6]),
        "seller_id": auction[7],
        "image_url": image_url
    }
    print("DEBUG: Item prepared:", item)

    # Calculate tax and total amount (1% tax)
    tax_rate = Decimal('0.01')
    price_decimal = Decimal(str(item["price"]))
    item["tax"] = price_decimal * tax_rate
    item["total_amount"] = price_decimal + item["tax"]
    print("DEBUG: Price:", price_decimal, "Tax:", item["tax"], "Total Amount:", item["total_amount"])

    if request.method == "POST":
        print("DEBUG: POST request received")
        payment_method = request.POST.get('payment_method')
        print("DEBUG: Payment method selected:", payment_method)
        # Get shipping details from POST
        full_name = request.POST.get("full_name")
        phone = request.POST.get("phone")
        address = request.POST.get("address")
        city = request.POST.get("city")
        state = request.POST.get("state")
        zip_code = request.POST.get("zip")
        country = request.POST.get("country")
        shipping_details = f"{full_name} {phone} {address} {city} {state} {zip_code} {country}"
        print("DEBUG: Shipping details received:", shipping_details)

        # Validate shipping details
        if not all([full_name, phone, address, city, state, zip_code, country]):
            print("DEBUG: Incomplete shipping details")
            messages.error(request, "Please provide complete shipping details.")
            return render(request, 'buy_it_now_payment.html', {"item": item})

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Create invoice record
                    invoice_id = uuid4().hex[:16]
                    issue_date = timezone.now()
                    due_date = issue_date
                    print("DEBUG: Creating invoice with id:", invoice_id)
                    cursor.execute("""
                        INSERT INTO invoices (id, auction_id, buyer_id, seller_id, amount_due, issue_date, due_date, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending')
                    """, [invoice_id, auction_id, user_id, item["seller_id"], float(item["total_amount"]), issue_date, due_date])
                    print("DEBUG: Invoice created successfully")

                    # Process payment
                    transaction_id = uuid4().hex[:16]
                    payment_date = timezone.now()
                    payment_amount = float(item["total_amount"])
                    print("DEBUG: Processing payment. Transaction ID:", transaction_id)

                    if payment_method == "credit_card":
                        print("DEBUG: Inserting credit card payment details")
                        cursor.execute("""
                            INSERT INTO payment_details (
                                user_id, invoice_id, auction_id, payment_method, 
                                payment_status, transaction_id, payment_amount,
                                credit_card_number, payment_date
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [user_id, invoice_id, auction_id, payment_method, 'Completed', transaction_id, payment_amount, request.POST.get("card_number"), payment_date])
                    elif payment_method == "paypal":
                        print("DEBUG: Inserting PayPal payment details")
                        cursor.execute("""
                            INSERT INTO payment_details (
                                user_id, invoice_id, auction_id, payment_method,
                                payment_status, transaction_id, payment_amount,
                                paypal_email, payment_date
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [user_id, invoice_id, auction_id, payment_method, 'Completed', transaction_id, payment_amount, request.POST.get("paypal_email"), payment_date])
                    elif payment_method == "bank_transfer":
                        print("DEBUG: Inserting bank transfer payment details")
                        cursor.execute("""
                            INSERT INTO payment_details (
                                user_id, invoice_id, auction_id, payment_method,
                                payment_status, transaction_id, payment_amount,
                                bank_account_number, bank_routing_number, payment_date
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, [user_id, invoice_id, auction_id, payment_method, 'Completed', transaction_id, payment_amount, request.POST.get("iban"), request.POST.get("bic"), payment_date])
                    else:
                        raise ValueError("Invalid payment method selected")

                    print("DEBUG: Payment details inserted successfully")

                    # Update invoice status to 'Paid'
                    print("DEBUG: Updating invoice status to 'Paid'")
                    cursor.execute("""
                        UPDATE invoices 
                        SET status = 'Paid' 
                        WHERE id = %s
                    """, [invoice_id])

                    # Fetch commission percentage
                    print("DEBUG: Fetching commission percentage")
                    cursor.execute("""
                        SELECT commission_percentage FROM platform_commission 
                        WHERE auction_type = 'buy_it_now'
                        ORDER BY effective_date DESC LIMIT 1
                    """)
                    commission_row = cursor.fetchone()
                    commission_percentage = float(commission_row[0]) if commission_row else 5.00
                    print("DEBUG: Commission percentage:", commission_percentage)

                    # Calculate fund distribution amounts
                    platform_share = (commission_percentage / 100) * payment_amount
                    seller_share = payment_amount - platform_share
                    print("DEBUG: Platform share:", platform_share, "Seller share:", seller_share)

                    cursor.execute("""
                        INSERT INTO fund_distribution (invoice_id, auction_id, seller_id, platform_share, 
                                                       seller_share, status, distribution_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, [invoice_id, auction_id, item["seller_id"], platform_share, seller_share, 'Pending', payment_date])
                    print("DEBUG: Fund distribution record inserted")

                    # Insert order details
                    tracking_id = uuid4().hex[:10]
                    print("DEBUG: Inserting order details with tracking id:", tracking_id)
                    cursor.execute("""
                        INSERT INTO orders (auction_id, user_id, invoice_id, payment_status, payment_amount, 
                                            shipping_status, tracking_number, order_date, order_status, progress)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, [auction_id, user_id, invoice_id, 'paid', payment_amount, 'processing', tracking_id, payment_date, 'Confirmed', 30])

                    cursor.execute("SELECT LAST_INSERT_ID()")
                    order_id = cursor.fetchone()[0]
                    print("DEBUG: Order inserted with order_id:", order_id)

                    # Insert shipping details
                    print("DEBUG: Inserting shipping details")
                    cursor.execute("""
                        INSERT INTO shipping_details (order_id, invoice_id, buyer_id, full_name, phone, address, city, state, zip_code, country, shipping_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, [order_id, invoice_id, user_id, full_name, phone, address, city, state, zip_code, country, payment_date])

                    # Update auction status to sold
                    print("DEBUG: Updating auction status to 'sold'")
                    cursor.execute("""
                        UPDATE auctions 
                        SET status = 'sold'
                        WHERE id = %s
                    """, [auction_id])

                    print("DEBUG: Payment processing completed successfully")
                    messages.success(request, "Purchase successful!")
                    return redirect('view_orders', order_id=order_id)

        except Exception as e:
            print("DEBUG: Payment processing failed.")
            traceback.print_exc()
            messages.error(request, f"Payment processing failed: {str(e)}")
            return render(request, 'buy_it_now_payment.html', {"item": item})

    print("DEBUG: Rendering payment page with item:", item)
    return render(request, 'buy_it_now_payment.html', {"item": item})
def view_orders(request, order_id=None):
    """
    View orders for both seller and buyer, with optional order_id filtering.
    Uses raw SQL to fetch orders. Displays all orders and specific order details on view_orders.html.
    Ensures 'buy_it_now' orders appear in buyer orders section.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to view orders.")
        return redirect('login')

    # Check GET parameter if order_id not provided in URL
    if not order_id:
        order_id = request.GET.get('order_id')

    def format_date(date_obj):
        """Helper to format dates or return 'N/A' if None."""
        return date_obj.strftime('%Y-%m-%d %H:%M:%S') if date_obj else "N/A"

    def format_date_only(date_obj):
        """Helper to format date-only or return 'N/A' if None."""
        return date_obj.strftime('%Y-%m-%d') if date_obj else "N/A"

    def fetch_auction_images(auction_id):
        """Fetch image paths for an auction, ensuring valid paths."""
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT image_path FROM auction_images WHERE auction_id = %s AND image_path IS NOT NULL",
                    [auction_id]
                )
                images = cursor.fetchall()
            valid_images = [f"/media/auction_images/{img[0]}" for img in images if img[0]]
            print(f"DEBUG: Auction ID {auction_id} returned images: {valid_images}")
            return valid_images
        except Exception as e:
            print(f"DEBUG: Error fetching images for auction {auction_id}: {e}")
            return []

    def fetch_shipping_details(order_id):
        """Fetch shipping details for buy_it_now orders."""
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT address, city, state, zip_code, country, shipping_date
                    FROM shipping_details
                    WHERE order_id = %s
                    LIMIT 1
                """, [order_id])
                result = cursor.fetchone()
            if result:
                address, city, state, zip_code, country, shipping_date = result
                shipping_address = f"{address}, {city}, {state}, {zip_code}, {country}"
                print(f"DEBUG: Shipping details for order {order_id}: {shipping_address}, {shipping_date}")
                return {
                    "shipping_address": shipping_address,
                    "delivery_date": shipping_date,
                }
            print(f"DEBUG: No shipping details found for order {order_id}")
            return None
        except Exception as e:
            print(f"DEBUG: Error fetching shipping details for order {order_id}: {e}")
            return None

    # Initialize context
    context = {
        "seller_orders": [],
        "buyer_orders": [],
        "total_orders": 0,
        "completed_orders": 0,
        "selected_order_id": order_id,
        "order_detail": None
    }

    if order_id:
        # Fetch specific order details
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT o.order_id, o.auction_id, a.title, a.auction_type, o.payment_status, o.payment_amount, 
                           o.order_status, o.order_date, o.shipping_status, o.shipping_address, 
                           o.tracking_number, o.delivery_date, o.progress,
                           o.user_id as buyer_id, u.username AS buyer_name, u.email AS buyer_email,
                           o.invoice_id
                    FROM orders o
                    JOIN auctions a ON o.auction_id = a.id
                    JOIN users u ON o.user_id = u.id
                    WHERE o.order_id = %s AND (o.user_id = %s OR a.user_id = %s)
                """, [order_id, user_id, user_id])
                order_detail = cursor.fetchone()
            print(f"DEBUG: Order {order_id} details: {order_detail}")
        except Exception as e:
            print(f"DEBUG: Error fetching order {order_id}: {e}")
            messages.error(request, "Error fetching order details.")
            return render(request, 'view_orders.html', context)

        if order_detail:
            def map_order_detail(order):
                mapped = {
                    "order_id": order[0],
                    "auction_id": order[1],
                    "title": order[2],
                    "auction_type": order[3],
                    "payment_status": order[4],
                    "payment_amount": float(order[5]) if order[5] is not None else 0.0,
                    "order_status": order[6] if order[6] else "Pending",
                    "order_date": format_date(order[7]),
                    "shipping_status": order[8] if order[8] else "Not Shipped",
                    "shipping_address": order[9] if order[9] else "N/A",
                    "tracking_number": order[10] if order[10] else "N/A",
                    "delivery_date": format_date_only(order[11]),
                    "progress": order[12] if order[12] is not None else 0,
                    "buyer_id": order[13],
                    "buyer_name": order[14],
                    "buyer_email": order[15],
                    "images": fetch_auction_images(order[1]),
                    "invoice_id": order[16] if order[16] else ""
                }
                if mapped["auction_type"] == "buy_it_now":
                    shipping = fetch_shipping_details(mapped["order_id"])
                    if shipping:
                        mapped["shipping_address"] = shipping.get("shipping_address", mapped["shipping_address"])
                        if shipping.get("delivery_date"):
                            mapped["delivery_date"] = format_date_only(shipping["delivery_date"])
                return mapped

            context["order_detail"] = map_order_detail(order_detail)
        else:
            messages.error(request, "Order not found or you lack permission to view it.")

    # Fetch all seller and buyer orders
    try:
        with connection.cursor() as cursor:
            # Seller orders
            cursor.execute("""
                SELECT o.order_id, o.auction_id, a.title, o.payment_status, o.payment_amount, o.order_status,
                       o.order_date, o.shipping_status, o.shipping_address, o.tracking_number, o.delivery_date,
                       u.username AS buyer_name, u.email AS buyer_email, o.progress, a.auction_type, o.invoice_id
                FROM orders o
                JOIN auctions a ON o.auction_id = a.id
                JOIN users u ON o.user_id = u.id
                WHERE a.user_id = %s
                ORDER BY o.order_date DESC
            """, [user_id])
            seller_orders = cursor.fetchall()
            print(f"DEBUG: Seller orders for user {user_id}: {seller_orders}")

            # Buyer orders
            cursor.execute("""
                SELECT o.order_id, o.auction_id, a.title, o.payment_status, o.payment_amount,
                       o.order_date, o.order_status, o.shipping_status, o.shipping_address,
                       o.tracking_number, o.delivery_date, o.progress, a.auction_type, o.invoice_id
                FROM orders o
                JOIN auctions a ON o.auction_id = a.id
                WHERE o.user_id = %s
                ORDER BY o.order_date DESC
            """, [user_id])
            buyer_orders = cursor.fetchall()
            print(f"DEBUG: Buyer orders for user {user_id}: {buyer_orders}")
    except Exception as e:
        print(f"DEBUG: Error fetching orders: {e}")
        messages.error(request, "Error fetching orders.")
        return render(request, 'view_orders.html', context)

    def map_seller_order(order):
        auction_id = order[1]
        mapped = {
            "order_id": order[0],
            "auction_id": auction_id,
            "title": order[2],
            "payment_status": order[3],
            "payment_amount": float(order[4]) if order[4] is not None else 0.0,
            "order_status": order[5] if order[5] else "Pending",
            "order_date": format_date(order[6]),
            "shipping_status": order[7] if order[7] else "Not Shipped",
            "shipping_address": order[8] if order[8] else "N/A",
            "tracking_number": order[9] if order[9] else "N/A",
            "delivery_date": format_date_only(order[10]),
            "buyer_name": order[11],
            "buyer_email": order[12],
            "progress": order[13] if order[13] is not None else 0,
            "auction_type": order[14],
            "images": fetch_auction_images(auction_id),
            "invoice_id": order[15] if order[15] else ""
        }
        if mapped["auction_type"] == "buy_it_now":
            shipping = fetch_shipping_details(mapped["order_id"])
            if shipping:
                mapped["shipping_address"] = shipping.get("shipping_address", mapped["shipping_address"])
                if shipping.get("delivery_date"):
                    mapped["delivery_date"] = format_date_only(shipping["delivery_date"])
        return mapped

    def map_buyer_order(order):
        auction_id = order[1]
        mapped = {
            "order_id": order[0],
            "auction_id": auction_id,
            "title": order[2],
            "payment_status": order[3],
            "payment_amount": float(order[4]) if order[4] is not None else 0.0,
            "order_date": format_date(order[5]),
            "order_status": order[6] if order[6] else "Pending",
            "shipping_status": order[7] if order[7] else "Not Shipped",
            "shipping_address": order[8] if order[8] else "N/A",
            "tracking_number": order[9] if order[9] else "N/A",
            "delivery_date": format_date_only(order[10]),
            "progress": order[11] if order[11] is not None else 0,
            "auction_type": order[12],
            "images": fetch_auction_images(auction_id),
            "invoice_id": order[13] if order[13] is not None else ""
        }
        if mapped["auction_type"] == "buy_it_now":
            shipping = fetch_shipping_details(mapped["order_id"])
            if shipping:
                mapped["shipping_address"] = shipping.get("shipping_address", mapped["shipping_address"])
                if shipping.get("delivery_date"):
                    mapped["delivery_date"] = format_date_only(shipping["delivery_date"])
        return mapped

    seller_orders_list = [map_seller_order(order) for order in seller_orders]
    buyer_orders_list = [map_buyer_order(order) for order in buyer_orders]
    print(f"DEBUG: Mapped buyer orders: {buyer_orders_list}")

    context.update({
        "seller_orders": seller_orders_list,
        "buyer_orders": buyer_orders_list,
        "total_orders": len(seller_orders_list) + len(buyer_orders_list),
        "completed_orders": len([o for o in buyer_orders_list if o['shipping_status'] == 'Delivered']),
    })

    return render(request, 'view_orders.html', context)


def update_shipping_details(request):
    """
    Update the shipping details for an order in both the orders and shipping_details tables.
    Combines the primary and secondary contact numbers into the shipping address for the orders table.
    Updates or inserts into the shipping_details table with detailed shipping information, including full_name and shipping_date.
    Includes debug logging for inputs, queries, and errors.
    """
    logger.debug("Entering update_shipping_details function")

    if request.method == "POST":
        user_id = request.session.get('user_id')
        logger.debug(f"User ID from session: {user_id}")

        if not user_id:
            logger.error("No user_id in session; user not logged in")
            messages.error(request, "You must be logged in to update shipping details.")
            return redirect('login')

        # Log POST data
        post_data = {
            'order_id': request.POST.get('order_id'),
            'full_name': request.POST.get('full_name'),
            'full_address': request.POST.get('full_address'),
            'city': request.POST.get('city'),
            'state': request.POST.get('state'),
            'zip_code': request.POST.get('zip_code'),
            'country': request.POST.get('country'),
            'contact_number_primary': request.POST.get('contact_number_primary'),
            'contact_number_secondary': request.POST.get('contact_number_secondary')
        }
        logger.debug(f"POST data received: {post_data}")

        order_id = post_data['order_id']
        full_name = post_data['full_name']
        full_address = post_data['full_address']
        city = post_data['city']
        state = post_data['state']
        zip_code = post_data['zip_code']
        country = post_data['country']
        contact_number_primary = post_data['contact_number_primary']
        contact_number_secondary = post_data['contact_number_secondary']

        # Validate required fields
        if not all([order_id, full_name, full_address, city, state, zip_code, country, contact_number_primary]):
            logger.error("Missing required fields in POST data")
            messages.error(request, "All required shipping details must be provided.")
            return redirect('view_orders')

        # Combine the address and contact numbers into a single shipping address string for the orders table
        shipping_address = (
            f"{full_address}, {city}, {state}, {zip_code}, {country}. "
            f"Primary Contact: {contact_number_primary}"
        )
        if contact_number_secondary:
            shipping_address += f", Secondary Contact: {contact_number_secondary}"
        logger.debug(f"Constructed shipping_address: {shipping_address}")

        try:
            with connection.cursor() as cursor:
                # Fetch invoice_id and buyer_id from the orders table
                logger.debug(f"Executing SELECT query for orders with order_id={order_id}, user_id={user_id}")
                cursor.execute("""
                    SELECT invoice_id, user_id
                    FROM orders
                    WHERE order_id = %s AND user_id = %s
                """, [order_id, user_id])
                order_data = cursor.fetchone()
                logger.debug(f"Order query result: {order_data}")

                if not order_data:
                    logger.error(f"No order found for order_id={order_id}, user_id={user_id}")
                    messages.error(request, "Order not found or you do not have permission to update it.")
                    return redirect('view_orders')

                invoice_id, buyer_id = order_data
                logger.debug(f"Retrieved invoice_id={invoice_id}, buyer_id={buyer_id}")

                if not invoice_id:
                    logger.error(f"No invoice_id associated with order_id={order_id}")
                    messages.error(request, "Order does not have an associated invoice.")
                    return redirect('view_orders')

                # Combine primary and secondary contact numbers for the phone field
                phone = contact_number_primary
                if contact_number_secondary:
                    phone += f" / {contact_number_secondary}"
                logger.debug(f"Constructed phone: {phone}")

                # Update the orders table
                logger.debug(f"Executing UPDATE query for orders with order_id={order_id}, user_id={user_id}")
                cursor.execute("""
                    UPDATE orders
                    SET shipping_address = %s
                    WHERE order_id = %s AND user_id = %s
                """, [shipping_address, order_id, user_id])
                logger.debug(f"Orders table updated, rows affected: {cursor.rowcount}")

                # Check if a shipping_details entry already exists for this order
                logger.debug(f"Executing SELECT query for shipping_details with order_id={order_id}")
                cursor.execute("""
                    SELECT id
                    FROM shipping_details
                    WHERE order_id = %s
                """, [order_id])
                existing_shipping = cursor.fetchone()
                logger.debug(f"Shipping details query result: {existing_shipping}")

                if existing_shipping:
                    # Update existing shipping_details entry
                    logger.debug(f"Executing UPDATE query for shipping_details with order_id={order_id}")
                    cursor.execute("""
                        UPDATE shipping_details
                        SET full_name = %s, phone = %s, address = %s, city = %s, state = %s, 
                            zip_code = %s, country = %s, shipping_date = NOW()
                        WHERE order_id = %s
                    """, [full_name, phone, full_address, city, state, zip_code, country, order_id])
                    logger.info(f"Updated shipping_details for order_id={order_id}, rows affected: {cursor.rowcount}")
                else:
                    # Insert new shipping_details entry
                    logger.debug(f"Executing INSERT query for shipping_details with order_id={order_id}")
                    cursor.execute("""
                        INSERT INTO shipping_details (
                            order_id, invoice_id, buyer_id, full_name, phone, address, city, state, 
                            zip_code, country, shipping_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, [order_id, invoice_id, buyer_id, full_name, phone, full_address, city, state, zip_code,
                          country])
                    logger.info(
                        f"Inserted new shipping_details for order_id={order_id}, rows affected: {cursor.rowcount}")

                logger.info(f"Shipping details updated successfully for order_id={order_id}")
                messages.success(request, "Shipping details updated successfully!")
                return redirect('view_orders')

        except Exception as e:
            logger.exception(f"Error updating shipping details for order_id={order_id}: {str(e)}")
            messages.error(request, f"Failed to update shipping details: {str(e)}")
            return redirect('view_orders')

    logger.error("Invalid request method; expected POST")
    messages.error(request, "Invalid request.")
    return redirect('view_orders')

@require_POST
def seller_confirm_order(request):
    """
    Seller confirms an order.
    Updates the order's status to "Confirmed" if the order belongs to an auction created by the seller.
    After confirmation, sends a notification and email to the buyer (and a notification to the seller).
    """
    seller_id = request.session.get('user_id')
    if not seller_id:
        messages.error(request, "You must be logged in as a seller to confirm orders.")
        return redirect('login')

    order_id = request.POST.get('order_id')
    if not order_id:
        messages.error(request, "Order ID is missing.")
        return redirect('view_orders')

    with connection.cursor() as cursor:
        # Retrieve the buyer's details and seller's email by joining the relevant tables.
        cursor.execute("""
            SELECT o.order_id, o.user_id, buyer.email, seller.email
            FROM orders o
            JOIN auctions a ON o.auction_id = a.id
            JOIN users buyer ON o.user_id = buyer.id
            JOIN users seller ON a.user_id = seller.id
            WHERE o.order_id = %s AND a.user_id = %s
        """, [order_id, seller_id])
        result = cursor.fetchone()
        if not result:
            messages.error(request, "Order not found or you are not authorized to confirm it.")
            return redirect('view_orders')

        # Extract buyer and seller details from the query result.
        buyer_id = result[1]
        buyer_email = result[2]
        seller_email = result[3]

        # Update order_status to "Confirmed"
        cursor.execute("""
                   UPDATE orders
                   SET order_status = %s, progress = %s
                   WHERE order_id = %s
               """, ["Confirmed", 10, order_id])

    # Prepare notification messages.
    buyer_message = "Your order has been confirmed by the seller. Thank you for your purchase!"
    seller_message = "You have confirmed the order. The buyer has been notified."

    # Send notifications (and email) to buyer and seller.
    notify_user(buyer_id, buyer_email, buyer_message, subject="Order Confirmed!")
    notify_user(seller_id, seller_email, seller_message, subject="Order Confirmed!")

    # Compose and send the email to the buyer.
    subject = "Your Order Has Been Confirmed"
    message = (
        f"Dear Customer,\n\n"
        f"Your order #{order_id} has been confirmed by the seller.\n"
        f"Thank you for shopping with us!\n\n"
        f"Best regards,\n"
        f"The Team"
    )
    recipient_list = [buyer_email]
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)

    messages.success(request, "Order confirmed successfully, and the buyer has been notified.")
    return redirect('view_orders')


@require_POST
def seller_cancel_order(request):
    """
    Seller cancels an order with a provided cancellation reason.
    Updates the order's status to "Canceled" if the order belongs to an auction created by the seller.
    The cancellation reason is then sent to the buyer via email and in-app notification.
    """
    seller_id = request.session.get('user_id')
    if not seller_id:
        messages.error(request, "You must be logged in as a seller to cancel orders.")
        return redirect('login')

    order_id = request.POST.get('order_id')
    cancel_reason = request.POST.get('cancel_reason')
    if not order_id:
        messages.error(request, "Order ID is missing.")
        return redirect('view_orders')
    if not cancel_reason:
        messages.error(request, "Cancellation reason is required.")
        return redirect('view_orders')

    with connection.cursor() as cursor:
        # Retrieve buyer and seller email details.
        cursor.execute("""
            SELECT o.order_id, o.user_id, buyer.email, seller.email
            FROM orders o
            JOIN auctions a ON o.auction_id = a.id
            JOIN users buyer ON o.user_id = buyer.id
            JOIN users seller ON a.user_id = seller.id
            WHERE o.order_id = %s AND a.user_id = %s
        """, [order_id, seller_id])
        result = cursor.fetchone()
        if not result:
            messages.error(request, "Order not found or you are not authorized to cancel it.")
            return redirect('view_orders')

        buyer_id = result[1]
        buyer_email = result[2]
        seller_email = result[3]

        # Update order_status to "Canceled"
        cursor.execute("""
            UPDATE orders
            SET order_status = %s
            WHERE order_id = %s
        """, ["Rejected", order_id])

    # Prepare notification messages including the cancellation reason.
    buyer_message = f"Your order #{order_id} has been canceled by the seller. Reason: {cancel_reason}"
    seller_message = f"You have canceled order #{order_id} with reason: {cancel_reason}"

    # Send notifications (and email) to buyer and seller.
    notify_user(buyer_id, buyer_email, buyer_message, subject="Order Canceled")
    notify_user(seller_id, seller_email, seller_message, subject="Order Canceled")

    # Compose and send the email to the buyer.
    subject = "Your Order Has Been Canceled"
    message = (
        f"Dear Customer,\n\n"
        f"Your order #{order_id} has been canceled by the seller.\n"
        f"Cancellation Reason: {cancel_reason}\n"
        f"We apologize for any inconvenience caused.\n\n"
        f"Best regards,\n"
        f"The Team"
    )
    recipient_list = [buyer_email]
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)

    messages.success(request, "Order canceled successfully, and the buyer has been notified.")
    return redirect('view_orders')


def add_review(request):
    if request.method == "POST":
        user_id = request.session.get("user_id")  # Fetch logged-in user's ID from session
        order_id = request.POST.get("order_id")
        rating = request.POST.get("rating")
        reasons = request.POST.getlist("reason")  # Multiple selected reasons
        custom_reason = request.POST.get("custom_reason", "").strip()
        comments = request.POST.get("comments", "").strip()

        if not user_id:
            messages.error(request, "You need to be logged in to submit a review.")
            return redirect("view_orders")

        # Combine reasons into a single string
        reason_text = ", ".join(reasons)
        if custom_reason:
            reason_text += f", {custom_reason}" if reason_text else custom_reason

        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO reviews (order_id, user_id, rating, reasons, comments, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, [order_id, user_id, rating, reason_text, comments])

        messages.success(request, "Review submitted successfully!")
        return redirect("view_orders")  # Redirect back to orders page

    messages.error(request, "Invalid request.")
    return redirect("view_orders")






@require_POST
def contact_seller(request):
    """
    Handles sending a message with optional file attachment.
    For buyers: receiver is the seller, and sends email notification for new chats.
    For sellers: if a hidden 'buyer_id' is provided, use that as receiver.
    Otherwise, reply to the latest buyer enquiry.
    """
    auction_id = request.POST.get("auction_id")
    message = request.POST.get("message", "")
    buyer_id = request.POST.get("buyer_id")
    attachment = request.FILES.get("attachment")

    if not auction_id or (not message and not attachment):
        return HttpResponseBadRequest("Missing parameters or empty message/file.")

    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"error": "User not authenticated"}, status=401)

    # File validation
    if attachment:
        if attachment.size > 300 * 1024:  # 300KB limit
            return JsonResponse({"error": "File size exceeds 300KB limit"}, status=400)
        allowed_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.pdf', '.txt', '.doc', '.docx']
        ext = os.path.splitext(attachment.name)[1].lower()
        if ext not in allowed_extensions:
            return JsonResponse({"error": "Invalid file type"}, status=400)

    # Fetch auction details and seller's ID
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id, title FROM auctions WHERE id = %s", [auction_id])
        row = cursor.fetchone()
        if not row:
            return HttpResponseBadRequest("Auction not found.")
        seller_id, auction_title = row

    # Determine receiver
    if buyer_id:
        receiver_id = buyer_id
    else:
        if user_id != seller_id:
            receiver_id = seller_id
        else:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT sender_id FROM messages 
                    WHERE auction_id = %s AND receiver_id = %s 
                    ORDER BY timestamp DESC LIMIT 1
                """, [auction_id, seller_id])
                row = cursor.fetchone()
                if row:
                    receiver_id = row[0]
                else:
                    return JsonResponse({"error": "No buyer found to reply to."}, status=400)

    # Check if this is a new buyer-initiated chat
    send_notification = False
    buyer_username = None
    seller_email = None
    if user_id != seller_id:  # Buyer sending to seller
        with connection.cursor() as cursor:
            # Check if this is the first message for this buyer-seller-auction
            cursor.execute("""
                SELECT COUNT(*) FROM messages 
                WHERE auction_id = %s AND sender_id = %s AND receiver_id = %s
            """, [auction_id, user_id, seller_id])
            message_count = cursor.fetchone()[0]
            if message_count == 0:
                send_notification = True
                # Fetch buyer username and seller email
                cursor.execute("SELECT username FROM users WHERE id = %s", [user_id])
                buyer_username = cursor.fetchone()[0]
                cursor.execute("SELECT email FROM users WHERE id = %s", [seller_id])
                seller_email = cursor.fetchone()[0]

    # Handle file upload
    attachment_path = None
    if attachment:
        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'messages'))
        filename = f"{uuid.uuid4()}{os.path.splitext(attachment.name)[1]}"
        attachment_path = fs.save(filename, attachment)
        attachment_url = request.build_absolute_uri(f"{settings.MEDIA_URL}messages/{attachment_path}")
    else:
        attachment_url = None

    # Insert the message
    timestamp = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO messages (auction_id, sender_id, receiver_id, message, timestamp, attachment)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, [auction_id, user_id, receiver_id, message, timestamp, attachment_path])
        msg_id = cursor.lastrowid

    # Fetch sender's username
    with connection.cursor() as cursor:
        cursor.execute("SELECT username FROM users WHERE id = %s", [user_id])
        row = cursor.fetchone()
        if not row:
            return JsonResponse({"error": "Sender not found."}, status=500)
        sender_username = row[0]

    # Send email notification for new buyer chat
    if send_notification and seller_email:
        subject = f"New Chat Message for Auction: {auction_title}"
        message_snippet = message[:50] + ("..." if len(message) > 50 else "")
        email_body = (
            f"Dear Seller,\n\n"
            f"You have received a new message from {buyer_username} regarding your auction '{auction_title}'.\n\n"
            f"Message: {message_snippet}\n\n"
            f"To respond, please visit the chat section on the auction platform.\n\n"
            f"Best regards,\nAuction Platform Team"
        )
        try:
            send_mail(
                subject=subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[seller_email],
                fail_silently=False,
            )
        except Exception as e:
            # Log the error but don't fail the request
            print(f"Failed to send email notification: {e}")

    # Return success response
    return JsonResponse({
        "success": True,
        "msg_id": msg_id,
        "sender_id": user_id,
        "sender_username": sender_username,
        "message": message,
        "timestamp": timestamp.isoformat(),
        "attachment": attachment_url
    })
def seller_inbox(request):
    """
    Displays the seller's inbox with a list of unique buyers who sent messages,
    along with the count of messages per buyer and their profile picture.
    Supports both HTML and real-time JSON response.
    """
    seller_id = request.session.get("user_id")
    if not seller_id:
        return JsonResponse({"error": "User not authenticated"}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT m.sender_id, u.username, u.profile_picture, COUNT(*) AS message_count, MAX(m.timestamp) AS last_timestamp
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.receiver_id = %s
            GROUP BY m.sender_id, u.username, u.profile_picture
            ORDER BY last_timestamp DESC
        """, [seller_id])
        rows = cursor.fetchall()

    inbox = []
    for row in rows:
        profile_picture = row[2]
        if profile_picture:
            profile_picture_url = f"/media/{profile_picture}"
        else:
            profile_picture_url = "/static/images/default_profile.png"

        inbox.append({
            "sender_id": row[0],
            "username": row[1],
            "profile_picture": profile_picture_url,
            "message_count": row[3],
            "last_timestamp": row[4],
        })

    # Return JSON response for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({"inbox": inbox}, safe=False)

    # Render the HTML page for normal requests
    return render(request, "seller_inbox.html", {"inbox": inbox})


def chat_detail(request, buyer_id):
    seller_id = request.session.get("user_id")
    if not seller_id:
        return JsonResponse({"error": "User not authenticated"}, status=401)

    # Fetch messages between seller and buyer
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT m.id, m.auction_id, m.sender_id, u.username, m.message, m.timestamp, m.attachment
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE (m.sender_id = %s AND m.receiver_id = %s)
               OR (m.sender_id = %s AND m.receiver_id = %s)
            ORDER BY m.timestamp ASC
        """, [buyer_id, seller_id, seller_id, buyer_id])
        rows = cursor.fetchall()

    messages_list = [
        {
            "id": row[0],
            "auction_id": row[1],
            "sender_id": row[2],
            "sender_username": row[3],
            "message": row[4],
            "timestamp": row[5].isoformat() if isinstance(row[5], datetime) else row[5],
            "attachment": f"{settings.MEDIA_URL}messages/{row[6]}" if row[6] else None
        } for row in rows
    ]

    # Fetch buyer details
    with connection.cursor() as cursor:
        cursor.execute("SELECT username, profile_picture FROM users WHERE id = %s", [buyer_id])
        buyer_data = cursor.fetchone()

    if buyer_data:
        profile_pic = (
            f"{settings.MEDIA_URL}{buyer_data[1]}" if buyer_data[1]
            else f"{settings.STATIC_URL}images/default_profile.png"
        )
    else:
        profile_pic = f"{settings.STATIC_URL}images/default_profile.png"

    buyer = {
        "id": buyer_id,
        "username": buyer_data[0] if buyer_data else "Unknown",
        "profile_picture": profile_pic
    }

    context = {
        "messages": messages_list,
        "buyer": buyer,
        "buyer_id": buyer_id,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(context)

    return render(request, "chat_detail.html", context)



@require_GET
def messages_received(request):
    auction_id = request.GET.get('auction_id')
    user_id = request.session.get('sender_id') or request.session.get('user_id')

    if not auction_id or not user_id:
        return JsonResponse({'success': False, 'error': 'Missing auction_id or user_id'}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    m.id,
                    m.sender_id,
                    u.username AS sender_username,
                    m.message,
                    m.timestamp,
                    m.attachment
                FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.auction_id = %s
                AND (m.sender_id = %s OR m.receiver_id = %s)
                ORDER BY m.timestamp ASC
            """, [auction_id, user_id, user_id])
            messages = cursor.fetchall()

        messages_data = [
            {
                'id': msg[0],
                'sender_id': msg[1],
                'sender_username': msg[2],
                'message': msg[3],
                'timestamp': msg[4].isoformat() if isinstance(msg[4], datetime) else msg[4],
                'attachment': f"{settings.MEDIA_URL}messages/{msg[5]}" if msg[5] else None
            } for msg in messages
        ]

        return JsonResponse({'success': True, 'messages': messages_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@require_POST
def delete_conversation(request, buyer_id):
    """
    Deletes the entire conversation between the seller (current user) and the specified buyer.
    """
    seller_id = request.session.get("user_id")
    if not seller_id:
        return JsonResponse({"error": "User not authenticated"}, status=401)

    # Delete all messages between seller and buyer
    with connection.cursor() as cursor:
        cursor.execute("""
            DELETE FROM messages
            WHERE (sender_id = %s AND receiver_id = %s)
               OR (sender_id = %s AND receiver_id = %s)
        """, [buyer_id, seller_id, seller_id, buyer_id])

    # Redirect back to the seller inbox
    return redirect('seller_inbox')





def clear_chat(request):
    if request.method == "POST":
        user_id = request.session.get("user_id")  # Logged-in user
        other_user_id = request.POST.get("other_user_id")  # Chat partner

        if not user_id or not other_user_id:
            print("❌ ERROR: Missing user_id or other_user_id")  # Debugging
            return JsonResponse({"status": "error", "message": "Invalid request. Missing user ID."}, status=400)

        try:
            print(f"✅ Deleting chat between {user_id} and {other_user_id}")  # Debugging

            with connection.cursor() as cursor:
                query = """
                DELETE FROM messages 
                WHERE (sender_id = %s AND receiver_id = %s) 
                   OR (sender_id = %s AND receiver_id = %s)
                """
                cursor.execute(query, [user_id, other_user_id, other_user_id, user_id])

            print("✅ Chat deleted successfully!")  # Debugging
            return JsonResponse({"status": "success", "message": "Chat cleared successfully"})

        except Exception as e:
            print(f"❌ ERROR: {str(e)}")  # Print exact error in logs
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    print("❌ ERROR: Invalid request method")  # Debugging
    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)




def report_block_user(request):
    if request.method == "POST":
        user_id = request.session.get("user_id")  # Logged-in user
        target_user_id = request.POST.get("target_user_id")  # User being reported/blocked
        action = request.POST.get("action")  # 'report' or 'block'
        reason = request.POST.get("reason", "")  # Reason for reporting (optional)

        if not user_id or not target_user_id:
            return JsonResponse({"status": "error", "message": "Invalid request. Missing user IDs."}, status=400)

        try:
            with connection.cursor() as cursor:
                if action == "report":
                    # ✅ Insert Report into `reported_users`
                    query = """
                    INSERT INTO reported_users (reported_by, reported_user, reason, report_date) 
                    VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(query, [user_id, target_user_id, reason, datetime.now()])  # ✅ Fixed
                    return JsonResponse({"status": "success", "message": "User reported successfully!"})

                elif action == "block":
                    # ✅ Insert Block into `blocked_users`
                    query = """
                    INSERT INTO blocked_users (blocked_by, blocked_user, block_date) 
                    VALUES (%s, %s, %s)
                    """
                    cursor.execute(query, [user_id, target_user_id, datetime.now()])  # ✅ Fixed
                    return JsonResponse({"status": "success", "message": "User blocked successfully!"})

                else:
                    return JsonResponse({"status": "error", "message": "Invalid action."}, status=400)

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)


def block_user(request):
    if request.method == "POST":
        user_id = request.session.get("user_id")  # Logged-in user (who is blocking)
        target_user_id = request.POST.get("target_user_id")  # User being blocked

        if not user_id or not target_user_id:
            return JsonResponse({"status": "error", "message": "Invalid request. Missing user IDs."}, status=400)

        try:
            with connection.cursor() as cursor:
                # ✅ Insert into `blocked_users`
                query = """
                INSERT INTO blocked_users (blocked_by, blocked_user, block_date) 
                VALUES (%s, %s, %s)
                """
                cursor.execute(query, [user_id, target_user_id, datetime.now()])

            return JsonResponse({"status": "success", "message": "User blocked successfully!"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)


def wallet_dashboard(request):
    user_id = request.session.get('user_id')
    logger.debug(f"wallet_dashboard - User ID from session: {user_id}")

    if not user_id:
        messages.error(request, "You must be logged in to view your wallet.")
        logger.warning("wallet_dashboard - No user_id in session, redirecting to login")
        return redirect('login')

    # Determine the referer to identify if coming from place_bid
    referer = request.META.get('HTTP_REFERER', '')
    from_place_bid = False
    auction_id = None

    if referer:
        parsed_url = urlparse(referer)
        path = parsed_url.path
        # Check if referer matches the place_bid URL pattern (e.g., /place_bid/123/)
        match = re.match(r'^/place_bid/(\d+)/$', path)
        if match:
            from_place_bid = True
            auction_id = int(match.group(1))
            logger.debug(f"wallet_dashboard - Referer from place_bid, auction_id: {auction_id}")
        else:
            logger.debug(f"wallet_dashboard - Referer not from place_bid: {referer}")

    # Store referer info in session to persist across POST requests
    request.session['from_place_bid'] = from_place_bid
    request.session['auction_id'] = auction_id
    logger.debug(f"wallet_dashboard - Session updated: from_place_bid={from_place_bid}, auction_id={auction_id}")

    try:
        with connection.cursor() as cursor:
            # Check if wallet exists
            cursor.execute("SELECT balance FROM wallets WHERE user_id = %s", [user_id])
            result = cursor.fetchone()
            logger.debug(f"wallet_dashboard - Database query result: {result}")

            if result is None:
                # Create a new wallet with balance 0.0 if none exists
                cursor.execute("INSERT INTO wallets (user_id, balance) VALUES (%s, %s)", [user_id, 0.0])
                logger.info(f"wallet_dashboard - Created new wallet for user_id: {user_id} with balance: 0.0")
                balance = 0.0
            else:
                balance = float(result[0])
    except Exception as e:
        messages.error(request, "Error accessing wallet balance. Please try again later.")
        logger.error(f"wallet_dashboard - Database error: {str(e)}")
        balance = 0.0

    return render(request, 'wallet.html', {
        'balance': balance,
        'from_place_bid': from_place_bid,
        'auction_id': auction_id
    })

def deposit_wallet(request):
    user_id = request.session.get('user_id')
    logger.debug(f"deposit_wallet - User ID from session: {user_id}")

    if not user_id:
        messages.error(request, "You must be logged in to deposit funds.")
        logger.warning("deposit_wallet - No user_id in session, redirecting to login")
        return redirect('login')

    # Get referer info from session
    from_place_bid = request.session.get('from_place_bid', False)
    auction_id = request.session.get('auction_id', None)
    logger.debug(f"deposit_wallet - Session data: from_place_bid={from_place_bid}, auction_id={auction_id}")

    if request.method == "POST":
        amount = request.POST.get('amount')
        logger.debug(f"deposit_wallet - POST data: amount={amount}")

        payment_details = {
            'card_number': request.POST.get('card_number'),
            'expiry_date': request.POST.get('expiry_date'),
            'cvv': request.POST.get('cvv'),
            'upi_id': request.POST.get('upi_id'),
            'bank_name': request.POST.get('bank_name')
        }
        logger.debug(f"deposit_wallet - Payment details: {payment_details}")

        try:
            deposit_amount = float(amount)
        except (ValueError, TypeError):
            messages.error(request, "Invalid deposit amount. Please enter a valid number.")
            logger.warning(f"deposit_wallet - Invalid amount: {amount}")
            return redirect('wallet')

        if deposit_amount <= 0:
            messages.error(request, "Please enter a positive amount to deposit.")
            logger.warning(f"deposit_wallet - Non-positive amount: {deposit_amount}")
            return redirect('wallet')

        try:
            with connection.cursor() as cursor:
                # Check if wallet exists
                cursor.execute("SELECT balance FROM wallets WHERE user_id = %s", [user_id])
                result = cursor.fetchone()

                if result is None:
                    # Create a new wallet with the deposit amount
                    cursor.execute("INSERT INTO wallets (user_id, balance) VALUES (%s, %s)", [user_id, deposit_amount])
                    logger.info(f"deposit_wallet - Created new wallet for user_id: {user_id} with initial balance: {deposit_amount}")
                else:
                    # Update existing wallet
                    cursor.execute("""
                        UPDATE wallets 
                        SET balance = balance + %s 
                        WHERE user_id = %s
                    """, [deposit_amount, user_id])
                    if cursor.rowcount == 0:
                        messages.error(request, "Failed to update wallet balance.")
                        logger.error(f"deposit_wallet - Update failed for user_id: {user_id}")
                        return redirect('wallet')

                # Fetch user email for notification
                cursor.execute("SELECT email FROM users WHERE id = %s", [user_id])
                result = cursor.fetchone()
                user_email = result[0] if result else None

        except Exception as e:
            messages.error(request, "Error processing deposit. Please try again later.")
            logger.error(f"deposit_wallet - Database error: {str(e)}")
            return redirect('wallet')

        # Send notifications: Email and in-app
        if user_email:
            deposit_message = f"Your deposit of ₹{deposit_amount:.2f} was successful. Your wallet balance has been updated."
            notify_user(user_id, user_email, deposit_message, subject="Deposit Successful")
            logger.info(f"deposit_wallet - Notification sent to user {user_id} at {user_email}")

        messages.success(request, f"Successfully deposited ₹{deposit_amount:.2f}.")
        logger.info(f"deposit_wallet - Deposit successful for user_id: {user_id}, amount: {deposit_amount}")
        return redirect('wallet')

    return render(request, 'wallet.html', {
        'from_place_bid': from_place_bid,
        'auction_id': auction_id
    })


def withdraw_wallet(request):
    user_id = request.session.get('user_id')
    logger.debug(f"withdraw_wallet - User ID from session: {user_id}")

    if not user_id:
        messages.error(request, "You must be logged in to withdraw funds.")
        logger.warning("withdraw_wallet - No user_id in session, redirecting to login")
        return redirect('login')

    # Get referer info from session
    from_place_bid = request.session.get('from_place_bid', False)
    auction_id = request.session.get('auction_id', None)
    logger.debug(f"withdraw_wallet - Session data: from_place_bid={from_place_bid}, auction_id={auction_id}")

    if request.method == "POST":
        amount = request.POST.get('amount')
        logger.debug(f"withdraw_wallet - POST data: amount={amount}")

        withdrawal_details = {
            'bank_account': request.POST.get('bank_account'),
            'account_number': request.POST.get('account_number'),
            'ifsc_code': request.POST.get('ifsc_code')
        }
        logger.debug(f"withdraw_wallet - Withdrawal details: {withdrawal_details}")

        try:
            withdraw_amount = float(amount)
        except (ValueError, TypeError):
            messages.error(request, "Invalid withdrawal amount. Please enter a valid number.")
            logger.warning(f"withdraw_wallet - Invalid amount: {amount}")
            return redirect('wallet')

        if withdraw_amount <= 0:
            messages.error(request, "Please enter a positive amount to withdraw.")
            logger.warning(f"withdraw_wallet - Non-positive amount: {withdraw_amount}")
            return redirect('wallet')

        try:
            with connection.cursor() as cursor:
                # Check if wallet exists and get balance
                cursor.execute("SELECT balance FROM wallets WHERE user_id = %s", [user_id])
                result = cursor.fetchone()
                logger.debug(f"withdraw_wallet - Current balance query result: {result}")

                if result is None:
                    # Create a new wallet with zero balance (withdrawal will fail due to insufficient balance)
                    cursor.execute("INSERT INTO wallets (user_id, balance) VALUES (%s, %s)", [user_id, 0.0])
                    logger.info(f"withdraw_wallet - Created new wallet for user_id: {user_id} with balance: 0.0")
                    balance = 0.0
                else:
                    balance = float(result[0])

                if withdraw_amount > balance:
                    messages.error(request, "Insufficient balance for this withdrawal.")
                    logger.warning(f"withdraw_wallet - Insufficient balance: {balance} < {withdraw_amount}")
                    return redirect('wallet')

                cursor.execute("""
                    UPDATE wallets 
                    SET balance = balance - %s 
                    WHERE user_id = %s
                """, [withdraw_amount, user_id])
                if cursor.rowcount == 0:
                    messages.error(request, "Failed to update wallet balance.")
                    logger.error(f"withdraw_wallet - Update failed for user_id: {user_id}")
                    return redirect('wallet')

                # Fetch user email for notification
                cursor.execute("SELECT email FROM users WHERE id = %s", [user_id])
                result = cursor.fetchone()
                user_email = result[0] if result else None

        except Exception as e:
            messages.error(request, "Error processing withdrawal. Please try again later.")
            logger.error(f"withdraw_wallet - Database error: {str(e)}")
            return redirect('wallet')

        # Send notifications: Email and in-app
        if user_email:
            withdraw_message = f"Your withdrawal of ₹{withdraw_amount:.2f} was successful. Your wallet balance has been updated."
            notify_user(user_id, user_email, withdraw_message, subject="Withdrawal Successful")
            logger.info(f"withdraw_wallet - Notification sent to user {user_id} at {user_email}")

        messages.success(request, f"Successfully withdrew ₹{withdraw_amount:.2f}.")
        logger.info(f"withdraw_wallet - Withdrawal successful for user_id: {user_id}, amount: {withdraw_amount}")
        return redirect('wallet')

    return render(request, 'wallet.html', {
        'from_place_bid': from_place_bid,
        'auction_id': auction_id
    })



def submit_feedback(request):
    """
    A view for users to submit feedback with optional file uploads.
    - On GET: Displays the feedback form. If a user is logged in, pre-populates name and email.
    - On POST: Saves feedback and file paths in the feedback table using raw SQL.
    """
    if request.method == "POST":
        # Retrieve form values
        user_id = request.session.get("user_id")  # Could be None for anonymous feedback
        name = request.POST.get("name")
        email = request.POST.get("email")
        subject = request.POST.get("subject")
        message = request.POST.get("message")
        files = request.FILES.getlist("files")  # Get list of uploaded files

        # Basic validation
        if not name or not email or not subject or not message:
            context = {
                "error": "Please fill all required fields.",
                "name": name,
                "email": email,
                "subject": subject,
                "message": message
            }
            return render(request, "feedback_form.html", context)

        # Validate files (optional: limit to 5 files, 10MB each)
        file_paths = []
        if files:
            for file in files:
                if file.size > 10 * 1024 * 1024:  # 10MB limit
                    context = {
                        "error": f"File {file.name} exceeds 10MB limit.",
                        "name": name,
                        "email": email,
                        "subject": subject,
                        "message": message
                    }
                    return render(request, "feedback_form.html", context)
            if len(files) > 5:
                context = {
                    "error": "You can upload a maximum of 5 files.",
                    "name": name,
                    "email": email,
                    "subject": subject,
                    "message": message
                }
                return render(request, "feedback_form.html", context)

            # Save files and collect paths
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'feedback'))
            os.makedirs(fs.location, exist_ok=True)  # Ensure feedback directory exists
            for file in files:
                filename = f"{uuid.uuid4()}_{file.name}"
                file_path = fs.save(filename, file)
                file_paths.append(os.path.join('feedback', file_path))

        # Join file paths into a comma-separated string (or None if no files)
        file_paths_str = ','.join(file_paths) if file_paths else None

        # Insert the feedback record with file_paths using raw SQL
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO feedback (user_id, name, email, subject, message, file_paths)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, [user_id, name, email, subject, message, file_paths_str])

        messages.success(request, "Thank you for your feedback!")
        return redirect("submit_feedback")

    # For GET, initialize a context dict
    context = {}
    user_id = request.session.get("user_id")
    if user_id:
        with connection.cursor() as cursor:
            cursor.execute("SELECT username, email FROM users WHERE id = %s", [user_id])
            row = cursor.fetchone()
        if row:
            context["name"] = row[0]  # Using username as the name
            context["email"] = row[1]
    return render(request, "feedback_form.html", context)












#admin
# In core/views.py
def list_users(request):
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "Please log in.")
        return redirect('login')

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
        user_role = cursor.fetchone()

    if not user_role or user_role[0] != 'admin':
        messages.error(request, "You are not authorized to access this page.")
        return redirect('login')

    # Fetch all non-admin users including their profile picture
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, username, email, role, is_authenticated, profile_picture
            FROM users
            WHERE role != 'admin'
            ORDER BY created_at DESC
        """)
        users = [
            {
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "role": row[3],
                "is_authenticated": row[4],
                "profile_picture": f"{settings.MEDIA_URL}{row[5]}" if row[5] else None,  # Prepend MEDIA_URL
            }
            for row in cursor.fetchall()
        ]

    context = {"users": users}

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(context)

    return render(request, "list_users.html", context)



def manage_user(request, user_id):
    """
    View to display and edit a user's details, including reports filed against them.
    Only an admin (logged in) can access this view.
    GET: Show user details (with a form for editing) along with:
         - All fields from the users table.
         - Auctions created by the user.
         - Auctions won by the user.
         - Auctions where the user has placed a bid.
         - Order history (won auctions that are sold).
         - Buying and selling orders from the orders table.
         - Reports filed against the user.
    POST: Update user details including bidding_restricted, premium, and account_status, return JSON response.
    """
    # Log the start of the view with the user_id being managed
    logger.debug(f"Starting manage_user view for user_id: {user_id}, request method: {request.method}")

    # Check that the logged-in user is an admin
    admin_id = request.session.get('user_id')
    logger.debug(f"Admin ID from session: {admin_id}")
    if not admin_id:
        logger.warning("No admin_id found in session, redirecting to login.")
        messages.error(request, "Please log in.")
        return redirect('login')

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    logger.debug(f"Admin role fetched: {admin_role}")
    if not admin_role or admin_role[0] != 'admin':
        logger.warning(f"User with ID {admin_id} is not an admin (role: {admin_role[0] if admin_role else None}), redirecting to login.")
        messages.error(request, "You are not authorized to access this page.")
        return redirect('login')

    if request.method == "GET":
        logger.info(f"Processing GET request for user_id: {user_id}")
        with connection.cursor() as cursor:
            # Fetch all user details from the users table
            logger.debug("Fetching all user details from users table.")
            cursor.execute("""
                SELECT id, username, email, password_hash, salt, created_at, role, email_verified, 
                       is_authenticated, bidding_restricted, bank_account_number, paypal_email, 
                       profile_picture, phone, address, email_notifications, sms_notifications, 
                       pincode, membership_plan_id, premium, account_status, id_proof, selfie
                FROM users
                WHERE id = %s
            """, [user_id])
            user_row = cursor.fetchone()
        if not user_row:
            logger.error(f"User with ID {user_id} not found, redirecting to list_users.")
            messages.error(request, "User not found.")
            return redirect('list_users')

        logger.debug(f"User details fetched: {user_row}")
        # Map all fetched columns to a dictionary
        user_detail = {
            "id": user_row[0],
            "username": user_row[1],
            "email": user_row[2],
            "password_hash": user_row[3],  # Sensitive, consider masking or not displaying
            "salt": user_row[4],           # Sensitive, consider masking or not displaying
            "created_at": user_row[5],
            "role": user_row[6],
            "email_verified": bool(user_row[7]),
            "is_authenticated": bool(user_row[8]),
            "bidding_restricted": bool(user_row[9]),
            "bank_account_number": user_row[10],
            "paypal_email": user_row[11],
            "profile_picture": f"{settings.MEDIA_URL}{user_row[12]}" if user_row[12] else None,
            "phone": user_row[13],
            "address": user_row[14],
            "email_notifications": bool(user_row[15]),
            "sms_notifications": bool(user_row[16]),
            "pincode": user_row[17],
            "membership_plan_id": user_row[18],
            "premium": bool(user_row[19]),
            "account_status": user_row[20] if user_row[20] else 'pending',
            "id_proof_url": f"{settings.MEDIA_URL}{user_row[21]}" if user_row[21] else None,
            "id_proof_path": user_row[21] if user_row[21] else None,
            "selfie_url": f"{settings.MEDIA_URL}{user_row[22]}" if user_row[22] else None,
            "selfie_path": user_row[22] if user_row[22] else None,
        }
        logger.debug(f"User details mapped: {user_detail}")

        # Extra validation: warn if no email is on file
        if not user_detail["email"]:
            logger.warning(f"User {user_id} has no email on file.")
            messages.warning(request, "User has no email on file.")

        with connection.cursor() as cursor:
            # Fetch auctions created by the user
            logger.debug(f"Fetching auctions created by user_id: {user_id}")
            cursor.execute("""
                SELECT id, title, category, starting_price, current_bid, status
                FROM auctions
                WHERE user_id = %s
            """, [user_id])
            created_auctions = [{"id": row[0], "title": row[1], "category": row[2], "starting_price": row[3], "current_bid": row[4], "status": row[5]} for row in cursor.fetchall()]
            logger.debug(f"Created auctions: {created_auctions}")

            # Fetch auctions won by the user
            logger.debug(f"Fetching auctions won by user_id: {user_id}")
            cursor.execute("""
                SELECT id, title, category, current_bid
                FROM auctions
                WHERE winner_user_id = %s
            """, [user_id])
            won_auctions = [{"id": row[0], "title": row[1], "category": row[2], "current_bid": row[3]} for row in cursor.fetchall()]
            logger.debug(f"Won auctions: {won_auctions}")

            # Fetch auctions where the user has placed a bid
            logger.debug(f"Fetching auctions bidded on by user_id: {user_id}")
            cursor.execute("""
                SELECT a.id, a.title, a.category, a.current_bid, a.status
                FROM auctions a
                JOIN bids b ON a.id = b.auction_id
                WHERE b.user_id = %s
                GROUP BY a.id
            """, [user_id])
            bidded_auctions = [{"id": row[0], "title": row[1], "category": row[2], "current_bid": row[3], "status": row[4]} for row in cursor.fetchall()]
            logger.debug(f"Bidded auctions: {bidded_auctions}")

            # Fetch order history (won auctions with status 'sold')
            logger.debug(f"Fetching order history for user_id: {user_id}")
            cursor.execute("""
                SELECT id, title, category, current_bid
                FROM auctions
                WHERE winner_user_id = %s AND status = 'sold'
            """, [user_id])
            order_history = [{"id": row[0], "title": row[1], "category": row[2], "current_bid": row[3]} for row in cursor.fetchall()]
            logger.debug(f"Order history: {order_history}")

            # Fetch buying orders (where the user is the buyer)
            logger.debug(f"Fetching buying orders for user_id: {user_id}")
            cursor.execute("""
                SELECT o.order_id, o.auction_id, o.invoice_id, a.title, o.order_date, o.payment_amount, 
                       o.payment_status, o.shipping_status, o.tracking_number, 
                       o.delivery_date, o.order_status, o.progress
                FROM orders o
                JOIN auctions a ON o.auction_id = a.id
                WHERE o.user_id = %s
            """, [user_id])
            buying_orders = [{"order_id": row[0], "auction_id": row[1], "invoice_id": row[2], "auction_title": row[3], "order_date": row[4], "payment_amount": row[5],
                              "payment_status": row[6], "shipping_status": row[7], "tracking_number": row[8], "delivery_date": row[9],
                              "order_status": row[10], "progress": row[11]} for row in cursor.fetchall()]
            logger.debug(f"Buying orders: {buying_orders}")

            # Fetch selling orders (where the user is the seller)
            logger.debug(f"Fetching selling orders for user_id: {user_id}")
            cursor.execute("""
                SELECT o.order_id, o.auction_id, o.invoice_id, a.title, o.order_date, o.payment_amount, 
                       o.payment_status, o.shipping_status, o.tracking_number, 
                       o.delivery_date, o.order_status, o.progress
                FROM orders o
                JOIN auctions a ON o.auction_id = a.id
                WHERE a.user_id = %s
            """, [user_id])
            selling_orders = [{"order_id": row[0], "auction_id": row[1], "invoice_id": row[2], "auction_title": row[3], "order_date": row[4], "payment_amount": row[5],
                               "payment_status": row[6], "shipping_status": row[7], "tracking_number": row[8], "delivery_date": row[9],
                               "order_status": row[10], "progress": row[11]} for row in cursor.fetchall()]
            logger.debug(f"Selling orders: {selling_orders}")

            # Fetch reports filed against the user
            logger.debug(f"Fetching reports for user_id: {user_id}")
            cursor.execute("""
                SELECT ru.id, ru.reported_by, u.username, ru.reason, ru.report_date
                FROM reported_users ru
                JOIN users u ON ru.reported_by = u.id
                WHERE ru.reported_user = %s
            """, [user_id])
            reports = [
                {
                    "id": row[0],
                    "reported_by": row[1],
                    "reporting_username": row[2],
                    "reason": row[3],
                    "report_date": row[4],
                } for row in cursor.fetchall()
            ]
            logger.debug(f"Reports: {reports}")

        context = {
            "user": user_detail,
            "created_auctions": created_auctions,
            "won_auctions": won_auctions,
            "bidded_auctions": bidded_auctions,
            "order_history": order_history,
            "buying_orders": buying_orders,
            "selling_orders": selling_orders,
            "reports": reports,
        }
        logger.info("Rendering manage_user.html with context.")
        return render(request, "manage_user.html", context)

    elif request.method == "POST":
        logger.info(f"Processing POST request for user_id: {user_id}")
        try:
            # Handle regular user update
            logger.debug("Handling regular user update.")
            username = request.POST.get("username")
            email = request.POST.get("email")
            role_new = request.POST.get("role")
            bidding_restricted = request.POST.get("bidding_restricted")
            premium_status = request.POST.get("premium")
            account_status = request.POST.get("account_status")
            logger.debug(f"POST data - username: {username}, email: {email}, role: {role_new}, "
                        f"bidding_restricted: {bidding_restricted}, premium: {premium_status}, "
                        f"account_status: {account_status}")

            # Convert checkbox values to 1/0 for database
            bidding_restricted_flag = 1 if bidding_restricted == 'on' else 0
            premium_flag = 1 if premium_status == 'on' else 0
            logger.debug(f"Converted flags - bidding_restricted_flag: {bidding_restricted_flag}, premium_flag: {premium_flag}")

            # Validate account_status
            allowed_statuses = ['pending', 'verified', 'rejected', 'banned']
            if account_status not in allowed_statuses:
                logger.error(f"Invalid account_status: {account_status}, allowed: {allowed_statuses}")
                return JsonResponse({
                    "status": "error",
                    "message": "Invalid account status value."
                }, status=400)

            # Update the database
            with connection.cursor() as cursor:
                logger.debug("Updating user details in the database.")
                cursor.execute("""
                    UPDATE users
                    SET username = %s, email = %s, role = %s, bidding_restricted = %s, 
                        premium = %s, account_status = %s
                    WHERE id = %s
                """, [username, email, role_new, bidding_restricted_flag, premium_flag, account_status, user_id])
                logger.debug(f"User {user_id} updated successfully.")

            # Return JSON success response with updated user data
            return JsonResponse({
                "status": "success",
                "message": "User details updated successfully",
                "updated_user": {
                    "username": username,
                    "email": email,
                    "role": role_new,
                    "bidding_restricted": bool(bidding_restricted_flag),
                    "premium": bool(premium_flag),
                    "account_status": account_status,
                }
            })
        except Exception as e:
            logger.error(f"Error processing POST request for user_id {user_id}: {str(e)}", exc_info=True)
            return JsonResponse({
                "status": "error",
                "message": f"Failed to process request: {str(e)}"
            }, status=500)

    else:
        logger.warning(f"Invalid request method: {request.method}")
        return JsonResponse({
            "status": "error",
            "message": "Invalid request method."
        }, status=405)


@require_POST
def admin_delete_user(request, user_id):
    """
    Deletes a user and all related records across multiple tables.
    Only accessible to admin users. Redirects to list_users upon completion.
    """
    logger.debug(f"Initiating deletion for user id: {user_id}")

    # Check if the admin is logged in
    admin_id = request.session.get('user_id')
    if not admin_id:
        logger.warning("No admin_id found in session.")
        messages.error(request, "Unauthorized access. Please log in.")
        return render(request, 'auth_page.html', {'message': 'Unauthorized access. Please log in.'}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    logger.debug(f"Admin role fetched: {admin_role}")
    if not admin_role or admin_role[0] != 'admin':
        logger.warning(f"User with ID {admin_id} is not an admin.")
        messages.error(request, "You are not authorized to delete users.")
        return HttpResponseForbidden("You are not authorized to perform this action.")

    # Check if the target user exists
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE id = %s", [user_id])
        user = cursor.fetchone()
    logger.debug(f"Fetched user details: {user}")
    if not user:
        logger.error(f"User with ID {user_id} not found.")
        messages.error(request, "User not found.")
        return redirect('list_users')

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Delete from watchlist
                cursor.execute("DELETE FROM watchlist WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted watchlist for user id: {user_id}")

                # Delete from wallets
                cursor.execute("DELETE FROM wallets WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted wallets for user id: {user_id}")

                # Delete from user_otp
                cursor.execute("DELETE FROM user_otp WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted user_otp for user id: {user_id}")

                # Delete from user_activity
                cursor.execute("DELETE FROM user_activity WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted user_activity for user id: {user_id}")

                # Delete from shipping_details
                cursor.execute("DELETE FROM shipping_details WHERE buyer_id = %s", [user_id])
                logger.debug(f"Deleted shipping_details for user id: {user_id}")

                # Delete from reviews
                cursor.execute("DELETE FROM reviews WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted reviews for user id: {user_id}")

                # Delete from reported_users
                cursor.execute("""
                    DELETE FROM reported_users 
                    WHERE reported_by = %s OR reported_user = %s
                """, [user_id, user_id])
                logger.debug(f"Deleted reported_users for user id: {user_id}")

                # Delete from premium_users
                cursor.execute("DELETE FROM premium_users WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted premium_users for user id: {user_id}")

                # Delete from payment_details
                cursor.execute("DELETE FROM payment_details WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted payment_details for user id: {user_id}")

                # Delete from orders
                cursor.execute("DELETE FROM orders WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted orders for user id: {user_id}")

                # Delete from offers
                cursor.execute("DELETE FROM offers WHERE buyer_id = %s", [user_id])
                logger.debug(f"Deleted offers for user id: {user_id}")

                # Delete from notifications
                cursor.execute("DELETE FROM notifications WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted notifications for user id: {user_id}")

                # Delete from messages
                cursor.execute("""
                    DELETE FROM messages 
                    WHERE sender_id = %s OR receiver_id = %s
                """, [user_id, user_id])
                logger.debug(f"Deleted messages for user id: {user_id}")

                # Delete from bids
                cursor.execute("DELETE FROM bids WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted bids for user id: {user_id}")

                # Delete from auction_images for auctions created by the user
                cursor.execute("SELECT id FROM auctions WHERE user_id = %s", [user_id])
                auction_ids = [row[0] for row in cursor.fetchall()]
                if auction_ids:
                    cursor.execute(
                        "DELETE FROM auction_images WHERE auction_id IN %s",
                        [tuple(auction_ids)]
                    )
                    logger.debug(f"Deleted auction_images for user id: {user_id}")

                # Delete from fund_distribution
                cursor.execute("""
                    DELETE FROM fund_distribution 
                    WHERE seller_id = %s
                """, [user_id])
                logger.debug(f"Deleted fund_distribution for user id: {user_id}")

                # Delete from seller_payouts (must come before invoices due to foreign key)
                cursor.execute("DELETE FROM seller_payouts WHERE seller_id = %s", [user_id])
                logger.debug(f"Deleted seller_payouts for user id: {user_id}")

                # Delete from invoices
                cursor.execute("""
                    DELETE FROM invoices 
                    WHERE seller_id = %s OR buyer_id = %s
                """, [user_id, user_id])
                logger.debug(f"Deleted invoices for user id: {user_id}")

                # Delete auctions created by the user
                cursor.execute("DELETE FROM auctions WHERE user_id = %s", [user_id])
                logger.debug(f"Deleted auctions for user id: {user_id}")

                # Finally, delete the user from users table
                cursor.execute("DELETE FROM users WHERE id = %s", [user_id])
                logger.debug(f"Deleted user record for user id: {user_id}")

        messages.success(request, "User and all related records deleted successfully.")
        logger.info(f"Successfully deleted user id: {user_id} and all related records.")
        return redirect('list_users')

    except Exception as e:
        logger.error(f"Exception encountered during deletion of user id {user_id}: {str(e)}", exc_info=True)
        messages.error(request, f"Error deleting user: {str(e)}")
        return redirect('list_users')


def admin_auct_deta(request, auction_id):
    # If the user is authenticated, store their sender ID (admin ID) in the session
    if request.user.is_authenticated:
        request.session['sender_id'] = request.user.id

    # Fetch auction details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                a.id, 
                a.title, 
                a.description, 
                a.category, 
                a.starting_price, 
                a.current_bid, 
                a.bid_increment, 
                a.reserve_price,
                a.start_date, 
                a.end_date, 
                a.user_id, 
                a.auction_type, 
                a.winner_user_id,
                (SELECT image_path FROM auction_images WHERE auction_id = a.id LIMIT 1) AS image_url,
                a.buy_it_now_price, 
                a.is_make_offer_enabled,
                a.status,
                a.condition,
                a.condition_description
            FROM auctions a
            WHERE a.id = %s
        """, [auction_id])
        auction = cursor.fetchone()

    if not auction:
        raise Http404("Auction not found.")

    # Map auction data
    auction_data = {
        'id': auction[0],
        'title': auction[1],
        'description': auction[2],
        'category': auction[3],
        'starting_price': auction[4],
        'current_bid': auction[5],
        'bid_increment': auction[6],
        'reserve_price': auction[7],
        'start_date': auction[8],
        'end_date': auction[9],
        'user_id': auction[10],
        'auction_type': auction[11],
        'winner_user_id': auction[12],
        'image_url': f"/media/auction_images/{auction[13]}" if auction[13] else "/static/images/placeholder.png",
        'buy_it_now_price': auction[14],
        'is_make_offer_enabled': auction[15],
        'status': auction[16],
        'condition': auction[17],
        'condition_description': auction[18],
    }

    # Fetch seller details
    with connection.cursor() as cursor:
        cursor.execute("SELECT username, email, profile_picture FROM users WHERE id = %s", [auction_data['user_id']])
        user = cursor.fetchone()

    profile_picture_path = user[2] if user and user[2] else ""
    final_profile_picture = (
        profile_picture_path if profile_picture_path.startswith(("/", "http"))
        else f"/media/{profile_picture_path}" if profile_picture_path
        else "/static/images/default_profile.png"
    )
    auction_data['user'] = {
        'username': user[0] if user else "Unknown User",
        'email': user[1] if user else "No Email",
        'profile_picture': final_profile_picture,
    }

    # Initialize winner details
    winner = None
    winner_available = False
    is_second_highest_bidder = False

    if datetime.now() > auction_data['end_date'] and auction_data.get('winner_user_id'):
        winner_available = True
        current_winner_id = auction_data['winner_user_id']

        # Fetch the top two bidders for this auction
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT user_id, amount 
                FROM bids 
                WHERE auction_id = %s 
                ORDER BY amount DESC, created_at ASC 
                LIMIT 2
            """, [auction_data['id']])
            top_bidders = cursor.fetchall()

        # Determine the highest and second-highest bidder
        highest_bidder_id = None
        second_highest_bidder_id = None
        if top_bidders:
            highest_bidder_id = top_bidders[0][0]  # Highest bidder
            if len(top_bidders) > 1:
                second_highest_bidder_id = top_bidders[1][0]  # Second-highest bidder

        # Check if an offer was sent to the second winner
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT buyer_id 
                FROM offers 
                WHERE auction_id = %s AND second_winner_offer = 1
            """, [auction_data['id']])
            second_winner_offer = cursor.fetchone()

        # If an offer exists with second_winner_offer = 1 and the buyer_id matches the current winner, they are the second-highest bidder
        if second_winner_offer and str(second_winner_offer[0]) == str(current_winner_id):
            is_second_highest_bidder = True

        # Fetch winner details
        with connection.cursor() as cursor:
            cursor.execute("SELECT username, email, profile_picture FROM users WHERE id = %s", [current_winner_id])
            winner_data = cursor.fetchone()

        if winner_data:
            winner_profile = winner_data[2] if winner_data[2] else ""
            final_winner_profile = (
                winner_profile if winner_profile.startswith(("/", "http"))
                else f"/media/{winner_profile}" if winner_profile
                else "/static/images/default_profile.png"
            )
            winner = {
                'user_id': current_winner_id,
                'username': winner_data[0],
                'email': winner_data[1],
                'profile_picture': final_winner_profile,
                'final_price': auction_data['current_bid']
            }

    auction_data['winner'] = winner
    auction_data['winner_available'] = winner_available

    # Fetch last bid and update current_bid
    with connection.cursor() as cursor:
        cursor.execute("SELECT amount FROM bids WHERE auction_id = %s ORDER BY created_at DESC LIMIT 1", [auction_data['id']])
        last_bid = cursor.fetchone()
    auction_data['current_bid'] = last_bid[0] if last_bid else auction_data['starting_price']

    # Fetch all images
    with connection.cursor() as cursor:
        cursor.execute("SELECT image_path FROM auction_images WHERE auction_id = %s", [auction_data['id']])
        images = cursor.fetchall()
    auction_data['images'] = [f"/media/auction_images/{img[0]}" for img in images if img and img[0]]

    # Determine the origin of the request
    managed_user_id = request.GET.get('managed_user_id', auction_data['user_id'])
    came_from_manage_user = str(managed_user_id) != str(auction_data['user_id'])

    return render(request, 'admin_auct_deta.html', {
        'auction': auction_data,
        'now': datetime.now(),
        'sender_id': request.session.get('sender_id'),
        'managed_user_id': managed_user_id,
        'came_from_manage_user': came_from_manage_user,
        'is_second_highest_bidder': is_second_highest_bidder,  # Pass the flag to the template
    })


def stop_auction(request, auction_id):
    """
    View to stop an auction by changing its status to 'stopped'.
    Only accessible to admins, and only if the auction is active and not sold or stopped.
    Returns JSON response for AJAX requests or redirects for standard requests.
    """
    print(f"DEBUG: Starting stop_auction for auction_id: {auction_id}")

    # Check if the user is logged in and is an admin
    admin_id = request.session.get('user_id')
    if not admin_id:
        print("DEBUG: No admin_id found in session.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  # Check for AJAX
            return JsonResponse({"status": "error", "message": "Please log in as an admin to stop auctions."}, status=403)
        messages.error(request, "Please log in as an admin to stop auctions.")
        return redirect('login')  # Adjust to your login URL

    print(f"DEBUG: Found admin_id: {admin_id}")

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    print(f"DEBUG: Fetched admin role: {admin_role}")

    if not admin_role or admin_role[0] != 'admin':
        print("DEBUG: User is not an admin.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  # Check for AJAX
            return JsonResponse({"status": "error", "message": "You are not authorized to stop auctions."}, status=403)
        messages.error(request, "You are not authorized to stop auctions.")
        return HttpResponseForbidden("You are not authorized to perform this action.")

    # Ensure the request is POST
    if request.method != "POST":
        print(f"DEBUG: Invalid request method: {request.method}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':  # Check for AJAX
            return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)
        messages.error(request, "Invalid request method.")
        return redirect('admin_auct_deta', auction_id=auction_id)

    # Fetch auction details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT status, end_date
            FROM auctions
            WHERE id = %s
        """, [auction_id])
        auction = cursor.fetchone()
    print(f"DEBUG: Fetched auction details: {auction}")

    if not auction:
        print("DEBUG: Auction not found.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "Auction not found."}, status=404)
        messages.error(request, "Auction not found.")
        return redirect('list_auctions')  # Adjust to your auction list URL

    auction_status, end_date = auction
    current_time = timezone.now()
    print(f"DEBUG: Current time: {current_time}")

    # Make end_date timezone-aware (assuming database returns naive datetimes)
    if end_date is not None and timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date, timezone.get_current_timezone())
    print(f"DEBUG: Auction status: {auction_status}, Auction end_date: {end_date}")

    # Validate auction state
    if auction_status == 'sold':
        print("DEBUG: Auction is sold and cannot be stopped.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "Cannot stop a sold auction."}, status=400)
        messages.error(request, "Cannot stop a sold auction.")
        return redirect('admin_auct_deta', auction_id=auction_id)
    elif auction_status == 'stopped':
        print("DEBUG: Auction is already stopped.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "This auction has already been stopped."}, status=400)
        messages.error(request, "This auction has already been stopped.")
        return redirect('admin_auct_deta', auction_id=auction_id)
    elif auction_status == 'closed' or (end_date and end_date < current_time):
        print("DEBUG: Auction is closed or has already ended (end_date < current_time).")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "This auction has already ended."}, status=400)
        messages.error(request, "This auction has already ended.")
        return redirect('admin_auct_deta', auction_id=auction_id)

    # Optional: Drop into interactive debugging session if needed
    # import pdb; pdb.set_trace()

    # Stop the auction by setting status to 'stopped' without updating the end_date
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE auctions
                SET status = 'stopped', updated_at = %s
                WHERE id = %s
            """, [current_time, auction_id])
        print(f"DEBUG: Auction {auction_id} updated to 'stopped'. (end_date not updated)")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Auction stopped successfully."})
        messages.success(request, "Auction stopped successfully.")
        return redirect('admin_auct_deta', auction_id=auction_id)
    except Exception as e:
        print(f"DEBUG: Exception encountered while stopping auction: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": f"Error stopping auction: {str(e)}"}, status=500)
        messages.error(request, f"Error stopping auction: {str(e)}")
        return redirect('admin_auct_deta', auction_id=auction_id)

@require_POST
def resume_auction(request, auction_id):
    """
    View to resume a stopped auction by setting its status to 'active' without updating the end_date.
    Only accessible to admins, and only if the auction is stopped.
    Returns JSON response for AJAX requests or redirects for standard requests.
    """
    print(f"DEBUG: Starting resume_auction for auction_id: {auction_id}")

    # Check if the user is logged in and is an admin
    admin_id = request.session.get('user_id')
    if not admin_id:
        print("DEBUG: No admin_id found in session.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "Please log in as an admin to resume auctions."}, status=403)
        messages.error(request, "Please log in as an admin to resume auctions.")
        return redirect('login')  # Adjust to your login URL

    print(f"DEBUG: Found admin_id: {admin_id}")

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    print(f"DEBUG: Fetched admin role: {admin_role}")

    if not admin_role or admin_role[0] != 'admin':
        print("DEBUG: User is not an admin.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "You are not authorized to resume auctions."}, status=403)
        messages.error(request, "You are not authorized to resume auctions.")
        return HttpResponseForbidden("You are not authorized to perform this action.")

    # Fetch auction details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT status, end_date, updated_at
            FROM auctions
            WHERE id = %s
        """, [auction_id])
        auction = cursor.fetchone()
    print(f"DEBUG: Fetched auction details: {auction}")

    if not auction:
        print("DEBUG: Auction not found.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "Auction not found."}, status=404)
        messages.error(request, "Auction not found.")
        return redirect('list_auctions')  # Adjust to your auction list URL

    auction_status, end_date, updated_at = auction
    current_time = timezone.now()
    print(f"DEBUG: Current time: {current_time}")

    # Make end_date and updated_at timezone-aware if necessary
    if end_date and timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date, timezone.get_current_timezone())
    if updated_at and timezone.is_naive(updated_at):
        updated_at = timezone.make_aware(updated_at, timezone.get_current_timezone())
    print(f"DEBUG: Auction status: {auction_status}, end_date: {end_date}, updated_at: {updated_at}")

    # Validate auction state
    if auction_status != 'stopped':
        print("DEBUG: Auction is not stopped.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "This auction is not stopped."}, status=400)
        messages.error(request, "This auction is not stopped.")
        return redirect('admin_auct_deta', auction_id=auction_id)

    # Resume the auction by setting status to 'active' without updating end_date
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE auctions
                SET status = 'active', updated_at = %s
                WHERE id = %s
            """, [current_time, auction_id])
        print(f"DEBUG: Auction {auction_id} updated to 'active' with original end_date: {end_date}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Auction resumed successfully."})
        messages.success(request, "Auction resumed successfully.")
        return redirect('admin_auct_deta', auction_id=auction_id)
    except Exception as e:
        print(f"DEBUG: Exception encountered: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": f"Error resuming auction: {str(e)}"}, status=500)
        messages.error(request, f"Error resuming auction: {str(e)}")
        return redirect('admin_auct_deta', auction_id=auction_id)


def admin_view_bids(request, auction_id):
    # Get user_id from session
    user_id = request.session.get('user_id')
    print("DEBUG: session user_id =", user_id)

    # Check if user is logged in
    if not user_id:
        print("DEBUG: No user_id in session, user not logged in")
        if request.GET.get('json') == 'true':
            return JsonResponse({'error': 'Authentication required'}, status=403)
        return HttpResponseForbidden("You must be logged in to access this page.")

    # Check if the current user is an admin
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT role 
            FROM users 
            WHERE id = %s
        """, [user_id])
        user_role = cursor.fetchone()
        print("DEBUG: user_role =", user_role)

    if not user_role or user_role[0] != 'admin':
        print("DEBUG: User is not an admin or not found")
        if request.GET.get('json') == 'true':
            return JsonResponse({'error': 'Admin access required'}, status=403)
        return HttpResponseForbidden("You do not have permission to view this page. Admin access required.")

    # Fetch auction details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, title 
            FROM auctions 
            WHERE id = %s
        """, [auction_id])
        auction = cursor.fetchone()

    if not auction:
        if request.GET.get('json') == 'true':
            return JsonResponse({'error': 'Auction not found'}, status=404)
        raise Http404("Auction not found")

    auction_data = {
        'id': auction[0],
        'title': auction[1],
    }

    # Fetch the highest bid (max of amount for manual bids or current_bid for proxy bids)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT GREATEST(
                COALESCE((SELECT MAX(amount) FROM bids WHERE auction_id = %s AND is_proxy = 0), 0),
                COALESCE((SELECT MAX(current_bid) FROM bids WHERE auction_id = %s AND is_proxy = 1), 0)
            ) AS highest_bid
        """, [auction_id, auction_id])
        highest_bid_result = cursor.fetchone()
        highest_bid = float(highest_bid_result[0]) if highest_bid_result[0] is not None else 0.00
        print("DEBUG: highest_bid =", highest_bid)

    # Check if this is an AJAX request for JSON data
    if request.GET.get('json') == 'true':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    b.id,
                    b.user_id,
                    u.username,
                    b.amount,
                    b.bid_time,
                    b.is_proxy,
                    b.proxy_max_amount,
                    b.current_bid
                FROM bids b
                JOIN users u ON b.user_id = u.id
                WHERE b.auction_id = %s
                ORDER BY b.bid_time DESC
            """, [auction_id])
            bids = cursor.fetchall()

        regular_bids = []
        proxy_bids = []
        for bid in bids:
            bid_dict = {
                'id': bid[0],
                'user_id': bid[1],
                'bidder_username': bid[2],
                'amount': float(bid[3]),
                'timestamp': bid[4].isoformat() if bid[4] else None,
                'is_proxy': bool(bid[5]),
                'proxy_max_amount': float(bid[6]) if bid[6] is not None else None,
                'current_bid': float(bid[7]) if bid[7] is not None else float(bid[3]),
            }
            if bid_dict['is_proxy']:
                proxy_bids.append(bid_dict)
            else:
                regular_bids.append(bid_dict)

        response_data = {
            'total_bids': len(bids),
            'regular_bids': regular_bids,
            'proxy_bids': proxy_bids,
            'current_price': highest_bid,  # Highest bid as current price
        }
        return JsonResponse(response_data)

    # Pass highest_bid to the template for initial render
    auction_data['current_price'] = highest_bid
    return render(request, 'admin_view_bids.html', {'auction': auction_data})

@require_POST
def admin_delete_auction(request, auction_id):
    """
    Deletes an auction along with its related records in bids, images, sealed bid details,
    orders, invoices, offers, fund_distribution, seller_payouts, and watchlist tables.
    Only accessible to admin users.
    Returns a JSON response for AJAX requests or redirects to manage_user for the auction's creator.
    """
    print(f"DEBUG: Initiating deletion for auction id: {auction_id}")

    # Check if the user is logged in and is an admin
    admin_id = request.session.get('user_id')
    if not admin_id:
        print("DEBUG: No admin_id found in session.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Unauthorized access. Please log in.'}, status=401)
        messages.error(request, "Unauthorized access. Please log in.")
        return render(request, 'auth_page.html', {'message': 'Unauthorized access. Please log in.'}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    print(f"DEBUG: Admin role fetched: {admin_role}")
    if not admin_role or admin_role[0] != 'admin':
        print("DEBUG: User is not an admin.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'You are not authorized to perform this action.'}, status=403)
        messages.error(request, "You are not authorized to delete auctions.")
        return HttpResponseForbidden("You are not authorized to perform this action.")

    # Fetch auction details including the creator's user_id
    with connection.cursor() as cursor:
        cursor.execute("SELECT auction_type, user_id FROM auctions WHERE id = %s", [auction_id])
        auction = cursor.fetchone()
    print(f"DEBUG: Fetched auction details: {auction}")
    if not auction:
        print("DEBUG: Auction not found.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Auction not found.'}, status=404)
        messages.error(request, "Auction not found.")
        return redirect('manage_user', user_id=admin_id)

    auction_type, creator_user_id = auction[0], auction[1]
    print(f"DEBUG: Auction type: {auction_type}, Creator user_id: {creator_user_id}")

    # Check if creator_user_id is valid
    if creator_user_id is None:
        print("DEBUG: creator_user_id is None, redirecting to admin's manage_user page.")
        creator_user_id = admin_id  # Fallback to admin_id

    # Delete all related records in a transaction
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Delete from fund_distribution
                cursor.execute("DELETE FROM fund_distribution WHERE auction_id = %s", [auction_id])
                print(f"DEBUG: Deleted fund_distribution records for auction id: {auction_id}")

                # Delete from orders
                cursor.execute("DELETE FROM orders WHERE auction_id = %s", [auction_id])
                print(f"DEBUG: Deleted orders for auction id: {auction_id}")

                # Delete from seller_payouts (related to invoices)
                cursor.execute("""
                    DELETE FROM seller_payouts 
                    WHERE invoice_id IN (SELECT id FROM invoices WHERE auction_id = %s)
                """, [auction_id])
                print(f"DEBUG: Deleted seller_payouts for auction id: {auction_id}")

                # Delete from invoices
                cursor.execute("DELETE FROM invoices WHERE auction_id = %s", [auction_id])
                print(f"DEBUG: Deleted invoices for auction id: {auction_id}")

                # Delete from offers
                cursor.execute("DELETE FROM offers WHERE auction_id = %s", [auction_id])
                print(f"DEBUG: Deleted offers for auction id: {auction_id}")

                # Delete all bids for this auction
                cursor.execute("DELETE FROM bids WHERE auction_id = %s", [auction_id])
                print(f"DEBUG: Deleted bids for auction id: {auction_id}")

                # Delete all images for this auction
                cursor.execute("DELETE FROM auction_images WHERE auction_id = %s", [auction_id])
                print(f"DEBUG: Deleted images for auction id: {auction_id}")

                # If this is a sealed bid auction, delete its sealed bid details
                if auction_type == 'sealed_bid':
                    cursor.execute("DELETE FROM sealed_bid_details WHERE auction_id = %s", [auction_id])
                    print(f"DEBUG: Deleted sealed bid details for auction id: {auction_id}")

                # Delete from watchlist
                cursor.execute("DELETE FROM watchlist WHERE auction_id = %s", [auction_id])
                print(f"DEBUG: Deleted watchlist records for auction id: {auction_id}")

                # Finally, delete the auction itself
                cursor.execute("DELETE FROM auctions WHERE id = %s", [auction_id])
                print(f"DEBUG: Deleted auction record for auction id: {auction_id}")

    except Exception as e:
        error_message = f"Exception during transaction: {str(e)}\n{traceback.format_exc()}"
        print(f"DEBUG: {error_message}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        messages.error(request, f"Error deleting auction: {str(e)}")
        return redirect('manage_user', user_id=creator_user_id)

    # If we reach here, the transaction was successful
    print("DEBUG: Transaction committed successfully.")

    # Handle the response based on whether it's an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Auction and all related records deleted successfully.'})
    else:
        try:
            messages.success(request, "Auction and all related records deleted successfully.")
            print("DEBUG: Success message set.")
            return redirect('manage_user', user_id=creator_user_id)
        except Exception as e:
            error_message = f"Exception after transaction (during message/redirect): {str(e)}\n{traceback.format_exc()}"
            print(f"DEBUG: {error_message}")
            messages.error(request, f"Error after deletion: {str(e)}. The auction may have been deleted, but an issue occurred.")
            return redirect('manage_user', user_id=creator_user_id)
@require_GET
def auction_orders(request, auction_id):
    # Check if the user is logged in
    logged_in_user_id = request.session.get('user_id')
    if not logged_in_user_id:
        messages.error(request, "Please log in to view this page.")
        return render(request, 'auth_page.html', {'message': 'Please log in.'}, status=401)

    # Check authorization
    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [logged_in_user_id])
        user_role = cursor.fetchone()

    if not user_role:
        messages.error(request, "User not found.")
        return HttpResponseForbidden("You are not authorized to view this page.")

    # Fetch auction details
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id, title, auction_type FROM auctions WHERE id = %s", [auction_id])
        auction_data = cursor.fetchone()

    if not auction_data:
        messages.error(request, "Auction not found.")
        return redirect('list_users')

    auction_creator_id, auction_title, auction_type = auction_data

    # Authorization
    is_admin = user_role[0] == 'admin'
    is_creator = logged_in_user_id == auction_creator_id
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM orders WHERE auction_id = %s AND user_id = %s",
                       [auction_id, logged_in_user_id])
        is_buyer = cursor.fetchone()[0] > 0

    if not (is_admin or is_creator or is_buyer):
        messages.error(request, "You are not authorized to view this auction's orders.")
        return HttpResponseForbidden("You are not authorized to view this page.")

    managed_user_id = request.GET.get('managed_user_id', auction_creator_id if is_admin else logged_in_user_id)

    # AJAX request handling
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        progress_data = {}

        if is_buyer or is_admin:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT order_id, progress, order_status, shipping_status, delivery_date
                    FROM orders
                    WHERE auction_id = %s AND user_id = %s
                """, [auction_id, logged_in_user_id])
                buying_progress = [
                    {
                        'order_id': row[0],
                        'progress': row[1] if row[1] is not None else 0,
                        'order_status': row[2] if row[2] else 'Processing',
                        'shipping_status': row[3] if row[3] else 'Not Shipped',
                        'delivery_date': row[4].strftime('%Y-%m-%d') if row[4] else 'N/A'
                    } for row in cursor.fetchall()
                ]
                progress_data['buying_orders'] = {item['order_id']: item for item in buying_progress}

        if is_creator or is_admin:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT order_id, progress, order_status, shipping_status, delivery_date
                    FROM orders
                    WHERE auction_id = %s
                """, [auction_id])
                selling_progress = [
                    {
                        'order_id': row[0],
                        'progress': row[1] if row[1] is not None else 0,
                        'order_status': row[2] if row[2] else 'Processing',
                        'shipping_status': row[3] if row[3] else 'Not Shipped',
                        'delivery_date': row[4].strftime('%Y-%m-%d') if row[4] else 'N/A'
                    } for row in cursor.fetchall()
                ]
                progress_data['selling_orders'] = {item['order_id']: item for item in selling_progress}

        return JsonResponse(progress_data)

    # Helper functions
    def fetch_auction_images(auction_id):
        with connection.cursor() as cursor:
            cursor.execute("SELECT image_path FROM auction_images WHERE auction_id = %s", [auction_id])
            images = cursor.fetchall()
        return [f"/media/auction_images/{img[0]}" for img in images if img and img[0]]

    def fetch_shipping_details(order_id):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT address, city, state, zip_code, country, shipping_date
                FROM shipping_details
                WHERE order_id = %s
                LIMIT 1
            """, [order_id])
            result = cursor.fetchone()
        if result:
            address, city, state, zip_code, country, shipping_date = result
            shipping_address = f"{address}, {city}, {state}, {zip_code}, {country}"
            return {
                "shipping_address": shipping_address,
                "delivery_date": shipping_date,
            }
        return None

    # Fetch buying orders
    buying_orders = []
    if is_buyer or is_admin:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT o.order_id, o.auction_id, a.title, o.payment_status, o.payment_amount, o.order_status,
                       o.order_date, o.shipping_status, o.shipping_address, o.tracking_number, o.delivery_date,
                       o.progress
                FROM orders o
                JOIN auctions a ON o.auction_id = a.id
                WHERE o.auction_id = %s AND o.user_id = %s
                ORDER BY o.order_date DESC
            """, [auction_id, logged_in_user_id])
            buying_orders_raw = cursor.fetchall()

        images = fetch_auction_images(auction_id)
        buying_orders = [
            {
                'order_id': row[0],
                'auction_id': row[1],
                'auction_title': row[2],
                'payment_status': row[3] if row[3] else 'Pending',
                'payment_amount': float(row[4]) if row[4] is not None else 0.0,
                'order_status': row[5] if row[5] else 'Processing',
                'order_date': row[6].strftime('%Y-%m-%d %H:%M:%S') if row[6] else 'N/A',
                'shipping_status': row[7] if row[7] else 'Not Shipped',
                'shipping_address': row[8] if row[8] else 'N/A',
                'tracking_number': row[9] if row[9] else 'N/A',
                'delivery_date': row[10].strftime('%Y-%m-%d') if row[10] else 'N/A',
                'progress': row[11] if row[11] is not None else 0,
                'images': images,
                'auction_type': auction_type,
            } for row in buying_orders_raw
        ]

        for order in buying_orders:
            if order['auction_type'] == 'buy_it_now':
                shipping = fetch_shipping_details(order['order_id'])
                if shipping:
                    order['shipping_address'] = shipping.get('shipping_address', order['shipping_address'])
                    if shipping.get('delivery_date'):
                        order['delivery_date'] = shipping['delivery_date'].strftime('%Y-%m-%d')

    # Fetch selling orders
    selling_orders = []
    if is_creator or is_admin:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT o.order_id, o.auction_id, a.title, o.payment_status, o.payment_amount, o.order_status,
                       o.order_date, o.shipping_status, o.shipping_address, o.tracking_number, o.delivery_date,
                       o.progress, o.user_id AS buyer_id, u.username AS buyer_name, u.email AS buyer_email
                FROM orders o
                JOIN auctions a ON o.auction_id = a.id
                JOIN users u ON o.user_id = u.id
                WHERE o.auction_id = %s
                ORDER BY o.order_date DESC
            """, [auction_id])
            selling_orders_raw = cursor.fetchall()

        images = fetch_auction_images(auction_id)
        selling_orders = [
            {
                'order_id': row[0],
                'auction_id': row[1],
                'auction_title': row[2],
                'payment_status': row[3] if row[3] else 'Pending',
                'payment_amount': float(row[4]) if row[4] is not None else 0.0,
                'order_status': row[5] if row[5] else 'Processing',
                'order_date': row[6].strftime('%Y-%m-%d %H:%M:%S') if row[6] else 'N/A',
                'shipping_status': row[7] if row[7] else 'Not Shipped',
                'shipping_address': row[8] if row[8] else 'N/A',
                'tracking_number': row[9] if row[9] else 'N/A',
                'delivery_date': row[10].strftime('%Y-%m-%d') if row[10] else 'N/A',
                'progress': row[11] if row[11] is not None else 0,
                'buyer_id': row[12],
                'buyer_name': row[13],
                'buyer_email': row[14],
                'images': images,
                'auction_type': auction_type,
            } for row in selling_orders_raw
        ]

        for order in selling_orders:
            if order['auction_type'] == 'buy_it_now':
                shipping = fetch_shipping_details(order['order_id'])
                if shipping:
                    order['shipping_address'] = shipping.get('shipping_address', order['shipping_address'])
                    if shipping.get('delivery_date'):
                        order['delivery_date'] = shipping['delivery_date'].strftime('%Y-%m-%d')

    context = {
        'logged_in_user': {'id': logged_in_user_id},
        'managed_user_id': managed_user_id,
        'auction_id': auction_id,
        'auction_title': auction_title,
        'buying_orders': buying_orders,
        'selling_orders': selling_orders,
        'created_auctions': [],
        'won_auctions': [],
        'bidded_auctions': [],
        'messages': messages.get_messages(request),
    }

    return render(request, 'auction_orders.html', context)

def payment_details(request):
    """
    View to display all payment details from the payment_details and seller_payouts tables,
    and all fund distributions from the fund_distribution table.
    Only accessible by an admin.
    GET: Fetch and display premium payments, auction payments, seller payouts, and all fund distributions with masked sensitive data.
    """
    logger.debug(f"Starting payment_details view, request method: {request.method}")

    # Check if the logged-in user is an admin
    admin_id = request.session.get('user_id')
    logger.debug(f"Admin ID from session: {admin_id}")
    if not admin_id:
        logger.warning("No admin_id found in session, redirecting to login.")
        messages.error(request, "Please log in.")
        return redirect('core:login')

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    logger.debug(f"Admin role fetched: {admin_role}")
    if not admin_role or admin_role[0] != 'admin':
        logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
        messages.error(request, "You are not authorized to access this page.")
        return redirect('core:login')

    if request.method == "GET":
        logger.info("Processing GET request for payment_details")

        # Fetch payment details
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, user_id, invoice_id, auction_id, payment_method, payment_status, 
                       transaction_id, payment_amount, debit_card_number, debit_card_expiry, 
                       debit_card_cvc, credit_card_number, credit_card_expiry, credit_card_cvc, 
                       paypal_email, bank_account_number, bank_routing_number, payment_date, 
                       payment_timestamp, payment_notes, premium_type
                FROM payment_details
                ORDER BY payment_timestamp DESC
            """)
            payments = cursor.fetchall()

        # Categorize payments
        premium_payments = []
        auction_payments = []
        for payment in payments:
            # Mask sensitive card details
            debit_card_number = payment[8] if payment[8] else None
            if debit_card_number:
                debit_card_number = f"****-****-****-{debit_card_number[-4:]}"

            credit_card_number = payment[11] if payment[11] else None
            if credit_card_number:
                credit_card_number = f"****-****-****-{credit_card_number[-4:]}"

            debit_card_cvc = payment[10] if payment[10] else None
            if debit_card_cvc:
                debit_card_cvc = "***"

            credit_card_cvc = payment[13] if payment[13] else None
            if credit_card_cvc:
                credit_card_cvc = "***"

            bank_account_number = payment[15] if payment[15] else None
            if bank_account_number:
                bank_account_number = f"****-****-{bank_account_number[-4:]}"

            bank_routing_number = payment[16] if payment[16] else None
            if bank_routing_number:
                bank_routing_number = f"****-{bank_routing_number[-4:]}"

            payment_dict = {
                "id": payment[0],
                "user_id": payment[1],
                "invoice_id": payment[2],
                "auction_id": payment[3],
                "payment_method": payment[4],
                "payment_status": payment[5],
                "transaction_id": payment[6],
                "payment_amount": payment[7],
                "debit_card_number": debit_card_number,
                "debit_card_expiry": payment[9],
                "debit_card_cvc": debit_card_cvc,
                "credit_card_number": credit_card_number,
                "credit_card_expiry": payment[12],
                "credit_card_cvc": credit_card_cvc,
                "paypal_email": payment[14],
                "bank_account_number": bank_account_number,
                "bank_routing_number": bank_routing_number,
                "payment_date": payment[17],
                "payment_timestamp": payment[18],
                "payment_notes": payment[19],
                "premium_type": payment[20],
            }
            if payment[20]:  # If premium_type is not null, it's a premium payment
                premium_payments.append(payment_dict)
            elif payment[3]:  # If auction_id is not null, it's an auction payment
                auction_payments.append(payment_dict)

        # Fetch seller payouts
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT payout_id, seller_id, auction_id, invoice_id, payout_amount, payout_method,
                       transaction_id, payout_status, payout_date
                FROM seller_payouts
                ORDER BY payout_date DESC
            """)
            payouts = cursor.fetchall()

        seller_payouts = []
        for payout in payouts:
            payout_dict = {
                "id": payout[0],
                "seller_id": payout[1],
                "auction_id": payout[2],
                "invoice_id": payout[3],
                "payout_amount": payout[4],
                "payout_method": payout[5],
                "transaction_id": payout[6],
                "payout_status": payout[7],
                "payout_date": payout[8],
            }
            seller_payouts.append(payout_dict)

        # Fetch all fund distributions
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, invoice_id, auction_id, seller_id, platform_share, seller_share, status, distribution_date
                FROM fund_distribution
                ORDER BY distribution_date DESC
            """)
            distributions = cursor.fetchall()

        fund_distributions = []
        for distribution in distributions:
            distribution_dict = {
                "id": distribution[0],
                "invoice_id": distribution[1],
                "auction_id": distribution[2],
                "seller_id": distribution[3],
                "platform_share": distribution[4],
                "seller_share": distribution[5],
                "status": distribution[6],
                "distribution_date": distribution[7],
            }
            fund_distributions.append(distribution_dict)

        logger.debug(f"Fetched {len(premium_payments)} premium payments, {len(auction_payments)} auction payments, {len(seller_payouts)} seller payouts, {len(fund_distributions)} fund distributions")
        return render(request, "payment_details.html", {
            "premium_payments": premium_payments,
            "auction_payments": auction_payments,
            "seller_payouts": seller_payouts,
            "fund_distributions": fund_distributions
        })

    else:
        logger.warning(f"Invalid request method: {request.method}")
        return redirect('payment_details')

def process_manual_fund_distribution(request, fund_id):
        """
        Manually process a specific fund distribution by transferring the seller's share and logging the payout.
        Funds are distributed only if the corresponding order's shipping_status is 'Delivered'.
        Sends an email to the seller confirming the funds have been credited to their bank or PayPal.
        Only accessible by an admin.
        """
        logger.debug(f"Starting process_manual_fund_distribution for fund_id: {fund_id}")

        # Check if the logged-in user is an admin
        admin_id = request.session.get('user_id')
        logger.debug(f"Admin ID from session: {admin_id}")
        if not admin_id:
            logger.warning("No admin_id found in session, redirecting to login.")
            messages.error(request, "Please log in.")
            return redirect('core:login')

        with connection.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
            admin_role = cursor.fetchone()
        logger.debug(f"Admin role fetched: {admin_role}")
        if not admin_role or admin_role[0] != 'admin':
            logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
            messages.error(request, "You are not authorized to access this page.")
            return redirect('core:login')

        try:
            with connection.cursor() as cursor:
                # Fetch the specific fund distribution and related data
                cursor.execute("""
                    SELECT fd.id, fd.invoice_id, fd.auction_id, fd.seller_id, 
                           fd.platform_share, fd.seller_share, u.bank_account_number, u.paypal_email,
                           o.shipping_status
                    FROM fund_distribution fd
                    JOIN users u ON fd.seller_id = u.id
                    JOIN orders o ON fd.invoice_id = o.invoice_id
                    WHERE fd.id = %s AND fd.status = 'Pending'
                """, [fund_id])
                distribution = cursor.fetchone()

                if not distribution:
                    logger.warning(f"No pending fund distribution found for ID {fund_id} or order not delivered.")
                    messages.error(request, "Fund distribution not found or already processed.")
                    return redirect('payment_details')

                fund_id, invoice_id, auction_id, seller_id, platform_share, seller_share, bank_account, paypal_email, shipping_status = distribution

                if shipping_status != 'Delivered':
                    logger.warning(
                        f"Order for fund_id {fund_id} has shipping_status {shipping_status}, cannot distribute funds.")
                    messages.error(request, "Cannot distribute funds: Order has not been delivered.")
                    return redirect('payment_details')

                # Fetch payment_date from the payment_details table for the corresponding invoice
                cursor.execute("""
                    SELECT payment_date FROM payment_details WHERE invoice_id = %s
                """, [invoice_id])
                payment_data = cursor.fetchone()

                if not payment_data:
                    logger.error(f"No payment data found for Invoice ID {invoice_id}.")
                    messages.error(request, f"No payment data found for Invoice ID {invoice_id}.")
                    return redirect('payment_details')

                payment_date = payment_data[0]

                # Make payment_date aware if it is naive
                if timezone.is_naive(payment_date):
                    payment_date = timezone.make_aware(payment_date)

                # Check if 1 hour has passed since the payment date (optional, can be removed for manual processing)
                if payment_date + timezone.timedelta(minutes=1) > timezone.now():
                    logger.warning(f"Payment for Invoice {invoice_id} is less than 1 hour old.")
                    messages.warning(request, "Payment is recent. Consider waiting before distributing funds.")
                    return redirect('payment_details')

                # Proceed with fund distribution
                with transaction.atomic():  # Ensure atomicity
                    # Check seller's payout method
                    if bank_account:
                        payment_method = f"Bank Transfer to {bank_account}"
                        credited_to = f"bank account ending in {bank_account[-4:]}"
                    elif paypal_email:
                        payment_method = f"PayPal Transfer to {paypal_email}"
                        credited_to = f"PayPal account ({paypal_email})"
                    else:
                        logger.error(f"No payout method found for Seller ID {seller_id}.")
                        messages.error(request, "No payout method found for the seller.")
                        return redirect('payment_details')

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

                    logger.info(f"Fund transferred for Auction {auction_id} using {payment_method}")

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
                        # Assuming notify_user is a custom function for in-app notifications
                        notify_user(seller_id, seller_email, seller_message, subject="Funds Credited for Your Auction")
                        logger.info(f"Email sent to seller {seller_id} ({seller_email})")

                    # Notify the platform admin
                    admin_message = (
                        f"Manual fund distribution processed for Auction ID: {auction_id}.\n"
                        f"Seller's Share: ₹{seller_share:.2f}\n"
                        f"Platform Commission: ₹{platform_share:.2f}\n"
                        f"Seller ID: {seller_id}\n"
                        f"Payment Method: {payment_method}\n"
                        f"Transaction ID: {transaction_id}"
                    )
                    send_mail("Manual Fund Distribution Processed", admin_message, platform_email, [platform_email])
                    logger.info("Fund distribution email sent to platform admin.")

                    messages.success(request, f"Funds successfully distributed for Auction ID {auction_id}.")
                    return redirect('payment_details')

        except Exception as e:
            logger.error(f"Failed to process fund distribution for fund_id {fund_id}: {str(e)}")
            messages.error(request, f"Failed to process fund distribution: {str(e)}")
            return redirect('payment_details')

def invoice_list(request):
    """
    View to display all invoices from the invoices table.
    Only accessible by an admin.
    GET: Fetch and display all invoice records with search, filter, and pagination.
    POST: Handle delete action or export request for invoices.
    """
    logger.debug(f"Starting invoice_list view, request method: {request.method}")

    # Check if the logged-in user is an admin
    admin_id = request.session.get('user_id')
    logger.debug(f"Admin ID from session: {admin_id}")
    if not admin_id:
        logger.warning("No admin_id found in session, redirecting to login.")
        messages.error(request, "Please log in.")
        return redirect('core:login')

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    logger.debug(f"Admin role fetched: {admin_role}")
    if not admin_role or admin_role[0] != 'admin':
        logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
        messages.error(request, "You are not authorized to access this page.")
        return redirect('login')

    if request.method == "GET":
        logger.info("Processing GET request for invoice_list")

        # Search parameter
        search_query = request.GET.get('search', '').strip()

        # Filter parameters
        status_filter = request.GET.get('status', 'All Status')
        date_range = request.GET.get('date_range', 'Last 30 days')

        # Pagination parameters
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 10))
        offset = (page - 1) * per_page

        # Build base query
        base_query = """
            SELECT id, auction_id, buyer_id, seller_id, amount_due, issue_date,
                   due_date, status, late_fee, reminder_sent
            FROM invoices
            WHERE 1=1
        """
        params = []

        # Add search conditions
        if search_query:
            base_query += " AND (CAST(id AS TEXT) ILIKE %s OR CAST(auction_id AS TEXT) ILIKE %s OR CAST(buyer_id AS TEXT) ILIKE %s OR CAST(seller_id AS TEXT) ILIKE %s)"
            search_pattern = f'%{search_query}%'
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

        # Add status filter
        if status_filter != 'All Status':
            base_query += " AND status = %s"
            params.append(status_filter)

        # Add date range filter
        if date_range == 'Last 30 days':
            start_date = datetime.now() - timedelta(days=30)
            base_query += " AND issue_date >= %s"
            params.append(start_date)
        elif date_range == 'Last 90 days':
            start_date = datetime.now() - timedelta(days=90)
            base_query += " AND issue_date >= %s"
            params.append(start_date)
        elif date_range == 'This year':
            start_date = datetime(datetime.now().year, 1, 1)
            base_query += " AND issue_date >= %s"
            params.append(start_date)

        # Get total count for pagination
        with connection.cursor() as cursor:
            count_query = f"SELECT COUNT(*) FROM ({base_query}) as count_query"
            cursor.execute(count_query, params)
            total_invoices = cursor.fetchone()[0]

        # Add ordering and pagination
        base_query += " ORDER BY issue_date DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        # Fetch invoices
        with connection.cursor() as cursor:
            cursor.execute(base_query, params)
            invoices = [
                {
                    "id": row[0],
                    "auction_id": row[1],
                    "buyer_id": row[2],
                    "seller_id": row[3],
                    "amount_due": row[4],
                    "issue_date": row[5],
                    "due_date": row[6],
                    "status": row[7],
                    "late_fee": row[8],
                    "reminder_sent": bool(row[9]),
                } for row in cursor.fetchall()
            ]

        # Calculate pagination details
        total_pages = (total_invoices + per_page - 1) // per_page
        start_range = offset + 1
        end_range = min(offset + per_page, total_invoices)

        logger.debug(f"Fetched {len(invoices)} invoice records out of {total_invoices}")
        return render(request, "invoice_list.html", {
            "invoices": invoices,
            "total_invoices": total_invoices,
            "current_page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "start_range": start_range,
            "end_range": end_range,
            "search_query": search_query,
            "status_filter": status_filter,
            "date_range": date_range,
        })

    elif request.method == "POST":
        logger.info("Processing POST request for invoice_list")
        action = request.POST.get('action')

        if action == 'delete':
            invoice_id = request.POST.get('invoice_id')
            if not invoice_id:
                logger.error(f"Invalid POST data: invoice_id={invoice_id}")
                return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

            try:
                logger.debug(f"Processing delete request for invoice_id: {invoice_id}")
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM invoices WHERE id = %s", [invoice_id])
                    logger.debug(f"Invoice {invoice_id} deleted successfully")

                return JsonResponse({
                    "status": "success",
                    "message": f"Invoice {invoice_id} has been deleted successfully."
                })
            except Exception as e:
                logger.error(f"Error deleting invoice_id {invoice_id}: {str(e)}", exc_info=True)
                return JsonResponse({"status": "error", "message": f"Failed to delete invoice: {str(e)}"}, status=500)

        elif action == 'export':
            logger.info("Processing export request for invoices")
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, auction_id, buyer_id, seller_id, amount_due, issue_date,
                           due_date, status, late_fee, reminder_sent
                    FROM invoices
                    ORDER BY issue_date DESC
                """)
                invoices = cursor.fetchall()

            # Create CSV response
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="invoices_export.csv"'

            writer = csv.writer(response)
            writer.writerow([
                'Invoice ID', 'Auction ID', 'Buyer ID', 'Seller ID', 'Amount Due',
                'Issue Date', 'Due Date', 'Status', 'Late Fee', 'Reminder Sent'
            ])

            for row in invoices:
                writer.writerow([
                    row[0], row[1], row[2], row[3], f"₹{row[4]:.2f}",
                    row[5].strftime('%Y-%m-%d %H:%M'), row[6].strftime('%Y-%m-%d %H:%M'),
                    row[7], f"₹{row[8]:.2f}", 'Yes' if row[9] else 'No'
                ])

            logger.debug(f"Exported {len(invoices)} invoices to CSV")
            return response

        else:
            logger.warning(f"Invalid action in POST request: {action}")
            return JsonResponse({"status": "error", "message": "Invalid action"}, status=400)

    else:
        logger.warning(f"Invalid request method: {request.method}")
        return redirect('invoice_list')

def edit_invoice(request, invoice_id):
        """
        View to edit an invoice.
        GET: Display the invoice details in a form for editing.
        POST: Update the invoice details in the database.
        """
        logger.debug(f"Starting edit_invoice view for invoice_id: {invoice_id}, request method: {request.method}")

        # Check if the logged-in user is an admin
        admin_id = request.session.get('user_id')
        logger.debug(f"Admin ID from session: {admin_id}")
        if not admin_id:
            logger.warning("No admin_id found in session, redirecting to login.")
            messages.error(request, "Please log in.")
            return redirect('login')

        with connection.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
            admin_role = cursor.fetchone()
        logger.debug(f"Admin role fetched: {admin_role}")
        if not admin_role or admin_role[0] != 'admin':
            logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
            messages.error(request, "You are not authorized to access this page.")
            return redirect('login')

        # Fetch the invoice
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, auction_id, buyer_id, seller_id, amount_due, issue_date, 
                       due_date, status, late_fee, reminder_sent
                FROM invoices
                WHERE id = %s
            """, [invoice_id])
            row = cursor.fetchone()

        if not row:
            logger.warning(f"Invoice {invoice_id} not found.")
            messages.error(request, "Invoice not found.")
            return redirect('invoice_list')

        invoice = {
            "id": row[0],
            "auction_id": row[1],
            "buyer_id": row[2],
            "seller_id": row[3],
            "amount_due": row[4],
            "issue_date": row[5],
            "due_date": row[6],
            "status": row[7],
            "late_fee": row[8],
            "reminder_sent": bool(row[9]),
        }

        if request.method == "GET":
            logger.info(f"Displaying edit form for invoice {invoice_id}")
            return render(request, "edit_invoice.html", {"invoice": invoice})

        elif request.method == "POST":
            logger.info(f"Processing POST request to update invoice {invoice_id}")
            auction_id = request.POST.get('auction_id')
            buyer_id = request.POST.get('buyer_id')
            seller_id = request.POST.get('seller_id')
            amount_due = request.POST.get('amount_due')
            issue_date = request.POST.get('issue_date')
            due_date = request.POST.get('due_date')
            status = request.POST.get('status')
            late_fee = request.POST.get('late_fee', '0.00')
            reminder_sent = request.POST.get('reminder_sent') == 'on'

            try:
                # Validate and convert dates
                issue_date = datetime.strptime(issue_date, '%Y-%m-%dT%H:%M')
                due_date = datetime.strptime(due_date, '%Y-%m-%dT%H:%M')

                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE invoices
                        SET auction_id = %s, buyer_id = %s, seller_id = %s, amount_due = %s, 
                            issue_date = %s, due_date = %s, status = %s, late_fee = %s, reminder_sent = %s
                        WHERE id = %s
                    """, [auction_id, buyer_id, seller_id, amount_due, issue_date, due_date,
                          status, late_fee, 1 if reminder_sent else 0, invoice_id])
                    logger.debug(f"Invoice {invoice_id} updated successfully")

                messages.success(request, f"Invoice {invoice_id} updated successfully.")
                return redirect('invoice_list')
            except Exception as e:
                logger.error(f"Error updating invoice_id {invoice_id}: {str(e)}", exc_info=True)
                messages.error(request, f"Failed to update invoice: {str(e)}")
                return render(request, "edit_invoice.html", {"invoice": invoice})

def admin_auction_list(request):
    """
    View to display all auctions from the auctions table.
    Only accessible by an admin.
    GET: Fetch and display all auction records.
    AJAX GET: Return auction data as JSON for real-time updates.
    """
    logger.debug(f"Starting admin_auction_list view, request method: {request.method}")

    # Check if the logged-in user is an admin
    admin_id = request.session.get('user_id')
    logger.debug(f"Admin ID from session: {admin_id}")
    if not admin_id:
        logger.warning("No admin_id found in session, redirecting to login.")
        messages.error(request, "Please log in.")
        return redirect('login')

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [admin_id])
        admin_role = cursor.fetchone()
    logger.debug(f"Admin role fetched: {admin_role}")
    if not admin_role or admin_role[0] != 'admin':
        logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
        messages.error(request, "You are not authorized to access this page.")
        return redirect('login')

    def fetch_auctions():
        """Helper function to fetch auctions from the database."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, user_id, title, description, category, starting_price, 
                       reserve_price, bid_increment, start_date, end_date, created_at, 
                       updated_at, category_id, current_bid, is_make_offer_enabled, 
                       buy_it_now_price, auction_type, `condition`, condition_description, 
                       winner_user_id, global_notified, checked, views_count, status, 
                       is_relisted
                FROM auctions
                ORDER BY created_at DESC
            """)
            auctions = [
                {
                    "id": row[0],
                    "user_id": row[1],
                    "title": row[2],
                    "description": row[3],
                    "category": row[4],
                    "starting_price": row[5],
                    "reserve_price": row[6],
                    "bid_increment": row[7],
                    "start_date": row[8],
                    "end_date": row[9],
                    "created_at": row[10],
                    "updated_at": row[11],
                    "category_id": row[12],
                    "current_bid": row[13],
                    "is_make_offer_enabled": bool(row[14]),
                    "buy_it_now_price": row[15],
                    "auction_type": row[16],
                    "condition": row[17],
                    "condition_description": row[18],
                    "winner_user_id": row[19],
                    "global_notified": bool(row[20]),
                    "checked": bool(row[21]),
                    "views_count": row[22],
                    "status": row[23],
                    "is_relisted": bool(row[24]),
                } for row in cursor.fetchall()
            ]
        return auctions

    if request.method == "GET":
        logger.info("Processing GET request for admin_auction_list")
        auctions = fetch_auctions()

        # Check if the request is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            logger.debug("Processing AJAX request for auction data")
            return JsonResponse({"auctions": auctions})

        logger.debug(f"Fetched {len(auctions)} auction records")
        return render(request, "admin_auction_list.html", {"auctions": auctions})

    else:
        logger.warning(f"Invalid request method: {request.method}")
        return redirect('adash')




def admin_edit_auction(request, auction_id):
    logger.debug("Entered admin_edit_auction for auction_id: %s", auction_id)

    # Get logged-in user ID from session
    user_id = request.session.get('user_id')
    if not user_id:
        logger.warning("No user_id in session")
        return redirect('home')

    # Check if the user is admin
    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
        user_data = cursor.fetchone()
    if not user_data or user_data[0] != 'admin':
        logger.warning("User %s is not admin.", user_id)
        return redirect('home')

    # Helper function to fetch auction data
    def fetch_auction_data(auction_id):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT a.id, a.user_id, a.title, a.description, a.category, a.starting_price, a.reserve_price, 
                       a.bid_increment, a.start_date, a.end_date, a.created_at, a.updated_at, a.category_id, 
                       a.current_bid, a.is_make_offer_enabled, a.buy_it_now_price, a.auction_type, 
                       a.condition, a.condition_description, a.winner_user_id, a.global_notified, a.checked, 
                       a.views_count, a.status, a.is_relisted,
                       s.winner_selection_date
                FROM auctions a
                LEFT JOIN sealed_bid_details s ON a.id = s.auction_id
                WHERE a.id = %s
            """, [auction_id])
            auction = cursor.fetchone()
        if not auction:
            logger.error("Auction %s not found.", auction_id)
            raise Http404("Auction not found.")

        auction_data = {
            'id': auction[0],
            'user_id': auction[1],
            'title': auction[2],
            'description': auction[3],
            'category': auction[4],
            'starting_price': float(auction[5]) if auction[5] is not None else None,
            'reserve_price': float(auction[6]) if auction[6] is not None else None,
            'bid_increment': float(auction[7]) if auction[7] is not None else None,
            'start_date': auction[8].isoformat() if auction[8] else None,
            'end_date': auction[9].isoformat() if auction[9] else None,
            'created_at': auction[10].isoformat() if auction[10] else None,
            'updated_at': auction[11].isoformat() if auction[11] else None,
            'category_id': auction[12],
            'current_bid': float(auction[13]) if auction[13] is not None else None,
            'is_make_offer_enabled': bool(auction[14]),
            'buy_it_now_price': float(auction[15]) if auction[15] is not None else None,
            'auction_type': auction[16],
            'condition': auction[17],
            'condition_description': auction[18],
            'winner_user_id': auction[19],
            'global_notified': bool(auction[20]),
            'checked': bool(auction[21]),
            'views_count': auction[22],
            'status': auction[23],
            'is_relisted': bool(auction[24]),
            'winner_selection_date': auction[25].isoformat() if auction[25] else None,  # Add winner_selection_date
        }

        with connection.cursor() as cursor:
            cursor.execute("SELECT image_path FROM auction_images WHERE auction_id = %s", [auction_id])
            image_rows = cursor.fetchall()
        auction_image_paths = [f"/media/auction_images/{row[0]}" for row in image_rows]
        return auction_data, auction_image_paths

    # Handle GET request (fetch data for form)
    if request.method == 'GET':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                auction_data, auction_image_paths = fetch_auction_data(auction_id)
                return JsonResponse({
                    'auction': auction_data,
                    'auction_image_paths': auction_image_paths
                })
            except Exception as e:
                logger.exception("Error fetching auction data for auction_id %s: %s", auction_id, str(e))
                return JsonResponse({'error': 'Failed to fetch auction data'}, status=500)
        else:
            return render(request, 'admin_edit_auction.html', {'auction_id': auction_id})

    # Handle POST request (update auction)
    if request.method == 'POST':
        try:
            # Helper functions to clean values
            def clean_numeric(value):
                try:
                    return float(value) if value.strip() else None
                except (ValueError, AttributeError):
                    return None

            def clean_int(value):
                try:
                    return int(value) if value.strip() else None
                except (ValueError, AttributeError):
                    return None

            # Fetch current auction data to preserve disabled fields and reserve_price if not updated
            current_auction, _ = fetch_auction_data(auction_id)

            # Process form data (only update fields that are editable)
            title = request.POST.get('title')
            if not title:
                return JsonResponse({'error': 'Title is required'}, status=400)

            description = request.POST.get('description')
            category = request.POST.get('category')
            starting_price = clean_numeric(request.POST.get('starting_price', ''))
            bid_increment = clean_numeric(request.POST.get('bid_increment', ''))
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            category_id = clean_int(request.POST.get('category_id', ''))
            winner_user_id = clean_int(request.POST.get('winner_user_id', ''))
            global_notified = 1 if request.POST.get('global_notified') == '1' else 0
            checked = 1 if request.POST.get('checked') == '1' else 0
            status = request.POST.get('status')
            buy_it_now_price = clean_numeric(request.POST.get('buy_it_now_price', ''))
            winner_selection_date = request.POST.get('winner_selection_date')  # Get winner_selection_date from form

            # Handle reserve_price based on auction_type
            reserve_price = clean_numeric(request.POST.get('reserve_price', ''))
            if reserve_price is None:  # If no new value provided, keep the current one
                reserve_price = current_auction['reserve_price']

            # Preserve disabled fields from current auction data
            auction_type = current_auction['auction_type']
            current_bid = current_auction['current_bid']
            is_make_offer_enabled = current_auction['is_make_offer_enabled']
            condition = current_auction['condition']
            condition_description = current_auction['condition_description']
            views_count = current_auction['views_count']
            is_relisted = current_auction['is_relisted']

            # Update auction in database
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE auctions
                    SET title = %s, description = %s, category = %s, starting_price = %s, reserve_price = %s,
                        bid_increment = %s, start_date = %s, end_date = %s, category_id = %s, current_bid = %s,
                        is_make_offer_enabled = %s, buy_it_now_price = %s, auction_type = %s, `condition` = %s,
                        condition_description = %s, winner_user_id = %s, global_notified = %s, checked = %s,
                        views_count = %s, status = %s, is_relisted = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, [
                    title, description, category, starting_price, reserve_price, bid_increment, start_date,
                    end_date, category_id, current_bid, is_make_offer_enabled, buy_it_now_price, auction_type,
                    condition, condition_description, winner_user_id, global_notified, checked, views_count,
                    status, is_relisted, auction_id
                ])

            # Update or insert winner_selection_date in sealed_bid_details if auction_type is 'sealed'
            if auction_type == 'sealed' and winner_selection_date:
                with connection.cursor() as cursor:
                    # Check if a record already exists in sealed_bid_details
                    cursor.execute("SELECT COUNT(*) FROM sealed_bid_details WHERE auction_id = %s", [auction_id])
                    exists = cursor.fetchone()[0] > 0

                    if exists:
                        # Update existing record
                        cursor.execute("""
                            UPDATE sealed_bid_details
                            SET winner_selection_date = %s
                            WHERE auction_id = %s
                        """, [winner_selection_date, auction_id])
                    else:
                        # Insert new record
                        cursor.execute("""
                            INSERT INTO sealed_bid_details (auction_id, winner_selection_date)
                            VALUES (%s, %s)
                        """, [auction_id, winner_selection_date])

            # Handle image uploads
            if 'images' in request.FILES:
                uploaded_files = request.FILES.getlist('images')
                for file in uploaded_files:
                    file_name = f"auction_{auction_id}_{file.name}"
                    file_path = os.path.join(settings.MEDIA_ROOT, "auction_images", file_name)
                    with default_storage.open(file_path, 'wb+') as destination:
                        for chunk in file.chunks():
                            destination.write(chunk)
                    with connection.cursor() as cursor:
                        cursor.execute("INSERT INTO auction_images (auction_id, image_path) VALUES (%s, %s)", [auction_id, file_name])

            # Fetch updated data
            updated_auction_data, updated_image_paths = fetch_auction_data(auction_id)
            return JsonResponse({
                'auction': updated_auction_data,
                'auction_image_paths': updated_image_paths,
                'message': 'Auction updated successfully'
            })

        except Exception as e:
            logger.exception("Error updating auction %s: %s", auction_id, str(e))
            return JsonResponse({'error': f'Internal server error: {str(e)}'}, status=500)

@csrf_exempt  # Remove this if you handle CSRF properly in production
def delete_auction_image(request):
    if request.method == 'POST':
        auction_id = request.POST.get('auction_id')
        image_path = request.POST.get('image_path')

        # Validate inputs
        if not auction_id or not image_path:
            return JsonResponse({'success': False, 'error': 'Missing auction_id or image_path'}, status=400)

        # Check admin permissions (similar to admin_edit_auction)
        user_id = request.session.get('user_id')
        with connection.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
            user_data = cursor.fetchone()
        if not user_data or not user_data[0]:
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

        # Delete from filesystem
        file_path = os.path.join(settings.MEDIA_ROOT, "auction_images", image_path)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug("Deleted file from disk: %s", file_path)
            except Exception as e:
                logger.exception("Failed to delete file %s: %s", file_path, e)

        # Delete from database
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM auction_images
                WHERE auction_id = %s AND image_path = %s
            """, [auction_id, image_path])
            if cursor.rowcount > 0:
                logger.debug("Deleted image record for: %s", image_path)
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': 'Image not found'}, status=404)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)



@csrf_exempt
@require_POST
def chatbot_response(request):
    # Check if user is admin
    is_admin = request.session.get('role') == 'admin'
    if not is_admin:
        logger.warning(f"Unauthorized access attempt: session role = {request.session.get('role')}")
        return JsonResponse({'success': False, 'response': 'Unauthorized access'}, status=403)

    chatbot = Chatbot()
    try:
        data = json.loads(request.body)
        user_id = request.session.get('user_id', 'default')
        username = request.session.get('username', None)
        logger.debug(f"Received payload: {data}")

        # Admin response handling
        if 'question' in data and 'answer' in data and 'intent' in data:
            question = data['question'].strip()
            answer = data['answer'].strip()
            intent = data['intent'].strip()

            if not question or not answer or not intent:
                logger.warning(f"Empty fields in payload: question='{question}', answer='{answer}', intent='{intent}'")
                return JsonResponse(
                    {'success': False, 'response': 'Question, answer, and intent cannot be empty'},
                    status=400
                )

            # Validate intent tag format (lowercase letters, numbers, underscores only)
            if not re.match(r'^[a-z0-9_]+$', intent):
                logger.warning(f"Invalid intent tag format: {intent}")
                return JsonResponse(
                    {'success': False, 'response': 'Intent tag must contain only lowercase letters, numbers, and underscores'},
                    status=400
                )

            logger.info(f"Processing admin response for question: {question} with intent: {intent}")
            response = chatbot.handle_admin_response(
                json.dumps({'question': question, 'answer': answer, 'intent': intent}),
                user_id,
                username
            )
            return JsonResponse({'success': True, 'response': response})
        else:
            logger.warning(f"Invalid admin payload: {data}")
            return JsonResponse(
                {'success': False, 'response': 'Please provide question, answer, and intent'},
                status=400
            )
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return JsonResponse({'success': False, 'response': 'Invalid JSON payload'}, status=400)
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return JsonResponse({'success': False, 'response': str(e)}, status=500)
def chatbot_user_response(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            message = data.get('message')
            user_id = request.session.get('user_id', 'default')
            username = request.session.get('username', None)
            is_authenticated = 'user_id' in request.session
            is_admin = request.session.get('role') == 'admin'

            if not message:
                return JsonResponse({'success': False, 'response': 'Please provide a message'}, status=400)

            chatbot = Chatbot()
            response = chatbot.get_response(
                message,
                user_id=user_id,
                is_authenticated=is_authenticated,
                username=username,
                is_admin=is_admin
            )
            return JsonResponse({'success': True, 'response': response})
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            return JsonResponse({'success': False, 'response': 'Invalid JSON payload'}, status=400)
        except Exception as e:
            logger.error(f"Error processing user request: {str(e)}")
            return JsonResponse({'success': False, 'response': f'Error: {str(e)}'}, status=400)
    return JsonResponse({'success': False, 'response': 'Invalid request method'}, status=405)

@require_GET
def get_intents(request):
    chatbot = Chatbot()
    try:
        # Update path to point to core/intents.json
        intents_file = os.path.join(settings.BASE_DIR, 'core', 'intents.json')
        logger.debug(f"Attempting to read intents from: {intents_file}")
        with open(intents_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        intents = [intent['tag'] for intent in data.get('intents', [])]
        logger.debug(f"Loaded intents: {intents}")
        return JsonResponse({'intents': intents}, safe=False)
    except FileNotFoundError as e:
        logger.error(f"intents.json not found: {str(e)}")
        return JsonResponse({'error': 'intents.json not found'}, status=500)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in intents.json: {str(e)}")
        return JsonResponse({'error': 'Invalid JSON in intents.json'}, status=500)
    except PermissionError as e:
        logger.error(f"Permission denied for intents.json: {str(e)}")
        return JsonResponse({'error': 'Permission denied for intents.json'}, status=500)
    except Exception as e:
        logger.error(f"Unexpected error in get_intents: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
def get_new_questions(request):
    try:
        new_questions_file = os.path.join(os.path.dirname(__file__), 'new_questions.json')
        with open(new_questions_file, 'r', encoding='utf-8') as f:
            new_questions = json.load(f)
        # Filter unanswered questions
        unanswered = [q for q in new_questions['questions'] if not q.get('answered', False)]
        return JsonResponse({'success': True, 'questions': unanswered})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
def admin_feedback(request):
    """
    A view that returns a basic HTML skeleton, with feedback loaded via AJAX.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "Please log in.")
        return redirect('auth_user')

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
        user_role = cursor.fetchone()

    if not user_role or user_role[0] != 'admin':
        messages.error(request, "You are not authorized to access this page.")
        return redirect('auth_user')

    return render(request, "admin_feedback.html")

@require_GET
def initial_feedback(request):
    """
    A view to fetch initial feedback data via AJAX.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({"error": "Please log in."}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
        user_role = cursor.fetchone()

    if not user_role or user_role[0] != 'admin':
        return JsonResponse({"error": "You are not authorized to access this page."}, status=403)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                f.id, f.user_id, f.name, f.email, f.subject, f.message, f.file_paths, f.created_at, u.account_status,
                IFNULL(
                    JSON_ARRAYAGG(
                        JSON_OBJECT(
                            'reply_text', fr.reply_text,
                            'reply_created_at', fr.created_at,
                            'admin_id', fr.admin_id
                        )
                    ), '[]'
                ) AS replies
            FROM feedback f
            LEFT JOIN users u ON f.user_id = u.id
            LEFT JOIN feedback_replies fr ON f.id = fr.feedback_id
            GROUP BY f.id, f.user_id, f.name, f.email, f.subject, f.message, f.file_paths, f.created_at, u.account_status
            ORDER BY f.created_at DESC
        """)
        feedback_rows = []
        for row in cursor.fetchall():
            replies = json.loads(row[9]) if row[9] and row[9] != 'null' else []
            feedback = {
                "id": row[0],
                "user_id": row[1],
                "name": row[2],
                "email": row[3],
                "subject": row[4],
                "message": row[5],
                "file_paths": [f"{settings.MEDIA_URL}{path}" for path in row[6].split(',')] if row[6] else [],
                "created_at": row[7].isoformat() if row[7] else None,
                "account_status": row[8],
                "replies": replies
            }
            feedback_rows.append(feedback)

    seller_feedback = [f for f in feedback_rows if f["account_status"] == 'verified']
    buyer_feedback = [f for f in feedback_rows if f["account_status"] != 'verified']

    return JsonResponse({
        "seller_feedback": seller_feedback,
        "buyer_feedback": buyer_feedback,
        "last_updated": timezone.now().isoformat()
    })

@require_POST
def delete_feedback(request, feedback_id):
    """
    Delete a feedback entry by ID and return JSON response.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({"success": False, "error": "Please log in."}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
        user_role = cursor.fetchone()

    if not user_role or user_role[0] != 'admin':
        return JsonResponse({"success": False, "error": "You are not authorized to perform this action."}, status=403)

    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM feedback WHERE id = %s", [feedback_id])
            if cursor.rowcount > 0:
                return JsonResponse({"success": True})
            else:
                return JsonResponse({"success": False, "error": "Feedback not found."}, status=404)
    except Exception as e:
        logger.error(f"Error deleting feedback ID {feedback_id}: {str(e)}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)

@require_POST
def reply_feedback(request, feedback_id):
    """
    Reply to a feedback entry by ID, send email, and trigger notification.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        logger.error("No user_id in session for reply_feedback")
        return JsonResponse({"success": False, "error": "Please log in."}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
        user_role = cursor.fetchone()

    if not user_role or user_role[0] != 'admin':
        logger.error(f"Unauthorized access to reply_feedback by user_id {user_id}")
        return JsonResponse({"success": False, "error": "You are not authorized to perform this action."}, status=403)

    reply_text = request.POST.get('reply_text')
    if not reply_text:
        return JsonResponse({"success": False, "error": "Reply cannot be empty."}, status=400)

    try:
        with connection.cursor() as cursor:
            # Fetch user email from users table based on feedback user_id
            cursor.execute("SELECT u.email FROM feedback f JOIN users u ON f.user_id = u.id WHERE f.id = %s", [feedback_id])
            user_email = cursor.fetchone()
            if not user_email:
                logger.error(f"No email found for feedback ID {feedback_id}")
                return JsonResponse({"success": False, "error": "User email not found."}, status=404)

            user_email = user_email[0]

            # Check if a reply exists for this feedback_id
            cursor.execute("""
                SELECT id FROM feedback_replies WHERE feedback_id = %s AND admin_id = %s
            """, [feedback_id, user_id])
            existing_reply = cursor.fetchone()

            if existing_reply:
                # Update existing reply
                cursor.execute("""
                    UPDATE feedback_replies
                    SET reply_text = %s, created_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, [reply_text, existing_reply[0]])
            else:
                # Insert new reply
                cursor.execute("""
                    INSERT INTO feedback_replies (feedback_id, admin_id, reply_text)
                    VALUES (%s, %s, %s)
                """, [feedback_id, user_id, reply_text])

            # Send email notification
            subject = 'AuctionHub - Reply to Your Feedback'
            message = f"Dear {user_email.split('@')[0]},\n\nYour feedback has been addressed:\n\n{reply_text}\n\nRegards,\nAuctionHub Admin Team"
            from_email = settings.DEFAULT_FROM_EMAIL
            try:
                send_mail(
                    subject,
                    message,
                    from_email,
                    [user_email],
                    fail_silently=False,
                )
                logger.info(f"Email sent to {user_email} for feedback ID {feedback_id}")
            except Exception as e:
                logger.error(f"Failed to send email to {user_email} for feedback ID {feedback_id}: {str(e)}")
                return JsonResponse({"success": False, "error": f"Reply saved but email failed: {str(e)}"}, status=500)

            return JsonResponse({"success": True, "new_reply": reply_text, "feedback_id": feedback_id, "created_at": timezone.now().isoformat()})
    except DatabaseError as db_error:
        logger.error(f"Database error in reply_feedback for feedback ID {feedback_id}: {str(db_error)}")
        return JsonResponse({"success": False, "error": f"Database error: {str(db_error)}"}, status=500)
    except Exception as e:
        logger.error(f"Unexpected error in reply_feedback for feedback ID {feedback_id}: {str(e)}")
        return JsonResponse({"success": False, "error": f"Unexpected error: {str(e)}"}, status=500)

@require_GET
def feedback_api(request):
    """
    A view to fetch incremental feedback updates via AJAX.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({"error": "Please log in."}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT role FROM users WHERE id = %s", [user_id])
        user_role = cursor.fetchone()

    if not user_role or user_role[0] != 'admin':
        return JsonResponse({"error": "You are not authorized to access this page."}, status=403)

    last_updated = request.GET.get('last_updated')
    query = """
        SELECT 
            f.id, f.user_id, f.name, f.email, f.subject, f.message, f.file_paths, f.created_at, u.account_status,
            IFNULL(
                JSON_ARRAYAGG(
                    JSON_OBJECT(
                        'reply_text', fr.reply_text,
                        'reply_created_at', fr.created_at,
                        'admin_id', fr.admin_id
                    )
                ), '[]'
            ) AS replies
        FROM feedback f
        LEFT JOIN users u ON f.user_id = u.id
        LEFT JOIN feedback_replies fr ON f.id = fr.feedback_id
    """
    params = []
    if last_updated:
        query += " WHERE f.created_at > %s"
        params.append(last_updated)

    query += """
        GROUP BY f.id, f.user_id, f.name, f.email, f.subject, f.message, f.file_paths, f.created_at, u.account_status
        ORDER BY f.created_at DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        feedback_rows = []
        for row in cursor.fetchall():
            replies = json.loads(row[9]) if row[9] and row[9] != 'null' else []
            feedback = {
                "id": row[0],
                "user_id": row[1],
                "name": row[2],
                "email": row[3],
                "subject": row[4],
                "message": row[5],
                "file_paths": [f"{settings.MEDIA_URL}{path}" for path in row[6].split(',')] if row[6] else [],
                "created_at": row[7].isoformat() if row[7] else None,
                "account_status": row[8],
                "replies": replies
            }
            feedback_rows.append(feedback)

    seller_feedback = [f for f in feedback_rows if f["account_status"] == 'verified']
    buyer_feedback = [f for f in feedback_rows if f["account_status"] != 'verified']

    return JsonResponse({
        "seller_feedback": seller_feedback,
        "buyer_feedback": buyer_feedback,
        "last_updated": timezone.now().isoformat()
    })