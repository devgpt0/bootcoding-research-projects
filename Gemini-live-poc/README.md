# Generic AI Interview Agent

A role-adaptive, voice-based interview application built with FastAPI and Gemini Live.

## Phase 1: run the API health check

Requires Python 3.11 or newer.

```powershell
cd C:\bootcoding-research-projects\Gemini-live-poc
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/health` or `http://127.0.0.1:8000/docs`.
The health endpoint does not need a Gemini API key. Configure credentials in `.env` before using Gemini features. The example Live model is `gemini-3.8-live`; confirm it is available to your API project before starting a session.

## Gemini Live audio contract

The backend session adapter expects raw signed 16-bit little-endian mono PCM at 16 kHz from the client. Gemini Live returns raw 16-bit little-endian mono PCM at 24 kHz. The adapter forwards audio bytes and exposes audio transcription, turn completion, and interruption events; browser capture conversion and WebSocket transport follow in the next phase.
