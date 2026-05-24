from django.db import models
from django.utils import timezone


class User(models.Model):
    """Maps to the existing 'users' table."""
    ROLE_CHOICES = [
        ('user', 'User'),
        ('admin', 'Admin'),
    ]
    ACCOUNT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('banned', 'Banned'),
    ]

    username = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, unique=True)
    password_hash = models.CharField(max_length=255)
    salt = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    role = models.CharField(max_length=5, choices=ROLE_CHOICES, default='user')
    email_verified = models.BooleanField(default=False)
    is_authenticated = models.BooleanField(default=False)
    bidding_restricted = models.BooleanField(default=False)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    paypal_email = models.CharField(max_length=100, blank=True, null=True)
    profile_picture = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    email_notifications = models.BooleanField(default=False)
    sms_notifications = models.BooleanField(default=False)
    pincode = models.CharField(max_length=10, blank=True, null=True)
    membership_plan_id = models.IntegerField(blank=True, null=True)
    premium = models.BooleanField(default=False)
    account_status = models.CharField(max_length=20, choices=ACCOUNT_STATUS_CHOICES, default='pending')
    id_proof = models.CharField(max_length=255, blank=True, null=True)
    restriction_notified = models.BooleanField(default=False)
    selfie = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'users'

    def __str__(self):
        return self.username


class Category(models.Model):
    """Maps to the existing 'categories' table."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'categories'

    def __str__(self):
        return self.name


class Auction(models.Model):
    """Maps to the existing 'auctions' table."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('sold', 'Sold'),
        ('stopped', 'Stopped'),
    ]
    AUCTION_TYPE_CHOICES = [
        ('regular', 'Regular'),
        ('buy_it_now', 'Buy It Now'),
        ('sealed_bid', 'Sealed Bid'),
    ]
    CONDITION_CHOICES = [
        ('new', 'New'),
        ('like_new', 'Like New'),
        ('used', 'Used'),
        ('refurbished', 'Refurbished'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auctions')
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=100, blank=True, null=True)
    starting_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    reserve_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    bid_increment = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    category_id_fk = models.ForeignKey(
        Category, on_delete=models.SET_NULL, blank=True, null=True,
        db_column='category_id', related_name='auctions'
    )
    current_bid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_make_offer_enabled = models.BooleanField(default=False)
    buy_it_now_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    auction_type = models.CharField(max_length=20, choices=AUCTION_TYPE_CHOICES)
    condition = models.CharField(max_length=255, blank=True, null=True)
    condition_description = models.TextField(blank=True, null=True)
    winner_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, blank=True, null=True,
        related_name='won_auctions', db_column='winner_user_id'
    )
    global_notified = models.BooleanField(default=False)
    checked = models.BooleanField(default=False)
    views_count = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    is_relisted = models.BooleanField(default=False)
    relist_notified = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'auctions'

    def __str__(self):
        return self.title


class AuctionImage(models.Model):
    """Maps to the existing 'auction_images' table."""
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='images')
    image_path = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'auction_images'

    def __str__(self):
        return f"Image for Auction #{self.auction_id}"


class Bid(models.Model):
    """Maps to the existing 'bids' table."""
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='bids')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bids')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    current_bid = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    bid_time = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_proxy = models.BooleanField(default=False)
    proxy_max_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'bids'

    def __str__(self):
        return f"Bid #{self.id} - ₹{self.amount} on {self.auction}"


class Offer(models.Model):
    """Maps to the existing 'offers' table."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]

    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='offers')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='offers_made', db_column='buyer_id')
    offer_price = models.DecimalField(max_digits=10, decimal_places=2)
    offer_message = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    second_winner_offer = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'offers'

    def __str__(self):
        return f"Offer #{self.id} - ₹{self.offer_price}"


class Invoice(models.Model):
    """Maps to the existing 'invoices' table."""
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Overdue', 'Overdue'),
    ]

    id = models.CharField(max_length=36, primary_key=True)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='invoices')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices_as_buyer', db_column='buyer_id')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices_as_seller', db_column='seller_id')
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    issue_date = models.DateTimeField()
    due_date = models.DateTimeField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    late_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    reminder_sent = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'invoices'

    def __str__(self):
        return f"Invoice {self.id}"


class Order(models.Model):
    """Maps to the existing 'orders' table."""
    order_id = models.AutoField(primary_key=True)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='orders', blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', blank=True, null=True)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='orders',
        blank=True, null=True, db_column='invoice_id'
    )
    payment_status = models.CharField(max_length=50, blank=True, null=True)
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    shipping_status = models.CharField(max_length=50, blank=True, null=True)
    shipping_address = models.TextField(blank=True, null=True)
    tracking_number = models.CharField(max_length=50, blank=True, null=True)
    order_date = models.DateTimeField(blank=True, null=True)
    delivery_date = models.DateTimeField(blank=True, null=True)
    order_status = models.CharField(max_length=50, default='Pending')
    progress = models.IntegerField(default=0)
    shipping_updated_at = models.DateTimeField(blank=True, null=True)
    last_notification_status = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'orders'

    def __str__(self):
        return f"Order #{self.order_id}"


class Notification(models.Model):
    """Maps to the existing 'notifications' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'notifications'

    def __str__(self):
        return f"Notification #{self.id} for User #{self.user_id}"


class Watchlist(models.Model):
    """Maps to the existing 'watchlist' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlist', blank=True, null=True)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='watchlist', blank=True, null=True)
    auction_type = models.CharField(max_length=255, blank=True, null=True)
    added_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'watchlist'

    def __str__(self):
        return f"Watchlist: User #{self.user_id} → Auction #{self.auction_id}"


class Message(models.Model):
    """Maps to the existing 'messages' table."""
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages', db_column='sender_id')
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='messages')
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages', db_column='receiver_id')
    attachment = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'messages'

    def __str__(self):
        return f"Message #{self.id} from User #{self.sender_id}"


class Feedback(models.Model):
    """Maps to the existing 'feedback' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedbacks', blank=True, null=True)
    name = models.CharField(max_length=255)
    email = models.CharField(max_length=255)
    subject = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    file_paths = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'feedback'

    def __str__(self):
        return f"Feedback #{self.id} by {self.name}"


class FeedbackReply(models.Model):
    """Maps to the existing 'feedback_replies' table."""
    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name='replies')
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedback_replies', db_column='admin_id')
    reply_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'feedback_replies'

    def __str__(self):
        return f"Reply #{self.id} to Feedback #{self.feedback_id}"


class PaymentDetail(models.Model):
    """Maps to the existing 'payment_details' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_details', blank=True, null=True)
    invoice_id = models.CharField(max_length=36, blank=True, null=True)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='payment_details', blank=True, null=True)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    payment_status = models.CharField(max_length=20, blank=True, null=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    debit_card_number = models.CharField(max_length=20, blank=True, null=True)
    debit_card_expiry = models.CharField(max_length=10, blank=True, null=True)
    debit_card_cvc = models.CharField(max_length=4, blank=True, null=True)
    credit_card_number = models.CharField(max_length=20, blank=True, null=True)
    credit_card_expiry = models.CharField(max_length=10, blank=True, null=True)
    credit_card_cvc = models.CharField(max_length=4, blank=True, null=True)
    paypal_email = models.CharField(max_length=100, blank=True, null=True)
    bank_account_number = models.CharField(max_length=20, blank=True, null=True)
    bank_routing_number = models.CharField(max_length=20, blank=True, null=True)
    payment_date = models.DateTimeField(blank=True, null=True)
    payment_timestamp = models.DateTimeField(auto_now_add=True)
    payment_notes = models.TextField(blank=True, null=True)
    premium_type = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'payment_details'

    def __str__(self):
        return f"Payment #{self.id} - {self.payment_method}"


class FundDistribution(models.Model):
    """Maps to the existing 'fund_distribution' table."""
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Transferred', 'Transferred'),
    ]

    invoice_id = models.CharField(max_length=50)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='fund_distributions')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fund_distributions', db_column='seller_id')
    platform_share = models.DecimalField(max_digits=10, decimal_places=2)
    seller_share = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='Pending')
    distribution_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'fund_distribution'

    def __str__(self):
        return f"Fund Distribution #{self.id}"


class SellerPayout(models.Model):
    """Maps to the existing 'seller_payouts' table."""
    payout_id = models.AutoField(primary_key=True)
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payouts', db_column='seller_id')
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='payouts')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payouts', db_column='invoice_id')
    payout_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payout_method = models.CharField(max_length=50)
    transaction_id = models.CharField(max_length=50)
    payout_status = models.CharField(max_length=20, default='Pending')
    payout_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'seller_payouts'

    def __str__(self):
        return f"Payout #{self.payout_id}"


class ShippingDetail(models.Model):
    """Maps to the existing 'shipping_details' table."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='shipping_details')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='shipping_details', db_column='invoice_id')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shipping_details', db_column='buyer_id')
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    shipping_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'shipping_details'

    def __str__(self):
        return f"Shipping for Order #{self.order_id}"


class MembershipPlan(models.Model):
    """Maps to the existing 'membership_plans' table."""
    plan_id = models.AutoField(primary_key=True)
    plan_name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    regular_auction_limit = models.IntegerField()
    sealed_bid_limit = models.IntegerField()
    wallet_credit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'membership_plans'

    def __str__(self):
        return self.plan_name


class PremiumUser(models.Model):
    """Maps to the existing 'premium_users' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='premium_subscriptions')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE, related_name='subscribers', db_column='plan_id')
    premium_start_date = models.DateTimeField()
    premium_end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'premium_users'

    def __str__(self):
        return f"Premium: {self.user} ({self.plan})"


class PlatformCommission(models.Model):
    """Maps to the existing 'platform_commission' table."""
    AUCTION_TYPE_CHOICES = [
        ('regular', 'Regular'),
        ('sealed_bid', 'Sealed Bid'),
        ('buy_now', 'Buy Now'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
    ]

    auction_type = models.CharField(max_length=10, choices=AUCTION_TYPE_CHOICES)
    commission_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    effective_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')

    class Meta:
        managed = False
        db_table = 'platform_commission'

    def __str__(self):
        return f"{self.auction_type}: {self.commission_percentage}%"


class SealedBidDetail(models.Model):
    """Maps to the existing 'sealed_bid_details' table."""
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='sealed_bid_details')
    winner_selection_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'sealed_bid_details'

    def __str__(self):
        return f"Sealed Bid for Auction #{self.auction_id}"


class UserActivity(models.Model):
    """Maps to the existing 'user_activity' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    description = models.TextField()
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'user_activity'

    def __str__(self):
        return f"Activity: {self.description[:50]}"


class UserOTP(models.Model):
    """Maps to the existing 'user_otp' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'user_otp'

    def __str__(self):
        return f"OTP for User #{self.user_id}"


class Wallet(models.Model):
    """Maps to the existing 'wallets' table."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallets')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'wallets'

    def __str__(self):
        return f"Wallet for User #{self.user_id}: ₹{self.balance}"


class BankCard(models.Model):
    """Maps to the existing 'bank_cards' table."""
    card_number = models.CharField(max_length=20)
    card_holder = models.CharField(max_length=255)
    expiration_date = models.DateField()
    cvv = models.CharField(max_length=4)
    bank_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = 'bank_cards'

    def __str__(self):
        return f"Card ending in {self.card_number[-4:]}"


class ReportedUser(models.Model):
    """Maps to the existing 'reported_users' table."""
    reported_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='reports_made',
        db_column='reported_by'
    )
    reported_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='reports_received',
        db_column='reported_user'
    )
    reason = models.TextField()
    report_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'reported_users'

    def __str__(self):
        return f"Report #{self.id}"


class Review(models.Model):
    """Maps to the existing 'reviews' table."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    rating = models.IntegerField(blank=True, null=True)
    reasons = models.TextField(blank=True, null=True)
    comments = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'reviews'

    def __str__(self):
        return f"Review #{self.id} - {self.rating}★"
class BiddingHistory(models.Model):
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='history_bids')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='history_bids')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    time = models.DateTimeField(auto_now_add=True)
    is_winner = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'bidding_history'

class AuctionWinner(models.Model):
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='winners')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='won_bids')
    win_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    win_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'auction_winners'

class BlockedUser(models.Model):
    blocked_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocked_users_by', db_column='blocked_by')
    blocked_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='users_blocked', db_column='blocked_user')
    block_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'blocked_users'
