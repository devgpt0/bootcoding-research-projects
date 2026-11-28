from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.meetings import router as meetings_router
from app.core.config import livekit_configuration_status

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Log whether LiveKit configuration is present without logging values."""
    status = livekit_configuration_status()
    logger.info("LiveKit configuration presence: %s", status)
    missing = [name for name, present in status.items() if not present]
    if missing:
        logger.warning("LiveKit configuration is missing: %s", ", ".join(missing))
    yield


app = FastAPI(title="AI Meeting Assistant", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(meetings_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Return a basic service health status."""
    return {
        "status": "healthy",
        "service": "AI Meeting Assistant",
    }
