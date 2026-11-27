"""Meeting API schemas."""

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MeetingCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Meeting title cannot be blank")
        return value


class MeetingResponse(BaseModel):
    meeting_id: str
    room_name: str
    title: str
    created_at: datetime
    ended_at: datetime | None = None
    status: Literal["active", "ending", "ended"] = "active"
    agent_dispatch_status: Literal["pending", "accepted", "failed"] | None = None
    agent_dispatch_id: str | None = None


class MeetingCreateResponse(MeetingResponse):
    host_key: str


class JoinMeetingRequest(BaseModel):
    participant_name: str = Field(min_length=1, max_length=80)

    @field_validator("participant_name")
    @classmethod
    def participant_name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Participant name cannot be blank")
        return value


class JoinMeetingResponse(BaseModel):
    meeting_id: str
    room_name: str
    participant_identity: str
    participant_name: str
    server_url: str
    token: str


class EndMeetingResponse(BaseModel):
    meeting_id: str
    ended_at: datetime


class EndMeetingRequest(BaseModel):
    host_key: str = Field(min_length=32, max_length=128)
