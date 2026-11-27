"""Unit checks for the silent LiveKit participant behavior."""

import asyncio
import unittest
from unittest.mock import AsyncMock

import main
from livekit.agents import AutoSubscribe


class SilentAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_worker_cannot_publish_and_has_stable_dispatch_name(self) -> None:
        self.assertFalse(main.server._permissions.can_publish)
        self.assertFalse(main.server._permissions.can_publish_data)
        self.assertTrue(main.server._permissions.can_subscribe)
        self.assertEqual(main.AI_AGENT_NAME, "ai-meeting-assistant")
        self.assertEqual(main.server._agent_name, main.AI_AGENT_NAME)

    async def test_agent_accepts_stable_participant_identity_and_name(self) -> None:
        request = type("Request", (), {"accept": AsyncMock()})()
        await main.accept_agent_job(request)
        request.accept.assert_awaited_once_with(
            name="AI Meeting Assistant",
            identity="ai-meeting-assistant",
        )

    async def test_entrypoint_subscribes_to_audio_and_waits_for_disconnect(self) -> None:
        class Room:
            name = "meeting-room"

            def on(self, event_name):
                self.event_name = event_name

                def register(callback):
                    self.callback = callback
                    return callback

                return register

        room = Room()
        context = type(
            "Context",
            (),
            {
                "room": room,
                "connect": AsyncMock(),
            },
        )()
        task = asyncio.create_task(main.entrypoint(context))
        await asyncio.sleep(0)

        context.connect.assert_awaited_once_with(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        self.assertEqual(room.event_name, "disconnected")
        self.assertFalse(task.done())
        room.callback()
        await asyncio.wait_for(task, timeout=1)


if __name__ == "__main__":
    unittest.main()
