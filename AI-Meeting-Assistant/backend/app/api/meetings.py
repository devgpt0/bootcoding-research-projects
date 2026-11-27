"""Meeting creation endpoints."""

from datetime import datetime, timezone
import hmac
import logging
import secrets
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas.meeting import (
    EndMeetingResponse,
    EndMeetingRequest,
    JoinMeetingRequest,
    JoinMeetingResponse,
    MeetingCreateResponse,
    MeetingCreateRequest,
    MeetingResponse,
)
from app.services.file_storage_service import (
    MeetingStorageError,
    get_meeting,
    list_meetings as read_meetings,
    save_meeting,
    update_meeting,
)
from app.services.livekit_service import (
    LiveKitServiceError,
    create_participant_token,
    create_room,
    delete_room,
    dispatch_agent,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
logger = logging.getLogger(__name__)


@router.post("", response_model=MeetingCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_meeting(request: MeetingCreateRequest) -> MeetingCreateResponse:
    meeting_id = str(uuid4())
    room_name = f"meeting-{meeting_id}"
    created_at = datetime.now(timezone.utc)
    host_key = secrets.token_urlsafe(32)

    try:
        room = await create_room(room_name)
    except LiveKitServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create a meeting room with LiveKit",
        ) from exc

    meeting = MeetingResponse(
        meeting_id=meeting_id,
        room_name=room.name,
        title=request.title,
        created_at=created_at,
        agent_dispatch_status="pending",
    )
    try:
        save_meeting({**meeting.model_dump(mode="json"), "host_key": host_key})
    except MeetingStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save meeting metadata",
        ) from exc

    try:
        dispatch = await dispatch_agent(room.name)
        meeting.agent_dispatch_status = "accepted"
        meeting.agent_dispatch_id = dispatch.dispatch_id
        if dispatch.already_dispatched:
            logger.info("AI agent dispatch already exists for room %s", room.name)
        else:
            logger.info(
                "AI agent dispatch %s accepted for room %s; waiting for participant connection",
                dispatch.dispatch_id,
                room.name,
            )
    except LiveKitServiceError:
        meeting.agent_dispatch_status = "failed"
        logger.exception("AI agent dispatch failed for room %s", room.name)

    try:
        updated = update_meeting(
            meeting_id,
            {
                "agent_dispatch_status": meeting.agent_dispatch_status,
                "agent_dispatch_id": meeting.agent_dispatch_id,
            },
        )
        if updated is None:
            raise MeetingStorageError("Created meeting metadata could not be updated")
    except MeetingStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save AI agent dispatch status",
        ) from exc
    return MeetingCreateResponse(**meeting.model_dump(), host_key=host_key)


@router.get("", response_model=list[MeetingResponse])
async def list_meetings() -> list[MeetingResponse]:
    try:
        return [MeetingResponse.model_validate(row) for row in read_meetings()]
    except (MeetingStorageError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Unable to read meeting metadata") from exc


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting_details(meeting_id: str) -> MeetingResponse:
    try:
        record = get_meeting(meeting_id)
    except MeetingStorageError as exc:
        raise HTTPException(status_code=500, detail="Unable to read meeting metadata") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    try:
        return MeetingResponse.model_validate(record)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Meeting metadata is invalid") from exc


@router.post("/{meeting_id}/join", response_model=JoinMeetingResponse)
async def join_meeting(meeting_id: str, request: JoinMeetingRequest) -> JoinMeetingResponse:
    try:
        meeting = get_meeting(meeting_id)
    except MeetingStorageError as exc:
        raise HTTPException(status_code=500, detail="Unable to read meeting metadata") from exc
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("ended_at") or meeting.get("status") in {"ending", "ended"}:
        raise HTTPException(status_code=409, detail="Meeting has ended")
    identity = f"participant-{uuid4()}"
    try:
        token = create_participant_token(
            meeting["room_name"], identity, request.participant_name
        )
    except (KeyError, LiveKitServiceError) as exc:
        raise HTTPException(
            status_code=502, detail="Unable to create a LiveKit participant token"
        ) from exc
    if not settings.livekit_url:
        raise HTTPException(status_code=503, detail="LiveKit is not configured")
    return JoinMeetingResponse(
        meeting_id=meeting_id,
        room_name=meeting["room_name"],
        participant_identity=identity,
        participant_name=request.participant_name,
        server_url=settings.livekit_url,
        token=token,
    )


@router.post("/{meeting_id}/end", response_model=EndMeetingResponse)
async def end_meeting(
    meeting_id: str, request: EndMeetingRequest
) -> EndMeetingResponse:
    try:
        meeting = get_meeting(meeting_id)
    except MeetingStorageError as exc:
        raise HTTPException(status_code=500, detail="Unable to read meeting metadata") from exc
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    stored_host_key = meeting.get("host_key", "")
    if not stored_host_key or not hmac.compare_digest(stored_host_key, request.host_key):
        raise HTTPException(status_code=403, detail="Only the meeting host can end this meeting")
    if meeting.get("ended_at") or meeting.get("status") == "ended":
        return EndMeetingResponse(meeting_id=meeting_id, ended_at=meeting["ended_at"])
    try:
        update_meeting(meeting_id, {"status": "ending"})
    except MeetingStorageError as exc:
        raise HTTPException(status_code=500, detail="Unable to save meeting status") from exc
    try:
        await delete_room(meeting["room_name"])
    except (KeyError, LiveKitServiceError) as exc:
        try:
            update_meeting(meeting_id, {"status": "active"})
        except MeetingStorageError:
            logger.exception("Could not restore meeting status after LiveKit end failure")
        raise HTTPException(status_code=502, detail="Unable to end LiveKit room") from exc
    ended_at = datetime.now(timezone.utc)
    try:
        update_meeting(
            meeting_id,
            {"ended_at": ended_at.isoformat(), "status": "ended"},
        )
    except MeetingStorageError as exc:
        raise HTTPException(status_code=500, detail="Unable to save meeting status") from exc
    return EndMeetingResponse(meeting_id=meeting_id, ended_at=ended_at)
