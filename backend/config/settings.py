import os
import json
import math
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "local-only-insecure-key-change-before-deployment"
    else:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DEBUG is disabled.")
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]

INSTALLED_APPS = [
    "daphne", "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "channels", "corsheaders", "rest_framework", "rest_framework.authtoken", "supply_chain.apps.SupplyChainConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
redis_url = os.getenv("ARES_REDIS_URL", "").strip()
if not redis_url and not DEBUG:
    raise ImproperlyConfigured("Set ARES_REDIS_URL to a shared Redis service when DEBUG is disabled.")
if redis_url and not DEBUG and not redis_url.startswith("rediss://"):
    raise ImproperlyConfigured("Use a TLS-enabled rediss:// URL for Redis when DEBUG is disabled.")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [redis_url]},
    }
} if redis_url else {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

# PostgreSQL is the ARES application database. Connection values come from the
# environment; blank user/host values use libpq's local defaults.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "ares"),
        "USER": os.getenv("POSTGRES_USER", ""),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", ""),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}
postgres_sslmode = os.getenv("POSTGRES_SSLMODE", "").strip()
postgres_sslrootcert = os.getenv("POSTGRES_SSLROOTCERT", "").strip()
postgres_options = {}
if postgres_sslmode:
    postgres_options["sslmode"] = postgres_sslmode
if postgres_sslrootcert:
    postgres_options["sslrootcert"] = postgres_sslrootcert
if postgres_options:
    DATABASES["default"]["OPTIONS"] = postgres_options

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if os.getenv("DJANGO_TRUST_PROXY_SSL", "false").lower() == "true"
    else None
)
SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "false").lower() == "true"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "supply_chain.authentication.ExpiringTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_RENDERER_CLASSES": (
        ["rest_framework.renderers.JSONRenderer", "rest_framework.renderers.BrowsableAPIRenderer"]
        if DEBUG else ["rest_framework.renderers.JSONRenderer"]
    ),
    "EXCEPTION_HANDLER": "config.api_errors.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {"auth_login": "10/hour", "ares_agent_execution": "5/hour"},
}
ARES_API_TOKEN_TTL_HOURS = max(1, int(os.getenv("ARES_API_TOKEN_TTL_HOURS", "8")))
ARES_EMAIL_DELIVERY_ENABLED = os.getenv("ARES_EMAIL_DELIVERY_ENABLED", "false").lower() == "true"
ARES_AGENT_PROVIDER = os.getenv("ARES_AGENT_PROVIDER", "disabled").strip().lower()
ARES_AGENT_MODEL = os.getenv("ARES_AGENT_MODEL", "").strip()
ARES_AGENT_API_KEY = os.getenv("ARES_AGENT_API_KEY", "").strip()
ARES_AGENT_API_BASE_URL = os.getenv("ARES_AGENT_API_BASE_URL", "").strip()
ARES_AGENT_EXTERNAL_PROCESSING_ENABLED = os.getenv("ARES_AGENT_EXTERNAL_PROCESSING_ENABLED", "false").lower() == "true"
ARES_AGENT_TIMEOUT_SECONDS = max(5, min(60, int(os.getenv("ARES_AGENT_TIMEOUT_SECONDS", "30"))))
ARES_AGENT_MAX_TOOL_CALLS = max(1, min(8, int(os.getenv("ARES_AGENT_MAX_TOOL_CALLS", "4"))))
ARES_AGENT_MAX_OUTPUT_TOKENS = max(128, min(4000, int(os.getenv("ARES_AGENT_MAX_OUTPUT_TOKENS", "1200"))))
ARES_ACTION_EXECUTION_ENABLED = os.getenv("ARES_ACTION_EXECUTION_ENABLED", "false").lower() == "true"
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "false").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv("ARES_NOTIFICATION_FROM_EMAIL", "")

# Approximate point-to-hazard exposure distances in km. These are configurable
# policy defaults; they are not claims about a disaster's actual footprint.
_default_exposure_thresholds = {
    "default": {"low": 25, "medium": 50, "high": 100, "critical": 250},
    "earthquake": {"low": 50, "medium": 100, "high": 200, "critical": 400},
    "flood": {"low": 25, "medium": 50, "high": 100, "critical": 200},
    "tropical cyclone": {"low": 50, "medium": 100, "high": 200, "critical": 400},
    "wildfire": {"low": 15, "medium": 30, "high": 60, "critical": 120},
}
_exposure_json = os.getenv("ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM", "").strip()
try:
    ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM = json.loads(_exposure_json) if _exposure_json else _default_exposure_thresholds
    if not isinstance(ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM, dict):
        raise ValueError
    for _kind, _bands in ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM.items():
        if not isinstance(_bands, dict) or any(
            band not in {"low", "medium", "high", "critical"}
            or not isinstance(distance, (int, float)) or isinstance(distance, bool)
            or not math.isfinite(distance) or distance < 0 or distance > 5000
            for band, distance in _bands.items()
        ):
            raise ValueError
except (TypeError, ValueError, OverflowError, json.JSONDecodeError) as exc:
    raise ImproperlyConfigured("ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM must be a JSON object of nonnegative km values by severity.") from exc
