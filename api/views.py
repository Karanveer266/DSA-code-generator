"""
REST API views.

Endpoints
---------
* ``POST /api/v1/solve/``          - submit a problem, returns a job id (202).
* ``GET  /api/v1/solve/<id>/``     - poll a job's status and result.
* ``GET  /api/v1/solve/``          - list recent jobs.
* ``GET  /api/v1/health/``         - liveness/readiness probe.

Submitting a job enqueues a Celery task so the HTTP request returns immediately
and never blocks on the (potentially minutes-long) agentic loop.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from engine.config import get_config

from .models import SolveJob
from .serializers import (
    SolveJobSerializer,
    SolveJobSummarySerializer,
    SolveRequestSerializer,
)
from .tasks import run_solve_job

logger = logging.getLogger("engine.views")


@api_view(["POST"])
def create_solve_job(request: Request) -> Response:
    """Validate the payload, persist a job, and enqueue the worker task."""
    serializer = SolveRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    job = SolveJob.objects.create(
        problem_statement=data["problem_statement"],
        test_cases=data.get("test_cases", []),
        language=data["language"],
    )

    # Kick off the asynchronous agentic workflow.
    run_solve_job.delay(str(job.id))

    body = SolveJobSerializer(job).data
    body["poll_url"] = request.build_absolute_uri(f"{job.id}/")
    return Response(body, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
def get_solve_job(request: Request, job_id: str) -> Response:
    """Return the current state (and result, if ready) of a job."""
    try:
        job = SolveJob.objects.get(pk=job_id)
    except SolveJob.DoesNotExist:
        return Response(
            {"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND
        )
    except (ValueError, TypeError):
        return Response(
            {"detail": "Invalid job id."}, status=status.HTTP_400_BAD_REQUEST
        )
    return Response(SolveJobSerializer(job).data)


@api_view(["GET"])
def list_solve_jobs(request: Request) -> Response:
    """List recent jobs (most recent first, capped)."""
    try:
        limit = min(int(request.query_params.get("limit", 25)), 100)
    except (TypeError, ValueError):
        limit = 25
    jobs = SolveJob.objects.all()[:limit]
    return Response(SolveJobSummarySerializer(jobs, many=True).data)


@api_view(["GET"])
def health(request: Request) -> Response:
    """Lightweight health check reporting the active engine configuration."""
    cfg = get_config()
    return Response(
        {
            "status": "ok",
            "engine": {
                "llm_backend": cfg.llm_backend,
                "llm_model": cfg.llm_model,
                "sandbox_backend": cfg.sandbox_backend,
                "max_attempts": cfg.max_attempts,
            },
        }
    )
