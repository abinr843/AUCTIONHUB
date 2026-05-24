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
from django.db.models import Max, Count, Q, F, Subquery, OuterRef, Sum, Case, When, Value, CharField
from django.utils.timezone import now, make_aware
from django.shortcuts import render, redirect
from django.contrib import messages
from uuid import uuid4
from decimal import Decimal
import csv
from .chatbot import Chatbot
import string
from .models import (
    User, Category, Auction, AuctionImage, Bid, Offer, Invoice, Order,
    Notification, Watchlist, Message, Feedback, FeedbackReply, PaymentDetail,
    FundDistribution, SellerPayout, ShippingDetail, MembershipPlan, PremiumUser,
    PlatformCommission, SealedBidDetail, UserActivity, UserOTP, Wallet,
    BankCard, ReportedUser, Review,
)
# Create a logger instance
logger = logging.getLogger(__name__)


def home(request):
    # Check if the user is logged in
    user_id = request.session.get('user_id')
    username = request.session.get('username')
    is_authenticated = False

    if user_id:
        # Fetch user authentication status from the database using ORM
        try:
            user_obj = User.objects.get(id=user_id)
            is_authenticated = user_obj.is_authenticated
            username = username or user_obj.username
        except User.DoesNotExist:
            # User not found; clear session to prevent stale data
            request.session.flush()
            is_authenticated = False
            username = None

    # Fetch auction data using ORM
    auctions_qs = Auction.objects.all().order_by('-start_date').values(
        'id', 'title', 'description', 'start_date', 'end_date', 'auction_type'
    )
    auction_list = list(auctions_qs)

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

    current_time = datetime.now()

    # Fetch total number of users using ORM
    total_users = User.objects.count()

    # Fetch total active auctions using ORM
    active_auctions = Auction.objects.filter(
        start_date__lte=current_time,
        end_date__gte=current_time,
        status='active'
    ).count()

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
        # Auction trend data (last 6 months based on start_date)
        auction_trend = {'labels': [], 'data': []}
        for i in range(5, -1, -1):  # Last 6 months, including current
            month_start = datetime.now().replace(day=1) - timedelta(days=i*30)
            month_end = datetime.now().replace(day=1) - timedelta(days=(i-1)*30)
            count = Auction.objects.filter(
                start_date__gte=month_start,
                start_date__lt=month_end
            ).count()
            auction_trend['labels'].append(month_start.strftime('%b'))
            auction_trend['data'].append(count)

        # User distribution data using ORM
        user_dist_raw = User.objects.values('role').annotate(count=Count('id'))
        user_dist = {'labels': [], 'data': []}
        role_map = {'buyer': 'Buyers', 'seller': 'Sellers', 'admin': 'Admins', 'guest': 'Guests'}
        for entry in user_dist_raw:
            label = role_map.get(entry['role'], entry['role'].capitalize())
            user_dist['labels'].append(label)
            user_dist['data'].append(entry['count'])
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
        'pending_disputes': 0,  # Hardcoded since disputes table doesn't exist
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

        # Check if username or email already exists using ORM
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists!")
            return render(request, "auth_page.html")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email is already registered! Please log in or use a different email.")
            return render(request, "auth_page.html")

        # Generate a random salt and hash the password
        salt = get_random_string(12)
        hashed_password = hashlib.sha256((password + salt).encode()).hexdigest()
        role = "user"  # Default role

        try:
            # Create user using ORM
            user_obj = User.objects.create(
                username=username,
                email=email,
                password_hash=hashed_password,
                salt=salt,
                role=role,
                email_verified=False,
                premium=False,
            )

            # Store email in session for OTP verification
            request.session['email'] = email

            # Generate OTP
            otp = random.randint(100000, 999999)

            # Store OTP in the database with a 5-minute expiration
            UserOTP.objects.create(
                user=user_obj,
                otp=str(otp),
                expires_at=now() + timedelta(minutes=5),
            )

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

        # Check if OTP is valid and not expired using ORM
        try:
            user_obj = User.objects.get(email=email)
            valid_otp = UserOTP.objects.filter(
                user=user_obj,
                otp=otp,
                expires_at__gt=now()
            ).first()

            if valid_otp:
                try:
                    # Mark email as verified
                    user_obj.email_verified = True
                    user_obj.save(update_fields=['email_verified'])

                    # Delete OTP after successful verification
                    UserOTP.objects.filter(user=user_obj).delete()
                    messages.success(request, "Email verified successfully!")

                    # Store user in session after successful verification
                    request.session['user_id'] = user_obj.id
                    request.session['username'] = user_obj.username

                except Exception as e:
                    logger.error(f"Error during email verification: {e}")
                    messages.error(request, "An error occurred during email verification.")

                return redirect('login')  # Redirect to user dashboard after successful verification
            else:
                messages.error(request, "Invalid or expired OTP. Please try again.")
        except User.DoesNotExist:
            messages.error(request, "User not found. Please sign up again.")
            return redirect('login')

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

            # Check if user exists using ORM
            try:
                user_obj = User.objects.get(email=email)
            except User.DoesNotExist:
                return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

            user_id = user_obj.id
            email_verified = user_obj.email_verified
            user_created_at = user_obj.created_at
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

            # Check for valid OTP using ORM
            current_time = timezone.now()
            otp_obj = UserOTP.objects.filter(
                user=user_obj,
                expires_at__gt=current_time
            ).order_by('-created_at').first()

            has_valid_otp = bool(otp_obj)
            can_request_new_otp = True
            otp_message = 'No valid OTP found. Request a new one.'

            if has_valid_otp:
                otp_created_at = otp_obj.created_at
                if timezone.is_naive(otp_created_at):
                    otp_created_at = timezone.make_aware(otp_created_at, timezone.get_default_timezone())
                otp_expires_at = otp_obj.expires_at
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

            # Check if user exists using ORM
            try:
                user_obj = User.objects.get(email=email)
            except User.DoesNotExist:
                return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

            user_id = user_obj.id
            email_verified = user_obj.email_verified
            user_created_at = user_obj.created_at
            if timezone.is_naive(user_created_at):
                user_created_at = timezone.make_aware(user_created_at, timezone.get_default_timezone())
            logger.info(f"Resend OTP for {email}: email_verified={email_verified}, created_at={user_created_at}")

            if email_verified:
                return JsonResponse({
                    'success': False,
                    'message': 'Email already verified. No OTP needed.'
                }, status=400)

            # Check for valid OTP using ORM
            current_time = timezone.now()
            logger.info(f"Current time at start: {current_time}")
            otp_obj = UserOTP.objects.filter(
                user=user_obj,
                expires_at__gt=current_time
            ).order_by('-created_at').first()

            if otp_obj:
                otp_created_at = otp_obj.created_at
                if timezone.is_naive(otp_created_at):
                    otp_created_at = timezone.make_aware(otp_created_at, timezone.get_default_timezone())
                time_diff = (current_time - otp_created_at).total_seconds() / 60
                logger.info(f"Existing OTP for {email}: created_at={otp_created_at}, time_diff={time_diff} minutes")

                if time_diff <= 5:
                    return JsonResponse({
                        'success': False,
                        'message': 'Please use the existing OTP or try again after 5 minutes.'
                    }, status=429)

            # Delete all existing OTPs for the user using ORM
            UserOTP.objects.filter(user=user_obj).delete()
            logger.info(f"Deleted all OTPs for user_id={user_id}")

            # Generate new OTP
            new_otp = str(random.randint(100000, 999999))

            # Use timezone-aware datetime and convert to session timezone
            current_time_local = timezone.localtime(current_time)
            expires_at_local = current_time_local + timedelta(minutes=10)

            # Insert new OTP using ORM within a transaction
            with transaction.atomic():
                otp_record = UserOTP.objects.create(
                    user=user_obj,
                    otp=new_otp,
                    created_at=current_time_local,
                    expires_at=expires_at_local,
                )
                logger.info(
                    f"Verified inserted OTP: created_at={otp_record.created_at}, expires_at={otp_record.expires_at}")

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

            # Check if user exists using ORM
            try:
                user_obj = User.objects.get(email=email)
            except User.DoesNotExist:
                return JsonResponse({'success': False, 'message': 'User not found.'}, status=404)

            if user_obj.email_verified:
                return JsonResponse({'success': True, 'message': 'Email already verified.'})

            # Check for valid OTP using ORM
            current_time = timezone.now()
            otp_record = UserOTP.objects.filter(
                user=user_obj,
                expires_at__gt=current_time
            ).order_by('-created_at').first()

            logger.info(f"OTP records for user_id={user_obj.id}: {otp_record}")

            if not otp_record:
                return JsonResponse({'success': False, 'message': 'No valid OTP found. Please request a new one.'},
                                    status=400)

            # Timezone handling
            created_at = otp_record.created_at
            expires_at = otp_record.expires_at
            if timezone.is_naive(created_at):
                created_at = timezone.make_aware(created_at, timezone.get_default_timezone())
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at, timezone.get_default_timezone())
            current_time_local = timezone.localtime(current_time)
            expires_at_local = timezone.localtime(expires_at)
            logger.info(
                f"Comparing OTP: stored={otp_record.otp}, provided={otp}, created_at={created_at}, expires_at={expires_at_local}, current_time={current_time_local}")

            if expires_at_local < current_time_local:
                return JsonResponse({'success': False, 'message': 'OTP has expired. Please request a new one.'},
                                    status=400)
            if otp_record.otp != otp:
                return JsonResponse({'success': False, 'message': 'Invalid OTP.'}, status=400)

            # OTP is valid, update email_verified using ORM
            user_obj.email_verified = True
            user_obj.save(update_fields=['email_verified'])

            # Delete used OTP
            UserOTP.objects.filter(user=user_obj).delete()

            return JsonResponse({'success': True, 'message': 'Email verified successfully.'})

        except Exception as e:
            logger.error(f"Error in verify_email_profile: {str(e)}")
            return JsonResponse({'success': False, 'message': 'An error occurred. Please try again.'}, status=500)

    return JsonResponse({'success': False, 'message': 'Invalid request method.'}, status=405)
def login(request):
    if request.method == "POST":
        email = request.POST.get('email')
        password = request.POST.get('password')

        # Fetch user using ORM
        try:
            user_obj = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, "Invalid email or password.")
            return render(request, 'auth_page.html')

        # Check if user is banned
        if user_obj.account_status == 'banned':
            messages.error(request, "Your account has been banned by the admin.")
            return redirect('banned_page')  # Redirect to banned page

        # Hash the provided password with the stored salt
        hashed_password = hashlib.sha256((password + user_obj.salt).encode()).hexdigest()

        if hashed_password == user_obj.password_hash:
            # Store user data in the session
            request.session['user_id'] = user_obj.id
            request.session['username'] = user_obj.username
            request.session['role'] = user_obj.role  # Store role in session
            request.session.set_expiry(3600)  # Session expires in 1 hour for security

            # Log the login activity using ORM
            UserActivity.objects.create(
                user=user_obj,
                description="User logged in"
            )

            # Update authentication status using ORM
            user_obj.is_authenticated = True
            user_obj.save(update_fields=['is_authenticated'])

            logging.info(f"User {user_obj.username} (ID: {user_obj.id}) logged in successfully.")

            # Redirect based on role
            if user_obj.role == 'admin':
                return redirect('adash')  # Redirect admin to Admin Dashboard
            else:
                return redirect('udash')  # Redirect regular users to User Dashboard

        else:
            messages.error(request, "Invalid email or password.")

    return render(request, 'auth_page.html')



def logout(request):
    # Get the user_id from the session if available.
    user_id = request.session.get('user_id')
    if user_id:
        # Update the is_authenticated field using ORM
        User.objects.filter(id=user_id).update(is_authenticated=False)

    request.session.flush()  # Clear the session
    messages.success(request, "Logged out successfully!")
    return redirect('auth_page')  # Redirect to the login page



def fopass(request):
    if request.method == "POST":
        email = request.POST.get('email')

        if not email:
            messages.error(request, "Please provide your email.")
            return render(request, 'fopass.html')

        # Check if the email exists using ORM
        try:
            user_obj = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, "No account found with this email.")
            return render(request, 'fopass.html')

        # Generate a 6-digit OTP
        otp = str(random.randint(100000, 999999))

        # OTP expiry time (5 minutes from now)
        otp_expiry_time = timezone.now() + timedelta(minutes=5)

        # Store the OTP using ORM
        UserOTP.objects.create(
            user=user_obj,
            otp=otp,
            expires_at=otp_expiry_time,
        )

        # Send OTP via email
        subject = "Password Reset OTP"
        message = f"Your OTP for password reset is {otp}. It is valid for 5 minutes."
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

        messages.success(request, "OTP has been sent to your email.")
        return redirect('repass')  # Redirect to the OTP verification page

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

        # Verify the OTP using ORM
        valid_otp = UserOTP.objects.filter(
            otp=otp,
            expires_at__gt=timezone.now()
        ).first()

        if valid_otp:
            user_obj = valid_otp.user

            # Hash the new password
            salt = get_random_string(12)  # Generate a random salt
            hashed_password = hashlib.sha256((new_password + salt).encode()).hexdigest()

            # Update the user's password using ORM
            user_obj.password_hash = hashed_password
            user_obj.salt = salt
            user_obj.save(update_fields=['password_hash', 'salt'])

            # Delete the used OTP
            UserOTP.objects.filter(user=user_obj).delete()

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
        # Fetch user details using ORM
        try:
            user_obj = User.objects.get(id=user_id)
        except User.DoesNotExist:
            messages.error(request, "User not found.")
            logger.error(f"udash - No user found for user_id: {user_id}")
            return redirect('login')

        username = user_obj.username
        is_premium = user_obj.premium
        account_status = user_obj.account_status
        phone = user_obj.phone
        address = user_obj.address
        pincode = user_obj.pincode
        bank_account_number = user_obj.bank_account_number
        id_proof = user_obj.id_proof

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
    locked = False
    user_auction_count = 0
    premium = False

    # Check user's premium status and auction count using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        premium = bool(user_obj.premium)
        user_auction_count = Auction.objects.filter(
            user_id=user_id,
            auction_type__in=['regular', 'buy_it_now', 'sealed_bid']
        ).count()
    except User.DoesNotExist:
        return redirect('auth_page')

    if user_auction_count >= 1 and not premium:
        locked = True

    if request.method == 'POST' and not locked:
        auction_type = request.POST.get('auction_type')

        item_condition = request.POST.get('item_condition', '')
        condition_description = request.POST.get('condition_description', '')

        current_time = timezone.now()
        default_start_date = current_time
        default_end_date = current_time + timedelta(days=7)

        # Helper to save auction images
        def _save_auction_images(auction_obj, images):
            for image in images:
                unique_filename = f"{uuid.uuid4().hex}_{image.name}"
                image_path = os.path.join(settings.MEDIA_ROOT, 'auction_images', unique_filename)
                os.makedirs(os.path.dirname(image_path), exist_ok=True)
                AuctionImage.objects.create(auction=auction_obj, image_path=unique_filename)
                with open(image_path, 'wb+') as destination:
                    for chunk in image.chunks():
                        destination.write(chunk)

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

            auction_obj = Auction.objects.create(
                user_id=user_id,
                title=title,
                description=description,
                category=category,
                starting_price=starting_price,
                reserve_price=reserve_price,
                bid_increment=bid_increment,
                start_date=start_date,
                end_date=end_date,
                auction_type=auction_type,
                condition=item_condition,
                condition_description=condition_description,
            )

            _save_auction_images(auction_obj, images)

            UserActivity.objects.create(user_id=user_id, description="Created a regular auction.")
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

            auction_obj = Auction.objects.create(
                user_id=user_id,
                title=title,
                description=description,
                category=category,
                buy_it_now_price=buy_it_now_price,
                is_make_offer_enabled=1 if is_make_offer_enabled else 0,
                start_date=start_date,
                end_date=end_date,
                auction_type=auction_type,
                condition=item_condition,
                condition_description=condition_description,
            )

            _save_auction_images(auction_obj, images)

            UserActivity.objects.create(user_id=user_id, description="Created a Buy It Now auction.")
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

            auction_obj = Auction.objects.create(
                user_id=user_id,
                title=title,
                description=description,
                category=category,
                reserve_price=reserve_price,
                start_date=start_date,
                end_date=end_date,
                auction_type=auction_type,
                condition=item_condition,
                condition_description=condition_description,
            )

            SealedBidDetail.objects.create(
                auction=auction_obj,
                winner_selection_date=winner_selection_date,
            )

            images = request.FILES.getlist('sealed_bid_images')
            _save_auction_images(auction_obj, images)

            UserActivity.objects.create(user_id=user_id, description="Created a Sealed Bid auction.")
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
        # Fetch user's auctions with first image and max bid using ORM
        auctions_qs = Auction.objects.filter(user_id=user_id).annotate(
            first_image=Subquery(
                AuctionImage.objects.filter(auction_id=OuterRef('id')).values('image_path')[:1]
            ),
            max_bid=Max('bid__amount'),
        ).order_by('-created_at')

        auctions = []
        for a in auctions_qs:
            auctions.append({
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "starting_price": float(a.starting_price) if a.starting_price is not None else 0.0,
                "end_date": a.end_date.strftime('%Y-%m-%d %H:%M:%S') if a.end_date else None,
                "buy_it_now_price": float(a.buy_it_now_price) if a.buy_it_now_price is not None else None,
                "is_make_offer_enabled": a.is_make_offer_enabled,
                "type": a.auction_type,
                "status": a.status,
                "image_url": f"/media/auction_images/{a.first_image}" if a.first_image else "/static/images/placeholder.png",
                "current_bid": float(a.max_bid) if a.max_bid is not None else (float(a.starting_price) if a.starting_price is not None else 0.0),
            })
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
        # Get auction IDs where user has placed bids
        bid_auction_ids = Bid.objects.filter(user_id=user_id).values_list('auction_id', flat=True).distinct()

        auctions_qs = Auction.objects.filter(id__in=bid_auction_ids).annotate(
            first_image=Subquery(
                AuctionImage.objects.filter(auction_id=OuterRef('id')).values('image_path')[:1]
            ),
            max_bid=Max('bid__amount'),
            user_bid_count=Count('bid', filter=Q(bid__user_id=user_id)),
        ).order_by('-end_date')

        auctions = []
        for a in auctions_qs:
            auctions.append({
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "starting_price": a.starting_price,
                "end_date": a.end_date,
                "buy_it_now_price": a.buy_it_now_price if a.buy_it_now_price else None,
                "is_make_offer_enabled": a.is_make_offer_enabled,
                "auction_type": a.auction_type,
                "image_url": f"/media/auction_images/{a.first_image}" if a.first_image else "/static/images/placeholder.png",
                "current_bid": a.max_bid if a.max_bid else a.starting_price,
                "bid_count": a.user_bid_count,
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
            # Check ownership using ORM
            try:
                auction_obj = Auction.objects.get(id=auction_id, user_id=user_id)
            except Auction.DoesNotExist:
                logger.debug(f"Auction id {auction_id} not found or user {user_id} not authorized.")
                messages.error(request, "Auction not found or unauthorized.")
                return redirect('my_auc')

            auction_type = auction_obj.auction_type
            bid_count = Bid.objects.filter(auction_id=auction_id).count()
            logger.debug(f"Auction type: {auction_type}, bid_count: {bid_count}")

            # Prevent deletion if there are any bids
            if bid_count > 0:
                logger.debug(f"Auction id {auction_id} has bids, deletion aborted.")
                messages.error(request, "You cannot delete an auction with bids.")
                return redirect('my_auc')

            # Delete related records using ORM
            Watchlist.objects.filter(auction_id=auction_id).delete()
            logger.debug(f"Deleted watchlist records for auction id: {auction_id}")

            if auction_type == "sealed_bid":
                SealedBidDetail.objects.filter(auction_id=auction_id).delete()
                logger.debug(f"Deleted sealed_bid_details for auction id: {auction_id}")

            FundDistribution.objects.filter(auction_id=auction_id).delete()
            logger.debug(f"Deleted fund_distribution for auction id: {auction_id}")

            # Delete seller_payouts before invoices to avoid foreign key constraint
            invoice_ids = Invoice.objects.filter(auction_id=auction_id).values_list('id', flat=True)
            SellerPayout.objects.filter(invoice_id__in=invoice_ids).delete()
            logger.debug(f"Deleted seller_payouts for auction id: {auction_id}")

            Invoice.objects.filter(auction_id=auction_id).delete()
            logger.debug(f"Deleted invoices for auction id: {auction_id}")

            auction_obj.delete()
            logger.debug(f"Deleted auction record for auction id: {auction_id}")

            # Log activity
            UserActivity.objects.create(
                user_id=user_id,
                description=f"Deleted {auction_type} auction #{auction_id}"
            )
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

    # Fetch the auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        raise Http404("Auction not found.")

    # Map auction data
    auction_data = {
        'id': auction_obj.id,
        'title': auction_obj.title,
        'description': auction_obj.description,
        'category': auction_obj.category,
        'starting_price': auction_obj.starting_price,
        'bid_increment': auction_obj.bid_increment,
        'reserve_price': auction_obj.reserve_price,
        'auction_type': auction_obj.auction_type,
        'buy_it_now_price': auction_obj.buy_it_now_price,
        'user_id': auction_obj.user_id,
    }

    # Ensure only the owner can edit
    if auction_data['user_id'] != user_id:
        return redirect('home')

    # Fetch winner selection date from sealed bid details (if applicable) using ORM
    winner_selection_date = None
    if auction_data['auction_type'] == 'sealed':
        sealed_detail = SealedBidDetail.objects.filter(auction_id=auction_id).first()
        if sealed_detail:
            winner_selection_date = sealed_detail.winner_selection_date

    # Fetch auction images using ORM
    auction_images = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True)
    auction_image_paths = [f"/media/auction_images/{img}" for img in auction_images]

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

        # Update auction details using ORM
        auction_obj.title = title
        auction_obj.description = description
        auction_obj.starting_price = starting_price
        auction_obj.bid_increment = bid_increment
        auction_obj.reserve_price = reserve_price
        auction_obj.buy_it_now_price = buy_now_price
        auction_obj.save(update_fields=[
            'title', 'description', 'starting_price', 'bid_increment',
            'reserve_price', 'buy_it_now_price'
        ])

        # Update winner selection date if auction is sealed
        if auction_data['auction_type'] == 'sealed' and winner_selection_date:
            SealedBidDetail.objects.filter(auction_id=auction_id).update(
                winner_selection_date=winner_selection_date
            )

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

                # Store image in the database using ORM
                AuctionImage.objects.create(auction_id=auction_id, image_path=file_name)

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
        with transaction.atomic():
            # Fetch auction details using ORM
            try:
                auction_obj = Auction.objects.get(id=auction_id)
            except Auction.DoesNotExist:
                messages.error(request, "Auction not found.")
                return redirect('my_auc')

            if auction_obj.user_id != user_id:
                messages.error(request, "You are not authorized to relist this auction.")
                return redirect('my_auc')

            # Calculate a new end date (for testing, extend by 1 day; adjust as needed for production)
            new_end_date = timezone.now() + timedelta(days=1)
            logger.debug(f"Relisting auction {auction_id}: new end date set to {new_end_date}")

            # Update the auction using ORM
            auction_obj.winner_user_id = None
            auction_obj.end_date = new_end_date
            auction_obj.is_relisted = True
            auction_obj.checked = False
            auction_obj.status = 'active'
            auction_obj.current_bid = auction_obj.starting_price
            auction_obj.save(update_fields=[
                'winner_user_id', 'end_date', 'is_relisted', 'checked',
                'status', 'current_bid'
            ])
            logger.info(f"Auction {auction_id} relisted by seller {user_id}")

            # Mark any second-winner offers as expired
            Offer.objects.filter(auction_id=auction_id, second_winner_offer=True).update(status='expired')
            logger.info(f"Marked second-winner offers as expired for auction {auction_id}")

            # Delete all previous bids for this auction
            Bid.objects.filter(auction_id=auction_id).delete()
            logger.info(f"Deleted all bids for auction {auction_id}")

            # Delete the associated invoice for this auction
            Invoice.objects.filter(auction_id=auction_id).delete()
            logger.info(f"Deleted invoice(s) for auction {auction_id}")

            # Delete the associated order for this auction
            Order.objects.filter(auction_id=auction_id).delete()
            logger.info(f"Deleted orders for auction {auction_id}")

            # Fetch seller details to send notification using ORM
            try:
                seller_obj = User.objects.get(id=auction_obj.user_id)
                email_subject = "Auction Relisted Successfully"
                email_body = (
                    f"Dear {seller_obj.username},\n\n"
                    f"Your auction (ID: {auction_id}) has been successfully relisted. "
                    f"The new end date is {new_end_date.strftime('%Y-%m-%d %H:%M:%S')}.\n\n"
                    "All previous bids, invoices, and orders for this auction have been removed, "
                    "and the auction has been reset for further bidding.\n\n"
                    "Thank you,\nAuction Platform Team"
                )
                send_email_notification(seller_obj.email, email_subject, email_body)
                logger.info(f"Sent relisting email to seller {seller_obj.email} for auction {auction_id}")
            except User.DoesNotExist:
                logger.warning(f"Seller details not found for seller_id {auction_obj.user_id}")

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

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        raise Http404("Auction not found.")

    # Ensure the auction belongs to the logged-in seller
    if auction_obj.user_id != user_id:
        raise Http404("You do not have permission to view this auction.")

    # Get first image
    first_image = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True).first()

    # Organize fetched auction data
    auction_data = {
        'id': auction_obj.id,
        'title': auction_obj.title,
        'description': auction_obj.description,
        'category': auction_obj.category,
        'starting_price': auction_obj.starting_price,
        'current_bid': auction_obj.current_bid,
        'bid_increment': auction_obj.bid_increment,
        'reserve_price': auction_obj.reserve_price,
        'start_date': auction_obj.start_date,
        'end_date': auction_obj.end_date,
        'user_id': auction_obj.user_id,
        'auction_type': auction_obj.auction_type,
        'winner_user_id': auction_obj.winner_user_id,
        'image_url': f"/media/auction_images/{first_image}" if first_image else "/static/images/placeholder.png",
        'buy_it_now_price': auction_obj.buy_it_now_price,
        'is_make_offer_enabled': auction_obj.is_make_offer_enabled,
        'status': auction_obj.status,
        'updated_at': auction_obj.updated_at,
    }

    # Fetch seller details using ORM
    try:
        seller_user = User.objects.get(id=user_id)
        auction_data['user'] = {
            'username': seller_user.username,
            'email': seller_user.email,
        }
    except User.DoesNotExist:
        auction_data['user'] = {'username': "Unknown User", 'email': "No Email"}

    # Initialize winner details
    winner = None
    winner_available = False

    # Check if the auction has ended and has a winner
    if datetime.now() > auction_data['end_date'] and auction_data.get('winner_user_id'):
        winner_available = True
        try:
            winner_user = User.objects.get(id=auction_data['winner_user_id'])
            winner = {
                'user_id': auction_data['winner_user_id'],
                'username': winner_user.username,
                'email': winner_user.email,
                'final_price': auction_data['current_bid']
            }
        except User.DoesNotExist:
            pass

    auction_data['winner'] = winner
    auction_data['winner_available'] = winner_available

    # Fetch last bid using ORM
    last_bid = Bid.objects.filter(auction_id=auction_data['id']).order_by('-created_at').first()
    auction_data['current_bid'] = last_bid.amount if last_bid else auction_data['starting_price']

    # Fetch all images for the auction using ORM
    images = AuctionImage.objects.filter(auction_id=auction_data['id']).values_list('image_path', flat=True)
    auction_data['images'] = [f"/media/auction_images/{img}" for img in images]

    # Fetch winner selection date for sealed bid auctions
    if auction_data['auction_type'] == 'sealed_bid':
        sealed_detail = SealedBidDetail.objects.filter(auction_id=auction_data['id']).first()
        if sealed_detail:
            auction_data['sealed_bid_details'] = {'winner_selection_date': sealed_detail.winner_selection_date}

        # Fetch winner details for sealed bid
        if auction_data.get('winner_user_id'):
            try:
                sealed_winner = User.objects.get(id=auction_data['winner_user_id'])
                auction_data['winner'] = {
                    'user_id': auction_data['winner_user_id'],
                    'username': sealed_winner.username,
                    'email': sealed_winner.email,
                }
                auction_data['winner_available'] = True
            except User.DoesNotExist:
                pass

    # Fetch bid history using ORM
    bids_qs = Bid.objects.filter(auction_id=auction_data['id']).select_related('user').order_by('-created_at')
    auction_data['bid_history'] = [
        {
            'amount': bid.amount,
            'created_at': bid.created_at,
            'bidder_username': bid.user.username if bid.user else 'Unknown',
            'bidder_email': bid.user.email if bid.user else 'Unknown',
        }
        for bid in bids_qs
    ]

    # Determine if the "Relist Auction" button should be available using ORM
    pending_offer_count = Offer.objects.filter(
        auction_id=auction_id, second_winner_offer=True, status='pending'
    ).count()

    rejected_or_expired_offer_count = Offer.objects.filter(
        auction_id=auction_id, second_winner_offer=True, status__in=['rejected', 'expired']
    ).count()
    relist_offer_condition = rejected_or_expired_offer_count > 0

    # Check for second highest bid
    second_bid = Bid.objects.filter(auction_id=auction_id).order_by('-amount').values_list('amount', flat=True)
    second_bid_amount = second_bid[1] if len(second_bid) > 1 else None

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

    # Fetch bids with related auction data using ORM
    bids_qs = Bid.objects.filter(user_id=user_id).select_related('auction').order_by('-auction_id', '-bid_time')

    # Build rows compatible with the existing processing logic
    rows = []
    for bid in bids_qs:
        rows.append({
            'auction_id': bid.auction_id,
            'auction_title': bid.auction.title,
            'bid_amount': bid.amount,
            'bid_time': bid.bid_time,
            'current_bid': bid.auction.current_bid,
            'reserve_price': bid.auction.reserve_price,
            'end_date': bid.auction.end_date,
            'winner_user_id': bid.auction.winner_user_id,
        })

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
        auction_id = row['auction_id']
        auction = auctions[auction_id]

        # Set auction details if not already set
        if not auction['auction_id']:
            auction['auction_id'] = row['auction_id']
            auction['auction_title'] = row['auction_title']
            auction['current_bid'] = row['current_bid']
            auction['reserve_price'] = row['reserve_price']
            auction['end_date'] = row['end_date']
            auction['winner_user_id'] = row['winner_user_id']

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
        bid_amount = row['bid_amount']
        if bid_amount > auction['user_max_bid']:
            auction['user_max_bid'] = bid_amount

        # Ensure bid_time is timezone-aware
        bid_time = row['bid_time']
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
    # Update is_winner using ORM - Note: this references a bidding_history table
    from django.db import connection as raw_connection
    with raw_connection.cursor() as cursor:
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

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        print("DEBUG: No auction found for auction_id =", auction_id)
        messages.error(request, "Auction not found.")
        return redirect('auct_list')

    # Get first image
    first_image = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True).first()

    auction_data = {
        'id': auction_obj.id,
        'title': auction_obj.title,
        'description': auction_obj.description,
        'condition': auction_obj.condition,
        'condition_description': auction_obj.condition_description,
        'category': auction_obj.category,
        'buy_it_now_price': auction_obj.buy_it_now_price,
        'seller_id': auction_obj.user_id,
        'status': auction_obj.status,
        'start_date': auction_obj.start_date,
        'end_date': auction_obj.end_date,
        'image_url': f"/media/auction_images/{first_image}" if first_image else "/static/images/placeholder.png",
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

        # Insert offer using ORM
        print("DEBUG: Inserting offer into offers table")
        Offer.objects.create(
            auction_id=auction_id,
            buyer_id=buyer_id,
            offer_price=offer_price,
            offer_message=request.POST.get('offer_message', ''),
            status='pending',
        )
        print("DEBUG: Offer inserted successfully")
        messages.success(request, "Your offer has been submitted.")

        # Notify seller using ORM
        try:
            seller = User.objects.get(id=auction_data['seller_id'])
            seller_email = seller.email
        except User.DoesNotExist:
            seller_email = None
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

    # Received Offers: Offers where the current user is the seller, excluding second winner offers.
    received_qs = Offer.objects.filter(
        auction__user_id=user_id, second_winner_offer=False
    ).select_related('auction', 'buyer').annotate(
        accepted_count=Count(
            'auction__offer',
            filter=Q(auction__offer__status='accepted')
        )
    ).order_by('-created_at')

    for o in received_qs:
        offer = {
            "offer_id": o.id,
            "auction_id": o.auction_id,
            "offer_price": float(o.offer_price),
            "offer_message": o.offer_message,
            "status": o.status,
            "created_at": o.created_at,
            "auction_title": o.auction.title,
            "buy_it_now_price": o.auction.buy_it_now_price,
            "buyer_id": o.buyer_id,
            "buyer_username": o.buyer.username if o.buyer else 'Unknown',
            "buyer_email": o.buyer.email if o.buyer else 'Unknown',
            "accepted_count": o.accepted_count,
        }
        received_offers.append(offer)
        logger.debug(f"view_offers - Received offer mapped: {offer}")

    # Sent Offers: Offers submitted by the current user, excluding second winner offers.
    sent_qs = Offer.objects.filter(
        buyer_id=user_id, second_winner_offer=False
    ).select_related('auction', 'auction__user').order_by('-created_at')

    for o in sent_qs:
        seller = o.auction.user if hasattr(o.auction, 'user') else None
        offer = {
            "offer_id": o.id,
            "auction_id": o.auction_id,
            "offer_price": float(o.offer_price),
            "offer_message": o.offer_message,
            "status": o.status,
            "created_at": o.created_at,
            "auction_title": o.auction.title,
            "buy_it_now_price": o.auction.buy_it_now_price,
            "seller_id": o.auction.user_id,
            "seller_username": seller.username if seller else 'Unknown',
            "seller_email": seller.email if seller else 'Unknown',
        }
        sent_offers.append(offer)
        logger.debug(f"view_offers - Sent offer mapped: {offer}")

    # Auction Offers: Offers on 'regular' or 'sealed_bid' auctions, including second winner offers for the buyer.
    auction_offers_qs = Offer.objects.filter(
        auction__auction_type__in=['regular', 'sealed_bid']
    ).filter(
        Q(second_winner_offer=False) | Q(second_winner_offer=True, buyer_id=user_id)
    ).select_related('auction', 'buyer').annotate(
        accepted_count=Count(
            'auction__offer',
            filter=Q(auction__offer__status='accepted')
        )
    ).order_by('-created_at')

    for o in auction_offers_qs:
        offer = {
            "offer_id": o.id,
            "auction_id": o.auction_id,
            "offer_price": float(o.offer_price),
            "offer_message": o.offer_message,
            "status": o.status,
            "created_at": o.created_at,
            "auction_title": o.auction.title,
            "buy_it_now_price": o.auction.buy_it_now_price,
            "auction_type": o.auction.auction_type,
            "buyer_username": o.buyer.username if o.buyer else 'Unknown',
            "buyer_email": o.buyer.email if o.buyer else 'Unknown',
            "accepted_count": o.accepted_count,
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

        # Fetch auction details using ORM
        try:
            auction_obj = Auction.objects.get(id=auction_id)
        except Auction.DoesNotExist:
            messages.error(request, "Auction not found.")
            logger.error(f"❌ ERROR: Auction ID {auction_id} not found.")
            return redirect('view_offers')

        seller_id = auction_obj.user_id
        auction_type = auction_obj.auction_type
        print(f"✅ DEBUG: Auction Type: {auction_type}, Seller ID: {seller_id}")

        # Allow action only for Buy It Now auctions.
        if auction_type.lower() != "buy_it_now":
            messages.error(request, "This action is only available for Buy It Now auctions.")
            logger.error(f"❌ ERROR: Auction type is '{auction_type}', not Buy It Now.")
            return redirect('view_offers')

        # Verify offer exists and is pending using ORM
        try:
            offer_obj = Offer.objects.get(id=offer_id, auction_id=auction_id)
        except Offer.DoesNotExist:
            messages.error(request, "Offer not found or not pending.")
            logger.error(f"❌ ERROR: Offer {offer_id} not found.")
            return redirect('view_offers')

        print(f"✅ DEBUG: Offer Query Result: status={offer_obj.status}, buyer_id={offer_obj.buyer_id}")

        if offer_obj.status != 'pending':
            messages.error(request, "Offer not found or not pending.")
            logger.error(f"❌ ERROR: Offer {offer_id} status is {offer_obj.status}.")
            return redirect('view_offers')

        offer_buyer_id = offer_obj.buyer_id

        # Verify that the logged-in user is the seller.
        if auction_obj.user_id != seller_id:
            messages.error(request, "You are not authorized to accept this offer.")
            logger.error(f"❌ ERROR: User {user_id} not authorized for auction {auction_id}.")
            return redirect('view_offers')

        # For Buy It Now auctions, update the offer status to accepted using ORM.
        offer_obj.status = 'accepted'
        offer_obj.save(update_fields=['status'])
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

        # Fetch auction details using ORM
        try:
            auction_obj = Auction.objects.get(id=auction_id)
        except Auction.DoesNotExist:
            messages.error(request, "Auction not found.")
            return redirect('view_offers')
        auction_type = auction_obj.auction_type
        print(f"✅ DEBUG: Auction Type: {auction_type}")

        # Allow action only for Buy It Now auctions.
        if auction_type.lower() != "buy_it_now":
            messages.error(request, "This action is only available for Buy It Now auctions.")
            logger.error(f"❌ ERROR: Auction type is '{auction_type}', not Buy It Now.")
            return redirect('view_offers')

        # Verify the offer exists and is pending using ORM
        try:
            offer_obj = Offer.objects.get(id=offer_id, auction_id=auction_id)
        except Offer.DoesNotExist:
            messages.error(request, "Offer not found or not pending.")
            logger.warning(f"reject_offer - Offer {offer_id} not found.")
            return redirect('view_offers')

        print(f"✅ DEBUG: Offer Query Result: status={offer_obj.status}")
        if offer_obj.status != 'pending':
            messages.error(request, "Offer not found or not pending.")
            logger.warning(f"reject_offer - Offer {offer_id} status is {offer_obj.status}.")
            return redirect('view_offers')

        # Verify that the logged-in user is the seller.
        if auction_obj.user_id != seller_id:
            messages.error(request, "You are not authorized to reject this offer.")
            logger.warning(f"reject_offer - User {seller_id} not authorized for auction {auction_id}.")
            return redirect('view_offers')

        # For Buy It Now auctions, update the offer status to rejected using ORM
        offer_obj.status = 'rejected'
        offer_obj.save(update_fields=['status'])
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

        # Verify the offer using ORM
        try:
            offer_obj = Offer.objects.get(id=offer_id)
        except Offer.DoesNotExist:
            messages.error(request, "Offer not found.")
            logger.error(f"Offer ID {offer_id} not found.")
            return redirect('view_offers')

        auction_id = offer_obj.auction_id
        buyer_id = offer_obj.buyer_id
        status = offer_obj.status
        is_second_winner = offer_obj.second_winner_offer
        logger.debug(f"Offer details - auction_id: {auction_id}, buyer_id: {buyer_id}, status: {status}, is_second_winner: {is_second_winner}")

        # Check conditions
        if status != 'pending':
            messages.error(request, "This offer is not pending.")
            logger.error(f"Offer {offer_id} status is {status}, not pending.")
            return redirect('view_offers')
        if not is_second_winner:
            messages.error(request, "This is not a second winner offer.")
            logger.error(f"Offer {offer_id} is not a second winner offer.")
            return redirect('view_offers')
        if buyer_id != user_id:
            messages.error(request, "You are not authorized to accept this offer.")
            logger.error(f"User {user_id} not authorized to accept offer {offer_id} (buyer_id: {buyer_id}).")
            return redirect('view_offers')

        # Fetch buyer and seller emails using ORM
        try:
            buyer_user = User.objects.get(id=user_id)
            buyer_email = buyer_user.email
        except User.DoesNotExist:
            buyer_email = None
        logger.debug(f"Buyer email for user_id {user_id}: {buyer_email}")

        try:
            auction_obj = Auction.objects.select_related('user').get(id=auction_id)
            seller_id = auction_obj.user_id
            seller_user = User.objects.get(id=seller_id)
            seller_email = seller_user.email
        except (Auction.DoesNotExist, User.DoesNotExist):
            seller_id, seller_email = None, None
        logger.debug(f"Seller details for auction_id {auction_id}: seller_id={seller_id}, seller_email={seller_email}")

        # Debug: Log before performing updates
        logger.debug(f"Preparing to update tables for offer_id {offer_id}")

        # Perform updates in a transaction using ORM
        with transaction.atomic():
            # Update offers table
            offer_obj.status = 'accepted'
            offer_obj.save(update_fields=['status'])
            logger.debug(f"Updated offers table: status set to 'accepted' for offer_id {offer_id}")

            # Update auctions table
            Auction.objects.filter(id=auction_id).update(winner_user_id=user_id)
            logger.debug(f"Updated auctions table: winner_user_id set to {user_id} for auction_id {auction_id}")

            # Update invoices table
            Invoice.objects.filter(auction_id=auction_id).update(
                buyer_id=user_id,
                status='pending',
                late_fee=0,
                issue_date=timezone.now(),
                due_date=timezone.now() + timedelta(days=2),
            )
            logger.debug(f"Updated invoices table: buyer_id={user_id}, status='pending' for auction_id {auction_id}")

            # Update orders table and fetch order_id
            order_obj = Order.objects.filter(auction_id=auction_id).first()
            if order_obj:
                order_obj.user_id = user_id
                order_obj.shipping_address = None
                order_obj.save(update_fields=['user_id', 'shipping_address'])
                order_id = order_obj.id
                logger.debug(f"Updated orders table: user_id set to {user_id}, order_id={order_id} for auction_id {auction_id}")

                # Delete shipping details for the order_id
                ShippingDetail.objects.filter(order_id=order_id).delete()
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

        # Verify the offer using ORM
        try:
            offer_obj = Offer.objects.get(id=offer_id)
        except Offer.DoesNotExist:
            messages.error(request, "Offer not found.")
            logger.error(f"Offer ID {offer_id} not found.")
            return redirect('view_offers')

        auction_id = offer_obj.auction_id
        buyer_id = offer_obj.buyer_id
        status = offer_obj.status
        is_second_winner = offer_obj.second_winner_offer
        logger.debug(f"Offer details - auction_id: {auction_id}, buyer_id: {buyer_id}, status: {status}, is_second_winner: {is_second_winner}")

        # Check conditions
        if status != 'pending':
            messages.error(request, "This offer is not pending.")
            logger.error(f"Offer {offer_id} status is {status}, not pending.")
            return redirect('view_offers')
        if not is_second_winner:
            messages.error(request, "This is not a second winner offer.")
            logger.error(f"Offer {offer_id} is not a second winner offer.")
            return redirect('view_offers')
        if buyer_id != user_id:
            messages.error(request, "You are not authorized to reject this offer.")
            logger.error(f"User {user_id} not authorized to reject offer {offer_id} (buyer_id: {buyer_id}).")
            return redirect('view_offers')

        # Fetch buyer and seller emails using ORM
        try:
            buyer_user = User.objects.get(id=user_id)
            buyer_email = buyer_user.email
        except User.DoesNotExist:
            buyer_email = None
        logger.debug(f"Buyer email for user_id {user_id}: {buyer_email}")

        try:
            auction_obj = Auction.objects.get(id=auction_id)
            seller_user = User.objects.get(id=auction_obj.user_id)
            seller_id = seller_user.id
            seller_email = seller_user.email
        except (Auction.DoesNotExist, User.DoesNotExist):
            seller_id, seller_email = None, None
        logger.debug(f"Seller details for auction_id {auction_id}: seller_id={seller_id}, seller_email={seller_email}")

        # Debug: Log before performing update
        logger.debug(f"Preparing to update offers table for offer_id {offer_id}")

        # Update offers table using ORM
        offer_obj.status = 'rejected'
        offer_obj.save(update_fields=['status'])
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

    # Fetch offer details using ORM
    try:
        offer_obj = Offer.objects.get(id=offer_id)
    except Offer.DoesNotExist:
        messages.error(request, "Offer not found.")
        return redirect('view_offers')

    auction_id = offer_obj.auction_id
    offer_price = offer_obj.offer_price
    offer_status = offer_obj.status
    print("DEBUG: Offer details fetched:", offer_obj.id, auction_id, offer_price, offer_status)

    # Ensure the offer is accepted before proceeding
    if offer_status != 'accepted':
        messages.error(request, "Offer is not accepted; cannot proceed to checkout.")
        return redirect('view_offers')

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id, auction_type='buy_it_now')
    except Auction.DoesNotExist:
        messages.error(request, "Auction not found.")
        return redirect('auct_list')
    print("DEBUG: Auction details fetched:", auction_obj.id, auction_obj.title)

    # Prepare item data for the payment page
    # Override the auction price with the accepted offer price.
    item = {
        "id": auction_obj.id,
        "title": auction_obj.title,
        "description": auction_obj.description,
        "condition": auction_obj.condition,
        "condition_description": auction_obj.condition_description,
        "category": auction_obj.category,
        "price": float(offer_price),
        "seller_id": auction_obj.user_id,
        "image_url": None,
    }

    # Fetch auction image using ORM
    first_image = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True).first()
    if first_image:
        item["image_url"] = f"/media/auction_images/{first_image}"
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

    # Fetch offer details using ORM
    try:
        offer_obj = Offer.objects.select_related('auction').get(id=offer_id)
        print("DEBUG: Offer fetched:", offer_obj.id, offer_obj.auction_id, offer_obj.offer_price, offer_obj.status)
    except Offer.DoesNotExist:
        print("DEBUG: Offer not found for offer_id:", offer_id)
        messages.error(request, "Invalid or unavailable offer.")
        return redirect('auct_list')
    except Exception as ex:
        print("DEBUG: Error fetching offer details")
        traceback.print_exc()
        messages.error(request, "Error fetching offer details.")
        return redirect('auct_list')

    auction_id = offer_obj.auction_id
    buyer_id = offer_obj.buyer_id
    offer_price = offer_obj.offer_price
    offer_message = offer_obj.offer_message
    offer_status = offer_obj.status
    second_winner_offer = offer_obj.second_winner_offer
    auction_title = offer_obj.auction.title if offer_obj.auction else None

    if offer_status != 'accepted' or not second_winner_offer:
        print("DEBUG: Offer invalid: status =", offer_status, ", second_winner_offer =", second_winner_offer)
        messages.error(request, "Invalid or unavailable offer.")
        return redirect('auct_list')

    if buyer_id != user_id:
        print("DEBUG: User_id does not match offer buyer_id:", user_id, buyer_id)
        messages.error(request, "You are not authorized to complete this offer.")
        return redirect('auct_list')

    # Fetch auction details using ORM
    auction = None
    try:
        auction_obj_detail = Auction.objects.get(id=auction_id)
        auction = auction_obj_detail
        print("DEBUG: Auction fetched:", auction.id, auction.title)
    except Auction.DoesNotExist:
        print("DEBUG: Auction not found for auction_id:", auction_id)
    except Exception as ex:
        print("DEBUG: Error fetching auction details")
        traceback.print_exc()

    # Fetch auction image using ORM
    image_url = None
    try:
        first_image = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True).first()
        if first_image:
            if first_image.startswith("/media/"):
                image_url = first_image
            else:
                image_url = f"/media/auction_images/{first_image}"
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
            "id": auction.id,
            "title": auction.title,
            "description": auction.description,
            "condition": auction.condition,
            "condition_description": auction.condition_description,
            "category": auction.category,
            "price": float(offer_price),
            "seller_id": auction.user_id,
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
                    # Check for existing invoice using ORM
                    print("DEBUG: Checking for existing invoice for auction_id:", auction_id, "buyer_id:", user_id)
                    existing_invoice = Invoice.objects.filter(
                        auction_id=auction_id, buyer_id=user_id, status__in=['Pending', 'Overdue']
                    ).first()
                    print("DEBUG: Existing invoice:", existing_invoice)

                    issue_date = timezone.now()
                    due_date = issue_date
                    invoice_id = None

                    if existing_invoice:
                        # Update existing invoice
                        invoice_id = existing_invoice.id
                        print("DEBUG: Updating existing invoice with id:", invoice_id)
                        existing_invoice.amount_due = float(item["total_amount"])
                        existing_invoice.issue_date = issue_date
                        existing_invoice.due_date = due_date
                        existing_invoice.status = 'Pending'
                        existing_invoice.save(update_fields=['amount_due', 'issue_date', 'due_date', 'status'])
                        print("DEBUG: Invoice updated successfully")
                    else:
                        # Create new invoice using ORM
                        invoice_id = uuid4().hex[:16]
                        print("DEBUG: Creating new invoice with id:", invoice_id)
                        Invoice.objects.create(
                            id=invoice_id,
                            auction_id=auction_id,
                            buyer_id=user_id,
                            seller_id=item["seller_id"],
                            amount_due=float(item["total_amount"]),
                            issue_date=issue_date,
                            due_date=due_date,
                            status='Pending',
                        )
                        print("DEBUG: Invoice created successfully")

                    # Process payment
                    transaction_id = uuid4().hex[:16]
                    payment_date = timezone.now()
                    payment_amount = float(item["total_amount"])
                    print("DEBUG: Processing payment. Transaction ID:", transaction_id)

                    # Create payment details using ORM
                    payment_kwargs = {
                        'user_id': user_id,
                        'invoice_id': invoice_id,
                        'auction_id': auction_id,
                        'payment_method': payment_method,
                        'payment_status': 'Completed',
                        'transaction_id': transaction_id,
                        'payment_amount': payment_amount,
                        'payment_date': payment_date,
                    }
                    if payment_method == "credit_card":
                        print("DEBUG: Inserting credit card payment details")
                        payment_kwargs['credit_card_number'] = request.POST.get("card_number")
                    elif payment_method == "paypal":
                        print("DEBUG: Inserting PayPal payment details")
                        payment_kwargs['paypal_email'] = request.POST.get("paypal_email")
                    elif payment_method == "bank_transfer":
                        print("DEBUG: Inserting bank transfer payment details")
                        payment_kwargs['bank_account_number'] = request.POST.get("iban")
                        payment_kwargs['bank_routing_number'] = request.POST.get("bic")
                    else:
                        raise ValueError("Invalid payment method selected")

                    PaymentDetail.objects.create(**payment_kwargs)
                    print("DEBUG: Payment details inserted successfully")

                    # Update invoice status to 'Paid' using ORM
                    print("DEBUG: Updating invoice status to 'Paid'")
                    Invoice.objects.filter(id=invoice_id).update(status='Paid')

                    # Confirm offer status as 'accepted' using ORM
                    print("DEBUG: Confirming offer status as 'accepted'")
                    Offer.objects.filter(id=offer_id).update(status='accepted')

                    # Fetch commission percentage using ORM
                    print("DEBUG: Fetching commission percentage")
                    commission_obj = PlatformCommission.objects.filter(
                        auction_type='standard'
                    ).order_by('-effective_date').first()
                    commission_percentage = float(commission_obj.commission_percentage) if commission_obj else 5.00
                    print("DEBUG: Commission percentage:", commission_percentage)

                    # Calculate fund distribution amounts
                    platform_share = (commission_percentage / 100) * payment_amount
                    seller_share = payment_amount - platform_share
                    print("DEBUG: Platform share:", platform_share, "Seller share:", seller_share)

                    FundDistribution.objects.create(
                        invoice_id=invoice_id,
                        auction_id=auction_id,
                        seller_id=item["seller_id"],
                        platform_share=platform_share,
                        seller_share=seller_share,
                        status='Pending',
                        distribution_date=payment_date,
                    )
                    print("DEBUG: Fund distribution record inserted")

                    # Check for existing order using ORM
                    print("DEBUG: Checking for existing order for auction_id:", auction_id, "user_id:", user_id, "invoice_id:", invoice_id)
                    existing_order = Order.objects.filter(
                        auction_id=auction_id, user_id=user_id, invoice_id=invoice_id
                    ).first()
                    print("DEBUG: Existing order:", existing_order)

                    tracking_id = uuid4().hex[:16]
                    order_id = None

                    if existing_order:
                        # Update existing order
                        order_id = existing_order.id
                        print("DEBUG: Updating existing order with id:", order_id)
                        existing_order.payment_status = 'paid'
                        existing_order.payment_amount = payment_amount
                        existing_order.shipping_status = 'processing'
                        existing_order.tracking_number = tracking_id
                        existing_order.order_date = payment_date
                        existing_order.order_status = 'Confirmed'
                        existing_order.progress = 30
                        existing_order.save(update_fields=[
                            'payment_status', 'payment_amount', 'shipping_status',
                            'tracking_number', 'order_date', 'order_status', 'progress'
                        ])
                        print("DEBUG: Order updated successfully")
                    else:
                        # Create new order using ORM
                        print("DEBUG: Inserting new order with tracking id:", tracking_id)
                        new_order = Order.objects.create(
                            auction_id=auction_id,
                            user_id=user_id,
                            invoice_id=invoice_id,
                            payment_status='paid',
                            payment_amount=payment_amount,
                            shipping_status='processing',
                            tracking_number=tracking_id,
                            order_date=payment_date,
                            order_status='Confirmed',
                            progress=30,
                        )
                        order_id = new_order.id
                        print("DEBUG: Order inserted with order_id:", order_id)

                    # Insert or update shipping details using ORM
                    print("DEBUG: Checking for existing shipping details for order_id:", order_id)
                    existing_shipping = ShippingDetail.objects.filter(
                        order_id=order_id, invoice_id=invoice_id
                    ).first()

                    if existing_shipping:
                        # Update existing shipping details
                        print("DEBUG: Updating existing shipping details for order_id:", order_id)
                        existing_shipping.full_name = full_name
                        existing_shipping.phone = phone
                        existing_shipping.address = address
                        existing_shipping.city = city
                        existing_shipping.state = state
                        existing_shipping.zip_code = zip_code
                        existing_shipping.country = country
                        existing_shipping.shipping_date = payment_date
                        existing_shipping.save(update_fields=[
                            'full_name', 'phone', 'address', 'city', 'state',
                            'zip_code', 'country', 'shipping_date'
                        ])
                        print("DEBUG: Shipping details updated successfully")
                    else:
                        # Insert new shipping details using ORM
                        print("DEBUG: Inserting new shipping details")
                        ShippingDetail.objects.create(
                            order_id=order_id,
                            invoice_id=invoice_id,
                            buyer_id=user_id,
                            full_name=full_name,
                            phone=phone,
                            address=address,
                            city=city,
                            state=state,
                            zip_code=zip_code,
                            country=country,
                            shipping_date=payment_date,
                        )
                        print("DEBUG: Shipping details inserted successfully")

                    # Notify seller using ORM
                    print("DEBUG: Notifying seller")
                    try:
                        seller_user = User.objects.get(id=item["seller_id"])
                        seller_email = seller_user.email
                    except User.DoesNotExist:
                        seller_email = None
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
    two_hours_ago = timezone.now() - timedelta(hours=2)

    try:
        # Build base queryset using ORM with annotations
        qs = Auction.objects.filter(
            end_date__gte=two_hours_ago,
            status__in=['active', 'Active'],  # Exclude stopped auctions
        ).exclude(
            user_id=logged_in_user_id or -1
        ).exclude(
            status='stopped'
        ).annotate(
            first_image=Subquery(
                AuctionImage.objects.filter(auction_id=OuterRef('id')).values('image_path')[:1]
            ),
            max_bid=Max('bid__amount'),
        ).select_related('user')

        # Apply dynamic filters
        if category_filter:
            qs = qs.filter(category_id=category_filter)
        if price_min:
            qs = qs.filter(starting_price__gte=price_min)
        if price_max:
            qs = qs.filter(starting_price__lte=price_max)
        if search_keywords:
            qs = qs.filter(Q(title__icontains=search_keywords) | Q(description__icontains=search_keywords))

        # Apply ordering
        if ending_soon:
            qs = qs.order_by('end_date', '-user__premium')
        else:
            qs = qs.order_by('-user__premium', '-id')

        auctions = []
        current_time = timezone.now()
        for a in qs:
            starting_price = a.starting_price if a.starting_price is not None else 0.0
            current_bid = a.max_bid if a.max_bid is not None else starting_price
            end_date = a.end_date
            if timezone.is_naive(end_date):
                end_date = timezone.make_aware(end_date, timezone.get_current_timezone())

            auction = {
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "starting_price": float(starting_price),
                "end_date": end_date,
                "user_id": a.user_id,
                "buy_it_now_price": float(a.buy_it_now_price) if a.buy_it_now_price is not None else None,
                "is_make_offer_enabled": bool(a.is_make_offer_enabled),
                "auction_type": a.auction_type,
                "image_url": f"/media/auction_images/{a.first_image}" if a.first_image else "/static/images/placeholder.png",
                "current_bid": float(current_bid),
                "is_own_auction": False,  # Auctions created by the user are excluded
                "is_ended": end_date <= current_time,
            }
            auctions.append(auction)
    except Exception as e:
        auctions = []
        messages.error(request, f"Error fetching auctions: {e}")
        print(f"Error fetching auctions: {e}")

    # Fetch categories using ORM
    try:
        categories = list(Category.objects.values('id', 'name'))
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

    # Check if user is restricted using ORM
    try:
        user_obj = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect('login')
    if user_obj.bidding_restricted:
        logger.debug(f"User {user_id} is restricted from bidding.")
        return render(request, 'bidding_restricted.html', {})

    # Determine if user can access proxy bidding (only for premium users with membership_plan_id 2 or 3)
    is_premium_proxy_eligible = user_obj.premium and user_obj.membership_plan_id in [2, 3]

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        logger.error(f"Auction {auction_id} not found.")
        raise Http404("Auction not found.")

    # Validate starting_price, bid_increment, and reserve_price
    if auction_obj.starting_price is None or auction_obj.bid_increment is None or auction_obj.reserve_price is None:
        logger.error(f"Auction {auction_id} has invalid starting_price, bid_increment, or reserve_price.")
        return render(request, 'place_bid.html', {
            'auction': {'id': auction_id},
            'error': "This auction is invalid due to missing pricing information.",
            'is_premium_proxy_eligible': is_premium_proxy_eligible
        })

    auction = {
        "id": auction_obj.id,
        "title": auction_obj.title,
        "description": auction_obj.description,
        "starting_price": float(auction_obj.starting_price),
        "bid_increment": float(auction_obj.bid_increment),
        "end_date": auction_obj.end_date,
        "current_bid": float(auction_obj.current_bid) if auction_obj.current_bid is not None else None,
        "user_id": auction_obj.user_id,  # Seller
        "reserve_price": float(auction_obj.reserve_price),
    }

    # Fetch wallet balance using ORM
    wallet_obj = Wallet.objects.filter(user_id=user_id).first()
    wallet_balance = float(wallet_obj.balance) if wallet_obj else 0.0

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

    # Get current highest bidder using ORM
    highest_bid = Bid.objects.filter(auction_id=auction_id).order_by('-amount').select_related('user').first()
    current_highest_bidder_id = highest_bid.user_id if highest_bid else None
    current_highest_bidder_email = highest_bid.user.email if highest_bid and highest_bid.user else None

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

    # Fetch current user's email and seller's email using ORM
    current_user_email = user_obj.email
    try:
        seller_user = User.objects.get(id=auction["user_id"])
        seller_email = seller_user.email
    except User.DoesNotExist:
        seller_email = None

    if request.method == 'POST':
        bid_amount_str = request.POST.get('bid_amount')
        enable_auto_bid = request.POST.get('enable_auto_bid') == 'on'
        proxy_bid_str = request.POST.get('proxy_bid')

        try:
            # Fetch all existing proxy bids (excluding the current user)
            # Fetch existing proxy bids using ORM
            proxy_bid_qs = Bid.objects.filter(
                auction_id=auction_id, is_proxy=True
            ).exclude(user_id=user_id).select_related('user').order_by('created_at')
            proxy_bids = [(b.user_id, float(b.proxy_max_amount), float(b.amount), b.user.email if b.user else None) for b in proxy_bid_qs]

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

                # Insert new proxy bid using ORM
                Bid.objects.create(
                    auction_id=auction_id, user_id=user_id,
                    amount=new_bid_amount, is_proxy=True, proxy_max_amount=proxy_bid
                )
                # Update auction's current bid using ORM
                Auction.objects.filter(id=auction_id).update(current_bid=new_bid_amount)
                updated_current_bid = new_bid_amount

                # Notify previous highest bidder
                if current_highest_bidder_id and current_highest_bidder_id != user_id:
                    new_bidder_username = user_obj.username
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

                # Insert bids and update auction using ORM
                for bid_user_id, amount, is_proxy, proxy_max, email in bids_to_insert:
                    Bid.objects.create(
                        auction_id=auction_id, user_id=bid_user_id,
                        amount=amount, is_proxy=is_proxy,
                        proxy_max_amount=proxy_max if is_proxy and proxy_max else None
                    )
                Auction.objects.filter(id=auction_id).update(current_bid=latest_bid)
                updated_current_bid = latest_bid

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
                        new_bidder_username = user_obj.username
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
    # Refresh current bid using ORM
    auction_obj.refresh_from_db(fields=['current_bid'])
    refreshed_current_bid = float(auction_obj.current_bid) if auction_obj.current_bid is not None else auction["starting_price"]
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

    # Check for existing bid using ORM
    bid_count = Bid.objects.filter(auction_id=auction_id, user_id=user_id).count()
    if bid_count > 0:
        messages.error(request, "You have already placed a bid for this auction. Only one bid per user is allowed.")
        return render(request, 'place_sealed_bid.html', {
            'auction_id': auction_id,
            'error': "You have already placed a bid for this auction. Only one bid per user is allowed."
        })

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        print(f"[ERROR] Auction {auction_id} not found.")
        messages.error(request, "Auction not found.")
        return redirect('auct_deta', auction_id=auction_id)

    starting_price = float(auction_obj.starting_price) if auction_obj.starting_price is not None else 0.0
    bid_increment = float(auction_obj.bid_increment) if auction_obj.bid_increment is not None else 1.0

    auction = {
        "user_id": auction_obj.user_id,
        "starting_price": starting_price,
        "bid_increment": bid_increment,
        "end_date": auction_obj.end_date,
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

    # Fetch seller's email using ORM
    try:
        seller_user = User.objects.get(id=auction["user_id"])
        seller_email = seller_user.email
    except User.DoesNotExist:
        seller_email = None

    # Calculate minimum bid using ORM
    max_bid_val = Bid.objects.filter(auction_id=auction_id).aggregate(max_amount=Max('amount'))['max_amount']
    current_bid = float(max_bid_val) if max_bid_val is not None else None
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

                # Insert sealed bid using ORM
                Bid.objects.create(
                    auction_id=auction_id,
                    user_id=user_id,
                    amount=amount,
                    is_proxy=False,
                    bid_time=current_timestamp,
                    created_at=current_timestamp,
                )

                # Notify seller
                if seller_email:
                    notification_message = f"A new sealed bid of ${amount:.2f} has been placed on your auction (ID: {auction_id})."
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

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.select_related('user').get(id=auction_id)
    except Auction.DoesNotExist:
        raise Http404("Auction not found.")

    # Get first image
    first_image = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True).first()

    auction_data = {
        'id': auction_obj.id,
        'title': auction_obj.title,
        'description': auction_obj.description,
        'category': auction_obj.category,
        'starting_price': auction_obj.starting_price,
        'current_bid': auction_obj.current_bid,
        'bid_increment': auction_obj.bid_increment,
        'reserve_price': auction_obj.reserve_price,
        'start_date': auction_obj.start_date,
        'end_date': auction_obj.end_date,
        'user_id': auction_obj.user_id,
        'auction_type': auction_obj.auction_type,
        'winner_user_id': auction_obj.winner_user_id,
        'image_url': f"/media/auction_images/{first_image}" if first_image else "/static/images/placeholder.png",
        'buy_it_now_price': auction_obj.buy_it_now_price,
        'is_make_offer_enabled': auction_obj.is_make_offer_enabled,
        'status': auction_obj.status,
        'condition': auction_obj.condition,
        'condition_description': auction_obj.condition_description,
        'views_count': auction_obj.views_count,
        'premium': auction_obj.user.premium if auction_obj.user else False,
    }

    # Debug: Print current_bid to verify
    print(f"Fetching current_bid for auction {auction_id}: {auction_data['current_bid']}")

    # Increment views_count only if the user hasn't viewed this auction before
    if auction_id not in viewed_auctions:
        Auction.objects.filter(id=auction_id).update(views_count=F('views_count') + 1)
        auction_obj.refresh_from_db(fields=['views_count'])
        auction_data['views_count'] = auction_obj.views_count
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
        Auction.objects.filter(id=auction_id).update(status='closed')
        auction_data['status'] = "closed"

    # Fetch seller details using ORM
    try:
        seller = User.objects.get(id=auction_data['user_id'])
        seller_username = seller.username
        seller_email = seller.email
        profile_picture_path = seller.profile_picture or ""
    except User.DoesNotExist:
        seller_username = "Unknown User"
        seller_email = "No Email"
        profile_picture_path = ""

    if profile_picture_path:
        if profile_picture_path.startswith("/") or profile_picture_path.startswith("http"):
            final_profile_picture = profile_picture_path
        else:
            final_profile_picture = f"/media/{profile_picture_path}"
    else:
        final_profile_picture = "/static/images/default_profile.png"

    auction_data['user'] = {
        'username': seller_username,
        'email': seller_email,
        'profile_picture': final_profile_picture,
    }

    # Initialize winner details
    winner = None
    winner_available = False

    if current_time > auction_data['end_date'] and auction_data.get('winner_user_id') and auction_data['status'] == 'closed':
        winner_available = True
        try:
            winner_user = User.objects.get(id=auction_data['winner_user_id'])
            winner_profile = winner_user.profile_picture or ""
            if winner_profile:
                if winner_profile.startswith("/") or winner_profile.startswith("http"):
                    final_winner_profile = winner_profile
                else:
                    final_winner_profile = f"/media/{winner_profile}"
            else:
                final_winner_profile = "/static/images/default_profile.png"
            winner = {
                'user_id': auction_data['winner_user_id'],
                'username': winner_user.username,
                'email': winner_user.email,
                'profile_picture': final_winner_profile,
                'final_price': auction_data['current_bid']
            }
        except User.DoesNotExist:
            pass

    auction_data['winner'] = winner
    auction_data['winner_available'] = winner_available

    # Fetch all images using ORM
    images = AuctionImage.objects.filter(auction_id=auction_data['id']).values_list('image_path', flat=True)
    auction_data['images'] = [f"/media/auction_images/{img}" for img in images if img]

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

    # Insert into the watchlist using ORM (avoid duplicates)
    if not Watchlist.objects.filter(user_id=user_id, auction_id=auction_id).exists():
        try:
            auction_obj = Auction.objects.get(id=auction_id)
            Watchlist.objects.create(
                user_id=user_id,
                auction_id=auction_id,
                auction_type=auction_obj.auction_type,
            )
        except Auction.DoesNotExist:
            pass

    return redirect('watchlist')  # Redirect to the watchlist page

# Display watchlist
def watchlist(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('auth_page')  # Redirect to login if the user is not logged in

    # Fetch watchlist items using ORM with annotations
    watchlist_qs = Watchlist.objects.filter(user_id=user_id).select_related('auction')
    current_time = timezone.now()

    watchlist_items = []
    for w in watchlist_qs.order_by('-auction__end_date'):
        a = w.auction
        if not a:
            continue
        first_image = AuctionImage.objects.filter(auction_id=a.id).values_list('image_path', flat=True).first()
        end_date = a.end_date
        if end_date and timezone.is_naive(end_date):
            end_date = timezone.make_aware(end_date, timezone.get_current_timezone())
        auction_status = 'Expired' if (end_date and end_date < current_time) else 'Active'

        auction_data = {
            'id': a.id,
            'title': a.title,
            'description': a.description,
            'category': a.category,
            'starting_price': a.starting_price,
            'current_bid': a.current_bid,
            'bid_increment': a.bid_increment,
            'reserve_price': a.reserve_price,
            'start_date': a.start_date,
            'end_date': end_date,
            'user_id': a.user_id,
            'auction_type': a.auction_type,
            'winner_user_id': a.winner_user_id,
            'image_url': f"/media/auction_images/{first_image}" if first_image else "/static/images/placeholder.png",
            'buy_it_now_price': a.buy_it_now_price,
            'is_make_offer_enabled': a.is_make_offer_enabled,
            'status': a.status,
            'condition': a.condition,
            'condition_description': a.condition_description,
            'auction_status': auction_status,
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
        return redirect('auth_page')

    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect('watchlist')

    try:
        Watchlist.objects.filter(auction_id=auction_id, user_id=user_id).delete()
        messages.success(request, "Auction removed from your watchlist successfully.")
    except Exception as e:
        messages.error(request, "An error occurred while removing the auction from your watchlist.")
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
                User.objects.filter(id=user_id).update(selfie=selfie_relative_path, account_status='pending')
                UserActivity.objects.create(user_id=user_id, description='Submitted selfie for verification.')
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
                User.objects.filter(id=user_id).update(
                    id_proof=id_proof_relative_path, selfie=selfie_relative_path, account_status='pending'
                )
                UserActivity.objects.create(user_id=user_id, description='Submitted ID proof and selfie for verification.')
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
            user_obj = User.objects.get(id=user_id)
            current_data = (
                user_obj.username, user_obj.email, user_obj.phone, user_obj.address, user_obj.pincode,
                user_obj.email_notifications, user_obj.sms_notifications,
                user_obj.bank_account_number, user_obj.paypal_email, user_obj.profile_picture,
                user_obj.id_proof, user_obj.selfie,
            )

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
                update_fields = {
                    'username': username, 'email': email, 'phone': phone,
                    'address': address, 'pincode': pincode,
                    'email_notifications': email_notifications,
                    'sms_notifications': sms_notifications,
                    'bank_account_number': bank_account_number,
                    'paypal_email': paypal_email,
                    'profile_picture': profile_pic_relative_path,
                    'id_proof': id_proof_relative_path,
                    'selfie': selfie_relative_path,
                }
                if id_proof or selfie_data:
                    update_fields['account_status'] = 'pending'
                User.objects.filter(id=user_id).update(**update_fields)
                UserActivity.objects.create(user_id=user_id, description='Updated profile information.')
                logger.info(f"Profile updated successfully for user ID: {user_id}")
                messages.success(request, "Profile updated successfully!")
            except Exception as e:
                logger.error(f"Error updating profile for user ID: {user_id}: {str(e)}")
                messages.error(request, "An error occurred while updating the profile. Please try again.")
            return redirect('profman')

    # Fetch user data for pre-filling the form
    try:
        user_obj = User.objects.get(id=user_id)
        user_data = (
            user_obj.username, user_obj.email, user_obj.phone, user_obj.address,
            user_obj.email_notifications, user_obj.sms_notifications,
            user_obj.bank_account_number, user_obj.paypal_email,
            user_obj.bidding_restricted, user_obj.is_authenticated,
            user_obj.premium, user_obj.email_verified,
            user_obj.profile_picture, user_obj.pincode, user_obj.created_at,
            user_obj.account_status, user_obj.id_proof, user_obj.selfie,
        )
        logger.debug(f"User data fetched for user ID: {user_id}")
    except Exception as e:
        logger.error(f"Error fetching user data for user ID: {user_id}: {str(e)}")
        messages.error(request, "An error occurred while fetching user data.")
        return redirect('login')

    # Fetch recent activities
    try:
        activities_qs = UserActivity.objects.filter(user_id=user_id).order_by('-date').values_list('description', 'date')
        activities_data = list(activities_qs)
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
    # Check if user already has a membership plan using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        user_membership = (user_obj.membership_plan_id, user_obj.premium)
    except User.DoesNotExist:
        return redirect('login')

    if user_membership and user_membership[0] is not None:
        # User already has a membership, fetch latest subscription details
        premium_user = PremiumUser.objects.filter(
            user_id=user_id
        ).select_related('plan').order_by('-premium_end_date').first()
        premium_details = None
        if premium_user:
            premium_details = (premium_user.premium_start_date, premium_user.premium_end_date, premium_user.plan.plan_name)

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
        plans_qs = MembershipPlan.objects.all().values(
            'plan_id', 'plan_name', 'price', 'regular_auction_limit', 'sealed_bid_limit', 'wallet_credit'
        )
        plans = [{
            "id": row['plan_id'],
            "plan_name": row['plan_name'],
            "price": row['price'],
            "regular_limit": row['regular_auction_limit'],
            "sealed_limit": row['sealed_bid_limit'],
            "wallet_amount": row['wallet_credit'],
        } for row in plans_qs]
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
    try:
        plan_obj = MembershipPlan.objects.get(plan_id=plan_id)
    except MembershipPlan.DoesNotExist:
        return JsonResponse({"success": False, "error": "Membership plan not found."}, status=400)

    plan_name = plan_obj.plan_name
    price = plan_obj.price
    regular_limit = plan_obj.regular_auction_limit
    sealed_limit = plan_obj.sealed_bid_limit
    wallet_amount = plan_obj.wallet_credit

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

    # Insert payment details using ORM
    PaymentDetail.objects.create(
        user_id=user_id,
        premium_type=plan_name,
        payment_method=payment_method,
        payment_amount=price,
        payment_status='completed',
        transaction_id=str(uuid.uuid4()),
        payment_date=start_date,
        debit_card_number=payment_details['debit_card_number'] or None,
        debit_card_expiry=payment_details['debit_card_expiry'] or None,
        debit_card_cvc=payment_details['debit_card_cvc'] or None,
        credit_card_number=payment_details['credit_card_number'] or None,
        credit_card_expiry=payment_details['credit_card_expiry'] or None,
        credit_card_cvc=payment_details['credit_card_cvc'] or None,
        paypal_email=payment_details['paypal_email'] or None,
        bank_account_number=payment_details['bank_account_number'] or None,
        bank_routing_number=payment_details['bank_routing_number'] or None,
    )

    # Insert premium subscription using ORM
    PremiumUser.objects.create(
        user_id=user_id, plan_id=plan_id,
        premium_start_date=start_date, premium_end_date=end_date,
    )

    # Update user's membership_plan_id and premium flag using ORM
    User.objects.filter(id=user_id).update(premium=True, membership_plan_id=plan_id)

    # Update or create wallet using ORM
    wallet_obj, created = Wallet.objects.get_or_create(user_id=user_id, defaults={'balance': wallet_amount})
    if not created:
        wallet_obj.balance = F('balance') + wallet_amount
        wallet_obj.save(update_fields=['balance'])

    # Fetch user's email for notification using ORM
    user_email = user_obj.email

    # Fetch admin email using ORM
    admin_user = User.objects.filter(role='admin').first()
    admin_email = admin_user.email if admin_user else 'admin@example.com'

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
    # Fetch winner selection date using ORM
    sealed_detail = SealedBidDetail.objects.filter(auction_id=auction_id).first()
    winner_selection_date = sealed_detail.winner_selection_date if sealed_detail else None

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
        # Note: auction_winners table not in models, kept as raw for now
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
    notifications = list(
        Notification.objects.filter(user_id=user_id).order_by('-created_at').values('id', 'message', 'is_read')
    )
    return render(request, "notifications.html", {"notifications": notifications})

@csrf_exempt
def mark_notification_read(request, notification_id):
    if request.method == "POST":
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)
        updated = Notification.objects.filter(id=notification_id, user_id=user_id).update(is_read=True)
        if updated == 0:
            return JsonResponse({"success": False, "error": "Notification not found or not authorized"}, status=404)
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Invalid request method"}, status=400)

@csrf_exempt
def mark_all_notifications_read(request):
    user_id = request.session.get('user_id')
    if request.method == "POST" and user_id:
        Notification.objects.filter(user_id=user_id).update(is_read=True)
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Not authenticated or invalid request method"}, status=400)

@csrf_exempt
def delete_notification(request, notification_id):
    if request.method == "POST":
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)
        deleted, _ = Notification.objects.filter(id=notification_id, user_id=user_id).delete()
        if deleted == 0:
            return JsonResponse({"success": False, "error": "Notification not found or not authorized"}, status=404)
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Invalid request method"}, status=400)

@csrf_exempt
def delete_all_notifications(request):
    if request.method == "POST":
        user_id = request.session.get('user_id')
        if not user_id:
            return JsonResponse({"success": False, "error": "Not authenticated"}, status=401)
        Notification.objects.filter(user_id=user_id).delete()
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

    # Fetch invoices using ORM
    invoice_qs = Invoice.objects.filter(buyer_id=user_id).values(
        'id', 'auction_id', 'amount_due', 'issue_date', 'due_date', 'status',
        'seller_id', 'late_fee',
    )
    # For each invoice, check if there's an accepted offer with second_winner_offer
    invoices = []
    for inv in invoice_qs:
        second_winner = Offer.objects.filter(
            auction_id=inv['auction_id'], status='accepted'
        ).values_list('second_winner_offer', flat=True).first()
        invoices.append((*inv.values(), second_winner))

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
            # Fetch invoice using ORM
            try:
                invoice_obj = Invoice.objects.get(id=invoice_id, buyer_id=user_id)
            except Invoice.DoesNotExist:
                messages.error(request, "Invalid invoice selected.")
                return redirect('payment_page')

            invoice_status = invoice_obj.status
            due_date = invoice_obj.due_date
            if isinstance(due_date, datetime) and due_date.tzinfo is None:
                due_date = make_aware(due_date)

            # Check for second winner offer
            second_winner_offer = Offer.objects.filter(
                auction_id=invoice_obj.auction_id, status='accepted'
            ).values_list('second_winner_offer', flat=True).first()
            second_winner_offer = second_winner_offer if second_winner_offer is not None else False

            if second_winner_offer and invoice_status != 'Paid':
                messages.error(request, "Second winner invoices cannot be paid here.")
                return redirect('payment_page')

            grace_period = timedelta(minutes=10)
            if invoice_status == 'Overdue' and current_datetime > due_date + grace_period:
                messages.error(request, "The grace period for this overdue invoice has expired.")
                return redirect('payment_page')

            transaction_id = str(uuid4())[:16]
            payment_date = timezone.now()
            payment_amount = float(invoice_obj.amount_due) + float(invoice_obj.late_fee or 0)
            auction_id = invoice_obj.auction_id
            seller_id = invoice_obj.seller_id

            with transaction.atomic():
                # Create payment detail using ORM
                payment_kwargs = {
                    'user_id': user_id,
                    'invoice_id': invoice_id,
                    'auction_id': auction_id,
                    'payment_method': payment_method,
                    'payment_status': 'Completed',
                    'transaction_id': transaction_id,
                    'payment_amount': payment_amount,
                    'payment_date': payment_date,
                }
                if payment_method == "credit_card":
                    payment_kwargs['credit_card_number'] = request.POST.get("card_number")
                    payment_kwargs['payment_notes'] = request.POST.get("bank_name")
                elif payment_method == "paypal":
                    payment_kwargs['paypal_email'] = request.POST.get("paypal_email")
                elif payment_method == "bank_transfer":
                    payment_kwargs['bank_account_number'] = request.POST.get("iban")
                    payment_kwargs['bank_routing_number'] = request.POST.get("bic")
                    payment_kwargs['payment_notes'] = request.POST.get("bank_name")
                elif payment_method == "crypto":
                    payment_kwargs['wallet_address'] = request.POST.get("wallet_address")
                    payment_kwargs['crypto_type'] = request.POST.get("crypto_type")
                else:
                    raise ValueError(f"Invalid payment method: {payment_method}")

                PaymentDetail.objects.create(**payment_kwargs)

                # Update invoice status
                Invoice.objects.filter(id=invoice_id).update(status='Paid')

                # Calculate commission
                auction_obj = Auction.objects.get(id=auction_id)
                commission = PlatformCommission.objects.filter(
                    auction_type=auction_obj.auction_type, status='active'
                ).order_by('-effective_date').first()
                commission_percentage = float(commission.commission_percentage) if commission else 5.00

                platform_share = (commission_percentage / 100) * payment_amount
                seller_share = payment_amount - platform_share

                FundDistribution.objects.create(
                    invoice_id=invoice_id, auction_id=auction_id, seller_id=seller_id,
                    platform_share=platform_share, seller_share=seller_share,
                    status='Pending', distribution_date=payment_date,
                )

                tracking_id = str(uuid4())[:10]
                Order.objects.filter(invoice_id=invoice_id).update(
                    shipping_status='processing', progress=30,
                    payment_status='paid', tracking_number=tracking_id,
                )

                Auction.objects.filter(id=auction_id).update(status='sold')

            # Notify Seller
            try:
                seller_user = User.objects.get(id=seller_id)
                seller_message = f"A payment of ₹{payment_amount:.2f} has been received for auction (ID: {auction_id}). The auction status is now sold."
                notify_user(seller_id, seller_user.email, seller_message, subject="Auction Sold")
            except Exception as e:
                logger.error(f"Failed to notify seller (ID: {seller_id}): {str(e)}")

            # Notify Buyer
            try:
                buyer_user = User.objects.get(id=user_id)
                buyer_message = f"Your payment of ₹{payment_amount:.2f} for invoice (ID: {invoice_id}) and auction (ID: {auction_id}) has been successfully processed."
                notify_user(user_id, buyer_user.email, buyer_message, subject="Payment Confirmation")
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

    # Fetch auction details using ORM
    try:
        print("DEBUG: Fetching auction details for auction_id:", auction_id)
        auction_obj = Auction.objects.get(id=auction_id, auction_type='buy_it_now')
        if auction_obj.status == 'sold':
            raise Auction.DoesNotExist
        print("DEBUG: Auction fetched:", auction_obj.title)
    except Auction.DoesNotExist:
        print("DEBUG: Auction not found, invalid, or already sold")
        messages.error(request, "Invalid, unavailable, or already sold auction.")
        return redirect('auct_list')
    except Exception as ex:
        print("DEBUG: Error fetching auction details")
        traceback.print_exc()
        messages.error(request, "Error fetching auction details.")
        return redirect('auct_list')

    # Fetch auction image using ORM
    image_url = None
    try:
        print("DEBUG: Fetching auction image for auction_id:", auction_id)
        first_image = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True).first()
        if first_image:
            if first_image.startswith("/media/"):
                image_url = first_image
            else:
                image_url = f"/media/auction_images/{first_image}"
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
        "id": auction_obj.id,
        "title": auction_obj.title,
        "description": auction_obj.description,
        "condition": auction_obj.condition,
        "condition_description": auction_obj.condition_description,
        "category": auction_obj.category,
        "price": float(auction_obj.buy_it_now_price),
        "seller_id": auction_obj.user_id,
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
                # Create invoice using ORM
                invoice_id = uuid4().hex[:16]
                issue_date = timezone.now()
                due_date = issue_date
                print("DEBUG: Creating invoice with id:", invoice_id)
                Invoice.objects.create(
                    id=invoice_id, auction_id=auction_id, buyer_id=user_id,
                    seller_id=item["seller_id"], amount_due=float(item["total_amount"]),
                    issue_date=issue_date, due_date=due_date, status='Pending',
                )
                print("DEBUG: Invoice created successfully")

                # Process payment using ORM
                transaction_id = uuid4().hex[:16]
                payment_date = timezone.now()
                payment_amount = float(item["total_amount"])
                print("DEBUG: Processing payment. Transaction ID:", transaction_id)

                payment_kwargs = {
                    'user_id': user_id, 'invoice_id': invoice_id, 'auction_id': auction_id,
                    'payment_method': payment_method, 'payment_status': 'Completed',
                    'transaction_id': transaction_id, 'payment_amount': payment_amount,
                    'payment_date': payment_date,
                }
                if payment_method == "credit_card":
                    print("DEBUG: Inserting credit card payment details")
                    payment_kwargs['credit_card_number'] = request.POST.get("card_number")
                elif payment_method == "paypal":
                    print("DEBUG: Inserting PayPal payment details")
                    payment_kwargs['paypal_email'] = request.POST.get("paypal_email")
                elif payment_method == "bank_transfer":
                    print("DEBUG: Inserting bank transfer payment details")
                    payment_kwargs['bank_account_number'] = request.POST.get("iban")
                    payment_kwargs['bank_routing_number'] = request.POST.get("bic")
                else:
                    raise ValueError("Invalid payment method selected")

                PaymentDetail.objects.create(**payment_kwargs)
                print("DEBUG: Payment details inserted successfully")

                # Update invoice status to 'Paid'
                print("DEBUG: Updating invoice status to 'Paid'")
                Invoice.objects.filter(id=invoice_id).update(status='Paid')

                # Fetch commission percentage using ORM
                print("DEBUG: Fetching commission percentage")
                commission = PlatformCommission.objects.filter(
                    auction_type='buy_it_now'
                ).order_by('-effective_date').first()
                commission_percentage = float(commission.commission_percentage) if commission else 5.00
                print("DEBUG: Commission percentage:", commission_percentage)

                # Calculate fund distribution amounts
                platform_share = (commission_percentage / 100) * payment_amount
                seller_share = payment_amount - platform_share
                print("DEBUG: Platform share:", platform_share, "Seller share:", seller_share)

                FundDistribution.objects.create(
                    invoice_id=invoice_id, auction_id=auction_id, seller_id=item["seller_id"],
                    platform_share=platform_share, seller_share=seller_share,
                    status='Pending', distribution_date=payment_date,
                )
                print("DEBUG: Fund distribution record inserted")

                # Insert order using ORM
                tracking_id = uuid4().hex[:10]
                print("DEBUG: Inserting order details with tracking id:", tracking_id)
                order_obj = Order.objects.create(
                    auction_id=auction_id, user_id=user_id, invoice_id=invoice_id,
                    payment_status='paid', payment_amount=payment_amount,
                    shipping_status='processing', tracking_number=tracking_id,
                    order_date=payment_date, order_status='Confirmed', progress=30,
                )
                order_id = order_obj.id
                print("DEBUG: Order inserted with order_id:", order_id)

                # Insert shipping details using ORM
                print("DEBUG: Inserting shipping details")
                ShippingDetail.objects.create(
                    order_id=order_id, invoice_id=invoice_id, buyer_id=user_id,
                    full_name=full_name, phone=phone, address=address,
                    city=city, state=state, zip_code=zip_code, country=country,
                    shipping_date=payment_date,
                )

                # Update auction status to sold
                print("DEBUG: Updating auction status to 'sold'")
                Auction.objects.filter(id=auction_id).update(status='sold')

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
            images = AuctionImage.objects.filter(
                auction_id=auction_id, image_path__isnull=False
            ).values_list('image_path', flat=True)
            valid_images = [f"/media/auction_images/{img}" for img in images if img]
            print(f"DEBUG: Auction ID {auction_id} returned images: {valid_images}")
            return valid_images
        except Exception as e:
            print(f"DEBUG: Error fetching images for auction {auction_id}: {e}")
            return []

    def fetch_shipping_details(order_id):
        """Fetch shipping details for buy_it_now orders."""
        try:
            sd = ShippingDetail.objects.filter(order_id=order_id).first()
            if sd:
                shipping_address = f"{sd.address}, {sd.city}, {sd.state}, {sd.zip_code}, {sd.country}"
                print(f"DEBUG: Shipping details for order {order_id}: {shipping_address}, {sd.shipping_date}")
                return {
                    "shipping_address": shipping_address,
                    "delivery_date": sd.shipping_date,
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
        # Fetch specific order details using ORM
        try:
            order_qs = Order.objects.filter(
                order_id=order_id
            ).filter(
                Q(user_id=user_id) | Q(auction__user_id=user_id)
            ).select_related('auction', 'user').first()
            
            if order_qs:
                order_detail = order_qs
            else:
                order_detail = None
            print(f"DEBUG: Order {order_id} details: {order_detail}")
        except Exception as e:
            print(f"DEBUG: Error fetching order {order_id}: {e}")
            messages.error(request, "Error fetching order details.")
            return render(request, 'view_orders.html', context)

        if order_detail:
            o = order_detail
            buyer_user = o.user
            def map_order_detail_orm(o, buyer_user):
                mapped = {
                    "order_id": o.order_id,
                    "auction_id": o.auction_id,
                    "title": o.auction.title if o.auction else "N/A",
                    "auction_type": o.auction.auction_type if o.auction else "N/A",
                    "payment_status": o.payment_status,
                    "payment_amount": float(o.payment_amount) if o.payment_amount is not None else 0.0,
                    "order_status": o.order_status if o.order_status else "Pending",
                    "order_date": format_date(o.order_date),
                    "shipping_status": o.shipping_status if o.shipping_status else "Not Shipped",
                    "shipping_address": o.shipping_address if o.shipping_address else "N/A",
                    "tracking_number": o.tracking_number if o.tracking_number else "N/A",
                    "delivery_date": format_date_only(o.delivery_date),
                    "progress": o.progress if o.progress is not None else 0,
                    "buyer_id": o.user_id,
                    "buyer_name": buyer_user.username if buyer_user else "N/A",
                    "buyer_email": buyer_user.email if buyer_user else "N/A",
                    "images": fetch_auction_images(o.auction_id),
                    "invoice_id": o.invoice_id if o.invoice_id else "",
                }
                if mapped["auction_type"] == "buy_it_now":
                    shipping = fetch_shipping_details(mapped["order_id"])
                    if shipping:
                        mapped["shipping_address"] = shipping.get("shipping_address", mapped["shipping_address"])
                        if shipping.get("delivery_date"):
                            mapped["delivery_date"] = format_date_only(shipping["delivery_date"])
                return mapped

            context["order_detail"] = map_order_detail_orm(o, buyer_user)
        else:
            messages.error(request, "Order not found or you lack permission to view it.")

    # Fetch all seller and buyer orders using ORM
    try:
        # Seller orders (auctions owned by user)
        seller_orders_qs = Order.objects.filter(
            auction__user_id=user_id
        ).select_related('auction', 'user').order_by('-order_date')
        seller_orders = list(seller_orders_qs)
        print(f"DEBUG: Seller orders for user {user_id}: {len(seller_orders)}")

        # Buyer orders
        buyer_orders_qs = Order.objects.filter(
            user_id=user_id
        ).select_related('auction').order_by('-order_date')
        buyer_orders = list(buyer_orders_qs)
        print(f"DEBUG: Buyer orders for user {user_id}: {len(buyer_orders)}")
    except Exception as e:
        print(f"DEBUG: Error fetching orders: {e}")
        messages.error(request, "Error fetching orders.")
        return render(request, 'view_orders.html', context)

    def map_seller_order(o):
        buyer_user = o.user
        mapped = {
            "order_id": o.order_id,
            "auction_id": o.auction_id,
            "title": o.auction.title if o.auction else "N/A",
            "payment_status": o.payment_status,
            "payment_amount": float(o.payment_amount) if o.payment_amount is not None else 0.0,
            "order_status": o.order_status if o.order_status else "Pending",
            "order_date": format_date(o.order_date),
            "shipping_status": o.shipping_status if o.shipping_status else "Not Shipped",
            "shipping_address": o.shipping_address if o.shipping_address else "N/A",
            "tracking_number": o.tracking_number if o.tracking_number else "N/A",
            "delivery_date": format_date_only(o.delivery_date),
            "buyer_name": buyer_user.username if buyer_user else "N/A",
            "buyer_email": buyer_user.email if buyer_user else "N/A",
            "progress": o.progress if o.progress is not None else 0,
            "auction_type": o.auction.auction_type if o.auction else "N/A",
            "images": fetch_auction_images(o.auction_id),
            "invoice_id": o.invoice_id if o.invoice_id else "",
        }
        if mapped["auction_type"] == "buy_it_now":
            shipping = fetch_shipping_details(mapped["order_id"])
            if shipping:
                mapped["shipping_address"] = shipping.get("shipping_address", mapped["shipping_address"])
                if shipping.get("delivery_date"):
                    mapped["delivery_date"] = format_date_only(shipping["delivery_date"])
        return mapped

    def map_buyer_order(o):
        mapped = {
            "order_id": o.order_id,
            "auction_id": o.auction_id,
            "title": o.auction.title if o.auction else "N/A",
            "payment_status": o.payment_status,
            "payment_amount": float(o.payment_amount) if o.payment_amount is not None else 0.0,
            "order_date": format_date(o.order_date),
            "order_status": o.order_status if o.order_status else "Pending",
            "shipping_status": o.shipping_status if o.shipping_status else "Not Shipped",
            "shipping_address": o.shipping_address if o.shipping_address else "N/A",
            "tracking_number": o.tracking_number if o.tracking_number else "N/A",
            "delivery_date": format_date_only(o.delivery_date),
            "progress": o.progress if o.progress is not None else 0,
            "auction_type": o.auction.auction_type if o.auction else "N/A",
            "images": fetch_auction_images(o.auction_id),
            "invoice_id": o.invoice_id if o.invoice_id else "",
        }
        if mapped["auction_type"] == "buy_it_now":
            shipping = fetch_shipping_details(mapped["order_id"])
            if shipping:
                mapped["shipping_address"] = shipping.get("shipping_address", mapped["shipping_address"])
                if shipping.get("delivery_date"):
                    mapped["delivery_date"] = format_date_only(shipping["delivery_date"])
        return mapped

    seller_orders_list = [map_seller_order(o) for o in seller_orders]
    buyer_orders_list = [map_buyer_order(o) for o in buyer_orders]
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
            # Fetch order using ORM
            try:
                order_obj = Order.objects.get(order_id=order_id, user_id=user_id)
            except Order.DoesNotExist:
                logger.error(f"No order found for order_id={order_id}, user_id={user_id}")
                messages.error(request, "Order not found or you do not have permission to update it.")
                return redirect('view_orders')

            invoice_id = order_obj.invoice_id
            buyer_id = order_obj.user_id
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

            # Update the orders table using ORM
            logger.debug(f"Updating orders with order_id={order_id}, user_id={user_id}")
            Order.objects.filter(order_id=order_id, user_id=user_id).update(shipping_address=shipping_address)
            logger.debug(f"Orders table updated")

            # Update or create shipping_details using ORM
            sd, created = ShippingDetail.objects.update_or_create(
                order_id=order_id,
                defaults={
                    'invoice_id': invoice_id, 'buyer_id': buyer_id,
                    'full_name': full_name, 'phone': phone,
                    'address': full_address, 'city': city, 'state': state,
                    'zip_code': zip_code, 'country': country,
                    'shipping_date': timezone.now(),
                }
            )
            if created:
                logger.info(f"Inserted new shipping_details for order_id={order_id}")
            else:
                logger.info(f"Updated shipping_details for order_id={order_id}")

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

    # Retrieve order with related auction and users using ORM
    try:
        order_obj = Order.objects.select_related('auction').get(order_id=order_id, auction__user_id=seller_id)
    except Order.DoesNotExist:
        messages.error(request, "Order not found or you are not authorized to confirm it.")
        return redirect('view_orders')

    buyer_id = order_obj.user_id
    buyer_user = User.objects.get(id=buyer_id)
    seller_user = User.objects.get(id=seller_id)
    buyer_email = buyer_user.email
    seller_email = seller_user.email

    # Update order_status to "Confirmed" using ORM
    Order.objects.filter(order_id=order_id).update(order_status='Confirmed', progress=10)

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

    # Retrieve order with related auction using ORM
    try:
        order_obj = Order.objects.select_related('auction').get(order_id=order_id, auction__user_id=seller_id)
    except Order.DoesNotExist:
        messages.error(request, "Order not found or you are not authorized to cancel it.")
        return redirect('view_orders')

    buyer_id = order_obj.user_id
    buyer_user = User.objects.get(id=buyer_id)
    seller_user = User.objects.get(id=seller_id)
    buyer_email = buyer_user.email
    seller_email = seller_user.email

    # Update order_status to "Rejected" using ORM
    Order.objects.filter(order_id=order_id).update(order_status='Rejected')

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

        Review.objects.create(
            order_id=order_id, user_id=user_id, rating=rating,
            reasons=reason_text, comments=comments,
        )

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
    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
        seller_id = auction_obj.user_id
        auction_title = auction_obj.title
    except Auction.DoesNotExist:
        return HttpResponseBadRequest("Auction not found.")

    # Determine receiver
    if buyer_id:
        receiver_id = buyer_id
    else:
        if user_id != seller_id:
            receiver_id = seller_id
        else:
            last_msg = Message.objects.filter(
                auction_id=auction_id, receiver_id=seller_id
            ).order_by('-timestamp').first()
            if last_msg:
                receiver_id = last_msg.sender_id
            else:
                return JsonResponse({"error": "No buyer found to reply to."}, status=400)

    # Check if this is a new buyer-initiated chat
    send_notification = False
    buyer_username = None
    seller_email = None
    if user_id != seller_id:  # Buyer sending to seller
        # Check if this is the first message for this buyer-seller-auction using ORM
        message_count = Message.objects.filter(
            auction_id=auction_id, sender_id=user_id, receiver_id=seller_id
        ).count()
        if message_count == 0:
            send_notification = True
            buyer_user = User.objects.get(id=user_id)
            buyer_username = buyer_user.username
            seller_user_obj = User.objects.get(id=seller_id)
            seller_email = seller_user_obj.email

    # Handle file upload
    attachment_path = None
    if attachment:
        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'messages'))
        filename = f"{uuid.uuid4()}{os.path.splitext(attachment.name)[1]}"
        attachment_path = fs.save(filename, attachment)
        attachment_url = request.build_absolute_uri(f"{settings.MEDIA_URL}messages/{attachment_path}")
    else:
        attachment_url = None

    # Insert the message using ORM
    timestamp = timezone.now()
    msg_obj = Message.objects.create(
        auction_id=auction_id, sender_id=user_id, receiver_id=receiver_id,
        message=message, timestamp=timestamp, attachment=attachment_path,
    )
    msg_id = msg_obj.id

    # Fetch sender's username using ORM
    try:
        sender_user = User.objects.get(id=user_id)
        sender_username = sender_user.username
    except User.DoesNotExist:
        return JsonResponse({"error": "Sender not found."}, status=500)

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

    # Fetch inbox using ORM with annotations
    from django.db.models import Max, Count
    inbox_qs = Message.objects.filter(
        receiver_id=seller_id
    ).values('sender_id').annotate(
        message_count=Count('id'),
        last_timestamp=Max('timestamp'),
    ).order_by('-last_timestamp')

    inbox = []
    for entry in inbox_qs:
        try:
            sender = User.objects.get(id=entry['sender_id'])
            profile_picture = sender.profile_picture
            profile_picture_url = f"/media/{profile_picture}" if profile_picture else "/static/images/default_profile.png"
            inbox.append({
                "sender_id": entry['sender_id'],
                "username": sender.username,
                "profile_picture": profile_picture_url,
                "message_count": entry['message_count'],
                "last_timestamp": entry['last_timestamp'],
            })
        except User.DoesNotExist:
            continue

    # Return JSON response for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({"inbox": inbox}, safe=False)

    # Render the HTML page for normal requests
    return render(request, "seller_inbox.html", {"inbox": inbox})


def chat_detail(request, buyer_id):
    seller_id = request.session.get("user_id")
    if not seller_id:
        return JsonResponse({"error": "User not authenticated"}, status=401)

    # Fetch messages using ORM
    msgs_qs = Message.objects.filter(
        Q(sender_id=buyer_id, receiver_id=seller_id) | Q(sender_id=seller_id, receiver_id=buyer_id)
    ).select_related().order_by('timestamp')

    messages_list = []
    for m in msgs_qs:
        try:
            sender = User.objects.get(id=m.sender_id)
            sender_username = sender.username
        except User.DoesNotExist:
            sender_username = "Unknown"
        messages_list.append({
            "id": m.id,
            "auction_id": m.auction_id,
            "sender_id": m.sender_id,
            "sender_username": sender_username,
            "message": m.message,
            "timestamp": m.timestamp.isoformat() if isinstance(m.timestamp, datetime) else m.timestamp,
            "attachment": f"{settings.MEDIA_URL}messages/{m.attachment}" if m.attachment else None,
        })

    # Fetch buyer details using ORM
    try:
        buyer_user = User.objects.get(id=buyer_id)
        profile_pic = (
            f"{settings.MEDIA_URL}{buyer_user.profile_picture}" if buyer_user.profile_picture
            else f"{settings.STATIC_URL}images/default_profile.png"
        )
        buyer = {
            "id": buyer_id,
            "username": buyer_user.username,
            "profile_picture": profile_pic,
        }
    except User.DoesNotExist:
        buyer = {
            "id": buyer_id,
            "username": "Unknown",
            "profile_picture": f"{settings.STATIC_URL}images/default_profile.png",
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
        msgs_qs = Message.objects.filter(
            auction_id=auction_id
        ).filter(
            Q(sender_id=user_id) | Q(receiver_id=user_id)
        ).order_by('timestamp')

        messages_data = []
        for m in msgs_qs:
            try:
                sender = User.objects.get(id=m.sender_id)
                sender_username = sender.username
            except User.DoesNotExist:
                sender_username = "Unknown"
            messages_data.append({
                'id': m.id,
                'sender_id': m.sender_id,
                'sender_username': sender_username,
                'message': m.message,
                'timestamp': m.timestamp.isoformat() if isinstance(m.timestamp, datetime) else m.timestamp,
                'attachment': f"{settings.MEDIA_URL}messages/{m.attachment}" if m.attachment else None,
            })

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

    # Delete all messages between seller and buyer using ORM
    Message.objects.filter(
        Q(sender_id=buyer_id, receiver_id=seller_id) | Q(sender_id=seller_id, receiver_id=buyer_id)
    ).delete()

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

            Message.objects.filter(
                Q(sender_id=user_id, receiver_id=other_user_id) | Q(sender_id=other_user_id, receiver_id=user_id)
            ).delete()

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
            with transaction.atomic():
                if action == "report":
                    ReportedUser.objects.create(
                        reported_by_id=user_id, reported_user_id=target_user_id,
                        reason=reason, report_date=datetime.now(),
                    )
                    return JsonResponse({"status": "success", "message": "User reported successfully!"})

                elif action == "block":
                    # blocked_users table not in models, keep as raw
                    with connection.cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO blocked_users (blocked_by, blocked_user, block_date) 
                            VALUES (%s, %s, %s)
                        """, [user_id, target_user_id, datetime.now()])
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
        # Get or create wallet using ORM
        wallet, created = Wallet.objects.get_or_create(user_id=user_id, defaults={'balance': 0.0})
        if created:
            logger.info(f"wallet_dashboard - Created new wallet for user_id: {user_id} with balance: 0.0")
        balance = float(wallet.balance)
        logger.debug(f"wallet_dashboard - Wallet balance: {balance}")
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
            # Get or create wallet, then update balance using ORM
            wallet, created = Wallet.objects.get_or_create(user_id=user_id, defaults={'balance': deposit_amount})
            if not created:
                updated = Wallet.objects.filter(user_id=user_id).update(balance=F('balance') + deposit_amount)
                if updated == 0:
                    messages.error(request, "Failed to update wallet balance.")
                    logger.error(f"deposit_wallet - Update failed for user_id: {user_id}")
                    return redirect('wallet')
            else:
                logger.info(f"deposit_wallet - Created new wallet for user_id: {user_id} with initial balance: {deposit_amount}")

            # Fetch user email for notification
            try:
                user_obj = User.objects.get(id=user_id)
                user_email = user_obj.email
            except User.DoesNotExist:
                user_email = None

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
            # Get or create wallet using ORM
            wallet, created = Wallet.objects.get_or_create(user_id=user_id, defaults={'balance': 0.0})
            if created:
                logger.info(f"withdraw_wallet - Created new wallet for user_id: {user_id} with balance: 0.0")
            balance = float(wallet.balance)
            logger.debug(f"withdraw_wallet - Current balance: {balance}")

            if withdraw_amount > balance:
                messages.error(request, "Insufficient balance for this withdrawal.")
                logger.warning(f"withdraw_wallet - Insufficient balance: {balance} < {withdraw_amount}")
                return redirect('wallet')

            updated = Wallet.objects.filter(user_id=user_id).update(balance=F('balance') - withdraw_amount)
            if updated == 0:
                messages.error(request, "Failed to update wallet balance.")
                logger.error(f"withdraw_wallet - Update failed for user_id: {user_id}")
                return redirect('wallet')

            # Fetch user email for notification
            try:
                user_obj = User.objects.get(id=user_id)
                user_email = user_obj.email
            except User.DoesNotExist:
                user_email = None

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

        # Insert the feedback record using ORM
        Feedback.objects.create(
            user_id=user_id, name=name, email=email,
            subject=subject, message=message, file_paths=file_paths_str,
        )

        messages.success(request, "Thank you for your feedback!")
        return redirect("submit_feedback")

    # For GET, initialize a context dict
    context = {}
    user_id = request.session.get("user_id")
    if user_id:
        try:
            user_obj = User.objects.get(id=user_id)
            context["name"] = user_obj.username
            context["email"] = user_obj.email
        except User.DoesNotExist:
            pass
    return render(request, "feedback_form.html", context)












#admin
# In core/views.py
def list_users(request):
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "Please log in.")
        return redirect('login')

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=user_id)
        if admin_user.role != 'admin':
            messages.error(request, "You are not authorized to access this page.")
            return redirect('login')
    except User.DoesNotExist:
        messages.error(request, "You are not authorized to access this page.")
        return redirect('login')

    # Fetch all non-admin users using ORM
    users_qs = User.objects.exclude(role='admin').order_by('-created_at')
    users = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_authenticated": u.is_authenticated,
            "profile_picture": f"{settings.MEDIA_URL}{u.profile_picture}" if u.profile_picture else None,
        }
        for u in users_qs
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

    try:
        admin_user = User.objects.get(id=admin_id)
        admin_role_val = admin_user.role
    except User.DoesNotExist:
        admin_role_val = None
    logger.debug(f"Admin role fetched: {admin_role_val}")
    if admin_role_val != 'admin':
        logger.warning(f"User with ID {admin_id} is not an admin (role: {admin_role_val}), redirecting to login.")
        messages.error(request, "You are not authorized to access this page.")
        return redirect('login')

    if request.method == "GET":
        logger.info(f"Processing GET request for user_id: {user_id}")
        # Fetch user details using ORM
        logger.debug("Fetching all user details using ORM.")
        try:
            u = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.error(f"User with ID {user_id} not found, redirecting to list_users.")
            messages.error(request, "User not found.")
            return redirect('list_users')

        user_detail = {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "password_hash": u.password_hash,
            "salt": u.salt,
            "created_at": u.created_at,
            "role": u.role,
            "email_verified": bool(u.email_verified),
            "is_authenticated": bool(u.is_authenticated),
            "bidding_restricted": bool(u.bidding_restricted),
            "bank_account_number": u.bank_account_number,
            "paypal_email": u.paypal_email,
            "profile_picture": f"{settings.MEDIA_URL}{u.profile_picture}" if u.profile_picture else None,
            "phone": u.phone,
            "address": u.address,
            "email_notifications": bool(u.email_notifications),
            "sms_notifications": bool(u.sms_notifications),
            "pincode": u.pincode,
            "membership_plan_id": u.membership_plan_id,
            "premium": bool(u.premium),
            "account_status": u.account_status if u.account_status else 'pending',
            "id_proof_url": f"{settings.MEDIA_URL}{u.id_proof}" if u.id_proof else None,
            "id_proof_path": u.id_proof if u.id_proof else None,
            "selfie_url": f"{settings.MEDIA_URL}{u.selfie}" if u.selfie else None,
            "selfie_path": u.selfie if u.selfie else None,
        }
        logger.debug(f"User details mapped: {user_detail}")

        # Extra validation: warn if no email is on file
        if not user_detail["email"]:
            logger.warning(f"User {user_id} has no email on file.")
            messages.warning(request, "User has no email on file.")

        # Fetch auctions created by the user using ORM
        logger.debug(f"Fetching auctions created by user_id: {user_id}")
        created_auctions = list(
            Auction.objects.filter(user_id=user_id).values('id', 'title', 'category', 'starting_price', 'current_bid', 'status')
        )
        logger.debug(f"Created auctions: {created_auctions}")

        # Fetch auctions won by the user
        logger.debug(f"Fetching auctions won by user_id: {user_id}")
        won_auctions = list(
            Auction.objects.filter(winner_user_id=user_id).values('id', 'title', 'category', 'current_bid')
        )
        logger.debug(f"Won auctions: {won_auctions}")

        # Fetch auctions where the user has placed a bid
        logger.debug(f"Fetching auctions bidded on by user_id: {user_id}")
        bidded_auction_ids = Bid.objects.filter(user_id=user_id).values_list('auction_id', flat=True).distinct()
        bidded_auctions = list(
            Auction.objects.filter(id__in=bidded_auction_ids).values('id', 'title', 'category', 'current_bid', 'status')
        )
        logger.debug(f"Bidded auctions: {bidded_auctions}")

        # Fetch order history (won auctions with status 'sold')
        logger.debug(f"Fetching order history for user_id: {user_id}")
        order_history = list(
            Auction.objects.filter(winner_user_id=user_id, status='sold').values('id', 'title', 'category', 'current_bid')
        )
        logger.debug(f"Order history: {order_history}")

        # Fetch buying orders using ORM
        logger.debug(f"Fetching buying orders for user_id: {user_id}")
        buying_orders_qs = Order.objects.filter(user_id=user_id).select_related('auction')
        buying_orders = [
            {
                "order_id": o.order_id, "auction_id": o.auction_id, "invoice_id": o.invoice_id,
                "auction_title": o.auction.title if o.auction else "N/A",
                "order_date": o.order_date, "payment_amount": o.payment_amount,
                "payment_status": o.payment_status, "shipping_status": o.shipping_status,
                "tracking_number": o.tracking_number, "delivery_date": o.delivery_date,
                "order_status": o.order_status, "progress": o.progress,
            } for o in buying_orders_qs
        ]
        logger.debug(f"Buying orders: {buying_orders}")

        # Fetch selling orders using ORM
        logger.debug(f"Fetching selling orders for user_id: {user_id}")
        selling_orders_qs = Order.objects.filter(auction__user_id=user_id).select_related('auction')
        selling_orders = [
            {
                "order_id": o.order_id, "auction_id": o.auction_id, "invoice_id": o.invoice_id,
                "auction_title": o.auction.title if o.auction else "N/A",
                "order_date": o.order_date, "payment_amount": o.payment_amount,
                "payment_status": o.payment_status, "shipping_status": o.shipping_status,
                "tracking_number": o.tracking_number, "delivery_date": o.delivery_date,
                "order_status": o.order_status, "progress": o.progress,
            } for o in selling_orders_qs
        ]
        logger.debug(f"Selling orders: {selling_orders}")

        # Fetch reports filed against the user using ORM
        logger.debug(f"Fetching reports for user_id: {user_id}")
        reports_qs = ReportedUser.objects.filter(reported_user_id=user_id).select_related('reported_by')
        reports = []
        for r in reports_qs:
            try:
                reporter = User.objects.get(id=r.reported_by_id)
                reporting_username = reporter.username
            except User.DoesNotExist:
                reporting_username = "Unknown"
            reports.append({
                "id": r.id,
                "reported_by": r.reported_by_id,
                "reporting_username": reporting_username,
                "reason": r.reason,
                "report_date": r.report_date,
            })
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

            # Update the database using ORM
            logger.debug("Updating user details using ORM.")
            User.objects.filter(id=user_id).update(
                username=username, email=email, role=role_new,
                bidding_restricted=bidding_restricted_flag,
                premium=premium_flag, account_status=account_status,
            )
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

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=admin_id)
        if admin_user.role != 'admin':
            logger.warning(f"User with ID {admin_id} is not an admin.")
            messages.error(request, "You are not authorized to delete users.")
            return HttpResponseForbidden("You are not authorized to perform this action.")
    except User.DoesNotExist:
        logger.warning(f"User with ID {admin_id} is not an admin.")
        messages.error(request, "You are not authorized to delete users.")
        return HttpResponseForbidden("You are not authorized to perform this action.")

    # Check if the target user exists using ORM
    if not User.objects.filter(id=user_id).exists():
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

    # Fetch auction details using ORM
    try:
        a = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        raise Http404("Auction not found.")

    first_image = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True).first()

    # Map auction data
    auction_data = {
        'id': a.id,
        'title': a.title,
        'description': a.description,
        'category': a.category,
        'starting_price': a.starting_price,
        'current_bid': a.current_bid,
        'bid_increment': a.bid_increment,
        'reserve_price': a.reserve_price,
        'start_date': a.start_date,
        'end_date': a.end_date,
        'user_id': a.user_id,
        'auction_type': a.auction_type,
        'winner_user_id': a.winner_user_id,
        'image_url': f"/media/auction_images/{first_image}" if first_image else "/static/images/placeholder.png",
        'buy_it_now_price': a.buy_it_now_price,
        'is_make_offer_enabled': a.is_make_offer_enabled,
        'status': a.status,
        'condition': a.condition,
        'condition_description': a.condition_description,
    }

    # Fetch seller details using ORM
    try:
        seller = User.objects.get(id=a.user_id)
        profile_picture_path = seller.profile_picture if seller.profile_picture else ""
        final_profile_picture = (
            profile_picture_path if profile_picture_path.startswith(("/", "http"))
            else f"/media/{profile_picture_path}" if profile_picture_path
            else "/static/images/default_profile.png"
        )
        auction_data['user'] = {
            'username': seller.username,
            'email': seller.email,
            'profile_picture': final_profile_picture,
        }
    except User.DoesNotExist:
        auction_data['user'] = {
            'username': "Unknown User",
            'email': "No Email",
            'profile_picture': "/static/images/default_profile.png",
        }

    # Initialize winner details
    winner = None
    winner_available = False
    is_second_highest_bidder = False

    if datetime.now() > auction_data['end_date'] and auction_data.get('winner_user_id'):
        winner_available = True
        current_winner_id = auction_data['winner_user_id']

        # Fetch the top two bidders using ORM
        top_bidders = list(
            Bid.objects.filter(auction_id=auction_data['id'])
            .order_by('-amount', 'created_at')
            .values_list('user_id', 'amount')[:2]
        )

        # Determine the highest and second-highest bidder
        highest_bidder_id = None
        second_highest_bidder_id = None
        if top_bidders:
            highest_bidder_id = top_bidders[0][0]
            if len(top_bidders) > 1:
                second_highest_bidder_id = top_bidders[1][0]

        # Check if an offer was sent to the second winner using ORM
        second_winner_offer = Offer.objects.filter(
            auction_id=auction_data['id'], second_winner_offer=1
        ).values_list('buyer_id', flat=True).first()

        if second_winner_offer and str(second_winner_offer) == str(current_winner_id):
            is_second_highest_bidder = True

        # Fetch winner details using ORM
        try:
            winner_user = User.objects.get(id=current_winner_id)
            winner_profile = winner_user.profile_picture if winner_user.profile_picture else ""
            final_winner_profile = (
                winner_profile if winner_profile.startswith(("/", "http"))
                else f"/media/{winner_profile}" if winner_profile
                else "/static/images/default_profile.png"
            )
            winner = {
                'user_id': current_winner_id,
                'username': winner_user.username,
                'email': winner_user.email,
                'profile_picture': final_winner_profile,
                'final_price': auction_data['current_bid']
            }
        except User.DoesNotExist:
            winner = None

    auction_data['winner'] = winner
    auction_data['winner_available'] = winner_available

    # Fetch last bid using ORM
    last_bid = Bid.objects.filter(auction_id=auction_data['id']).order_by('-created_at').first()
    auction_data['current_bid'] = last_bid.amount if last_bid else auction_data['starting_price']

    # Fetch all images using ORM
    images = AuctionImage.objects.filter(auction_id=auction_data['id']).values_list('image_path', flat=True)
    auction_data['images'] = [f"/media/auction_images/{img}" for img in images if img]

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

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=admin_id)
        admin_role_val = admin_user.role
    except User.DoesNotExist:
        admin_role_val = None
    print(f"DEBUG: Fetched admin role: {admin_role_val}")

    if admin_role_val != 'admin':
        print("DEBUG: User is not an admin.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
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
    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        print("DEBUG: Auction not found.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "Auction not found."}, status=404)
        messages.error(request, "Auction not found.")
        return redirect('list_auctions')

    auction_status = auction_obj.status
    end_date = auction_obj.end_date
    print(f"DEBUG: Fetched auction details: status={auction_status}, end_date={end_date}")
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
        Auction.objects.filter(id=auction_id).update(status='stopped', updated_at=current_time)
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

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=admin_id)
        admin_role_val = admin_user.role
    except User.DoesNotExist:
        admin_role_val = None
    print(f"DEBUG: Fetched admin role: {admin_role_val}")

    if admin_role_val != 'admin':
        print("DEBUG: User is not an admin.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "You are not authorized to resume auctions."}, status=403)
        messages.error(request, "You are not authorized to resume auctions.")
        return HttpResponseForbidden("You are not authorized to perform this action.")

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
    except Auction.DoesNotExist:
        print("DEBUG: Auction not found.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "Auction not found."}, status=404)
        messages.error(request, "Auction not found.")
        return redirect('list_auctions')

    auction_status = auction_obj.status
    end_date = auction_obj.end_date
    updated_at = auction_obj.updated_at
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
        Auction.objects.filter(id=auction_id).update(status='active', updated_at=current_time)
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
    # Check if the current user is an admin using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        user_role_val = user_obj.role
    except User.DoesNotExist:
        user_role_val = None
    print("DEBUG: user_role =", user_role_val)

    if user_role_val != 'admin':
        print("DEBUG: User is not an admin or not found")
        if request.GET.get('json') == 'true':
            return JsonResponse({'error': 'Admin access required'}, status=403)
        return HttpResponseForbidden("You do not have permission to view this page. Admin access required.")

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
        auction_data = {
            'id': auction_obj.id,
            'title': auction_obj.title,
        }
    except Auction.DoesNotExist:
        if request.GET.get('json') == 'true':
            return JsonResponse({'error': 'Auction not found'}, status=404)
        raise Http404("Auction not found")

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

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=admin_id)
        if admin_user.role != 'admin':
            print("DEBUG: User is not an admin.")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'You are not authorized to perform this action.'}, status=403)
            messages.error(request, "You are not authorized to delete auctions.")
            return HttpResponseForbidden("You are not authorized to perform this action.")
    except User.DoesNotExist:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'You are not authorized to perform this action.'}, status=403)
        messages.error(request, "You are not authorized to delete auctions.")
        return HttpResponseForbidden("You are not authorized to perform this action.")

    # Fetch auction details including the creator's user_id
    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
        auction_type = auction_obj.auction_type
        creator_user_id = auction_obj.user_id
    except Auction.DoesNotExist:
        print("DEBUG: Auction not found.")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Auction not found.'}, status=404)
        messages.error(request, "Auction not found.")
        return redirect('manage_user', user_id=admin_id)
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

    # Check authorization using ORM
    try:
        user_obj = User.objects.get(id=logged_in_user_id)
        user_role = user_obj.role
    except User.DoesNotExist:
        messages.error(request, "User not found.")
        return HttpResponseForbidden("You are not authorized to view this page.")

    # Fetch auction details using ORM
    try:
        auction_obj = Auction.objects.get(id=auction_id)
        auction_creator_id = auction_obj.user_id
        auction_title = auction_obj.title
        auction_type = auction_obj.auction_type
    except Auction.DoesNotExist:
        messages.error(request, "Auction not found.")
        return redirect('list_users')

    # Authorization
    is_admin = user_role == 'admin'
    is_creator = logged_in_user_id == auction_creator_id
    is_buyer = Order.objects.filter(auction_id=auction_id, user_id=logged_in_user_id).exists()

    if not (is_admin or is_creator or is_buyer):
        messages.error(request, "You are not authorized to view this auction's orders.")
        return HttpResponseForbidden("You are not authorized to view this page.")

    managed_user_id = request.GET.get('managed_user_id', auction_creator_id if is_admin else logged_in_user_id)

    # AJAX request handling
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        progress_data = {}

        if is_buyer or is_admin:
            buying_orders_qs = Order.objects.filter(
                auction_id=auction_id, user_id=logged_in_user_id
            )
            buying_progress = [
                {
                    'order_id': o.order_id,
                    'progress': o.progress if o.progress is not None else 0,
                    'order_status': o.order_status if o.order_status else 'Processing',
                    'shipping_status': o.shipping_status if o.shipping_status else 'Not Shipped',
                    'delivery_date': o.delivery_date.strftime('%Y-%m-%d') if o.delivery_date else 'N/A',
                } for o in buying_orders_qs
            ]
            progress_data['buying_orders'] = {item['order_id']: item for item in buying_progress}

        if is_creator or is_admin:
            selling_orders_qs = Order.objects.filter(auction_id=auction_id)
            selling_progress = [
                {
                    'order_id': o.order_id,
                    'progress': o.progress if o.progress is not None else 0,
                    'order_status': o.order_status if o.order_status else 'Processing',
                    'shipping_status': o.shipping_status if o.shipping_status else 'Not Shipped',
                    'delivery_date': o.delivery_date.strftime('%Y-%m-%d') if o.delivery_date else 'N/A',
                } for o in selling_orders_qs
            ]
            progress_data['selling_orders'] = {item['order_id']: item for item in selling_progress}

        return JsonResponse(progress_data)

    # Helper functions
    def fetch_auction_images(auction_id):
        images = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True)
        return [f"/media/auction_images/{img}" for img in images if img]

    def fetch_shipping_details(order_id):
        sd = ShippingDetail.objects.filter(order_id=order_id).first()
        if sd:
            shipping_address = f"{sd.address}, {sd.city}, {sd.state}, {sd.zip_code}, {sd.country}"
            return {
                "shipping_address": shipping_address,
                "delivery_date": sd.shipping_date,
            }
        return None

    # Fetch buying orders
    buying_orders = []
    if is_buyer or is_admin:
        buying_orders_qs = Order.objects.filter(
            auction_id=auction_id, user_id=logged_in_user_id
        ).select_related('auction').order_by('-order_date')

        images = fetch_auction_images(auction_id)
        buying_orders = [
            {
                'order_id': o.order_id,
                'auction_id': o.auction_id,
                'auction_title': o.auction.title if o.auction else 'N/A',
                'payment_status': o.payment_status if o.payment_status else 'Pending',
                'payment_amount': float(o.payment_amount) if o.payment_amount is not None else 0.0,
                'order_status': o.order_status if o.order_status else 'Processing',
                'order_date': o.order_date.strftime('%Y-%m-%d %H:%M:%S') if o.order_date else 'N/A',
                'shipping_status': o.shipping_status if o.shipping_status else 'Not Shipped',
                'shipping_address': o.shipping_address if o.shipping_address else 'N/A',
                'tracking_number': o.tracking_number if o.tracking_number else 'N/A',
                'delivery_date': o.delivery_date.strftime('%Y-%m-%d') if o.delivery_date else 'N/A',
                'progress': o.progress if o.progress is not None else 0,
                'images': images,
                'auction_type': auction_type,
            } for o in buying_orders_qs
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
        selling_orders_qs = Order.objects.filter(
            auction_id=auction_id
        ).select_related('auction', 'user').order_by('-order_date')

        images = fetch_auction_images(auction_id)
        selling_orders = [
            {
                'order_id': o.order_id,
                'auction_id': o.auction_id,
                'auction_title': o.auction.title if o.auction else 'N/A',
                'payment_status': o.payment_status if o.payment_status else 'Pending',
                'payment_amount': float(o.payment_amount) if o.payment_amount is not None else 0.0,
                'order_status': o.order_status if o.order_status else 'Processing',
                'order_date': o.order_date.strftime('%Y-%m-%d %H:%M:%S') if o.order_date else 'N/A',
                'shipping_status': o.shipping_status if o.shipping_status else 'Not Shipped',
                'shipping_address': o.shipping_address if o.shipping_address else 'N/A',
                'tracking_number': o.tracking_number if o.tracking_number else 'N/A',
                'delivery_date': o.delivery_date.strftime('%Y-%m-%d') if o.delivery_date else 'N/A',
                'progress': o.progress if o.progress is not None else 0,
                'buyer_id': o.user_id,
                'buyer_name': o.user.username if o.user else 'N/A',
                'buyer_email': o.user.email if o.user else 'N/A',
                'images': images,
                'auction_type': auction_type,
            } for o in selling_orders_qs
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

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=admin_id)
        if admin_user.role != 'admin':
            logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
            messages.error(request, "You are not authorized to access this page.")
            return redirect('core:login')
    except User.DoesNotExist:
        logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
        messages.error(request, "You are not authorized to access this page.")
        return redirect('core:login')

    if request.method == "GET":
        logger.info("Processing GET request for payment_details")

        # Fetch payment details using ORM
        payments_qs = PaymentDetail.objects.all().order_by('-payment_timestamp')

        # Categorize payments
        premium_payments = []
        auction_payments = []
        for p in payments_qs:
            # Mask sensitive card details
            debit_card_number = p.debit_card_number if p.debit_card_number else None
            if debit_card_number:
                debit_card_number = f"****-****-****-{debit_card_number[-4:]}"

            credit_card_number = p.credit_card_number if p.credit_card_number else None
            if credit_card_number:
                credit_card_number = f"****-****-****-{credit_card_number[-4:]}"

            debit_card_cvc = "***" if p.debit_card_cvc else None
            credit_card_cvc = "***" if p.credit_card_cvc else None

            bank_account_number = p.bank_account_number if p.bank_account_number else None
            if bank_account_number:
                bank_account_number = f"****-****-{bank_account_number[-4:]}"

            bank_routing_number = p.bank_routing_number if p.bank_routing_number else None
            if bank_routing_number:
                bank_routing_number = f"****-{bank_routing_number[-4:]}"

            payment_dict = {
                "id": p.id,
                "user_id": p.user_id,
                "invoice_id": p.invoice_id,
                "auction_id": p.auction_id,
                "payment_method": p.payment_method,
                "payment_status": p.payment_status,
                "transaction_id": p.transaction_id,
                "payment_amount": p.payment_amount,
                "debit_card_number": debit_card_number,
                "debit_card_expiry": p.debit_card_expiry,
                "debit_card_cvc": debit_card_cvc,
                "credit_card_number": credit_card_number,
                "credit_card_expiry": p.credit_card_expiry,
                "credit_card_cvc": credit_card_cvc,
                "paypal_email": p.paypal_email,
                "bank_account_number": bank_account_number,
                "bank_routing_number": bank_routing_number,
                "payment_date": p.payment_date,
                "payment_timestamp": p.payment_timestamp,
                "payment_notes": p.payment_notes,
                "premium_type": p.premium_type,
            }
            if p.premium_type:
                premium_payments.append(payment_dict)
            elif p.auction_id:
                auction_payments.append(payment_dict)

        # Fetch seller payouts using ORM
        payouts_qs = SellerPayout.objects.all().order_by('-payout_date')
        seller_payouts = [
            {
                "id": p.payout_id,
                "seller_id": p.seller_id,
                "auction_id": p.auction_id,
                "invoice_id": p.invoice_id,
                "payout_amount": p.payout_amount,
                "payout_method": p.payout_method,
                "transaction_id": p.transaction_id,
                "payout_status": p.payout_status,
                "payout_date": p.payout_date,
            } for p in payouts_qs
        ]

        # Fetch all fund distributions using ORM
        distributions_qs = FundDistribution.objects.all().order_by('-distribution_date')
        fund_distributions = [
            {
                "id": d.id,
                "invoice_id": d.invoice_id,
                "auction_id": d.auction_id,
                "seller_id": d.seller_id,
                "platform_share": d.platform_share,
                "seller_share": d.seller_share,
                "status": d.status,
                "distribution_date": d.distribution_date,
            } for d in distributions_qs
        ]

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

        # Admin role check using ORM
        try:
            admin_user = User.objects.get(id=admin_id)
            if admin_user.role != 'admin':
                logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
                messages.error(request, "You are not authorized to access this page.")
                return redirect('core:login')
        except User.DoesNotExist:
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

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=admin_id)
        if admin_user.role != 'admin':
            logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
            messages.error(request, "You are not authorized to access this page.")
            return redirect('login')
    except User.DoesNotExist:
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
                Invoice.objects.filter(id=invoice_id).delete()
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
            invoices_qs = Invoice.objects.all().order_by('-issue_date')

            # Create CSV response
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="invoices_export.csv"'

            writer = csv.writer(response)
            writer.writerow([
                'Invoice ID', 'Auction ID', 'Buyer ID', 'Seller ID', 'Amount Due',
                'Issue Date', 'Due Date', 'Status', 'Late Fee', 'Reminder Sent'
            ])

            for inv in invoices_qs:
                writer.writerow([
                    inv.id, inv.auction_id, inv.buyer_id, inv.seller_id, f"₹{inv.amount_due:.2f}",
                    inv.issue_date.strftime('%Y-%m-%d %H:%M'), inv.due_date.strftime('%Y-%m-%d %H:%M'),
                    inv.status, f"₹{inv.late_fee:.2f}", 'Yes' if inv.reminder_sent else 'No'
                ])

            logger.debug(f"Exported {invoices_qs.count()} invoices to CSV")
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

        # Admin role check using ORM
        try:
            admin_user = User.objects.get(id=admin_id)
            if admin_user.role != 'admin':
                logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
                messages.error(request, "You are not authorized to access this page.")
                return redirect('login')
        except User.DoesNotExist:
            logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
            messages.error(request, "You are not authorized to access this page.")
            return redirect('login')

        # Fetch the invoice using ORM
        try:
            inv = Invoice.objects.get(id=invoice_id)
        except Invoice.DoesNotExist:
            logger.warning(f"Invoice {invoice_id} not found.")
            messages.error(request, "Invoice not found.")
            return redirect('invoice_list')

        invoice = {
            "id": inv.id,
            "auction_id": inv.auction_id,
            "buyer_id": inv.buyer_id,
            "seller_id": inv.seller_id,
            "amount_due": inv.amount_due,
            "issue_date": inv.issue_date,
            "due_date": inv.due_date,
            "status": inv.status,
            "late_fee": inv.late_fee,
            "reminder_sent": bool(inv.reminder_sent),
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

                Invoice.objects.filter(id=invoice_id).update(
                    auction_id=auction_id, buyer_id=buyer_id, seller_id=seller_id,
                    amount_due=amount_due, issue_date=issue_date, due_date=due_date,
                    status=status, late_fee=late_fee, reminder_sent=1 if reminder_sent else 0,
                )
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

    # Admin role check using ORM
    try:
        admin_user = User.objects.get(id=admin_id)
        if admin_user.role != 'admin':
            logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
            messages.error(request, "You are not authorized to access this page.")
            return redirect('login')
    except User.DoesNotExist:
        logger.warning(f"User with ID {admin_id} is not an admin, redirecting to login.")
        messages.error(request, "You are not authorized to access this page.")
        return redirect('login')

    def fetch_auctions():
        auctions_qs = Auction.objects.all().order_by('-created_at')
        return [
            {
                "id": a.id,
                "user_id": a.user_id,
                "title": a.title,
                "description": a.description,
                "category": a.category,
                "starting_price": a.starting_price,
                "reserve_price": a.reserve_price,
                "bid_increment": a.bid_increment,
                "start_date": a.start_date,
                "end_date": a.end_date,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
                "category_id": a.category_id,
                "current_bid": a.current_bid,
                "is_make_offer_enabled": bool(a.is_make_offer_enabled),
                "buy_it_now_price": a.buy_it_now_price,
                "auction_type": a.auction_type,
                "condition": a.condition,
                "condition_description": a.condition_description,
                "winner_user_id": a.winner_user_id,
                "global_notified": bool(a.global_notified),
                "checked": bool(a.checked),
                "views_count": a.views_count,
                "status": a.status,
                "is_relisted": bool(a.is_relisted),
            } for a in auctions_qs
        ]

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

    # Check if the user is admin using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        if user_obj.role != 'admin':
            logger.warning("User %s is not admin.", user_id)
            return redirect('home')
    except User.DoesNotExist:
        logger.warning("User %s is not admin.", user_id)
        return redirect('home')

    # Helper function to fetch auction data
    def fetch_auction_data(auction_id):
        try:
            a = Auction.objects.get(id=auction_id)
        except Auction.DoesNotExist:
            logger.error("Auction %s not found.", auction_id)
            raise Http404("Auction not found.")

        # Get sealed bid details
        sealed_detail = SealedBidDetail.objects.filter(auction_id=auction_id).first()

        auction_data = {
            'id': a.id,
            'user_id': a.user_id,
            'title': a.title,
            'description': a.description,
            'category': a.category,
            'starting_price': float(a.starting_price) if a.starting_price is not None else None,
            'reserve_price': float(a.reserve_price) if a.reserve_price is not None else None,
            'bid_increment': float(a.bid_increment) if a.bid_increment is not None else None,
            'start_date': a.start_date.isoformat() if a.start_date else None,
            'end_date': a.end_date.isoformat() if a.end_date else None,
            'created_at': a.created_at.isoformat() if a.created_at else None,
            'updated_at': a.updated_at.isoformat() if a.updated_at else None,
            'category_id': a.category_id,
            'current_bid': float(a.current_bid) if a.current_bid is not None else None,
            'is_make_offer_enabled': bool(a.is_make_offer_enabled),
            'buy_it_now_price': float(a.buy_it_now_price) if a.buy_it_now_price is not None else None,
            'auction_type': a.auction_type,
            'condition': a.condition,
            'condition_description': a.condition_description,
            'winner_user_id': a.winner_user_id,
            'global_notified': bool(a.global_notified),
            'checked': bool(a.checked),
            'views_count': a.views_count,
            'status': a.status,
            'is_relisted': bool(a.is_relisted),
            'winner_selection_date': sealed_detail.winner_selection_date.isoformat() if sealed_detail and sealed_detail.winner_selection_date else None,
        }

        image_paths = AuctionImage.objects.filter(auction_id=auction_id).values_list('image_path', flat=True)
        auction_image_paths = [f"/media/auction_images/{img}" for img in image_paths]
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

            # Update auction using ORM
            Auction.objects.filter(id=auction_id).update(
                title=title, description=description, category=category,
                starting_price=starting_price, reserve_price=reserve_price,
                bid_increment=bid_increment, start_date=start_date, end_date=end_date,
                category_id=category_id, current_bid=current_bid,
                is_make_offer_enabled=is_make_offer_enabled, buy_it_now_price=buy_it_now_price,
                auction_type=auction_type, condition=condition,
                condition_description=condition_description, winner_user_id=winner_user_id,
                global_notified=global_notified, checked=checked,
                views_count=views_count, status=status, is_relisted=is_relisted,
            )

            # Update or insert winner_selection_date using ORM
            if auction_type == 'sealed' and winner_selection_date:
                SealedBidDetail.objects.update_or_create(
                    auction_id=auction_id,
                    defaults={'winner_selection_date': winner_selection_date}
                )

            # Handle image uploads
            if 'images' in request.FILES:
                uploaded_files = request.FILES.getlist('images')
                for file in uploaded_files:
                    file_name = f"auction_{auction_id}_{file.name}"
                    file_path = os.path.join(settings.MEDIA_ROOT, "auction_images", file_name)
                    with default_storage.open(file_path, 'wb+') as destination:
                        for chunk in file.chunks():
                            destination.write(chunk)
                    AuctionImage.objects.create(auction_id=auction_id, image_path=file_name)

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

        # Check admin permissions using ORM
        user_id = request.session.get('user_id')
        try:
            user_obj = User.objects.get(id=user_id)
            if not user_obj.role:
                return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

        # Delete from filesystem
        file_path = os.path.join(settings.MEDIA_ROOT, "auction_images", image_path)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug("Deleted file from disk: %s", file_path)
            except Exception as e:
                logger.exception("Failed to delete file %s: %s", file_path, e)

        # Delete from database using ORM
        deleted_count, _ = AuctionImage.objects.filter(auction_id=auction_id, image_path=image_path).delete()
        if deleted_count > 0:
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

    # Admin role check using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        if user_obj.role != 'admin':
            messages.error(request, "You are not authorized to access this page.")
            return redirect('auth_user')
    except User.DoesNotExist:
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

    # Admin role check using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        if user_obj.role != 'admin':
            return JsonResponse({"error": "You are not authorized to access this page."}, status=403)
    except User.DoesNotExist:
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

    # Admin role check using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        if user_obj.role != 'admin':
            return JsonResponse({"success": False, "error": "You are not authorized to perform this action."}, status=403)
    except User.DoesNotExist:
        return JsonResponse({"success": False, "error": "You are not authorized to perform this action."}, status=403)

    try:
        deleted_count, _ = Feedback.objects.filter(id=feedback_id).delete()
        if deleted_count > 0:
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

    # Admin role check using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        if user_obj.role != 'admin':
            logger.error(f"Unauthorized access to reply_feedback by user_id {user_id}")
            return JsonResponse({"success": False, "error": "You are not authorized to perform this action."}, status=403)
    except User.DoesNotExist:
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

    # Admin role check using ORM
    try:
        user_obj = User.objects.get(id=user_id)
        if user_obj.role != 'admin':
            return JsonResponse({"error": "You are not authorized to access this page."}, status=403)
    except User.DoesNotExist:
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