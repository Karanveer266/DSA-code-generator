"""
API integration tests using Django's test client.

Tasks run eagerly (synchronously) under the test settings, and the engine uses
the offline mock LLM + local sandbox, so these run with no Docker, no broker,
and no API key.
"""

from __future__ import annotations

import shutil

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

_ENGINE_TEST = {
    "LLM_BACKEND": "mock",
    "ANTHROPIC_API_KEY": "",
    "LLM_MODEL": "claude-opus-5-5",
    "LLM_EFFORT": "high",
    "MAX_ATTEMPTS": 3,
    "GENERATED_TESTCASE_COUNT": 4,
    "SANDBOX_BACKEND": "local",
    "SANDBOX_CPP_IMAGE": "gcc:13",
    "SANDBOX_PYTHON_IMAGE": "python:3.11-slim",
    "SANDBOX_MEMORY_LIMIT": "256m",
    "SANDBOX_CPU_TIMEOUT": 3,
    "SANDBOX_COMPILE_TIMEOUT": 15,
}


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    RUN_TASKS_SYNC=True,
    ENGINE=_ENGINE_TEST,
)
class SolveApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_health(self):
        resp = self.client.get("/api/v1/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_validation_requires_problem(self):
        resp = self.client.post("/api/v1/solve/", {"test_cases": []}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("problem_statement", resp.json())

    def test_invalid_language(self):
        resp = self.client.post(
            "/api/v1/solve/",
            {"problem_statement": "x", "language": "rust"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("language", resp.json())

    def test_unknown_job_404(self):
        resp = self.client.get(
            "/api/v1/solve/00000000-0000-0000-0000-000000000000/"
        )
        self.assertEqual(resp.status_code, 404)

    def _skip_if_no_python(self):
        if not shutil.which("python3"):
            self.skipTest("python3 required for local sandbox")

    def test_full_solve_python(self):
        self._skip_if_no_python()
        payload = {
            "problem_statement": "Read two integers a and b and print a + b.",
            "language": "python",
            "test_cases": [
                {"input": "2 3\n", "expected_output": "5"},
                {"input": "100 1\n", "expected_output": "101"},
            ],
        }
        resp = self.client.post("/api/v1/solve/", payload, format="json")
        self.assertEqual(resp.status_code, 202)
        job_id = resp.json()["id"]

        # Eager execution => job is already terminal.
        poll = self.client.get(f"/api/v1/solve/{job_id}/")
        self.assertEqual(poll.status_code, 200)
        body = poll.json()
        self.assertEqual(body["status"], "succeeded", msg=body.get("result"))
        self.assertTrue(body["result"]["success"])
        self.assertIn("def main", body["result"]["final_code"])

    def test_list_jobs(self):
        self._skip_if_no_python()
        self.client.post(
            "/api/v1/solve/",
            {
                "problem_statement": "Read two integers a and b and print a + b.",
                "language": "python",
                "test_cases": [{"input": "1 1\n", "expected_output": "2"}],
            },
            format="json",
        )
        resp = self.client.get("/api/v1/solve/list/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.json()), 1)
