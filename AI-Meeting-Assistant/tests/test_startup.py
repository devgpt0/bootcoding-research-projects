import unittest
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from start import (
    ProcessManager,
    StartupError,
    _create_ngrok_endpoint,
    _ensure_distinct_public_endpoints,
    _ngrok_api_base,
    _ngrok_config_path,
    _ngrok_readiness_error,
    _ngrok_start_command,
    _npm_dev_command,
    _wait_for_ngrok_connection,
    _wait_for_ngrok_api,
    _write_ngrok_web_config,
    build_share_url,
    read_project_env,
)


class StartupTests(unittest.TestCase):
    def test_env_reader_parses_values_without_echoing_them(self) -> None:
        env_file = Path(__file__).with_name("startup-test.env")
        env_file.write_text("LIVEKIT_API_KEY='placeholder-value'\n# ignored\n", encoding="utf-8")
        try:
            self.assertEqual(read_project_env(env_file), {"LIVEKIT_API_KEY": "placeholder-value"})
        finally:
            env_file.unlink(missing_ok=True)

    def test_share_url_uses_frontend_origin_and_encodes_meeting_id(self) -> None:
        self.assertEqual(
            build_share_url("https://web.ngrok.app/", "room id/1"),
            "https://web.ngrok.app/meeting/room%20id%2F1",
        )

    def test_process_manager_starts_and_stops_children(self) -> None:
        manager = ProcessManager()
        process = MagicMock()
        process.poll.return_value = None
        with patch("start.subprocess.Popen", return_value=process) as popen:
            manager.start_process("test service", ["test"], cwd=Path.cwd(), env={})
        popen.assert_called_once()
        with patch.object(manager, "_stop_process") as stop_process:
            manager.stop_all()
        stop_process.assert_called_once_with(process)
        self.assertEqual(manager.children, [])

    def test_process_manager_detects_early_exit(self) -> None:
        manager = ProcessManager()
        process = MagicMock()
        process.poll.return_value = 3
        manager.children.append(("failed service", process))
        with self.assertRaisesRegex(StartupError, "failed service exited unexpectedly"):
            manager.assert_running()

    def test_ngrok_endpoint_uses_dynamic_url_and_expected_upstream(self) -> None:
        manager = ProcessManager()
        with patch("start._http_json", return_value={"url": "https://public.ngrok.app"}) as api:
            public_url = _create_ngrok_endpoint(
                "meeting-backend", "http://127.0.0.1:8000", "", manager
            )
        self.assertEqual(public_url, "https://public.ngrok.app")
        api.assert_called_once_with(
            "/endpoints",
            body={
                "name": "meeting-backend",
                "upstream": {"url": "http://127.0.0.1:8000"},
            },
            api_base="http://127.0.0.1:4040/api",
        )

    def test_public_frontend_and_backend_endpoints_must_be_distinct(self) -> None:
        _ensure_distinct_public_endpoints(
            "https://web.ngrok-free.dev", "https://api.ngrok-free.dev"
        )
        with self.assertRaisesRegex(StartupError, "distinct public hostnames"):
            _ensure_distinct_public_endpoints(
                "https://same.ngrok-free.dev", "https://same.ngrok-free.dev"
            )

    def test_ngrok_readiness_checks_endpoint_collection(self) -> None:
        manager = MagicMock()
        _wait_for_ngrok_api(manager, "http://127.0.0.1:5050/api")
        manager.wait_for_http.assert_called_once_with(
            "ngrok local API", "http://127.0.0.1:5050/api/endpoints"
        )

    def test_ngrok_web_address_defaults_and_supports_custom_port(self) -> None:
        self.assertEqual(_ngrok_api_base("127.0.0.1:4040"), "http://127.0.0.1:4040/api")
        self.assertEqual(_ngrok_api_base("127.0.0.1:5050"), "http://127.0.0.1:5050/api")

    def test_ngrok_web_address_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(StartupError, "NGROK_WEB_ADDR"):
            _ngrok_api_base("https://127.0.0.1:4040/api")

    def test_ngrok_config_path_is_read_from_cli_check_output(self) -> None:
        path = _ngrok_config_path("Valid configuration file at C:\\Users\\me\\ngrok.yml\n")
        self.assertEqual(str(path), "C:\\Users\\me\\ngrok.yml")

    def test_ngrok_overlay_sets_web_addr_without_copying_auth_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "ngrok.yml"
            config.write_text("version: 2\nauthtoken: do-not-copy\n", encoding="utf-8")
            overlay = _write_ngrok_web_config(config, "127.0.0.1:5050")
            try:
                content = overlay.read_text(encoding="utf-8")
                self.assertEqual(content, 'version: 2\nweb_addr: "127.0.0.1:5050"\n')
                self.assertNotIn("do-not-copy", content)
            finally:
                overlay.unlink(missing_ok=True)

    def test_ngrok_start_command_merges_existing_config_and_overlay(self) -> None:
        self.assertEqual(
            _ngrok_start_command("ngrok.exe", Path("user.yml"), Path("web.yml")),
            [
                "ngrok.exe", "start", "--none",
                "--config", "user.yml", "--config", "web.yml",
            ],
        )

    def test_ngrok_connection_wait_accepts_online_status(self) -> None:
        manager = ProcessManager()
        with patch("start._http_json", return_value={"status": "online"}) as api:
            _wait_for_ngrok_connection(manager, "http://127.0.0.1:5050/api")
        api.assert_called_once_with("/status", api_base="http://127.0.0.1:5050/api")

    def test_ngrok_connection_wait_reports_reconnecting_status(self) -> None:
        manager = ProcessManager()
        with (
            patch("start._http_json", return_value={"status": "reconnecting"}),
            patch("start.time.monotonic", side_effect=[0.0, 0.5, 2.0]),
            patch("start.time.sleep"),
        ):
            with self.assertRaisesRegex(StartupError, "tunnel connection failed.*reconnecting"):
                _wait_for_ngrok_connection(manager, timeout=1.0)

    def test_windows_npm_command_preserves_batch_file_path_with_spaces(self) -> None:
        npm = r"C:\Program Files\nodejs\npm.cmd"
        with patch("start.os.name", "nt"):
            command = _npm_dev_command(npm)
        self.assertEqual(
            command,
            [
                "cmd.exe", "/d", "/c", "call", npm,
                "run", "dev", "--", "--host", "127.0.0.1",
            ],
        )

    def test_ngrok_readiness_error_reports_process_exit(self) -> None:
        original = StartupError("ngrok tunnel agent exited unexpectedly with status 1")
        with self.assertLogs("meeting-assistant-startup", level="ERROR") as logs:
            error = _ngrok_readiness_error(original)
        self.assertIn("ngrok process exited", str(error))
        self.assertIn(str(original), str(error))
        self.assertIn("ngrok process exited", logs.output[0])

    def test_ngrok_readiness_error_reports_api_timeout(self) -> None:
        original = StartupError("ngrok local API did not become ready (TimeoutError)")
        with self.assertLogs("meeting-assistant-startup", level="ERROR") as logs:
            error = _ngrok_readiness_error(original)
        self.assertIn("ngrok local API readiness timed out", str(error))
        self.assertIn(str(original), str(error))
        self.assertIn("timed out", logs.output[0])

    def test_ngrok_readiness_error_reports_unsuccessful_http_response(self) -> None:
        original = StartupError("ngrok local API did not become ready (HTTP 503)")
        with self.assertLogs("meeting-assistant-startup", level="ERROR") as logs:
            error = _ngrok_readiness_error(original)
        self.assertIn("unsuccessful HTTP response", str(error))
        self.assertIn("HTTP 503", str(error))
        self.assertIn("unsuccessful HTTP response", logs.output[0])

    def test_ngrok_readiness_error_reports_tunnel_connection_failure(self) -> None:
        original = StartupError("ngrok tunnel connection failed (agent status: reconnecting)")
        with self.assertLogs("meeting-assistant-startup", level="ERROR") as logs:
            error = _ngrok_readiness_error(original)
        self.assertIn("ngrok tunnel connection failed", str(error))
        self.assertIn("reconnecting", str(error))
        self.assertIn("tunnel connection failed", logs.output[0])

    def test_cleanup_errors_are_logged_without_raising(self) -> None:
        manager = ProcessManager()
        process = MagicMock()
        manager.children.append(("ngrok", process))
        with patch.object(manager, "_stop_process", side_effect=RuntimeError("stop failed")):
            with self.assertLogs("meeting-assistant-startup", level="ERROR"):
                manager.stop_all()


if __name__ == "__main__":
    unittest.main()
