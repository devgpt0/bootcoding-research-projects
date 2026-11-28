import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from start import ProcessManager, StartupError, _npm_dev_command, build_share_url, read_project_env


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
            build_share_url("http://127.0.0.1:5173/", "room id/1"),
            "http://127.0.0.1:5173/meeting/room%20id%2F1",
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

    def test_cleanup_errors_are_logged_without_raising(self) -> None:
        manager = ProcessManager()
        process = MagicMock()
        manager.children.append(("test service", process))
        with patch.object(manager, "_stop_process", side_effect=RuntimeError("stop failed")):
            with self.assertLogs("meeting-assistant-startup", level="ERROR"):
                manager.stop_all()


if __name__ == "__main__":
    unittest.main()
