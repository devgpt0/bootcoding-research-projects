"""JSON-backed persistence for meeting metadata."""

import json
import os
from pathlib import Path
import threading
from typing import Any

from app.core.config import PROJECT_ROOT

MEETINGS_FILE = PROJECT_ROOT / "storage" / "meetings" / "meetings.json"
_storage_lock = threading.Lock()


class MeetingStorageError(ValueError):
    """Raised when the meeting JSON file cannot be read safely."""


def _read_records() -> list[dict[str, Any]]:
    MEETINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MEETINGS_FILE.exists():
        return []
    try:
        with MEETINGS_FILE.open("r", encoding="utf-8") as file:
            content = json.load(file)
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise MeetingStorageError("Meeting metadata file cannot be read") from exc
    if not isinstance(content, list) or any(not isinstance(row, dict) for row in content):
        raise MeetingStorageError("Meeting metadata must be a JSON array of objects")
    return content


def _write_records(records: list[dict[str, Any]]) -> None:
    MEETINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = MEETINGS_FILE.with_suffix(".json.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(MEETINGS_FILE)
    except OSError as exc:
        raise MeetingStorageError("Meeting metadata file cannot be written") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def list_meetings() -> list[dict[str, Any]]:
    with _storage_lock:
        return _read_records()


def get_meeting(meeting_id: str) -> dict[str, Any] | None:
    with _storage_lock:
        return next(
            (row for row in _read_records() if row.get("meeting_id") == meeting_id),
            None,
        )


def save_meeting(meeting: dict[str, Any]) -> None:
    """Append a meeting record using an atomic replace to avoid partial JSON."""
    with _storage_lock:
        records = _read_records()
        records.append(meeting)
        _write_records(records)


def update_meeting(meeting_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    with _storage_lock:
        records = _read_records()
        for record in records:
            if record.get("meeting_id") == meeting_id:
                record.update(updates)
                _write_records(records)
                return record
        return None
