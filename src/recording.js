import { createAgentController } from "./agent.js";

const INSTALL_KEY = "__lodeRunnerRecording";
const API_BASE = "/api/recordings";
const OVERLAY_ID = "recording-overlay";
const FULLSCREEN_RESTART_DELAY_MS = 180;
const FAILED_DEMO_STOP_POLL_MS = 100;
const PLAYBACK_STEP_TIMEOUT_MS = 8000;

const agentController = createAgentController({
  apiFetch,
  clearPlaybackDebugState,
  getContextKey,
  getCurrentContext,
  normalizeDemo,
  recordingApiBase: API_BASE,
  scheduleRefresh,
  setUiState,
  syncOverlayState,
});

export function installRecording() {
  if (window[INSTALL_KEY]?.installed) {
    return window[INSTALL_KEY];
  }

  const state = {
    installed: true,
    currentKey: "",
    currentRecord: null,
    records: [],
    selectedRecordIndex: 0,
    selectedTraceSummary: null,
    selectedTraceId: "",
    selectedTraceTicks: [],
    selectedTraceLoadId: "",
    currentState: "idle",
    busyAction: "",
    playbackKey: "",
    saveTimer: 0,
    refreshTimer: 0,
    fullscreenRestartTimer: 0,
    playbackStopTimer: 0,
    playbackSaveGuard: null,
    playbackPaused: false,
    playbackStepping: false,
    playbackStepRaf: 0,
    playbackStepStartedAt: 0,
    debugBarRaf: 0,
    els: {},
  };
  agentController.initState(state);
  window[INSTALL_KEY] = state;

  createOverlay(state);
  patchRecordingSave(state);
  void refreshStatus(state);
  state.refreshTimer = window.setInterval(() => void refreshWhenLevelChanges(state), 1200);

  return state;
}

function patchRecordingSave(state) {
  const original = window.updatePlayerDemoData;
  if (typeof original !== "function" || original.__recordingPatched) {
    return;
  }

  function patchedUpdatePlayerDemoData(playData, demoDataInfo) {
    const result = original.apply(this, arguments);
    void saveCompletedRecording(state, playData, demoDataInfo);
    return result;
  }

  patchedUpdatePlayerDemoData.__recordingPatched = true;
  patchedUpdatePlayerDemoData.__original = original;
  window.updatePlayerDemoData = patchedUpdatePlayerDemoData;
}

async function saveCompletedRecording(state, playData, demoDataInfo) {
  const playDataId = Number(playData);
  const level = Number(demoDataInfo?.level);

  if (!isBuiltInPlayData(playDataId) || !Number.isInteger(level) || level <= 0) {
    return;
  }
  if (isStoredPlaybackSave(state, playDataId, level, demoDataInfo)) {
    return;
  }
  if (Number(demoDataInfo?.state) !== 1) {
    return;
  }

  const promotedDemo = window.playerDemoData?.[level - 1] || demoDataInfo;
  const demo = normalizeDemo(promotedDemo, playDataId, level);

  setUiState(state, state.currentRecord ? "available" : "idle", "save");
  try {
    const record = await apiFetch(`${API_BASE}/${playDataId}/${level}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demo, source: "user", result: "success" }),
    });
    state.currentRecord = record;
    setUiState(state, "available");
    scheduleRefresh(state);
  } catch (_error) {
    setUiState(state, "error");
  }
}

function normalizeDemo(demo, playData, level) {
  return {
    level,
    ai: Number(demo.ai ?? window.AI_VERSION ?? 0),
    time: Number(demo.time ?? 0),
    state: Number(demo.state ?? 1),
    godMode: Number(demo.godMode ?? 0),
    action: copyArray(demo.action),
    goldDrop: copyArray(demo.goldDrop),
    bornPos: copyArray(demo.bornPos),
    player: String(demo.player ?? window.playerName ?? "Local"),
    date: String(demo.date ?? new Date().toISOString()),
    location: String(demo.location ?? "Local"),
    cId: String(demo.cId ?? "Unknown"),
    ip: String(demo.ip ?? "local"),
    playData,
  };
}

function copyArray(value) {
  return Array.isArray(value) ? value.slice() : [];
}

function createOverlay(state) {
  const existing = document.getElementById(OVERLAY_ID);
  if (existing) {
    existing.remove();
  }
  document.querySelectorAll(".recording-debug-bar").forEach((element) => element.remove());

  const overlay = document.createElement("section");
  overlay.id = OVERLAY_ID;
  overlay.className = "recording-rail";
  overlay.setAttribute("aria-label", "Recording");
  overlay.innerHTML = `
    <button
      type="button"
      class="recording-rail-button"
      data-action="agent"
      data-icon="AI"
      aria-label="Solve with AI agent"
      title="Solve Classic level 1 with AI agent"
    ></button>
    <button
      type="button"
      class="recording-rail-button"
      data-action="play"
      data-icon="▶"
      aria-label="Play stored recording"
      title="Play stored recording"
    ></button>
    <button
      type="button"
      class="recording-rail-button"
      data-action="prev"
      data-icon="‹"
      aria-label="Previous stored run"
      title="Previous stored run"
    ></button>
    <button
      type="button"
      class="recording-rail-button"
      data-action="next"
      data-icon="›"
      aria-label="Next stored run"
      title="Next stored run"
    ></button>
    <button
      type="button"
      class="recording-rail-button"
      data-action="delete"
      data-icon="✕"
      aria-label="Delete stored recording"
      title="Delete stored recording"
    ></button>
    <button
      type="button"
      class="recording-rail-button"
      data-action="god"
      data-icon="★"
      aria-label="Toggle god mode"
      title="Toggle god mode"
    ></button>
    <button
      type="button"
      class="recording-rail-button"
      data-action="fullscreen"
      data-icon="⛶"
      aria-label="Toggle full screen"
      title="Toggle full screen"
    ></button>
  `;
  document.body.appendChild(overlay);
  const debugBar = document.createElement("div");
  debugBar.className = "recording-debug-bar";
  debugBar.hidden = true;
  debugBar.setAttribute("aria-live", "polite");
  document.body.appendChild(debugBar);

  state.els.overlay = overlay;
  state.els.debugBar = debugBar;
  state.els.play = overlay.querySelector("[data-action='play']");
  state.els.prev = overlay.querySelector("[data-action='prev']");
  state.els.next = overlay.querySelector("[data-action='next']");
  state.els.delete = overlay.querySelector("[data-action='delete']");
  state.els.agent = overlay.querySelector("[data-action='agent']");
  state.els.god = overlay.querySelector("[data-action='god']");
  state.els.fullscreen = overlay.querySelector("[data-action='fullscreen']");

  state.els.play.addEventListener("click", () => void playOrToggleCurrentRecording(state));
  state.els.prev.addEventListener("click", () => selectAdjacentRecord(state, -1));
  state.els.next.addEventListener("click", () => selectAdjacentRecord(state, 1));
  state.els.delete.addEventListener("click", () => void deleteCurrentRecording(state));
  state.els.god.addEventListener("click", () => toggleGodModeFromRail(state));
  state.els.fullscreen.addEventListener("click", () => void toggleFullscreenFromRail(state));
  window.addEventListener("keydown", (event) => handlePlaybackDebugKeyDown(state, event), true);
  document.addEventListener("fullscreenchange", () => handleFullscreenChange(state));
  document.addEventListener("webkitfullscreenchange", () => handleFullscreenChange(state));
  agentController.bindButton(state, state.els.agent);

  syncOverlayState(state);
}

async function refreshWhenLevelChanges(state) {
  syncPlaybackState(state);
  const key = getCurrentKey();
  if (key && key !== state.currentKey) {
    await refreshStatus(state);
    return;
  }
  syncOverlayState(state);
  if (!key && state.currentState !== "idle") {
    state.currentKey = "";
    state.currentRecord = null;
    state.records = [];
    state.selectedRecordIndex = 0;
    state.selectedTraceSummary = null;
    clearSelectedTraceTicks(state);
    clearPlaybackDebugState(state);
    setUiState(state, "idle");
  }
}

function scheduleRefresh(state) {
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(() => void refreshStatus(state, true), 400);
}

async function refreshStatus(state, force = false, preferredRecordId = null) {
  const context = getCurrentContext();
  if (!context) {
    state.currentKey = "";
    state.currentRecord = null;
    state.records = [];
    state.selectedRecordIndex = 0;
    state.selectedTraceSummary = null;
    clearSelectedTraceTicks(state);
    clearPlaybackDebugState(state);
    setUiState(state, "idle");
    return;
  }

  const key = getContextKey(context);
  if (!force && key === state.currentKey && state.currentState !== "idle" && !state.busyAction) {
    return;
  }
  state.currentKey = key;

  const previousRecordId = preferredRecordId ?? state.currentRecord?.id;
  setUiState(state, state.currentRecord ? "available" : "idle", "refresh");
  try {
    const result = await apiFetch(`${API_BASE}/${context.playData}/${context.level}/records`);
    setRecordList(state, Array.isArray(result.records) ? result.records : [], previousRecordId);
    setUiState(state, state.currentRecord ? "available" : "missing");
  } catch (error) {
    if (error.status === 404) {
      state.currentRecord = null;
      state.records = [];
      state.selectedRecordIndex = 0;
      state.selectedTraceSummary = null;
      clearSelectedTraceTicks(state);
      clearPlaybackDebugState(state);
      setUiState(state, "missing");
      return;
    }
    state.currentRecord = null;
    state.records = [];
    state.selectedRecordIndex = 0;
    state.selectedTraceSummary = null;
    clearSelectedTraceTicks(state);
    clearPlaybackDebugState(state);
    setUiState(state, "error");
  }
}

function setRecordList(state, records, preferredRecordId = null) {
  state.records = records;
  if (!records.length) {
    state.selectedRecordIndex = 0;
    state.currentRecord = null;
    state.selectedTraceSummary = null;
    clearSelectedTraceTicks(state);
    return;
  }

  const preferredIndex = preferredRecordId
    ? records.findIndex((record) => record?.id === preferredRecordId)
    : -1;
  state.selectedRecordIndex = preferredIndex >= 0 ? preferredIndex : 0;
  applySelectedRecord(state);
}

function applySelectedRecord(state) {
  const record = state.records[state.selectedRecordIndex] ?? null;
  state.currentRecord = record;
  state.selectedTraceSummary = record?.trace ?? null;
  clearSelectedTraceTicks(state);
  clearPlaybackDebugState(state);
  syncOverlayState(state);
  void loadSelectedTraceTicks(state, record);
}

async function loadSelectedTraceTicks(state, record) {
  const traceId = record?.traceId;
  if (typeof traceId !== "string" || !traceId) {
    return;
  }

  state.selectedTraceLoadId = traceId;
  try {
    const trace = await apiFetch(`/api/agent/traces/${encodeURIComponent(traceId)}`);
    if (state.selectedTraceLoadId !== traceId || state.currentRecord?.traceId !== traceId) {
      return;
    }
    state.selectedTraceId = traceId;
    state.selectedTraceTicks = extractTraceStepTicks(trace);
    syncOverlayState(state);
  } catch (_error) {
    if (state.selectedTraceLoadId === traceId) {
      state.selectedTraceId = "";
      state.selectedTraceTicks = [];
      syncOverlayState(state);
    }
  }
}

function extractTraceStepTicks(trace) {
  if (!Array.isArray(trace?.steps)) {
    return [];
  }
  return trace.steps
    .map((step) => getTraceStepTick(step))
    .filter((tick) => Number.isFinite(tick))
    .sort((left, right) => left - right);
}

function getTraceStepTick(step) {
  const stateTick = getFiniteNumber(step?.state?.tick);
  if (stateTick !== null) {
    return stateTick;
  }
  const history = Array.isArray(step?.historyTail) ? step.historyTail : [];
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const tick = getFiniteNumber(history[index]?.tick);
    if (tick !== null) {
      return tick;
    }
  }
  return null;
}

function clearSelectedTraceTicks(state) {
  state.selectedTraceId = "";
  state.selectedTraceTicks = [];
  state.selectedTraceLoadId = "";
}

function selectAdjacentRecord(state, delta) {
  if (state.records.length <= 1 || state.busyAction) {
    return;
  }
  const count = state.records.length;
  state.selectedRecordIndex = (state.selectedRecordIndex + delta + count) % count;
  state.playbackKey = "";
  clearStoredDemoStopTimer(state);
  applySelectedRecord(state);
  setUiState(state, state.currentRecord ? "available" : "missing");
}

async function playOrToggleCurrentRecording(state) {
  const context = getCurrentContext();
  if (!context) {
    clearPlaybackDebugState(state);
    setUiState(state, "idle");
    return;
  }

  if (isWrapperPlaybackActive(state)) {
    toggleStoredPlaybackPause(state);
    return;
  }

  setUiState(state, state.currentRecord ? "available" : "missing", "play");
  try {
    if (!state.currentRecord) {
      await refreshStatus(state, true);
    }
    const record = state.currentRecord;
    if (!record) {
      setUiState(state, "missing");
      return;
    }
    const demo = normalizeDemo(record.demo, context.playData, context.level);
    startStoredDemo(state, demo, context);
    state.playbackKey = getContextKey(context);
    state.currentRecord = record;
    setUiState(state, "available");
  } catch (_error) {
    setUiState(state, "error");
  }
}

async function deleteCurrentRecording(state) {
  const context = getCurrentContext();
  if (!context) {
    clearPlaybackDebugState(state);
    setUiState(state, "idle");
    return;
  }

  setUiState(state, state.currentRecord ? "available" : "missing", "delete");
  try {
    const nextRecord = getRecordAfterDelete(state);
    const recordId = state.currentRecord?.id;
    const traceId = state.currentRecord?.traceId;
    const query = recordId
      ? `?recordId=${encodeURIComponent(recordId)}`
      : traceId
        ? `?traceId=${encodeURIComponent(traceId)}`
        : "";
    const result = await apiFetch(`${API_BASE}/${context.playData}/${context.level}${query}`, {
      method: "DELETE",
    });
    await refreshStatus(state, true, nextRecord?.id ?? result.latestRecord?.id ?? null);
  } catch (_error) {
    setUiState(state, "error");
  }
}

function getRecordAfterDelete(state) {
  if (state.records.length <= 1) {
    return null;
  }
  const nextIndex = Math.min(state.selectedRecordIndex, state.records.length - 2);
  return state.records.filter((_record, index) => index !== state.selectedRecordIndex)[nextIndex] ?? null;
}

function startStoredDemo(state, demo, context) {
  if (typeof window.startGame !== "function") {
    throw new Error("legacy startGame is unavailable");
  }

  clearPlaybackDebugState(state);
  clearStoredDemoStopTimer(state);

  if (!Array.isArray(window.playerDemoData)) {
    window.playerDemoData = [];
  }

  window.playData = context.playData;
  window.curLevel = context.level;
  window.levelData = window.getPlayVerData(context.playData);
  window.playerDemoData[context.level - 1] = demo;
  window.demoSoundOff = 1;
  window.playMode = window.PLAY_DEMO_ONCE;
  state.playbackSaveGuard = createPlaybackSaveGuard(demo, context);

  if (typeof window.anyKeyStopDemo === "function") {
    window.anyKeyStopDemo();
  }
  window.startGame(1);
  if (typeof window.showTipsText === "function") {
    window.setTimeout(() => window.showTipsText("HIT ANY KEY TO STOP DEMO", 3500), 50);
  }
  scheduleFailedDemoStop(state, demo, context);
}

function createPlaybackSaveGuard(demo, context) {
  return {
    key: getContextKey(context),
    actionLength: copyArray(demo?.action).length,
    goldDropLength: copyArray(demo?.goldDrop).length,
    bornPosLength: copyArray(demo?.bornPos).length,
    time: Number(demo?.time ?? 0),
    expiresAt: Date.now() + 10 * 60 * 1000,
  };
}

function isStoredPlaybackSave(state, playData, level, demoDataInfo) {
  const guard = state.playbackSaveGuard;
  if (!guard) {
    return false;
  }
  if (Date.now() > guard.expiresAt) {
    state.playbackSaveGuard = null;
    return false;
  }

  const key = getContextKey({ playData, level });
  if (key !== guard.key) {
    return false;
  }

  const actionLength = copyArray(demoDataInfo?.action).length;
  const goldDropLength = copyArray(demoDataInfo?.goldDrop).length;
  const bornPosLength = copyArray(demoDataInfo?.bornPos).length;
  const time = Number(demoDataInfo?.time ?? 0);
  const matchesPlayedDemo =
    actionLength === guard.actionLength &&
    goldDropLength === guard.goldDropLength &&
    bornPosLength === guard.bornPosLength &&
    time === guard.time;

  if (matchesPlayedDemo || Number(window.playMode) === Number(window.PLAY_DEMO_ONCE)) {
    state.playbackSaveGuard = null;
    return true;
  }
  return false;
}

function scheduleFailedDemoStop(state, demo, context) {
  const demoTime = Number(demo?.time);
  if (Number(demo?.state) === 1 || !Number.isFinite(demoTime) || demoTime <= 0) {
    return;
  }

  state.playbackStopTimer = window.setInterval(() => {
    const stillPlayingDemo =
      Number(window.playMode) === Number(window.PLAY_DEMO_ONCE) &&
      Number(window.playData) === Number(context.playData) &&
      Number(window.curLevel) === Number(context.level);
    if (!stillPlayingDemo) {
      clearStoredDemoStopTimer(state);
      return;
    }
    if (state.playbackPaused) {
      return;
    }
    if (Number(window.demoTickCount) >= demoTime) {
      stopFailedDemoPlayback(state);
    }
  }, FAILED_DEMO_STOP_POLL_MS);
}

function stopFailedDemoPlayback(state) {
  clearStoredDemoStopTimer(state);
  clearPlaybackDebugState(state);
  if ("ACT_STOP" in window) {
    window.keyAction = window.ACT_STOP;
  }
  if (typeof window.stopPlayTicker === "function") {
    window.stopPlayTicker();
  }
  state.playbackKey = "";
  setUiState(state, state.currentRecord ? "available" : "missing");
  if (typeof window.showTipsText === "function") {
    window.showTipsText("FAILED DEMO ENDED", 2500);
  }
}

function clearStoredDemoStopTimer(state) {
  if (state.playbackStopTimer) {
    window.clearInterval(state.playbackStopTimer);
    state.playbackStopTimer = 0;
  }
}

function handlePlaybackDebugKeyDown(state, event) {
  if (!isWrapperPlaybackActive(state)) {
    return;
  }

  const isSpace = event.code === "Space" || event.key === " ";
  const isPeriod = event.code === "Period" || event.key === ".";
  if (!isSpace && !isPeriod) {
    return;
  }

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation?.();

  if (isSpace) {
    toggleStoredPlaybackPause(state);
    return;
  }
  if (state.playbackPaused) {
    stepStoredPlaybackSegment(state);
  }
}

function isWrapperPlaybackActive(state) {
  if (!state.playbackKey) {
    return false;
  }
  const context = getCurrentContext();
  return Boolean(
    context &&
      getContextKey(context) === state.playbackKey &&
      Number(window.playMode) === Number(window.PLAY_DEMO_ONCE),
  );
}

function toggleStoredPlaybackPause(state) {
  if (state.playbackStepping) {
    return;
  }
  if (state.playbackPaused) {
    resumeStoredPlayback(state);
  } else {
    pauseStoredPlayback(state);
  }
}

function pauseStoredPlayback(state, { showTip = true } = {}) {
  if (!isWrapperPlaybackActive(state)) {
    clearPlaybackDebugState(state);
    return false;
  }
  if (typeof window.gamePause === "function" && Number(window.gameState) !== Number(window.GAME_PAUSE)) {
    window.gamePause();
  }
  if (typeof window.stopPlayTicker === "function") {
    window.stopPlayTicker();
  }
  if (typeof window.stopAllSpriteObj === "function") {
    window.stopAllSpriteObj();
  }
  state.playbackPaused = true;
  if (showTip && typeof window.showTipsText === "function") {
    window.showTipsText("DEMO PAUSED", 0);
  }
  syncOverlayState(state);
  return true;
}

function resumeStoredPlayback(state, { showTip = true } = {}) {
  if (!isWrapperPlaybackActive(state)) {
    clearPlaybackDebugState(state);
    return false;
  }
  if (typeof window.gameResume === "function" && Number(window.gameState) === Number(window.GAME_PAUSE)) {
    window.gameResume();
  }
  if (typeof window.startAllSpriteObj === "function") {
    window.startAllSpriteObj();
  }
  if (typeof window.startPlayTicker === "function") {
    window.startPlayTicker();
  }
  state.playbackPaused = false;
  if (showTip && typeof window.showTipsText === "function") {
    window.showTipsText("", 1000);
  }
  syncOverlayState(state);
  return true;
}

function stepStoredPlaybackSegment(state) {
  if (!state.playbackPaused || state.playbackStepping || !isWrapperPlaybackActive(state)) {
    return;
  }

  const startRecordIdx = getFiniteNumber(window.demoRecordIdx);
  const startTick = getFiniteNumber(window.demoTickCount);
  state.playbackStepping = true;
  state.playbackStepStartedAt = performance.now();
  resumeStoredPlayback(state, { showTip: false });
  syncOverlayState(state);

  const pollStep = (now) => {
    if (!state.playbackStepping) {
      return;
    }
    if (!isWrapperPlaybackActive(state)) {
      clearPlaybackDebugState(state);
      syncOverlayState(state);
      return;
    }

    const currentRecordIdx = getFiniteNumber(window.demoRecordIdx);
    const currentTick = getFiniteNumber(window.demoTickCount);
    const advancedByRecord =
      startRecordIdx !== null && currentRecordIdx !== null && currentRecordIdx > startRecordIdx;
    const advancedByTick =
      startRecordIdx === null && startTick !== null && currentTick !== null && currentTick > startTick;
    const timedOut = now - state.playbackStepStartedAt >= PLAYBACK_STEP_TIMEOUT_MS;

    if (advancedByRecord || advancedByTick || timedOut) {
      state.playbackStepRaf = 0;
      state.playbackStepping = false;
      pauseStoredPlayback(state, { showTip: !timedOut });
      if (timedOut && typeof window.showTipsText === "function") {
        window.showTipsText("DEMO STEP TIMEOUT", 2500);
      }
      syncOverlayState(state);
      return;
    }

    state.playbackStepRaf = window.requestAnimationFrame(pollStep);
  };

  state.playbackStepRaf = window.requestAnimationFrame(pollStep);
}

function getFiniteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clearPlaybackDebugState(state) {
  if (state.playbackStepRaf) {
    window.cancelAnimationFrame(state.playbackStepRaf);
  }
  stopDebugBarRefresh(state);
  state.playbackPaused = false;
  state.playbackStepping = false;
  state.playbackStepRaf = 0;
  state.playbackStepStartedAt = 0;
}

function startDebugBarRefresh(state) {
  if (state.debugBarRaf) {
    return;
  }
  const tick = () => {
    state.debugBarRaf = 0;
    if (!isWrapperPlaybackActive(state)) {
      syncDebugBar(state);
      return;
    }
    syncDebugBar(state);
    state.debugBarRaf = window.requestAnimationFrame(tick);
  };
  state.debugBarRaf = window.requestAnimationFrame(tick);
}

function stopDebugBarRefresh(state) {
  if (state.debugBarRaf) {
    window.cancelAnimationFrame(state.debugBarRaf);
    state.debugBarRaf = 0;
  }
}

function getCurrentContext() {
  const playData = Number(window.playData);
  const level = Number(window.curLevel);
  if (!isBuiltInPlayData(playData) || !Number.isInteger(level) || level <= 0) {
    return null;
  }
  return { playData, level };
}

function getCurrentKey() {
  const context = getCurrentContext();
  return context ? getContextKey(context) : "";
}

function getContextKey(context) {
  return `${context.playData}:${context.level}`;
}

function isBuiltInPlayData(playData) {
  return (
    Number.isInteger(playData) &&
    playData > 0 &&
    Number.isInteger(Number(window.maxPlayId)) &&
    playData <= Number(window.maxPlayId)
  );
}

function setUiState(state, nextState, busyAction = "") {
  state.currentState = nextState;
  state.busyAction = busyAction;
  syncOverlayState(state);
}

function toggleGodModeFromRail(state) {
  if (typeof window.toggleGodMode !== "function") {
    setUiState(state, "error");
    return;
  }
  window.toggleGodMode();
  syncOverlayState(state);
}

async function toggleFullscreenFromRail(state) {
  if (!isFullscreenSupported()) {
    setUiState(state, "error");
    return;
  }

  setUiState(state, state.currentState, "fullscreen");
  try {
    if (isFullscreenActive()) {
      await exitFullscreen();
    } else {
      await enterFullscreen();
    }
    scheduleLegacyFullscreenRestart(state);
    setUiState(state, state.currentRecord ? "available" : "missing");
  } catch (_error) {
    setUiState(state, "error");
  }
}

function handleFullscreenChange(state) {
  syncOverlayState(state);
  scheduleLegacyFullscreenRestart(state);
}

function scheduleLegacyFullscreenRestart(state) {
  window.clearTimeout(state.fullscreenRestartTimer);
  state.fullscreenRestartTimer = window.setTimeout(
    () => restartLegacyForFullscreen(state),
    FULLSCREEN_RESTART_DELAY_MS,
  );
}

function restartLegacyForFullscreen(state) {
  state.fullscreenRestartTimer = 0;
  state.playbackKey = "";
  clearPlaybackDebugState(state);
  clearStoredDemoStopTimer(state);

  try {
    state.agentAbort?.abort();
    stopLegacyRuntime();
    removeLegacyOverlayCanvases();
    resetLegacyInput();

    if (typeof window.init !== "function") {
      throw new Error("legacy init is unavailable");
    }

    window.init();
    setUiState(state, state.currentRecord ? "available" : "missing");
    scheduleRefresh(state);
  } catch (error) {
    console.error("Failed to restart Lode Runner after fullscreen change", error);
    setUiState(state, "error");
  }
}

function stopLegacyRuntime() {
  if (typeof window.stopPlayTicker === "function") {
    window.stopPlayTicker();
  }
  if (typeof window.clearIdleDemoTimer === "function") {
    window.clearIdleDemoTimer();
  }
  if (typeof window.disableStageClickEvent === "function") {
    window.disableStageClickEvent();
  }
  if (window.mainStage?.removeAllEventListeners) {
    window.mainStage.removeAllEventListeners();
  }
  if (window.mainStage?.removeAllChildren) {
    window.mainStage.removeAllChildren();
  }
}

function removeLegacyOverlayCanvases() {
  for (const canvas of document.querySelectorAll("body > canvas")) {
    if (canvas.id !== "canvas") {
      canvas.remove();
    }
  }
}

function resetLegacyInput() {
  if ("ACT_STOP" in window) {
    window.keyAction = window.ACT_STOP;
  }
  document.onkeydown = null;
  document.onkeyup = null;
}

function isFullscreenSupported() {
  const root = document.documentElement;
  return Boolean(
    document.fullscreenEnabled ||
      document.webkitFullscreenEnabled ||
      root.requestFullscreen ||
      root.webkitRequestFullscreen
  );
}

function isFullscreenActive() {
  return Boolean(document.fullscreenElement || document.webkitFullscreenElement);
}

function enterFullscreen() {
  const root = document.documentElement;
  if (root.requestFullscreen) {
    return root.requestFullscreen();
  }
  return root.webkitRequestFullscreen();
}

function exitFullscreen() {
  if (document.exitFullscreen) {
    return document.exitFullscreen();
  }
  return document.webkitExitFullscreen();
}

function syncPlaybackState(state) {
  const playbackKey = state.playbackKey;
  if (!playbackKey) {
    clearPlaybackDebugState(state);
    return false;
  }

  const context = getCurrentContext();
  const matchesContext = Boolean(context && getContextKey(context) === playbackKey);
  const isDemoOnce = Number(window.playMode) === Number(window.PLAY_DEMO_ONCE);
  const active = matchesContext && isDemoOnce;

  if (!active) {
    state.playbackKey = "";
    clearPlaybackDebugState(state);
    clearStoredDemoStopTimer(state);
  }
  return active;
}

function syncOverlayState(state) {
  const overlay = state.els.overlay;
  if (!overlay) {
    return;
  }

  const hasRecord = Boolean(state.currentRecord);
  const playbackActive = syncPlaybackState(state);
  const playbackPaused = playbackActive && state.playbackPaused;
  const godModeActive = Number(window.godMode) === 1;
  const godModeSupported = typeof window.toggleGodMode === "function";
  const fullscreenActive = isFullscreenActive();
  const fullscreenSupported = isFullscreenSupported();
  overlay.dataset.state = state.currentState;
  overlay.dataset.hasRecord = hasRecord ? "true" : "false";
  overlay.dataset.playback = playbackActive ? "true" : "false";
  overlay.dataset.playbackPaused = playbackPaused ? "true" : "false";
  overlay.dataset.playbackStepping = state.playbackStepping ? "true" : "false";
  overlay.dataset.godMode = godModeActive ? "true" : "false";
  overlay.dataset.fullscreen = fullscreenActive ? "true" : "false";

  if (state.busyAction) {
    overlay.dataset.busy = state.busyAction;
  } else {
    delete overlay.dataset.busy;
  }

  state.els.play.disabled = !hasRecord || Boolean(state.busyAction);
  state.els.delete.disabled = !hasRecord || Boolean(state.busyAction) || playbackActive;
  const canNavigateRecords = state.records.length > 1 && !state.busyAction && !playbackActive;
  state.els.prev.disabled = !canNavigateRecords;
  state.els.next.disabled = !canNavigateRecords;
  const agentButtonState = agentController.getButtonState(state);
  state.els.agent.disabled = agentButtonState.disabled;
  state.els.god.disabled = !godModeSupported || Boolean(state.busyAction);
  state.els.fullscreen.disabled = !fullscreenSupported || Boolean(state.busyAction);

  state.els.play.dataset.icon = playbackPaused ? "▶" : playbackActive ? "⏸" : "▶";
  const playTitle = state.playbackStepping
    ? "Stepping to next recorded action"
    : playbackPaused
      ? "Resume demo playback"
      : playbackActive
        ? "Pause demo playback"
        : hasRecord
          ? "Play stored recording"
          : "No stored recording for this level";
  state.els.play.title = playTitle;
  state.els.play.setAttribute("aria-label", playTitle);
  state.els.delete.title = playbackActive
    ? "Stop playback before deleting"
    : hasRecord
      ? "Delete stored recording"
      : "No stored recording to delete";
  state.els.prev.title = playbackActive
    ? "Stop playback before selecting another run"
    : canNavigateRecords
      ? "Previous stored run"
      : "No previous stored run";
  state.els.next.title = playbackActive
    ? "Stop playback before selecting another run"
    : canNavigateRecords
      ? "Next stored run"
      : "No next stored run";
  state.els.agent.title = agentButtonState.title;
  state.els.agent.setAttribute("aria-label", agentButtonState.title);
  state.els.god.title = godModeSupported
    ? godModeActive
      ? "God mode is on"
      : "God mode is off"
    : "God mode unavailable";
  state.els.fullscreen.title = fullscreenSupported
    ? fullscreenActive
      ? "Exit full screen"
      : "Enter full screen"
    : "Full screen unavailable";
  syncDebugBar(state);
  if (playbackActive) {
    startDebugBarRefresh(state);
  } else {
    stopDebugBarRefresh(state);
  }
}

function syncDebugBar(state) {
  const debugBar = state.els.debugBar;
  if (!debugBar) {
    return;
  }
  if (!state.currentRecord || state.agentRunning || state.busyAction === "agent") {
    debugBar.hidden = true;
    debugBar.textContent = "";
    return;
  }

  debugBar.hidden = false;
  debugBar.textContent = formatDebugLine(state);
}

function formatDebugLine(state) {
  const record = state.currentRecord;
  const trace = state.selectedTraceSummary;
  const model = record?.solver?.model ?? trace?.model?.model ?? "unknown";
  return [
    `run ${state.selectedRecordIndex + 1}/${Math.max(state.records.length, 1)}`,
    `${record.source ?? "unknown"} ${record.result ?? "unknown"}`,
    `trace ${shortId(record.traceId)}`,
    `model ${model}`,
    `demo ${formatDemoTime(record.demo?.time)}`,
    formatPlaybackProgress(state),
  ].join(" | ");
}

function shortId(value) {
  return typeof value === "string" && value ? value.slice(0, 8) : "none";
}

function formatDemoTime(value) {
  const time = Number(value);
  if (!Number.isFinite(time) || time <= 0) {
    return "-";
  }
  return `${Math.round(time)}s`;
}

function formatPlaybackProgress(state) {
  const record = state.currentRecord;
  const trace = state.selectedTraceSummary;
  const traceStepCount = getPositiveInteger(trace?.stepCount);
  if (record?.traceId && traceStepCount !== null) {
    if (isWrapperPlaybackActive(state)) {
      const traceProgress = getTracePlaybackProgress(state, traceStepCount);
      return `steps ${traceProgress}/${traceStepCount}`;
    }
    return `steps ${traceStepCount}`;
  }

  const demoStepCount = getDemoStepCount(record?.demo);
  if (isWrapperPlaybackActive(state)) {
    return `keys ${getDemoRecordProgress(demoStepCount)}/${demoStepCount}`;
  }
  return `keys ${demoStepCount}`;
}

function getTracePlaybackProgress(state, total) {
  if (state.selectedTraceId !== state.currentRecord?.traceId || !state.selectedTraceTicks.length) {
    return "-";
  }
  const currentTick = getFiniteNumber(window.demoTickCount);
  if (currentTick === null) {
    return 0;
  }
  let count = 0;
  for (const tick of state.selectedTraceTicks) {
    if (tick > currentTick) {
      break;
    }
    count += 1;
  }
  return Math.min(Math.max(count, 0), total);
}

function getDemoRecordProgress(total) {
  const currentIndex = getFiniteNumber(window.demoRecordIdx);
  if (currentIndex === null) {
    return 0;
  }
  return Math.min(Math.max(Math.floor(currentIndex), 0), total);
}

function getDemoStepCount(demo) {
  const action = Array.isArray(demo?.action) ? demo.action : [];
  return Math.floor(action.length / 2);
}

function getPositiveInteger(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    return null;
  }
  return Math.floor(number);
}

async function apiFetch(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.error || response.statusText);
    error.status = response.status;
    throw error;
  }
  return body;
}
