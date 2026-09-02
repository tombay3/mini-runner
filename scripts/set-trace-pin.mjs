const [operation, recordId, ...extra] = process.argv.slice(2);

if (!['pin', 'unpin'].includes(operation) || !recordId?.trim() || extra.length) {
  console.error('Usage: npm run trace:pin -- <full-or-unique-prefix>');
  console.error('   or: npm run trace:unpin -- <full-or-unique-prefix>');
  process.exit(1);
}

const apiBaseUrl = (process.env.TRACE_API_BASE_URL || 'http://127.0.0.1:8485').replace(/\/$/, '');

try {
  const response = await fetch(`${apiBaseUrl}/api/recordings/1/1/pin`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ recordId: recordId.trim(), pinned: operation === 'pin' }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `backend returned HTTP ${response.status}`);
  }
  console.log(`${operation === 'pin' ? 'pinned' : 'unpinned'} ${payload.recordId}`);
} catch (error) {
  console.error(`Unable to ${operation} recording: ${error.message}`);
  console.error('Ensure the backend is running with npm run api.');
  process.exit(1);
}
