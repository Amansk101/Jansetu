import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-change-me-before-deployment')
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost,.onrender.com').split(',') if h.strip()]
# Render terminates TLS in front of the app, so trust its forwarded protocol header.
# This lets Django build https:// links (emails, certificates) and use secure cookies.
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get(
    'DJANGO_CSRF_TRUSTED_ORIGINS', 'https://*.onrender.com').split(',') if o.strip()]
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'portal',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves collected static files directly in production (no separate web server needed).
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'portal.middleware.ForcePasswordChangeMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True, 'OPTIONS': {'context_processors': [
        'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'portal.context_processors.unread_notifications',
        'portal.context_processors.officer_permissions',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'
if os.environ.get('DATABASE_URL'):
    # Render (and most hosts) provide a single DATABASE_URL connection string.
    import dj_database_url
    DATABASES = {'default': dj_database_url.config(
        conn_max_age=600, conn_health_checks=True, ssl_require=True)}
elif os.environ.get('POSTGRES_DB'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': os.environ['POSTGRES_DB'],
        'USER': os.environ.get('POSTGRES_USER', ''), 'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'), 'PORT': os.environ.get('POSTGRES_PORT', '5432')}}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'en'
# Languages offered by the interface. English plus the 22 scheduled languages
# of India. Interface text is translated from locale/*/LC_MESSAGES/django.po.
LANGUAGES = [
    ('en', 'English'),
    ('as', 'অসমীয়া (Assamese)'),
    ('bn', 'বাংলা (Bengali)'),
    ('brx', 'बड़ो (Bodo)'),
    ('doi', 'डोगरी (Dogri)'),
    ('gu', 'ગુજરાતી (Gujarati)'),
    ('hi', 'हिन्दी (Hindi)'),
    ('kn', 'ಕನ್ನಡ (Kannada)'),
    ('ks', 'کٲشُر (Kashmiri)'),
    ('kok', 'कोंकणी (Konkani)'),
    ('mai', 'मैथिली (Maithili)'),
    ('ml', 'മലയാളം (Malayalam)'),
    ('mni', 'মৈতৈলোন্ (Manipuri)'),
    ('mr', 'मराठी (Marathi)'),
    ('ne', 'नेपाली (Nepali)'),
    ('or', 'ଓଡ଼ିଆ (Odia)'),
    ('pa', 'ਪੰਜਾਬੀ (Punjabi)'),
    ('sa', 'संस्कृतम् (Sanskrit)'),
    ('sat', 'ᱥᱟᱱᱛᱟᱲᱤ (Santali)'),
    ('sd', 'سنڌي (Sindhi)'),
    ('ta', 'தமிழ் (Tamil)'),
    ('te', 'తెలుగు (Telugu)'),
    ('ur', 'اردو (Urdu)'),
]
# Right-to-left scripts need the document direction flipped.
RTL_LANGUAGES = ['ur', 'sd', 'ks']
LOCALE_PATHS = [BASE_DIR / 'locale']
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
# collectstatic writes here; WhiteNoise serves this folder in production.
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'portal.User'
LOGIN_URL = 'login'
FILE_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# --- Email / SMTP (all configuration comes from environment variables) ---
_default_backend = ('django.core.mail.backends.console.EmailBackend' if DEBUG
                    else 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_BACKEND = os.environ.get('DJANGO_EMAIL_BACKEND', _default_backend)
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() == 'true'
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'false').lower() == 'true'
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '10'))
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
RESEND_FROM_EMAIL = os.environ.get('RESEND_FROM_EMAIL', 'JanSutra AI <onboarding@resend.dev>')

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'JanSutra AI <onboarding@resend.dev>')
EMAIL_SUBJECT_PREFIX = os.environ.get('EMAIL_SUBJECT_PREFIX', '[JanSutra AI] ')

# Base URL used to build secure links inside emails (no trailing slash).
SITE_BASE_URL = os.environ.get('SITE_BASE_URL', 'http://127.0.0.1:8000')
EMAIL_VERIFICATION_TIMEOUT = int(os.environ.get('EMAIL_VERIFICATION_TIMEOUT', str(60 * 60 * 24 * 3)))
# Citizen accounts must confirm their email before signing in (disable for quick local demos).
REQUIRE_EMAIL_VERIFICATION = os.environ.get('REQUIRE_EMAIL_VERIFICATION', 'true').lower() == 'true'
# Temporary password issued to a new officer must be changed on first login.
OFFICER_TEMP_PASSWORD_BYTES = int(os.environ.get('OFFICER_TEMP_PASSWORD_BYTES', '12'))
# Lifetime of password-reset and email-verification links (seconds).
PASSWORD_RESET_TIMEOUT = int(os.environ.get('PASSWORD_RESET_TIMEOUT', str(60 * 60 * 24)))

# --- Login attempt protection ---
LOGIN_MAX_ATTEMPTS = int(os.environ.get('LOGIN_MAX_ATTEMPTS', '5'))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get('LOGIN_LOCKOUT_SECONDS', '300'))

# --- Initial Admin / Collector bootstrap (used by the create_collector command) ---
COLLECTOR_USERNAME = os.environ.get('COLLECTOR_USERNAME', '')
COLLECTOR_EMAIL = os.environ.get('COLLECTOR_EMAIL', '')
COLLECTOR_PASSWORD = os.environ.get('COLLECTOR_PASSWORD', '')

# --- AI Citizen Assistant (Google Gemini) ---
# Leave GEMINI_API_KEY empty to use the deterministic FAQ-only assistant.
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash')
# Tried in order when the primary model is unavailable (free-tier spikes).
GEMINI_FALLBACK_MODELS = [
    model.strip()
    for model in os.environ.get(
        'GEMINI_FALLBACK_MODELS', 'gemini-flash-latest,gemini-3.1-flash-lite'
    ).split(',')
    if model.strip()
]
GEMINI_TIMEOUT = int(os.environ.get('GEMINI_TIMEOUT', '3'))
