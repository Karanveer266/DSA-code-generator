"""
Database models.

A :class:`SolveJob` captures one problem-solving request and its lifecycle. The
heavy agentic work happens in a Celery task; the job row is the durable record
clients poll for status and results.
"""

from __future__ import annotations

import uuid

from django.db import models


class SolveJob(models.Model):
    """A single problem-solving job."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        ERROR = "error", "Error"  # infrastructure/unexpected failure

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )

    # ---- input ----
    problem_statement = models.TextField()
    test_cases = models.JSONField(default=list, blank=True)
    language = models.CharField(max_length=16, default="cpp")

    # ---- lifecycle ----
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    celery_task_id = models.CharField(max_length=255, blank=True, default="")

    # ---- output ----
    result = models.JSONField(null=True, blank=True)
    # Lightweight progress log mirrored from the orchestrator for live polling.
    progress = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True, default="")

    # ---- timestamps ----
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin convenience
        return f"SolveJob({self.id}, {self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            self.Status.SUCCEEDED,
            self.Status.FAILED,
            self.Status.ERROR,
        }
