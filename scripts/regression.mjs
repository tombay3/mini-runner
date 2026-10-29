// Focused regressions for all JavaScript areas; no paid model calls.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { projectPython, rootDir } from "./launch-python.mjs";
import { verifyEngineContext, replayStateAt, normalizeState } from "./hybrid-runtime.mjs";

const python = projectPython("Install requirements.txt before running regressions.");
const result = spawnSync(python, ["scripts/regression_backend.py"], { cwd: rootDir, stdio: "inherit" });
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);

async function runChecks() {
  const {default: test} = await import('node:test');
  const {default: fs} = await import('node:fs');
  const {default: os} = await import('node:os');
  const {default: path} = await import('node:path');
  const {startServer} = await import('./hybrid-reproducer.mjs');

  for(const godMode of [false,true]) {
  test(`${godMode?'god':'normal'} mode rejects mode or context drift`,()=>{
    const state={playData:1,level:1,godMode};
    verifyEngineContext(state,godMode);
    assert.throws(()=>verifyEngineContext({...state,godMode:!godMode},godMode));
    assert.throws(()=>verifyEngineContext({...state,godMode:undefined},godMode));
    assert.throws(()=>verifyEngineContext({...state,level:2},godMode));
    assert.throws(()=>verifyEngineContext({...state,playData:2},godMode));
  });

  }
  test('natural terminal sharing a tick does not replace a decision boundary',()=>{
    const initialState={tick:0,gameStateName:'start',godMode:true};
    const running={tick:8,gameStateName:'running',godMode:true};
    const terminal={tick:8,gameStateName:'finish',godMode:true};
    const replay={initialState,states:[running],terminal};
    assert.equal(replayStateAt(replay,0),initialState);
    assert.equal(replayStateAt(replay,8),running);
    assert.equal(replayStateAt(replay,8,true),terminal);
    assert.throws(()=>replayStateAt(replay,9));
  });

  test('engine observations normalize to V4 state including guard gold cooldowns',()=>{
    const actor={x:2,y:1,xOffset:0,yOffset:0,actionName:'left'};
    const engine={tick:8,gameStateName:'running',godMode:false,runner:actor,
      guards:[{...actor,id:0,hasGold:-1}],
      gold:{remainingCount:1,complete:false,visiblePositions:[{x:4,y:1}]}};
    const trace={tick:8,gameState:'running',godMode:false,runner:{...actor,action:'left'},
      guards:[{...actor,id:0,action:'left',carryingGold:false}],
      gold:{remaining:1,complete:false,visible:[{x:4,y:1}]}};
    assert.deepEqual(normalizeState(engine,true),normalizeState(trace));
    engine.guards[0].hasGold=12;trace.guards[0].carryingGold=true;
    assert.deepEqual(normalizeState(engine,true),normalizeState(trace));
  });

  test('limited continuation can end at a running replay boundary',()=>{
    const state={tick:8,gameStateName:'running',godMode:true};
    const replay={states:[state],terminal:{tick:10,gameStateName:'running',godMode:true}};
    assert.equal(replayStateAt(replay,8,true),state);
  });

  test('missing executable and early service exit fail startup', async t=>{
    const cwd=fs.mkdtempSync(path.join(os.tmpdir(),'hybrid-startup-'));
    t.after(()=>fs.rmSync(cwd,{recursive:true,force:true}));
    const url='http://127.0.0.1:1/';
    await assert.rejects(startServer(path.join(cwd,'missing'),[],cwd,url,path.join(cwd,'missing.log')),
      error=>error.code==='ENOENT');
    await assert.rejects(startServer(process.execPath,['-e','process.exit(2)'],cwd,url,path.join(cwd,'exit.log')),
      /Owned service exited/);
  });
}

await runChecks();

function resetWindow() {
  globalThis.window = {
    AI_VERSION: 4, playerName: "Tester", location: { search: "" },
    demoTickCount: 0, demoRecordIdx: 0, playMode: 0, gameState: 4,
    PLAY_CLASSIC: 1, PLAY_DEMO_ONCE: 7,
    GAME_START: 0, GAME_RUNNING: 1, GAME_WAITING: 4, GAME_PAUSE: 5,
  };
}

const agent = (await import("../src/agent.js"))._test;
globalThis.window = {};
for (const result of ["success", "failure"]) {
  resetWindow();
  let releaseRefresh, enterRefresh;
  const entered = new Promise(resolve => { enterRefresh = resolve; });
  const pending = new Promise(resolve => { releaseRefresh = resolve; });
  const state = { agentRunning: true, agentRunId: "run", busyAction: "agent" };
  const record = { id: "run", source: "agent", result };
  let settled = false, saves = 0;
  const deps = {
    normalizeDemo: () => ({}),
    apiFetch: async () => { saves++; return record; },
    recordingApiBase: "/api/recordings",
    formatGameLevel: () => "1:1",
    finishUiAction: s => { s.busyAction = ""; },
    refreshStatus: async () => { enterRefresh(); await pending; },
    updateRecordingDebugUi: () => {},
    syncOverlayState: () => {},
  };
  const completion = agent.finishAgentRun(
    state, deps, { stop() {} }, {}, result, result === "failure" ? "runner dead" : null,
    { agent: { playData: 1, level: 1 } },
  ).then(value => { settled = true; return value; });
  await Promise.race([entered, completion]);
  assert.equal(settled, false);
  assert.equal(state.agentRunning, true);
  releaseRefresh();
  assert.equal(await completion, record);
  assert.equal(state.agentRunning, false);
  assert.equal(saves, 1);
}


try {
// Both stepping modes share scheduling, but retain their own completion boundary.
const recording = (await import("../src/recording.js"))._test;
for (const mode of ["action", "trace"]) {
  for (const ending of ["complete", "timeout", "cancel", "playback-ended"]) {
    resetWindow();
    const frames = new Map(), tips = [];
    let sequence = 0;
    Object.assign(window, {
      playData: 1, curLevel: 1, maxPlayId: 1, playMode: window.PLAY_DEMO_ONCE,
      gameState: window.GAME_PAUSE,
      requestAnimationFrame: fn => { frames.set(++sequence, fn); return sequence; },
      cancelAnimationFrame: id => frames.delete(id),
      gameResume: () => { window.gameState = window.GAME_RUNNING; },
      gamePause: () => { window.gameState = window.GAME_PAUSE; },
      showTipsText: text => tips.push(text),
    });
    const state = { els: {}, playbackGameLevel: "1:1", playbackPhase: "paused",
      currentRecord: { traceId: "test" }, selectedTraceId: "test", selectedTraceTicks: [0, 4],
      playbackStepRaf: 0, debugBarRaf: 0 };
    const start = mode === "action" ? recording.stepStoredPlaybackSegment : recording.stepStoredPlaybackTraceStep;
    start(state);
    assert.equal(frames.size, 1);
    if (ending === "complete") Object.assign(window, { demoRecordIdx: 1, demoTickCount: 4 });
    if (ending === "cancel") state.playbackPhase = "paused";
    if (ending === "playback-ended") window.playMode = 0;
    const fn = frames.values().next().value;
    frames.clear();
    fn(state.playbackStepStartedAt + (ending === "timeout" ? 8001 : 1));
    assert.equal(frames.size, 0, `${mode}: ${ending}`);
    assert.equal(state.playbackPhase, ending === "playback-ended" ? "inactive" : "paused");
    if (ending === "timeout") assert(tips.some(t => t.includes("TIMEOUT")));
  }
}

resetWindow();
const noTrace = { currentRecord: { traceId: "test" }, selectedTraceId: "other", selectedTraceTicks: [0, 4] };
assert.equal(recording.getNextTraceStepTargetTick(noTrace), null);
assert.equal(recording.getTracePlaybackProgress(noTrace, 2), "-");
noTrace.selectedTraceId = "test";
window.demoTickCount = undefined;
assert.equal(recording.getTracePlaybackProgress(noTrace, 2), 0);
assert.equal(recording.getNextTraceStepTargetTick(noTrace), null);
const emptySelection = { ...noTrace, records: [1], selectedTraceSummary: {}, selectedTraceLoadId: "old" };
recording.clearRecordSelection(emptySelection);
assert.deepEqual(emptySelection.records, []);
assert.equal(emptySelection.currentRecord, null);
assert.deepEqual(emptySelection.selectedTraceTicks, []);

// Refresh reset paths keep the same empty selection and cleanup state.
for (const situation of ["no-context", "offline", "missing-record"]) {
  resetWindow();
  Object.assign(window, { playData: 1, curLevel: situation === "no-context" ? 0 : 1,
    maxPlayId: 1, cancelAnimationFrame: () => {} });
  const state = { els: {}, records: [{}], currentRecord: {}, selectedTraceTicks: [1],
    currentGameLevel: "other", backendStatus: situation === "offline" ? "offline" : "online",
    selectedTraceSummary: {}, playbackStepRaf: 0, debugBarRaf: 0,
    videoChunks: [], videoRecorder: null, videoStream: null, videoRecording: false };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 404, statusText: "missing", json: async () => ({error: "missing"}) });
  try { await recording.refreshStatus(state, true); }
  finally { globalThis.fetch = originalFetch; }
  assert.equal(state.currentRecord, null);
  assert.deepEqual(state.records, []);
  assert.deepEqual(state.selectedTraceTicks, []);
}

// Finally cleanup also runs when persistence fails.
const failedState = { agentRunning: true, agentRunId: "run", agentAbort: {}, busyAction: "agent" };
let stopped = false;
await assert.rejects(agent.finishAgentRun(failedState, {
  normalizeDemo: () => ({}), apiFetch: async () => { throw Error("save failed"); },
  recordingApiBase: "/api/recordings", syncOverlayState: () => {},
  finishUiAction: (state, { error }) => { state.busyAction = ""; state.uiError = error; },
}, { stop: () => { stopped = true; } }, {}, "failure", "cancelled", { agent: { playData: 1, level: 1 } }));
assert(stopped && !failedState.agentRunning && failedState.agentAbort === null && failedState.agentRunId === null);
assert.equal(failedState.busyAction, "");
assert.equal(failedState.uiError, true);

// Real child-process forwarding; no server or notebook is started.
const {pathToFileURL} = await import("node:url");
const launcher = pathToFileURL(`${rootDir}/scripts/launch-python.mjs`).href;
for (const [code, expected] of [["import os,sys; print(sys.argv[1]); print(os.getcwd()); sys.exit(7)", 7], ["import os,signal; os.kill(os.getpid(),signal.SIGTERM)", null]]) {
  const source = `import {launchPython} from ${JSON.stringify(launcher)}; launchPython(['-c',${JSON.stringify(code)},'argument'],'setup');`;
  const child = spawnSync(process.execPath, ["--input-type=module", "-e", source], { encoding: "utf8" });
  assert.equal(child.status, expected);
  if (expected === 7) assert.deepEqual(child.stdout.trim().split("\n"), ["argument", rootDir]);
  else assert.equal(child.signal, "SIGTERM");
}
assert.throws(() => projectPython("setup", "/tmp/nonexistent-batch4-venv"));
console.log("wrapper and launcher regressions ok");

} catch (error) {
  console.error(error.stack);
  process.exitCode = 1;
}
