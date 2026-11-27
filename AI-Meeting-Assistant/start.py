"""Start and supervise the local meeting app, agent, and ngrok endpoints."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:5173"
AGENT_HEALTH_URL = "http://127.0.0.1:8081/"
DEFAULT_NGROK_WEB_ADDR = "127.0.0.1:4040"
NGROK_API = f"http://{DEFAULT_NGROK_WEB_ADDR}/api"
STARTUP_TIMEOUT = 45.0
logger = logging.getLogger("meeting-assistant-startup")


class StartupError(RuntimeError):
    """Raised when a required service cannot be started or verified."""


def _ngrok_readiness_error(exc: StartupError) -> StartupError:
    """Add a useful ngrok readiness diagnosis without discarding its cause."""
    details = str(exc)
    if "exited unexpectedly" in details:
        failure = "ngrok process exited"
    elif "tunnel connection failed" in details:
        failure = "ngrok tunnel connection failed"
    elif "(HTTP " in details:
        failure = "ngrok local API returned an unsuccessful HTTP response during readiness"
    else:
        failure = "ngrok local API readiness timed out or could not be reached"
    logger.error("ngrok readiness failure (%s): %s", failure, details)
    return StartupError(f"ngrok readiness failed ({failure}): {details}")


def _ngrok_api_base(web_addr: str) -> str:
    try:
        parsed = urlsplit(f"//{web_addr}")
        port = parsed.port
    except ValueError as exc:
        raise StartupError(f"Invalid NGROK_WEB_ADDR: {web_addr!r}") from exc
    if (
        not parsed.hostname
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise StartupError(
            "NGROK_WEB_ADDR must be a host:port address such as 127.0.0.1:4040"
        )
    return f"http://{web_addr}/api"


def _ngrok_config_path(config_check_output: str) -> Path:
    prefix = "Valid configuration file at "
    for line in config_check_output.splitlines():
        if line.startswith(prefix):
            return Path(line[len(prefix):].strip())
    raise StartupError("Could not determine the ngrok configuration file path")


def _write_ngrok_web_config(config_path: Path, web_addr: str) -> Path:
    config_text = config_path.read_text(encoding="utf-8-sig")
    match = re.search(r"(?m)^version:\s*['\"]?([23])['\"]?\s*$", config_text)
    if match is None:
        raise StartupError("Could not determine the ngrok config version for web_addr")
    version = match.group(1)
    value = json.dumps(web_addr)
    if version == "2":
        overlay = f"version: 2\nweb_addr: {value}\n"
    else:
        overlay = f"version: 3\nagent:\n  web_addr: {value}\n"

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".yml", prefix="ai-meeting-ngrok-", delete=False
    ) as temp_config:
        temp_config.write(overlay)
        return Path(temp_config.name)


def _ngrok_start_command(ngrok: str, config_path: Path, overlay_path: Path) -> list[str]:
    return [
        ngrok, "start", "--none",
        "--config", str(config_path), "--config", str(overlay_path),
    ]


def _wait_for_ngrok_api(manager: ProcessManager, api_base: str = NGROK_API) -> None:
    manager.wait_for_http("ngrok local API", f"{api_base}/endpoints")


def _wait_for_ngrok_connection(
    manager: ProcessManager,
    api_base: str = NGROK_API,
    *,
    timeout: float = STARTUP_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout
    last_status = "unavailable"
    while time.monotonic() < deadline:
        manager.assert_running()
        try:
            result = _http_json("/status", api_base=api_base)
            last_status = str(result.get("status", "unknown"))
            if last_status.lower() == "online":
                logger.info("ngrok tunnel connection is online")
                return
        except StartupError as exc:
            last_status = str(exc)
        time.sleep(0.4)
    raise StartupError(f"ngrok tunnel connection failed (agent status: {last_status})")


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


def _http_json(
    path: str,
    *,
    body: dict[str, Any] | None = None,
    api_base: str = NGROK_API,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        f"{api_base}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise StartupError(
            f"ngrok local API request failed (HTTP {exc.code})"
        ) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise StartupError(f"Could not communicate with the local ngrok agent API ({type(exc).__name__})") from exc


def _create_ngrok_endpoint(
    name: str,
    upstream: str,
    configured_url: str,
    manager: ProcessManager,
    *,
    api_base: str = NGROK_API,
) -> str:
    body: dict[str, Any] = {
        "name": name,
        "upstream": {"url": upstream},
    }
    if configured_url.strip():
        if not configured_url.startswith("https://"):
            raise StartupError(f"{name} must be a public HTTPS URL")
        body["url"] = configured_url.strip()
    result = _http_json("/endpoints", body=body, api_base=api_base)
    public_url = result.get("url") or result.get("public_url")
    if not isinstance(public_url, str) or not public_url.startswith("https://"):
        raise StartupError(f"ngrok did not return a public HTTPS URL for {name}")
    manager.assert_running()
    return public_url.rstrip("/")


def _ensure_distinct_public_endpoints(frontend_url: str, backend_url: str) -> None:
    """Require separate public hosts so frontend requests reach the right service."""
    frontend_host = urlsplit(frontend_url).hostname
    backend_host = urlsplit(backend_url).hostname
    if not frontend_host or not backend_host or frontend_host == backend_host:
        raise StartupError(
            "NGROK_FRONTEND_URL and NGROK_BACKEND_URL must use distinct public hostnames"
        )


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
    ngrok = shutil.which("ngrok")
    if npm is None:
        raise StartupError("npm was not found on PATH")
    if ngrok is None:
        raise StartupError("ngrok was not found on PATH; install the ngrok CLI first")

    config_check = subprocess.run(
        [ngrok, "config", "check"], capture_output=True, text=True, check=False
    )
    if config_check.returncode != 0:
        raise StartupError(
            "ngrok is not configured. Install the CLI and add an account authtoken with `ngrok config add-authtoken`."
        )
    ngrok_config_path = _ngrok_config_path(
        f"{config_check.stdout}\n{config_check.stderr}"
    )
    ngrok_web_addr = env.get("NGROK_WEB_ADDR", DEFAULT_NGROK_WEB_ADDR).strip()
    if not ngrok_web_addr:
        ngrok_web_addr = DEFAULT_NGROK_WEB_ADDR
    ngrok_api_base = _ngrok_api_base(ngrok_web_addr)
    ngrok_addr = urlsplit(f"//{ngrok_web_addr}")
    ngrok_overlay_path = _write_ngrok_web_config(ngrok_config_path, ngrok_web_addr)

    agent_env = env.copy()
    agent_env["LIVEKIT_AGENT_DEPLOYMENT"] = env["LIVEKIT_AGENT_DEPLOYMENT"]
    backend_env = env.copy()

    frontend_env = {
        key: value
        for key, value in os.environ.items()
        if not any(secret in key.upper() for secret in ("SECRET", "TOKEN", "API_KEY", "LIVEKIT", "NGROK"))
    }
    frontend_env["VITE_API_BASE_URL"] = "http://127.0.0.1:8000"
    ngrok_env = os.environ.copy()
    for secret_name in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        ngrok_env.pop(secret_name, None)
    if env.get("NGROK_AUTHTOKEN"):
        ngrok_env["NGROK_AUTHTOKEN"] = env["NGROK_AUTHTOKEN"]

    try:
        manager.start_process(
            "FastAPI backend",
            [str(backend_python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=PROJECT_ROOT / "backend",
            env=backend_env,
        )
        manager.wait_for_http("FastAPI backend", f"{BACKEND_URL}/health")

        manager.start_process(
            "LiveKit Agent worker",
            [str(agent_python), "main.py", "start", "--log-level", "info"],
            cwd=PROJECT_ROOT / "agent",
            env=agent_env,
        )
        manager.wait_for_http("LiveKit Agent worker", AGENT_HEALTH_URL)

        if _port_is_open(ngrok_addr.hostname or "127.0.0.1", ngrok_addr.port or 4040):
            raise StartupError(f"ngrok local API address {ngrok_web_addr} is already in use")
        manager.start_process(
            "ngrok tunnel agent",
            _ngrok_start_command(ngrok, ngrok_config_path, ngrok_overlay_path),
            cwd=PROJECT_ROOT,
            env=ngrok_env,
        )
        try:
            _wait_for_ngrok_api(manager, ngrok_api_base)
        except StartupError as exc:
            raise _ngrok_readiness_error(exc) from exc
        try:
            _wait_for_ngrok_connection(manager, ngrok_api_base)
        except StartupError as exc:
            raise _ngrok_readiness_error(exc) from exc

        backend_public_url = _create_ngrok_endpoint(
            "meeting-backend",
            "http://127.0.0.1:8000",
            env.get("NGROK_BACKEND_URL", ""),
            manager,
            api_base=ngrok_api_base,
        )

        frontend_env["VITE_API_BASE_URL"] = backend_public_url
        npm_command = _npm_dev_command(npm)
        manager.start_process(
            "React/Vite frontend",
            npm_command,
            cwd=PROJECT_ROOT / "frontend",
            env=frontend_env,
        )
        manager.wait_for_http("React/Vite frontend", FRONTEND_URL)

        frontend_public_url = _create_ngrok_endpoint(
            "meeting-frontend",
            "http://127.0.0.1:5173",
            env.get("NGROK_FRONTEND_URL", ""),
            manager,
            api_base=ngrok_api_base,
        )
        _ensure_distinct_public_endpoints(frontend_public_url, backend_public_url)

        logger.info("FastAPI backend started at %s", BACKEND_URL)
        logger.info("LiveKit Agent worker is healthy (deployment: %s)", env["LIVEKIT_AGENT_DEPLOYMENT"])
        logger.info("Local frontend started at %s", FRONTEND_URL)
        logger.info("Public frontend: %s", frontend_public_url)
        logger.info("Public backend: %s", backend_public_url)
        logger.info("Press Ctrl+C to stop all services and tunnels")

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
        finally:
            try:
                ngrok_overlay_path.unlink(missing_ok=True)
            except OSError:
                if original_error is None:
                    raise
                logger.exception("Could not remove the temporary ngrok config overlay")


def _npm_dev_command(npm: str) -> list[str]:
    args = [npm, "run", "dev", "--", "--host", "127.0.0.1"]
    if os.name == "nt":
        # Pass arguments separately so Popen quotes npm.cmd paths correctly;
        # `call` lets cmd.exe return after executing the batch file.
        return ["cmd.exe", "/d", "/c", "call", *args]
    return args


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


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
