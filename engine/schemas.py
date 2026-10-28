"""
Typed data structures shared across the engine.

Using plain ``dataclasses`` keeps the engine framework-agnostic: it has no
dependency on Django or DRF and can be unit-tested or reused standalone.
Every dataclass exposes :meth:`to_dict` so results serialise cleanly to JSON
for the REST API and the database.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


class Language(str, enum.Enum):
    """Target languages the coder agents may emit."""

    CPP = "cpp"
    PYTHON = "python"

    @classmethod
    def from_str(cls, value: str) -> "Language":
        """Normalise a free-form language string to a :class:`Language`."""
        normalized = (value or "").strip().lower()
        aliases = {
            "c++": cls.CPP,
            "cpp": cls.CPP,
            "cxx": cls.CPP,
            "cc": cls.CPP,
            "py": cls.PYTHON,
            "python": cls.PYTHON,
            "python3": cls.PYTHON,
        }
        if normalized not in aliases:
            raise ValueError(f"Unsupported language: {value!r}")
        return aliases[normalized]


class ExecutionStatus(str, enum.Enum):
    """Outcome categories for a single sandbox run."""

    SUCCESS = "success"  # exit code 0, produced output
    COMPILE_ERROR = "compile_error"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    MEMORY_EXCEEDED = "memory_exceeded"
    INTERNAL_ERROR = "internal_error"  # sandbox infrastructure failure


@dataclass
class TestCase:
    """A single input/expected-output pair.

    ``expected_output`` is optional because the test-generator agent produces
    inputs for which the ground truth is computed later by the brute-force
    solution.
    """

    input: str
    expected_output: Optional[str] = None
    # Where the case came from: "user" or "generated".
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResult:
    """Result of running a program against one input in the sandbox."""

    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class TestCaseResult:
    """Pass/fail outcome of the optimal solution on a single test case."""

    index: int
    input: str
    expected_output: str
    actual_output: str
    passed: bool
    status: ExecutionStatus
    stderr: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class AttemptResult:
    """Everything that happened during a single attempt of the optimal coder."""

    attempt: int
    code: str
    passed: bool
    test_results: list[TestCaseResult] = field(default_factory=list)
    # Human-readable summary of why the attempt failed (fed to the critic).
    failure_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "code": self.code,
            "passed": self.passed,
            "test_results": [t.to_dict() for t in self.test_results],
            "failure_summary": self.failure_summary,
        }


@dataclass
class SolveRequest:
    """Normalised input to the orchestrator."""

    problem_statement: str
    test_cases: list[TestCase] = field(default_factory=list)
    language: Language = Language.CPP

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_statement": self.problem_statement,
            "test_cases": [t.to_dict() for t in self.test_cases],
            "language": self.language.value,
        }


@dataclass
class SolveResult:
    """Final result returned by the orchestrator."""

    success: bool
    language: Language
    final_code: str = ""
    brute_force_code: str = ""
    attempts: list[AttemptResult] = field(default_factory=list)
    all_test_cases: list[TestCase] = field(default_factory=list)
    # Short machine-readable status, e.g. "solved", "max_attempts_exhausted".
    status: str = ""
    message: str = ""
    # Diagnostic timeline of the run (strings), surfaced to the API caller.
    log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "language": self.language.value,
            "final_code": self.final_code,
            "brute_force_code": self.brute_force_code,
            "attempts": [a.to_dict() for a in self.attempts],
            "all_test_cases": [t.to_dict() for t in self.all_test_cases],
            "attempts_used": len(self.attempts),
            "log": self.log,
        }
