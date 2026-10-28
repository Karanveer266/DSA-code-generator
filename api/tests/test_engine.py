"""
Unit tests for the engine, exercised end-to-end with the offline mock LLM and
the local subprocess sandbox. These run without Docker or an API key.

They are skipped automatically if a Python 3 interpreter is somehow missing.
"""

from __future__ import annotations

import shutil
import unittest

from engine.config import EngineConfig
from engine.llm_client import extract_code, get_llm_client
from engine.mock_solutions import mock_completion
from engine.orchestrator import Orchestrator, _normalize_output, solve_problem
from engine.schemas import Language, SolveRequest, TestCase

_HAS_PY = shutil.which("python3") is not None


def _mock_local_config() -> EngineConfig:
    """Config that uses the offline mock LLM and the local sandbox."""
    return EngineConfig(
        llm_backend="mock",
        sandbox_backend="local",
        max_attempts=3,
        generated_testcase_count=6,
    )


class ExtractCodeTests(unittest.TestCase):
    def test_strips_fences(self):
        text = "Here you go:\n```python\nprint(1)\n```\nDone."
        self.assertEqual(extract_code(text), "print(1)")

    def test_plain_code_passthrough(self):
        self.assertEqual(extract_code("print(2)"), "print(2)")

    def test_picks_longest_block(self):
        text = "```py\nshort\n```\n```py\nmuch longer block here\n```"
        self.assertEqual(extract_code(text), "much longer block here")


class NormalizeOutputTests(unittest.TestCase):
    def test_trailing_whitespace_and_blank_lines(self):
        self.assertEqual(_normalize_output("5  \n\n\n"), "5")

    def test_crlf(self):
        self.assertEqual(_normalize_output("a\r\nb\r\n"), "a\nb")


class MockLLMTests(unittest.TestCase):
    def test_test_designer_returns_json(self):
        client = get_llm_client(_mock_local_config())
        from engine import prompts

        out = client.complete(
            prompts.TEST_DESIGNER_SYSTEM,
            prompts.test_designer_user("Sum of two integers", 5),
        )
        self.assertIn("test_cases", out)

    def test_brute_force_returns_code(self):
        from engine import prompts

        out = mock_completion(
            prompts.brute_force_system(Language.PYTHON),
            prompts.brute_force_user("Sum of two integers"),
        )
        self.assertIn("def main", out)


@unittest.skipUnless(_HAS_PY, "python3 interpreter required for local sandbox")
class OrchestratorPythonTests(unittest.TestCase):
    def test_solves_sum_of_two_integers(self):
        request = SolveRequest(
            problem_statement="Read two integers a and b and print a + b.",
            test_cases=[
                TestCase(input="2 3\n", expected_output="5", source="user"),
                TestCase(input="10 20\n", expected_output="30", source="user"),
            ],
            language=Language.PYTHON,
        )
        result = solve_problem(request, config=_mock_local_config())
        self.assertTrue(result.success, msg=result.message)
        self.assertEqual(result.status, "solved")
        self.assertIn("def main", result.final_code)

    def test_generates_extra_cases(self):
        request = SolveRequest(
            problem_statement="Maximum subarray sum (Kadane).",
            test_cases=[],
            language=Language.PYTHON,
        )
        result = solve_problem(request, config=_mock_local_config())
        # Mock generates array inputs; brute force establishes ground truth.
        self.assertGreater(len(result.all_test_cases), 0)
        self.assertTrue(result.success, msg=result.message)


@unittest.skipUnless(shutil.which("g++"), "g++ required for C++ local sandbox")
class OrchestratorCppTests(unittest.TestCase):
    def test_solves_sum_cpp(self):
        request = SolveRequest(
            problem_statement="Read two integers a and b and print a + b.",
            test_cases=[
                TestCase(input="7 8\n", expected_output="15", source="user"),
            ],
            language=Language.CPP,
        )
        result = solve_problem(request, config=_mock_local_config())
        self.assertTrue(result.success, msg=result.message)


if __name__ == "__main__":
    unittest.main()
