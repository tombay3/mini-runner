// Local supervision: polling and retries do not require Codex/model turns.
import {spawn} from 'node:child_process';
import {existsSync, mkdirSync, openSync, closeSync, readFileSync, writeFileSync, renameSync, unlinkSync, realpathSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseArgs, root} from './extract-demos.mjs';

const read = file => JSON.parse(readFileSync(file, 'utf8'));
const save = (file, data) => {
  writeFileSync(`${file}.tmp`, JSON.stringify(data, null, 2) + '\n');
  renameSync(`${file}.tmp`, file);
};
export const shouldRetry = (code, signal, retries) => retries < 2 && (code === 75 || ['SIGSEGV', 'SIGABRT'].includes(signal));

export function clearOwnedWorkerLock(output, pid) {
  const file = path.join(output, '.extract.lock');
  if (!existsSync(file)) return;
  const lock = read(file);
  if (lock.pid !== pid || lock.hostname !== os.hostname()) throw new Error('Extraction lock is not owned by this supervisor');
  try { process.kill(pid, 0); }
  catch (error) {
    if (error.code !== 'ESRCH') throw error;
    unlinkSync(file); return;
  }
  throw new Error('Previous extraction process is still alive');
}

export function worker(command, args, logFd, onStart = () => {}) {
  return new Promise(resolve => {
    const child = spawn(command, args, {cwd: root, stdio: ['ignore', logFd, logFd]});
    onStart(child);
    child.once('error', error => resolve({code: 1, signal: null, error: error.message, pid: child.pid}));
    child.once('exit', (code, signal) => resolve({code, signal, pid: child.pid}));
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log('npm run demos:campaign -- --output DIRECTORY --browser-executable PATH [--resume] [--pilot] [--python PATH]\nDefault: pilot, 20-level gate, then all 150 Classic levels.');
    return;
  }
  const output = path.resolve(options.output || path.join(os.homedir(), 'runner1-experiments/demo-scoring', new Date().toISOString().replace(/[:.]/g, '-')));
  // Refuse repository output before creating logs or locks; extractor repeats the check.
  let ancestor = output;
  while (!existsSync(ancestor)) ancestor = path.dirname(ancestor);
  const resolved = path.join(realpathSync(ancestor), path.relative(ancestor, output));
  const {spawnSync} = await import('node:child_process');
  const listing = spawnSync('git', ['worktree', 'list', '--porcelain'], {cwd: root, encoding: 'utf8'});
  if (listing.status !== 0) throw new Error('Cannot resolve worktree boundaries');
  for (const line of listing.stdout.split('\n').filter(s => s.startsWith('worktree '))) {
    const dir = realpathSync(line.slice(9));
    if (resolved === dir || resolved.startsWith(dir + path.sep)) throw new Error('Output must be outside worktrees');
  }
  mkdirSync(output, {recursive: true});
  const stateFile = path.join(output, 'supervisor.json');
  const manifestFile = path.join(output, 'manifest.json');
  if (existsSync(stateFile) && !options.resume) throw new Error('Existing campaign: use --resume');
  if (options.resume && !existsSync(manifestFile)) throw new Error('No extraction manifest to resume');
  const lockFile = path.join(output, '.campaign.lock');
  const lockFd = openSync(lockFile, 'wx');
  writeFileSync(lockFd, JSON.stringify({pid: process.pid, hostname: os.hostname()})); closeSync(lockFd);
  const state = existsSync(stateFile) ? read(stateFile) : {retries: 0, attempts: [], startedAt: new Date().toISOString()};
  const logFd = openSync(path.join(output, 'campaign.log'), 'a');
  let child, monitor, stopped = false;
  const stop = () => {stopped = true; child?.kill('SIGTERM');};
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  try {
    let resume = options.resume;
    while (true) {
      const args = [path.join(root, 'scripts/extract-demos.mjs'), '--output', output,
        ...(options.pilot ? ['--pilot'] : ['--all']), ...(resume ? ['--resume'] : []), '--python', options.python,
        ...(options.browserExecutable ? ['--browser-executable', options.browserExecutable] : [])];
      state.status = 'running'; save(stateFile, state);
      const result = await worker(process.execPath, args, logFd, running => {
        child = running;
        state.workerPid = child.pid;
        state.lastCheck = new Date().toISOString(); save(stateFile, state);
        monitor = setInterval(() => {
          try {
            const manifest = existsSync(manifestFile) ? read(manifestFile) : null;
            const count = Object.values(manifest?.levels || {}).filter(e => ['completed', 'quarantined'].includes(e.status)).length;
            state.progressSincePreviousCheck = count !== state.finishedLevels;
            state.finishedLevels = count;
            state.lastCheck = new Date().toISOString();
            state.processAlive = child.exitCode === null && child.signalCode === null;
            save(stateFile, state);
          } catch (error) { state.monitorError = error.message; stop(); }
        }, 300000);
      });
      clearInterval(monitor);
      state.attempts.push({...result, endedAt: new Date().toISOString()});
      if (stopped || !shouldRetry(result.code, result.signal, state.retries)) {
        state.status = result.code === 0 ? 'completed' : 'failed';
        state.finishedAt = new Date().toISOString(); save(stateFile, state);
        if (result.code !== 0) process.exitCode = 1;
        break;
      }
      clearOwnedWorkerLock(output, result.pid);
      state.retries++;
      save(stateFile, state);
      resume = existsSync(manifestFile);
    }
    const manifest = existsSync(manifestFile) ? read(manifestFile) : null;
    const entries = Object.values(manifest?.levels || {});
    const summaryFile = path.join(output, 'reports/summary.json');
    const summary = { ...(existsSync(summaryFile) ? read(summaryFile) : {}),
      status: state.status, dataset: output, retries: state.retries,
      completed: entries.filter(e => e.status === 'completed').length,
      quarantined: entries.filter(e => e.status === 'quarantined').length,
      elapsedSeconds: (Date.now() - Date.parse(state.startedAt)) / 1000,
      failure: manifest?.failure || (state.status === 'failed' ? state.attempts.at(-1) : null),
      log: path.join(output, 'campaign.log')};
    save(path.join(output, 'campaign-summary.json'), summary);
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    clearInterval(monitor); closeSync(logFd); unlinkSync(lockFile);
    process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {console.error(error.stack); process.exitCode = 1;});
}
