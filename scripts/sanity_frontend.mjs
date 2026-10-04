// Wrapper/helper smoke checks. No browser, services, model calls or store writes.
import assert from "node:assert/strict";

function resetWindow() {
  globalThis.window = {
    AI_VERSION: 4, playerName: "Tester", location: { search: "" },
    demoTickCount: 0, demoRecordIdx: 0, playMode: 0, gameState: 4,
    PLAY_CLASSIC: 1, PLAY_DEMO_ONCE: 7,
    GAME_START: 0, GAME_RUNNING: 1, GAME_WAITING: 4, GAME_PAUSE: 5,
  };
}
resetWindow();
const agent = (await import("../src/agent.js"))._test;
const recording = (await import("../src/recording.js"))._test;
const { summarizeAttempt } = await import("./evaluate-agent.mjs");

const config = agent.normalizeAgentConfig({
  agent: { playData: "1", level: "1", maxPlaybackTimeSeconds: 30 },
  backend: { maxActionTicks: 99 },
});
assert.equal(config.agent.level, 1);
assert.equal(config.backend.maxActionTicks, 20);
const action = agent.normalizeAgentAction({ keyCode: "39", ticks: 99 }, config);
assert.equal(action.keyCode, 39);
assert.equal(action.ticks, 20);
assert.throws(() => agent.normalizeAgentAction(null, config));
assert.equal(agent.hasExceededPlaybackTime({ timing: { gameTime: 29 } }, config), false);
assert.equal(agent.hasExceededPlaybackTime({ timing: { gameTime: 30 } }, config), true);

// One shared async fixture checks both terminal outcomes, without duplicate saves.
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

resetWindow();
window.godMode = 0;
window.toggleGodMode = () => { window.godMode = Number(!window.godMode); };
recording.ensureEvaluationGodMode(true);
assert.equal(window.godMode, 1);
recording.ensureEvaluationGodMode(false);
assert.equal(window.godMode, 0);

const originalActions = [0, 39];
const demo = recording.normalizeDemo({
  ai: 1, time: 32, state: 1, action: originalActions, goldDrop: [], bornPos: [],
}, 1, 1);
originalActions.push(8, 32);
assert.deepEqual(demo.action, [0, 39]);
const playback = {
  currentRecord: { traceId: "run", demo },
  selectedTraceSummary: { stepCount: 3 }, selectedTraceId: "run",
  selectedTraceTicks: [0, 16, 32], playbackGameLevel: "1:1", playbackPhase: "playing",
};
Object.assign(window, { playData: 1, curLevel: 1, maxPlayId: 1,
  playMode: window.PLAY_DEMO_ONCE, demoTickCount: 16 });
assert.equal(recording.getTracePlaybackProgress(playback, 3), 2);
assert.equal(recording.getNextTraceStepTargetTick(playback), 32);
window.demoTickCount = 32;
assert.equal(recording.getNextTraceStepTargetTick(playback), null);

// One evaluator-summary case uses the current trace contract.
const trace = {
  id: "run", playData: 1, level: 1, model: null,
  outcome: { result: "failure", reason: "runner dead", finalState: { godMode: false } },
  steps: [{
    state: { tick: 0, risk: "low", godMode: false }, action: { keyCode: 39, ticks: 4 },
    candidates: [{ id: "right", kind: "collect_same_row_gold", lane: "progress",
      score: 100, firstAction: { keyCode: 39, ticks: 4 } }],
    decision: { requestedId: "right", selectedId: "right", rationale: "smoke", fallback: null },
    loop: { active: false, type: null }, candidateEvents: [],
  }],
};
const summary = summarizeAttempt(1, "smoke", {
  id: "run", traceId: "run", result: "failure", godMode: 0, playData: 1, level: 1,
}, trace, { godMode: false });
assert.equal(summary.stepCount, 1);
assert.equal(summary.modeValid, true);
assert.equal(summary.contextValid, true);
console.log("frontend smoke ok");
