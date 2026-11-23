import csv
from functools import wraps
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.http import FileResponse, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .emails import DEFAULT_TEMPLATES_BY_KIND, decode_uid, notify, render_template, send_email, send_password_reset_email
from .forms import (ApplicationForm, CertificateTemplateForm, DocumentForm, GovernmentServiceForm,
                    ProfileForm, RegisterForm, ServiceDocumentRequirementForm)
from .models import (AIAnalysisReport, Application, ApplicationAssignment, ApplicationDocument, ApplicationField,
                     ApplicationRemark, ApplicationStatusHistory, AnomalyFlag, AuditLog, CertificateTemplate,
                     CompensationConfiguration, CorrectionRequest, Department, EmailLog, GeneratedCertificate,
                     GovernmentService, Notification, OfficerRemark, Scheme, ServiceDocumentRequirement, User)
from .permissions import officer_can, officer_can_category, officer_categories, officer_department_id, officer_visible_q
from .services import process_document, assess_eligibility, calculate_compensation, change_status, delay_risk, potential_duplicates, refresh_anomalies, sync_extracted_rows, assistant_answer, department_for_category, required_documents, REQUIRED_DOCUMENTS, SERVICE_CATALOG, ALLOWED_EXTENSIONS, application_documents, application_requirements, application_service, build_certificate_pdf, document_check, generate_certificate, risk_category, save_application_documents, write_analysis_report

CATEGORY_FIELDS = {
    'welfare': ('beneficiary_type', 'family_members'),
    'disaster': ('disaster_type', 'loss_summary'),
    'land': ('survey_number', 'ownership'),
    'revenue': ('service_type', 'property_id'),
}
REQUIRED_EXTRAS = {'disaster': ('disaster_type',), 'revenue': ('service_type',), 'land': ('survey_number', 'ownership')}

def role_required(*roles):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles and not request.user.is_superuser: return HttpResponseForbidden('You do not have permission to view this page.')
            return view(request, *args, **kwargs)
        return wrapped
    return deco

def home(request):
    return render(request, 'landing/home.html')

@login_required
def documents_hub(request):
    if request.user.role == User.Role.OFFICER and not officer_can(request.user, 'documents'):
        return HttpResponseForbidden('Your account does not have access to the Document Intelligence module.')
    if request.user.role == User.Role.CITIZEN:
        docs = ApplicationDocument.objects.filter(application__citizen=request.user)
    elif request.user.role == User.Role.OFFICER:
        docs = ApplicationDocument.objects.filter(application__in=Application.objects.filter(officer_visible_q(request.user)))
    else:
        docs = ApplicationDocument.objects.all()
    if request.GET.get('q'):
        docs = docs.filter(original_name__icontains=request.GET['q']) | docs.filter(application__public_id__icontains=request.GET['q'])
    return render(request, 'modules/documents.html', {'documents': docs.select_related('application').order_by('-uploaded_at')[:100]})

@login_required
def eligibility_hub(request):
    if request.user.role == User.Role.OFFICER and not officer_can(request.user, 'eligibility'):
        return HttpResponseForbidden('Your account does not have access to the Eligibility Engine module.')
    if request.user.role == User.Role.CITIZEN:
        apps = Application.objects.filter(citizen=request.user)
    elif request.user.role == User.Role.OFFICER:
        apps = Application.objects.filter(officer_visible_q(request.user))
    else:
        apps = Application.objects.all()
    return render(request, 'modules/eligibility.html', {'applications': apps.select_related('citizen','scheme').prefetch_related('assessments').order_by('-created_at')[:100]})

@login_required
def compensation_hub(request):
    if request.user.role == User.Role.OFFICER and not officer_can(request.user, 'compensation'):
        return HttpResponseForbidden('Your account does not have access to the Compensation Calculator module.')
    if request.user.role == User.Role.CITIZEN:
        apps = Application.objects.filter(citizen=request.user, category=Application.Category.LAND)
    elif request.user.role == User.Role.OFFICER:
        apps = Application.objects.filter(officer_visible_q(request.user), category=Application.Category.LAND)
    else:
        apps = Application.objects.filter(category=Application.Category.LAND)
    if request.method == 'POST' and request.POST.get('action') == 'estimate':
        app = apps.filter(pk=request.POST.get('application_id')).first()
        config = CompensationConfiguration.objects.filter(pk=request.POST.get('config_id'), active=True).first()
        if not app or not config:
            messages.error(request, 'Select a valid application and an active compensation configuration.')
        else:
            try:
                estimate = calculate_compensation(app, config, request.POST.get('area', '0'))
                AuditLog.objects.create(actor=request.user, application=app, action='compensation_estimate', detail=f'Illustrative estimate {estimate.estimated_amount}')
                messages.info(request, f'Illustrative estimate for {app.public_id}: \u20b9{estimate.estimated_amount}. Subject to official verification.')
            except (ValueError, ArithmeticError):
                messages.error(request, 'Enter a valid positive area for this estimate.')
        return redirect('compensation_hub')
    return render(request, 'modules/compensation.html', {'applications': apps.select_related('citizen').prefetch_related('compensation_estimates').order_by('-created_at')[:100], 'configs': CompensationConfiguration.objects.filter(active=True)})

@login_required
def officer_module(request):
    if request.user.role != User.Role.OFFICER and not request.user.is_superuser:
        return render(request, 'errors/403.html', status=403)
    return redirect('dashboard')

@login_required
def admin_module(request):
    if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
        return render(request, 'errors/403.html', status=403)
    return redirect('dashboard')

def register(request):
    return redirect('/account/?mode=signup')

def _login_throttle_key(request, username):
    return f'login-fail:{request.META.get("REMOTE_ADDR", "unknown")}:{(username or "").lower()}'

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    mode = 'signup' if request.GET.get('mode') == 'signup' else 'login'
    signup_form = RegisterForm()
    if request.method == 'POST':
        if request.POST.get('action') == 'signup':
            mode = 'signup'
            signup_form = RegisterForm(request.POST)
            if signup_form.is_valid():
                user = signup_form.save()
                AuditLog.objects.create(actor=user, action='citizen_registration')
                if user.email:
                    # Citizens are ready to sign in as soon as they register; no email
                    # verification step is required at account creation.
                    user.email_verified = True
                    user.save(update_fields=['email_verified'])
                    messages.success(request, 'Account created. You can sign in now with your email address.')
                    return redirect('login')
                messages.error(request, 'An email address is required to create an account.')
        else:
            mode = 'login'
            email = (request.POST.get('email') or '').strip()
            key = _login_throttle_key(request, email)
            attempts = cache.get(key, 0)
            if attempts >= settings.LOGIN_MAX_ATTEMPTS:
                messages.error(request, 'Too many failed attempts. Please wait a few minutes and try again.')
                return render(request, 'auth/account.html', {'signup_form': signup_form, 'mode': mode})
            # Citizens and officers sign in with the email address on the account.
            account = User.objects.filter(email__iexact=email).first() if email else None
            user = authenticate(request, username=account.username if account else email,
                                password=request.POST.get('password'))
            selected_role = request.POST.get('role')
            if user is not None and user.role == selected_role:
                cache.delete(key)
                login(request, user)
                AuditLog.objects.create(actor=user, action='login')
                return redirect('dashboard')
            cache.set(key, attempts + 1, settings.LOGIN_LOCKOUT_SECONDS)
            if user is not None:
                messages.error(request, 'Selected account type does not match this account. Choose the correct role and try again.')
            else:
                messages.error(request, 'Email address or password was not recognized.')
    return render(request, 'auth/account.html', {'signup_form': signup_form, 'mode': mode})

def password_reset_request(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        user = User.objects.filter(email__iexact=email, is_active=True).first() if email else None
        if user:
            send_password_reset_email(user, request)
            AuditLog.objects.create(actor=user, action='password_reset_requested')
        return redirect('password_reset_done')
    return render(request, 'auth/password_reset.html')

def password_reset_done(request):
    return render(request, 'auth/password_reset_done.html')

def password_reset_confirm(request, uidb64, token):
    uid = decode_uid(uidb64)
    user = User.objects.filter(pk=uid).first() if uid else None
    valid = bool(user and default_token_generator.check_token(user, token))
    form = SetPasswordForm(user, request.POST or None) if valid else None
    if request.method == 'POST':
        if not valid:
            messages.error(request, 'This password reset link is invalid or has expired.')
            return redirect('password_reset_request')
        if form.is_valid():
            form.save()
            user.email_verified = True
            user.must_change_password = False
            user.save(update_fields=['email_verified', 'must_change_password'])
            AuditLog.objects.create(actor=user, action='password_reset_completed')
            messages.success(request, 'Your password has been reset. Please sign in.')
            return redirect('login')
    return render(request, 'auth/password_reset_confirm.html', {'form': form, 'valid': valid})

@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        if user.must_change_password:
            user.must_change_password = False
            user.save(update_fields=['must_change_password'])
        update_session_auth_hash(request, user)
        AuditLog.objects.create(actor=user, action='password_changed')
        messages.success(request, 'Your password was updated.')
        return redirect('profile')
    return render(request, 'account/password.html', {'form': form, 'forced': False})

@login_required
def force_password_change(request):
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=['must_change_password'])
        update_session_auth_hash(request, user)
        AuditLog.objects.create(actor=user, action='password_changed_first_login')
        messages.success(request, 'Temporary password replaced. Welcome to your workspace.')
        return redirect('dashboard')
    return render(request, 'account/password.html', {'form': form, 'forced': True})

@login_required
def logout_view(request):
    AuditLog.objects.create(actor=request.user, action='logout'); logout(request); return redirect('home')

@login_required
def dashboard(request):
    role = request.user.role
    if role == User.Role.CITIZEN:
        qs = Application.objects.filter(citizen=request.user).order_by('-created_at')
        departments = Department.objects.filter(active=True).prefetch_related('services')
        ctx = {'applications': qs[:6], 'total': qs.count(), 'approved': qs.filter(status='approved').count(),
               'pending': qs.exclude(status__in=['approved','rejected']).count(),
               'needs_docs': qs.filter(status='more_info').count(),
               'certificates': qs.filter(status__in=[Application.Status.APPROVED, Application.Status.CERTIFICATE_GENERATED]).count(),
               'departments': departments}
        template = 'citizen/dashboard.html'
    else:
        qs = Application.objects.all() if role == User.Role.ADMIN or request.user.is_superuser else Application.objects.filter(officer_visible_q(request.user))
        if role == User.Role.OFFICER and not request.user.is_superuser:
            allowed_categories = officer_categories(request.user)
            if len(allowed_categories) < len(Application.Category.values):
                qs = qs.filter(category__in=allowed_categories)
        if request.GET.get('q'): qs = qs.filter(public_id__icontains=request.GET['q']) | qs.filter(citizen__first_name__icontains=request.GET['q'])
        if request.GET.get('status'): qs = qs.filter(status=request.GET['status'])
        if request.GET.get('category'): qs = qs.filter(category=request.GET['category'])
        start, end = parse_date(request.GET.get('date_from', '') or ''), parse_date(request.GET.get('date_to', '') or '')
        if start: qs = qs.filter(created_at__date__gte=start)
        if end: qs = qs.filter(created_at__date__lte=end)
        sort = request.GET.get('sort', '-created_at')
        if sort not in ('created_at', '-created_at', 'status', '-status', 'public_id', '-public_id'): sort = '-created_at'
        filters = request.GET.copy(); filters.pop('page', None)
        ctx = {'applications': Paginator(qs.order_by(sort), 12).get_page(request.GET.get('page')), 'total': qs.count(), 'pending': qs.exclude(status__in=['approved','rejected']).count(), 'approved': qs.filter(status='approved').count(), 'rejected': qs.filter(status='rejected').count(), 'under_review': qs.filter(status=Application.Status.REVIEW).count(), 'verification': qs.filter(status=Application.Status.VERIFICATION).count(), 'needs_documents': qs.filter(status=Application.Status.MORE_INFO).count(), 'citizen_count': User.objects.filter(role='citizen').count(), 'officer_count': User.objects.filter(role='officer').count(), 'by_status': list(qs.values('status').annotate(n=Count('id'))), 'by_category': list(qs.values('category').annotate(n=Count('id'))), 'by_scheme': list(qs.values('scheme__name').annotate(n=Count('id')).order_by('-n')), 'monthly_trend': list(qs.annotate(month=TruncMonth('created_at')).values('month').annotate(n=Count('id')).order_by('month')), 'department_rows': list(Department.objects.annotate(n=Count('applications', distinct=True), officers_n=Count('officers', distinct=True)).order_by('name')), 'officers': User.objects.filter(role='officer').select_related('officer_record__department'), 'categories': Application.Category.choices, 'statuses': Application.Status.choices, 'filter_query': filters.urlencode(), 'sort': sort}
        template = 'officer/dashboard.html' if role == User.Role.OFFICER else 'administrator/dashboard.html'
    ctx['unread_count'] = request.user.notifications.filter(read=False).count()
    return render(request, template, ctx)

@login_required
def departments(request):
    """Directory of every active government department and its services."""
    rows = Department.objects.filter(active=True).prefetch_related('services')
    return render(request, 'citizen/departments.html', {'departments': rows})


@login_required
def department_detail(request, department_id):
    """All services offered by one department, loaded from the database."""
    department = get_object_or_404(Department.objects.filter(active=True), pk=department_id)
    services = department.services.filter(active=True).prefetch_related('requirements')
    return render(request, 'citizen/department.html', {'department': department, 'services': services})


@login_required
def service_detail(request, slug):
    """Detailed page for one service: eligibility, documents, time, apply."""
    service = get_object_or_404(GovernmentService.objects.filter(active=True).select_related('department'),
                                slug=slug)
    requirements = service.requirements.filter(active=True).order_by('order', 'id')
    return render(request, 'citizen/service_detail.html', {
        'service': service,
        'department': service.department,
        'requirements': requirements,
        'template': getattr(service, 'certificate_template', None),
    })


@role_required(User.Role.CITIZEN)
def new_application(request):
    form = ApplicationForm(request.POST or None)
    preselected = None
    slug = request.POST.get('service_slug') or request.GET.get('service')
    if slug:
        preselected = GovernmentService.objects.filter(slug=slug, active=True).select_related('department').first()
    if request.method == 'POST' and form.is_valid():
        category = form.cleaned_data['category']
        extras = {key: request.POST.get(key, '').strip()[:180] for key in CATEGORY_FIELDS.get(category, ())}
        if preselected:
            # The service was chosen from the catalogue, so the service type is known.
            extras.setdefault('service_type', preselected.slug)
        required_extras = [key for key in REQUIRED_EXTRAS.get(category, ()) if not (preselected and key == 'service_type')]
        missing = [key.replace('_', ' ') for key in required_extras if not extras.get(key)]
        uploads, labels, rejected = collect_document_uploads(request)
        # Every service needs at least two documents and any two from the service's
        # checklist count towards that. Officers never upload documents -- everything
        # is provided by the citizen with the application.
        checklist_names = ([row.name for row in preselected.requirements.filter(active=True)]
                           if preselected else [])
        attached_documents = [labels[index] for index in uploads if labels.get(index) in checklist_names]
        need_documents = min(2, len(checklist_names))
        if missing:
            messages.error(request, 'Complete the required service details: ' + ', '.join(missing) + '.')
        if need_documents and len(attached_documents) < need_documents:
            messages.error(request, f'Attach at least {need_documents} documents from this service\'s checklist '
                                    f'before submitting. You have attached {len(attached_documents)}.')
        if not missing and (not need_documents or len(attached_documents) >= need_documents):
            app = form.save(commit=False); app.citizen = request.user; app.form_data = extras
            if preselected:
                app.service = preselected
                app.category = preselected.category
            app.department = preselected.department if preselected else department_for_category(app.category)
            app.save()
            # Store the labelled form values so the officer and certificate read the same data.
            store_application_fields(app, extras)
            ApplicationStatusHistory.objects.create(application=app, status=app.status, actor=request.user, remark='Application submitted')
            # Attach the documents uploaded in this form and OCR-process each one.
            if uploads:
                change_status(app, Application.Status.PROCESSING, request.user, 'Document processing started.')
                save_application_documents(app, uploads, labels)
            # AI pre-screening runs automatically so the officer only has to verify.
            if app.scheme_id:
                assess_eligibility(app)
            refresh_anomalies(app)
            check = document_check(app)
            write_analysis_report(app, check)
            change_status(app, Application.Status.VERIFICATION, request.user,
                          'AI pre-screening complete \u2014 awaiting officer verification. ' + check['headline'])
            if rejected:
                messages.warning(request, 'These files were skipped (use PDF/JPG/PNG up to 8 MB): ' + ', '.join(rejected) + '.')
            notify(request.user, f'Application {app.public_id} submitted successfully.', application=app,
                   kind='application_submitted', subject=f'Application {app.public_id} received',
                   body=(f'Hello {request.user.get_full_name() or request.user.username},\n\n'
                         f'We received your {application_service(app)} application.\n\n'
                         f'Application ID: {app.public_id}\nCurrent status: {app.get_status_display()}\n\n'
                         f'AI document check: {check["headline"]}\n' +
                         (('Still needed:\n- ' + '\n- '.join(check['missing']) + '\n\n') if check['missing'] else '\n') +
                         'Our AI has already pre-screened the case. Track progress any time from your JanSutra AI dashboard.\n'))
            for admin_user in User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(email=''):
                notify(admin_user, f'New application {app.public_id} from {request.user.username}.', application=app,
                       kind='admin_new_application', subject=f'New application {app.public_id}',
                       body=(f'A new {application_service(app)} application ({app.public_id}) was submitted by '
                             f'{request.user.get_full_name() or request.user.username}.\n\n'
                             f'AI document check: {check["headline"]}'))
            if app.department_id:
                for officer_user in User.objects.filter(
                        role=User.Role.OFFICER, is_active=True, officer_record__department=app.department).exclude(email=''):
                    notify(officer_user, f'New {application_service(app)} case {app.public_id} is ready for review.',
                           application=app, kind='case_assigned',
                           subject=f'New case in {app.department.name}: {app.public_id}',
                           body=(f'A new {application_service(app)} application ({app.public_id}) has been routed to '
                                 f'{app.department.name}.\n\nAI pre-screening and the AI document check are complete.\n'
                                 'Sign in to review the documents, the ready certificate and record your decision.\n'))
            AuditLog.objects.create(actor=request.user, application=app, action='application_submission')
            messages.success(request, f'Application {app.public_id} submitted. {check["headline"]}')
            return redirect('application_detail', public_id=app.public_id)
    if preselected:
        form.fields['category'].initial = preselected.category
    services = (GovernmentService.objects.filter(active=True).select_related('department')
                .prefetch_related('requirements').order_by('department__order', 'department__name', 'order', 'name'))
    service_index = [{
        'slug': service.slug, 'name': service.name, 'category': service.category,
        'department': service.department.name, 'department_id': service.department_id,
        'icon': service.icon or 'bi-file-earmark-text',
        'requirements': [{'name': row.name, 'required': row.required, 'hint': row.description or ''}
                         for row in service.requirements.filter(active=True).order_by('order', 'id')],
    } for service in services]
    return render(request, 'citizen/new_application.html', {
        'form': form,
        'schemes': Scheme.objects.filter(active=True),
        'required_documents': REQUIRED_DOCUMENTS,
        'service_catalog': SERVICE_CATALOG,
        'preselected': preselected,
        'service_index': service_index,
        'service_requirements': [{'name': r.name, 'required': r.required, 'hint': r.description}
                                 for r in (preselected.requirements.filter(active=True).order_by('order', 'id') if preselected else [])],
        'departments': Department.objects.filter(active=True).prefetch_related('services'),
    })


def store_application_fields(application, extras):
    """Save the labelled application form values as ApplicationField rows."""
    from .models import ApplicationField
    application.fields.all().delete()
    labels = {'beneficiary_type': 'Beneficiary type', 'family_members': 'Family members',
              'disaster_type': 'Disaster type', 'loss_summary': 'Loss summary',
              'survey_number': 'Survey number', 'ownership': 'Ownership type',
              'service_type': 'Service type', 'property_id': 'Property / record ID'}
    rows = []
    for index, (key, value) in enumerate(extras.items()):
        if value:
            rows.append(ApplicationField(application=application, label=labels.get(key, key.replace('_', ' ').title()),
                                         value=str(value)[:500], order=index))
    ApplicationField.objects.bulk_create(rows)

MAX_UPLOAD_SLOTS = 25

def collect_document_uploads(request):
    """Pair each uploaded file with the document type the citizen chose for it."""
    uploads, labels, rejected = {}, {}, []
    for index in range(MAX_UPLOAD_SLOTS):
        upload = request.FILES.get(f'docfile_{index}')
        if not upload:
            continue
        if Path(upload.name).suffix.lower() not in ALLOWED_EXTENSIONS or upload.size > 8 * 1024 * 1024:
            rejected.append(upload.name)
            continue
        uploads[index] = upload
        labels[index] = (request.POST.get(f'doclabel_{index}') or '').strip()
    return uploads, labels, rejected

def visible_app(request, public_id):
    app = get_object_or_404(Application.objects.select_related('citizen','scheme','assigned_officer').prefetch_related('documents','history__actor','remarks__officer','assessments'), public_id=public_id)
    if request.user.role == User.Role.CITIZEN and app.citizen_id != request.user.id: return None
    if request.user.role == User.Role.OFFICER:
        department_id = officer_department_id(request.user)
        if app.assigned_officer_id != request.user.id and not (department_id and app.department_id == department_id):
            return None
        if not officer_can_category(request.user, app.category): return None
    return app

STATUS_STEPS = [
    Application.Status.SUBMITTED,
    Application.Status.PROCESSING,
    Application.Status.VERIFICATION,
    Application.Status.FORWARDED,
    Application.Status.PENDING_REVIEW,
    Application.Status.REVIEW,
    Application.Status.APPROVED,
    Application.Status.CERTIFICATE_GENERATED,
]

@login_required
def application_detail(request, public_id):
    app = visible_app(request, public_id)
    if not app: return HttpResponseForbidden('This application is not available to your account.')
    ai_report = getattr(app, 'ai_report', None)
    corrections = app.correction_requests.all()
    open_corrections = [c for c in corrections if c.status == CorrectionRequest.Status.OPEN]
    step_rank = _step_rank(app.status)
    reached = STATUS_STEPS[:step_rank + 1]
    return render(request, 'applications/detail.html', {
        'app': app, 'risk': delay_risk(app), 'possible_duplicates': potential_duplicates(app),
        'anomalies': refresh_anomalies(app),
        'is_officer': request.user.role in ('officer','admin') or request.user.is_superuser,
        'officers': User.objects.filter(role=User.Role.OFFICER, is_active=True).select_related('officer_record__department'),
        'compensation_configs': CompensationConfiguration.objects.filter(active=True),
        'required_documents': application_documents(app), 'requirements': application_requirements(app),
        'service': application_service(app), 'doc_check': document_check(app),
        'ai_report': ai_report, 'corrections': corrections, 'open_corrections': open_corrections,
        'status_steps': STATUS_STEPS, 'status_reached': reached, 'risk_category': risk_category(document_check(app)),
        'certificate_record': getattr(app, 'certificate_record', None),
        'fields': app.fields.all(),
    })


def _step_rank(status):
    """Index of a status on the progress tracker (handles off-track states)."""
    if status in STATUS_STEPS:
        return STATUS_STEPS.index(status)
    if status in (Application.Status.MORE_INFO, Application.Status.RESUBMITTED):
        return STATUS_STEPS.index(Application.Status.PENDING_REVIEW)
    if status == Application.Status.REJECTED:
        return STATUS_STEPS.index(Application.Status.REVIEW)
    return 0

@login_required
@require_POST
def upload_document(request, public_id):
    app = visible_app(request, public_id)
    # Documents are supplied by the citizen with the application; officers and admins never upload.
    if not app or request.user.role != User.Role.CITIZEN or app.citizen_id != request.user.id:
        return HttpResponseForbidden('Only the applicant can upload documents for this case.')
    if app.status in (Application.Status.FORWARDED, Application.Status.APPROVED, Application.Status.REJECTED):
        messages.error(request, 'This case is no longer accepting documents. Contact the assigned office if you believe more information is needed.')
        return redirect('application_detail', public_id=app.public_id)
    form = DocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False); doc.application = app; doc.original_name = request.FILES['file'].name; doc.content_type = request.FILES['file'].content_type or ''
        doc.doc_type = (request.POST.get('doc_type') or '').strip()[:160]
        doc.save()
        change_status(app, Application.Status.PROCESSING, request.user, 'Document processing started.')
        process_document(doc)
        refresh_anomalies(app)
        AuditLog.objects.create(actor=request.user, application=app, action='document_upload', detail=f'{doc.original_name} ({doc.doc_type or "unclassified"})')
        AuditLog.objects.create(actor=request.user, application=app, action='document_processing', detail=f'{doc.ocr_status}; confidence={doc.ocr_confidence}')
        check = document_check(app)
        change_status(app, Application.Status.VERIFICATION, request.user, f'AI document check finished: {check["headline"]}')
        notify(app.citizen, f'{doc.original_name} processed for {app.public_id}. {check["headline"]}',
               application=app, kind='document_processing', subject=f'{app.public_id} document processed',
               body=(f'Your document {doc.original_name} for application {app.public_id} has been processed.\n'
                     f'Result: {doc.ocr_status.replace("_", " ")}\n\n'
                     f'AI document check: {check["headline"]}\n' +
                     (('Still needed:\n- ' + '\n- '.join(check['missing']) + '\n') if check['missing'] else '') +
                     '\nSign in to review the extracted details.\n'))
        messages.success(request, 'Document uploaded. AI check: ' + check['headline'])
    else:
        for e in form.errors.values(): messages.error(request, e.as_text())
    return redirect('application_detail', public_id=app.public_id)

@login_required
@require_POST
def correct_extraction(request, document_id):
    doc = get_object_or_404(ApplicationDocument.objects.select_related('application'), pk=document_id)
    app = doc.application
    if request.user.role == User.Role.CITIZEN and app.citizen_id != request.user.id:
        return HttpResponseForbidden()
    if request.user.role == User.Role.OFFICER and app.assigned_officer_id != request.user.id:
        return HttpResponseForbidden()
    if request.user.role not in (User.Role.CITIZEN, User.Role.OFFICER, User.Role.ADMIN) and not request.user.is_superuser:
        return HttpResponseForbidden()
    allowed = ('applicant_name', 'document_number', 'address', 'date_of_birth', 'income', 'survey_number', 'document_date')
    corrected = {key: request.POST.get(key, '').strip()[:180] for key in allowed if request.POST.get(key, '').strip()}
    doc.extracted_fields = corrected
    doc.ocr_status = 'corrected'
    doc.ocr_warning = 'Fields manually reviewed. This does not certify the document as official.'
    doc.save(update_fields=['extracted_fields', 'ocr_status', 'ocr_warning'])
    sync_extracted_rows(doc)
    AuditLog.objects.create(actor=request.user, application=app, action='extraction_correction', detail=f'Manual fields updated for {doc.original_name}')
    if request.user.role != User.Role.CITIZEN:
        Notification.objects.create(recipient=app.citizen, application=app, message=f'An officer reviewed the extracted details in {doc.original_name}.')
    messages.success(request, 'The extracted fields were saved for review.')
    return redirect('application_detail', public_id=app.public_id)

@login_required
def document_download(request, document_id):
    from .models import ApplicationDocument
    doc = get_object_or_404(ApplicationDocument.objects.select_related('application'), pk=document_id)
    app = doc.application
    if request.user.role == User.Role.CITIZEN and app.citizen_id != request.user.id:
        return HttpResponseForbidden('This document is not available to your account.')
    if request.user.role == User.Role.OFFICER and app.assigned_officer_id != request.user.id:
        return HttpResponseForbidden('This document is not available to your account.')
    if request.user.role not in (User.Role.CITIZEN, User.Role.OFFICER, User.Role.ADMIN) and not request.user.is_superuser:
        return HttpResponseForbidden()
    return FileResponse(doc.file.open('rb'), as_attachment=True, filename=doc.original_name)

@login_required
def document_preview(request, document_id):
    doc = get_object_or_404(ApplicationDocument.objects.select_related('application'), pk=document_id)
    app = doc.application
    if request.user.role == User.Role.CITIZEN and app.citizen_id != request.user.id:
        return HttpResponseForbidden()
    if request.user.role == User.Role.OFFICER and app.assigned_officer_id != request.user.id:
        return HttpResponseForbidden()
    if request.user.role not in (User.Role.CITIZEN, User.Role.OFFICER, User.Role.ADMIN) and not request.user.is_superuser:
        return HttpResponseForbidden()
    return FileResponse(doc.file.open('rb'), content_type=doc.content_type or 'application/octet-stream')

@role_required(User.Role.CITIZEN, User.Role.OFFICER, User.Role.ADMIN)
@require_POST
def assess(request, public_id):
    app = visible_app(request, public_id)
    if not app: return HttpResponseForbidden()
    assessment = assess_eligibility(app)
    AuditLog.objects.create(actor=request.user, application=app, action='eligibility_assessment', detail=assessment.outcome)
    messages.info(request, 'Assessment complete: ' + assessment.outcome + '. An officer must review this recommendation.')
    return redirect('application_detail', public_id=app.public_id)

@login_required
@require_POST
def compensation(request, public_id):
    app = visible_app(request, public_id)
    if not app: return HttpResponseForbidden()
    if app.category != Application.Category.LAND:
        messages.error(request, 'Compensation estimates are only available for land applications.')
        return redirect('application_detail', public_id=app.public_id)
    try:
        config = get_object_or_404(CompensationConfiguration, pk=request.POST.get('configuration'), active=True)
        estimate = calculate_compensation(app, config, request.POST.get('area', '0'))
        AuditLog.objects.create(actor=request.user, application=app, action='compensation_estimate', detail=f'Illustrative estimate {estimate.estimated_amount}')
        messages.info(request, f'Illustrative estimate created: ₹{estimate.estimated_amount}. Subject to official verification.')
    except (ValueError, ArithmeticError):
        messages.error(request, 'Enter a valid positive area for this estimate.')
    return redirect('application_detail', public_id=app.public_id)

@role_required(User.Role.OFFICER, User.Role.ADMIN)
@require_POST
def officer_action(request, public_id):
    app = visible_app(request, public_id)
    if not app: return HttpResponseForbidden()
    action, remark = request.POST.get('action'), request.POST.get('remark','').strip()
    if action == 'assign' and request.user.role == 'admin':
        officer = get_object_or_404(User, pk=request.POST.get('officer'), role='officer')
        app.assigned_officer = officer
        from .models import Officer
        try:
            profile = officer.officer_record
        except Officer.DoesNotExist:
            profile = None
        if profile and profile.department_id:
            app.department = profile.department
        app.save(update_fields=['assigned_officer', 'department', 'updated_at'])
        ApplicationAssignment.objects.create(application=app, officer=officer, assigned_by=request.user, note=remark[:200])
        AuditLog.objects.create(actor=request.user, application=app, action='officer_assignment', detail=officer.username)
        notify(app.citizen, f'An officer has been assigned to {app.public_id}.', application=app,
               kind='officer_assigned', subject=f'{app.public_id}: officer assigned',
               body=f'Application {app.public_id} has been assigned to a reviewing officer.')
        notify(officer, f'New case assigned: {app.public_id}.', application=app, kind='case_assigned',
               subject=f'New case assigned: {app.public_id}',
               body=(f'A new case ({app.public_id}) has been assigned to you.\n'
                     f'Category: {app.get_category_display()}\nCurrent status: {app.get_status_display()}\n\n'
                     'Sign in to review the documents and history.\n'))
        messages.success(request, 'Officer assigned.')
        return redirect('application_detail', public_id=app.public_id)
    mapping = {'review':'review','request_docs':'more_info','forward':'forwarded','approve':'approved','reject':'rejected','verify':'verification'}
    if action not in mapping: return HttpResponseForbidden()
    if action in ('approve', 'reject') and len(remark) < 5:
        messages.error(request, 'Add a decision reason of at least five characters before approving or rejecting.')
        return redirect('application_detail', public_id=app.public_id)
    if remark:
        OfficerRemark.objects.create(application=app, officer=request.user, text=remark)
        ApplicationRemark.objects.create(application=app, author=request.user, text=remark, kind=ApplicationRemark.Kind.REQUEST if action == 'request_docs' else ApplicationRemark.Kind.INTERNAL)
    if action == 'request_docs':
        # Record exactly what the officer wants fixed so the citizen sees a checklist.
        CorrectionRequest.objects.create(application=app, officer=request.user,
                                         item=(request.POST.get('item') or '').strip()[:200],
                                         message=remark or 'Please correct or re-upload the flagged document(s).')
    change_status(app, mapping[action], request.user, remark)
    label = app.get_status_display()
    if action == 'approve':
        headline = f'{app.public_id} approved.'
    elif action == 'reject':
        headline = f'{app.public_id} rejected.'
    elif action == 'request_docs':
        headline = f'{app.public_id}: documents requested.'
    else:
        headline = f'{app.public_id} status updated to: {label}.'
    if action in ('approve', 'reject'):
        # A final decision closes any open correction requests.
        app.correction_requests.filter(status=CorrectionRequest.Status.OPEN).update(
            status=CorrectionRequest.Status.RESOLVED, resolved_at=timezone.now())
    if action == 'approve':
        # Generate the verifiable PDF certificate, move to Certificate Generated and email it.
        certificate = send_certificate(app)
        change_status(app, Application.Status.CERTIFICATE_GENERATED, request.user,
                      f'Certificate {certificate.certificate_number if certificate else ""} generated and emailed to the citizen.')
        notify(app.citizen, headline, application=app, kind='status_approved')
    else:
        notify(app.citizen, headline, application=app, kind=f'status_{mapping[action]}',
               subject=f'{app.public_id} \u2014 {label}',
               body=(f'Application {app.public_id} status: {label}.\n'
                     + (f'Officer remark: {remark}\n' if remark else '')
                     + '\nSign in to view the full history and any document requests.\n'),
               context={'remarks': remark})
    messages.success(request, f'Application updated: {app.get_status_display()}.')
    return redirect('application_detail', public_id=app.public_id)

def send_certificate(application):
    """Generate the verifiable PDF certificate, email it and record delivery.

    Returns the GeneratedCertificate so the caller can move the case to the
    Certificate Generated status and quote the certificate number.
    """
    certificate = generate_certificate(application)
    if not application.citizen.email:
        return certificate
    service = application_service(application)
    certificate.pdf.open('rb')
    pdf_bytes = certificate.pdf.read()
    certificate.pdf.close()
    defaults = DEFAULT_TEMPLATES_BY_KIND['certificate_issued']
    subject, body = render_template(
        'certificate_issued', defaults['subject'], defaults['body'],
        user=application.citizen, application=application,
        extra={'service': service, 'certificate_number': certificate.certificate_number,
               'verification_code': certificate.verification_code})
    logs = send_email('certificate_issued', subject,
                      body, [application.citizen.email], user=application.citizen, application=application,
                      attachments=[(f'{application.public_id}-certificate.pdf', pdf_bytes, 'application/pdf')])
    if logs and logs[0].status == EmailLog.Status.SENT:
        certificate.emailed_at = timezone.now()
        certificate.save(update_fields=['emailed_at'])
    return certificate

@login_required
def certificate(request, public_id):
    """Serve the certificate PDF: the official file once approved, a stamped
    draft for officers before approval."""
    app = visible_app(request, public_id)
    if not app: return HttpResponseForbidden('This application is not available to your account.')
    is_staff = request.user.role in ('officer','admin') or request.user.is_superuser
    approved = app.status in (Application.Status.APPROVED, Application.Status.CERTIFICATE_GENERATED)
    if not approved and not is_staff:
        messages.info(request, 'The certificate becomes available once an officer approves the application.')
        return redirect('application_detail', public_id=app.public_id)
    if approved:
        record = getattr(app, 'certificate_record', None) or generate_certificate(app)
        record.pdf.open('rb')
        payload = record.pdf.read()
        record.pdf.close()
        filename = record.certificate_number.replace('/', '-') + '.pdf'
    else:
        messages.info(request, 'This is a draft certificate. It becomes final and is emailed to the citizen once you approve the case.')
        payload = build_certificate_pdf(app, draft=True)
        filename = f'{app.public_id}-draft-certificate.pdf'
    response = HttpResponse(payload, content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    return response

def verify_certificate(request, code=''):
    """Public page: confirm a certificate's authenticity from its code or QR."""
    code = (code or request.GET.get('code') or '').strip()
    record = GeneratedCertificate.objects.filter(verification_code__iexact=code).select_related(
        'application', 'application__citizen', 'application__department', 'application__service').first() if code else None
    if code:
        AuditLog.objects.create(actor=request.user if request.user.is_authenticated else None,
                                action='certificate_verification',
                                detail=f'{code}: {"valid" if record and not record.revoked else "not found"}')
    return render(request, 'public/verify.html', {'record': record, 'code': code})

@login_required
def assistant(request):
    """AI Citizen Assistant: answers only from the approved FAQ knowledge base."""
    from .models import AssistantFAQ
    if request.method == 'POST':
        question = (request.POST.get('question') or '').strip()[:300]
        if not question:
            return JsonResponse({'question': '', 'matched': False, 'answer': 'Please type a question so I can help.', 'topic': '', 'suggestions': []})
        result = assistant_answer(question)
        result['question'] = question
        AuditLog.objects.create(actor=request.user, action='assistant_query', detail=question[:200])
        return JsonResponse(result)
    return render(request, 'citizen/assistant.html', {
        'faqs': AssistantFAQ.objects.filter(active=True).order_by('topic', 'question'),
    })

@login_required
def notifications(request):
    qs = request.user.notifications.select_related('application').order_by('-created_at')
    if request.method == 'POST': qs.filter(read=False).update(read=True)
    return render(request, 'citizen/notifications.html', {'notifications': qs})

@role_required(User.Role.ADMIN)
def report_csv(request):
    qs = Application.objects.select_related('citizen','assigned_officer').prefetch_related('documents').order_by('-created_at')
    if request.GET.get('status') in Application.Status.values: qs = qs.filter(status=request.GET['status'])
    if request.GET.get('category') in Application.Category.values: qs = qs.filter(category=request.GET['category'])
    if request.GET.get('department', '').isdigit(): qs = qs.filter(department_id=request.GET['department'])
    if request.GET.get('q'):
        qs = qs.filter(public_id__icontains=request.GET['q']) | qs.filter(citizen__first_name__icontains=request.GET['q']) | qs.filter(citizen__last_name__icontains=request.GET['q'])
    start, end = parse_date(request.GET.get('date_from', '') or ''), parse_date(request.GET.get('date_to', '') or '')
    if start: qs = qs.filter(created_at__date__gte=start)
    if end: qs = qs.filter(created_at__date__lte=end)
    response = HttpResponse(content_type='text/csv'); response['Content-Disposition'] = 'attachment; filename="jansutra-applications.csv"'
    writer = csv.writer(response); writer.writerow(['Application ID','Applicant','Service','Category','Status','Submitted','Officer','Department','Documents','AI Document Check','Certificate'])
    for a in qs.select_related('department', 'scheme'):
        check = document_check(a)
        writer.writerow([a.public_id, a.citizen.get_full_name() or a.citizen.username, application_service(a), a.get_category_display(), a.get_status_display(), a.created_at.isoformat(), a.assigned_officer.username if a.assigned_officer else 'Unassigned', a.department.name if a.department_id else '', f'{check["verified_count"]}/{check["required_count"]} verified', check['headline'], 'Issued' if a.status == Application.Status.APPROVED else 'Pending'])
    return response

@role_required(User.Role.ADMIN)
def audit_logs(request):
    logs = AuditLog.objects.select_related('actor','application').order_by('-created_at')
    if request.GET.get('q'):
        logs = logs.filter(action__icontains=request.GET['q']) | logs.filter(detail__icontains=request.GET['q'])
    return render(request, 'administrator/audit_logs.html', {'logs': Paginator(logs, 30).get_page(request.GET.get('page'))})

@login_required
def profile(request):
    from .models import UserProfile
    profile_row, _ = UserProfile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        if form.cleaned_data.get('date_of_birth'):
            profile_row.date_of_birth = form.cleaned_data['date_of_birth']
            profile_row.save(update_fields=['date_of_birth'])
        AuditLog.objects.create(actor=request.user, action='profile_update')
        messages.success(request, 'Profile saved.')
        return redirect('profile')
    form.fields['date_of_birth'].initial = profile_row.date_of_birth
    return render(request, 'account/profile.html', {'form': form})

@role_required(User.Role.CITIZEN)
def application_history(request):
    qs = Application.objects.filter(citizen=request.user).select_related('scheme').order_by('-created_at')
    if request.GET.get('status') in Application.Status.values:
        qs = qs.filter(status=request.GET['status'])
    return render(request, 'citizen/history.html', {'applications': qs, 'statuses': Application.Status.choices})

@login_required
def acknowledgement(request, public_id):
    app = visible_app(request, public_id)
    if not app:
        return HttpResponseForbidden('This application is not available to your account.')
    response = render(request, 'applications/acknowledgement.html', {'app': app})
    if request.GET.get('download') == '1':
        response['Content-Disposition'] = f'attachment; filename="{app.public_id}-acknowledgement.html"'
    return response

@role_required(User.Role.CITIZEN)
@require_POST
def citizen_reply(request, public_id):
    app = visible_app(request, public_id)
    if not app:
        return HttpResponseForbidden()
    text = request.POST.get('reply', '').strip()
    if app.status != Application.Status.MORE_INFO:
        messages.error(request, 'A response can be sent when the case is waiting for documents.')
        return redirect('application_detail', public_id=app.public_id)
    if len(text) < 5:
        messages.error(request, 'Describe the correction or the documents you are providing.')
        return redirect('application_detail', public_id=app.public_id)
    ApplicationRemark.objects.create(application=app, author=request.user, kind=ApplicationRemark.Kind.CITIZEN, text=text)
    app.correction_requests.filter(status=CorrectionRequest.Status.OPEN).update(
        status=CorrectionRequest.Status.RESOLVED, resolved_at=timezone.now())
    change_status(app, Application.Status.RESUBMITTED, request.user, text)
    check = document_check(app)
    write_analysis_report(app, check)
    if app.assigned_officer_id:
        Notification.objects.create(recipient=app.assigned_officer, application=app, message=f'{app.public_id}: the applicant responded to the document request.')
    messages.success(request, 'Your response was sent to the reviewing officer.')
    return redirect('application_detail', public_id=app.public_id)

@role_required(User.Role.OFFICER, User.Role.ADMIN)
@require_POST
def dismiss_anomaly(request, public_id, flag_id):
    app = visible_app(request, public_id)
    if not app:
        return HttpResponseForbidden()
    flag = get_object_or_404(AnomalyFlag, pk=flag_id, application=app)
    flag.dismissed = True
    flag.save(update_fields=['dismissed'])
    AuditLog.objects.create(actor=request.user, application=app, action='anomaly_reviewed', detail=flag.kind)
    messages.info(request, 'The warning was marked as reviewed. The application status was not changed.')
    return redirect('application_detail', public_id=app.public_id)


@role_required(User.Role.ADMIN)
def manage_services(request):
    """Administrator catalogue: departments' services and their document requirements."""
    edit = GovernmentService.objects.filter(pk=request.GET.get('edit')).select_related('department').first()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle':
            service = GovernmentService.objects.filter(pk=request.POST.get('id')).first()
            if service:
                service.active = not service.active
                service.save(update_fields=['active'])
                messages.success(request, f'{service.name} {"activated" if service.active else "marked inactive"}.')
            return redirect('manage_services')
        if action == 'delete':
            GovernmentService.objects.filter(pk=request.POST.get('id')).delete()
            messages.success(request, 'Service removed from the catalogue.')
            return redirect('manage_services')
        if action in ('add_requirement', 'delete_requirement'):
            service = GovernmentService.objects.filter(pk=request.POST.get('service')).first()
            if service is None:
                messages.error(request, 'Choose a service first.')
                return redirect('manage_services')
            if action == 'add_requirement':
                form = ServiceDocumentRequirementForm(request.POST)
                if form.is_valid():
                    requirement = form.save(commit=False)
                    requirement.service = service
                    requirement.save()
                    AuditLog.objects.create(actor=request.user, action='service_requirement_saved',
                                            detail=f'{service.name}: {requirement.name}')
                    messages.success(request, f'Document "{requirement.name}" added to {service.name}.')
                else:
                    messages.error(request, 'Enter a document name to add a requirement.')
            else:
                ServiceDocumentRequirement.objects.filter(pk=request.POST.get('id'), service=service).delete()
                messages.success(request, 'Requirement removed.')
            return redirect(f'{reverse("manage_services")}?edit={service.pk}')
        form = GovernmentServiceForm(request.POST, instance=GovernmentService.objects.filter(pk=request.POST.get('id')).first())
        if form.is_valid():
            service = form.save()
            AuditLog.objects.create(actor=request.user, action='service_saved', detail=str(service))
            messages.success(request, 'Service saved.')
            return redirect(f'{reverse("manage_services")}?edit={service.pk}')
        messages.error(request, 'Please correct the highlighted errors.')
        edit = GovernmentService.objects.filter(pk=request.POST.get('id')).first()
    else:
        form = GovernmentServiceForm(instance=edit)
    requirements = edit.requirements.order_by('order', 'id') if edit else []
    return render(request, 'administrator/manage_services.html', {
        'title': 'Services & document requirements', 'form': form, 'edit': edit,
        'requirement_form': ServiceDocumentRequirementForm(),
        'requirements': requirements,
        'services': GovernmentService.objects.select_related('department').annotate(cases=Count('applications')),
    })


@role_required(User.Role.ADMIN)
def manage_templates(request):
    """Administrator certificate templates used when a service is approved."""
    edit = CertificateTemplate.objects.filter(pk=request.GET.get('edit')).select_related('service').first()
    if request.method == 'POST':
        if request.POST.get('action') == 'delete':
            CertificateTemplate.objects.filter(pk=request.POST.get('id')).delete()
            messages.success(request, 'Certificate template removed.')
            return redirect('manage_templates')
        form = CertificateTemplateForm(request.POST, instance=CertificateTemplate.objects.filter(pk=request.POST.get('id')).first())
        if form.is_valid():
            template = form.save()
            AuditLog.objects.create(actor=request.user, action='certificate_template_saved', detail=str(template))
            messages.success(request, 'Certificate template saved.')
            return redirect('manage_templates')
        messages.error(request, 'Please correct the highlighted errors.')
    else:
        form = CertificateTemplateForm(instance=edit)
    return render(request, 'administrator/manage_templates.html', {
        'title': 'Certificate templates', 'form': form, 'edit': edit,
        'rows': CertificateTemplate.objects.select_related('service', 'service__department'),
        'services': GovernmentService.objects.select_related('department').order_by('department__name', 'name'),
    })


@role_required(User.Role.ADMIN)
def analytics(request):
    """Monitoring dashboard: AI verification outcomes, processing time and workload."""
    decided = Application.objects.filter(status__in=[Application.Status.APPROVED, Application.Status.REJECTED])
    avg_days = (round(sum((a.updated_at - a.created_at).days for a in decided) / decided.count(), 1)
                if decided.exists() else 0)
    officer_rows = User.objects.filter(role=User.Role.OFFICER).annotate(
        open_cases=Count('assigned_applications', filter=~Q(assigned_applications__status__in=[
            Application.Status.APPROVED, Application.Status.REJECTED, Application.Status.CERTIFICATE_GENERATED])),
        decided_cases=Count('assigned_applications', filter=Q(assigned_applications__status__in=[
            Application.Status.APPROVED, Application.Status.REJECTED])),
    ).select_related('officer_record__department').order_by('-open_cases')
    total = Application.objects.count()
    ready = AIAnalysisReport.objects.filter(ready=True).count()
    certificates = GeneratedCertificate.objects.count()
    certificates_emailed = GeneratedCertificate.objects.exclude(emailed_at=None).count()
    return render(request, 'administrator/analytics.html', {
        'title': 'Monitoring & analytics',
        'total': total,
        'by_status': list(Application.objects.values('status').annotate(n=Count('id')).order_by('-n')),
        'by_department': list(Department.objects.annotate(
            n=Count('applications', distinct=True),
            approved=Count('applications', filter=Q(applications__status=Application.Status.APPROVED), distinct=True),
        ).order_by('-n')),
        'officer_rows': officer_rows,
        'avg_days': avg_days,
        'certificates': certificates,
        'certificates_emailed': certificates_emailed,
        'certificates_pending': certificates - certificates_emailed,
        'ai_checked': AIAnalysisReport.objects.count(),
        'ai_ready': ready,
        'ai_pass_rate': round((ready / total) * 100, 1) if total else 0,
        'corrections_open': CorrectionRequest.objects.filter(status=CorrectionRequest.Status.OPEN).count(),
        'statuses': Application.Status.choices,
    })
