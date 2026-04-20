from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('profman/', views.profman, name='profman'),
    path('verify-email-profile/', views.verify_email_profile, name='verify_email_profile'),
    path('check_otp_status/', views.check_otp_status, name='check_otp_status'),
    path('', views.home, name='home'),
    path('auth/', views.auth_page, name='auth_page'),  # Combined login/signup page
    path('signup/', views.signup, name='signup'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),  # Add logout if needed

    path('udash/', views.udash, name='udash'),  # User dashboard
    path('otp_verify/', views.otp_verify, name='otp_verify'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    path('fopass/', views.fopass, name='fopass'),
    path('repass/', views.repass, name='repass'),
    path('my_auc/', views.my_auc, name='my_auc'),
    path('auct_list/', views.auct_list, name='auct_list'),
    path('place_bid/<int:auction_id>/', views.place_bid, name='place_bid'),
    path('auct_deta/<int:auction_id>/', views.auct_deta, name='auct_deta'),
    path('myauc_deta/<int:auction_id>/', views.myauc_deta, name='myauc_deta'),
    path('delete_auc/<int:auction_id>/', views.delete_auc, name='delete_auc'),
    path('auction/<int:auction_id>/relist/', views.relist_auction, name='relist_auction'),
    path('auction/edit/<int:auction_id>/', views.edit_auction, name='edit_auction'),
    path('bidding-history/', views.bidding_history, name='bidding_history'),
    path('create_auction/', views.create_auction, name='create_auction'),
    path('upgrade/', views.upgrade, name='upgrade'),
    path('add_to_watchlist/<int:auction_id>/', views.add_to_watchlist, name='add_to_watchlist'),
    path('watchlist/', views.watchlist, name='watchlist'),
    path('watchlist/remove/<int:auction_id>/', views.remove_from_watchlist, name='remove_watchlist'),
    path('auction/<int:auction_id>/bid/', views.place_sealed_bid, name='place_sealed_bid'),
    path('sealed_thanks/<int:auction_id>/', views.sealed_thanks, name='sealed_thanks'),
    path('ajax/auction/<int:auction_id>/winner/', views.get_winner_details, name='get_winner_details'),
    path('my_bids/', views.my_bids, name='my_bids'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('about/', views.about, name='about'),
    path('terms-and-conditions/', views.terms_conditions, name='terms_conditions'),
    path('bidding-restricted/', views.bidding_restricted, name='bidding_restricted'),
    path('auction/<int:auction_id>/offer/', views.make_offer, name='make_offer'),
    path('offer/<int:offer_id>/accept/', views.accept_offer, name='accept_offer'),
    path('offer/<int:offer_id>/reject/', views.reject_offer, name='reject_offer'),
    path('seller/offers/', views.view_offers, name='view_offers'),
    path('offer/<int:offer_id>/accept-second-winner/', views.accept_second_winner_offer, name='accept_second_winner_offer'),
    path('offer/<int:offer_id>/reject-second-winner/', views.reject_second_winner_offer, name='reject_second_winner_offer'),
    path('offer/<int:offer_id>/checkout/', views.checkout_offer, name='checkout_offer'),
    path('offer/<int:offer_id>/second-winner-checkout/', views.offer_checkout, name='offer_checkout'),
    path("notifications/", views.notifications_page, name="notifications_page"),
    path('notifications/mark-read/<int:notification_id>/', views.mark_notification_read,name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read,name='mark_all_notifications_read'),
    path('notifications/delete/<int:notification_id>/', views.delete_notification,name='delete_notification'),
    path('notifications/delete-all/', views.delete_all_notifications, name='delete_all_notifications'),
    path('payment/', views.payment_page, name='payment_page'),
    path('buy_it_now_payment/<int:auction_id>/', views.buy_it_now_payment, name='buy_it_now_payment'),
    path('orders/', views.view_orders, name='view_orders'),
    path('orders/<int:order_id>/', views.view_orders, name='view_orders'),
    path('submit/', views.submit_feedback, name='submit_feedback'),



    path('update-shipping/', views.update_shipping_details, name='update_shipping_details'),
    path('seller/confirm-order/', views.seller_confirm_order, name='seller_confirm_order'),
    path('seller/cancel-order/', views.seller_cancel_order, name='seller_cancel_order'),
    path('add_review/', views.add_review, name='add_review'),




    path('wallet/', views.wallet_dashboard, name='wallet'),
    path('wallet/deposit/', views.deposit_wallet, name='wallet_deposit'),
    path('wallet/withdraw/', views.withdraw_wallet, name='wallet_withdraw'),






    path('validate-payment/', views.validate_payment, name='validate_payment'),
    path('validate-card-data/', views.validate_card_data_view, name='validate_card_data'),
    path('validate-paypal/', views.validate_paypal_view, name='validate_paypal'),
    path('validate-bank-transfer/', views.validate_bank_transfer_view, name='validate_bank_transfer'),
    path('validate-crypto/', views.validate_crypto_view, name='validate_crypto'),














    path("contact_seller/", views.contact_seller, name="contact_seller"),
    path("messages_received/", views.messages_received, name="messages_received"),  # ✅ Add this
    path("seller_inbox/", views.seller_inbox, name="seller_inbox"),
    path("chat/<int:buyer_id>/", views.chat_detail, name="chat_detail"),
    path("delete_conversation/<int:buyer_id>/", views.delete_conversation, name="delete_conversation"),
    path("clear-chat/", views.clear_chat, name="clear_chat"),
    path("report-block/", views.report_block_user, name="report_block_user"),



# admin


    path('adash/', views.adash, name='adash'),  # Admin dashboard
    path('users/', views.list_users, name='list_users'),
    path('users/<int:user_id>/', views.manage_user, name='manage_user'),  # Combined view for viewing/editing a user
    path('user/<int:user_id>/delete/', views.admin_delete_user, name='admin_delete_user'),
    path('auction/<int:auction_id>/', views.admin_auct_deta, name='admin_auct_deta'),
    path('auction/<int:auction_id>/stop/', views.stop_auction, name='stop_auction'),
    path('auction/<int:auction_id>/resume/', views.resume_auction, name='resume_auction'),
    path('auction/<int:auction_id>/edit/', views.admin_edit_auction, name='admin_edit_auction'),
    path('auction/<int:auction_id>/bids/', views.admin_view_bids, name='admin_view_bids'),
    path('auction/<int:auction_id>/delete/', views.admin_delete_auction, name='admin_delete_auction'),
    path('auction/<int:auction_id>/orders/', views.auction_orders, name='auction_orders'),
    path('auctions/', views.admin_auction_list, name='admin_auction_list'),
    path('delete_auction_image/', views.delete_auction_image, name='delete_auction_image'),
    path('banned/', views.banned_page, name='banned_page'),
    path('payment-details/', views.payment_details, name='payment_details'),
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('edit-invoice/<str:invoice_id>/', views.edit_invoice, name='edit_invoice'),
    path('feedbacks/', views.admin_feedback, name='admin_feedback'),
    path('feedbacks/delete/<int:feedback_id>/', views.delete_feedback, name='delete_feedback'),
    path('feedbacks/reply/<int:feedback_id>/', views.reply_feedback, name='reply_feedback'),
    path('feedbacks/api/', views.feedback_api, name='feedback_api'),
    path('feedbacks/initial/', views.initial_feedback, name='initial_feedback'),
    path('process-manual-fund-distribution/<int:fund_id>/', views.process_manual_fund_distribution, name='process_manual_fund_distribution'),








    path('chatbot_response/', views.chatbot_response, name='chatbot_response'),
    path('get_new_questions/', views.get_new_questions, name='get_new_questions'),
    path('chatbot_user_response/', views.chatbot_user_response, name='chatbot_user_response'),
    path('get_intents/', views.get_intents, name='get_intents'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


