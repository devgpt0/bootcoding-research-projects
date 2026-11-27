"""Entry point for the explicitly dispatched, silent meeting assistant."""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import (
    AgentServer,
    AutoSubscribe,
    JobContext,
    JobRequest,
    WorkerPermissions,
    cli,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("LIVEKIT_AGENT_DEPLOYMENT", "local-dev")

logging.basicConfig(level=logging.INFO)
AI_AGENT_NAME = "ai-meeting-assistant"
logger = logging.getLogger(AI_AGENT_NAME)

server = AgentServer(
    host="127.0.0.1",
    port=8081,
    permissions=WorkerPermissions(
        can_publish=False,
        can_subscribe=True,
        can_publish_data=False,
        can_update_metadata=False,
    )
)


async def accept_agent_job(job_request: JobRequest) -> None:
    """Give the visible room participant a stable identity and display name."""
    await job_request.accept(
        name="AI Meeting Assistant",
        identity=AI_AGENT_NAME,
    )


@server.rtc_session(agent_name=AI_AGENT_NAME, on_request=accept_agent_job)
async def entrypoint(ctx: JobContext) -> None:
    """Join a dispatched room, receive audio, and publish no tracks or speech."""
    logger.info("Connecting silent assistant to room %s", ctx.room.name)
    disconnected = asyncio.Event()

    @ctx.room.on("disconnected")
    def on_disconnected(*_: object) -> None:
        disconnected.set()

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    try:
        await disconnected.wait()
    except asyncio.CancelledError:
        logger.info("Silent assistant disconnecting from room %s", ctx.room.name)
        raise


if __name__ == "__main__":
    cli.run_app(server)
