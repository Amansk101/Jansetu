"""Seed the JanSutra service catalogue described in the project specification.

Nine departments, the services each one offers, the exact documents every
service needs (per the applicable government rules) and a certificate template
for the services that issue one. Everything is editable afterwards from the
administrator console, so nothing here is hardcoded in the frontend.
"""
from django.db import migrations
from django.utils.text import slugify

# (code, name, description, categories, icon, order)
DEPARTMENTS = [
    ('REV', 'Revenue Department', 'Land records, revenue certificates, compensation and district revenue administration.',
     ['revenue', 'land'], 'bi-cash-coin', 1),
    ('WEL', 'Social Welfare Department', 'Social security pensions, ration cards and welfare scheme benefits.',
     ['welfare'], 'bi-people', 2),
    ('DMC', 'Disaster Management Department', 'Disaster relief assistance, loss assessment and rehabilitation support.',
     ['disaster'], 'bi-cloud-lightning-rain', 3),
    ('EDU', 'Education Department', 'Scholarships, bonafide and migration certificates and school services.',
     ['education'], 'bi-mortarboard', 4),
    ('HLT', 'Health Department', 'Health scheme enrolment, medical reimbursement and public health services.',
     ['health'], 'bi-heart-pulse', 5),
    ('AGR', 'Agriculture Department', 'Farmer registration, input subsidies and crop insurance support.',
     ['agriculture'], 'bi-tree', 6),
    ('MUN', 'Municipal Administration', 'Trade licences, water connections and property tax services.',
     ['municipal'], 'bi-buildings', 7),
    ('WCD', 'Women and Child Development Department', 'Women and child welfare schemes and support services.',
     ['wcd'], 'bi-gender-female', 8),
    ('OTH', 'Other Government Services', 'Other citizen services and general government requests.',
     ['other'], 'bi-grid-3x3-gap', 9),
]

ID_PROOF = 'Identity proof (Aadhaar / Voter ID / Passport)'
ADDRESS_PROOF = 'Address proof (ration card or electricity bill)'
PHOTO = 'Passport-size photograph'

# (department_code, service name, category, icon, description, eligibility,
#  instructions, [(document name, required, hint), ...])
SERVICES = [
    ('REV', 'Income Certificate', 'revenue', 'bi-cash-stack',
     'Official certificate of the annual income of the applicant and family, used for scholarships, welfare schemes and concessions.',
     'Any resident of the district who needs proof of annual household income.',
     'Fill the application, upload every required document, then submit. The AI checks the documents and forwards the case to the Revenue officer for approval.',
     [(ID_PROOF, True, 'Aadhaar, Voter ID or Passport'),
      (ADDRESS_PROOF, True, 'Ration card, electricity bill or rent agreement'),
      ('Income proof or supporting income declaration', True, 'Salary slips, ITR, employer letter or a signed self-declaration'),
      ('Ration card', False, 'If applicable, for family income verification'),
      (PHOTO, True, 'Recent passport-size photograph'),
      ('Self-declaration', True, 'Signed declaration of the annual family income')]),

    ('REV', 'Caste Certificate', 'revenue', 'bi-person-badge',
     'Certificate of caste / community for education, employment and reservation benefits.',
     'Applicants belonging to a recognised caste or community as per state rules.',
     'Upload the caste proof of the applicant or a close relative, then submit for officer verification.',
     [(ID_PROOF, True, ''),
      ('Caste proof of father or relative', True, 'Existing caste certificate or school record showing caste'),
      (ADDRESS_PROOF, True, ''),
      (PHOTO, True, ''),
      ('Self-declaration', True, 'Signed declaration of caste and place of origin')]),

    ('REV', 'Domicile Certificate', 'revenue', 'bi-geo-alt',
     'Certificate proving continuous residence in the state, required for education and government benefits.',
     'Persons who have resided in the state continuously for the period prescribed by government rules.',
     'Provide proof of continuous residence and identity, then submit for verification.',
     [(ID_PROOF, True, ''),
      ('Proof of continuous residence', True, 'Ration card, electricity bill, school record or rent agreement'),
      ('Birth certificate or school leaving certificate', True, ''),
      (PHOTO, True, '')]),

    ('REV', 'Non-Creamy Layer Certificate', 'revenue', 'bi-file-earmark-check',
     'Certificate confirming that the applicant is not part of the creamy layer of an Other Backward Class.',
     'OBC applicants whose family income is within the limit set by government rules.',
     'Upload income and caste evidence; the officer verifies the income limit before approval.',
     [(ID_PROOF, True, ''),
      ('Caste certificate', True, 'Existing caste certificate of the applicant or relative'),
      ('Income proof of the family', True, 'ITR, salary slips or income certificate'),
      (ADDRESS_PROOF, True, ''),
      ('Self-declaration', True, 'Declaration of family income and creamy-layer status')]),

    ('REV', 'Nationality Certificate', 'revenue', 'bi-passport',
     'Certificate confirming Indian nationality, required for passport, education and employment purposes.',
     'Indian citizens who need an official confirmation of nationality.',
     'Submit identity and citizenship evidence; the officer verifies before issuing the certificate.',
     [(ID_PROOF, True, ''),
      ('Proof of citizenship', True, 'Birth certificate, school leaving certificate or passport'),
      ('Proof of continuous residence', True, ''),
      (PHOTO, True, '')]),

    ('REV', 'Residence Certificate', 'revenue', 'bi-house-door',
     'Certificate confirming the present residential address of the applicant.',
     'Any resident who needs proof of their current residential address.',
     'Provide address and identity proof, then submit for verification.',
     [(ID_PROOF, True, ''),
      (ADDRESS_PROOF, True, ''),
      ('Proof of continuous residence', True, 'Ration card, electricity bill or rent agreement'),
      (PHOTO, True, '')]),

    ('REV', 'Land Record / 7-12 Extract Copy', 'land', 'bi-map',
     'Certified copy of the land record (7/12 extract or Form I & XIV) for a survey number.',
     'Land owners or authorised applicants seeking a certified land record copy.',
     'Enter the survey number and upload ownership evidence, then submit for the record copy.',
     [(ID_PROOF, True, ''),
      ('Survey number and property details', True, ''),
      ('Previous land record or sale deed', True, ''),
      (ADDRESS_PROOF, True, '')]),

    ('REV', 'Other Revenue Service', 'revenue', 'bi-three-dots',
     'Any other revenue department service or request not listed above.',
     'Applicants who need a revenue service that is not covered by another entry.',
     'Describe the service you need, upload the relevant documents and submit.',
     [(ID_PROOF, True, ''),
      (ADDRESS_PROOF, True, ''),
      ('Document relevant to the service requested', True, '')]),

    ('WEL', 'Ration Card', 'welfare', 'bi-card-checklist',
     'New ration card or addition / deletion of family members on an existing card.',
     'Residents of the district who are eligible for a ration card under the public distribution system.',
     'Upload identity, address and family details, then submit for verification.',
     [(ID_PROOF, True, ''), (ADDRESS_PROOF, True, ''),
      ('Family members proof', True, 'Aadhaar or birth certificate of family members'),
      (PHOTO, True, '')]),

    ('WEL', 'Old Age Pension Scheme', 'welfare', 'bi-person-wheelchair',
     'Monthly social security pension for senior citizens below the prescribed income limit.',
     'Senior citizens of the prescribed age whose family income is within the scheme limit.',
     'Upload age, income and bank details, then submit for verification by the welfare officer.',
     [(ID_PROOF, True, ''), ('Age proof', True, 'Birth certificate or school record'),
      ('Income proof or self-declaration of household income', True, ''),
      ('Bank passbook copy', True, 'For benefit transfer'), (PHOTO, True, '')]),

    ('WEL', 'Widow Pension Scheme', 'welfare', 'bi-person-heart',
     'Monthly financial assistance for widows under the state social security scheme.',
     'Widowed women whose family income is within the scheme limit.',
     'Upload the death certificate of the spouse, income and bank details, then submit.',
     [(ID_PROOF, True, ''), ('Death certificate of spouse', True, ''),
      ('Income proof or self-declaration of household income', True, ''),
      ('Bank passbook copy', True, ''), (PHOTO, True, '')]),

    ('WEL', 'Disability Pension Scheme', 'welfare', 'bi-universal-access',
     'Monthly pension and support for persons with a certified disability.',
     'Persons with a disability of the prescribed percentage and income within the scheme limit.',
     'Upload the disability certificate, income and bank details, then submit.',
     [(ID_PROOF, True, ''), ('Disability certificate', True, 'Issued by the competent medical authority'),
      ('Income proof or self-declaration of household income', True, ''),
      ('Bank passbook copy', True, ''), (PHOTO, True, '')]),

    ('DMC', 'Disaster Relief Assistance', 'disaster', 'bi-house-exclamation',
     'Financial relief for families affected by a notified natural disaster.',
     'Families affected by a notified disaster in the district.',
     'Upload identity, residence and damage evidence, then submit for assessment.',
     [(ID_PROOF, True, ''), ('Address proof / residence certificate', True, ''),
      ('Photographs of the damage or loss', True, ''),
      ('Loss or damage estimate or panchnama', False, 'If available'),
      ('Bank passbook copy', True, '')]),

    ('DMC', 'Crop Loss Compensation', 'disaster', 'bi-flower1',
     'Compensation for crop loss caused by flood, drought or other notified calamity.',
     'Farmers whose crops were damaged by a notified calamity.',
     'Upload land and crop loss evidence, then submit for field assessment.',
     [(ID_PROOF, True, ''), ('Land record (7/12 extract)', True, ''),
      ('Crop loss evidence', True, 'Photographs or panchnama of the affected crop'),
      ('Bank passbook copy', True, '')]),

    ('DMC', 'House Damage Assistance', 'disaster', 'bi-house-crack',
     'Assistance for repair or reconstruction of houses damaged in a disaster.',
     'Owners of houses damaged in a notified disaster.',
     'Upload ownership, damage evidence and estimate, then submit for assessment.',
     [(ID_PROOF, True, ''), ('House ownership proof', True, ''),
      ('Damage photographs', True, ''),
      ('Repair or reconstruction estimate', False, 'If available'),
      ('Bank passbook copy', True, '')]),

    ('EDU', 'Scholarship Application', 'education', 'bi-award',
     'Post-matric scholarship for eligible students under a government education scheme.',
     'Students who meet the scheme eligibility and income criteria.',
     'Upload mark sheets, income and bank details, then submit for verification.',
     [(ID_PROOF, True, ''), ('Previous mark sheet', True, ''),
      ('Income certificate or self-declaration of household income', True, ''),
      ('Bank passbook copy', True, ''), (PHOTO, True, '')]),

    ('EDU', 'Bonafide Certificate', 'education', 'bi-file-earmark-person',
     'Certificate confirming that the applicant is a bona fide student of an institution.',
     'Students currently enrolled in a recognised institution.',
     'Upload the enrolment proof and identity, then submit.',
     [(ID_PROOF, True, ''), ('Enrolment or admission proof', True, 'Fee receipt or ID card'),
      (PHOTO, True, '')]),

    ('EDU', 'Migration Certificate', 'education', 'bi-arrow-left-right',
     'Certificate required when a student moves from one board or university to another.',
     'Students who have completed a course and are migrating to another institution.',
     'Upload the passing mark sheet and identity, then submit.',
     [(ID_PROOF, True, ''), ('Passing mark sheet', True, ''), (PHOTO, True, '')]),

    ('HLT', 'Health Scheme Enrolment', 'health', 'bi-heart-pulse',
     'Enrolment in a government health insurance or assistance scheme.',
     'Residents who are eligible under the health scheme.',
     'Upload identity, income and family details, then submit for enrolment.',
     [(ID_PROOF, True, ''), (ADDRESS_PROOF, True, ''),
      ('Income proof or self-declaration of household income', True, ''), (PHOTO, True, '')]),

    ('HLT', 'Medical Reimbursement', 'health', 'bi-receipt',
     'Reimbursement of treatment expenses under an applicable government health scheme.',
     'Patients treated at an empanelled hospital under the scheme.',
     'Upload the hospital bills, discharge summary and scheme card, then submit.',
     [(ID_PROOF, True, ''), ('Hospital bills and receipts', True, ''),
      ('Discharge summary or medical certificate', True, ''),
      ('Health scheme card', False, 'If applicable')]),

    ('AGR', 'Farmer Registration', 'agriculture', 'bi-person-vcard',
     'Registration of farmers for access to government agriculture schemes.',
     'Farmers owning or cultivating land in the district.',
     'Upload land record and identity, then submit for verification.',
     [(ID_PROOF, True, ''), ('Land record (7/12 extract)', True, ''), (PHOTO, True, '')]),

    ('AGR', 'Farm Input Subsidy', 'agriculture', 'bi-basket',
     'Subsidy on seeds, fertiliser or farm equipment under a government scheme.',
     'Registered farmers who meet the scheme criteria.',
     'Upload the land record, quotation and bank details, then submit.',
     [(ID_PROOF, True, ''), ('Land record (7/12 extract)', True, ''),
      ('Quotation or purchase estimate', True, ''), ('Bank passbook copy', True, '')]),

    ('AGR', 'Crop Insurance Claim', 'agriculture', 'bi-shield-check',
     'Claim under the crop insurance scheme for a notified crop loss.',
     'Farmers enrolled in the crop insurance scheme with a notified loss.',
     'Upload the insurance details and loss evidence, then submit.',
     [(ID_PROOF, True, ''), ('Crop insurance policy or receipt', True, ''),
      ('Crop loss evidence', True, ''), ('Bank passbook copy', True, '')]),

    ('MUN', 'Trade Licence', 'municipal', 'bi-shop',
     'Licence to run a trade or business within the municipal limits.',
     'Persons wishing to start or continue a trade within municipal limits.',
     'Upload identity, address and shop details, then submit for inspection.',
     [(ID_PROOF, True, ''), ('Shop or premises address proof', True, 'Rent agreement or ownership document'),
      ('Shop establishment photograph', True, ''), (PHOTO, True, '')]),

    ('MUN', 'Water Connection', 'municipal', 'bi-droplet',
     'New municipal water connection or transfer of an existing connection.',
     'Owners or lawful occupants of premises within the municipal water network.',
     'Upload ownership, address and identity proof, then submit.',
     [(ID_PROOF, True, ''), ('Property ownership or occupancy proof', True, ''),
      ('Property tax receipt', False, 'If available')]),

    ('MUN', 'Property Tax Assessment', 'municipal', 'bi-building-gear',
     'Assessment or revision of municipal property tax for a building or plot.',
     'Property owners within the municipal limits.',
     'Upload the ownership document and property details, then submit.',
     [(ID_PROOF, True, ''), ('Property ownership document', True, ''),
      ('Previous property tax receipt', False, 'If available')]),

    ('WCD', 'Child Welfare Scheme', 'wcd', 'bi-balloon',
     'Benefit under a government scheme for the welfare of children.',
     'Guardians of eligible children as per the scheme rules.',
     'Upload the child identity, guardian identity and income details, then submit.',
     [(ID_PROOF, True, 'Guardian identity proof'), ('Child birth certificate', True, ''),
      ('Income proof or self-declaration of household income', True, ''), (PHOTO, True, '')]),

    ('WCD', "Women's Welfare Scheme", 'wcd', 'bi-gender-female',
     'Financial or training assistance for women under a government welfare scheme.',
     'Women who meet the scheme eligibility and income criteria.',
     'Upload identity, income and bank details, then submit.',
     [(ID_PROOF, True, ''), ('Income proof or self-declaration of household income', True, ''),
      ('Bank passbook copy', True, ''), (PHOTO, True, '')]),

    ('OTH', 'General Grievance / Request', 'other', 'bi-chat-left-text',
     'A general request or grievance addressed to a government department.',
     'Any citizen with a request or grievance for a government department.',
     'Describe your request, attach any supporting document and submit.',
     [(ID_PROOF, True, ''), ('Supporting document', False, 'Attach anything relevant to your request')]),

    ('OTH', 'Other Certificate Request', 'other', 'bi-file-earmark-plus',
     'Request for any other government certificate not listed elsewhere.',
     'Applicants who need a certificate not covered by another service.',
     'Describe the certificate you need and upload the supporting documents.',
     [(ID_PROOF, True, ''), (ADDRESS_PROOF, True, ''),
      ('Document relevant to the certificate requested', True, '')]),
]

# Certificate templates for the services that issue a certificate.
TEMPLATES = {
    'Income Certificate': ('Income Certificate',
                           'This is to certify that the annual income of the applicant and family has been verified.',
                           'The applicant is a resident of the district and the details furnished have been verified against the submitted documents.'),
    'Caste Certificate': ('Caste Certificate',
                          'This is to certify the caste / community of the applicant as verified from the submitted records.',
                          'The applicant belongs to the caste / community shown above as per the records verified by this office.'),
    'Domicile Certificate': ('Domicile Certificate',
                             'This is to certify that the applicant is a domicile of the State as per the records verified.',
                             'The applicant has been residing continuously in the State as required by the applicable rules.'),
    'Non-Creamy Layer Certificate': ('Non-Creamy Layer Certificate',
                                     'This is to certify that the applicant does not fall in the creamy layer of the Other Backward Class.',
                                     'The family income of the applicant is within the limit prescribed for the non-creamy layer.'),
    'Nationality Certificate': ('Nationality Certificate',
                                'This is to certify that the applicant is a citizen of India as verified from the submitted records.',
                                'The applicant is an Indian citizen and the details furnished have been verified.'),
    'Residence Certificate': ('Residence Certificate',
                              'This is to certify the residential address of the applicant as verified from the submitted records.',
                              'The applicant resides at the address shown above as verified by this office.'),
}


def _slug_for(name, taken):
    base = slugify(name)[:80] or 'service'
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f'{base}-{n}'
    taken.add(candidate)
    return candidate


def seed_catalogue(apps, schema_editor):
    Department = apps.get_model('portal', 'Department')
    GovernmentService = apps.get_model('portal', 'GovernmentService')
    ServiceDocumentRequirement = apps.get_model('portal', 'ServiceDocumentRequirement')
    CertificateTemplate = apps.get_model('portal', 'CertificateTemplate')

    departments = {}
    for code, name, description, categories, icon, order in DEPARTMENTS:
        department, _ = Department.objects.get_or_create(code=code, defaults={'name': name})
        department.name = name
        department.description = description
        department.categories = categories
        department.icon = icon
        department.order = order
        department.active = True
        department.save()
        departments[code] = department

    taken_slugs = set(GovernmentService.objects.exclude(slug='').values_list('slug', flat=True))
    for index, (code, name, category, icon, description, eligibility, instructions, docs) in enumerate(SERVICES):
        department = departments[code]
        service, _ = GovernmentService.objects.get_or_create(
            department=department, name=name,
            defaults={'category': category}, )
        service.category = category
        service.icon = icon
        service.description = description
        service.eligibility = eligibility
        service.instructions = instructions
        service.active = True
        service.order = index
        if not service.slug:
            service.slug = _slug_for(name, taken_slugs)
        service.save()

        # Add the required documents once; the administrator can edit them later.
        if not ServiceDocumentRequirement.objects.filter(service=service).exists():
            for order, (doc_name, required, hint) in enumerate(docs):
                ServiceDocumentRequirement.objects.create(
                    service=service, name=doc_name, required=required,
                    description=hint or '', order=order, active=True)

        if name in TEMPLATES:
            title, subtitle, body = TEMPLATES[name]
            CertificateTemplate.objects.get_or_create(
                service=service,
                defaults={'title': title, 'subtitle': subtitle, 'body': body,
                          'signatory_designation': 'Authorised Signatory, ' + department.name,
                          'validity': 'Valid as per government rules from the date of issue'})


def unseed_catalogue(apps, schema_editor):
    # Non-destructive: seeded catalogue rows stay so nothing an administrator
    # edited is lost if this migration is rolled back.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0012_alter_application_category_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_catalogue, unseed_catalogue),
    ]
