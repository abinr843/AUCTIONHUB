from django.contrib import admin
from .models import (
    User, Category, Auction, AuctionImage, Bid, Offer, Invoice, Order,
    Notification, Watchlist, Message, Feedback, FeedbackReply, PaymentDetail,
    FundDistribution, SellerPayout, ShippingDetail, MembershipPlan, PremiumUser,
    PlatformCommission, SealedBidDetail, UserActivity, UserOTP, Wallet,
    BankCard, ReportedUser, Review,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'email', 'role', 'premium', 'account_status', 'email_verified')
    list_filter = ('role', 'premium', 'account_status', 'email_verified', 'bidding_restricted')
    search_fields = ('username', 'email')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'auction_type', 'status', 'starting_price', 'current_bid', 'start_date', 'end_date')
    list_filter = ('auction_type', 'status')
    search_fields = ('title', 'description')


@admin.register(AuctionImage)
class AuctionImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'auction', 'image_path', 'uploaded_at')


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('id', 'auction', 'user', 'amount', 'bid_time', 'is_proxy')
    list_filter = ('is_proxy',)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ('id', 'auction', 'buyer', 'offer_price', 'status', 'second_winner_offer')
    list_filter = ('status', 'second_winner_offer')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'auction', 'buyer', 'seller', 'amount_due', 'status', 'issue_date', 'due_date')
    list_filter = ('status',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'auction', 'user', 'payment_status', 'payment_amount', 'order_status', 'shipping_status')
    list_filter = ('order_status', 'payment_status', 'shipping_status')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'is_read', 'created_at')
    list_filter = ('is_read',)


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'auction', 'auction_type', 'added_on')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'receiver', 'auction', 'timestamp')


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'email', 'subject', 'created_at')
    search_fields = ('name', 'email', 'subject')


@admin.register(FeedbackReply)
class FeedbackReplyAdmin(admin.ModelAdmin):
    list_display = ('id', 'feedback', 'admin', 'created_at')


@admin.register(PaymentDetail)
class PaymentDetailAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'payment_method', 'payment_status', 'payment_amount', 'payment_date')
    list_filter = ('payment_method', 'payment_status')


@admin.register(FundDistribution)
class FundDistributionAdmin(admin.ModelAdmin):
    list_display = ('id', 'auction', 'seller', 'platform_share', 'seller_share', 'status')
    list_filter = ('status',)


@admin.register(SellerPayout)
class SellerPayoutAdmin(admin.ModelAdmin):
    list_display = ('payout_id', 'seller', 'auction', 'payout_amount', 'payout_status')
    list_filter = ('payout_status',)


@admin.register(ShippingDetail)
class ShippingDetailAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'buyer', 'full_name', 'city', 'country')


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ('plan_id', 'plan_name', 'price', 'regular_auction_limit', 'sealed_bid_limit')


@admin.register(PremiumUser)
class PremiumUserAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'plan', 'premium_start_date', 'premium_end_date')


@admin.register(PlatformCommission)
class PlatformCommissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'auction_type', 'commission_percentage', 'status')
    list_filter = ('auction_type', 'status')


@admin.register(SealedBidDetail)
class SealedBidDetailAdmin(admin.ModelAdmin):
    list_display = ('id', 'auction', 'winner_selection_date')


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'description', 'date')


@admin.register(UserOTP)
class UserOTPAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'otp', 'created_at', 'expires_at')


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'balance', 'updated_at')


@admin.register(BankCard)
class BankCardAdmin(admin.ModelAdmin):
    list_display = ('id', 'card_holder', 'bank_name', 'status')


@admin.register(ReportedUser)
class ReportedUserAdmin(admin.ModelAdmin):
    list_display = ('id', 'reported_by', 'reported_user', 'report_date')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'user', 'rating', 'created_at')
    list_filter = ('rating',)
