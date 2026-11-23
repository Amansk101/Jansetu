from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from .emails import (DEFAULT_TEMPLATES_BY_KIND, notify, render_text, send_direct_message_email, send_email,
                     send_officer_activation_email)
from .forms import CompensationConfigForm, DepartmentForm, DirectMessageForm, EmailTemplateForm, EligibilityRuleForm, SchemeForm, StaffAccountForm
from .models import Application, ApplicationAssignment, AuditLog, CompensationConfiguration, Department, EligibilityRule, EmailLog, EmailTemplate, MODULES, Notification, Officer, Scheme, User, UserProfile
from .views import role_required

TEMP_PASSWORD_ALPHABET = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789@#%'

def _temp_password():
    return get_random_string(settings.OFFICER_TEMP_PASSWORD_BYTES, TEMP_PASSWORD_ALPHABET)

def _unique_officer_username(first_name='', last_name=''):
    base = slugify(f'{first_name} {last_name}')[:24] or 'officer'
    candidate, n = base, 1
    while User.objects.filter(username=candidate).exists():
        n += 1
        candidate = f'{base}{n}'
    return candidate


def _save_config(request, form, action):
    obj = form.save()
    AuditLog.objects.create(actor=request.user, action=action, detail=str(obj))
    messages.success(request, 'Saved.')
    return obj

@role_required(User.Role.ADMIN)
def reports(request):
    qs = Application.objects.select_related('citizen', 'assigned_officer', 'department', 'scheme')
    if request.GET.get('status') in Application.Status.values:
        qs = qs.filter(status=request.GET['status'])
    if request.GET.get('category') in Application.Category.values:
        qs = qs.filter(category=request.GET['category'])
    if request.GET.get('department', '').isdigit():
        qs = qs.filter(department_id=request.GET['department'])
    return render(request, 'administrator/reports.html', {
        'applications': qs.order_by('-created_at')[:200],
        'total': qs.count(),
        'by_status': qs.values('status').annotate(n=Count('id')),
        'categories': Application.Category.choices,
        'statuses': Application.Status.choices,
        'departments': Department.objects.filter(active=True),
    })

@role_required(User.Role.ADMIN)
def manage_departments(request):
    instance = Department.objects.filter(pk=request.GET.get('edit')).first()
    if request.method == 'POST':
        if request.POST.get('action') == 'delete':
            Department.objects.filter(pk=request.POST.get('id')).delete()
            messages.success(request, 'Department removed.')
            return redirect('manage_departments')
        form = DepartmentForm(request.POST, instance=Department.objects.filter(pk=request.POST.get('id')).first())
        if form.is_valid():
            _save_config(request, form, 'department_saved')
            return redirect('manage_departments')
    else:
        form = DepartmentForm(instance=instance)
    return render(request, 'administrator/manage.html', {'title': 'Departments', 'form': form, 'rows': Department.objects.annotate(officers_n=Count('officers'), cases=Count('applications')), 'kind': 'department', 'edit': instance})

@role_required(User.Role.ADMIN)
def manage_schemes(request):
    instance = Scheme.objects.filter(pk=request.GET.get('edit')).first()
    if request.method == 'POST':
        if request.POST.get('action') == 'toggle':
            scheme = Scheme.objects.filter(pk=request.POST.get('id')).first()
            if scheme:
                scheme.active = not scheme.active
                scheme.save(update_fields=['active'])
                messages.success(request, f'{scheme.name} {"activated" if scheme.active else "marked inactive"}.')
            return redirect('manage_schemes')
        form = SchemeForm(request.POST, instance=Scheme.objects.filter(pk=request.POST.get('id')).first())
        if form.is_valid():
            _save_config(request, form, 'scheme_saved')
            return redirect('manage_schemes')
    else:
        form = SchemeForm(instance=instance)
    return render(request, 'administrator/manage.html', {'title': 'Government schemes', 'form': form, 'rows': Scheme.objects.annotate(cases=Count('application')), 'kind': 'scheme', 'edit': instance})

@role_required(User.Role.ADMIN)
def manage_rules(request):
    instance = EligibilityRule.objects.filter(pk=request.GET.get('edit')).first()
    if request.method == 'POST':
        if request.POST.get('action') == 'delete':
            EligibilityRule.objects.filter(pk=request.POST.get('id')).delete()
            messages.success(request, 'Rule removed.')
            return redirect('manage_rules')
        form = EligibilityRuleForm(request.POST, instance=EligibilityRule.objects.filter(pk=request.POST.get('id')).first())
        if form.is_valid():
            _save_config(request, form, 'eligibility_rule_saved')
            return redirect('manage_rules')
    else:
        form = EligibilityRuleForm(instance=instance)
    return render(request, 'administrator/manage.html', {'title': 'Eligibility rules', 'form': form, 'rows': EligibilityRule.objects.select_related('scheme'), 'kind': 'rule', 'edit': instance})

@role_required(User.Role.ADMIN)
def manage_rates(request):
    instance = CompensationConfiguration.objects.filter(pk=request.GET.get('edit')).first()
    if request.method == 'POST':
        if request.POST.get('action') == 'toggle':
            config = CompensationConfiguration.objects.filter(pk=request.POST.get('id')).first()
            if config:
                config.active = not config.active
                config.save(update_fields=['active'])
                messages.success(request, f'{config.land_category} {"activated" if config.active else "marked inactive"}. Existing estimates are unchanged.')
            return redirect('manage_rates')
        form = CompensationConfigForm(request.POST, instance=CompensationConfiguration.objects.filter(pk=request.POST.get('id')).first())
        if form.is_valid():
            _save_config(request, form, 'compensation_rate_saved')
            return redirect('manage_rates')
    else:
        form = CompensationConfigForm(instance=instance)
    return render(request, 'administrator/manage.html', {'title': 'Compensation demonstration rates', 'form': form, 'rows': CompensationConfiguration.objects.all(), 'kind': 'rate', 'edit': instance, 'disclaimer': 'These are demonstration rates for the calculator. They are not official government rates.'})

@role_required(User.Role.ADMIN)
def manage_accounts(request):
    form = StaffAccountForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle':
            account = get_object_or_404(User, pk=request.POST.get('id'))
            if account.pk == request.user.pk or account.role == User.Role.ADMIN:
                messages.error(request, 'This account cannot be changed here.')
            else:
                account.is_active = not account.is_active
                account.save(update_fields=['is_active'])
                AuditLog.objects.create(actor=request.user, action='account_status', detail=f'{account.username} active={account.is_active}')
                messages.success(request, 'Account status updated.')
            return redirect('manage_accounts')
        if action == 'delete':
            account = get_object_or_404(User, pk=request.POST.get('id'), role=User.Role.OFFICER)
            if account.pk == request.user.pk:
                messages.error(request, 'You cannot remove your own account.')
            else:
                username = account.username
                ApplicationAssignment.objects.filter(officer=account).delete()
                account.delete()
                AuditLog.objects.create(actor=request.user, action='officer_removed', detail=username)
                messages.success(request, f'Officer {username} removed. Their cases are now unassigned and need reassignment.')
            return redirect('manage_accounts')
        if action == 'reset_password':
            officer_user = get_object_or_404(User, pk=request.POST.get('id'), role=User.Role.OFFICER)
            temp_password = _temp_password()
            officer_user.set_password(temp_password)
            officer_user.must_change_password = True
            officer_user.save(update_fields=['password', 'must_change_password'])
            logs = send_officer_activation_email(officer_user, temp_password, request)
            AuditLog.objects.create(actor=request.user, action='officer_password_reset', detail=officer_user.username)
            if logs and logs[0].status == EmailLog.Status.SENT:
                messages.success(request, f'A new temporary password was emailed to {officer_user.email}. The officer must change it at first sign-in.')
            else:
                messages.warning(request, f'Email could not be delivered. New temporary password for {officer_user.username}: {temp_password} — share it securely; it must be changed at first sign-in.')
            return redirect('manage_accounts')
        if action == 'update_officer':
            officer_user = get_object_or_404(User, pk=request.POST.get('id'), role=User.Role.OFFICER)
            department = Department.objects.filter(pk=request.POST.get('department') or None).first()
            record, _ = Officer.objects.get_or_create(user=officer_user)
            record.department = department
            record.designation = request.POST.get('designation', record.designation)[:120]
            record.allowed_modules = [m for m in request.POST.getlist('allowed_modules') if m in dict(MODULES)]
            record.allowed_categories = [c for c in request.POST.getlist('allowed_categories') if c in Application.Category.values]
            record.save()
            AuditLog.objects.create(actor=request.user, action='officer_permissions', detail=f'{officer_user.username} modules={record.allowed_modules} categories={record.allowed_categories}')
            notify(officer_user, 'Your department, designation or access permissions were updated by the administrator.',
                   kind='officer_permissions_changed', subject='Your JanSutra AI access was updated',
                   body=(f'Hello {officer_user.get_full_name() or officer_user.username},\n\n'
                         'The administrator updated your JanSutra AI access.\n\n'
                         f'Department: {record.department.name if record.department else "Unassigned"}\n'
                         f'Designation: {record.designation or "Not set"}\n'
                         f'Allowed modules: {", ".join(record.allowed_modules) or "All modules"}\n'
                         f'Allowed categories: {", ".join(record.allowed_categories) or "All categories"}\n\n'
                         'Sign in to your workspace to see the updated access.\n'))
            messages.success(request, f'Updated {officer_user.username}: department, designation and access permissions saved.')
            return redirect('manage_accounts')
        form = StaffAccountForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            username = data.get('username') or _unique_officer_username(data.get('first_name', ''), data.get('last_name', ''))
            temp_password = data.get('password') or _temp_password()
            user = User.objects.create_user(
                username=username, password=temp_password,
                first_name=data.get('first_name', ''), last_name=data.get('last_name', ''),
                email=data['email'], role=User.Role.OFFICER,
            )
            user.email_verified = True
            user.must_change_password = True
            user.save(update_fields=['email_verified', 'must_change_password'])
            UserProfile.objects.get_or_create(user=user)
            Officer.objects.create(
                user=user, department=data.get('department'), designation=data.get('designation') or 'Review Officer',
                allowed_modules=data.get('allowed_modules') or [], allowed_categories=data.get('allowed_categories') or [],
            )
            logs = send_officer_activation_email(user, temp_password, request)
            AuditLog.objects.create(actor=request.user, action='account_created', detail=user.username)
            if logs and logs[0].status == EmailLog.Status.SENT:
                messages.success(request, f'Officer {username} created. An activation email with the temporary password was sent to {user.email}.')
            else:
                messages.warning(request, f'Officer {username} created. Email delivery failed, so share this temporary password securely: {temp_password} — the officer must change it at first sign-in.')
            return redirect('manage_accounts')
    accounts = User.objects.filter(role=User.Role.OFFICER).select_related('officer_record__department').order_by('username')
    return render(request, 'administrator/accounts.html', {'form': form, 'accounts': accounts, 'departments': Department.objects.filter(active=True), 'modules': MODULES, 'categories': Application.Category.choices})


@role_required(User.Role.ADMIN)
def email_log(request):
    logs = EmailLog.objects.select_related('user', 'application').order_by('-created_at')
    if request.GET.get('status') in EmailLog.Status.values:
        logs = logs.filter(status=request.GET['status'])
    if request.GET.get('kind'):
        logs = logs.filter(kind__icontains=request.GET['kind'])
    notifications_qs = Notification.objects.select_related('recipient', 'application').order_by('-created_at')
    return render(request, 'administrator/email_log.html', {
        'logs': Paginator(logs, 30).get_page(request.GET.get('page')),
        'notifications': notifications_qs[:40],
        'statuses': EmailLog.Status.choices,
        'filter_kind': request.GET.get('kind', ''),
        'filter_status': request.GET.get('status', ''),
        'modules': MODULES,
    })


@role_required(User.Role.ADMIN)
def send_direct_email(request):
    """Collector sends a free-text email to a chosen officer or citizen."""
    prefill = request.GET.get('to', '')
    if request.method == 'POST':
        form = DirectMessageForm(request.POST)
        if form.is_valid():
            recipient = get_object_or_404(User, pk=form.cleaned_data['recipient'])
            subject = form.cleaned_data['subject']
            logs = send_direct_message_email(recipient, subject, form.cleaned_data['message'])
            Notification.objects.create(recipient=recipient, message=f'Message from the Collector: {subject}'[:250])
            AuditLog.objects.create(actor=request.user, action='admin_message_sent', detail=f'{recipient.username}: {subject}')
            if logs and logs[0].status == EmailLog.Status.SENT:
                messages.success(request, f'Email sent to {recipient.get_full_name() or recipient.username} at {recipient.email}.')
            else:
                messages.error(request, f'The email to {recipient.email} could not be delivered. Check the Notifications log for the SMTP error.')
            return redirect('send_direct_email')
    else:
        initial = {'recipient': prefill} if prefill.isdigit() else None
        form = DirectMessageForm(initial=initial)
    return render(request, 'administrator/messaging.html', {
        'form': form,
        'modules': MODULES,
        'sent': EmailLog.objects.filter(kind='admin_message').select_related('user').order_by('-created_at')[:25],
        'recipient_count': User.objects.filter(role__in=[User.Role.OFFICER, User.Role.CITIZEN], is_active=True).exclude(email='').count(),
    })


# Sample values used to preview and test an email template without a real case.
SAMPLE_EMAIL_CONTEXT = {
    'name': 'Rohan Naik', 'username': 'rohan.naik',
    'application_id': 'JS-DEMO-0001', 'service': 'Income Certificate',
    'status': 'Verification Pending', 'certificate_number': 'JS/CERT/2026/00001',
    'verification_code': 'A1B2C3D4', 'remarks': 'Please upload a clearer copy of the income proof.',
    'message': 'This is a sample message written by the Collector.',
    'link': 'https://example.org/verify/sample-account',
    'temp_password': 'SampleTmp#92',
    'login_link': 'https://example.org/portal/login',
    'dashboard_link': 'https://example.org/portal/dashboard',
}


@role_required(User.Role.ADMIN)
def manage_email_templates(request):
    """Administrator console: edit the subject and body of every notification email."""
    if request.method == 'POST':
        row = EmailTemplate.objects.filter(pk=request.POST.get('id')).first()
        action = request.POST.get('action') or 'save'
        if row is None:
            messages.error(request, 'Choose an email template first.')
            return redirect('manage_email_templates')
        if action == 'toggle':
            row.active = not row.active
            row.save(update_fields=['active', 'updated_at'])
            messages.success(request, f'{row.name} {"enabled" if row.active else "disabled"}.')
            return redirect(f'{reverse("manage_email_templates")}?edit={row.pk}')
        if action == 'reset':
            default = DEFAULT_TEMPLATES_BY_KIND.get(row.kind)
            if default:
                row.name, row.description = default['name'], default['description']
                row.placeholders, row.subject, row.body = default['placeholders'], default['subject'], default['body']
                row.active = True
                row.save()
                AuditLog.objects.create(actor=request.user, action='email_template_reset', detail=row.kind)
                messages.success(request, f'{row.name} has been reset to the built-in text.')
            return redirect(f'{reverse("manage_email_templates")}?edit={row.pk}')
        if action == 'test':
            subject, body = render_text(row.subject, row.body, extra=SAMPLE_EMAIL_CONTEXT)
            logs = send_email(row.kind, f'[TEST] {subject}', body, [request.user.email] or [], user=request.user)
            if logs and logs[0].status == EmailLog.Status.SENT:
                messages.success(request, f'A test email was sent to {request.user.email}.')
            else:
                messages.error(request, 'The test email could not be delivered. Check the Notifications log for the SMTP error.')
            return redirect(f'{reverse("manage_email_templates")}?edit={row.pk}')
        form = EmailTemplateForm(request.POST, instance=row)
        if form.is_valid():
            template = form.save()
            AuditLog.objects.create(actor=request.user, action='email_template_saved', detail=template.kind)
            messages.success(request, f'{template.name} saved. New emails use this text immediately.')
            return redirect(f'{reverse("manage_email_templates")}?edit={template.pk}')
        messages.error(request, 'Please correct the highlighted errors.')
        edit, preview_form = row, form
    else:
        edit, preview_form = EmailTemplate.objects.filter(pk=request.GET.get('edit')).first(), None

    form = preview_form or EmailTemplateForm(instance=edit)
    preview = None
    if edit is not None:
        subject, body = render_text(edit.subject, edit.body, extra=SAMPLE_EMAIL_CONTEXT)
        preview = {'subject': subject, 'body': body}
    return render(request, 'administrator/email_templates.html', {
        'title': 'Email notification templates', 'form': form, 'edit': edit, 'preview': preview,
        'sample': SAMPLE_EMAIL_CONTEXT,
        'rows': EmailTemplate.objects.all(),
        'defaults': DEFAULT_TEMPLATES_BY_KIND,
    })
