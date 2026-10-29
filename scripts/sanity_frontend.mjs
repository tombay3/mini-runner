// Wrapper/helper smoke checks. No browser, services, model calls or store writes.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

// Exercise the real hook with revealed H tiles and an S in the source map.
const runtime = vm.createContext({
  window: {}, levelData: ["  S  "], curLevel: 1, playData: 1, playMode: 0,
  NO_OF_TILES_X: 5, NO_OF_TILES_Y: 1,
  runner: { pos: { x: 0, y: 0, xOffset: 0, yOffset: 0 }, action: 0 },
  ACT_STOP: 0, guardCount: 0, fillHoleObj: [],
  godMode: false, godModeKeyPressed: false, goldComplete: false, goldCount: 1,
  GAME_START: 0, GAME_RUNNING: 1, gameState: 1,
  recordCount: 0, playTickTimer: 0, curTime: 0, TICK_COUNT_PER_TIME: 16,
  EMPTY_T: 0, BLOCK_T: 1, SOLID_T: 2, LADDR_T: 3, BAR_T: 4,
  TRAP_T: 5, HLADR_T: 6, GOLD_T: 7, GUARD_T: 8, RUNNER_T: 9,
  map: Array.from({ length: 5 }, () => [{ base: 3, act: 3 }]),
});
vm.runInContext(readFileSync(new URL("../public/game/lodeRunner.agentHooks.js", import.meta.url), "utf8"), runtime);
const exitSnapshot = () => runtime.window.lodeRunnerAgentHooks.snapshot();
assert.equal(exitSnapshot().exitTarget, null);
runtime.goldComplete = true;
runtime.goldCount = 0;
assert.deepEqual(JSON.parse(JSON.stringify(exitSnapshot().exitTarget)), { x: 2, y: 0, tile: "S" });
runtime.levelData = ["    S"];
assert.equal(exitSnapshot().exitTarget.x, 4);
runtime.levelData = ["S   S"];
assert.equal(exitSnapshot().exitTarget, null);
runtime.levelData = ["HHHHH"];
assert.equal(exitSnapshot().exitTarget, null);

// The lower disconnected S is not an entrance to the top-connected exit.
const exitRows = ["  S  ", "  H  ", "  S  ", "     ", "  S  "];
runtime.NO_OF_TILES_Y = exitRows.length;
runtime.levelData = [exitRows.join("")];
runtime.map = Array.from({ length: 5 }, (_, x) => exitRows.map(row => {
  const tile = "SH".includes(row[x]) ? runtime.LADDR_T : runtime.EMPTY_T;
  return { base: tile, act: tile };
}));
runtime.runner.pos.y = 4;
assert.deepEqual(JSON.parse(JSON.stringify(exitSnapshot().exitTarget)), { x: 2, y: 2, tile: "S" });
runtime.runner.pos.y = 1;
assert.equal(exitSnapshot().exitTarget.y, 1);
runtime.runner.pos.x = 2;
assert.equal(exitSnapshot().exitTarget.y, 0);
runtime.runner.pos.y = 4;
assert.equal(exitSnapshot().exitTarget.y, 2);

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

// Navigation availability is shared by the rail and its keyboard shortcuts.
const navigation = {
  records: [{ id: "first" }, { id: "second" }],
  backendStatus: "online", playbackPhase: "inactive", busyAction: "", agentRunning: false,
};
Object.assign(window, { PLAY_AUTO: 6, PLAY_DEMO: 3, playMode: 2 });
for (const [count, autoDemoActive, expected] of [
  [0, false, false], [1, false, false], [2, false, true], [2, true, false],
]) {
  const state = { ...navigation, records: navigation.records.slice(0, count) };
  const view = recording.deriveOverlayViewModel({
    ...state, recordCount: count, autoDemoActive,
  });
  window.playMode = autoDemoActive ? window.PLAY_AUTO : 2;
  assert.equal(recording.canNavigateStoredRecords(state), expected);
  assert.equal(view.buttons.prev.disabled, !expected);
  assert.equal(view.buttons.next.disabled, !expected);
}
window.playMode = window.PLAY_DEMO;
assert.equal(recording.canNavigateStoredRecords(navigation), false);
resetWindow();

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
    state: { tick: 0, threat: { risk: "low" }, godMode: false }, issuedAction: { keyCode: 39, ticks: 4 },
    candidates: [{ id: "right", kind: "collect_same_row_gold", lane: "progress",
      score: 100, offeredAction: { name: "right", keyCode: 39, ticks: 4 } }],
    decision: { requestedId: "right", selectedId: "right", rationale: "smoke", fallback: null },
    loop: { active: false, type: null }, excludedProposals: [],
  }],
};
const summary = summarizeAttempt(1, "smoke", {
  id: "run", traceId: "run", result: "failure", godMode: 0, playData: 1, level: 1,
}, trace, { godMode: false });
assert.equal(summary.stepCount, 1);
assert.equal(summary.modeValid, true);
assert.equal(summary.contextValid, true);
console.log("frontend smoke ok");
