"""
Celery tasks.

The agentic loop (several LLM calls + many sandboxed executions) can run for
minutes, so it executes inside a Celery worker rather than the request thread.
With ``RUN_TASKS_SYNC=1`` (``CELERY_TASK_ALWAYS_EAGER``) the same task runs
inline, which is convenient for local development without a broker/worker.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from engine.orchestrator import solve_problem
from engine.schemas import Language, SolveRequest, TestCase

from .models import SolveJob

logger = logging.getLogger("engine.tasks")


@shared_task(bind=True, name="api.run_solve_job")
def run_solve_job(self, job_id: str) -> str:
    """Execute the full agentic workflow for one :class:`SolveJob`."""
    try:
        job = SolveJob.objects.get(pk=job_id)
    except SolveJob.DoesNotExist:  # pragma: no cover
        logger.error("SolveJob %s vanished before execution.", job_id)
        return "missing"

    job.status = SolveJob.Status.RUNNING
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id or ""
    job.save(update_fields=["status", "started_at", "celery_task_id", "updated_at"])

    # Mirror orchestrator progress into the DB so clients can poll it live.
    def _progress(message: str) -> None:
        job.progress = (job.progress or []) + [message]
        job.save(update_fields=["progress", "updated_at"])

    try:
        request = SolveRequest(
            problem_statement=job.problem_statement,
            test_cases=[
                TestCase(
                    input=tc.get("input", ""),
                    expected_output=tc.get("expected_output"),
                    source="user",
                )
                for tc in (job.test_cases or [])
            ],
            language=Language.from_str(job.language),
        )

        result = solve_problem(request, progress=_progress)

        job.result = result.to_dict()
        job.status = (
            SolveJob.Status.SUCCEEDED
            if result.success
            else SolveJob.Status.FAILED
        )
    except Exception as exc:  # noqa: BLE001 - record any failure on the job
        logger.exception("SolveJob %s crashed.", job_id)
        job.status = SolveJob.Status.ERROR
        job.error_message = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = timezone.now()
        job.save()

    return job.status
