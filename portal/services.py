from pathlib import Path
from django.conf import settings
from django.core.files.base import ContentFile
from decimal import Decimal
import re
import secrets
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import Application, ApplicationStatusHistory, ApplicationDocument, AuditLog, CompensationEstimate, EligibilityAssessment, EligibilityRule, ExtractedDocumentData, Notification

ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}

# Documents a citizen must attach for each service. Shown while applying and
# reused by the AI assistant so guidance stays consistent with the department.
REQUIRED_DOCUMENTS = {
    'welfare': [
        'Identity proof (Aadhaar / Voter ID / Passport)',
        'Address proof (ration card or electricity bill)',
        'Income certificate or self-declaration of household income',
        'Bank passbook copy (for benefit transfer)',
        'Passport-size photograph',
    ],
    'disaster': [
        'Identity proof (Aadhaar / Voter ID)',
        'Address proof / residence certificate',
        'Photographs of the damage or loss',
        'Loss or damage estimate or panchnama (if available)',
        'Bank passbook copy',
    ],
    'land': [
        'Identity proof (Aadhaar / Voter ID)',
        'Land ownership record (7/12 extract, Form I & XIV)',
        'Survey number / property map',
        'Sale deed or inheritance document',
        'Bank passbook copy',
    ],
    'revenue': [
        'Identity proof (Aadhaar / Voter ID)',
        'Address proof / residence certificate',
        'Property or record document relevant to the service requested',
        'Supporting affidavit (if applicable)',
    ],
}


def required_documents(category):
    """Return the list of documents a citizen must attach for this service."""
    return REQUIRED_DOCUMENTS.get(category, ['Identity proof', 'Address proof'])


# Each revenue service issues its own certificate and therefore needs its own
# set of documents. Add a service here and the citizen form, the AI document
# check, the officer view and the certificate all pick it up automatically.
SERVICE_CATALOG = {
    'income_certificate': {
        'label': 'Income Certificate',
        'documents': [
            'Identity proof (Aadhaar / Voter ID)',
            'Address proof (ration card or electricity bill)',
            'Income proof (salary slips, ITR or self-declaration of annual income)',
            'Ration card (for family income verification)',
            'Passport-size photograph',
        ],
    },
    'domicile_certificate': {
        'label': 'Domicile / Residence Certificate',
        'documents': [
            'Identity proof (Aadhaar / Voter ID)',
            'Proof of continuous residence (ration card, electricity bill or school record)',
            'Birth certificate or school leaving certificate',
            'Passport-size photograph',
        ],
    },
    'caste_certificate': {
        'label': 'Caste Certificate',
        'documents': [
            'Identity proof (Aadhaar / Voter ID)',
            'Caste proof from father or relative (existing certificate or school record)',
            'Address proof',
            'Passport-size photograph',
        ],
    },
    'birth_certificate': {
        'label': 'Birth Certificate',
        'documents': [
            'Hospital birth record or discharge summary',
            'Identity proof of both parents (Aadhaar / Voter ID)',
            'Address proof',
            'Marriage certificate of parents (if applicable)',
        ],
    },
    'death_certificate': {
        'label': 'Death Certificate',
        'documents': [
            'Hospital death summary or medical certificate',
            'Identity proof of the deceased',
            'Identity proof of the applicant (with relation proof)',
            'Address proof',
        ],
    },
    'marriage_certificate': {
        'label': 'Marriage Certificate',
        'documents': [
            'Identity proof of both spouses (Aadhaar / Voter ID)',
            'Address proof of both spouses',
            'Marriage photograph or invitation card',
            'Age proof (birth certificate or school leaving certificate)',
        ],
    },
    'land_record_copy': {
        'label': 'Land Record / 7-12 Extract Copy',
        'documents': [
            'Identity proof (Aadhaar / Voter ID)',
            'Survey number and property details',
            'Previous land record or sale deed',
            'Address proof',
        ],
    },
    'property_valuation': {
        'label': 'Property Valuation / NOC',
        'documents': [
            'Identity proof (Aadhaar / Voter ID)',
            'Property ownership document (sale deed or 7-12 extract)',
            'Property tax receipt',
            'Address proof',
        ],
    },
    'other_revenue': {
        'label': 'Other Revenue Service',
        'documents': [
            'Identity proof (Aadhaar / Voter ID)',
            'Address proof / residence certificate',
            'Document relevant to the service requested',
        ],
    },
}

SERVICE_ALIASES = {
    'income': 'income_certificate',
    'income_certificate': 'income_certificate',
    'domicile': 'domicile_certificate',
    'residence_certificate': 'domicile_certificate',
    'caste': 'caste_certificate',
    'birth': 'birth_certificate',
    'death': 'death_certificate',
    'marriage': 'marriage_certificate',
    'land_record': 'land_record_copy',
    '7_12': 'land_record_copy',
    'property': 'property_valuation',
    'noc': 'property_valuation',
}


def _slugify(value):
    return re.sub(r'[^a-z0-9]+', '_', (value or '').strip().lower()).strip('_')


def resolve_service(value):
    """Map a service name or slug (e.g. 'Income certificate') to a catalog key."""
    text = _slugify(value)
    if not text:
        return None
    if text in SERVICE_CATALOG:
        return text
    for key, meta in SERVICE_CATALOG.items():
        if _slugify(meta['label']) == text:
            return key
    return SERVICE_ALIASES.get(text)


def service_label(category, service_type=None):
    """Human-readable service name shown to citizens and officers."""
    if category == Application.Category.REVENUE:
        key = resolve_service(service_type)
        if key:
            return SERVICE_CATALOG[key]['label']
    return dict(Application.Category.choices).get(category, category)


def service_documents(category, service_type=None):
    """Documents required for the exact service the citizen selected."""
    if category == Application.Category.REVENUE:
        key = resolve_service(service_type)
        if key:
            return list(SERVICE_CATALOG[key]['documents'])
    return required_documents(category)


def application_service(application):
    """Human-readable name of the exact service this application is for.

    Prefers the configured GovernmentService the citizen applied for and falls
    back to the built-in catalogue for cases created before the catalogue
    existed.
    """
    if application.service_id:
        return application.service.name
    return service_label(application.category, (application.form_data or {}).get('service_type'))


def _catalogue_documents(application):
    return service_documents(application.category, (application.form_data or {}).get('service_type'))


def application_requirements(application):
    """The document checklist for this application.

    Each entry is {'name', 'required', 'hint'}. When the case is linked to a
    configured service the checklist comes from the database so the
    administrator controls it; otherwise the built-in catalogue is used.
    """
    if application.service_id:
        rows = application.service.requirements.filter(active=True).order_by('order', 'id')
        items = [{'name': row.name, 'required': row.required, 'hint': row.description or ''} for row in rows]
        if items:
            return items
    return [{'name': name, 'required': True, 'hint': ''} for name in _catalogue_documents(application)]


def application_documents(application):
    """List of required document names (kept for the existing templates)."""
    return [row['name'] for row in application_requirements(application)]


def _doc_keywords(text):
    """Keywords used to match an uploaded file to a required document."""
    words = set()
    for group in re.findall(r'\(([^)]*)\)', text or ''):
        words.update(part.strip().lower() for part in re.split(r'[/,]', group) if len(part.strip()) > 3)
    base = re.sub(r'\([^)]*\)', ' ', text or '').lower()
    words.update(word for word in re.findall(r'[a-z]{4,}', base) if word not in ('proof', 'copy', 'applicable'))
    return words


def document_check(application):
    """AI pre-check of the uploaded documents against the service checklist.

    Every uploaded file is matched to a required document by the type chosen at
    upload (falling back to filename and OCR-text keywords). The result tells the
    citizen what is correct, what is missing and what could not be read. It is
    advice only; an authorised officer still verifies everything.
    """
    requirements = application_requirements(application)
    documents = list(application.documents.all())
    used = set()
    items = []
    missing, unclear = [], []

    for requirement in requirements:
        name, required = requirement['name'], requirement['required']
        match = None
        for doc in documents:
            if doc.id in used:
                continue
            if (doc.doc_type or '').strip().lower() == name.strip().lower():
                match = doc
                break
        if match is None:
            keywords = _doc_keywords(name)
            for doc in documents:
                if doc.id in used:
                    continue
                haystack = f'{doc.original_name} {doc.extracted_text or ""}'.lower()
                if keywords and any(word in haystack for word in keywords):
                    match = doc
                    break
        if match is None:
            if required:
                state, evidence, note = 'missing', '', 'Not uploaded yet.'
                missing.append(name)
            else:
                state, evidence, note = 'optional', '', 'Optional document — not uploaded.'
        else:
            used.add(match.id)
            readable = match.ocr_status == 'completed' and bool((match.extracted_text or '').strip())
            if readable:
                state, note = 'verified', 'Read successfully by OCR.'
            else:
                state, note = 'unclear', (match.ocr_warning or 'Could not read clearly — a clearer scan or manual entry is needed.')
                if required:
                    unclear.append(name)
            evidence = match.original_name
        items.append({'label': name, 'state': state, 'evidence': evidence, 'note': note, 'required': required})

    extra = [doc.original_name for doc in documents if doc.id not in used]

    if not documents:
        status, headline = 'pending', 'No documents uploaded yet. Upload the required documents to start the AI check.'
    elif missing:
        status = 'attention'
        headline = f'{len(missing)} required document(s) still missing: ' + ', '.join(missing[:3]) + ('…' if len(missing) > 3 else '')
    elif unclear:
        status, headline = 'attention', f'All documents received, but {len(unclear)} could not be read clearly.'
    else:
        status, headline = 'complete', 'All required documents received and readable — ready for officer verification.'

    problems = [f'{item["label"]}: {item["note"]}' for item in items if item['state'] == 'unclear']
    return {
        'status': status,
        'headline': headline,
        'items': items,
        'missing': missing,
        'unclear': unclear,
        'extra_documents': extra,
        'problems': problems,
        'verified_count': sum(1 for item in items if item['state'] == 'verified'),
        'required_count': sum(1 for item in requirements if item['required']),
        'ready': bool(documents) and not missing,
    }


def risk_category(check):
    """Map the AI check to the four risk buckets defined in the specification."""
    if check['missing']:
        return 'Incomplete'
    if check['unclear']:
        return 'Needs Review'
    if check['problems']:
        return 'Potential Mismatch'
    return 'Passed'


def _analysis_summary(application, check):
    """Plain-language summary of the automated checks for the officer."""
    bullets = [
        f'Documents received: {len(application.documents.all())}',
        f'Required documents verified: {check["verified_count"]} of {check["required_count"]}',
        f'Outcome: {risk_category(check)}',
    ]
    if check['missing']:
        bullets.append('Missing: ' + ', '.join(check['missing']))
    if check['unclear']:
        bullets.append('Could not be read clearly: ' + ', '.join(check['unclear']))
    if check['extra_documents']:
        bullets.append('Additional files not on the checklist: ' + ', '.join(check['extra_documents']))
    bullets.append('This is an automated assistance report only. It does not certify authenticity — '
                   'the authorised officer makes the final decision.')
    return '\n'.join(bullets)


def write_analysis_report(application, check=None):
    """Persist the AI verification report and per-document analysis rows.

    Called right after the automated check so the officer screen, the report
    cards and the audit trail all read the same stored outcome.
    """
    from .models import AIAnalysisReport, DocumentAnalysis
    check = check or document_check(application)
    report, _ = AIAnalysisReport.objects.get_or_create(application=application)
    report.headline = check['headline']
    report.summary = _analysis_summary(application, check)
    report.verified_count = check['verified_count']
    report.required_count = check['required_count']
    report.ready = check['ready']
    report.checklist = check['items']
    report.missing = check['missing']
    report.unclear = check['unclear']
    report.extras = check['extra_documents']
    report.problems = check['problems']
    report.save()

    by_name = {item['evidence']: item for item in check['items'] if item['evidence']}
    DocumentAnalysis.objects.filter(document__application=application).delete()
    rows = []
    for doc in application.documents.all():
        item = by_name.get(doc.original_name)
        if item:
            state = item['state']
            verdict = 'ok' if state == 'verified' else 'unclear' if state == 'unclear' else 'pending'
            notes = item['note']
            label = item['label']
        else:
            verdict, notes, label = 'pending', 'Not matched to a checklist item — review manually.', ''
        rows.append(DocumentAnalysis(
            document=doc, checklist_item=label[:200], detected_type=(doc.doc_type or '')[:160],
            matched=bool(item), confidence=doc.ocr_confidence, verdict=verdict,
            notes=notes[:250], extracted=doc.extracted_fields or {}))
    DocumentAnalysis.objects.bulk_create(rows)
    return report


def render_certificate(application, draft=False):
    """Render the certificate document. `draft` marks it as not-yet-approved."""
    from django.template.loader import render_to_string
    return render_to_string('applications/certificate.html', {
        'app': application,
        'service': application_service(application),
        'documents': application_documents(application),
        'check': document_check(application),
        'officer': application.assigned_officer,
        'issued_on': timezone.localdate(),
        'draft': draft,
    })


def _certificate_number(application):
    """Sequential, department-tagged certificate number (JS/<dept>/<year>/<n>)."""
    from .models import GeneratedCertificate
    year = timezone.localdate().year
    code = application.department.code if application.department_id else 'GEN'
    prefix = f'JS/{code}/{year}/'
    last = GeneratedCertificate.objects.filter(certificate_number__startswith=prefix).order_by('-id').first()
    serial = 1
    if last:
        try:
            serial = int(last.certificate_number.rsplit('/', 1)[1]) + 1
        except (ValueError, IndexError):
            serial = GeneratedCertificate.objects.filter(certificate_number__startswith=prefix).count() + 1
    return f'{prefix}{serial:05d}'


def verification_url(certificate):
    """Public URL encoded in the certificate QR code for authenticity checks."""
    from django.urls import reverse
    from .emails import site_url
    return site_url(reverse('verify_certificate', kwargs={'code': certificate.verification_code}))


def _draw_qr(pdf, url, x, y, size):
    """Draw a QR code onto the PDF canvas at (x, y) with the given size."""
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF
    widget = QrCodeWidget(url or '')
    bounds = widget.getBounds()
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, x, y)


def _resolve_signatory(application, certificate=None, officer=None, template=None):
    """Return (name, designation, approved_at_str) for the approving officer."""
    payload = (certificate.payload if certificate and isinstance(certificate.payload, dict) else {}) or {}
    approving_user = officer or application.assigned_officer
    name = ''
    designation = ''
    if officer:
        name = officer.get_full_name() or officer.username
        rec = getattr(officer, 'officer_record', None)
        if rec and rec.designation:
            designation = rec.designation
        elif getattr(officer, 'role', '') == 'admin':
            designation = 'District Collector / Administrator'
        else:
            designation = 'Authorised Signatory'
    elif payload.get('approved_by_name'):
        name = payload.get('approved_by_name', '')
        designation = payload.get('approved_by_designation', '')
    elif approving_user:
        name = approving_user.get_full_name() or approving_user.username
        rec = getattr(approving_user, 'officer_record', None)
        if rec and rec.designation:
            designation = rec.designation
        elif getattr(approving_user, 'role', '') == 'admin':
            designation = 'District Collector / Administrator'

    if not name and template and template.signatory_name:
        name = template.signatory_name
    if not designation:
        designation = (template.signatory_designation if template and template.signatory_designation else '') or 'Authorised Signatory'
    if application.department_id and application.department.name not in designation:
        designation = f'{designation}, {application.department.name}'

    approved_at = payload.get('approved_at') or timezone.localtime(timezone.now()).strftime('%d %b %Y, %I:%M %p IST')
    return name or 'Authorised Officer', designation, approved_at


def _draw_emblem(pdf, cx, cy, r, navy, gold):
    """Draw a clean official circular emblem/crest at (cx, cy)."""
    pdf.saveState()
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.4)
    pdf.circle(cx, cy, r, stroke=1, fill=0)
    pdf.setStrokeColor(navy)
    pdf.setLineWidth(0.8)
    pdf.circle(cx, cy, r - 2.5, stroke=1, fill=0)
    # Inner Chakra-like spokes.
    import math
    inner_r = r - 5
    pdf.setLineWidth(0.5)
    for i in range(12):
        angle = (math.pi / 6) * i
        pdf.line(cx, cy, cx + inner_r * math.cos(angle), cy + inner_r * math.sin(angle))
    pdf.setFillColor(gold)
    pdf.circle(cx, cy, 2.2, stroke=0, fill=1)
    pdf.restoreState()


def _draw_rubber_stamp(pdf, cx, cy, r, navy, teal):
    """Draw a realistic circular official office stamp at (cx, cy)."""
    import math
    pdf.saveState()
    pdf.setStrokeColor(colors_with_alpha(navy, 0.35))
    pdf.setLineWidth(1.6)
    pdf.circle(cx, cy, r, stroke=1, fill=0)
    pdf.setLineWidth(0.7)
    pdf.circle(cx, cy, r - 3.5, stroke=1, fill=0)
    pdf.circle(cx, cy, r - 12, stroke=1, fill=0)

    # Top and bottom curved-look labels inside the ring.
    pdf.setFillColor(colors_with_alpha(navy, 0.45))
    pdf.setFont('Helvetica-Bold', 5.5)
    pdf.drawCentredString(cx, cy + r - 9, 'DISTRICT COLLECTORATE')
    pdf.drawCentredString(cx, cy - r + 5.5, 'SOUTH GOA · JANSUTRA')

    # Center APPROVED badge.
    pdf.setFillColor(colors_with_alpha(teal, 0.55))
    pdf.setFont('Helvetica-Bold', 7.5)
    pdf.drawCentredString(cx, cy + 1.5, 'VERIFIED')
    pdf.setFont('Helvetica-Bold', 6.5)
    pdf.drawCentredString(cx, cy - 6.5, 'APPROVED')
    pdf.restoreState()


def colors_with_alpha(hex_color, alpha):
    from reportlab.lib import colors
    return colors.Color(hex_color.red, hex_color.green, hex_color.blue, alpha=alpha)


def _draw_handwritten_signature(pdf, name, x, y, width_pt=95):
    """Draw a smooth pen-stroke signature derived deterministically from `name`."""
    from reportlab.lib import colors
    pdf.saveState()
    ink = colors.HexColor('#1e3a8a')
    pdf.setStrokeColor(ink)
    pdf.setLineCap(1)
    pdf.setLineJoin(1)

    seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(name or 'Officer'))
    p = pdf.beginPath()
    p.moveTo(x, y + 4)
    # Initial capital flourish.
    p.curveTo(x + 6, y + 22, x + 18, y + 24, x + 15, y + 2)
    p.curveTo(x + 13, y - 4, x + 24, y + 14, x + 32, y + 9)
    # Wave strokes seeded by officer name.
    cur_x = x + 32
    steps = 5
    step_w = (width_pt - 38) / steps
    for i in range(steps):
        h1 = 8 + ((seed >> (i * 2)) % 10)
        h2 = -2 + ((seed >> (i * 2 + 1)) % 6)
        nx = cur_x + step_w
        p.curveTo(cur_x + step_w * 0.35, y + h1, cur_x + step_w * 0.7, y + h2, nx, y + 4 + (i % 2) * 2)
        cur_x = nx
    # Trailing underline flourish.
    p.curveTo(cur_x + 8, y + 10, cur_x + 12, y - 2, x + 14, y - 3)
    pdf.setLineWidth(1.35)
    pdf.drawPath(p, stroke=1, fill=0)
    pdf.restoreState()


def build_certificate_pdf(application, certificate=None, draft=False, officer=None):
    """Generate an official-grade certificate PDF with State emblem, verified
    particulars table, approving officer's digital signature & stamp, and QR code.

    `draft=True` stamps the document so an unapproved copy can never be mistaken
    for an officially issued certificate.
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import Paragraph, Frame, Table, TableStyle, Spacer
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.lib.enums import TA_JUSTIFY

    template = None
    if application.service_id:
        template = getattr(application.service, 'certificate_template', None)
    service = application_service(application)
    department = application.department
    citizen = application.citizen
    issued_on = certificate.issued_on if certificate else timezone.localdate()
    cert_number = certificate.certificate_number if certificate else None
    verify = verification_url(certificate) if certificate else ''

    title = (template.title if template and template.title else f'{service}').strip()
    subtitle = (template.subtitle if template else '').strip()
    body_text = (template.body if template and template.body else '').strip()
    validity = (template.validity if template else '').strip()
    footer_note = (template.footer_note if template else '').strip()
    signatory_name, signatory_designation, approved_at = _resolve_signatory(
        application, certificate=certificate, officer=officer, template=template)

    buffer = BytesIO()
    pdf = pdfcanvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 16 * mm
    navy = colors.HexColor('#0f3d5c')
    gold = colors.HexColor('#b45309')
    teal = colors.HexColor('#0f766e')
    slate = colors.HexColor('#475569')
    light_bg = colors.HexColor('#f8fafc')
    line_color = colors.HexColor('#cbd5e1')

    # Outer navy border, gold accent border, and inner thin border.
    pdf.setStrokeColor(navy)
    pdf.setLineWidth(2.2)
    pdf.rect(margin - 5, margin - 5, width - 2 * margin + 10, height - 2 * margin + 10)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(0.9)
    pdf.rect(margin - 1.5, margin - 1.5, width - 2 * margin + 3, height - 2 * margin + 3)
    pdf.setStrokeColor(navy)
    pdf.setLineWidth(0.4)
    pdf.rect(margin + 1.5, margin + 1.5, width - 2 * margin - 3, height - 2 * margin - 3)

    # Subtle diagonal security watermark across the background.
    pdf.saveState()
    pdf.setFillColor(colors.Color(0.06, 0.24, 0.36, alpha=0.04))
    pdf.setFont('Helvetica-Bold', 34)
    pdf.translate(width / 2, height / 2)
    pdf.rotate(32)
    pdf.drawCentredString(0, 28, 'GOVERNMENT OF GOA')
    pdf.setFont('Helvetica-Bold', 22)
    pdf.drawCentredString(0, -12, 'OFFICIAL DIGITAL CERTIFICATE')
    pdf.restoreState()

    if draft:
        pdf.saveState()
        pdf.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.14))
        pdf.setFont('Helvetica-Bold', 64)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(35)
        pdf.drawCentredString(0, 0, 'DRAFT')
        pdf.restoreState()

    # Top emblem + Government header.
    emblem_y = height - margin - 13 * mm
    _draw_emblem(pdf, width / 2, emblem_y, 7.5 * mm, navy, gold)

    y = emblem_y - 11 * mm
    pdf.setFillColor(navy)
    pdf.setFont('Helvetica-Bold', 14.5)
    pdf.drawCentredString(width / 2, y, 'GOVERNMENT OF GOA')
    y -= 5 * mm
    pdf.setFont('Helvetica-Bold', 10)
    pdf.setFillColor(gold)
    pdf.drawCentredString(width / 2, y, 'OFFICE OF THE DISTRICT COLLECTOR, SOUTH GOA')
    if department:
        y -= 4.8 * mm
        pdf.setFont('Helvetica-Bold', 9.5)
        pdf.setFillColor(navy)
        pdf.drawCentredString(width / 2, y, department.name.upper())

    # Certificate Title Banner.
    y -= 9 * mm
    pdf.setFillColor(colors.HexColor('#0b2942'))
    pdf.setFont('Helvetica-Bold', 16.5)
    pdf.drawCentredString(width / 2, y, title.upper())
    if subtitle:
        y -= 5 * mm
        pdf.setFont('Helvetica-Oblique', 9)
        pdf.setFillColor(slate)
        pdf.drawCentredString(width / 2, y, subtitle[:120])
    y -= 4 * mm
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.4)
    pdf.line(margin + 24 * mm, y, width - margin - 24 * mm, y)

    # Shaded metadata bar: Certificate No & Date of Issue.
    y -= 9 * mm
    bar_h = 7.5 * mm
    pdf.setFillColor(light_bg)
    pdf.setStrokeColor(line_color)
    pdf.setLineWidth(0.6)
    pdf.rect(margin + 5 * mm, y - 2 * mm, width - 2 * margin - 10 * mm, bar_h, stroke=1, fill=1)
    pdf.setFillColor(navy)
    pdf.setFont('Helvetica-Bold', 9)
    cert_label = f'Certificate No: {cert_number}' if cert_number else 'Certificate No: (Issued on approval)'
    pdf.drawString(margin + 8 * mm, y + 0.5 * mm, cert_label)
    pdf.drawRightString(width - margin - 8 * mm, y + 0.5 * mm, f'Date of Issue: {issued_on.strftime("%d %b %Y")}')

    # Certification body + Verified Particulars Table.
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle('cert-body', parent=styles['Normal'], fontName='Helvetica', fontSize=10.5,
                                leading=15.5, alignment=TA_JUSTIFY, textColor=colors.HexColor('#1e293b'))
    cell_label_style = ParagraphStyle('cell-lbl', parent=styles['Normal'], fontName='Helvetica-Bold',
                                      fontSize=9, leading=12, textColor=navy)
    cell_val_style = ParagraphStyle('cell-val', parent=styles['Normal'], fontName='Helvetica',
                                    fontSize=9, leading=12, textColor=colors.HexColor('#0f172a'))

    applicant_name = citizen.get_full_name() or citizen.username
    intro = (f'This is to certify that <b>{applicant_name}</b>, '
             f'resident of <b>{citizen.address or "South Goa District"}</b>, has been duly verified and granted '
             f'the <b>{service}</b> against Application ID <b>{application.public_id}</b>.')
    if body_text:
        intro += ' ' + body_text

    rows = [
        [Paragraph('Applicant Name', cell_label_style), Paragraph(applicant_name, cell_val_style)],
        [Paragraph('Application ID', cell_label_style), Paragraph(application.public_id, cell_val_style)],
        [Paragraph('Document / Service', cell_label_style), Paragraph(service, cell_val_style)],
    ]
    if department:
        rows.append([Paragraph('Issuing Department', cell_label_style), Paragraph(department.name, cell_val_style)])
    if application.income is not None:
        rows.append([Paragraph('Verified Annual Income', cell_label_style),
                     Paragraph(f'Rs. {application.income:,.0f}/-', cell_val_style)])
    if application.land_area is not None:
        rows.append([Paragraph('Land Area', cell_label_style),
                     Paragraph(f'{application.land_area} sq. m / ha', cell_val_style)])
    if citizen.address:
        rows.append([Paragraph('Residential Address', cell_label_style), Paragraph(citizen.address[:160], cell_val_style)])
    if isinstance(application.form_data, dict):
        for k, v in list(application.form_data.items())[:4]:
            if v not in (None, '', []):
                label = k.replace('_', ' ').title()
                rows.append([Paragraph(label, cell_label_style), Paragraph(str(v)[:100], cell_val_style)])
    rows.append([Paragraph('Verification Status', cell_label_style),
                 Paragraph('<font color="#0f766e"><b>VERIFIED &amp; APPROVED</b></font>', cell_val_style)])

    col_w1 = 48 * mm
    col_w2 = width - 2 * margin - 14 * mm - col_w1
    table = Table(rows, colWidths=[col_w1, col_w2])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), light_bg),
        ('BOX', (0, 0), (-1, -1), 0.7, line_color),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, line_color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    frame_top = y - 4 * mm
    frame_bottom = margin + 62 * mm
    frame = Frame(margin + 7 * mm, frame_bottom, width - 2 * margin - 14 * mm,
                  frame_top - frame_bottom, showBoundary=0, topPadding=0, bottomPadding=0)
    flow = [Paragraph(intro, body_style), Spacer(1, 5 * mm), table]
    frame.addFromList(flow, pdf)

    # Bottom-right: Official Stamp + Handwritten Signature + Digital Signature Verification Box.
    sig_box_w = 72 * mm
    sig_box_x = width - margin - 6 * mm - sig_box_w
    sig_box_y = margin + 22 * mm

    # Draw official circular stamp overlapping top-left of signature box.
    _draw_rubber_stamp(pdf, sig_box_x + 12 * mm, sig_box_y + 28 * mm, 13 * mm, navy, teal)

    # Draw handwritten vector signature above the line.
    if not draft:
        _draw_handwritten_signature(pdf, signatory_name, sig_box_x + 18 * mm, sig_box_y + 25 * mm, width_pt=48 * mm)

    # Digital signature box.
    pdf.setFillColor(colors.HexColor('#f0fdf4') if not draft else light_bg)
    pdf.setStrokeColor(teal if not draft else line_color)
    pdf.setLineWidth(0.7)
    pdf.roundRect(sig_box_x, sig_box_y, sig_box_w, 22 * mm, 3, stroke=1, fill=1)

    pdf.setFillColor(teal if not draft else slate)
    pdf.setFont('Helvetica-Bold', 7.5)
    badge_text = 'DIGITALLY SIGNED & VERIFIED' if not draft else 'SIGNATURE PENDING APPROVAL'
    pdf.drawString(sig_box_x + 3 * mm, sig_box_y + 17.5 * mm, badge_text)

    pdf.setFillColor(navy)
    pdf.setFont('Helvetica-Bold', 9)
    pdf.drawString(sig_box_x + 3 * mm, sig_box_y + 12.2 * mm, signatory_name[:34])
    pdf.setFillColor(slate)
    pdf.setFont('Helvetica', 7.5)
    pdf.drawString(sig_box_x + 3 * mm, sig_box_y + 7.5 * mm, signatory_designation[:44])
    pdf.setFont('Helvetica', 6.8)
    pdf.drawString(sig_box_x + 3 * mm, sig_box_y + 3 * mm, f'Signed on: {approved_at}')

    # Bottom-left: QR + verification details.
    qr_x = margin + 6 * mm
    qr_y = margin + 24 * mm
    if verify:
        pdf.setStrokeColor(line_color)
        pdf.setLineWidth(0.6)
        pdf.rect(qr_x - 1.5, qr_y - 1.5, 27 * mm + 3, 27 * mm + 3, stroke=1, fill=0)
        _draw_qr(pdf, verify, qr_x, qr_y, 27 * mm)

    pdf.setFont('Helvetica-Bold', 7.5)
    pdf.setFillColor(navy)
    qr_text_y = margin + 19 * mm
    pdf.drawString(qr_x, qr_text_y, 'Scan QR to verify authenticity')
    pdf.setFont('Helvetica', 7.5)
    pdf.setFillColor(slate)
    if cert_number:
        pdf.drawString(qr_x + 31 * mm, qr_text_y + 11 * mm, f'Certificate No: {cert_number}')
        pdf.drawString(qr_x + 31 * mm, qr_text_y + 6.5 * mm, f'Verification Code: {certificate.verification_code}')
    if verify:
        pdf.drawString(qr_x + 31 * mm, qr_text_y + 2 * mm, verify[:52])
    pdf.drawString(qr_x + 31 * mm, qr_text_y - 2.5 * mm,
                   (validity or 'Valid as per government rules from the date of issue.')[:58])

    footer = footer_note or ('This is a digitally signed official certificate issued via JanSutra AI. '
                             'Verify authenticity anytime at the verification URL or by scanning the QR code.')
    pdf.setFont('Helvetica-Oblique', 7.2)
    pdf.setFillColor(slate)
    pdf.drawCentredString(width / 2, margin + 5 * mm, footer[:155])
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def generate_certificate(application, officer=None):
    """Create or refresh the verifiable certificate for an approved case.

    Generates the certificate number, a public verification code, the PDF (with
    QR code and approving officer's digital signature) and stores it against the
    application so the citizen and the officer portal both serve the same document.
    """
    from .models import GeneratedCertificate
    template = None
    if application.service_id:
        template = getattr(application.service, 'certificate_template', None)
    certificate = getattr(application, 'certificate_record', None)
    if certificate is None:
        certificate = GeneratedCertificate(application=application)
    if not certificate.certificate_number:
        certificate.certificate_number = _certificate_number(application)
    if not certificate.verification_code:
        certificate.verification_code = secrets.token_hex(6).upper()
    certificate.template = template
    certificate.issued_on = timezone.localdate()

    signatory_name, signatory_designation, approved_at = _resolve_signatory(
        application, certificate=certificate, officer=officer, template=template)
    certificate.payload = {
        'service': application_service(application),
        'citizen': application.citizen.get_full_name() or application.citizen.username,
        'application': application.public_id,
        'department': application.department.name if application.department_id else '',
        'verified_count': document_check(application)['verified_count'],
        'approved_by_name': signatory_name,
        'approved_by_designation': signatory_designation,
        'approved_at': approved_at,
    }
    pdf_bytes = build_certificate_pdf(application, certificate=certificate, officer=officer)
    filename = certificate.certificate_number.replace('/', '-') + '.pdf'
    certificate.pdf.save(filename, ContentFile(pdf_bytes), save=False)
    certificate.save()
    return certificate


def save_application_documents(application, uploads, labels):
    """Attach the documents uploaded inside the application form to the case.

    `uploads` and `labels` are {index: uploaded_file} and {index: document_type}
    maps, so every file is paired with the exact document type the citizen chose
    for it. Each file is OCR-processed straight away.
    """
    saved = []
    for index in sorted(uploads):
        upload = uploads[index]
        doc = ApplicationDocument(
            application=application,
            file=upload,
            original_name=upload.name,
            content_type=getattr(upload, 'content_type', '') or '',
            doc_type=(labels.get(index) or '').strip()[:160],
        )
        doc.save()
        process_document(doc)
        saved.append(doc)
    return saved


def department_for_category(category):
    """Return the active department that handles this application category.

    Departments opt in by listing the categories they handle, so the Collector
    can add any department (for example "Income Tax") and route cases to it.
    Returns None when no department claims the category.
    """
    from .models import Department
    for department in Department.objects.filter(active=True).order_by('name'):
        if category in (department.categories or []):
            return department
    return None


def extract_candidate_fields(text):
    """Extract only explicitly labeled text; all returned values remain unverified candidates."""
    patterns = {
        'applicant_name': r'(?im)^\s*(?:applicant\s+name|name)\s*[:\-]\s*(.{2,100})\s*$',
        'document_number': r'(?im)^\s*(?:document\s*(?:number|no\.?)|id\s*(?:number|no\.?))\s*[:\-]\s*([A-Z0-9\-/]{4,40})\s*$',
        'address': r'(?im)^\s*(?:address|residential\s+address)\s*[:\-]\s*(.{4,180})\s*$',
        'date_of_birth': r'(?im)^\s*(?:date\s+of\s+birth|dob)\s*[:\-]\s*(.{4,30})\s*$',
        'income': r'(?im)^\s*(?:annual\s+income|income)\s*[:\-]\s*([₹Rs.\s0-9,]+)\s*$',
        'survey_number': r'(?im)^\s*(?:survey\s*(?:number|no\.?))\s*[:\-]\s*([A-Z0-9\-/]{2,40})\s*$',
        'document_date': r'(?im)^\s*(?:document\s+date|date\s+of\s+issue)\s*[:\-]\s*(.{4,30})\s*$',
    }
    found = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, text or '')
        if match:
            found[field] = match.group(1).strip()[:180]
    return found

def process_document(document):
    """Best-effort OCR. Missing optional OCR tools produce an honest manual-review status."""
    ext = Path(document.original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        document.ocr_status, document.ocr_warning = 'unsupported', 'Use PDF, JPG, JPEG or PNG.'
    else:
        try:
            import pytesseract
            if ext == '.pdf':
                try:
                    from pdf2image import convert_from_path
                    pages = convert_from_path(document.file.path, first_page=1, last_page=5)
                except Exception:
                    document.ocr_status, document.ocr_warning = 'manual_review', 'PDF OCR needs Poppler; enter details manually.'
                    document.save(update_fields=['ocr_status', 'ocr_warning'])
                    sync_extracted_rows(document)
                    return
            else:
                from PIL import Image, ImageOps, ImageEnhance
                img = Image.open(document.file.path).convert('RGB')
                try:
                    import cv2
                    import numpy as np
                    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
                    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    img = Image.fromarray(binary)
                except Exception:
                    img = ImageEnhance.Contrast(ImageOps.grayscale(img)).enhance(1.5)
                pages = [img]
            from pytesseract import Output
            texts, confidences = [], []
            for page in pages:
                texts.append(pytesseract.image_to_string(page))
                data = pytesseract.image_to_data(page, output_type=Output.DICT)
                confidences.extend(float(c) for c in data.get('conf', []) if str(c).strip() not in ('', '-1') and float(c) >= 0)
            text = '\n'.join(texts).strip()
            document.extracted_text = text
            document.extracted_fields = extract_candidate_fields(text)
            document.ocr_confidence = round(sum(confidences) / len(confidences), 1) if confidences else None
            document.ocr_status = 'completed' if text else 'no_text'
            document.ocr_warning = '' if text else 'No text was detected. Please enter details manually.'
        except ImportError:
            document.ocr_status, document.ocr_warning = 'manual_review', 'OCR is not configured. No text was extracted; enter details manually.'
        except Exception as exc:
            document.ocr_status, document.ocr_warning = 'failed', f'OCR failed ({type(exc).__name__}). You can enter details manually.'
    document.save(update_fields=['ocr_status', 'ocr_warning', 'extracted_text', 'extracted_fields', 'ocr_confidence'])
    sync_extracted_rows(document)
    return document

def sync_extracted_rows(document):
    expected = ('applicant_name', 'document_number', 'address', 'date_of_birth', 'income', 'survey_number', 'document_date')
    fields = document.extracted_fields or {}
    document.extracted_rows.all().delete()
    rows = []
    for key in expected:
        value = (fields.get(key) or '').strip()
        rows.append(ExtractedDocumentData(
            document=document, field_name=key, value=value[:180],
            confidence=document.ocr_confidence, source='manual' if document.ocr_status == 'corrected' else 'ocr',
            missing=not value,
        ))
    ExtractedDocumentData.objects.bulk_create(rows)

def _compare(operator, value, threshold):
    limit = Decimal(str(threshold))
    if operator == EligibilityRule.Operator.GTE:
        return value >= limit
    return value <= limit

def assess_eligibility(application):
    reasons = []
    rules = list(application.scheme.rules.filter(active=True)) if application.scheme_id else []
    if application.scheme_id and rules:
        missing = failed = False
        for rule in rules:
            if rule.field_name == 'documents':
                present = application.documents.exists()
                reasons.append('Supporting documents are uploaded.' if present else 'Supporting documents are missing.')
                if not present:
                    missing = True
                continue
            if rule.field_name == 'income':
                if application.income is None:
                    missing = True
                    reasons.append('Applicant income was not provided.')
                    continue
                ok = _compare(rule.operator, application.income, rule.threshold or '0')
                reasons.append(f'Income meets the demonstration rule "{rule.name}".' if ok else f'Income does not meet the demonstration rule "{rule.name}".')
                failed = failed or not ok
                continue
            if rule.field_name == 'land_area':
                if application.land_area is None:
                    missing = True
                    reasons.append('Land area was not provided.')
                    continue
                ok = _compare(rule.operator, application.land_area, rule.threshold or '0')
                reasons.append(f'Land area meets "{rule.name}".' if ok else f'Land area does not meet "{rule.name}".')
                failed = failed or not ok
                continue
            if rule.field_name.startswith('form.'):
                key = rule.field_name.split('.', 1)[1]
                present = bool((application.form_data or {}).get(key))
                reasons.append(f'{key.replace("_", " ").title()} is present.' if present else f'{key.replace("_", " ").title()} is required.')
                if not present:
                    missing = True
        if missing:
            result = 'More Information Required'
        elif failed:
            result = 'Not Eligible'
        elif application.documents.exists():
            result = 'Eligible'
        else:
            result = 'Potentially Eligible'
            reasons.append('Supporting documents are missing.')
        reasons.append('This is a recommendation only. An authorized officer makes the official decision.')
        return EligibilityAssessment.objects.create(application=application, outcome=result, explanation=reasons)
    if not application.scheme:
        result = 'More Information Required'; reasons.append('No demonstration scheme is selected.')
    else:
        if application.income is None:
            result = 'More Information Required'; reasons.append('Applicant income was not provided.')
        elif application.income <= application.scheme.income_limit:
            result = 'Potentially Eligible'; reasons.append(f'Income is within the demonstration threshold of ₹{application.scheme.income_limit:,.0f}.')
        else:
            result = 'Not Eligible'; reasons.append('Income is above the configured demonstration threshold.')
        if application.documents.exists(): reasons.append('At least one supporting document is uploaded; officer verification is still required.')
        else: reasons.append('Supporting documents are missing.')
    if not application.documents.exists() and result == 'Potentially Eligible': result = 'More Information Required'
    return EligibilityAssessment.objects.create(application=application, outcome=result, explanation=reasons)

def change_status(application, status, actor, remark=''):
    with transaction.atomic():
        application.status = status
        application.save(update_fields=['status', 'updated_at'])
        ApplicationStatusHistory.objects.create(application=application, status=status, actor=actor, remark=remark)
        if actor: AuditLog.objects.create(actor=actor, application=application, action='status_change', detail=f'{status}: {remark}')
        note = f'{application.public_id} status updated: {application.get_status_display()}'
        if remark: note += f' — {remark[:90]}'
        Notification.objects.create(recipient=application.citizen, application=application, message=note[:250])

def potential_duplicates(application):
    cutoff = timezone.now() - timedelta(days=90)
    matches = list(Application.objects.filter(
        citizen=application.citizen, category=application.category, created_at__gte=cutoff,
    ).exclude(pk=application.pk).exclude(status__in=[Application.Status.APPROVED, Application.Status.REJECTED]).order_by('-created_at')[:5])
    this_ids = set(ApplicationDocument.objects.filter(application=application).values_list('extracted_fields__document_number', flat=True)) - {None, ''}
    if this_ids:
        docs = ApplicationDocument.objects.exclude(application=application).filter(extracted_fields__document_number__in=this_ids).select_related('application')
        known = {a.pk for a in matches}
        for doc in docs:
            if doc.application_id not in known:
                matches.append(doc.application)
                known.add(doc.application_id)
    return matches[:8]

def refresh_anomalies(application):
    from .models import AnomalyFlag
    findings = []
    duplicates = potential_duplicates(application)
    if duplicates:
        ids = ', '.join(item.public_id for item in duplicates[:4])
        findings.append(('possible_duplicate', f'Similar open applications for the same person and service: {ids}. Review before deciding.'))
    numbers = [row.value for row in ExtractedDocumentData.objects.filter(document__application=application, field_name='document_number', missing=False).exclude(value='')]
    if numbers:
        reused = ExtractedDocumentData.objects.filter(field_name='document_number', value__in=numbers).exclude(document__application=application).select_related('document__application')
        reused_ids = sorted({row.document.application.public_id for row in reused})
        if reused_ids:
            findings.append(('reused_document_number', f'Document number also appears on {", ".join(reused_ids[:4])}.'))
    if application.income is not None and application.income > Decimal('10000000'):
        findings.append(('unusual_income', 'Recorded income is unusually high for a demonstration case and should be checked.'))
    if application.land_area is not None and application.land_area > Decimal('5000'):
        findings.append(('unusual_land_area', 'Recorded land area is unusually large and should be checked against the uploaded record.'))
    if application.pending_days >= 14 and application.status not in (Application.Status.APPROVED, Application.Status.REJECTED) and not application.assigned_officer_id:
        findings.append(('unassigned_aging', 'This application is more than 14 days old and still has no assigned officer.'))
    for kind, detail in findings:
        flag, created = AnomalyFlag.objects.get_or_create(application=application, kind=kind, defaults={'detail': detail})
        if not created and not flag.dismissed and flag.detail != detail:
            flag.detail = detail
            flag.save(update_fields=['detail'])
    return application.anomaly_flags.filter(dismissed=False)

def delay_risk(application):
    score = min(100, application.pending_days * 7)
    reasons = [f'{application.pending_days} days pending']
    status_points = {'submitted': 5, 'processing': 10, 'verification': 15, 'review': 10, 'more_info': 22, 'forwarded': 8}
    if application.status in status_points:
        score += status_points[application.status]
        reasons.append(f'Current stage: {application.get_status_display()}')
    if not application.assigned_officer_id:
        score += 15
        reasons.append('Officer is not assigned')
    elif application.assigned_officer.assigned_applications.exclude(status__in=['approved', 'rejected']).count() >= 10:
        score += 10
        reasons.append('Assigned officer has a high pending workload')
    if application.status == 'more_info': reasons.append('Additional documents are required')
    score = min(100, score)
    level = 'High' if score >= 65 else 'Medium' if score >= 30 else 'Low'
    next_action = 'Contact the applicant or review outstanding documents' if application.status == 'more_info' else 'Assign an officer' if not application.assigned_officer_id else 'Review the next pending case step'
    return {'score': score, 'level': level, 'reasons': reasons, 'next_action': next_action}

def calculate_compensation(application, configuration, area):
    area = Decimal(str(area))
    if area <= 0: raise ValueError('Area must be greater than zero.')
    gross = area * configuration.base_rate * configuration.multiplier
    amount = max(Decimal('0'), gross + configuration.additional_components - configuration.deductions)
    breakdown = {
        'formula': '(area × base rate × multiplier) + additional components − deductions',
        'area': str(area), 'base_rate': str(configuration.base_rate), 'multiplier': str(configuration.multiplier),
        'additional_components': str(configuration.additional_components), 'deductions': str(configuration.deductions),
        'gross': str(gross.quantize(Decimal('0.01'))),
    }
    return CompensationEstimate.objects.create(application=application, configuration=configuration, area=area, estimated_amount=amount.quantize(Decimal('0.01')), breakdown=breakdown)

ASSISTANT_STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'can', 'do', 'does', 'for', 'from', 'how', 'i', 'in',
    'is', 'it', 'me', 'my', 'of', 'on', 'or', 'the', 'to', 'was', 'what', 'when', 'where', 'which', 'who',
    'why', 'will', 'with', 'you', 'your', 'kya', 'kaise', 'hai', 'ka', 'ki', 'ke', 'me', 'mein', 'aur', 'ko',
}

def _assistant_tokens(text):
    return [token for token in re.findall(r'[a-z0-9]+', (text or '').lower())
            if len(token) > 1 and token not in ASSISTANT_STOPWORDS]

def _gemini_answer(question, entries):
    """Ask the configured Google Gemini model, grounded on the approved FAQs.

    Returns the model's text, or None when no key is configured or the request
    fails so the caller can fall back to the deterministic FAQ matcher. The
    model is instructed to use only approved information and never to promise
    or decide an outcome.
    """
    import json
    import urllib.error
    import urllib.parse
    import urllib.request
    import time

    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        return None
    models = [getattr(settings, 'GEMINI_MODEL', 'gemini-3.8-flash')]
    models += [m for m in getattr(settings, 'GEMINI_FALLBACK_MODELS', []) if m not in models]
    knowledge = '\n'.join(f'Q: {entry.question}\nA: {entry.answer}' for entry in entries[:60])
    system_instruction = (
        'You are the JanSutra AI Citizen Assistant for the Revenue Department, District Collectorate, '
        'South Goa. Answer briefly and politely in the same language as the question (English, Hindi or Marathi). '
        'Use ONLY the approved information provided below. If it does not cover the question, say you are not sure '
        'and suggest contacting the district office. Never approve, reject, or guarantee any government outcome — '
        'an authorised officer makes every final decision. Do not invent schemes, fees, or deadlines.'
    )
    if knowledge:
        system_instruction += '\n\nApproved information:\n' + knowledge
    document_guide = '\n'.join(
        f'- {dict(Application.Category.choices).get(category, category)}: ' + '; '.join(items)
        for category, items in REQUIRED_DOCUMENTS.items()
    )
    revenue_guide = '\n'.join(
        f'- {meta["label"]}: ' + '; '.join(meta['documents'])
        for meta in SERVICE_CATALOG.values()
    )
    system_instruction += ('\n\nRequired documents by category (use these exact lists when asked what to upload):\n'
                           + document_guide
                           + '\n\nRequired documents by revenue service:\n' + revenue_guide)
    payload = {
        'system_instruction': {'parts': [{'text': system_instruction}]},
        'contents': [{'role': 'user', 'parts': [{'text': question}]}],
        'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 512},
    }
    timeout = max(1, float(getattr(settings, 'GEMINI_TIMEOUT', 5)))
    deadline = time.monotonic() + timeout
    for model in models:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        url = (f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
               f'?key={urllib.parse.quote(api_key)}')
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=remaining) as response:
                body = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            # Retrying overloaded or rate-limited models only adds latency.
            if exc.code in (429, 503):
                break
            continue
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            # Try another model only while the shared response-time budget remains.
            continue
        try:
            text = body['candidates'][0]['content']['parts'][0]['text'].strip()
        except (KeyError, IndexError, AttributeError, TypeError):
            continue
        if text:
            return text
    return None


def assistant_answer(question):
    """Prefer high-confidence approved FAQs, then use Gemini for open questions."""
    from .models import AssistantFAQ
    entries = list(AssistantFAQ.objects.filter(active=True))
    suggestions = [entry.question for entry in entries[:5]]

    lowered = (question or '').lower()
    query_tokens = set(_assistant_tokens(question))
    scored = []
    for entry in entries:
        entry_tokens = set(_assistant_tokens(f'{entry.question} {entry.keywords}'))
        phrases = [p.strip() for p in entry.keywords.lower().split(',') if p.strip()]
        score = len(query_tokens & entry_tokens) * 2
        score += sum(3 for phrase in phrases if phrase and phrase in lowered)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1].question))

    # Exact/strong FAQ matches are already approved and avoid waiting on Gemini.
    if scored and scored[0][0] >= 6:
        best = scored[0][1]
        return {
            'matched': True,
            'topic': best.topic or 'General',
            'source': 'faq',
            'answer': (f'{best.answer}\n\nThis is guidance only — an authorised officer makes the final decision on every application.'),
            'suggestions': [entry.question for _, entry in scored[:4]],
        }

    ai_text = _gemini_answer(question, entries)
    if ai_text:
        return {
            'matched': True, 'topic': 'AI Assistant', 'source': 'gemini',
            'answer': (f'{ai_text}\n\nThis is guidance only — an authorised officer makes the final decision '
                       'on every application.'),
            'suggestions': suggestions,
        }

    if not scored:
        return {
            'matched': False, 'topic': '', 'source': 'faq',
            'answer': ('I can only answer from the approved JanSutra AI information, and I could not match that question. '
                       'Please try one of the suggested questions below, or visit your nearest district office.'),
            'suggestions': [entry.question for entry in entries[:5]],
        }
    best_score, best = scored[0]
    suggestions = [entry.question for _, entry in scored[:4]] or [entry.question for entry in entries[:4]]
    if best_score < 3:
        return {
            'matched': False, 'topic': '', 'source': 'faq', 'answer': (
                'I am not fully sure about that. Based on approved information I can help with the questions listed below — '
                'pick one, or contact your district office for anything specific to your case.'),
            'suggestions': suggestions,
        }
    return {
        'matched': True,
        'topic': best.topic or 'General',
        'source': 'faq',
        'answer': (f'{best.answer}\n\nThis is guidance only — an authorised officer makes the final decision on every application.'),
        'suggestions': suggestions,
    }
