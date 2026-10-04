import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtempSync, writeFileSync, openSync, closeSync, existsSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {loadSources, selectLevels, parseArgs, initialGatePassed, transientBrowserError} from './extract-demos.mjs';
import {shouldRetry, worker, clearOwnedWorkerLock} from './demo-campaign.mjs';

test('all 150 levels preserve original splits and duplicate groups', () => {
  const {maps} = loadSources();
  const first = selectLevels(maps), all = selectLevels(maps, true);
  assert.deepEqual(all.slice(0, 20), first);
  assert.deepEqual(all.map(r => r.level).sort((a, b) => a - b), Array.from({length: 150}, (_, i) => i + 1));
  const duplicateMaps = [...maps]; duplicateMaps[1] = maps[0];
  const duplicate = selectLevels(duplicateMaps, true).find(r => r.level === 2);
  assert.equal(duplicate.split, 'train'); assert.equal(duplicate.duplicateOf, 1);
  assert.throws(() => parseArgs(['--pilot', '--all']), /mutually exclusive/);
});
test('all 20 must pass before expansion', () => {
  const selected = selectLevels(loadSources().maps, true);
  const manifest = {levels: Object.fromEntries(selected.slice(0, 20).map(r => [r.level, {status: 'completed'}]))};
  assert.equal(initialGatePassed(manifest, selected), true);
  manifest.levels[1].status = 'quarantined';
  assert.equal(initialGatePassed(manifest, selected), false);
  delete manifest.levels[1];
  assert.equal(initialGatePassed(manifest, selected), false);
});
test('retry budget is two and excludes fatal failures', () => {
  assert.equal(transientBrowserError(new Error('Target page, context or browser has been closed')), true);
  for (const message of ['Pilot failed', 'Runtime-store integrity check failed', 'Source/configuration changed', 'Replay wall-time watchdog expired']) assert.equal(transientBrowserError(new Error(message)), false);
  assert.equal(shouldRetry(75, null, 0), true);
  assert.equal(shouldRetry(null, 'SIGSEGV', 1), true);
  assert.equal(shouldRetry(75, null, 2), false);
  assert.equal(shouldRetry(1, null, 0), false);
  assert.equal(shouldRetry(null, 'SIGTERM', 0), false);
});
test('worker exit and lock ownership are checked', async () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'demo-supervisor-test-'));
  const fd = openSync(path.join(dir, 'log'), 'a');
  try {
    const result = await worker(process.execPath, ['-e', 'process.exit(75)'], fd);
    assert.equal(result.code, 75);
    const file = path.join(dir, '.extract.lock');
    writeFileSync(file, JSON.stringify({pid: result.pid, hostname: os.hostname()}));
    clearOwnedWorkerLock(dir, result.pid); assert.equal(existsSync(file), false);
    writeFileSync(file, JSON.stringify({pid: process.pid, hostname: os.hostname()}));
    assert.throws(() => clearOwnedWorkerLock(dir, result.pid), /not owned/);
    assert.throws(() => clearOwnedWorkerLock(dir, process.pid), /still alive/);
  } finally { closeSync(fd); }
});
