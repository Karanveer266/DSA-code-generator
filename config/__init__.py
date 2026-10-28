"""Django project configuration package.

Importing the Celery application here ensures the shared task queue is
initialised whenever Django starts, so that ``@shared_task`` decorators are
always bound to the configured app.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
