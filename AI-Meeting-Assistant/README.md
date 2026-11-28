# AI Meeting Assistant

A local-first meeting MVP using FastAPI, LiveKit Cloud, React/Vite, local JSON metadata, and a LiveKit transcription agent.

## Architecture

- FastAPI handles meeting create/list/detail/join/end requests.
- `livekit-api` creates rooms, issues room-scoped participant tokens, dispatches the agent, and closes rooms.
- Meeting metadata is stored in `storage/meetings/meetings.json` with atomic file replacement.
- React uses `livekit-client` and LiveKit React components for calls and current participant state.
- The Python Agent Server subscribes to incoming audio and transcribes speech with LiveKit Inference. It does not publish audio, video, or data.
- Final transcript segments are appended to `storage/transcripts/<room-name>.txt` with local timestamps. When the meeting ends, LiveKit Inference creates a summary at `storage/summaries/<room-name>.txt`.
- Audio recordings, database, and user accounts are not included.

The LiveKit dispatch name and participant identity are both `ai-meeting-assistant`; its display name is `AI Meeting Assistant`. A successful dispatch is recorded as accepted, while the frontend displays the assistant as connected only after it appears as an actual LiveKit Agent participant.

## Environment

Copy `.env.example` to `.env` and set your LiveKit values. Keep the real `.env` private; it is not modified by the startup script.

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
LIVEKIT_AGENT_DEPLOYMENT=local-dev
```

The backend and worker must use the same `LIVEKIT_AGENT_DEPLOYMENT`. The local default is `local-dev`. The startup manager passes it to both processes; when running them manually, keep the setting consistent. The current worker registers under this deployment, so `lk agent dev` with its automatically generated deployment ID will not receive dispatches targeted to `local-dev`.

## One-time installation

Install Python 3.11+, Node.js 20+, and Git Bash.

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

It starts FastAPI, waits for `/health`, starts the Agent Server and waits for its health check, then starts Vite. Open `http://127.0.0.1:5173` to use the app locally. Press Ctrl+C to terminate all child process trees. If startup fails, already-started child processes are stopped.

The frontend connects to the local backend at `http://127.0.0.1:8000` by default. If that port is occupied, the startup manager selects an available local port and passes it to Vite. CORS allows the local frontend origins. The frontend receives only participant tokens and the LiveKit server URL, never the LiveKit API key or secret.

## Meeting workflow

1. Open `http://127.0.0.1:5173`.
2. Enter a display name and create a meeting. The backend creates a unique LiveKit room and explicitly dispatches `ai-meeting-assistant` to that room.
3. Copy the meeting link from the call header and share it. A guest opening the link enters a display name before requesting a room-scoped token.
4. The participant list reports `AI Meeting Assistant · Connected` only when LiveKit reports its Agent participant. A failed dispatch is shown as a failure, not as a joined agent.
5. The meeting creator can end the room. The host control key is returned only by meeting creation, kept in that browser tab's session storage, and required by the end endpoint. It is omitted from list/detail responses and from the share URL.

The frontend uses `window.location.origin` to build local meeting links.

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

Backend tests mock LiveKit API calls; startup tests mock child processes. Frontend tests cover local API URL selection and share-link generation. These checks do not verify real LiveKit Cloud connectivity.

## Manual external workflow

1. Configure `.env` with LiveKit credentials.
2. Run `python start.py` and open `http://127.0.0.1:5173`.
3. Create a meeting and verify `AI Meeting Assistant · Connected` appears in the participant list (not merely a dispatch accepted response).
4. Copy the local meeting link and open it in another browser on this computer; enter a display name and confirm the guest joins the same room.
5. End the meeting as host and confirm both the guest and agent disconnect and the meeting is marked ended.
