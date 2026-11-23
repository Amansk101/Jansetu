from django.db import migrations, models

# Departments and the application categories each one handles. A new case is
# routed to the first active department whose category list contains it.
DEPARTMENTS = [
    ('Revenue Administration', 'REV', 'Land records, revenue services and compensation.', ['revenue', 'land']),
    ('Disaster Management Cell', 'DMC', 'Disaster relief applications and loss assessment.', ['disaster']),
    ('Welfare & Schemes Desk', 'WEL', 'Welfare scheme screening and verification.', ['welfare']),
]


def seed_departments(apps, schema_editor):
    Department = apps.get_model('portal', 'Department')
    Application = apps.get_model('portal', 'Application')
    mapping = {}
    for name, code, desc, categories in DEPARTMENTS:
        department, _ = Department.objects.get_or_create(
            name=name, defaults={'code': code, 'description': desc})
        department.categories = categories
        department.save(update_fields=['categories'])
        for category in categories:
            mapping.setdefault(category, department)
    # Backfill any existing case that has no department yet.
    for application in Application.objects.filter(department__isnull=True):
        department = mapping.get(application.category)
        if department:
            application.department = department
            application.save(update_fields=['department'])


def clear_departments(apps, schema_editor):
    # Reversible no-op: the categories field itself is removed by the reverse
    # AddField operation; seeded departments are harmless to keep.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0007_seed_assistant_faqs'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='categories',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(seed_departments, clear_departments),
    ]
