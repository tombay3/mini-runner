import assert from 'node:assert/strict';
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { root, loadSources, selectLevels, parseArgs, validateReplay, replayData, hash, verifyFiles } from './extract-demos.mjs';

test('fixture matches replay data and Classic selection is deterministic', () => {
  const {demos, maps} = loadSources();
  assert.equal(demos.length, 150);
  const selected = selectLevels(maps);
  assert.equal(selected.length, 20);
  assert.equal(selected[0].level, 1);
  assert.equal(selected[19].level, 150);
  assert.equal(new Set(selected.map(s => s.level)).size, 20);
  assert.deepEqual(['train', 'validation', 'test'].map(split => selected.filter(s => s.split === split).length), [12, 4, 4]);
  assert.equal('ip' in demos[0], false);
  assert.equal(hash(replayData({...demos[0], player: 'ignored'})), hash(demos[0]));
});

test('identical maps stay in the first partition, including level 1', () => {
  const maps = Array.from({length: 150}, (_, i) => String(i));
  maps[149] = maps[0];
  const selected = selectLevels(maps);
  assert.equal(selected.at(-1).split, 'train');
  assert.equal(selected.at(-1).duplicateOf, 1);
});

test('resume and argument validation', () => {
  assert.throws(() => parseArgs(['--resume']), /requires --output/);
  assert.throws(() => parseArgs(['--output']), /incomplete/);
  assert.throws(() => parseArgs(['--target', '1']), /Unknown/);
  assert.equal(parseArgs(['--pilot', '--output', '/tmp/demo']).pilot, true);
});

test('mode, outcome, gold, duration and timeline violations fail replay validation', () => {
  const demo = {level: 1, state: 1, time: 20, godMode: 0, ai: 4};
  const state = {playData: 1, level: 1, godMode: false, tick: 0};
  const terminal = {...state, tick: 20, gameStateName: 'finish', goldComplete: true, goldCount: 0};
  const good = {states: [state, terminal], terminal, aiVersion: 4};
  assert.equal(validateReplay(good, demo, 20).valid, true);
  for (const bad of [
    {...good, terminal: {...terminal, gameStateName: 'running'}},
    {...good, terminal: {...terminal, goldCount: 1}},
    {...good, terminal: {...terminal, tick: 21}},
    {...good, aiVersion: 3},
    {...good, states: [state, {...terminal, godMode: true}]},
    {...good, states: [state, {...terminal, level: 2}]},
    {...good, states: [state, state]},
    {...good, states: [state, {...terminal, tick: 21}]},
  ]) assert.equal(validateReplay(bad, demo, 20).valid, false);
});

test('completed artifact verification rejects missing and modified content', () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'demo-extraction-test-'));
  writeFileSync(path.join(dir, 'states.jsonl'), 'original');
  const files = {'states.jsonl': hash('original')};
  assert.equal(verifyFiles(dir, files), true);
  writeFileSync(path.join(dir, 'states.jsonl'), 'changed');
  assert.equal(verifyFiles(dir, files), false);
  assert.equal(verifyFiles(dir, {'missing.json': hash('')}), false);
});

test('offline adapter preserves input, ranking and history semantics', () => {
  const result = spawnSync(process.env.DEMO_PYTHON || path.join(root, '.venv/bin/python'),
    [path.join(root, 'scripts/demo_candidates_test.py')], {encoding: 'utf8', env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'}});
  assert.equal(result.status, 0, result.stderr || String(result.error));
});
