import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, existsSync, mkdirSync, renameSync, readdirSync,
  mkdtempSync, realpathSync, openSync, closeSync, unlinkSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { replayInPage } from './demo-replay.mjs';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const hash = value => createHash('sha256').update(typeof value === 'string' || Buffer.isBuffer(value)
  ? value : JSON.stringify(value)).digest('hex');
const replayFields = ['level', 'ai', 'time', 'state', 'godMode', 'action', 'goldDrop', 'bornPos'];
export const replayData = demo => Object.fromEntries(replayFields.map(key => [key, demo[key]]));
const json = file => JSON.parse(readFileSync(file, 'utf8'));
const atomic = (file, value) => {
  const temporary = `${file}.${process.pid}.tmp`;
  writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n');
  renameSync(temporary, file);
};
const git = (...args) => {
  const result = spawnSync('git', args, {cwd: root, encoding: 'utf8'});
  if (result.status !== 0) throw new Error(result.stderr || 'git failed');
  return result.stdout.trim();
};

export function loadSources() {
  const context = vm.createContext({});
  for (const name of ['lodeRunner.wData.js', 'lodeRunner.v.classic.js']) {
    const buffer = readFileSync(path.join(root, 'public/game', name));
    vm.runInContext(buffer.toString(buffer[0] === 255 && buffer[1] === 254 ? 'utf16le' : 'utf8'),
      context, {timeout: 1000});
  }
  const demos = JSON.parse(JSON.stringify(context.wfastDemoData1)).map(replayData);
  const maps = JSON.parse(JSON.stringify(context.classicData));
  const fixture = Object.values(json(path.join(root, 'docs/fast-demo1.json')).records)[0];
  if (fixture.playData !== 1 || hash(replayData(fixture.demo)) !== hash(demos.find(d => d.level === 1))) {
    throw new Error('Level-1 fixture does not match wfastDemoData1');
  }
  return {demos, maps};
}

export function selectLevels(maps) {
  const seen = new Map();
  return Array.from({length: 20}, (_, i) => {
    const level = 1 + Math.round(i * 149 / 19);
    const mapHash = hash(maps[level - 1]);
    const intendedSplit = i % 5 === 4 ? 'test' : i % 5 === 3 ? 'validation' : 'train';
    const prior = seen.get(mapHash);
    const row = {level, mapHash, intendedSplit, split: prior?.split ?? intendedSplit,
      duplicateOf: prior?.level ?? null};
    seen.set(mapHash, prior ?? row);
    return row;
  });
}

export function parseArgs(args) {
  const options = {pilot: false, resume: false, browserExecutable: process.env.CHROME_PATH,
    python: process.env.DEMO_PYTHON || path.join(root, '.venv/bin/python')};
  const names = {'--output': 'output', '--browser-executable': 'browserExecutable', '--python': 'python'};
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--pilot') options.pilot = true;
    else if (arg === '--resume') options.resume = true;
    else if (arg === '--help') options.help = true;
    else if (names[arg] && args[i + 1] && !args[i + 1].startsWith('--')) options[names[arg]] = args[++i];
    else throw new Error(`Unknown or incomplete argument: ${arg}`);
  }
  if (options.resume && !options.output) throw new Error('--resume requires --output');
  return options;
}

export function validateReplay(replay, demo, maxTicks) {
  const errors = [];
  const expected = demo.state === 1 ? 'finish' : 'runner_dead';
  if (replay.terminal.gameStateName !== expected) errors.push('terminal outcome mismatch');
  if (replay.terminal.tick !== demo.time) errors.push('recorded terminal tick mismatch');
  if (replay.aiVersion !== demo.ai) errors.push('AI version mismatch');
  if (demo.state === 1 && (!replay.terminal.goldComplete || replay.terminal.goldCount !== 0)) errors.push('incomplete gold');
  for (const s of [...replay.states, replay.terminal]) {
    if (s.playData !== 1 || s.level !== demo.level || s.godMode !== Boolean(demo.godMode)) errors.push('context/mode mismatch');
  }
  for (let i = 1; i < replay.states.length; i++) {
    const s = replay.states[i];
    if (i && (s.tick <= replay.states[i - 1].tick || s.tick - replay.states[i - 1].tick > maxTicks)) errors.push('sample timeline mismatch');
  }
  return {valid: errors.length === 0, errors: [...new Set(errors)]};
}

function treeHashes(directory) {
  const result = {};
  if (!existsSync(directory)) return result;
  const visit = dir => {
    for (const entry of readdirSync(dir, {withFileTypes: true})) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) { if (entry.name !== '__pycache__') visit(file); }
      else if (entry.isFile()) result[path.relative(directory, file)] = hash(readFileSync(file));
    }
  };
  visit(directory);
  return result;
}

function provenance(config) {
  return {revision: git('rev-parse', 'HEAD'), branch: git('branch', '--show-current'),
    status: git('status', '--porcelain'), dirtyDiffFingerprint: hash(git('diff', 'HEAD', '--binary')),
    sourceHashes: {bootstrap: hash(readFileSync(path.join(root, 'src/app.js'))),
      fixture: hash(readFileSync(path.join(root, 'docs/fast-demo1.json'))),
      agent: treeHashes(path.join(root, 'agent')), runtime: treeHashes(path.join(root, 'public/game')),
      scripts: Object.fromEntries(['extract-demos.mjs', 'demo-replay.mjs', 'demo-candidates.py'].map(name =>
        [name, hash(readFileSync(path.join(root, 'scripts', name)))]))}, config};
}

async function serve() {
  // Use the same legacy load order, but never load app.js or recording.js.
  const source = readFileSync(path.join(root, 'src/app.js'), 'utf8');
  const block = source.match(/const legacyScripts = \[([\s\S]*?)\];/);
  if (!block) throw new Error('Cannot locate legacy bootstrap script list');
  const scripts = [...block[1].matchAll(/"(\/game\/[^"\n]+)"/g)].map(m => m[1]);
  const html = '<!doctype html><html><head><base href="/game/"></head><body><canvas id="canvas"></canvas>' +
    scripts.map(src => `<script src="${src}"></script>`).join('') + '<script>init();</script></body></html>';
  const server = createServer((req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    if (req.method !== 'GET') { res.writeHead(405); res.end(); return; }
    if (pathname === '/') { res.setHeader('Content-Type', 'text/html'); res.end(html); return; }
    const file = path.resolve(root, 'public', '.' + decodeURIComponent(pathname));
    const allowed = path.join(root, 'public/game') + path.sep;
    if (!file.startsWith(allowed) || !existsSync(file)) { res.writeHead(404); res.end(); return; }
    try {
      let data = readFileSync(file);
      const types = {'.js': 'text/javascript; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg',
        '.gif': 'image/gif', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.json': 'application/json'};
      res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
      if (path.extname(file) === '.js' && data[0] === 255 && data[1] === 254) data = Buffer.from(data.toString('utf16le'));
      res.end(data);
    } catch { res.writeHead(404); res.end(); }
  });
  await new Promise((resolve, reject) => {server.once('error', reject); server.listen(0, '127.0.0.1', resolve);});
  return {server, url: `http://127.0.0.1:${server.address().port}/`};
}

async function replay(browser, url, demo, config, capture) {
  const page = await browser.newPage({viewport: {width: 1280, height: 720}, serviceWorkers: 'block'});
  const forbidden = [], pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.route('**/*', route => {
    const request = route.request(), target = new URL(request.url());
    if (target.origin !== new URL(url).origin || request.method() !== 'GET' || target.pathname.startsWith('/api/')) {
      forbidden.push({method: request.method(), url: request.url()});
      return route.abort();
    }
    return route.continue();
  });
  try {
    await page.goto(url, {waitUntil: 'load', timeout: 60000});
    await page.waitForFunction(() => window.lodeRunnerAgentHooks?.isReady(), null, {timeout: 60000});
    const result = await page.evaluate(replayInPage, {demo, maxTicks: config.backend.maxActionTicks, capture});
    if (forbidden.length || pageErrors.length) throw new Error(JSON.stringify({forbidden, pageErrors}));
    return result;
  } finally { await page.close(); }
}

function analyze(states, demo, config, python) {
  const start = performance.now();
  const result = spawnSync(python, [path.join(root, 'scripts/demo-candidates.py')], {
    cwd: root, input: JSON.stringify({states, demo, config}), encoding: 'utf8',
    maxBuffer: 128 * 1024 * 1024, timeout: 120000,
    env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'},
  });
  if (result.status !== 0) throw new Error(`Candidate adapter failed: ${result.error || result.stderr}`);
  return {...JSON.parse(result.stdout), elapsedMs: performance.now() - start};
}

export function verifyFiles(directory, files) {
  return Object.entries(files).every(([file, expected]) => existsSync(path.join(directory, file)) &&
    hash(readFileSync(path.join(directory, file))) === expected);
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log('npm run demos:extract -- [--pilot] [--output ABSOLUTE_DIRECTORY] [--resume] [--browser-executable PATH] [--python PATH]');
    return;
  }
  const {demos, maps} = loadSources();
  const config = json(path.join(root, 'public/agent-config.json'));
  const selected = selectLevels(maps);
  const source = provenance(config);
  const datasetId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${source.revision.slice(0, 7)}`;
  const output = path.resolve(options.output || path.join(os.homedir(), 'runner1-experiments/demo-scoring', datasetId));
  // Resolve existing ancestors to catch output paths symlinked into any worktree.
  let ancestor = output;
  while (!existsSync(ancestor)) ancestor = path.dirname(ancestor);
  const resolved = path.join(realpathSync(ancestor), path.relative(ancestor, output));
  const worktrees = git('worktree', 'list', '--porcelain').split('\n').filter(s => s.startsWith('worktree ')).map(s => s.slice(9));
  if (worktrees.some(dir => resolved === realpathSync(dir) || resolved.startsWith(realpathSync(dir) + path.sep))) {
    throw new Error('Output must be outside repository worktrees');
  }
  if (!options.resume && existsSync(output) && readdirSync(output).length) throw new Error('Output is not empty; use --resume');
  if (options.resume && !existsSync(path.join(output, 'manifest.json'))) throw new Error('No manifest to resume');
  mkdirSync(output, {recursive: true});
  const lock = path.join(output, '.extract.lock');
  const fd = openSync(lock, 'wx');
  writeFileSync(fd, JSON.stringify({pid: process.pid, hostname: os.hostname(), startedAt: new Date().toISOString()}));
  closeSync(fd);
  let browser, server, heartbeat, manifest;
  const beforeStores = treeHashes(path.join(root, '__data1'));
  const manifestFile = path.join(output, 'manifest.json');
  const pythonVersion = spawnSync(options.python, ['--version'], {encoding: 'utf8'});
  try {
    if (pythonVersion.status !== 0) throw new Error(`Python unavailable: ${options.python}`);
    const {chromium} = await import('playwright-core');
    browser = await chromium.launch({headless: true, executablePath: options.browserExecutable});
    const environment = {node: process.version, python: pythonVersion.stdout.trim(), browser: browser.version(), platform: process.platform};
    const identity = hash({schema: 1, source, selected, environment});
    if (options.resume) {
      const prior = json(manifestFile);
      if (prior.identity !== identity) throw new Error('Incompatible source/configuration/runtime; create a new dataset');
      manifest = prior;
      manifest.status = 'running';
      delete manifest.failure;
    } else {
      manifest = {schemaVersion: 1, datasetId, identity, source, environment, selected, levels: {}, pilot: null,
        startedAt: new Date().toISOString(), status: 'running'};
      atomic(manifestFile, manifest);
      atomic(path.join(output, 'splits.json'), selected);
    }
    const hosted = await serve(); server = hosted.server;
    let active = 'startup';
    heartbeat = setInterval(() => console.log(`active: ${active}`), 30000);
    console.log(`Dataset: ${output}\nSource: ${source.branch} ${source.revision}\n${source.status || 'Worktree clean'}`);
    const runLevel = async (level, pilot = false) => {
      const name = `classic-${String(level).padStart(3, '0')}`;
      const dir = path.join(output, 'levels', name);
      const previous = manifest.levels[level];
      if (previous?.status === 'completed') {
        if (!verifyFiles(dir, previous.files)) throw new Error(`Corrupted completed artifacts: ${name}`);
        console.log(`verified: level ${level}`); return;
      }
      const demo = demos.find(d => d.level === level);
      if (!demo) throw new Error(`Missing demo: ${level}`);
      active = `level ${level}${pilot ? ' pilot control replay' : ''}`;
      manifest.levels[level] = {status: 'running'}; atomic(manifestFile, manifest);
      const control = pilot ? await replay(browser, hosted.url, demo, config, false) : null;
      active = `level ${level} extraction replay`;
      const result = await replay(browser, hosted.url, demo, config, true);
      const validation = validateReplay(result, demo, config.backend.maxActionTicks);
      if (control) {
        const controlValidation = validateReplay(control, demo, config.backend.maxActionTicks);
        if (!controlValidation.valid || hash(control.checkpoints) !== hash(result.checkpoints)) {
          validation.valid = false; validation.errors.push('control/extraction replay mismatch');
        }
      }
      active = `level ${level} candidate analysis`;
      const analysis = validation.valid ? analyze(result.states, demo, config, options.python) : null;
      if (hash(beforeStores) !== hash(treeHashes(path.join(root, '__data1')))) throw new Error('Runtime stores changed during extraction');
      mkdirSync(path.join(output, 'levels'), {recursive: true});
      const staging = mkdtempSync(path.join(output, 'levels', `.${name}-`));
      const metadata = {level, playData: 1, split: selected.find(s => s.level === level).split,
        demo, demoHash: hash(demo), mapHash: hash(maps[level - 1]), validation,
        elapsedMs: result.elapsedMs, analysisMs: analysis?.elapsedMs ?? 0,
        controlElapsedMs: control?.elapsedMs ?? 0, terminal: result.terminal,
        aiVersion: result.aiVersion, demoSpeed: result.demoSpeed,
        checkpointHash: hash(result.checkpoints), controlCheckpointHash: control ? hash(control.checkpoints) : null,
        goldCursor: result.goldCursor, bornCursor: result.bornCursor};
      atomic(path.join(staging, 'metadata.json'), metadata);
      atomic(path.join(staging, 'coverage.json'), analysis?.coverage ?? {usableLabels: 0});
      for (const [file, rows] of [['states.jsonl', result.states], ['decisions.jsonl', analysis?.decisions ?? []],
        ['checkpoints.jsonl', result.checkpoints]]) {
        writeFileSync(path.join(staging, file), rows.map(r => JSON.stringify(r)).join('\n') + (rows.length ? '\n' : ''));
      }
      const files = treeHashes(staging);
      if (existsSync(dir)) renameSync(dir, `${dir}.previous-${Date.now()}`);
      renameSync(staging, dir);
      manifest.levels[level] = {status: validation.valid ? 'completed' : 'quarantined', files,
        validation, usableLabels: analysis?.coverage.usableLabels ?? 0,
        elapsedMs: result.elapsedMs, analysisMs: analysis?.elapsedMs ?? 0};
      if (pilot) manifest.pilot = {passed: validation.valid, checkpointHash: metadata.checkpointHash};
      atomic(manifestFile, manifest);
      console.log(`level ${level}: ${manifest.levels[level].status}; labels=${analysis?.coverage.usableLabels ?? 0}; replay=${Math.round(result.elapsedMs)}ms; analysis=${Math.round(analysis?.elapsedMs ?? 0)}ms`);
      if (pilot && !validation.valid) throw new Error(`Pilot failed: ${validation.errors.join(', ')}`);
    };
    if (!manifest.pilot?.passed) await runLevel(1, true);
    else {
      if (!verifyFiles(path.join(output, 'levels/classic-001'), manifest.levels[1].files)) throw new Error('Pilot artifacts corrupted');
    }
    if (!options.pilot) for (const {level} of selected) await runLevel(level);
    if (hash(source) !== hash(provenance(json(path.join(root, 'public/agent-config.json'))))) {
      throw new Error('Source/configuration changed during extraction; create a new dataset');
    }
    const entries = Object.values(manifest.levels);
    const summary = {completed: entries.filter(e => e.status === 'completed').length,
      failed: entries.filter(e => e.status === 'quarantined').length,
      usableLabels: entries.reduce((n, e) => n + (e.usableLabels || 0), 0),
      partitionSizes: Object.fromEntries(['train', 'validation', 'test'].map(split => [split, selected.filter(s => s.split === split).length])),
      estimated100LevelMs: entries.reduce((n, e) => n + e.elapsedMs + e.analysisMs, 0) / entries.length * 100,
      estimateBasis: 'Observed replay + analysis mean; excludes setup and pilot control replay; level durations vary.',
      readyForTrainingReview: !options.pilot && entries.length === 20 && entries.every(e => e.status === 'completed') && entries.some(e => e.usableLabels > 0)};
    mkdirSync(path.join(output, 'reports'), {recursive: true});
    atomic(path.join(output, 'reports/summary.json'), summary);
    manifest.status = options.pilot ? 'pilot_complete' : summary.failed ? 'complete_with_quarantine' : 'complete';
    manifest.finishedAt = new Date().toISOString(); atomic(manifestFile, manifest);
    console.log(JSON.stringify(summary, null, 2));
  } catch (error) {
    if (manifest) {
      manifest.status = 'failed'; manifest.failure = error.message; atomic(manifestFile, manifest);
      mkdirSync(path.join(output, 'reports'), {recursive: true});
      atomic(path.join(output, 'reports/failure.json'), {failure: error.message, levels: manifest.levels});
    }
    throw error;
  } finally {
    clearInterval(heartbeat);
    await browser?.close();
    if (server) await new Promise(resolve => server.close(resolve));
    unlinkSync(lock);
    if (hash(beforeStores) !== hash(treeHashes(path.join(root, '__data1')))) throw new Error('Runtime-store integrity check failed');
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {console.error(error.stack); process.exitCode = 1;});
}
