export function resolveApiBaseUrl(configured = import.meta.env?.VITE_API_BASE_URL) {
  return (configured || 'http://localhost:8000').replace(/\/+$/, '');
}

export function createMeetingShareUrl(meetingId, origin = window.location.origin) {
  return new URL(`/meeting/${encodeURIComponent(meetingId)}`, origin).toString();
}

const API_BASE = resolveApiBaseUrl();

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

export const api = {
  listMeetings: () => request('/api/meetings'),
  getMeeting: (id) => request(`/api/meetings/${encodeURIComponent(id)}`),
  createMeeting: (title) => request('/api/meetings', {
    method: 'POST', body: JSON.stringify({ title }),
  }),
  joinMeeting: (id, participant_name) => request(`/api/meetings/${encodeURIComponent(id)}/join`, {
    method: 'POST', body: JSON.stringify({ participant_name }),
  }),
  endMeeting: (id, host_key) => request(`/api/meetings/${encodeURIComponent(id)}/end`, {
    method: 'POST', body: JSON.stringify({ host_key }),
  }),
};
