import test from 'node:test';
import assert from 'node:assert/strict';
import { createMeetingShareUrl, resolveApiBaseUrl } from '../src/api.js';

test('API base URL uses the public backend URL when configured', () => {
  assert.equal(
    resolveApiBaseUrl('https://api-sample.ngrok.app/'),
    'https://api-sample.ngrok.app',
  );
});

test('API base URL keeps the local development default', () => {
  assert.equal(resolveApiBaseUrl(''), 'http://localhost:8000');
});

test('share URL is built from the current public frontend origin', () => {
  assert.equal(
    createMeetingShareUrl('room id/1', 'https://web-sample.ngrok.app'),
    'https://web-sample.ngrok.app/meeting/room%20id%2F1',
  );
});
