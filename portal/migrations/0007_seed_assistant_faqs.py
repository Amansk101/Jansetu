from django.db import migrations

DEFAULT_FAQS = [
    {
        'question': 'How do I apply for a government service?',
        'topic': 'Applications',
        'keywords': 'apply, application, new application, submit, how to apply, form',
        'answer': ('Sign in to your citizen workspace and choose "New application".\n'
                   '1. Select the service category (welfare, disaster, land or revenue).\n'
                   '2. Fill in the details and attach the required documents.\n'
                   '3. Submit the form. You receive a unique Application ID instantly and an email confirmation.'),
    },
    {
        'question': 'Which documents do I need to upload?',
        'topic': 'Documents',
        'keywords': 'documents, upload, papers, aadhaar, income certificate, land documents, proof, attachments',
        'answer': ('Common documents are identity proof, address proof and any category-specific paper such as an income '
                   'certificate, land record or loss report. The upload step lists what is required for the category you pick. '
                   'Upload clear PDF or image files so the AI document check can read them.'),
    },
    {
        'question': 'How can I track my application status?',
        'topic': 'Tracking',
        'keywords': 'status, track, tracking, where is my application, progress, update',
        'answer': ('Open "Application history" in your workspace to see every application and its current status. '
                   'You also receive an email and an in-app notification whenever the status changes or an officer adds a remark.'),
    },
    {
        'question': 'How long does processing take?',
        'topic': 'Tracking',
        'keywords': 'how long, time, days, processing time, delay, when will i get',
        'answer': ('Processing time depends on the service and how quickly the required documents are verified. '
                   'The dashboard shows a delay-risk indicator for every case so you can see if an application needs attention.'),
    },
    {
        'question': 'What is the AI document check?',
        'topic': 'AI',
        'keywords': 'ai, ocr, document check, extraction, verification, automatic, machine reading',
        'answer': ('When you upload a document, JanSutra AI uses OCR (Tesseract and OpenCV) to read the text and suggest the '
                   'key fields such as name, number and amount. Officers see these suggestions to save manual typing. '
                   'The AI only assists — a human officer verifies everything.'),
    },
    {
        'question': 'How is eligibility decided?',
        'topic': 'Eligibility',
        'keywords': 'eligibility, eligible, qualify, rules, criteria, am i eligible',
        'answer': ('The eligibility engine compares the details you entered against the rules configured for the scheme by the '
                   'department, for example an income limit. It shows a clear explanation of why a case passes or fails. '
                   'The final eligibility call is always taken by an authorised officer.'),
    },
    {
        'question': 'How is compensation calculated?',
        'topic': 'Compensation',
        'keywords': 'compensation, calculation, amount, money, rate, estimate, how much',
        'answer': ('Compensation is estimated from the land area, category and the rates configured by the department '
                   '(base rate, multiplier, additional components and deductions). The estimate is shown transparently with '
                   'a full breakdown, and the approved amount is confirmed by an officer.'),
    },
    {
        'question': 'What happens if a document is missing?',
        'topic': 'Documents',
        'keywords': 'missing document, incomplete, resubmit, asked for document, more information',
        'answer': ('If something is missing, the officer marks the case as "More information required" and you receive an email '
                   'and a notification listing exactly what to upload. Sign in, upload the missing paper on the application page '
                   'and the case continues automatically.'),
    },
    {
        'question': 'Will I get an acknowledgement?',
        'topic': 'Applications',
        'keywords': 'acknowledgement, receipt, proof, receipt download',
        'answer': ('Yes. Every submitted application has a downloadable acknowledgement with the Application ID, category, '
                   'submission date and status. Open the application and choose "Download acknowledgement".'),
    },
    {
        'question': 'Who makes the final decision?',
        'topic': 'Decisions',
        'keywords': 'final decision, who approves, approve, reject, authority, sanction',
        'answer': ('Only an authorised government officer makes the final decision to approve or reject an application. '
                   'The AI platform provides recommendations, eligibility checks and estimates, but never decides on its own.'),
    },
    {
        'question': 'How do I reset my password?',
        'topic': 'Account',
        'keywords': 'password, forgot password, reset, login problem, sign in problem',
        'answer': ('On the sign-in page choose "Forgot your password?" and enter your registered email. A secure reset link is '
                   'sent to that address. If it does not arrive, check your spam folder or contact your district office.'),
    },
    {
        'question': 'How do I verify my email address?',
        'topic': 'Account',
        'keywords': 'verify email, verification, confirm email, activation link, cannot login verify',
        'answer': ('After registration you receive a verification email with a confirmation link. Open it to activate your citizen '
                   'account. If the mail has expired you can request a new one from the verification page.'),
    },
]


def add_faqs(apps, schema_editor):
    AssistantFAQ = apps.get_model('portal', 'AssistantFAQ')
    for item in DEFAULT_FAQS:
        AssistantFAQ.objects.update_or_create(question=item['question'], defaults=item)


def remove_faqs(apps, schema_editor):
    AssistantFAQ = apps.get_model('portal', 'AssistantFAQ')
    AssistantFAQ.objects.filter(question__in=[item['question'] for item in DEFAULT_FAQS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0006_assistantfaq'),
    ]

    operations = [
        migrations.RunPython(add_faqs, remove_faqs),
    ]
