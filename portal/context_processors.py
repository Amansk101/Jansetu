def unread_notifications(request):
    if request.user.is_authenticated:
        return {'unread_count': request.user.notifications.filter(read=False).count()}
    return {'unread_count': 0}


def officer_permissions(request):
    """Expose the signed-in officer's allowed modules so the sidebar can hide
    links they are not permitted to open. Server-side checks remain the source
    of truth; this only keeps the navigation honest."""
    from .models import MODULES
    from .permissions import officer_modules
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated and user.role == 'officer':
        return {'allowed_modules': officer_modules(user), 'module_choices': list(MODULES)}
    return {'allowed_modules': None, 'module_choices': list(MODULES)}
