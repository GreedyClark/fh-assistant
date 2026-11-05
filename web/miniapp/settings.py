import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import Settings as BotSettings  # noqa: E402

BOT = BotSettings(_env_file=ROOT_DIR / ".env")
BOT_DB_PATH = BOT.db_path if BOT.db_path.is_absolute() else ROOT_DIR / BOT.db_path
PROFILE_PATH = BOT.profile_path if BOT.profile_path.is_absolute() else ROOT_DIR / BOT.profile_path

SECRET_KEY = hashlib.sha256(("django:" + BOT.bot_token.get_secret_value()).encode()).hexdigest()
DEBUG = os.environ.get("DJANGO_DEBUG") == "1"

MINIAPP_HOST = urlparse(BOT.miniapp_url).hostname if BOT.miniapp_url else None
ALLOWED_HOSTS = ["127.0.0.1", "localhost"] + ([MINIAPP_HOST] if MINIAPP_HOST else [])

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "miniapp.urls"
WSGI_APPLICATION = "miniapp.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BOT_DB_PATH,
        "OPTIONS": {"timeout": 20, "init_command": "PRAGMA journal_mode=WAL;"},
    }
}

LANGUAGE_CODE = "uk"
TIME_ZONE = "Europe/Kyiv"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
