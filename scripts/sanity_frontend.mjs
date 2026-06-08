import assert from "node:assert/strict";

globalThis.window = {
  AI_VERSION: 4,
  playerName: "Tester",
  location: { search: "" },
  demoTickCount: 0,
  demoRecordIdx: 0,
  playMode: 0,
  PLAY_DEMO_ONCE: 2,
};

const agentModule = await import("../src/agent.js");
const recordingModule = await import("../src/recording.js");
const agent = agentModule._test;
const recording = recordingModule._test;

function assertThrowsMessage(fn, text) {
  assert.throws(fn, (error) => error instanceof Error && error.message.includes(text));
}

const config = agent.normalizeAgentConfig({
  agent: {
    playData: "1",
    level: "1",
    maxPlaybackTimeSeconds: "30",
    maxSteps: "25",
    historyLimit: "5",
    modelProfile: " gemini ",
  },
  backend: {
    maxActionTicks: 99,
  },
});
assert.deepEqual(config.agent, {
  playData: 1,
  level: 1,
  maxPlaybackTimeSeconds: 30,
  maxSteps: 25,
  historyLimit: 5,
  modelProfile: "gemini",
});
assert.equal(config.backend.maxActionTicks, 20);

const action = agent.normalizeAgentAction({ keyCode: "39", ticks: 99, reason: 123 }, config);
assert.deepEqual(action, { keyCode: 39, ticks: 20, reason: "123" });
assert.equal(agent.normalizeAgentAction({ keyCode: 39, ticks: -2 }, config).ticks, 1);
assertThrowsMessage(() => agent.normalizeAgentAction(null, config), "no action");
assertThrowsMessage(() => agent.normalizeAgentAction({ keyCode: 39, ticks: "bad" }, config), "invalid action");

assert.equal(
  agent.hasExceededPlaybackTime({ timing: { gameTime: 30 } }, config),
  true,
  "gameTime limit",
);
assert.equal(
  agent.hasExceededPlaybackTime({ timing: { gameTime: 29, recordTick: 1 } }, config),
  false,
  "below gameTime limit",
);
assert.equal(
  agent.hasExceededPlaybackTime({ timing: { recordTick: 30 * 16 } }, config),
  true,
  "recordTick fallback limit",
);

assert.deepEqual(
  agent.summarizeHistorySnapshot({
    tick: 12,
    gameStateName: "running",
    gold: { remainingCount: 3, complete: false },
    runner: { x: 14, y: 14, xOffset: 0, yOffset: 0, actionName: "right" },
  }),
  {
    tick: 12,
    state: "running",
    goldCount: 3,
    goldComplete: false,
    runner: { x: 14, y: 14, xOffset: 0, yOffset: 0, action: "right" },
  },
);

window.location.search = "?profile=minimax";
assert.equal(agent.getAgentModelProfileOption({ modelProfile: "openai" }, config), "minimax");
window.location.search = "";
window.__lodeRunnerAgentOptions = { modelProfile: "openai" };
assert.equal(agent.getAgentModelProfileOption(window.__lodeRunnerAgentOptions, config), "openai");
delete window.__lodeRunnerAgentOptions;
assert.equal(agent.getAgentModelProfileOption(null, config), "gemini");

const sourceAction = [0, 39];
const demo = recording.normalizeDemo(
  {
    ai: 5,
    time: 32,
    state: 1,
    godMode: 1,
    action: sourceAction,
    goldDrop: [1],
    bornPos: [2],
  },
  1,
  1,
);
sourceAction.push(8, 32);
assert.equal(demo.level, 1);
assert.equal(demo.playData, 1);
assert.equal(demo.action.length, 2, "normalizeDemo copies action array");
assert.deepEqual(recording.copyArray("nope"), []);

const traceTicks = recording.extractTraceStepTicks({
  steps: [
    { state: { tick: 32 } },
    { historyTail: [{ tick: 8 }, { tick: 16 }] },
    { state: { tick: "bad" } },
  ],
});
assert.deepEqual(traceTicks, [16, 32]);
assert.equal(recording.getTraceStepTick({ state: { tick: 12 } }), 12);
assert.equal(recording.getTraceStepTick({ historyTail: [{ tick: 4 }, { tick: 6 }] }), 6);

assert.equal(recording.formatDemoTime(32), "2s");
assert.equal(recording.formatDemoTime(0), "-");

const traceState = {
  currentRecord: {
    traceId: "trace-1",
    demo: { action: [0, 39, 8, 32] },
  },
  selectedTraceSummary: { stepCount: 3 },
  selectedTraceId: "trace-1",
  selectedTraceTicks: [0, 16, 32],
  playbackKey: "1:1",
};
window.playData = 1;
window.curLevel = 1;
window.maxPlayId = 1;
window.playMode = window.PLAY_DEMO_ONCE;
window.demoTickCount = 16;
assert.equal(recording.formatPlaybackProgress(traceState), "steps 2/3");

const keyState = {
  currentRecord: {
    demo: { action: [0, 39, 8, 32, 16, 37] },
  },
  selectedTraceSummary: null,
  playbackKey: "1:1",
};
window.demoRecordIdx = 2;
assert.equal(recording.formatPlaybackProgress(keyState), "keys 2/3");
keyState.playbackKey = "";
assert.equal(recording.formatPlaybackProgress(keyState), "keys 3");

console.log("frontend sanity ok");
