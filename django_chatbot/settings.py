"""
Configuración del proyecto.

Los valores sensibles (llaves de API, SECRET_KEY) se leen del archivo .env
que está junto a manage.py. Copia .env.example a .env y llena tus llaves.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "si", "sí")


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# --- Seguridad -------------------------------------------------------------
DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Solo para desarrollo local. En producción SECRET_KEY es obligatoria.
        from django.core.management.utils import get_random_secret_key
        SECRET_KEY = get_random_secret_key()
    else:
        raise RuntimeError("Falta SECRET_KEY en el archivo .env")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")
TRUSTED_PROXY_CIDRS = env_list('TRUSTED_PROXY_CIDRS', '')

# Render define esta variable con el dominio de la app (xxx.onrender.com).
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOST}")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^salud$"]
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_CONTENT_TYPE_NOSNIFF = True

X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # una semana

# Dirección del panel de administración. Cámbiala en .env por algo difícil de adivinar.
ADMIN_URL = os.getenv("ADMIN_URL", "admin/").strip("/") + "/"

# --- Aplicaciones ----------------------------------------------------------
INSTALLED_APPS = [
    "chatbot.admin_config.ProtectedAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "chatbot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "django_chatbot.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "chatbot.context.account_notice",
            ],
        },
    },
]

WSGI_APPLICATION = "django_chatbot.wsgi.application"

# Caché: en línea se guarda en la base para que los límites sobrevivan reinicios.
if os.getenv("DATABASE_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "cache_table"}}

# Con DATABASE_URL (Neon u otro PostgreSQL) usa esa base; sin ella, SQLite local.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
        conn_health_checks=True,
    )
}

# Argon2 para contraseñas nuevas; las viejas se actualizan solas al iniciar sesión.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "interview"

# --- Inicio de sesión con Google (django-allauth) --------------------------
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_LOGIN_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APPS": [{"client_id": GOOGLE_CLIENT_ID, "secret": GOOGLE_CLIENT_SECRET, "key": ""}],
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"prompt": "select_account"},
        "OAUTH_PKCE_ENABLED": True,
    }
} if GOOGLE_LOGIN_ENABLED else {}
SOCIALACCOUNT_ONLY = True            # allauth solo para Google; usuario y contraseña siguen en nuestras vistas
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = False   # el botón usa POST con CSRF
SOCIALACCOUNT_STORE_TOKENS = False   # no se guardan tokens de Google
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_UNIQUE_EMAIL = False         # nunca se une una cuenta de Google con otra solo por el correo
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https" if not DEBUG else "http"

LANGUAGE_CODE = "es-mx"
TIME_ZONE = os.getenv("TIME_ZONE", "America/Mexico_City")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_MANIFEST_STRICT = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"chatbot": {"handlers": ["console"], "level": "INFO"}},
}

# --- Correo (recuperar contraseña) -----------------------------------------
# Con BREVO_API_KEY se envía por la API de Brevo; sin ella, los correos se
# muestran en la consola (útil en tu laptop).
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
EMAIL_BACKEND = ("chatbot.email_backend.BrevoEmailBackend" if BREVO_API_KEY
                 else "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.getenv("EMAIL_FROM", "no-responder@example.com")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Práctica ITM")
PASSWORD_RESET_TIMEOUT = 60 * 60  # el enlace vence en 1 hora

# --- Inteligencia artificial -----------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Orden en que se prueban los modelos. Si uno falla o se agota su cuota,
# se usa el siguiente. Formato: proveedor:modelo, separados por comas.
LLM_CHAIN = env_list(
    "LLM_CHAIN",
    "groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite",
)
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "40"))

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")
# Modelos de voz en orden; si el primero se queda sin cuota se usa el siguiente.
WHISPER_MODELS = env_list("WHISPER_MODELS", f"{WHISPER_MODEL},whisper-large-v3")
# Transcripciones por usuario por hora (la cuota de audio de Groq es aparte).
TRANSCRIBE_PER_HOUR = int(os.getenv("TRANSCRIBE_PER_HOUR", "60"))

# Límite de mensajes por usuario para cuidar la cuota gratuita.
MESSAGES_PER_MINUTE = int(os.getenv("MESSAGES_PER_MINUTE", "12"))
MESSAGES_PER_DAY = int(os.getenv("MESSAGES_PER_DAY", "250"))

# Preguntas por entrevista.
INTERVIEW_QUESTIONS = int(os.getenv("INTERVIEW_QUESTIONS", "8"))
