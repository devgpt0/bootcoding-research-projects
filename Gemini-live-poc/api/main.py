
"""FastAPI application entry point for the interview agent."""

import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.config import settings
from api.interview import live_router, router as interview_router


# Initialize FastAPI application
app = FastAPI(
    title="Generic AI Interview Agent",
    description="Real-time, role-adaptive interview agent powered by Gemini Live.",
    version="0.1.0",
)

# Register interview WebSocket routes
app.include_router(interview_router)
app.include_router(live_router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/interview", include_in_schema=False)
async def interview_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "interview.html")


# Health check endpoint
@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return application health status."""
    return {
        "status": "ok",
        "service": settings.app_name,
    }


# Start Uvicorn when this file is executed as a module
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=getattr(settings, "host", "127.0.0.1"),
        port=getattr(settings, "port", 8000),
        reload=True,
    )
