"""
Management command: run a solve directly from the command line.

Useful for local testing without the HTTP layer or a running worker, e.g.::

    python manage.py solve --problem "Sum of two integers" \\
        --language python --testcase "2 3" "5"

Or load a problem from a JSON file matching the API payload::

    python manage.py solve --file examples/two_sum.json
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from engine.orchestrator import solve_problem
from engine.schemas import Language, SolveRequest, TestCase


class Command(BaseCommand):
    help = "Run the agentic solve workflow from the command line."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--problem", type=str, help="Problem statement.")
        parser.add_argument(
            "--language",
            type=str,
            default="cpp",
            help="Target language: cpp | python.",
        )
        parser.add_argument(
            "--testcase",
            nargs=2,
            action="append",
            metavar=("INPUT", "EXPECTED"),
            help="A test case: input and expected output. Repeatable.",
        )
        parser.add_argument(
            "--file",
            type=str,
            help="Path to a JSON file with keys problem_statement, "
            "test_cases, language.",
        )

    def handle(self, *args, **options) -> None:
        if options.get("file"):
            with open(options["file"], encoding="utf-8") as fh:
                payload = json.load(fh)
            problem = payload["problem_statement"]
            language = payload.get("language", "cpp")
            test_cases = [
                TestCase(
                    input=tc["input"],
                    expected_output=tc.get("expected_output"),
                    source="user",
                )
                for tc in payload.get("test_cases", [])
            ]
        else:
            problem = options.get("problem")
            if not problem:
                raise CommandError("Provide --problem or --file.")
            language = options["language"]
            test_cases = [
                TestCase(input=inp, expected_output=exp, source="user")
                for inp, exp in (options.get("testcase") or [])
            ]

        request = SolveRequest(
            problem_statement=problem,
            test_cases=test_cases,
            language=Language.from_str(language),
        )

        self.stdout.write(self.style.NOTICE("Running agentic solve...\n"))
        result = solve_problem(
            request, progress=lambda m: self.stdout.write(f"  • {m}")
        )

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(
            self.style.SUCCESS("SUCCESS") if result.success
            else self.style.ERROR("FAILED")
        )
        self.stdout.write(f"Status : {result.status}")
        self.stdout.write(f"Message: {result.message}")
        self.stdout.write(f"Attempts used: {len(result.attempts)}")
        self.stdout.write("=" * 60)
        self.stdout.write("\nFinal solution:\n")
        self.stdout.write(result.final_code or "(none)")
