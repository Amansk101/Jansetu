from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from portal.models import (Application, ApplicationStatusHistory, AuditLog, CompensationConfiguration,
                           Department, EligibilityAssessment, EmailLog, Notification, Officer, Scheme, User)


class Command(BaseCommand):
    help = 'Create or refresh synthetic Jan Sutra demonstration accounts, departments and cases.'

    def handle(self, *args, **opts):
        admin = User.objects.filter(username='admin').first()
        if admin is None:
            # Reuse any existing administrator (e.g. an older demo account) so we never
            # create a second Collector; then standardise its username to 'admin'.
            admin = User.objects.filter(role=User.Role.ADMIN).order_by('id').first()
            if admin is not None:
                admin.username = 'admin'
                admin.save(update_fields=['username'])
        if admin is None:
            admin = User(username='admin')
        admin.role = User.Role.ADMIN; admin.is_staff = True; admin.is_superuser = True
        admin.email_verified = True; admin.must_change_password = False
        if not admin.email:
            admin.email = 'admin@example.test'
        admin.email = settings.COLLECTOR_EMAIL or admin.email
        admin.set_password('admin123'); admin.save()

        departments = {}
        for name, code, desc in [
            ('Revenue Administration', 'REV', 'Land records, revenue services and compensation.'),
            ('Disaster Management Cell', 'DMC', 'Disaster relief applications and loss assessment.'),
            ('Welfare & Schemes Desk', 'WEL', 'Welfare scheme screening and verification.'),
        ]:
            department, _ = Department.objects.get_or_create(name=name, defaults={'code': code, 'description': desc})
            departments[code] = department

        officers = []
        officer_designations = ['Deputy Collector', 'Review Officer']
        for i in range(1, 3):
            u, _ = User.objects.get_or_create(username=f'demo-officer{i}', defaults={'role': 'officer', 'first_name': f'Officer {i}', 'email': f'officer{i}@example.test', 'district': 'Demo District'})
            u.role = 'officer'; u.email_verified = True; u.must_change_password = False
            u.set_password('DemoOfficer!2026'); u.save()
            record, _ = Officer.objects.get_or_create(user=u)
            record.department = departments['REV' if i == 1 else 'DMC']
            record.designation = officer_designations[i - 1]
            record.allowed_modules = []      # empty = unrestricted
            record.allowed_categories = []   # empty = all categories
            record.save()
            officers.append(u)

        scheme, _ = Scheme.objects.get_or_create(name='Community Support Grant', defaults={'category': 'welfare', 'income_limit': Decimal('250000'), 'description': 'Synthetic demonstration scheme.', 'required_documents': 'Identity proof, Address proof'})
        CompensationConfiguration.objects.get_or_create(land_category='Demonstration agricultural land', defaults={'base_rate': Decimal('1500'), 'multiplier': Decimal('1.000'), 'additional_components': Decimal('10000'), 'deductions': Decimal('0')})

        statuses = ['submitted', 'processing', 'verification', 'review', 'more_info', 'forwarded', 'approved', 'rejected']
        categories = ['welfare', 'disaster', 'land', 'revenue']
        for i in range(1, 9):
            citizen, _ = User.objects.get_or_create(username=f'demo-citizen{i}', defaults={'role': 'citizen', 'first_name': f'Citizen {i}', 'last_name': 'Demo', 'email': f'citizen{i}@example.test', 'district': 'Demo District', 'mobile': f'90000000{i:02d}'})
            citizen.role = 'citizen'; citizen.email_verified = True; citizen.must_change_password = False
            citizen.set_password('DemoCitizen!2026'); citizen.save()
            for j in range(1, 4):
                status = statuses[(i + j - 2) % len(statuses)]
                category = categories[(i + j) % 4]
                app, created = Application.objects.get_or_create(
                    citizen=citizen, description=f'Synthetic demonstration case {i}-{j}.', category=category,
                    defaults={'status': status, 'scheme': scheme if (i + j) % 4 == 0 else None,
                              'income': Decimal(180000 + i * 12000), 'assigned_officer': officers[(i + j) % 2],
                              'department': departments['REV' if (i + j) % 2 == 0 else 'DMC']})
                if created:
                    ApplicationStatusHistory.objects.create(application=app, status=app.status, actor=admin, remark='Synthetic seed record')
                if not app.history.exists():
                    ApplicationStatusHistory.objects.create(application=app, status=app.status, actor=admin, remark='Synthetic seed record')
                if not app.assessments.exists():
                    EligibilityAssessment.objects.create(application=app, outcome='Potentially Eligible', explanation=['Synthetic sample assessment; officer verification required.'])
                Notification.objects.get_or_create(recipient=citizen, application=app, message=f'Demonstration update for {app.public_id}.')
                AuditLog.objects.get_or_create(actor=admin, application=app, action='demo_seed', detail='Synthetic demonstration data')

        EmailLog.objects.get_or_create(recipient='citizen1@example.test', kind='demo_seed', subject='Demonstration welcome email',
                                       defaults={'status': EmailLog.Status.SENT, 'user': User.objects.filter(username='demo-citizen1').first()})

        self.stdout.write(self.style.SUCCESS(
            'Demo data ready. Departments: 3, officers: demo-officer1/2, citizens: demo-citizen1..8. '
            'Admin login: admin / admin123 (other demo passwords are listed in README.md).'))
