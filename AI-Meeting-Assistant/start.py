"""Start and supervise the local meeting app and agent."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BACKEND_PORT = 8000
FRONTEND_URL = "http://127.0.0.1:5173"
AGENT_HEALTH_URL = "http://127.0.0.1:8081/"
STARTUP_TIMEOUT = 45.0
logger = logging.getLogger("meeting-assistant-startup")


class StartupError(RuntimeError):
    """Raised when a required service cannot be started or verified."""


def read_project_env(env_path: Path | None = None) -> dict[str, str]:
    """Read simple KEY=value entries without logging or modifying the file."""
    path = env_path or PROJECT_ROOT / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def build_share_url(frontend_origin: str, meeting_id: str) -> str:
    return f"{frontend_origin.rstrip('/')}/meeting/{quote(meeting_id, safe='')}"


class ProcessManager:
    def __init__(self) -> None:
        self.children: list[tuple[str, subprocess.Popen[bytes]]] = []
        self._stopping = False

    def start_process(
        self,
        name: str,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.Popen[bytes]:
        logger.info("Starting %s", name)
        kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        self.children.append((name, process))
        return process

    def assert_running(self) -> None:
        if self._stopping:
            return
        for name, process in self.children:
            code = process.poll()
            if code is not None:
                raise StartupError(f"{name} exited unexpectedly with status {code}")

    def wait_for_http(
        self,
        name: str,
        url: str,
        *,
        timeout: float = STARTUP_TIMEOUT,
    ) -> None:
        deadline = time.monotonic() + timeout
        last_error = "not responding yet"
        while time.monotonic() < deadline:
            self.assert_running()
            try:
                with urlopen(url, timeout=1.5) as response:
                    if 200 <= response.status < 300:
                        logger.info("%s is ready", name)
                        return
                    last_error = f"HTTP {response.status}"
            except HTTPError as exc:
                last_error = f"HTTP {exc.code}"
            except (URLError, TimeoutError, OSError) as exc:
                last_error = type(exc).__name__
            time.sleep(0.4)
        raise StartupError(f"{name} did not become ready ({last_error})")

    def _stop_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def stop_all(self) -> None:
        self._stopping = True
        for _, process in reversed(self.children):
            try:
                self._stop_process(process)
            except Exception:
                logger.exception("Could not stop child process")
        self.children.clear()


def _python_interpreter(environment_dir: Path) -> Path | None:
    candidate = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return candidate if candidate.is_file() else None


def run_project(manager: ProcessManager | None = None) -> None:
    manager = manager or ProcessManager()
    file_env = read_project_env()
    env = os.environ.copy()
    for key, value in file_env.items():
        env.setdefault(key, value)
    env.setdefault("LIVEKIT_AGENT_DEPLOYMENT", "local-dev")

    missing_livekit = [
        key for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
        if not env.get(key, "").strip()
    ]
    if missing_livekit:
        raise StartupError(
            "Missing required LiveKit configuration: " + ", ".join(missing_livekit)
        )

    backend_python = (
        _python_interpreter(PROJECT_ROOT / ".venv")
        or _python_interpreter(PROJECT_ROOT / "backend" / ".venv")
        or Path(sys.executable)
    )
    agent_python = _python_interpreter(PROJECT_ROOT / "agent" / ".venv")
    if agent_python is None:
        raise StartupError(
            "Agent environment is missing. Install agent/requirements.txt in agent/.venv first."
        )

    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        raise StartupError("npm was not found on PATH")

    backend_port = _available_port(DEFAULT_BACKEND_PORT)
    backend_url = f"http://127.0.0.1:{backend_port}"

    agent_env = env.copy()
    agent_env["LIVEKIT_AGENT_DEPLOYMENT"] = env["LIVEKIT_AGENT_DEPLOYMENT"]
    backend_env = env.copy()

    frontend_env = {
        key: value
        for key, value in os.environ.items()
        if not any(secret in key.upper() for secret in ("SECRET", "TOKEN", "API_KEY", "LIVEKIT"))
    }
    frontend_env["VITE_API_BASE_URL"] = backend_url

    try:
        manager.start_process(
            "FastAPI backend",
            [str(backend_python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(backend_port)],
            cwd=PROJECT_ROOT / "backend",
            env=backend_env,
        )
        manager.wait_for_http("FastAPI backend", f"{backend_url}/health")

        manager.start_process(
            "LiveKit Agent worker",
            [str(agent_python), "main.py", "start", "--log-level", "info"],
            cwd=PROJECT_ROOT / "agent",
            env=agent_env,
        )
        manager.wait_for_http("LiveKit Agent worker", AGENT_HEALTH_URL)

        npm_command = _npm_dev_command(npm)
        manager.start_process(
            "React/Vite frontend",
            npm_command,
            cwd=PROJECT_ROOT / "frontend",
            env=frontend_env,
        )
        manager.wait_for_http("React/Vite frontend", FRONTEND_URL)

        logger.info("FastAPI backend started at %s", backend_url)
        logger.info("LiveKit Agent worker is healthy (deployment: %s)", env["LIVEKIT_AGENT_DEPLOYMENT"])
        logger.info("Local frontend started at %s", FRONTEND_URL)
        logger.info("Press Ctrl+C to stop all services")

        while True:
            manager.assert_running()
            time.sleep(0.5)
    finally:
        original_error = sys.exc_info()[1]
        try:
            manager.stop_all()
        except Exception:
            if original_error is None:
                raise
            logger.exception("Cleanup failed while preserving the startup error")


def _npm_dev_command(npm: str) -> list[str]:
    args = [npm, "run", "dev", "--", "--host", "127.0.0.1"]
    if os.name == "nt":
        # Pass arguments separately so Popen quotes npm.cmd paths correctly;
        # `call` lets cmd.exe return after executing the batch file.
        return ["cmd.exe", "/d", "/c", "call", *args]
    return args


def _available_port(preferred_port: int) -> int:
    """Use the preferred local port or ask Windows for an available fallback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred_port))
            return preferred_port
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    try:
        run_project()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except StartupError as exc:
        logger.error("Startup failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
