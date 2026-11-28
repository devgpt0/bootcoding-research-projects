"""API tests use a temporary JSON file and mock all LiveKit network calls."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import jwt
from livekit import api as livekit_api

from app.main import app
from app.services import file_storage_service
from app.services import livekit_service


class MeetingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.tempdir.name) / "meetings.json"
        self.original_path = file_storage_service.MEETINGS_FILE
        file_storage_service.MEETINGS_FILE = self.storage_path
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        file_storage_service.MEETINGS_FILE = self.original_path
        self.tempdir.cleanup()

    def create_meeting(self) -> dict[str, object]:
        with patch(
            "app.api.meetings.create_room",
            new=AsyncMock(side_effect=lambda room_name: livekit_api.Room(name=room_name)),
        ), patch(
            "app.api.meetings.dispatch_agent",
            new=AsyncMock(
                return_value=livekit_service.AgentDispatchResult("dispatch-test", False)
            ),
        ):
            response = self.client.post("/api/meetings", json={"title": "Weekly sync"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    def test_create_list_and_get_meeting(self) -> None:
        meeting = self.create_meeting()
        meeting_id = meeting["meeting_id"]
        self.assertEqual(meeting["title"], "Weekly sync")
        self.assertTrue(meeting["room_name"].startswith("meeting-"))
        self.assertEqual(self.client.get("/api/meetings").json()[0]["meeting_id"], meeting_id)
        details = self.client.get(f"/api/meetings/{meeting_id}").json()
        self.assertEqual(details["agent_dispatch_status"], "accepted")
        self.assertNotIn("host_key", details)

    def test_meeting_creation_dispatches_once_to_the_created_room(self) -> None:
        with (
            patch(
                "app.api.meetings.create_room",
                new=AsyncMock(side_effect=lambda room_name: livekit_api.Room(name=room_name)),
            ),
            patch(
                "app.api.meetings.dispatch_agent",
                new=AsyncMock(
                    return_value=livekit_service.AgentDispatchResult("dispatch-test", False)
                ),
            ) as dispatch,
        ):
            response = self.client.post("/api/meetings", json={"title": "Dispatch check"})
        meeting = response.json()
        self.assertEqual(response.status_code, 201)
        dispatch.assert_awaited_once_with(meeting["room_name"])
        self.assertEqual(meeting["agent_dispatch_status"], "accepted")
        self.assertEqual(meeting["agent_dispatch_id"], "dispatch-test")

    def test_dispatch_failure_is_reported_without_claiming_agent_joined(self) -> None:
        with (
            patch(
                "app.api.meetings.create_room",
                new=AsyncMock(side_effect=lambda room_name: livekit_api.Room(name=room_name)),
            ),
            patch(
                "app.api.meetings.dispatch_agent",
                new=AsyncMock(side_effect=livekit_service.LiveKitServiceError("dispatch failed")),
            ),
        ):
            response = self.client.post("/api/meetings", json={"title": "No agent"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["agent_dispatch_status"], "failed")
        self.assertNotIn("agent_joined", response.json())

    def test_duplicate_agent_dispatch_is_reused(self) -> None:
        existing = SimpleNamespace(agent_name=livekit_service.AI_AGENT_NAME, id="existing-id")
        fake_dispatch = SimpleNamespace(list_dispatch=AsyncMock(return_value=[existing]))
        fake_client = SimpleNamespace(
            agent_dispatch=fake_dispatch,
            aclose=AsyncMock(),
        )
        with (
            patch.object(livekit_service.settings, "livekit_url", "wss://example.livekit.cloud"),
            patch.object(livekit_service.settings, "livekit_api_key", "test-key"),
            patch.object(livekit_service.settings, "livekit_api_secret", "test-secret"),
            patch.object(livekit_service.api, "LiveKitAPI", return_value=fake_client),
        ):
            result = __import__("asyncio").run(livekit_service.dispatch_agent("room-existing"))
        self.assertTrue(result.already_dispatched)
        self.assertEqual(result.dispatch_id, "existing-id")
        fake_dispatch.list_dispatch.assert_awaited_once_with("room-existing")
        self.assertFalse(hasattr(fake_dispatch, "create_dispatch"))

    def test_dispatch_request_targets_configured_agent_and_deployment(self) -> None:
        created = SimpleNamespace(id="dispatch-created")
        fake_dispatch = SimpleNamespace(
            list_dispatch=AsyncMock(return_value=[]),
            create_dispatch=AsyncMock(return_value=created),
        )
        fake_client = SimpleNamespace(agent_dispatch=fake_dispatch, aclose=AsyncMock())
        with (
            patch.object(livekit_service.settings, "livekit_url", "wss://example.livekit.cloud"),
            patch.object(livekit_service.settings, "livekit_api_key", "test-key"),
            patch.object(livekit_service.settings, "livekit_api_secret", "test-secret"),
            patch.object(livekit_service.settings, "livekit_agent_deployment", "local-dev"),
            patch.object(livekit_service.api, "LiveKitAPI", return_value=fake_client),
        ):
            result = __import__("asyncio").run(
                livekit_service.dispatch_agent("meeting-exact-room")
            )
        request = fake_dispatch.create_dispatch.await_args.args[0]
        self.assertEqual(request.room, "meeting-exact-room")
        self.assertEqual(request.agent_name, "ai-meeting-assistant")
        self.assertEqual(request.deployment, "local-dev")
        self.assertEqual(result.dispatch_id, "dispatch-created")
        self.assertFalse(result.already_dispatched)

    def test_ending_room_deletes_its_agent_dispatch(self) -> None:
        dispatch = SimpleNamespace(agent_name=livekit_service.AI_AGENT_NAME, id="dispatch-to-delete")
        fake_dispatch = SimpleNamespace(
            list_dispatch=AsyncMock(return_value=[dispatch]),
            delete_dispatch=AsyncMock(return_value=None),
        )
        fake_room = SimpleNamespace(delete_room=AsyncMock(return_value=None))
        fake_client = SimpleNamespace(
            room=fake_room,
            agent_dispatch=fake_dispatch,
            aclose=AsyncMock(),
        )
        with (
            patch.object(livekit_service.settings, "livekit_url", "wss://example.livekit.cloud"),
            patch.object(livekit_service.settings, "livekit_api_key", "test-key"),
            patch.object(livekit_service.settings, "livekit_api_secret", "test-secret"),
            patch.object(livekit_service.api, "LiveKitAPI", return_value=fake_client),
        ):
            __import__("asyncio").run(livekit_service.delete_room("room-to-end"))
        fake_dispatch.delete_dispatch.assert_awaited_once_with(
            "dispatch-to-delete", "room-to-end"
        )
        fake_room.delete_room.assert_awaited_once()

    def test_local_frontend_origins_can_preflight_meeting_creation(self) -> None:
        for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            with self.subTest(origin=origin):
                response = self.client.options(
                    "/api/meetings",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "content-type",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                self.assertIn("POST", response.headers["access-control-allow-methods"])
                self.assertIn("content-type", response.headers["access-control-allow-headers"])

    def test_meeting_routes_are_registered_at_expected_paths(self) -> None:
        meeting_paths = app.openapi()["paths"]
        self.assertIn("post", meeting_paths["/api/meetings"])
        self.assertIn("get", meeting_paths["/api/meetings"])
        response = self.client.get("/api/meetings")
        self.assertEqual(response.status_code, 200, response.text)

    def test_join_returns_participant_token_without_exposing_secrets(self) -> None:
        meeting = self.create_meeting()
        with patch(
            "app.api.meetings.create_participant_token", return_value="mock.jwt.token"
        ) as token_factory:
            response = self.client.post(
                f"/api/meetings/{meeting['meeting_id']}/join",
                json={"participant_name": "Alex"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["token"], "mock.jwt.token")
        self.assertEqual(response.json()["participant_name"], "Alex")
        self.assertNotIn("api_secret", response.json())
        token_factory.assert_called_once()

    def test_participant_token_is_room_scoped_with_publish_subscribe_rights(self) -> None:
        with (
            patch.object(livekit_service.settings, "livekit_api_key", "test-key-long-enough-for-sha256"),
            patch.object(
                livekit_service.settings,
                "livekit_api_secret",
                "test-secret-long-enough-for-sha256-validation",
            ),
        ):
            token = livekit_service.create_participant_token("room-a", "person-a", "Alex")
        claims = jwt.decode(token, options={"verify_signature": False})
        self.assertEqual(claims["sub"], "person-a")
        self.assertEqual(
            claims["video"],
            {
                "roomJoin": True,
                "room": "room-a",
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True,
            },
        )

    def test_unknown_meeting_cannot_be_read_or_joined(self) -> None:
        self.assertEqual(self.client.get("/api/meetings/missing").status_code, 404)
        response = self.client.post(
            "/api/meetings/missing/join", json={"participant_name": "Alex"}
        )
        self.assertEqual(response.status_code, 404)

    def test_end_meeting_closes_room_and_persists_status(self) -> None:
        meeting = self.create_meeting()
        with patch("app.api.meetings.delete_room", new=AsyncMock()) as delete_room:
            response = self.client.post(
                f"/api/meetings/{meeting['meeting_id']}/end",
                json={"host_key": meeting["host_key"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        delete_room.assert_awaited_once_with(meeting["room_name"])
        details = self.client.get(f"/api/meetings/{meeting['meeting_id']}").json()
        self.assertIsNotNone(details["ended_at"])
        self.assertEqual(
            self.client.post(
                f"/api/meetings/{meeting['meeting_id']}/join",
                json={"participant_name": "Alex"},
            ).status_code,
            409,
        )

    def test_non_host_cannot_end_meeting(self) -> None:
        meeting = self.create_meeting()
        response = self.client.post(
            f"/api/meetings/{meeting['meeting_id']}/end",
            json={"host_key": "x" * 32},
        )
        self.assertEqual(response.status_code, 403)

    def test_json_persistence_is_valid(self) -> None:
        meeting = self.create_meeting()
        records = json.loads(self.storage_path.read_text(encoding="utf-8"))
        self.assertEqual(records[0]["meeting_id"], meeting["meeting_id"])


if __name__ == "__main__":
    unittest.main()
