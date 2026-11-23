"""Middleware that forces an officer to change a temporary password.

After the administrator creates an officer with a temporary credential, the
account carries ``must_change_password = True``. Until the officer sets a new
password every request is redirected to the change-password page. Only a small
allow-list of paths (static files, media, logout and the change form itself)
remains reachable.
"""
from django.shortcuts import redirect

ALLOWED_PREFIXES = ('/account/force-password/', '/logout/', '/static/', '/media/')


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (user is not None and user.is_authenticated
                and getattr(user, 'must_change_password', False)
                and not any(request.path.startswith(prefix) for prefix in ALLOWED_PREFIXES)):
            return redirect('force_password_change')
        return self.get_response(request)
