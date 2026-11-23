import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from portal.models import User, UserProfile


class Command(BaseCommand):
    help = ('Create or update the single Administrator / District Collector account. '
            'Credentials are read from COLLECTOR_USERNAME / COLLECTOR_EMAIL / COLLECTOR_PASSWORD '
            'environment variables (or --username/--email/--password). No credentials are hardcoded.')

    def add_arguments(self, parser):
        parser.add_argument('--username', default='', help='Collector username (defaults to COLLECTOR_USERNAME).')
        parser.add_argument('--email', default='', help='Collector email (defaults to COLLECTOR_EMAIL).')
        parser.add_argument('--password', default='', help='Collector password (defaults to COLLECTOR_PASSWORD).')

    def handle(self, *args, **options):
        username = (options['username'] or settings.COLLECTOR_USERNAME or os.environ.get('COLLECTOR_USERNAME', '')).strip()
        email = (options['email'] or settings.COLLECTOR_EMAIL or os.environ.get('COLLECTOR_EMAIL', '')).strip()
        password = options['password'] or settings.COLLECTOR_PASSWORD or os.environ.get('COLLECTOR_PASSWORD', '')
        if not username or not password:
            raise CommandError(
                'Set COLLECTOR_USERNAME and COLLECTOR_PASSWORD in the environment (or pass '
                '--username/--password) before running create_collector.'
            )
        if len(password) < 8:
            raise CommandError('The collector password must be at least 8 characters long.')

        user = User.objects.filter(username=username).first()
        created = user is None
        if created:
            user = User(username=username)
        user.role = User.Role.ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.email_verified = True
        user.must_change_password = False
        if email:
            user.email = email
        user.set_password(password)
        user.save()
        UserProfile.objects.get_or_create(user=user)

        others = User.objects.filter(role=User.Role.ADMIN).exclude(pk=user.pk)
        if others.exists():
            self.stdout.write(self.style.WARNING(
                f'Note: {others.count()} other administrator account(s) exist. JanSutra AI is designed around a '
                f'single Collector account — review them with: python manage.py shell.'
            ))
        self.stdout.write(self.style.SUCCESS(
            f'Collector "{username}" {"created" if created else "updated"}. Keep these credentials secure.'
        ))
