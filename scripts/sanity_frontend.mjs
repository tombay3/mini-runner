import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = {
  AI_VERSION: 4,
  playerName: "Tester",
  location: { search: "" },
  demoTickCount: 0,
  demoRecordIdx: 0,
  playMode: 0,
  gameState: 4,
  PLAY_CLASSIC: 1,
  PLAY_MODERN: 2,
  PLAY_DEMO_ONCE: 7,
  GAME_START: 0,
  GAME_RUNNING: 1,
  GAME_WAITING: 4,
  GAME_PAUSE: 5,
};

const agentModule = await import("../src/agent.js");
const recordingModule = await import("../src/recording.js");
const agent = agentModule._test;
const recording = recordingModule._test;
const agentHookSource = readFileSync(
  new URL("../public/game/lodeRunner.agentHooks.js", import.meta.url),
  "utf8",
);
assert.match(agentHookSource, /activeDig: snapshotActiveDig\(\)/);
assert.match(agentHookSource, /holeObj\.action != ACT_DIGGING/);

window.crypto = {
  getRandomValues(array) {
    array.set(Array.from({ length: array.length }, (_value, index) => index));
    return array;
  },
};
assert.equal(agent.createRunId(), "00010203-0405-4607-8809-0a0b0c0d0e0f");
window.crypto = {};
const fallbackRunId = agent.createRunId();
assert.match(fallbackRunId, /^[a-f0-9]{8}-\d+$/);

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

assert.deepEqual(
  agent.summarizeTerminalSnapshot({
    playData: 1,
    level: 1,
    tick: 42,
    time: 3,
    gameStateName: "runner_dead",
    godMode: false,
    runner: { x: 7, y: 6, xOffset: -8, yOffset: 0, actionName: "up" },
    guards: [
      { id: 2, x: 7, y: 5, xOffset: 0, yOffset: 12, actionName: "down", hasGold: 1 },
    ],
    gold: {
      remainingCount: 1,
      complete: false,
      visiblePositions: [],
      carriedByGuards: [{ id: 2, x: 7, y: 5, hasGold: 1 }],
    },
  }),
  {
    playData: 1,
    level: 1,
    tick: 42,
    time: 3,
    gameState: "runner_dead",
    godMode: false,
    runner: { x: 7, y: 6, xOffset: -8, yOffset: 0, action: "up" },
    guards: [{ id: 2, x: 7, y: 5, xOffset: 0, yOffset: 12, action: "down", hasGold: 1 }],
    gold: {
      remainingCount: 1,
      complete: false,
      visiblePositions: [],
      carriedByGuards: [{ id: 2, x: 7, y: 5, hasGold: 1 }],
    },
  },
);

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
    playData: 1,
    level: 1,
    tick: 12,
    gameStateName: "running",
    gold: { remainingCount: 3, complete: false },
    runner: { x: 14, y: 14, xOffset: 0, yOffset: 0, actionName: "right" },
  }),
  {
    playData: 1,
    level: 1,
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

assert.deepEqual(
  agent.deriveAgentButtonState(
    { agentRunning: false, busyAction: "", backendStatus: "checking" },
    true,
  ),
  { disabled: true, title: "Checking AI server" },
);
assert.deepEqual(
  agent.deriveAgentButtonState(
    { agentRunning: false, busyAction: "", backendStatus: "offline" },
    true,
  ),
  { disabled: true, title: "AI server unavailable" },
);
assert.deepEqual(
  agent.deriveAgentButtonState(
    { agentRunning: true, busyAction: "agent", backendStatus: "offline" },
    true,
  ),
  { disabled: false, title: "Cancel AI agent" },
);

assert.equal(recording.formatGameLevel({ playData: 1, level: 1 }), "1:1");
const overlayFacts = (overrides = {}) => ({
  uiError: false,
  busyAction: "",
  backendStatus: "online",
  hasRecord: true,
  recordPinned: false,
  recordCount: 2,
  playbackPhase: "inactive",
  videoRecording: false,
  agentRunning: false,
  agentButtonState: { disabled: false, title: "Solve Classic level 1 with AI agent" },
  godModeActive: false,
  godModeSupported: true,
  fullscreenActive: false,
  fullscreenSupported: true,
  ...overrides,
});

let overlayView = recording.deriveOverlayViewModel(overlayFacts());
assert.equal(overlayView.buttons.play.disabled, false);
assert.equal(overlayView.buttons.prev.disabled, false);
assert.equal(overlayView.buttons.next.disabled, false);
assert.equal(overlayView.buttons.delete.disabled, false);
overlayView = recording.deriveOverlayViewModel(
  overlayFacts({ recordPinned: true }),
);
assert.equal(overlayView.buttons.delete.disabled, true);
assert.equal(
  overlayView.buttons.delete.title,
  "Unpin stored run before deleting",
);
assert.equal(
  recording.getRecordNavigationDelta({ code: "Tab", key: "Tab", shiftKey: false }),
  1,
);
assert.equal(
  recording.getRecordNavigationDelta({ code: "Tab", key: "Tab", shiftKey: true }),
  -1,
);
assert.equal(recording.getRecordNavigationDelta({ code: "Space", key: " " }), 0);
assert.equal(
  recording.canNavigateStoredRecords({
    records: [{ id: "new" }, { id: "old" }],
    busyAction: "",
    playbackPhase: "inactive",
  }),
  true,
);
assert.equal(
  recording.canNavigateStoredRecords({
    records: [{ id: "new" }, { id: "old" }],
    busyAction: "",
    playbackPhase: "paused",
  }),
  false,
  "run navigation remains disabled during playback",
);

overlayView = recording.deriveOverlayViewModel(
  overlayFacts({
    backendStatus: "offline",
    hasRecord: false,
    recordCount: 0,
    agentButtonState: { disabled: true, title: "AI server unavailable" },
  }),
);
assert.equal(overlayView.buttons.agent.disabled, true);
assert.equal(overlayView.buttons.play.disabled, true);
assert.equal(overlayView.buttons.prev.disabled, true);
assert.equal(overlayView.buttons.next.disabled, true);
assert.equal(overlayView.buttons.delete.disabled, true);
assert.equal(overlayView.buttons.god.disabled, false);
assert.equal(overlayView.buttons.fullscreen.disabled, false);

overlayView = recording.deriveOverlayViewModel(overlayFacts({ backendStatus: "offline" }));
assert.equal(overlayView.buttons.play.disabled, false, "cached playback remains available offline");
assert.equal(overlayView.buttons.prev.disabled, false, "cached navigation remains available offline");
assert.equal(overlayView.buttons.delete.disabled, true, "delete requires backend");

overlayView = recording.deriveOverlayViewModel(
  overlayFacts({ playbackPhase: "playing" }),
);
assert.equal(overlayView.buttons.play.icon, "⏸");
assert.equal(overlayView.buttons.play.title, "Pause demo playback");
assert.equal(overlayView.buttons.delete.disabled, true);
assert.equal(overlayView.buttons.prev.disabled, true);

overlayView = recording.deriveOverlayViewModel(
  overlayFacts({ playbackPhase: "paused" }),
);
assert.equal(overlayView.buttons.play.icon, "▶");
assert.equal(overlayView.buttons.play.title, "Resume demo playback");

overlayView = recording.deriveOverlayViewModel(
  overlayFacts({ playbackPhase: "step-action" }),
);
assert.equal(overlayView.buttons.play.title, "Stepping to next recorded action");
overlayView = recording.deriveOverlayViewModel(
  overlayFacts({ playbackPhase: "step-trace" }),
);
assert.equal(overlayView.buttons.play.title, "Stepping to next trace step");

assert.equal(
  recording.canStartStoredPlaybackFromHotkey({
    currentRecord: { id: "record-1" },
    busyAction: "",
    agentRunning: false,
  }),
  true,
);
window.playMode = window.PLAY_CLASSIC;
window.gameState = window.GAME_START;
assert.equal(
  recording.canStartStoredPlaybackFromHotkey({
    currentRecord: { id: "record-1" },
    busyAction: "",
    agentRunning: false,
  }),
  true,
  "Space starts selected playback from the idle level start",
);
window.gameState = window.GAME_RUNNING;
assert.equal(
  recording.canStartStoredPlaybackFromHotkey({
    currentRecord: { id: "record-1" },
    busyAction: "",
    agentRunning: false,
  }),
  false,
  "Space remains available to active manual gameplay",
);
window.gameState = window.GAME_PAUSE;
assert.equal(
  recording.canStartStoredPlaybackFromHotkey({
    currentRecord: { id: "record-1" },
    busyAction: "",
    agentRunning: false,
  }),
  false,
  "Space does not replace a paused manual game with playback",
);
window.gameState = window.GAME_WAITING;
assert.equal(
  recording.canStartStoredPlaybackFromHotkey({
    currentRecord: { id: "record-1" },
    busyAction: "agent",
    agentRunning: true,
  }),
  false,
);
assert.equal(
  recording.canStartStoredPlaybackFromHotkey({
    currentRecord: null,
    busyAction: "",
    agentRunning: false,
  }),
  false,
);

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
assert.equal(
  recording.shouldSaveUserCompletion({ agentRunning: false, busyAction: "" }),
  true,
  "manual completion is saved as a user recording",
);
assert.equal(
  recording.shouldSaveUserCompletion({
    agentRunning: true,
    busyAction: "agent",
  }),
  false,
  "agent completion is not also saved as a user recording",
);
assert.equal(
  recording.shouldSaveUserCompletion({
    agentRunning: false,
    busyAction: "agent",
  }),
  false,
  "agent save transition does not create a user recording",
);

const traceTicks = recording.extractTraceStepTicks({
  steps: [
    { state: { tick: 32 } },
    { state: {} },
    { state: { tick: "bad" } },
  ],
});
assert.deepEqual(traceTicks, [32]);
assert.equal(recording.getTraceStepTick({ state: { tick: 12 } }), 12);

assert.equal(recording.formatDemoTime(32), "0:02");
assert.equal(recording.formatDemoTime(968), "1:00");
assert.equal(recording.formatDemoTime(8), "0:00", "matches dashboard half-even rounding");
assert.equal(recording.formatDemoTime(24), "0:02", "matches dashboard half-even rounding");
assert.equal(recording.formatDemoTime(0), "-");
assert.equal(recording.shortId("037883a3-9cda-4bb9-aca0-b7c7a205e69b"), "037883a3");
assert.equal(recording.shortId("248cc0d0-1783960882373"), "248cc0d0");
assert.equal(recording.shortId(fallbackRunId), fallbackRunId.split("-", 1)[0]);
assert.equal(
  recording.formatRecordTraceId({ source: "user", traceId: null }),
  "user",
);
assert.equal(
  recording.formatRecordTraceId({ source: "agent", traceId: "037883a3-rest" }),
  "037883a3",
);
assert.equal(recording.formatRecordResult("success"), "✅");
assert.equal(recording.formatRecordResult("failure"), "❌");
assert.equal(
  recording.formatDebugOverlay({
    currentRecord: {
      source: "user",
      result: "success",
      savedAt: "",
      demo: { time: 32, action: [0, 39] },
    },
    selectedRecordIndex: 0,
    records: [{}],
    selectedTraceSummary: null,
    playbackPhase: "inactive",
  }),
  "[1/1] user | - | ✅ | 0:02 | keys 1",
);
assert.equal(
  recording.buildPlaybackVideoFileName(
    "23dfc383-aaaa-bbbb-cccc-dddddddddddd",
    new Date("2026-06-12T02:10:48.927Z"),
  ),
  "run-23dfc383-2026-06-12T02-10-48.mp4",
);
assert.equal(
  recording.buildPlaybackVideoFileName(
    "248cc0d0-1783960882373",
    new Date("2026-06-12T02:10:48.927Z"),
  ),
  "run-248cc0d0-2026-06-12T02-10-48.mp4",
);
assert.equal(
  recording.buildPlaybackVideoFileName(
    "trace:abc/123",
    new Date("2026-01-02T03:04:05.006Z"),
    "video/mp4",
  ),
  "run-trace-abc-123-2026-01-02T03-04-05.mp4",
);
assert.equal(
  recording.choosePlaybackVideoMimeType({
    isTypeSupported: (mimeType) => mimeType === "video/mp4;codecs=avc1.42E01E",
  }),
  "video/mp4;codecs=avc1.42E01E",
);
assert.equal(
  recording.choosePlaybackVideoMimeType({
    isTypeSupported: (mimeType) => mimeType.startsWith("video/webm"),
  }),
  "",
  "WebM-only browsers do not create mislabeled MP4 downloads",
);
assert.equal(recording.choosePlaybackVideoMimeType({ isTypeSupported: () => false }), "");
assert.equal(
  recording.buildRecordingDeleteConfirmation({
    id: "23dfc383-aaaa-bbbb-cccc-dddddddddddd",
    traceId: "23dfc383-aaaa-bbbb-cccc-dddddddddddd",
  }),
  "Delete stored run 23dfc383?\n\nIts linked agent trace will also be deleted.\n\nThis cannot be undone.",
);
assert.equal(
  recording.buildRecordingDeleteConfirmation({ id: "user:2026-06-12T02:10:48Z" }),
  "Delete stored run user:202?\n\nThis cannot be undone.",
);

const traceState = {
  currentRecord: {
    traceId: "trace-1",
    demo: { action: [0, 39, 8, 32] },
  },
  selectedTraceSummary: { stepCount: 3 },
  selectedTraceId: "trace-1",
  selectedTraceTicks: [0, 16, 32],
  playbackGameLevel: "1:1",
  playbackPhase: "playing",
};
window.playData = 1;
window.curLevel = 1;
window.maxPlayId = 1;
window.playMode = window.PLAY_DEMO_ONCE;
window.demoTickCount = 16;
assert.equal(recording.formatPlaybackProgress(traceState), "steps 2/3");
assert.equal(recording.getTracePlaybackProgress(traceState, 3), 2);
assert.equal(recording.getNextTraceStepTargetTick(traceState), 32);
window.demoTickCount = 32;
assert.equal(recording.getTracePlaybackProgress(traceState, 3), 3);
assert.equal(recording.getNextTraceStepTargetTick(traceState), null);

const missingTraceState = {
  currentRecord: { traceId: "trace-1" },
  selectedTraceSummary: { stepCount: 3 },
  selectedTraceId: "",
  selectedTraceTicks: [],
  playbackGameLevel: "1:1",
  playbackPhase: "playing",
};
assert.equal(recording.getNextTraceStepTargetTick(missingTraceState), null);

const keyState = {
  currentRecord: {
    demo: { action: [0, 39, 8, 32, 16, 37] },
  },
  selectedTraceSummary: null,
  playbackGameLevel: "1:1",
  playbackPhase: "playing",
};
window.demoRecordIdx = 2;
assert.equal(recording.formatPlaybackProgress(keyState), "keys 2/3");
keyState.playbackGameLevel = "";
assert.equal(recording.formatPlaybackProgress(keyState), "keys 3");

console.log("frontend sanity ok");
