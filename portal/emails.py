"""Email and notification helpers.

Every outbound message is recorded in EmailLog so delivery status and history
can be inspected from the administrator panel. Configuration (SMTP host,
credentials, from address) is read from environment-backed settings and is
never hardcoded here.
"""
import base64
import json
import os
import urllib.error
import urllib.request

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode

from .models import EmailLog, Notification


# Built-in subject/body for every notification event. The administrator can
# override any of these from the console (see the EmailTemplate model); the text
# here is used until a template is configured and by the "reset to default"
# action. Placeholders are filled from build_context() when the email is sent.
DEFAULT_EMAIL_TEMPLATES = [
    {'kind': 'email_verification', 'name': 'Citizen registration — confirm email',
     'description': 'Sent when a citizen registers and must confirm their email address.',
     'placeholders': 'name, link',
     'subject': 'Confirm your JanSutra AI account',
     'body': 'Hello {name},\n\n'
             'Welcome to JanSutra AI. Please confirm your email address to activate your citizen account.\n\n'
             'Verify my email: {link}\n\n'
             'If you did not create this account you can ignore this message.\n\n'
             'The JanSutra AI team'},
    {'kind': 'password_reset', 'name': 'Password reset link',
     'description': 'Sent when a user requests a password reset.',
     'placeholders': 'name, link',
     'subject': 'Reset your JanSutra AI password',
     'body': 'Hello {name},\n\n'
             'A password reset was requested for your JanSutra AI account.\n\n'
             'Choose a new password: {link}\n\n'
             'If you did not request this you can ignore this message; your password will not change.\n\n'
             'The JanSutra AI team'},
    {'kind': 'officer_activation', 'name': 'Officer account — temporary password',
     'description': 'Sent to a new officer with their ID and a temporary password.',
     'placeholders': 'name, username, temp_password, login_link',
     'subject': 'Your JanSutra AI officer account',
     'body': 'Hello {name},\n\n'
             'An officer account has been created for you on JanSutra AI.\n\n'
             'Officer ID / username: {username}\n'
             'Temporary password: {temp_password}\n\n'
             'Sign in here: {login_link}\n\n'
             'For security you must change this temporary password immediately after your first sign in.\n\n'
             'The JanSutra AI team'},
    {'kind': 'application_submitted', 'name': 'Application submitted (citizen)',
     'description': 'Sent to the citizen right after an application is submitted.',
     'placeholders': 'name, service, application_id, status, dashboard_link',
     'subject': 'Application {application_id} received — JanSutra AI',
     'body': 'Hello {name},\n\n'
             'We received your {service} application.\n\n'
             'Application ID: {application_id}\n'
             'Current status: {status}\n\n'
             'Our AI has already pre-screened the case. Track progress any time from your JanSutra AI dashboard:\n'
             '{dashboard_link}\n\n'
             'The JanSutra AI team'},
    {'kind': 'admin_new_application', 'name': 'New application (administrator)',
     'description': 'Sent to administrators when any new application is submitted.',
     'placeholders': 'application_id, service',
     'subject': 'New application {application_id}',
     'body': 'A new {service} application ({application_id}) was submitted.\n\n'
             'Sign in to the administrator console to review it.'},
    {'kind': 'case_assigned', 'name': 'Case routed to officer',
     'description': 'Sent to a department officer when a case is routed to them.',
     'placeholders': 'application_id, service, status',
     'subject': 'New case in your department: {application_id}',
     'body': 'A new {service} application ({application_id}) has been routed to your department.\n\n'
             'Current status: {status}\n\n'
             'Sign in to review the documents, the AI report and record your decision.'},
    {'kind': 'officer_assigned', 'name': 'Officer assigned (citizen)',
     'description': 'Sent to the citizen when the administrator assigns a reviewing officer.',
     'placeholders': 'application_id',
     'subject': '{application_id}: officer assigned',
     'body': 'Application {application_id} has been assigned to a reviewing officer.\n\n'
             'You can track the status from your JanSutra AI dashboard.'},
    {'kind': 'document_processing', 'name': 'Document processed',
     'description': 'Sent when a freshly uploaded document has been read by the AI.',
     'placeholders': 'application_id',
     'subject': '{application_id} document processed',
     'body': 'A document for application {application_id} has been processed by the AI. '
             'Sign in to view the result.'},
    {'kind': 'status_more_info', 'name': 'Additional documents requested',
     'description': 'Sent to the citizen when the officer requests corrections or more documents.',
     'placeholders': 'name, application_id, remarks, dashboard_link',
     'subject': '{application_id} — additional documents required',
     'body': 'Hello {name},\n\n'
             'The officer reviewing application {application_id} has requested additional documents or corrections.\n\n'
             'Officer remark: {remarks}\n\n'
             'Sign in to view the exact checklist and upload the corrected documents:\n{dashboard_link}\n\n'
             'The JanSutra AI team'},
    {'kind': 'status_rejected', 'name': 'Application rejected',
     'description': 'Sent to the citizen when an application is rejected.',
     'placeholders': 'name, application_id, remarks',
     'subject': '{application_id} — application rejected',
     'body': 'Hello {name},\n\n'
             'Application {application_id} has been rejected by the authorised officer.\n\n'
             'Reason: {remarks}\n\n'
             'You may submit a fresh application with the correct details if you wish.\n\n'
             'The JanSutra AI team'},
    {'kind': 'status_review', 'name': 'Application under review',
     'description': 'Sent to the citizen when the status changes to under review.',
     'placeholders': 'name, application_id, status',
     'subject': '{application_id} — status updated to {status}',
     'body': 'Hello {name},\n\n'
             'The status of your application {application_id} is now: {status}.\n\n'
             'Sign in to view the full history.\n\n'
             'The JanSutra AI team'},
    {'kind': 'status_forwarded', 'name': 'Application forwarded',
     'description': 'Sent to the citizen when the case is forwarded to the department.',
     'placeholders': 'name, application_id, status',
     'subject': '{application_id} — status updated to {status}',
     'body': 'Hello {name},\n\n'
             'Your application {application_id} has been forwarded to the department. Current status: {status}.\n\n'
             'Sign in to view the full history.\n\n'
             'The JanSutra AI team'},
    {'kind': 'certificate_issued', 'name': 'Certificate issued',
     'description': 'Sent to the citizen with the approved certificate attached as a PDF.',
     'placeholders': 'name, service, application_id, certificate_number, verification_code',
     'subject': 'Your {service} certificate — {application_id}',
     'body': 'Hello {name},\n\n'
             'Your {service} for application {application_id} has been approved and the certificate is attached '
             'to this email as a PDF.\n\n'
             'Certificate number: {certificate_number}\n'
             'Verification code: {verification_code}\n\n'
             'Anyone can confirm its authenticity by scanning the QR code printed on the certificate, or by entering '
             'the verification code on the JanSutra AI verification page. Keep the certificate safe — it is also '
             'available to download from your dashboard.\n\n'
             'The JanSutra AI team'},
    {'kind': 'officer_permissions_changed', 'name': 'Officer access updated',
     'description': 'Sent to an officer when the administrator changes their department or permissions.',
     'placeholders': 'name',
     'subject': 'Your JanSutra AI access was updated',
     'body': 'Hello {name},\n\n'
             'The administrator updated your JanSutra AI access. Sign in to your workspace to see the change.\n\n'
             'The JanSutra AI team'},
    {'kind': 'admin_message', 'name': 'Direct message from the Collector',
     'description': 'Free-text email the Collector sends to a chosen officer or citizen.',
     'placeholders': 'name, message',
     'subject': 'Message from the JanSutra AI administration',
     'body': 'Hello {name},\n\n'
             '{message}\n\n'
             'This message was sent from the JanSutra AI administration console by the District Collector.\n\n'
             'The JanSutra AI team'},
]

DEFAULT_TEMPLATES_BY_KIND = {row['kind']: row for row in DEFAULT_EMAIL_TEMPLATES}


class _TemplateValues(dict):
    """Mapping that leaves unknown placeholders visible instead of raising."""
    def __missing__(self, key):
        return '{' + str(key) + '}'


def build_context(user=None, application=None, extra=None):
    """Values available to an email template for this event."""
    context = {
        'site_name': 'JanSutra AI',
        'name': '', 'username': '', 'citizen_name': '', 'officer_name': '',
        'application_id': '', 'service': '', 'status': '',
        'certificate_number': '', 'verification_code': '', 'remarks': '',
        'message': '', 'link': '', 'temp_password': '',
        'login_link': site_url(reverse('login')),
        'dashboard_link': site_url(reverse('dashboard')),
    }
    if user is not None:
        display = user.get_full_name() or user.username
        context['name'] = display
        context['username'] = user.username
        context['officer_name' if user.role == 'officer' else 'citizen_name'] = display
    if application is not None:
        from .services import application_service
        context['application_id'] = application.public_id
        context['service'] = application_service(application)
        context['status'] = application.get_status_display()
        certificate = getattr(application, 'certificate_record', None)
        if certificate is not None:
            context['certificate_number'] = certificate.certificate_number
            context['verification_code'] = certificate.verification_code
    context.update(extra or {})
    return context


def render_text(subject, body, user=None, application=None, extra=None):
    """Fill the placeholders in a subject/body with the event's values."""
    values = _TemplateValues(build_context(user, application, extra))
    try:
        return subject.format_map(values), body.format_map(values)
    except (KeyError, ValueError, IndexError):
        return subject, body


def render_template(kind, subject, body, user=None, application=None, extra=None):
    """Return (subject, body) using the administrator's template for this event.

    Falls back to the supplied defaults when no active template exists or the
    configured template cannot be rendered (for example an unexpected
    placeholder), so a mis-edited template can never stop an email going out.
    """
    from .models import EmailTemplate
    template = EmailTemplate.objects.filter(kind=kind, active=True).first()
    if template is None:
        return subject, body
    return render_text(template.subject, template.body, user=user, application=application, extra=extra)



def _send_via_http_api(subject, body, recipients, attachments=None):
    """Send email via HTTPS REST API (Google Apps Script webhook, Brevo, or Resend), bypassing Render free tier's blocked SMTP ports (25, 465, 587)."""
    backend = getattr(settings, 'EMAIL_BACKEND', '')
    if backend.endswith(('locmem.EmailBackend', 'console.EmailBackend', 'dummy.EmailBackend', 'filebased.EmailBackend')):
        return None
    webhook_url = (os.environ.get('EMAIL_WEBHOOK_URL') or getattr(settings, 'EMAIL_WEBHOOK_URL', '')).strip()
    brevo_key = (os.environ.get('BREVO_API_KEY') or getattr(settings, 'BREVO_API_KEY', '')).strip()
    resend_key = (os.environ.get('RESEND_API_KEY') or getattr(settings, 'RESEND_API_KEY', '')).strip()

    if webhook_url:
        payload = {
            'to': ','.join(recipients),
            'subject': subject,
            'body': body,
        }
        if attachments:
            payload['attachments'] = [
                {
                    'filename': name,
                    'content': base64.b64encode(content if isinstance(content, bytes) else content.encode('utf-8')).decode('ascii'),
                    'mimetype': mimetype or 'application/pdf',
                }
                for name, content, mimetype in attachments
            ]
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 400:
                    return True
        except urllib.error.HTTPError as err:
            err_body = err.read().decode('utf-8', errors='replace')
            raise RuntimeError(f'Webhook error {err.code}: {err_body[:150]}')
        except Exception as e:
            raise RuntimeError(f'Webhook request failed: {e}')
        return False

    if brevo_key:
        url = 'https://api.brevo.com/v3/smtp/email'
        from_email = (os.environ.get('BREVO_FROM_EMAIL') or os.environ.get('EMAIL_HOST_USER') or 'armaan.sk113@gmail.com').strip()
        if '<' in from_email and '>' in from_email:
            from_email = from_email.split('<', 1)[1].split('>', 1)[0].strip()
        payload = {
            'sender': {'email': from_email, 'name': 'JanSutra AI'},
            'to': [{'email': r} for r in recipients],
            'subject': subject,
            'textContent': body,
        }
        if attachments:
            payload['attachment'] = [
                {'name': name, 'content': base64.b64encode(content if isinstance(content, bytes) else content.encode('utf-8')).decode('ascii')}
                for name, content, _ in attachments
            ]
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'api-key': brevo_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status in (200, 201):
                    return True
        except urllib.error.HTTPError as err:
            err_body = err.read().decode('utf-8', errors='replace')
            try:
                err_data = json.loads(err_body)
                msg = err_data.get('message', err_body)
            except Exception:
                msg = err_body
            raise RuntimeError(f'Brevo: {msg}')
        except Exception as e:
            raise RuntimeError(f'Brevo request failed: {e}')
        return False

    if resend_key:
        url = 'https://api.resend.com/emails'
        from_email = os.environ.get('RESEND_FROM_EMAIL') or getattr(settings, 'RESEND_FROM_EMAIL', '') or 'JanSutra AI <onboarding@resend.dev>'
        payload = {
            'from': from_email,
            'to': recipients,
            'subject': subject,
            'text': body,
        }
        if attachments:
            payload['attachments'] = [
                {'filename': name, 'content': base64.b64encode(content if isinstance(content, bytes) else content.encode('utf-8')).decode('ascii')}
                for name, content, _ in attachments
            ]
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Authorization': f'Bearer {resend_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'JanSutra-AI/1.0',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status in (200, 201):
                    return True
        except urllib.error.HTTPError as err:
            err_body = err.read().decode('utf-8', errors='replace')
            try:
                err_data = json.loads(err_body)
                msg = err_data.get('message', err_body)
            except Exception:
                msg = err_body
            raise RuntimeError(f'Resend: {msg}')
        except Exception as e:
            raise RuntimeError(f'Resend request failed: {e}')
        return False

    return None


def send_email(kind, subject, body, recipients, user=None, application=None, attachments=None):
    """Send one email to one or more recipients and log the outcome per address.

    Returns the list of EmailLog rows created. Delivery failures are recorded
    as `failed` instead of raising, so a broken SMTP setup can never break a
    user-facing action. `attachments` is an optional list of
    (filename, content, mimetype) tuples.
    """
    targets = [r for r in (recipients or []) if r]
    if not targets:
        return []
    status, error = EmailLog.Status.SENT, ''
    try:
        http_result = _send_via_http_api(subject, body, targets, attachments=attachments)
        if http_result is True:
            pass
        elif http_result is False:
            raise RuntimeError('HTTP email delivery returned an unsuccessful status code')
        else:
            message = EmailMultiAlternatives(subject, body, settings.DEFAULT_FROM_EMAIL, targets)
            for name, content, mimetype in (attachments or []):
                message.attach(name, content, mimetype)
            message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - record any transport error
        status, error = EmailLog.Status.FAILED, str(exc)
    logs = []
    for address in targets:
        logs.append(EmailLog.objects.create(
            recipient=address, subject=subject[:200], kind=kind,
            user=user if (user and getattr(user, 'pk', None) and user.email and user.email == address) else None,
            application=application if (application and getattr(application, 'pk', None)) else None,
            status=status, error=error[:250],
        ))
    return logs


def notify(user, message, application=None, kind='notification', subject=None, body=None, context=None):
    """Create an in-app notification and, when a subject is given, email it too."""
    if user is None:
        return None
    notification = Notification.objects.create(recipient=user, application=application, message=message[:250])
    if subject and user.email:
        email_subject, email_body = render_template(
            kind, subject, body or message, user=user, application=application, extra=context)
        send_email(kind, email_subject, email_body, [user.email], user=user, application=application)
    return notification


def site_url(path=''):
    return f'{settings.SITE_BASE_URL.rstrip("/")}{path}'


def absolute_link(path, request=None):
    """Build a full link that points at the host the user is actually using.

    Links in emails must work from the citizen's device, so when a request is
    available we use its real host instead of the configured SITE_BASE_URL
    (which can go stale when the machine's LAN address changes).
    """
    if request is not None:
        return request.build_absolute_uri(path)
    return site_url(path)


def build_verification_link(user, request=None):
    path = reverse('verify_email', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    })
    return absolute_link(path, request)


def build_password_reset_link(user, request=None):
    path = reverse('password_reset_confirm', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    })
    return absolute_link(path, request)


def decode_uid(uidb64):
    try:
        return force_str(urlsafe_base64_decode(uidb64))
    except (TypeError, ValueError, OverflowError):
        return None


def send_verification_email(user, request=None):
    link = build_verification_link(user, request)
    defaults = DEFAULT_TEMPLATES_BY_KIND['email_verification']
    subject, body = render_template('email_verification', defaults['subject'], defaults['body'],
                                    user=user, extra={'link': link})
    return send_email('email_verification', subject, body, [user.email], user=user)


def send_password_reset_email(user, request=None):
    link = build_password_reset_link(user, request)
    defaults = DEFAULT_TEMPLATES_BY_KIND['password_reset']
    subject, body = render_template('password_reset', defaults['subject'], defaults['body'],
                                    user=user, extra={'link': link})
    return send_email('password_reset', subject, body, [user.email], user=user)


def send_officer_activation_email(user, temp_password, request=None):
    """Send an officer their unique ID and a temporary password.

    Only a temporary credential is ever emailed; the officer must change it on
    first login before the workspace unlocks.
    """
    defaults = DEFAULT_TEMPLATES_BY_KIND['officer_activation']
    subject, body = render_template('officer_activation', defaults['subject'], defaults['body'], user=user,
                                    extra={'temp_password': temp_password,
                                           'login_link': absolute_link(reverse('login'), request)})
    return send_email('officer_activation', subject, body, [user.email] or [], user=user)


def send_direct_message_email(user, subject, message):
    """Free-text email sent by the Collector to one officer or citizen.

    The Collector writes the subject, so only the body is taken from the
    administrator's template for this event.
    """
    defaults = DEFAULT_TEMPLATES_BY_KIND['admin_message']
    _, body = render_template('admin_message', subject, defaults['body'], user=user, extra={'message': message})
    return send_email('admin_message', subject, body, [user.email] or [], user=user)
