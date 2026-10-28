"""Celery application bootstrap.

The engine runs the agentic loop (several LLM calls + many sandboxed
executions) which can take minutes. Running it inside a Celery task keeps the
HTTP request/response cycle short and avoids client-side timeouts.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("agentic_engine")

# Pull all CELERY_* settings from Django's settings module.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py modules in installed apps.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self) -> str:
    """Trivial task used to confirm the worker is wired up correctly."""
    return f"Celery worker alive. Request: {self.request!r}"
