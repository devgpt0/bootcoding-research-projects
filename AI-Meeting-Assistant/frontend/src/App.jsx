import { useEffect, useState } from 'react';
import { Link, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { LiveKitRoom, RoomAudioRenderer, VideoConference, useConnectionState, useParticipants } from '@livekit/components-react';
import { ConnectionState, ParticipantKind } from 'livekit-client';
import { api, createMeetingShareUrl } from './api.js';

function Home() {
  const navigate = useNavigate();
  const [meetings, setMeetings] = useState([]);
  const [title, setTitle] = useState('');
  const [meetingId, setMeetingId] = useState('');
  const [name, setName] = useState(localStorage.getItem('participantName') || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.listMeetings().then(setMeetings).catch(() => {});
  }, []);

  async function createMeeting(event) {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      const meeting = await api.createMeeting(title.trim() || 'Untitled meeting');
      saveName();
      if (meeting.host_key) {
        sessionStorage.setItem(`meeting-host:${meeting.meeting_id}`, meeting.host_key);
      }
      navigate(`/meeting/${meeting.meeting_id}?name=${encodeURIComponent(name.trim())}&host=1`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function saveName() {
    if (name.trim()) localStorage.setItem('participantName', name.trim());
  }

  function joinMeeting(event) {
    event.preventDefault();
    setError('');
    if (!meetingId.trim() || !name.trim()) {
      setError('Enter your name and a meeting ID.');
      return;
    }
    saveName();
    navigate(`/meeting/${encodeURIComponent(meetingId.trim())}?name=${encodeURIComponent(name.trim())}`);
  }

  return (
    <main className="home-shell">
      <nav className="topbar"><Link to="/" className="brand"><span className="brand-mark">✦</span> Gatherly <span className="brand-label">AI MEETING ASSISTANT</span></Link><span className="online-label"><i /> All systems ready</span></nav>
      <section className="hero">
        <div className="eyebrow"><span>✦</span> MAKE SPACE FOR GREAT IDEAS</div>
        <h1>Meet better.<br /><em>Think together.</em></h1>
        <p className="hero-copy">A calmer place to bring people together. Start a room or join your team in seconds.</p>
        <div className="name-field"><label htmlFor="participant-name">YOUR NAME</label><input id="participant-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="How should we call you?" maxLength={80} /></div>
        <div className="action-grid">
          <form className="action-card create-card" onSubmit={createMeeting}>
            <div className="card-icon violet">✦</div><span className="card-kicker">START FRESH</span><h2>Create a meeting</h2><p>Open a new room and invite your team.</p>
            <input aria-label="Meeting title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Give it a name (optional)" maxLength={200} />
            <button className="button primary" disabled={busy || !name.trim()}>{busy ? 'Creating room…' : 'Create meeting'} <span>↗</span></button>
          </form>
          <form className="action-card join-card" onSubmit={joinMeeting}>
            <div className="card-icon mint">↗</div><span className="card-kicker">HAVE AN INVITE?</span><h2>Join a meeting</h2><p>Enter the meeting ID shared with you.</p>
            <input aria-label="Meeting ID" value={meetingId} onChange={(e) => setMeetingId(e.target.value)} placeholder="Paste meeting ID" />
            <button className="button secondary" disabled={!name.trim() || !meetingId.trim()}>Join meeting <span>→</span></button>
          </form>
        </div>
        {error && <div className="alert" role="alert">{error}</div>}
        {meetings.length > 0 && <section className="recent"><div className="recent-heading"><h2>Recent meetings</h2><span>Pick up where you left off</span></div><div className="recent-list">{meetings.slice().reverse().slice(0, 4).map((meeting) => <button key={meeting.meeting_id} className="recent-item" onClick={() => setMeetingId(meeting.meeting_id)} disabled={meeting.status === 'ending' || meeting.status === 'ended' || Boolean(meeting.ended_at)}><span className="recent-dot">◉</span><span className="recent-title">{meeting.title}</span><code>{meeting.meeting_id.slice(0, 8)}…</code><span className="recent-arrow">→</span></button>)}</div></section>}
      </section>
      <footer>Thoughtful meetings, powered by LiveKit <span>·</span> Your conversations stay yours</footer>
    </main>
  );
}

function RoomStats({ meeting, host, onEnd }) {
  const participants = useParticipants();
  const connection = useConnectionState();
  const assistant = participants.find((participant) => participant.kind === ParticipantKind.AGENT);
  const label = connection === ConnectionState.Connected ? 'Connected' : connection === ConnectionState.Connecting ? 'Connecting' : connection;
  return <div className="room-details">
    <div className="room-meta"><span className={`connection-pill ${connection === ConnectionState.Connected ? 'connected' : ''}`}><i />{label}</span><span>{participants.length} participant{participants.length === 1 ? '' : 's'}</span><span className={`assistant-state ${assistant ? 'connected' : ''}`}><i />AI Meeting Assistant · {assistant ? 'Connected' : meeting.agent_dispatch_status === 'failed' ? 'Dispatch failed' : 'Waiting'}</span></div>
    <div className="participant-list" aria-label="Current participants">{participants.map((participant) => {
      const isAssistant = participant.kind === ParticipantKind.AGENT;
      return <span className="participant-chip" key={participant.identity}>{isAssistant ? '✦ AI Meeting Assistant' : participant.name || participant.identity}</span>;
    })}</div>
  </div>;
}

function Meeting() {
  const { meetingId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [meeting, setMeeting] = useState(null);
  const [credentials, setCredentials] = useState(null);
  const [error, setError] = useState('');
  const [endError, setEndError] = useState('');
  const [participantName, setParticipantName] = useState(
    searchParams.get('name') || localStorage.getItem('participantName') || '',
  );
  const [nameInput, setNameInput] = useState(participantName);
  const [ending, setEnding] = useState(false);
  const isHost = searchParams.get('host') === '1'
    && Boolean(sessionStorage.getItem(`meeting-host:${meetingId}`));

  useEffect(() => {
    if (!participantName.trim()) return undefined;
    let active = true;
    async function connect() {
      try {
        const [details, access] = await Promise.all([
          api.getMeeting(meetingId),
          api.joinMeeting(meetingId, participantName.trim()),
        ]);
        if (active) { setMeeting(details); setCredentials(access); }
      } catch (err) {
        if (active) setError(err.message);
      }
    }
    connect();
    return () => { active = false; };
  }, [meetingId, participantName]);

  function joinWithName(event) {
    event.preventDefault();
    const value = nameInput.trim();
    if (!value) return;
    localStorage.setItem('participantName', value);
    setParticipantName(value);
  }

  async function endMeeting() {
    setEnding(true);
    try {
      await api.endMeeting(meetingId, sessionStorage.getItem(`meeting-host:${meetingId}`));
      sessionStorage.removeItem(`meeting-host:${meetingId}`);
      setError('The host ended this meeting.');
    } catch (err) {
      setEndError(err.message);
      setEnding(false);
    }
  }

  async function handleRoomDisconnect() {
    try {
      const latest = await api.getMeeting(meetingId);
      if (latest.ended_at || latest.status === 'ending' || latest.status === 'ended') {
        setError('This meeting has ended.');
        return;
      }
    } catch {
      // A normal leave should still return to the home page if metadata is unavailable.
    }
    navigate('/');
  }

  if (error) return <main className="error-screen"><div className="alert" role="alert">{error}</div><button className="button secondary retry-button" onClick={() => window.location.reload()}>Try again</button><Link to="/" className="button primary">Back home</Link></main>;
  if (!participantName.trim()) return <main className="join-screen"><form className="join-prompt" onSubmit={joinWithName}><span className="eyebrow">MEETING INVITATION</span><h1>Join this meeting</h1><p>Choose the name other participants will see.</p><input autoFocus value={nameInput} onChange={(event) => setNameInput(event.target.value)} maxLength={80} placeholder="Your display name"/><button className="button primary" disabled={!nameInput.trim()}>Continue to meeting <span>→</span></button></form></main>;
  if (!meeting || !credentials) return <main className="loading-screen"><span className="spinner" /><p>Preparing your meeting…</p></main>;

  return (
    <main className="meeting-shell">
      <LiveKitRoom token={credentials.token} serverUrl={credentials.server_url} connect audio video onError={(err) => setError(err.message)} onDisconnected={handleRoomDisconnect} data-lk-theme="default" className="livekit-room">
        <header className="meeting-header"><Link to="/" className="brand"><span className="brand-mark">✦</span> Gatherly</Link><div><h1>{meeting.title}</h1><RoomStats meeting={meeting} />{endError && <span className="end-error" role="alert">{endError}</span>}</div><div className="meeting-actions"><button className="copy-button" onClick={() => navigator.clipboard.writeText(createMeetingShareUrl(meeting.meeting_id)).catch(() => {})}>Copy meeting link</button>{isHost && <button className="end-button" onClick={endMeeting} disabled={ending}>{ending ? 'Ending…' : 'End meeting'}</button>}</div></header>
        <RoomAudioRenderer />
        <VideoConference />
      </LiveKitRoom>
    </main>
  );
}

export default function App() {
  return <Routes><Route path="/" element={<Home />} /><Route path="/meeting/:meetingId" element={<Meeting />} /></Routes>;
}
