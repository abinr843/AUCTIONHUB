from django.shortcuts import redirect
from django.urls import reverse
from django.db import connection

class BannedUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Skip if the user is not authenticated or if there's no session user_id
        if not hasattr(request, 'session') or 'user_id' not in request.session:
            return None

        user_id = request.session.get('user_id')
        if not user_id:
            return None

        # Check the user's account_status
        with connection.cursor() as cursor:
            cursor.execute("SELECT account_status FROM users WHERE id = %s", [user_id])
            row = cursor.fetchone()
            if not row:
                return None  # User doesn't exist, let the view handle it

            account_status = row[0]

        # If the user is banned
        if account_status == 'banned':
            # Allow access only to the banned page
            banned_url = reverse('banned_page')  # URL name for the banned page
            if request.path != banned_url:
                return redirect(banned_url)

        return None  # Proceed to the view if not banned