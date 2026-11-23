# Jan Sutra AI

**Less Paperwork. Faster Decisions. Transparent Governance.**

A Django based governance workflow demonstration for the Revenue Department (District Collectorate – Revenue Administration), proposed as a pilot for the Office of the Collector, South Goa. It uses synthetic records and configurable demonstration rules; it is not an official government service, and authorized people remain responsible for decisions.

## Included now

- Django citizen registration, login, profile management, role-aware dashboard, application submission and private tracking.
- Four application categories (welfare, disaster relief, land acquisition, revenue) with dynamic category-specific fields and a unique application ID.
- Private PDF/JPG/PNG upload with preview, optional Tesseract OCR, editable extracted fields, and an explicit manual-entry fallback when OCR tools are missing or text is unreadable.
- Citizen status timeline, notifications, officer remarks, document-correction replies, acknowledgement download, and application history.
- Officer workspace with real database counters, search/filter/sort queue, document preview, OCR data, eligibility recommendations, compensation estimates, officer assignment, internal remarks, document requests, and approve/reject decisions that require a reason.
- Administrator panel with live counts, department-wise and scheme-wise statistics, Chart.js charts fed from database records, and dedicated management screens for departments, schemes, eligibility rules, compensation rates, and officer accounts. There is a single administrator (the Collector); the administrator adds or removes officer IDs and passwords, while citizens register and manage their own accounts.
- Transparent rule-based eligibility engine (Eligible / Potentially Eligible / More Information Required / Not Eligible) with human-readable reasons; AI never rejects an application on its own.
- Configurable illustrative compensation calculator with a transparent breakdown and the disclaimer "Illustrative Estimate – Subject to Official Verification."
- Rule-based delay-risk indicator (Low / Medium / High) with an explanation of why a case is flagged.
- Duplicate and anomaly flagging for officers, with manual investigation; flags never auto-reject.
- Database-backed notifications, application status history, audit logging, filtered reports, and CSV export.
- Real email notification system (Django SMTP via environment variables, console backend in development) with a notification centre showing read/unread state, per-message email delivery status, and history on the administrator's **Notifications log** page.
- Citizen email verification (secure signed link with resend), password reset by email, and in-app password change. Login attempts are rate-limited, and every protected action is checked on the server.
- Officer account lifecycle: the Collector adds an officer, the system generates a unique Officer ID/username and a temporary password, emails an activation message, and the officer is forced to set a new password on first sign-in (enforced by middleware).
- Officer module and application-category permissions: the Collector can restrict an officer to specific modules (documents, eligibility, compensation) and categories; checks are enforced server-side, and an empty selection means unrestricted.
- Secure role-based access control, password hashing, CSRF protection, validated private uploads, and object-level checks that stop citizens from opening other citizens' cases.
- Synthetic demo seed command and automated tests.

Remaining future work: richer geographic profile editing and PDF-format reports (CSV export is provided).

## Email and notifications

All SMTP configuration is read from environment variables (see `.env.example`); no credentials are hardcoded. When `DJANGO_DEBUG=True` the console email backend is used by default, so verification, activation, reset, and status emails print to the terminal. To send real mail, set `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, and `SITE_BASE_URL` (used to build the secure links), and either set `DJANGO_DEBUG=False` or point `DJANGO_EMAIL_BACKEND` at `django.core.mail.backends.smtp.EmailBackend`.

Emails are sent to citizens (verification, submission, application ID, document processing, missing-document requests, status updates, approval/rejection, remarks, password reset), to officers (account activation, new/reassigned cases, correction requests, permission changes), and to the Collector (new applications, officer account events). Delivery failures are recorded with a `failed` status in the email log instead of breaking the user action. Only temporary credentials are ever emailed, and they must be changed at first sign-in; permanent passwords are never sent in plain text.

## Requirements

- Python 3.11 or later.
- PowerShell on Windows.
- PostgreSQL 14+ for a PostgreSQL-backed setup (optional for local demo).
- Tesseract OCR and Poppler are optional; without them uploaded files still work and documents show manual review status.

## Windows PowerShell setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py makemigrations portal
python manage.py migrate
$env:COLLECTOR_USERNAME="admin"; $env:COLLECTOR_PASSWORD="admin123"
python manage.py create_collector
python manage.py seed_demo_data
python manage.py runserver
```

Open http://127.0.0.1:8000/.

The default development configuration uses SQLite (`db.sqlite3`). To use PostgreSQL, create a database and set `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT` in the process environment before starting Django. Install dependencies from requirements.txt to get psycopg.

## Initial Administrator / District Collector

JanSutra AI is designed around a single administrator — the Collector. Create that account from environment variables (never hardcoded) with:

```powershell
$env:COLLECTOR_USERNAME="admin"; $env:COLLECTOR_EMAIL="armaan.sk113@gmail.com"; $env:COLLECTOR_PASSWORD="admin123"
python manage.py create_collector
```

The command creates or updates the account with administrator rights. If a `COLLECTOR_*` variable is missing it exits with an error. The Collector can then sign in, update their profile/password, and create officer accounts from **Administration → Accounts**.

## Officer account workflow

1. The Collector creates an officer (name, official email, optional department/designation and module/category permissions).
2. The system generates a unique Officer ID/username and a temporary password (or the Collector supplies one).
3. An activation email with the Officer ID, temporary password and sign-in link is sent to the officer.
4. The officer signs in; middleware forces them to set a new password before any other page opens.
5. The officer then sees only the modules and application categories the Collector granted.

Officers cannot register themselves, create other officers, or change administrative settings. The Collector can reset an officer's temporary password at any time (a fresh one is emailed), or deactivate/remove the account; removed officers' cases become unassigned for reassignment.

## Demo accounts

Run `python manage.py seed_demo_data` first. All passwords are synthetic and for local demonstration only:

| Role | Username | Password |
|---|---|---|
| Administrator | `admin` | `admin123` |
| Officer | `demo-officer1` | `DemoOfficer!2026` |
| Officer | `demo-officer2` | `DemoOfficer!2026` |
| Citizen | `demo-citizen1` through `demo-citizen8` | `DemoCitizen!2026` |

Seed is safe to rerun: the known accounts, scheme, and sample applications are reused. The generated personal names and contact data are fabricated. Demo accounts are seeded with their email already verified and (for officers) no forced password change, so you can sign in immediately. Citizens who self-register through the sign-up form are active right away — no email verification step is required at account creation.

## Automated tests

```powershell
python manage.py test portal
```

The suite covers registration, role-based access, application submission and validation, document upload, OCR field extraction, eligibility assessment, the compensation calculator, officer decisions, and cross-citizen access control. All checks run against a throwaway test database and do not touch `db.sqlite3`.

## End-to-end workflow

1. A citizen signs in, submits an application in one of the four categories, and uploads supporting documents.
2. Processing extracts document text where OCR is available, saves editable fields, and flags missing data or possible duplicates.
3. The eligibility engine and compensation calculator produce advisory results with visible reasons and a transparent breakdown.
4. An officer (or an administrator who assigns the case) reviews the documents and recommendation, requests corrections if needed, and records an approve/reject decision with a mandatory reason.
5. The citizen sees the new status, remarks, and notification in their dashboard.
6. The administrator monitors live counts, charts, reports, and audit logs drawn from the same database records.

## OCR notes

Image OCR needs the Python `pytesseract` package and a Tesseract executable available on PATH. Scanned PDF OCR additionally needs Poppler. OCR output is unverified text and can be empty or inaccurate. The system never invents extracted fields; the citizen/officer must review uploaded documents. The app limits uploads to 8 MB and PDF/JPG/JPEG/PNG.

## Production preparation

Set `DJANGO_DEBUG=False`, provide a strong `DJANGO_SECRET_KEY`, configure `DJANGO_ALLOWED_HOSTS`, use PostgreSQL, serve static and private media through an authenticated storage setup, enable HTTPS, configure secure cookies, and run behind a production WSGI/ASGI server. Never expose the development secret or demo passwords publicly. Uploaded media is private by application routing; configure storage permissions and backups before deployment.
