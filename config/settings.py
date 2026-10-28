"""
Django settings for the Agentic AI Workflow Engine.

All environment-specific values are read from environment variables (optionally
populated from a ``.env`` file) so the same image can run in dev and prod.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env file if present (no-op in container when env is injected).
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean-ish environment variable."""
    return os.environ.get(name, str(int(default))).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, falling back on errors."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Core Django configuration
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me"
)
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # Local
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres"):
    # Minimal URL parser to avoid an extra dependency (dj-database-url).
    from urllib.parse import urlparse

    parsed = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Password validation / i18n
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("API_ANON_THROTTLE", "60/min"),
    },
}

# CORS - open by default for the demo; lock this down in production.
CORS_ALLOW_ALL_ORIGINS = _env_bool("CORS_ALLOW_ALL_ORIGINS", True)

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = _env_int("CELERY_TASK_TIME_LIMIT", 600)
# When true, .delay() executes inline and no worker/broker is required.
RUN_TASKS_SYNC = _env_bool("RUN_TASKS_SYNC", False)
CELERY_TASK_ALWAYS_EAGER = RUN_TASKS_SYNC
CELERY_TASK_EAGER_PROPAGATES = True

# ---------------------------------------------------------------------------
# Engine configuration (LLM + sandbox). Consumed by the `engine` package.
# ---------------------------------------------------------------------------
ENGINE = {
    # LLM
    "LLM_BACKEND": os.environ.get("LLM_BACKEND", "anthropic"),
    "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
    "LLM_MODEL": os.environ.get("LLM_MODEL", "claude-opus-5-5"),
    "LLM_EFFORT": os.environ.get("LLM_EFFORT", "high"),
    # Agentic loop
    "MAX_ATTEMPTS": _env_int("MAX_ATTEMPTS", 3),
    "GENERATED_TESTCASE_COUNT": _env_int("GENERATED_TESTCASE_COUNT", 12),
    # Sandbox
    "SANDBOX_BACKEND": os.environ.get("SANDBOX_BACKEND", "docker"),
    "SANDBOX_CPP_IMAGE": os.environ.get("SANDBOX_CPP_IMAGE", "gcc:13"),
    "SANDBOX_PYTHON_IMAGE": os.environ.get(
        "SANDBOX_PYTHON_IMAGE", "python:3.11-slim"
    ),
    "SANDBOX_MEMORY_LIMIT": os.environ.get("SANDBOX_MEMORY_LIMIT", "256m"),
    "SANDBOX_CPU_TIMEOUT": _env_int("SANDBOX_CPU_TIMEOUT", 3),
    "SANDBOX_COMPILE_TIMEOUT": _env_int("SANDBOX_COMPILE_TIMEOUT", 15),
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "engine": {
            "handlers": ["console"],
            "level": os.environ.get("ENGINE_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
