"""LiveKit room operations."""

from datetime import timedelta
import asyncio
from dataclasses import dataclass
import logging

from livekit import api

from app.core.config import settings

MAX_ROOM_PARTICIPANTS = 20
AI_AGENT_NAME = "ai-meeting-assistant"
_dispatch_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentDispatchResult:
    dispatch_id: str
    already_dispatched: bool


class LiveKitServiceError(RuntimeError):
    """Raised when LiveKit rejects or cannot complete an API request."""


async def create_room(room_name: str) -> api.Room:
    """Create a room in LiveKit Cloud and return its room model."""
    if not all(
        value and value.strip()
        for value in (
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
    ):
        raise LiveKitServiceError("LiveKit is not fully configured")

    client = None
    try:
        client = api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        return await client.room.create_room(
            api.CreateRoomRequest(name=room_name, max_participants=MAX_ROOM_PARTICIPANTS)
        )
    except Exception as exc:
        raise LiveKitServiceError("LiveKit could not create the room") from exc
    finally:
        await _close_client(client)


async def dispatch_agent(room_name: str) -> AgentDispatchResult:
    """Explicitly dispatch the named agent once to this exact LiveKit room."""
    if not all(
        value and value.strip()
        for value in (
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
    ):
        raise LiveKitServiceError("LiveKit is not fully configured")

    async with _dispatch_lock:
        client = None
        try:
            client = api.LiveKitAPI(
                url=settings.livekit_url,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
            existing_dispatches = await client.agent_dispatch.list_dispatch(room_name)
            existing = next(
                (item for item in existing_dispatches if item.agent_name == AI_AGENT_NAME),
                None,
            )
            if existing is not None:
                return AgentDispatchResult(existing.id, already_dispatched=True)

            dispatch = await client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=AI_AGENT_NAME,
                    room=room_name,
                    deployment=settings.livekit_agent_deployment,
                )
            )
            return AgentDispatchResult(dispatch.id, already_dispatched=False)
        except Exception as exc:
            raise LiveKitServiceError("LiveKit could not dispatch the AI agent") from exc
        finally:
            await _close_client(client)


def create_participant_token(
    room_name: str, identity: str, participant_name: str
) -> str:
    """Create a short-lived token with normal meeting publish/subscribe rights."""
    if not all(
        value and value.strip()
        for value in (
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
    ):
        raise LiveKitServiceError("LiveKit is not fully configured")
    try:
        return (
            api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(identity)
            .with_name(participant_name)
            .with_ttl(timedelta(hours=1))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )
    except Exception as exc:
        raise LiveKitServiceError("Unable to create participant access token") from exc


async def delete_room(room_name: str) -> None:
    if not all(
        value and value.strip()
        for value in (
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret,
        )
    ):
        raise LiveKitServiceError("LiveKit is not fully configured")
    client = None
    try:
        client = api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        try:
            dispatches = await client.agent_dispatch.list_dispatch(room_name)
            for dispatch in dispatches:
                if dispatch.agent_name == AI_AGENT_NAME:
                    try:
                        await client.agent_dispatch.delete_dispatch(dispatch.id, room_name)
                    except Exception:
                        logger.warning(
                            "Could not delete agent dispatch %s for room %s; closing room will disconnect it",
                            dispatch.id,
                            room_name,
                            exc_info=True,
                        )
        except Exception:
            logger.warning(
                "Could not list agent dispatches for room %s; closing the room will disconnect participants",
                room_name,
                exc_info=True,
            )
        await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
    except Exception as exc:
        raise LiveKitServiceError("LiveKit could not end the room") from exc
    finally:
        await _close_client(client)


async def _close_client(client: api.LiveKitAPI | None) -> None:
    if client is None:
        return
    try:
        await client.aclose()
    except Exception as exc:
        logger.warning("Could not close LiveKit SDK client (%s)", type(exc).__name__)
