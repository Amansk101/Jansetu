from django.db import migrations

DOCUMENT_FAQS = [
    {
        'question': 'Which documents are required for a Welfare Scheme application?',
        'topic': 'Documents',
        'keywords': 'welfare documents, welfare scheme documents, what documents welfare, bpl documents, subsidy documents',
        'answer': ('Welfare Scheme applications need these documents:\n'
                   '1. Identity proof (Aadhaar / Voter ID / Passport)\n'
                   '2. Address proof (ration card or electricity bill)\n'
                   '3. Income certificate or self-declaration of household income\n'
                   '4. Bank passbook copy (for benefit transfer)\n'
                   '5. Passport-size photograph\n'
                   'Upload clear scans from the application page after submitting.'),
    },
    {
        'question': 'Which documents are required for a Disaster Relief application?',
        'topic': 'Documents',
        'keywords': 'disaster documents, relief documents, flood documents, damage proof, disaster relief documents',
        'answer': ('Disaster Relief applications need these documents:\n'
                   '1. Identity proof (Aadhaar / Voter ID)\n'
                   '2. Address proof / residence certificate\n'
                   '3. Photographs of the damage or loss\n'
                   '4. Loss or damage estimate or panchnama (if available)\n'
                   '5. Bank passbook copy\n'
                   'Upload clear scans from the application page after submitting.'),
    },
    {
        'question': 'Which documents are required for a Land Acquisition application?',
        'topic': 'Documents',
        'keywords': 'land documents, land acquisition documents, 7/12 extract, survey number, land record, compensation documents',
        'answer': ('Land Acquisition / Compensation applications need these documents:\n'
                   '1. Identity proof (Aadhaar / Voter ID)\n'
                   '2. Land ownership record (7/12 extract, Form I & XIV)\n'
                   '3. Survey number / property map\n'
                   '4. Sale deed or inheritance document\n'
                   '5. Bank passbook copy\n'
                   'Upload clear scans from the application page after submitting.'),
    },
    {
        'question': 'Which documents are required for a Revenue Service application?',
        'topic': 'Documents',
        'keywords': 'revenue documents, certificate documents, income certificate documents, revenue service documents',
        'answer': ('Revenue Service applications need these documents:\n'
                   '1. Identity proof (Aadhaar / Voter ID)\n'
                   '2. Address proof / residence certificate\n'
                   '3. Property or record document relevant to the service requested\n'
                   '4. Supporting affidavit (if applicable)\n'
                   'Upload clear scans from the application page after submitting.'),
    },
]


def add_faqs(apps, schema_editor):
    AssistantFAQ = apps.get_model('portal', 'AssistantFAQ')
    for item in DOCUMENT_FAQS:
        AssistantFAQ.objects.update_or_create(question=item['question'], defaults=item)


def remove_faqs(apps, schema_editor):
    AssistantFAQ = apps.get_model('portal', 'AssistantFAQ')
    AssistantFAQ.objects.filter(question__in=[item['question'] for item in DOCUMENT_FAQS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0008_department_categories'),
    ]

    operations = [
        migrations.RunPython(add_faqs, remove_faqs),
    ]
