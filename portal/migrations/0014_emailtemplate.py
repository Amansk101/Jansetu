"""Add the administrator-editable notification email templates.

Every built-in notification event is seeded with its default subject and body
so the administrator console is usable immediately; the text can then be edited
from the console without a code change.
"""
from django.db import migrations, models


def seed_templates(apps, schema_editor):
    EmailTemplate = apps.get_model('portal', 'EmailTemplate')
    from portal.emails import DEFAULT_EMAIL_TEMPLATES
    for row in DEFAULT_EMAIL_TEMPLATES:
        EmailTemplate.objects.update_or_create(
            kind=row['kind'],
            defaults={
                'name': row['name'],
                'description': row['description'],
                'placeholders': row['placeholders'],
                'subject': row['subject'],
                'body': row['body'],
                'active': True,
            })


def unseed_templates(apps, schema_editor):
    # Non-destructive: keep any templates the administrator has edited.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0013_seed_prd_catalogue'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(db_index=True, max_length=60, unique=True)),
                ('name', models.CharField(max_length=160)),
                ('description', models.CharField(blank=True, help_text='When this email is sent.', max_length=250)),
                ('placeholders', models.CharField(blank=True, help_text='Comma-separated values you can use in the subject and body.', max_length=250)),
                ('subject', models.CharField(max_length=200)),
                ('body', models.TextField()),
                ('active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.RunPython(seed_templates, unseed_templates),
    ]
