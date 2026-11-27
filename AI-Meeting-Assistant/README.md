# AI Meeting Assistant

A local-first meeting MVP using FastAPI, LiveKit Cloud, React/Vite, local JSON metadata, and a silent LiveKit Agent. The root startup manager can expose the frontend and API through separate ngrok HTTPS endpoints.

## Architecture

- FastAPI handles meeting create/list/detail/join/end requests.
- `livekit-api` creates rooms, issues room-scoped participant tokens, dispatches the agent, and closes rooms.
- Meeting metadata is stored in `storage/meetings/meetings.json` with atomic file replacement.
- React uses `livekit-client` and LiveKit React components for calls and current participant state.
- The Python Agent Server subscribes to incoming audio only. Its worker permissions prohibit publishing audio, video, or data.
- No transcription, recording, summaries, database, or user accounts are included.

The LiveKit dispatch name and participant identity are both `ai-meeting-assistant`; its display name is `AI Meeting Assistant`. A successful dispatch is recorded as accepted, while the frontend displays the assistant as connected only after it appears as an actual LiveKit Agent participant.

## Environment

Copy `.env.example` to `.env` and set your LiveKit values. Keep the real `.env` private; it is not modified by the startup script.

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
LIVEKIT_AGENT_DEPLOYMENT=local-dev
NGROK_FRONTEND_URL=
NGROK_BACKEND_URL=
```

The backend and worker must use the same `LIVEKIT_AGENT_DEPLOYMENT`. The local default is `local-dev`. The startup manager passes it to both processes; when running them manually, keep the setting consistent. The current worker registers under this deployment, so `lk agent dev` with its automatically generated deployment ID will not receive dispatches targeted to `local-dev`.

`NGROK_FRONTEND_URL` and `NGROK_BACKEND_URL` are optional. Leave them blank for ngrok-assigned HTTPS URLs, or set them to distinct HTTPS domains reserved for your ngrok account.

`NGROK_WEB_ADDR` sets the ngrok local web/API bind address and defaults to `127.0.0.1:4040`. The startup manager applies it through a temporary ngrok config overlay, preserving the authtoken and other settings in ngrok's normal config.

## One-time installation

Install Python 3.11+, Node.js 20+, and Git Bash. Install ngrok on Windows and connect your account once:

```bash
winget install ngrok -s msstore
ngrok config add-authtoken "<YOUR_NGROK_AUTHTOKEN>"
```

Get the authtoken from your ngrok dashboard; do not put it in source code or share it. The startup manager reads the ngrok CLI's normal local configuration. The ngrok account is required for public tunnels. Two simultaneous public endpoints may require two account domains; if the account cannot assign two temporary URLs, reserve distinct frontend and backend domains and set the two optional URL variables.

Install project dependencies once from Git Bash at the project root:

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cd ../frontend
npm install
cd ../agent
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cd ..
```

The backend and Agent SDK use separate environments because their compatible `livekit-api` major versions differ.

## Start everything

From the project root, run one command:

```bash
python start.py
```

It starts FastAPI, waits for `/health`, starts the Agent Server and waits for its health check, starts one ngrok process, creates the backend endpoint, starts Vite with that public backend URL, and creates the frontend endpoint. It prints local and public addresses without printing credentials. Press Ctrl+C to terminate all child process trees and tunnels. If startup fails, already-started child processes are stopped.

The frontend reads `VITE_API_BASE_URL` at Vite startup. The manager sets it to the live backend tunnel URL. CORS and Vite host checks allow the supported ngrok hostnames and local development origins. The frontend receives only participant tokens and the LiveKit server URL, never the LiveKit API key or secret.

## Meeting workflow

1. Open the public frontend URL printed by `start.py` (or `http://127.0.0.1:5173` locally).
2. Enter a display name and create a meeting. The backend creates a unique LiveKit room and explicitly dispatches `ai-meeting-assistant` to that room.
3. Copy the meeting link from the call header and share it. A guest opening the link enters a display name before requesting a room-scoped token.
4. The participant list reports `AI Meeting Assistant · Connected` only when LiveKit reports its Agent participant. A failed dispatch is shown as a failure, not as a joined agent.
5. The meeting creator can end the room. The host control key is returned only by meeting creation, kept in that browser tab's session storage, and required by the end endpoint. It is omitted from list/detail responses and from the share URL.

The frontend uses `window.location.origin` to build links, so the same app produces local or public links without hardcoded tunnel URLs.

## API

- `POST /api/meetings` with `{"title":"Planning"}` creates a room, stores metadata, and dispatches the agent. Response includes `agent_dispatch_status` (`accepted` or `failed`). `accepted` means dispatch was accepted; check the LiveKit participant list for actual connection.
- `GET /api/meetings`
- `GET /api/meetings/{meeting_id}`
- `POST /api/meetings/{meeting_id}/join` with `{"participant_name":"Alex"}` returns a one-hour room-scoped token.
- `POST /api/meetings/{meeting_id}/end` with `{"host_key":"<host_key from create response>"}` closes dispatches and the room.
- `GET /health`

The meeting creation host key and join tokens are sensitive. Do not log or share them.

## Tests and builds

Run from the project root:

```bash
cd backend
./.venv/Scripts/python.exe -m unittest discover -s tests -v
./.venv/Scripts/python.exe -m compileall -q app tests
cd ..
backend/.venv/Scripts/python.exe -m unittest discover -s tests -v
cd frontend
npm test
npm run build
cd ../agent
./.venv/Scripts/python.exe -m unittest test_main -v
```

Backend tests mock LiveKit API calls; startup tests mock child processes. Frontend tests cover public API URL selection and share-link generation. These checks do not verify real LiveKit Cloud or ngrok connectivity.

## Manual external workflow

1. Configure `.env`, install the ngrok CLI, and add the ngrok authtoken once.
2. Run `python start.py` and open the printed public frontend URL.
3. Create a meeting and verify `AI Meeting Assistant · Connected` appears in the participant list (not merely a dispatch accepted response).
4. Copy the meeting link, open it on another device or network, enter a display name, and confirm the guest joins the same room.
5. End the meeting as host and confirm both the guest and agent disconnect and the meeting is marked ended.
