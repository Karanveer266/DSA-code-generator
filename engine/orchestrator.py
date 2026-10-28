"""
The orchestrator - the agentic control loop that ties the workflow together.

Workflow
--------
1. **Test Designer** invents extra inputs / edge cases, merged with the user's.
2. **Brute-Force Coder** writes a simple, correct reference solution. We run it
   on every test input to establish the GROUND TRUTH output for each case.
   (Cases where the brute force itself fails are discarded as unusable.)
3. **Optimal Coder** writes the efficient solution.
4. The optimal solution is executed on every test case and its output compared
   against the brute-force ground truth.
5. If any case fails (compile error, runtime error, timeout, or wrong answer),
   the **Critic** is given the concrete failure evidence and asked to rewrite
   the solution. Steps 4-5 repeat up to ``MAX_ATTEMPTS`` times.

The brute force is the oracle: because it is simple we trust its answers, so we
never need the user to provide expected outputs for the generated cases.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .agents import (
    BruteForceCoderAgent,
    CriticAgent,
    OptimalCoderAgent,
    TestDesignerAgent,
)
from .config import EngineConfig, get_config
from .llm_client import BaseLLMClient, get_llm_client
from .sandbox import BaseSandbox, CompiledProgram, get_sandbox
from .schemas import (
    AttemptResult,
    ExecutionResult,
    ExecutionStatus,
    Language,
    SolveRequest,
    SolveResult,
    TestCase,
    TestCaseResult,
)

logger = logging.getLogger("engine.orchestrator")

# A callback invoked with human-readable progress strings. Useful for
# streaming status to a task-result record.
ProgressCallback = Callable[[str], None]


def _normalize_output(text: str) -> str:
    """Normalise program output for comparison.

    Trailing whitespace on each line and trailing blank lines are irrelevant in
    virtually all competitive-programming judges, so we strip them to avoid
    false "wrong answer" verdicts caused by cosmetic differences.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    lines = [ln.rstrip() for ln in lines]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


class Orchestrator:
    """Runs the full multi-agent solve for one problem."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        llm: Optional[BaseLLMClient] = None,
        sandbox: Optional[BaseSandbox] = None,
        progress: Optional[ProgressCallback] = None,
    ):
        self.config = config or get_config()
        self._llm = llm or get_llm_client(self.config)
        self._sandbox = sandbox  # created lazily so LLM-only tests need no Docker
        self._progress = progress or (lambda _msg: None)

        self.test_designer = TestDesignerAgent(self._llm)
        self.brute_coder = BruteForceCoderAgent(self._llm)
        self.optimal_coder = OptimalCoderAgent(self._llm)
        self.critic = CriticAgent(self._llm)

        self._log: list[str] = []

    # ---- logging helper ---------------------------------------------------
    def _emit(self, message: str) -> None:
        logger.info(message)
        self._log.append(message)
        try:
            self._progress(message)
        except Exception:  # pragma: no cover - never let UI callbacks break run
            logger.exception("Progress callback raised.")

    @property
    def sandbox(self) -> BaseSandbox:
        if self._sandbox is None:
            self._sandbox = get_sandbox(self.config)
        return self._sandbox

    # ---- main entry point -------------------------------------------------
    def solve(self, request: SolveRequest) -> SolveResult:
        language = request.language
        result = SolveResult(success=False, language=language)

        self._emit(
            f"Starting solve: language={language.value}, "
            f"{len(request.test_cases)} user test case(s)."
        )

        # --- Step 1: design extra test cases -------------------------------
        try:
            generated = self.test_designer.generate(
                request.problem_statement,
                self.config.generated_testcase_count,
            )
        except Exception as exc:  # LLM hiccup should not abort the whole run
            self._emit(f"Test designer failed ({exc}); continuing with user cases.")
            generated = []
        self._emit(f"Generated {len(generated)} additional test case(s).")

        all_inputs: list[TestCase] = list(request.test_cases) + generated

        if not all_inputs:
            result.status = "no_test_cases"
            result.message = (
                "No test cases available (none provided and none generated)."
            )
            result.log = self._log
            return result

        # --- Step 2 & 3: write brute force and optimal (two agents) --------
        self._emit("Brute-force coder writing reference solution...")
        brute_code = self.brute_coder.write(request.problem_statement, language)
        result.brute_force_code = brute_code

        self._emit("Optimal coder writing candidate solution...")
        optimal_code = self.optimal_coder.write(
            request.problem_statement, language
        )

        # --- Establish ground truth via the brute force --------------------
        ground_truth, usable_cases = self._compute_ground_truth(
            brute_code, all_inputs, language
        )
        result.all_test_cases = usable_cases

        if not usable_cases:
            result.status = "brute_force_unusable"
            result.message = (
                "The brute-force reference solution failed on all test cases, "
                "so no ground truth could be established."
            )
            result.final_code = optimal_code
            result.log = self._log
            return result

        self._emit(
            f"Established ground truth on {len(usable_cases)} usable case(s)."
        )

        # --- Steps 4 & 5: verify + self-correct loop -----------------------
        current_code = optimal_code
        max_attempts = max(1, self.config.max_attempts)

        for attempt_no in range(1, max_attempts + 1):
            self._emit(f"Verification attempt {attempt_no}/{max_attempts}...")
            attempt = self._verify_attempt(
                attempt_no, current_code, usable_cases, ground_truth, language
            )
            result.attempts.append(attempt)

            if attempt.passed:
                self._emit(f"Attempt {attempt_no} PASSED all test cases. ✅")
                result.success = True
                result.status = "solved"
                result.message = (
                    f"Optimal solution verified against brute force on "
                    f"{len(usable_cases)} test case(s) in {attempt_no} "
                    f"attempt(s)."
                )
                result.final_code = current_code
                result.log = self._log
                return result

            self._emit(
                f"Attempt {attempt_no} FAILED: {attempt.failure_summary.splitlines()[0]}"
            )

            # If attempts remain, invoke the critic to repair the solution.
            if attempt_no < max_attempts:
                self._emit("Critic analysing failure and rewriting solution...")
                try:
                    current_code = self.critic.fix(
                        request.problem_statement,
                        current_code,
                        attempt.failure_summary,
                        language,
                    )
                except Exception as exc:  # pragma: no cover
                    self._emit(f"Critic failed to produce a fix: {exc}")
                    break

        # Exhausted attempts without success.
        result.status = "max_attempts_exhausted"
        result.message = (
            f"Could not verify an optimal solution within {max_attempts} "
            f"attempt(s)."
        )
        result.final_code = current_code
        result.log = self._log
        return result

    # ---- helpers ----------------------------------------------------------
    def _compute_ground_truth(
        self,
        brute_code: str,
        inputs: list[TestCase],
        language: Language,
    ) -> tuple[dict[int, str], list[TestCase]]:
        """Run the brute force on every input to establish expected outputs.

        For user cases that already carry an ``expected_output`` we trust the
        user's value (and also sanity-check the brute force against it). For
        generated cases, the brute-force output IS the ground truth.

        Returns a mapping ``{case_index: expected_output}`` and the list of
        usable test cases (those for which a ground truth exists).
        """
        self._emit("Running brute force to compute ground-truth outputs...")
        program = self.sandbox.compile(brute_code, language)
        if not program.compiled_ok:
            self._emit(
                "Brute-force solution failed to compile:\n"
                + program.compile_result.stderr
            )
            program.cleanup()
            return {}, []

        ground_truth: dict[int, str] = {}
        usable: list[TestCase] = []
        try:
            for case in inputs:
                exec_res = program.run(case.input)
                idx = len(usable)

                if not exec_res.ok:
                    # Brute force broke on this input - we cannot trust it.
                    self._emit(
                        f"  - brute force failed on a {case.source} case "
                        f"({exec_res.status.value}); discarding it."
                    )
                    continue

                brute_out = _normalize_output(exec_res.stdout)

                if case.source == "user" and case.expected_output is not None:
                    user_expected = _normalize_output(case.expected_output)
                    if brute_out != user_expected:
                        # Brute force disagrees with the user's stated answer.
                        # Trust the user and warn - but keep the user's answer.
                        self._emit(
                            "  - warning: brute force disagrees with a "
                            "user-provided expected output; trusting the user."
                        )
                    expected = user_expected
                else:
                    expected = brute_out

                stored = TestCase(
                    input=case.input,
                    expected_output=expected,
                    source=case.source,
                )
                ground_truth[idx] = expected
                usable.append(stored)
        finally:
            program.cleanup()

        return ground_truth, usable

    def _verify_attempt(
        self,
        attempt_no: int,
        code: str,
        cases: list[TestCase],
        ground_truth: dict[int, str],
        language: Language,
    ) -> AttemptResult:
        """Compile + run the optimal code against all cases, collect results."""
        attempt = AttemptResult(attempt=attempt_no, code=code, passed=False)

        program = self.sandbox.compile(code, language)
        if not program.compiled_ok:
            attempt.failure_summary = (
                "COMPILATION ERROR when building the optimal solution:\n"
                + (program.compile_result.stderr or "(no compiler output)")
            )
            program.cleanup()
            return attempt

        try:
            failures: list[str] = []
            for idx, case in enumerate(cases):
                exec_res = program.run(case.input)
                expected = ground_truth.get(idx, case.expected_output or "")
                actual = _normalize_output(exec_res.stdout)
                passed = exec_res.ok and actual == expected

                attempt.test_results.append(
                    TestCaseResult(
                        index=idx,
                        input=case.input,
                        expected_output=expected,
                        actual_output=actual,
                        passed=passed,
                        status=exec_res.status,
                        stderr=exec_res.stderr,
                        duration_ms=exec_res.duration_ms,
                    )
                )

                if not passed and len(failures) < 3:
                    failures.append(
                        self._describe_failure(idx, case, exec_res, expected, actual)
                    )

            all_passed = all(t.passed for t in attempt.test_results)
            attempt.passed = all_passed
            if not all_passed:
                n_failed = sum(1 for t in attempt.test_results if not t.passed)
                header = (
                    f"{n_failed}/{len(attempt.test_results)} test case(s) "
                    f"failed. Representative failures:\n"
                )
                attempt.failure_summary = header + "\n\n".join(failures)
        finally:
            program.cleanup()

        return attempt

    @staticmethod
    def _describe_failure(
        idx: int,
        case: TestCase,
        exec_res: ExecutionResult,
        expected: str,
        actual: str,
    ) -> str:
        """Build concrete, LLM-friendly failure evidence for the critic."""
        if exec_res.status == ExecutionStatus.TIMEOUT:
            return (
                f"[Case #{idx}] TIME LIMIT EXCEEDED on input:\n{case.input}\n"
                "The solution is too slow - a more efficient algorithm is "
                "required."
            )
        if exec_res.status == ExecutionStatus.MEMORY_EXCEEDED:
            return (
                f"[Case #{idx}] MEMORY LIMIT EXCEEDED on input:\n{case.input}\n"
                "Reduce memory usage / choose a more space-efficient approach."
            )
        if exec_res.status == ExecutionStatus.RUNTIME_ERROR:
            return (
                f"[Case #{idx}] RUNTIME ERROR (exit {exec_res.exit_code}) on "
                f"input:\n{case.input}\nstderr:\n{exec_res.stderr}"
            )
        # Wrong answer.
        return (
            f"[Case #{idx}] WRONG ANSWER on input:\n{case.input}\n"
            f"Expected output:\n{expected}\n"
            f"Your output:\n{actual}"
        )

    def close(self) -> None:
        if self._sandbox is not None:
            self._sandbox.close()


# ---------------------------------------------------------------------------
# Convenience functional entry point
# ---------------------------------------------------------------------------
def solve_problem(
    request: SolveRequest,
    config: Optional[EngineConfig] = None,
    progress: Optional[ProgressCallback] = None,
) -> SolveResult:
    """Solve a single problem end-to-end and return the result.

    This is the main public entry point used by the Celery task and tests.
    """
    orchestrator = Orchestrator(config=config, progress=progress)
    try:
        return orchestrator.solve(request)
    finally:
        orchestrator.close()
