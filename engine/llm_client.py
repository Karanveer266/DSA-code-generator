"""
LLM client abstraction.

Two backends are provided:

* :class:`AnthropicLLMClient` - talks to the real Claude API via the official
  ``anthropic`` SDK. Uses adaptive thinking + configurable effort, which is the
  recommended configuration for reasoning-heavy coding tasks.
* :class:`MockLLMClient` - a deterministic, offline backend used for tests,
  demos, and CI where no API key (or network) is available. It understands a
  small set of classic problems well enough to exercise the full workflow.

The factory :func:`get_llm_client` picks a backend based on configuration.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .config import EngineConfig, get_config
from .mock_solutions import mock_completion

logger = logging.getLogger("engine.llm")

# Non-streaming default; generous enough for long solutions but under the
# SDK HTTP timeout.
_MAX_TOKENS = 16000


class LLMError(RuntimeError):
    """Raised when the LLM backend fails irrecoverably."""


# ---------------------------------------------------------------------------
# Code extraction helper
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(
    r"```[a-zA-Z0-9_+-]*\s*\n(?P<body>.*?)```",
    re.DOTALL,
)


def extract_code(text: str) -> str:
    """Return raw source code from an LLM response.

    The coder prompts request *raw code only*, but models occasionally wrap
    output in markdown fences anyway. This helper strips fences when present
    and otherwise returns the trimmed text unchanged.
    """
    if not text:
        return ""
    matches = _FENCE_RE.findall(text)
    if matches:
        # Prefer the longest fenced block (usually the full program).
        return max(matches, key=len).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------
class BaseLLMClient:
    """Interface every LLM backend implements."""

    def complete(self, system: str, user: str) -> str:
        """Return the model's text response to a single (system, user) turn."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------
class AnthropicLLMClient(BaseLLMClient):
    """Claude-backed client using the official Anthropic SDK."""

    def __init__(self, config: EngineConfig):
        if not config.anthropic_api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY is not set but LLM_BACKEND='anthropic'. "
                "Set the key or switch LLM_BACKEND=mock."
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "The 'anthropic' package is required for the Anthropic "
                "backend. Install it via requirements.txt."
            ) from exc

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._model = config.llm_model
        self._effort = config.llm_effort

    def complete(self, system: str, user: str) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                # Adaptive thinking is the recommended mode for reasoning-heavy
                # coding tasks on current Claude models.
                thinking={"type": "adaptive"},
                output_config={"effort": self._effort},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.APIError as exc:  # pragma: no cover - network
            raise LLMError(f"Anthropic API error: {exc}") from exc

        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            raise LLMError(f"Model refused the request: {detail}")

        # Concatenate all text blocks (thinking blocks are skipped).
        parts = [b.text for b in response.content if b.type == "text"]
        text = "\n".join(parts).strip()
        if not text:
            raise LLMError("Model returned an empty response.")
        return text


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------
class MockLLMClient(BaseLLMClient):
    """Offline, deterministic backend for demos and tests.

    It inspects the prompts to decide which agent is calling and returns a
    canned-but-functional response. See :mod:`engine.mock_solutions`.
    """

    def complete(self, system: str, user: str) -> str:
        return mock_completion(system, user)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_llm_client(config: Optional[EngineConfig] = None) -> BaseLLMClient:
    """Return the configured LLM client.

    Falls back to the mock backend automatically when the Anthropic backend is
    requested but no API key is configured, so the project remains runnable
    out-of-the-box.
    """
    cfg = config or get_config()
    backend = (cfg.llm_backend or "anthropic").lower()

    if backend == "mock":
        logger.info("Using MOCK LLM backend.")
        return MockLLMClient()

    if backend == "anthropic":
        if not cfg.anthropic_api_key:
            logger.warning(
                "LLM_BACKEND='anthropic' but no API key set - "
                "falling back to MOCK backend."
            )
            return MockLLMClient()
        logger.info("Using Anthropic LLM backend (model=%s).", cfg.llm_model)
        return AnthropicLLMClient(cfg)

    raise LLMError(f"Unknown LLM_BACKEND: {cfg.llm_backend!r}")
