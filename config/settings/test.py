from config.settings.base import *  # noqa: F403

if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":  # noqa: F405
    raise RuntimeError("Os testes da Vidalys Flow exigem PostgreSQL.")

DEBUG = False
VIDALYS_DEMO_MODE = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
