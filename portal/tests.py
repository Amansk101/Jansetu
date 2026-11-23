from django.test import TestCase, override_settings
from django.urls import reverse
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
from django.core.files.uploadedfile import SimpleUploadedFile
from .emails import DEFAULT_TEMPLATES_BY_KIND, build_password_reset_link, render_template, send_password_reset_email
from .models import Application, AssistantFAQ, CompensationConfiguration, Department, EmailLog, EmailTemplate, Notification, Officer, User, Scheme
from .services import assess_eligibility, calculate_compensation, extract_candidate_fields, potential_duplicates, application_documents, application_service, document_check

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CoreWorkflowTests(TestCase):
    def setUp(self):
        self.citizen = User.objects.create_user(username='citizen', password='Testpass!234', role='citizen', email='citizen@example.test')
        self.other = User.objects.create_user(username='other', password='Testpass!234', role='citizen', email='other@example.test')
        self.officer = User.objects.create_user(username='officer', password='Testpass!234', role='officer', email='officer@example.test')
        self.app = Application.objects.create(citizen=self.citizen, category='welfare', description='A demonstration request', assigned_officer=self.officer)

    def test_citizen_can_submit_application(self):
        self.client.login(username='citizen', password='Testpass!234')
        response = self.client.post(reverse('new_application'), {'category':'revenue','description':'Please review this record','service_type':'Income certificate'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Application.objects.filter(citizen=self.citizen).count(), 2)

    def test_submission_requires_category_specific_field(self):
        self.client.login(username='citizen', password='Testpass!234')
        response = self.client.post(reverse('new_application'), {'category':'revenue','description':'Missing the service type'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Application.objects.filter(citizen=self.citizen).count(), 1)

    def test_citizen_cannot_view_another_citizens_case(self):
        self.client.login(username='other', password='Testpass!234')
        response = self.client.get(reverse('application_detail', args=[self.app.public_id]))
        self.assertEqual(response.status_code, 403)

    def test_officer_can_record_a_case_action(self):
        self.client.login(username='officer', password='Testpass!234')
        response = self.client.post(reverse('officer_action', args=[self.app.public_id]), {'action':'forward','remark':'Documents reviewed'})
        self.assertEqual(response.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'forwarded')
        self.assertTrue(self.app.history.exists())

    def test_eligibility_explains_missing_income(self):
        scheme = Scheme.objects.create(name='Test support', category='welfare', income_limit=100000)
        self.app.scheme = scheme
        self.app.save()
        result = assess_eligibility(self.app)
        self.assertEqual(result.outcome, 'More Information Required')
        self.assertTrue(any('income' in x.lower() for x in result.explanation))

    def test_compensation_formula_is_transparent_and_illustrative(self):
        config = CompensationConfiguration.objects.create(land_category='Demo land', base_rate=Decimal('100'), multiplier=Decimal('2'), additional_components=Decimal('50'), deductions=Decimal('10'))
        estimate = calculate_compensation(self.app, config, '3')
        self.assertEqual(estimate.estimated_amount, Decimal('640.00'))
        self.assertIn('formula', estimate.breakdown)

    def test_module_workspaces_render_for_signed_in_citizen(self):
        self.client.force_login(self.citizen)
        self.assertContains(self.client.get(reverse('home')), 'JanSutra AI')
        self.assertEqual(self.client.get(reverse('documents_hub')).status_code, 200)
        self.assertEqual(self.client.get(reverse('eligibility_hub')).status_code, 200)
        self.assertEqual(self.client.get(reverse('compensation_hub')).status_code, 200)

    def test_application_wizard_renders_the_review_step(self):
        self.client.force_login(self.citizen)
        response = self.client.get(reverse('new_application'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'confirmModal')
        self.assertContains(response, 'Review &amp; Submit')

    def test_admin_module_rejects_citizen(self):
        self.client.force_login(self.citizen)
        self.assertEqual(self.client.get(reverse('admin_module')).status_code, 403)

    def test_login_requires_the_selected_role_to_match(self):
        response = self.client.post(reverse('login'), {'action':'login','email':'officer@example.test','password':'Testpass!234','role':'admin'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_with_matching_role_opens_the_workspace(self):
        response = self.client.post(reverse('login'), {'action':'login','email':'officer@example.test','password':'Testpass!234','role':'officer'})
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(self.client.session['_auth_user_id'], str(self.officer.pk))

    def test_public_signup_always_creates_a_citizen(self):
        response = self.client.post(reverse('login') + '?mode=signup', {
            'action':'signup','name':'New Citizen',
            'email':'new@example.test','mobile':'9000000000','password1':'UniqueDemo!49382','password2':'UniqueDemo!49382','role':'admin',
        })
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(email='new@example.test')
        self.assertEqual(created.role, User.Role.CITIZEN)
        self.assertEqual(created.get_full_name(), 'New Citizen')

    def test_approval_requires_a_reason(self):
        self.client.login(username='officer', password='Testpass!234')
        response = self.client.post(reverse('officer_action', args=[self.app.public_id]), {'action':'approve','remark':''})
        self.assertEqual(response.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, Application.Status.SUBMITTED)

    def test_document_upload_updates_case_timeline_and_notice(self):
        self.client.login(username='citizen', password='Testpass!234')
        upload = SimpleUploadedFile('identity.png', b'not-a-real-image', content_type='image/png')
        response = self.client.post(reverse('upload_document', args=[self.app.public_id]), {'file':upload})
        self.assertEqual(response.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, Application.Status.VERIFICATION)
        self.assertEqual(list(self.app.history.values_list('status', flat=True)), ['processing', 'verification'])
        self.assertGreaterEqual(self.citizen.notifications.count(), 2)

    def test_labeled_ocr_fields_only_are_extracted(self):
        fields = extract_candidate_fields('Applicant Name: Asha Patil\nDocument Number: MH-123456\nRandom sentence without label')
        self.assertEqual(fields['applicant_name'], 'Asha Patil')
        self.assertEqual(fields['document_number'], 'MH-123456')
        self.assertNotIn('random_sentence', fields)

    def test_similar_open_application_is_flagged_for_review(self):
        duplicate = Application.objects.create(citizen=self.citizen, category=self.app.category, description='Another request')
        self.assertIn(duplicate, potential_duplicates(self.app))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AccountSecurityTests(TestCase):
    def test_signup_creates_a_ready_to_use_citizen_account(self):
        response = self.client.post(reverse('login') + '?mode=signup', {
            'action': 'signup', 'name': 'Verify Me',
            'email': 'verifyme@example.test', 'mobile': '9000000001',
            'password1': 'UniqueDemo!49382', 'password2': 'UniqueDemo!49382',
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email='verifyme@example.test')
        # Citizens can sign in straight away; no email verification step blocks them.
        self.assertTrue(user.email_verified)
        signed_in = self.client.post(reverse('login'), {'action': 'login', 'email': 'verifyme@example.test', 'password': 'UniqueDemo!49382', 'role': 'citizen'})
        self.assertRedirects(signed_in, reverse('dashboard'))

    def test_verified_citizen_can_sign_in_with_their_email(self):
        User.objects.create_user(username='byemail', password='Testpass!234', role='citizen',
                                 email='byemail@example.test', email_verified=True)
        response = self.client.post(reverse('login'), {'action': 'login', 'email': 'byemail@example.test',
                                                       'password': 'Testpass!234', 'role': 'citizen'})
        self.assertRedirects(response, reverse('dashboard'))

    def test_password_reset_request_records_email(self):
        user = User.objects.create_user(username='resetme', password='Testpass!234', role='citizen', email='reset@example.test')
        self.client.post(reverse('password_reset_request'), {'email': 'reset@example.test'})
        self.assertTrue(EmailLog.objects.filter(kind='password_reset', user=user).exists())
        reset = self.client.get(build_password_reset_link(user))
        self.assertEqual(reset.status_code, 200)

    def test_login_is_rate_limited_after_repeated_failures(self):
        User.objects.create_user(username='throttle', password='Testpass!234', role='citizen', email='throttle@example.test')
        for _ in range(5):
            self.client.post(reverse('login'), {'action': 'login', 'email': 'throttle@example.test', 'password': 'wrong', 'role': 'citizen'})
        response = self.client.post(reverse('login'), {'action': 'login', 'email': 'throttle@example.test', 'password': 'Testpass!234', 'role': 'citizen'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get('_auth_user_id'))

    def test_public_and_account_pages_render(self):
        verification_page = self.client.get('/account/verify/')
        self.assertEqual(verification_page.status_code, 200)
        self.assertNotContains(verification_page, 'Confirm your email')
        self.assertEqual(self.client.get(reverse('password_reset_request')).status_code, 200)
        self.assertEqual(self.client.get(reverse('password_reset_done')).status_code, 200)
        user = User.objects.create_user(username='render', password='Testpass!234', role='citizen')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('password_change')).status_code, 200)
        self.assertEqual(self.client.get(reverse('force_password_change')).status_code, 200)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class OfficerWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='collector', password='Testpass!234', role='admin')
        self.citizen = User.objects.create_user(username='wc', password='Testpass!234', role='citizen')
        self.case = Application.objects.create(citizen=self.citizen, category='welfare', description='Welfare case for officer workflow')

    def test_admin_creation_generates_temp_password_and_forces_change(self):
        self.client.login(username='collector', password='Testpass!234')
        response = self.client.post(reverse('manage_accounts'), {
            'action': 'create', 'username': '', 'first_name': 'Ravi', 'last_name': 'Naik',
            'email': 'ravi.officer@example.test', 'password': '',
        })
        self.assertEqual(response.status_code, 302)
        officer = User.objects.get(email='ravi.officer@example.test')
        self.assertEqual(officer.role, User.Role.OFFICER)
        self.assertTrue(officer.must_change_password)
        self.assertTrue(EmailLog.objects.filter(kind='officer_activation', user=officer).exists())
        self.client.logout()
        self.client.force_login(officer)
        guarded = self.client.get(reverse('dashboard'))
        self.assertEqual(guarded.status_code, 302)
        self.assertIn(reverse('force_password_change'), guarded.url)

    def test_officer_is_limited_to_granted_modules(self):
        officer = User.objects.create_user(username='limited', password='Testpass!234', role='officer')
        Officer.objects.create(user=officer, allowed_modules=['eligibility'])
        self.client.force_login(officer)
        self.assertEqual(self.client.get(reverse('documents_hub')).status_code, 403)
        self.assertEqual(self.client.get(reverse('compensation_hub')).status_code, 403)
        self.assertEqual(self.client.get(reverse('eligibility_hub')).status_code, 200)

    def test_officer_category_restriction_hides_unauthorised_case(self):
        officer = User.objects.create_user(username='revonly', password='Testpass!234', role='officer')
        Officer.objects.create(user=officer, allowed_categories=['revenue'])
        self.case.assigned_officer = officer
        self.case.save()
        self.client.force_login(officer)
        self.assertEqual(self.client.get(reverse('application_detail', args=[self.case.public_id])).status_code, 403)

    def test_only_admin_can_open_officer_management(self):
        officer = User.objects.create_user(username='plain', password='Testpass!234', role='officer')
        self.client.force_login(officer)
        self.assertEqual(self.client.get(reverse('manage_accounts')).status_code, 403)
        self.assertEqual(self.client.get(reverse('email_log')).status_code, 403)

    def test_admin_management_and_log_pages_render(self):
        self.client.login(username='collector', password='Testpass!234')
        self.assertEqual(self.client.get(reverse('manage_accounts')).status_code, 200)
        self.assertEqual(self.client.get(reverse('email_log')).status_code, 200)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', GEMINI_API_KEY='')
class AssistantAndMessagingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='collector2', password='Testpass!234', role='admin')
        self.citizen = User.objects.create_user(username='asker', password='Testpass!234', role='citizen', email='asker@example.test')
        self.officer = User.objects.create_user(username='field', password='Testpass!234', role='officer', email='field@example.test')
        Officer.objects.create(user=self.officer)
        AssistantFAQ.objects.update_or_create(
            question='How can I track my application status?',
            defaults={'topic': 'Tracking', 'keywords': 'status, track, progress',
                      'answer': 'Open Application history to see the live status of every case.'})

    def test_assistant_answers_from_the_approved_faqs(self):
        self.client.force_login(self.citizen)
        with override_settings(GEMINI_API_KEY='test-key'):
            with patch('urllib.request.urlopen') as gemini_request:
                response = self.client.post(reverse('assistant'), {'question': 'how do I track my application status'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['matched'])
        self.assertIn('Application history', data['answer'])
        gemini_request.assert_not_called()

    def test_assistant_stops_retrying_after_gemini_overload(self):
        from .services import assistant_answer
        error = HTTPError('https://example.test', 503, 'unavailable', None, BytesIO(b''))
        with override_settings(
            GEMINI_API_KEY='test-key',
            GEMINI_MODEL='gemini-primary',
            GEMINI_FALLBACK_MODELS=['gemini-fallback-1', 'gemini-fallback-2'],
            GEMINI_TIMEOUT=5,
        ):
            with patch('urllib.request.urlopen', side_effect=error) as request:
                result = assistant_answer('please explain a purple lantern')
        self.assertEqual(result['source'], 'faq')
        self.assertIn('guidance only', result['answer'])
        request.assert_called_once()

    def test_assistant_offers_topics_when_it_cannot_answer(self):
        self.client.force_login(self.citizen)
        data = self.client.post(reverse('assistant'), {'question': 'zzz qqq wubble'}).json()
        self.assertFalse(data['matched'])
        self.assertTrue(data['suggestions'])

    def test_assistant_page_renders_for_citizen(self):
        self.client.force_login(self.citizen)
        self.assertEqual(self.client.get(reverse('assistant')).status_code, 200)

    def test_only_admin_can_open_the_send_email_page(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse('send_direct_email')).status_code, 403)

    def test_admin_can_email_an_officer_from_the_app(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('send_direct_email'), {
            'recipient': str(self.officer.pk), 'subject': 'Case review', 'message': 'Please prioritise the pending case.'})
        self.assertEqual(response.status_code, 302)
        log = EmailLog.objects.get(kind='admin_message')
        self.assertEqual(log.recipient, 'field@example.test')
        self.assertTrue(Notification.objects.filter(recipient=self.officer).exists())

    def test_changing_officer_permissions_emails_the_officer(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('manage_accounts'), {
            'action': 'update_officer', 'id': self.officer.pk, 'department': '', 'designation': 'Review Officer',
            'allowed_modules': ['eligibility'], 'allowed_categories': ['revenue']})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EmailLog.objects.filter(kind='officer_permissions_changed', user=self.officer).exists())


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DepartmentRoutingTests(TestCase):
    def setUp(self):
        # Neutralise the seeded department mapping so this test controls routing.
        Department.objects.update(categories=[])
        self.citizen = User.objects.create_user(username='routed', password='Testpass!234', role='citizen')
        self.welfare_dept = Department.objects.create(name='Welfare Desk', code='WELX', categories=['welfare'])
        self.revenue_dept = Department.objects.create(name='Revenue Desk', code='REVX', categories=['revenue', 'land'])
        self.welfare_officer = User.objects.create_user(username='welfare-officer', password='Testpass!234', role='officer')
        Officer.objects.create(user=self.welfare_officer, department=self.welfare_dept)

    def test_new_application_is_routed_to_the_matching_department(self):
        self.client.force_login(self.citizen)
        self.client.post(reverse('new_application'), {
            'category': 'revenue', 'description': 'Please review this record', 'service_type': 'Income certificate'})
        application = Application.objects.get(citizen=self.citizen)
        self.assertEqual(application.department, self.revenue_dept)

    def test_officer_only_sees_cases_from_their_own_department(self):
        mine = Application.objects.create(citizen=self.citizen, category='welfare', description='Welfare case', department=self.welfare_dept)
        other = Application.objects.create(citizen=self.citizen, category='revenue', description='Revenue case', department=self.revenue_dept)
        self.client.force_login(self.welfare_officer)
        self.assertEqual(self.client.get(reverse('application_detail', args=[mine.public_id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('application_detail', args=[other.public_id])).status_code, 403)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ServiceCertificateTests(TestCase):
    def setUp(self):
        self.citizen = User.objects.create_user(username='cert-citizen', password='Testpass!234', role='citizen', email='cert@example.test')
        self.officer = User.objects.create_user(username='cert-officer', password='Testpass!234', role='officer')
        self.app = Application.objects.create(
            citizen=self.citizen, category='revenue', description='Income certificate request',
            form_data={'service_type': 'income_certificate'}, assigned_officer=self.officer)

    def test_income_certificate_has_its_own_document_list(self):
        self.assertEqual(application_service(self.app), 'Income Certificate')
        self.assertIn('Income proof (salary slips, ITR or self-declaration of annual income)', application_documents(self.app))

    def test_document_check_flags_missing_documents(self):
        result = document_check(self.app)
        self.assertFalse(result['ready'])
        self.assertTrue(result['missing'])

    def test_documents_uploaded_with_the_form_are_attached_to_the_case(self):
        self.client.force_login(self.citizen)
        response = self.client.post(reverse('new_application'), {
            'category': 'revenue', 'description': 'Income certificate for a scholarship',
            'service_type': 'income_certificate', 'service_slug': 'income-certificate',
            'docfile_0': SimpleUploadedFile('aadhaar.png', b'bytes', content_type='image/png'),
            'doclabel_0': 'Identity proof (Aadhaar / Voter ID / Passport)',
            'docfile_1': SimpleUploadedFile('address.png', b'bytes', content_type='image/png'),
            'doclabel_1': 'Address proof (ration card or electricity bill)',
        })
        self.assertEqual(response.status_code, 302)
        app = Application.objects.filter(citizen=self.citizen).exclude(pk=self.app.pk).latest('created_at')
        self.assertEqual(app.documents.count(), 2)
        self.assertEqual(app.documents.first().doc_type, 'Identity proof (Aadhaar / Voter ID / Passport)')

    def test_application_needs_at_least_two_required_documents(self):
        self.client.force_login(self.citizen)
        response = self.client.post(reverse('new_application'), {
            'category': 'revenue', 'description': 'Income certificate with only one document',
            'service_type': 'income_certificate', 'service_slug': 'income-certificate',
            'docfile_0': SimpleUploadedFile('aadhaar.png', b'bytes', content_type='image/png'),
            'doclabel_0': 'Identity proof (Aadhaar / Voter ID / Passport)',
        })
        # The submission is rejected: fewer than two required documents were attached.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.filter(citizen=self.citizen).exclude(pk=self.app.pk).exists())

    def test_officer_cannot_upload_documents(self):
        self.client.force_login(self.officer)
        upload = SimpleUploadedFile('extra.png', b'bytes', content_type='image/png')
        response = self.client.post(reverse('upload_document', args=[self.app.public_id]), {'file': upload})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.app.documents.count(), 0)

    def test_approval_emails_the_certificate_to_the_citizen(self):
        self.client.force_login(self.officer)
        response = self.client.post(reverse('officer_action', args=[self.app.public_id]), {'action': 'approve', 'remark': 'Verified against records'})
        self.assertEqual(response.status_code, 302)
        self.app.refresh_from_db()
        # Approval immediately issues the certificate, so the case advances to
        # Certificate Generated (PRD status 12).
        self.assertEqual(self.app.status, Application.Status.CERTIFICATE_GENERATED)
        certificate = self.app.certificate_record
        self.assertTrue(certificate.pdf)
        self.assertTrue(certificate.verification_code)
        self.assertTrue(EmailLog.objects.filter(kind='certificate_issued', application=self.app).exists())

    def test_certificate_is_only_available_once_approved(self):
        self.client.force_login(self.citizen)
        self.assertEqual(self.client.get(reverse('certificate', args=[self.app.public_id])).status_code, 302)
        self.app.status = Application.Status.APPROVED
        self.app.save(update_fields=['status'])
        response = self.client.get(reverse('certificate', args=[self.app.public_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailTemplateTests(TestCase):
    """Administrator-editable notification email templates (PRD admin console)."""

    def setUp(self):
        self.admin = User.objects.create_user(username='collector3', password='Testpass!234', role='admin', email='collector3@example.test')
        self.citizen = User.objects.create_user(username='et-citizen', password='Testpass!234', role='citizen', email='et@example.test')

    def test_default_templates_are_seeded(self):
        self.assertEqual(EmailTemplate.objects.count(), len(DEFAULT_TEMPLATES_BY_KIND))
        self.assertTrue(EmailTemplate.objects.filter(kind='certificate_issued').exists())

    def test_citizen_cannot_open_the_email_template_console(self):
        self.client.force_login(self.citizen)
        self.assertEqual(self.client.get(reverse('manage_email_templates')).status_code, 403)

    def test_admin_sees_the_console_with_a_preview(self):
        self.client.force_login(self.admin)
        response = self.client.get(f'{reverse("manage_email_templates")}?edit={EmailTemplate.objects.get(kind="email_verification").pk}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Email notification templates')
        self.assertContains(response, 'Live preview')

    def test_editing_a_template_changes_the_email_that_is_sent(self):
        self.client.force_login(self.admin)
        row = EmailTemplate.objects.get(kind='password_reset')
        response = self.client.post(reverse('manage_email_templates'), {
            'action': 'save', 'id': row.pk, 'name': row.name, 'description': row.description,
            'placeholders': row.placeholders, 'subject': 'Custom subject for {name}',
            'body': 'Hi {name}, please reset using {link}.', 'active': 'on'})
        self.assertEqual(response.status_code, 302)
        send_password_reset_email(self.citizen)
        log = EmailLog.objects.filter(kind='password_reset', recipient=self.citizen.email).latest('created_at')
        self.assertEqual(log.subject, 'Custom subject for et-citizen')
        _, body = render_template('password_reset', '', '', user=self.citizen, extra={'link': 'LINK'})
        self.assertIn('please reset using LINK', body)

    def test_disabled_template_falls_back_to_the_built_in_text(self):
        row = EmailTemplate.objects.get(kind='password_reset')
        row.active = False
        row.save(update_fields=['active'])
        subject, body = render_template('password_reset', 'fallback subject', 'fallback body',
                                        user=self.citizen, extra={'link': 'LINK'})
        self.assertEqual(subject, 'fallback subject')
        self.assertEqual(body, 'fallback body')

    def test_reset_restores_the_built_in_text(self):
        self.client.force_login(self.admin)
        row = EmailTemplate.objects.get(kind='password_reset')
        row.subject, row.body = 'changed', 'changed'
        row.save()
        response = self.client.post(reverse('manage_email_templates'), {'action': 'reset', 'id': row.pk})
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.subject, DEFAULT_TEMPLATES_BY_KIND['password_reset']['subject'])
