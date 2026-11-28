import test from 'node:test';
import assert from 'node:assert/strict';
import { createMeetingShareUrl, resolveApiBaseUrl } from '../src/api.js';

test('API base URL uses the configured local backend URL', () => {
  assert.equal(
    resolveApiBaseUrl('http://127.0.0.1:8000/'),
    'http://127.0.0.1:8000',
  );
});

test('API base URL keeps the local development default', () => {
  assert.equal(resolveApiBaseUrl(''), 'http://localhost:8000');
});

test('share URL is built from the current local frontend origin', () => {
  assert.equal(
    createMeetingShareUrl('room id/1', 'http://127.0.0.1:5173'),
    'http://127.0.0.1:5173/meeting/room%20id%2F1',
  );
});
