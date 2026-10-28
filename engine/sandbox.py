"""
Secure sandboxed execution of untrusted, LLM-generated code.

Two backends implement the same :class:`BaseSandbox` interface:

* :class:`DockerSandbox` (production, default) - spins up an **ephemeral**
  container per program with aggressive security constraints:
    - ``network_disabled=True`` (``--network none``): no outbound network.
    - strict memory limit (default 256 MB) and swap pinned to the same value.
    - CPU/wall-clock timeout (default 3 s) enforced by killing the container.
    - read-only root filesystem; code mounted read-only; a small writable
      ``tmpfs`` for scratch space.
    - dropped Linux capabilities and ``no-new-privileges``.
    - a bounded PID limit to prevent fork bombs.
  The container is always force-removed afterwards.

* :class:`LocalSandbox` (development only) - runs code in a subprocess with a
  wall-clock timeout. It is **NOT secure** and exists purely so the engine can
  be demoed on machines without Docker. It refuses to run unless explicitly
  selected via ``SANDBOX_BACKEND=local``.

The design uses the *sibling container* pattern: the Django container talks to
the host Docker daemon (socket mounted via docker-compose) and launches sandbox
containers as siblings, not children. Temporary code directories are created on
a host path shared with the daemon.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Optional

from .config import EngineConfig, get_config
from .schemas import ExecutionResult, ExecutionStatus, Language

logger = logging.getLogger("engine.sandbox")

# Filenames used inside the sandbox working directory.
_CPP_SRC = "solution.cpp"
_CPP_BIN = "solution"
_PY_SRC = "solution.py"

# Caps on captured output to avoid memory blowups from pathological programs.
_MAX_OUTPUT_BYTES = 1_000_000  # 1 MB of stdout/stderr retained


class SandboxError(RuntimeError):
    """Raised on sandbox infrastructure failures (not program errors)."""


def _truncate(text: str, limit: int = _MAX_OUTPUT_BYTES) -> str:
    if len(text) > limit:
        return text[:limit] + "\n...[output truncated]..."
    return text


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------
class BaseSandbox:
    """Common interface for all sandbox backends."""

    def __init__(self, config: EngineConfig):
        self.config = config

    def compile(self, code: str, language: Language) -> "CompiledProgram":
        """Compile (if needed) and return a reusable handle.

        Raises nothing for user-code compile errors - those are reported via
        the returned program's ``compile_result``.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Release any backend resources."""


class CompiledProgram:
    """Handle to a compiled program that can be run against many inputs."""

    def __init__(
        self,
        sandbox: BaseSandbox,
        language: Language,
        workdir: str,
        compile_result: ExecutionResult,
    ):
        self.sandbox = sandbox
        self.language = language
        self.workdir = workdir
        self.compile_result = compile_result

    @property
    def compiled_ok(self) -> bool:
        return self.compile_result.ok

    def run(self, stdin: str) -> ExecutionResult:
        """Run the compiled program against ``stdin``."""
        if not self.compiled_ok:
            return self.compile_result
        return self.sandbox._run(self, stdin)  # noqa: SLF001

    def cleanup(self) -> None:
        """Remove the temporary working directory."""
        shutil.rmtree(self.workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Docker backend
# ---------------------------------------------------------------------------
class DockerSandbox(BaseSandbox):
    """Ephemeral-container sandbox backed by the Docker Engine SDK."""

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        try:
            import docker
            from docker.errors import DockerException
        except ImportError as exc:  # pragma: no cover
            raise SandboxError(
                "The 'docker' SDK is required for the Docker sandbox."
            ) from exc

        self._docker = docker
        self._DockerException = DockerException
        try:
            self._client = docker.from_env()
            self._client.ping()
        except DockerException as exc:
            raise SandboxError(
                "Cannot reach the Docker daemon. Ensure the docker socket is "
                "mounted into this container (see docker-compose.yml) and that "
                "Docker is running. Original error: " + str(exc)
            ) from exc

        # Directory on a host-visible path where sandbox code dirs are created.
        # Must be bind-mountable by the daemon; defaults to the system temp dir.
        self._host_tmp_root = os.environ.get("SANDBOX_TMP_ROOT", tempfile.gettempdir())

    # ---- security-hardened container runner -------------------------------
    def _run_container(
        self,
        image: str,
        command: list[str],
        workdir_host: str,
        timeout: int,
        read_only_code: bool = True,
    ) -> ExecutionResult:
        """Run a single ephemeral, locked-down container.

        The container mounts ``workdir_host`` at ``/sandbox`` and runs
        ``command`` there. It is force-removed on completion.
        """
        container = None
        start = time.monotonic()
        mount_mode = "ro" if read_only_code else "rw"
        try:
            container = self._client.containers.run(
                image=image,
                command=command,
                working_dir="/sandbox",
                volumes={
                    workdir_host: {"bind": "/sandbox", "mode": mount_mode}
                },
                # ---- security constraints ----
                network_disabled=True,          # --network none
                mem_limit=self.config.sandbox_memory_limit,
                memswap_limit=self.config.sandbox_memory_limit,  # no swap
                pids_limit=128,                 # thwart fork bombs
                cpu_period=100_000,
                cpu_quota=100_000,              # ~1 CPU
                cap_drop=["ALL"],               # drop all Linux capabilities
                security_opt=["no-new-privileges"],
                read_only=True,                 # read-only root fs
                tmpfs={"/tmp": "rw,size=64m,noexec"},
                user="nobody" if read_only_code else None,
                network_mode="none",
                detach=True,
                stdout=True,
                stderr=True,
            )

            try:
                result = container.wait(timeout=timeout)
                exit_code = result.get("StatusCode", -1)
                timed_out = False
            except Exception:  # read timeout from the SDK => kill it
                timed_out = True
                exit_code = -1
                try:
                    container.kill()
                except Exception:  # pragma: no cover
                    pass

            duration_ms = int((time.monotonic() - start) * 1000)

            stdout = _truncate(
                container.logs(stdout=True, stderr=False).decode(
                    "utf-8", "replace"
                )
            )
            stderr = _truncate(
                container.logs(stdout=False, stderr=True).decode(
                    "utf-8", "replace"
                )
            )

            if timed_out:
                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    stdout=stdout,
                    stderr=stderr
                    or f"Time limit exceeded ({timeout}s).",
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                )

            # Detect OOM kills.
            try:
                container.reload()
                oom = bool(container.attrs.get("State", {}).get("OOMKilled"))
            except Exception:  # pragma: no cover
                oom = False

            if oom:
                return ExecutionResult(
                    status=ExecutionStatus.MEMORY_EXCEEDED,
                    stdout=stdout,
                    stderr=stderr or "Memory limit exceeded.",
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                )

            status = (
                ExecutionStatus.SUCCESS
                if exit_code == 0
                else ExecutionStatus.RUNTIME_ERROR
            )
            return ExecutionResult(
                status=status,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )

        except self._DockerException as exc:
            raise SandboxError(f"Docker execution failed: {exc}") from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:  # pragma: no cover
                    pass

    # ---- public API -------------------------------------------------------
    def compile(self, code: str, language: Language) -> CompiledProgram:
        workdir = os.path.join(
            self._host_tmp_root, f"sandbox_{uuid.uuid4().hex}"
        )
        os.makedirs(workdir, exist_ok=True)
        os.chmod(workdir, 0o777)  # writable by the 'nobody' sandbox user

        if language is Language.CPP:
            src_path = os.path.join(workdir, _CPP_SRC)
            with open(src_path, "w", encoding="utf-8") as fh:
                fh.write(code)

            # Compile with a writable mount (the binary must be written).
            compile_res = self._run_container(
                image=self.config.sandbox_cpp_image,
                command=[
                    "g++", "-O2", "-std=c++17", "-w",
                    _CPP_SRC, "-o", _CPP_BIN,
                ],
                workdir_host=workdir,
                timeout=self.config.sandbox_compile_timeout,
                read_only_code=False,
            )
            if not compile_res.ok:
                compile_res.status = ExecutionStatus.COMPILE_ERROR
            return CompiledProgram(self, language, workdir, compile_res)

        # Python: no compile step, just write the source.
        src_path = os.path.join(workdir, _PY_SRC)
        with open(src_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        ok = ExecutionResult(status=ExecutionStatus.SUCCESS)
        return CompiledProgram(self, language, workdir, ok)

    def _run(self, program: CompiledProgram, stdin: str) -> ExecutionResult:
        # Write the stdin to a file and feed it via shell redirection so we do
        # not need an interactive attach.
        stdin_name = f"input_{uuid.uuid4().hex}.txt"
        stdin_path = os.path.join(program.workdir, stdin_name)
        with open(stdin_path, "w", encoding="utf-8") as fh:
            fh.write(stdin)

        if program.language is Language.CPP:
            cmd = ["sh", "-c", f"./{_CPP_BIN} < {stdin_name}"]
            image = self.config.sandbox_cpp_image
        else:
            cmd = ["sh", "-c", f"python3 {_PY_SRC} < {stdin_name}"]
            image = self.config.sandbox_python_image

        try:
            return self._run_container(
                image=image,
                command=cmd,
                workdir_host=program.workdir,
                timeout=self.config.sandbox_cpu_timeout,
                read_only_code=True,
            )
        finally:
            try:
                os.remove(stdin_path)
            except OSError:  # pragma: no cover
                pass

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Local (insecure) backend - development only
# ---------------------------------------------------------------------------
class LocalSandbox(BaseSandbox):
    """Subprocess-based runner. NOT secure; for Docker-less dev only."""

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        logger.warning(
            "Using LOCAL (insecure) sandbox backend - do NOT use in "
            "production. Untrusted code runs in a plain subprocess."
        )

    def compile(self, code: str, language: Language) -> CompiledProgram:
        workdir = tempfile.mkdtemp(prefix="localsandbox_")
        if language is Language.CPP:
            src = os.path.join(workdir, _CPP_SRC)
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(code)
            binary = os.path.join(workdir, _CPP_BIN)
            if not shutil.which("g++"):
                res = ExecutionResult(
                    status=ExecutionStatus.INTERNAL_ERROR,
                    stderr="g++ not found on PATH for local sandbox.",
                )
                return CompiledProgram(self, language, workdir, res)
            proc = subprocess.run(
                ["g++", "-O2", "-std=c++17", "-w", src, "-o", binary],
                capture_output=True,
                text=True,
                timeout=self.config.sandbox_compile_timeout,
            )
            if proc.returncode != 0:
                res = ExecutionResult(
                    status=ExecutionStatus.COMPILE_ERROR,
                    stderr=_truncate(proc.stderr),
                    exit_code=proc.returncode,
                )
            else:
                res = ExecutionResult(status=ExecutionStatus.SUCCESS)
            return CompiledProgram(self, language, workdir, res)

        src = os.path.join(workdir, _PY_SRC)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(code)
        return CompiledProgram(
            self, language, workdir, ExecutionResult(ExecutionStatus.SUCCESS)
        )

    def _run(self, program: CompiledProgram, stdin: str) -> ExecutionResult:
        if program.language is Language.CPP:
            cmd = [os.path.join(program.workdir, _CPP_BIN)]
        else:
            cmd = ["python3", os.path.join(program.workdir, _PY_SRC)]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=self.config.sandbox_cpu_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                stdout=_truncate(exc.stdout or "" if isinstance(exc.stdout, str) else ""),
                stderr=f"Time limit exceeded ({self.config.sandbox_cpu_timeout}s).",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        status = (
            ExecutionStatus.SUCCESS
            if proc.returncode == 0
            else ExecutionStatus.RUNTIME_ERROR
        )
        return ExecutionResult(
            status=status,
            stdout=_truncate(proc.stdout),
            stderr=_truncate(proc.stderr),
            exit_code=proc.returncode,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_sandbox(config: Optional[EngineConfig] = None) -> BaseSandbox:
    """Return the configured sandbox backend."""
    cfg = config or get_config()
    backend = (cfg.sandbox_backend or "docker").lower()
    if backend == "docker":
        return DockerSandbox(cfg)
    if backend == "local":
        return LocalSandbox(cfg)
    raise SandboxError(f"Unknown SANDBOX_BACKEND: {cfg.sandbox_backend!r}")
