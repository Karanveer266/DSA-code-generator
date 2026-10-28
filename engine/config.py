"""
Engine configuration loader.

The engine reads its settings from Django's ``settings.ENGINE`` dict when it is
running inside the Django process, but falls back to environment variables so
it can be exercised from a plain Python shell or unit tests without Django.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    """Immutable snapshot of all engine tunables."""

    # ---- LLM ----
    llm_backend: str = "anthropic"
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "high"

    # ---- Agentic loop ----
    max_attempts: int = 3
    generated_testcase_count: int = 12

    # ---- Sandbox ----
    sandbox_backend: str = "docker"
    sandbox_cpp_image: str = "gcc:13"
    sandbox_python_image: str = "python:3.11-slim"
    sandbox_memory_limit: str = "256m"
    sandbox_cpu_timeout: int = 3
    sandbox_compile_timeout: int = 15


def _from_env() -> EngineConfig:
    """Build config purely from environment variables (Django-free path)."""

    def _int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except (TypeError, ValueError):
            return default

    return EngineConfig(
        llm_backend=os.environ.get("LLM_BACKEND", "anthropic"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", "claude-opus-5-5"),
        llm_effort=os.environ.get("LLM_EFFORT", "high"),
        max_attempts=_int("MAX_ATTEMPTS", 3),
        generated_testcase_count=_int("GENERATED_TESTCASE_COUNT", 12),
        sandbox_backend=os.environ.get("SANDBOX_BACKEND", "docker"),
        sandbox_cpp_image=os.environ.get("SANDBOX_CPP_IMAGE", "gcc:13"),
        sandbox_python_image=os.environ.get(
            "SANDBOX_PYTHON_IMAGE", "python:3.11-slim"
        ),
        sandbox_memory_limit=os.environ.get("SANDBOX_MEMORY_LIMIT", "256m"),
        sandbox_cpu_timeout=_int("SANDBOX_CPU_TIMEOUT", 3),
        sandbox_compile_timeout=_int("SANDBOX_COMPILE_TIMEOUT", 15),
    )


def get_config() -> EngineConfig:
    """Return the active :class:`EngineConfig`.

    Prefers Django settings when available; otherwise reads the environment.
    """
    try:
        from django.conf import settings

        if settings.configured and hasattr(settings, "ENGINE"):
            e = settings.ENGINE
            return EngineConfig(
                llm_backend=e.get("LLM_BACKEND", "anthropic"),
                anthropic_api_key=e.get("ANTHROPIC_API_KEY", ""),
                llm_model=e.get("LLM_MODEL", "claude-opus-5-5"),
                llm_effort=e.get("LLM_EFFORT", "high"),
                max_attempts=int(e.get("MAX_ATTEMPTS", 3)),
                generated_testcase_count=int(
                    e.get("GENERATED_TESTCASE_COUNT", 12)
                ),
                sandbox_backend=e.get("SANDBOX_BACKEND", "docker"),
                sandbox_cpp_image=e.get("SANDBOX_CPP_IMAGE", "gcc:13"),
                sandbox_python_image=e.get(
                    "SANDBOX_PYTHON_IMAGE", "python:3.11-slim"
                ),
                sandbox_memory_limit=e.get("SANDBOX_MEMORY_LIMIT", "256m"),
                sandbox_cpu_timeout=int(e.get("SANDBOX_CPU_TIMEOUT", 3)),
                sandbox_compile_timeout=int(
                    e.get("SANDBOX_COMPILE_TIMEOUT", 15)
                ),
            )
    except Exception:  # pragma: no cover - Django not installed/configured
        pass

    return _from_env()
