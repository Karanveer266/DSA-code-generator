"""
Thin agent wrappers around the LLM client.

Each function represents one role in the workflow and returns clean,
ready-to-use output (parsed test cases or extracted source code). Keeping the
prompt-plumbing here means :mod:`engine.orchestrator` reads like the high-level
algorithm it implements.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from . import prompts
from .llm_client import BaseLLMClient, extract_code
from .schemas import Language, TestCase

logger = logging.getLogger("engine.agents")


class TestDesignerAgent:
    """Agent 1 - invents additional test inputs and edge cases."""

    def __init__(self, llm: BaseLLMClient):
        self._llm = llm

    def generate(self, problem_statement: str, count: int) -> list[TestCase]:
        system = prompts.TEST_DESIGNER_SYSTEM
        user = prompts.test_designer_user(problem_statement, count)
        raw = self._llm.complete(system, user)
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> list[TestCase]:
        """Parse the designer's JSON, tolerating stray markdown fences."""
        text = raw.strip()
        # Strip code fences if the model added them despite instructions.
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        # Fall back to locating the outermost JSON object.
        if not text.startswith("{"):
            brace = text.find("{")
            if brace != -1:
                text = text[brace:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Test designer returned unparseable JSON; ignoring.")
            return []

        cases: list[TestCase] = []
        for item in data.get("test_cases", []):
            if isinstance(item, dict) and "input" in item:
                cases.append(
                    TestCase(input=str(item["input"]), source="generated")
                )
        logger.info("Test designer produced %d generated cases.", len(cases))
        return cases


class BruteForceCoderAgent:
    """Agent 2 - writes the obviously-correct reference solution."""

    def __init__(self, llm: BaseLLMClient):
        self._llm = llm

    def write(self, problem_statement: str, language: Language) -> str:
        system = prompts.brute_force_system(language)
        user = prompts.brute_force_user(problem_statement)
        return extract_code(self._llm.complete(system, user))


class OptimalCoderAgent:
    """Agent 3 - writes the efficient solution we want to ship."""

    def __init__(self, llm: BaseLLMClient):
        self._llm = llm

    def write(self, problem_statement: str, language: Language) -> str:
        system = prompts.optimal_system(language)
        user = prompts.optimal_user(problem_statement)
        return extract_code(self._llm.complete(system, user))


class CriticAgent:
    """Agent 4 - repairs a failing optimal solution using failure evidence."""

    def __init__(self, llm: BaseLLMClient):
        self._llm = llm

    def fix(
        self,
        problem_statement: str,
        failing_code: str,
        failure_summary: str,
        language: Language,
    ) -> str:
        system = prompts.critic_system(language)
        user = prompts.critic_user(
            problem_statement, failing_code, failure_summary, language
        )
        return extract_code(self._llm.complete(system, user))
