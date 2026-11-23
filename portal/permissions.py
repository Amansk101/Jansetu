"""Officer module and category permissions.

An officer with an empty permission list is treated as unrestricted, which
keeps the default behaviour for accounts created before this feature existed.
The administrator can restrict an officer to specific modules or application
categories, and every officer-facing view checks these helpers server side.
"""
from django.db.models import Q
from .models import Application, MODULES

MODULE_KEYS = [key for key, _ in MODULES]


def officer_record(user):
    return getattr(user, 'officer_record', None)


def officer_department_id(user):
    record = officer_record(user)
    return record.department_id if record else None


def officer_visible_q(user):
    """Applications an officer may see: the ones assigned to them plus every
    case routed to their department. An officer with neither sees nothing.
    """
    query = Q(assigned_officer=user)
    department_id = officer_department_id(user)
    if department_id:
        query |= Q(department_id=department_id)
    return query


def officer_modules(user):
    record = officer_record(user)
    if not record or not record.allowed_modules:
        return list(MODULE_KEYS)
    return [m for m in record.allowed_modules if m in MODULE_KEYS]


def officer_can(user, module):
    return module in officer_modules(user)


def officer_categories(user):
    record = officer_record(user)
    if not record or not record.allowed_categories:
        return list(Application.Category.values)
    return [c for c in record.allowed_categories if c in Application.Category.values]


def officer_can_category(user, category):
    return category in officer_categories(user)
