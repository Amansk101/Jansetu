import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

class User(AbstractUser):
    class Role(models.TextChoices):
        CITIZEN = 'citizen', 'Citizen'
        OFFICER = 'officer', 'Officer'
        ADMIN = 'admin', 'Administrator'
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.CITIZEN, db_index=True)
    mobile = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    district = models.CharField(max_length=100, blank=True)
    taluka = models.CharField(max_length=100, blank=True)
    village = models.CharField(max_length=100, blank=True)
    email_verified = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    def officer_department_id(self):
        try:
            return self.officer_record.department_id
        except Officer.DoesNotExist:
            return None

MODULES = (
    ('documents', 'Document Intelligence'),
    ('eligibility', 'Eligibility Engine'),
    ('compensation', 'Compensation Calculator'),
)

class Scheme(models.Model):
    name = models.CharField(max_length=160, unique=True)
    category = models.CharField(max_length=32)
    income_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    required_documents = models.CharField(max_length=250, default='Identity proof, Address proof')
    active = models.BooleanField(default=True)
    def __str__(self): return self.name

class Application(models.Model):
    class Category(models.TextChoices):
        WELFARE = 'welfare', 'Welfare Scheme'
        DISASTER = 'disaster', 'Disaster Relief'
        LAND = 'land', 'Land Acquisition / Compensation'
        REVENUE = 'revenue', 'Revenue Service'
        EDUCATION = 'education', 'Education Service'
        HEALTH = 'health', 'Health Service'
        AGRICULTURE = 'agriculture', 'Agriculture Service'
        MUNICIPAL = 'municipal', 'Municipal Service'
        WCD = 'wcd', 'Women & Child Development'
        OTHER = 'other', 'Other Government Service'
    class Status(models.TextChoices):
        # The twelve transparent statuses defined in the project specification.
        DRAFT = 'draft', 'Draft'
        SUBMITTED = 'submitted', 'Submitted'
        PROCESSING = 'processing', 'AI Verification in Progress'
        VERIFICATION = 'verification', 'AI Verification Completed'
        FORWARDED = 'forwarded', 'Forwarded to Department'
        PENDING_REVIEW = 'pending_review', 'Pending Officer Review'
        MORE_INFO = 'more_info', 'Additional Documents Required'
        RESUBMITTED = 'resubmitted', 'Resubmitted'
        REVIEW = 'review', 'Under Review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        CERTIFICATE_GENERATED = 'certificate_generated', 'Certificate Generated'
    public_id = models.CharField(max_length=16, unique=True, editable=False, db_index=True)
    citizen = models.ForeignKey(User, on_delete=models.PROTECT, related_name='applications')
    assigned_officer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_applications')
    category = models.CharField(max_length=20, choices=Category.choices)
    # The exact government service the citizen applied for. Set when the citizen
    # applies from a service page; drives the per-service document requirements.
    service = models.ForeignKey('GovernmentService', on_delete=models.SET_NULL, null=True, blank=True, related_name='applications')
    scheme = models.ForeignKey(Scheme, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    priority = models.CharField(max_length=10, default='Normal')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    income = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    land_area = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    form_data = models.JSONField(default=dict, blank=True)
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, blank=True, related_name='applications')
    def save(self, *args, **kwargs):
        if not self.public_id: self.public_id = 'JS-' + uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)
    @property
    def pending_days(self): return max(0, (timezone.now() - self.created_at).days)
    def __str__(self): return self.public_id

class ApplicationDocument(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to='documents/%Y/%m/')
    original_name = models.CharField(max_length=255)
    # Which required document this file is, chosen by the citizen at upload. The
    # AI document check matches files to the service checklist using this value.
    doc_type = models.CharField(max_length=160, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    ocr_status = models.CharField(max_length=30, default='not_processed')
    extracted_text = models.TextField(blank=True)
    extracted_fields = models.JSONField(default=dict, blank=True)
    ocr_confidence = models.FloatField(null=True, blank=True)
    ocr_warning = models.CharField(max_length=250, blank=True)

class ApplicationStatusHistory(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='history')
    status = models.CharField(max_length=24, choices=Application.Status.choices)
    remark = models.TextField(blank=True)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class EligibilityAssessment(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='assessments')
    outcome = models.CharField(max_length=32)
    explanation = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

class CompensationConfiguration(models.Model):
    land_category = models.CharField(max_length=80, unique=True)
    base_rate = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multiplier = models.DecimalField(max_digits=6, decimal_places=3, default=1)
    additional_components = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    active = models.BooleanField(default=True)
    def __str__(self): return self.land_category

class CompensationEstimate(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='compensation_estimates')
    configuration = models.ForeignKey(CompensationConfiguration, on_delete=models.PROTECT)
    area = models.DecimalField(max_digits=12, decimal_places=3)
    estimated_amount = models.DecimalField(max_digits=16, decimal_places=2)
    breakdown = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class OfficerRemark(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='remarks')
    officer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    application = models.ForeignKey(Application, on_delete=models.CASCADE, null=True, blank=True)
    message = models.CharField(max_length=250)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    application = models.ForeignKey(Application, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    # Application categories this department handles. New cases of these
    # categories are routed here automatically and shown to its officers.
    categories = models.JSONField(default=list, blank=True)
    # Bootstrap icon class shown on the citizen dashboard department card.
    icon = models.CharField(max_length=40, blank=True, default='bi-building')
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    class Meta:
        ordering = ['order', 'name']
    def __str__(self): return self.name
    def active_services(self):
        return self.services.filter(active=True).order_by('order', 'name')


class GovernmentService(models.Model):
    """A configurable government service offered by a department.

    The administrator creates and edits services here, and configures the exact
    documents each one needs (see ServiceDocumentRequirement). The citizen
    catalogue, the application form, the AI document check and the certificate
    all read from this table, so nothing is hardcoded in the frontend.
    """
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='services')
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=90, unique=True, blank=True)
    category = models.CharField(max_length=20, choices=Application.Category.choices, default=Application.Category.REVENUE,
                                help_text='Used to route the case to the right department queue.')
    description = models.TextField(blank=True)
    eligibility = models.TextField(blank=True, help_text='Who can apply for this service.')
    processing_time = models.CharField(max_length=90, blank=True, default='7-15 working days')
    instructions = models.TextField(blank=True, help_text='Step-by-step guidance shown on the service page.')
    fee = models.CharField(max_length=80, blank=True, default='As per government notification')
    icon = models.CharField(max_length=40, blank=True, default='bi-file-earmark-text')
    active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['order', 'name']
        constraints = [models.UniqueConstraint(fields=['department', 'name'], name='unique_service_per_department')]
    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.name)[:80] or 'service'
            candidate, n = base, 1
            while GovernmentService.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                n += 1
                candidate = f'{base}-{n}'
            self.slug = candidate
        super().save(*args, **kwargs)
    def __str__(self): return f'{self.name} ({self.department.name})'
    def requirement_names(self):
        return [row.name for row in self.requirements.filter(active=True).order_by('order', 'id')]


class ServiceDocumentRequirement(models.Model):
    """One document a citizen must (or may) upload for a given service."""
    service = models.ForeignKey(GovernmentService, on_delete=models.CASCADE, related_name='requirements')
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=250, blank=True)
    required = models.BooleanField(default=True)
    accepted_formats = models.CharField(max_length=80, blank=True, default='PDF, JPG, PNG')
    max_size_mb = models.PositiveSmallIntegerField(default=8)
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    class Meta:
        ordering = ['order', 'id']
    def __str__(self): return self.name


class ApplicationField(models.Model):
    """One labelled value the citizen filled in on the application form.

    Stored as rows (and not only inside Application.form_data) so the officer
    screen, the AI summary and the certificate all read the same values.
    """
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='fields')
    label = models.CharField(max_length=160)
    value = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['order', 'id']
    def __str__(self): return f'{self.label}: {self.value[:40]}'


class DocumentAnalysis(models.Model):
    """AI verification result for one uploaded document."""
    class Verdict(models.TextChoices):
        OK = 'ok', 'Verified'
        UNCLEAR = 'unclear', 'Unclear'
        MISMATCH = 'mismatch', 'Mismatch'
        PENDING = 'pending', 'Pending review'
    document = models.ForeignKey(ApplicationDocument, on_delete=models.CASCADE, related_name='analysis')
    checklist_item = models.CharField(max_length=200, blank=True)
    detected_type = models.CharField(max_length=160, blank=True)
    matched = models.BooleanField(default=False)
    confidence = models.FloatField(null=True, blank=True)
    verdict = models.CharField(max_length=12, choices=Verdict.choices, default=Verdict.PENDING)
    notes = models.CharField(max_length=250, blank=True)
    extracted = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'{self.checklist_item or self.detected_type} ({self.verdict})'


class AIAnalysisReport(models.Model):
    """Aggregated AI verification summary for one application.

    A single report per application keeps the checklist outcome, the text
    summary shown to the officer and the JSON payload used by the report screen.
    """
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='ai_report')
    headline = models.CharField(max_length=250, blank=True)
    summary = models.TextField(blank=True)
    verified_count = models.PositiveIntegerField(default=0)
    required_count = models.PositiveIntegerField(default=0)
    ready = models.BooleanField(default=False)
    checklist = models.JSONField(default=list, blank=True)
    missing = models.JSONField(default=list, blank=True)
    unclear = models.JSONField(default=list, blank=True)
    extras = models.JSONField(default=list, blank=True)
    problems = models.JSONField(default=list, blank=True)
    engine = models.CharField(max_length=60, blank=True, default='rules+ocr')
    generated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return f'AI report · {self.application.public_id}'


class CorrectionRequest(models.Model):
    """An officer's request for the citizen to fix or re-upload documents."""
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        RESOLVED = 'resolved', 'Resolved'
        CANCELLED = 'cancelled', 'Cancelled'
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='correction_requests')
    officer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='correction_requests')
    item = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-created_at']
    def __str__(self): return f'{self.application.public_id} · {self.item or "correction"}'


class CertificateTemplate(models.Model):
    """Layout and metadata used when a certificate is generated for a service."""
    service = models.OneToOneField(GovernmentService, on_delete=models.CASCADE, related_name='certificate_template')
    title = models.CharField(max_length=180, default='Certificate')
    subtitle = models.CharField(max_length=250, blank=True)
    body = models.TextField(blank=True, help_text='Certificate body text shown above the signature block.')
    signatory_name = models.CharField(max_length=160, blank=True)
    signatory_designation = models.CharField(max_length=160, blank=True)
    validity = models.CharField(max_length=140, blank=True, default='Valid for one year from the date of issue')
    footer_note = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return self.title


class GeneratedCertificate(models.Model):
    """A generated, publicly verifiable certificate for an approved application."""
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='certificate_record')
    template = models.ForeignKey(CertificateTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    certificate_number = models.CharField(max_length=40, unique=True, db_index=True)
    verification_code = models.CharField(max_length=40, unique=True, db_index=True)
    issued_on = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True)
    pdf = models.FileField(upload_to='certificates/%Y/%m/', blank=True, null=True)
    payload = models.JSONField(default=dict, blank=True)
    revoked = models.BooleanField(default=False)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.certificate_number

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    date_of_birth = models.DateField(null=True, blank=True)
    def __str__(self): return self.user.username

class Citizen(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='citizen_record')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.user.username

class Officer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='officer_record')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='officers')
    designation = models.CharField(max_length=120, blank=True, default='Review Officer')
    allowed_modules = models.JSONField(default=list, blank=True)
    allowed_categories = models.JSONField(default=list, blank=True)
    def __str__(self): return self.user.get_full_name() or self.user.username

class EmailLog(models.Model):
    class Status(models.TextChoices):
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
    recipient = models.EmailField()
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='email_logs')
    application = models.ForeignKey(Application, on_delete=models.SET_NULL, null=True, blank=True)
    kind = models.CharField(max_length=60)
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    error = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    def __str__(self): return f'{self.kind} -> {self.recipient} ({self.status})'

class GovernmentScheme(Scheme):
    class Meta:
        proxy = True

class EligibilityRule(models.Model):
    class Operator(models.TextChoices):
        LTE = 'lte', 'Less than or equal'
        GTE = 'gte', 'Greater than or equal'
        REQUIRED = 'required', 'Required'
    scheme = models.ForeignKey(Scheme, on_delete=models.CASCADE, related_name='rules')
    name = models.CharField(max_length=160)
    field_name = models.CharField(max_length=40)
    operator = models.CharField(max_length=12, choices=Operator.choices, default=Operator.LTE)
    threshold = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    def __str__(self): return self.name

class EligibilityResult(EligibilityAssessment):
    class Meta:
        proxy = True

class ExtractedDocumentData(models.Model):
    document = models.ForeignKey(ApplicationDocument, on_delete=models.CASCADE, related_name='extracted_rows')
    field_name = models.CharField(max_length=40)
    value = models.CharField(max_length=180, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=20, default='ocr')
    missing = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

class CompensationRule(CompensationConfiguration):
    class Meta:
        proxy = True

class ApplicationAssignment(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='assignments')
    officer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='assignment_records')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assignments_made')
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ApplicationRemark(models.Model):
    class Kind(models.TextChoices):
        INTERNAL = 'internal', 'Internal'
        CITIZEN = 'citizen', 'Citizen response'
        REQUEST = 'request', 'Document request'
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='case_remarks')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.INTERNAL)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class AnomalyFlag(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='anomaly_flags')
    kind = models.CharField(max_length=40)
    detail = models.TextField()
    dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ('application', 'kind')

class EmailTemplate(models.Model):
    """An administrator-editable subject and body for one notification event.

    The administrator console edits these. The notification layer renders them
    with the event's values (applicant name, application number, service,
    certificate number, secure links) and falls back to the built-in text when
    no active template is configured for the event.
    """
    kind = models.CharField(max_length=60, unique=True, db_index=True)
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=250, blank=True, help_text='When this email is sent.')
    placeholders = models.CharField(max_length=250, blank=True, help_text='Comma-separated values you can use in the subject and body.')
    subject = models.CharField(max_length=200)
    body = models.TextField()
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['name']
    def __str__(self): return self.name

class AssistantFAQ(models.Model):
    """Approved question/answer knowledge used by the AI Citizen Assistant.

    The assistant only ever returns text configured here; it never invents an
    answer, and it always reminds the citizen that an authorised officer makes
    the final decision.
    """
    question = models.CharField(max_length=200, unique=True)
    answer = models.TextField()
    keywords = models.CharField(max_length=240, blank=True)
    topic = models.CharField(max_length=60, blank=True)
    active = models.BooleanField(default=True)
    def __str__(self): return self.question
