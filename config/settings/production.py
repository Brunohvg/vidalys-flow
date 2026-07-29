from decouple import Csv, config

from config.settings.base import *  # noqa: F403

DEBUG = False
SECRET_KEY = config("SECRET_KEY")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", cast=Csv())
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
DATABASES = {  # noqa: F811
    "default": dj_database_url.config(  # noqa: F405
        default=config("DATABASE_URL"),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Absence is deliberately fail-closed. External effects require an explicit 0.
VIDALYS_DEMO_MODE = config("VIDALYS_DEMO_MODE", default=True, cast=bool)

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
