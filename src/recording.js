import { createAgentController } from "./agent.js";

const INSTALL_KEY = "__lodeRunnerRecording";
const API_BASE = "/api/recordings";
const OVERLAY_ID = "recording-overlay";
const FULLSCREEN_RESTART_DELAY_MS = 180;
const FAILED_DEMO_STOP_POLL_MS = 100;
const PLAYBACK_STEP_TIMEOUT_MS = 8000;
const BACKEND_HEALTH_TIMEOUT_MS = 3000;
const LEGACY_TICKS_PER_SECOND = 16;
const PLAYBACK_VIDEO_MIME_TYPES = [
  "video/mp4;codecs=avc1.42E01E,mp4a.40.2",
  "video/mp4;codecs=avc1.42E01E",
  "video/mp4",
];
const RAIL_BUTTONS = [
  {
    action: "agent", icon: "✨", label: "Solve with AI agent",
    title: "Solve this game with the AI agent",
  },
  {
    action: "play", icon: "▶", label: "Play stored recording",
    onClick: (state, event) => void playOrToggleCurrentRecording(state, event),
  },
  {
    action: "prev", icon: "⏮", label: "Previous stored run",
    onClick: (state) => selectAdjacentRecord(state, -1),
  },
  {
    action: "next", icon: "⏭", label: "Next stored run",
    onClick: (state) => selectAdjacentRecord(state, 1),
  },
  {
    action: "delete", icon: "✕", label: "Delete stored recording",
    onClick: (state) => void deleteCurrentRecording(state),
  },
  {
    action: "god", icon: "★", label: "Toggle god mode",
    onClick: (state) => toggleGodModeFromRail(state),
  },
  {
    action: "fullscreen", icon: "⛶", label: "Toggle full screen",
    onClick: (state) => void toggleFullscreenFromRail(state),
  },
];

const agentController = createAgentController({
  apiFetch,
  beginUiAction,
  checkBackendHealth,
  clearPlaybackDebugState,
  getCurrentContext,
  formatGameLevel,
  finishUiAction,
  normalizeDemo,
  recordingApiBase: API_BASE,
  refreshStatus,
  stopPlaybackVideoRecording,
  syncOverlayState,
});

export function installRecording() {
  if (window[INSTALL_KEY]?.installed) {
    return window[INSTALL_KEY];
  }

  const state = {
    installed: true,
    currentGameLevel: "",
    currentRecord: null,
    records: [],
    selectedRecordIndex: 0,
    selectedTraceSummary: null,
    selectedTraceId: "",
    selectedTraceTicks: [],
    selectedTraceLoadId: "",
    uiError: false,
    busyAction: "",
    backendStatus: "checking",
    backendCheckPromise: null,
    playbackGameLevel: "",
    saveTimer: 0,
    refreshTimer: 0,
    fullscreenRestartTimer: 0,
    playbackStopTimer: 0,
    playbackSaveGuard: null,
    playbackPhase: "inactive",
    playbackStepRaf: 0,
    playbackStepStartedAt: 0,
    videoRecorder: null,
    videoStream: null,
    videoChunks: [],
    videoRecording: false,
    videoStopping: false,
    videoDownloadOnStop: true,
    videoRecordId: "",
    videoMimeType: "",
    debugBarRaf: 0,
    els: {},
  };
  agentController.initState(state);
  window[INSTALL_KEY] = state;

  createOverlay(state);
  patchRecordingSave(state);
  installEvaluationApi(state);
  void initializeBackend(state);
  state.refreshTimer = window.setInterval(
    () => void refreshWhenLevelChanges(state),
    1200,
  );

  return state;
}

function installEvaluationApi(state) {
  window.__lodeRunnerEvaluation = Object.freeze({
    ready() {
      return (
        state.installed &&
        state.backendStatus === "online" &&
        window.lodeRunnerAgentHooks?.isReady?.() &&
        !state.agentRunning &&
        !state.busyAction
      );
    },

    status() {
      return {
        ready: this.ready(),
        backendStatus: state.backendStatus,
        agentRunning: state.agentRunning,
        busyAction: state.busyAction,
        godMode: Number(window.godMode),
      };
    },

    prepare(options = {}) {
      ensureEvaluationGodMode(Boolean(options.godMode));
      return this.status();
    },

    async runAttempt(options = {}) {
      ensureEvaluationGodMode(Boolean(options.godMode));
      const record = await agentController.runEvaluationAttempt(state);
      if (!record || record.source !== "agent") {
        throw new Error("agent evaluator produced no recording");
      }
      return {
        id: record.id,
        traceId: record.traceId,
        playData: record.playData,
        level: record.level,
        result: record.result,
        savedAt: record.savedAt,
        failureReason: record.solver?.failureReason ?? null,
        demoTime: record.demo?.time ?? null,
        godMode: record.demo?.godMode ?? null,
      };
    },
  });
}

function ensureEvaluationGodMode(requestedGodMode) {
  const enabled = Number(window.godMode) === 1;
  if (enabled !== requestedGodMode) {
    if (typeof window.toggleGodMode !== "function") {
      throw new Error(`cannot ${requestedGodMode ? "enable" : "disable"} god mode for evaluation`);
    }
    window.toggleGodMode();
  }
  if ((Number(window.godMode) === 1) !== requestedGodMode) {
    throw new Error(`evaluation requires god mode ${requestedGodMode ? "on" : "off"}`);
  }
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
  if (!shouldSaveUserCompletion(state)) {
    return;
  }
  const playDataId = Number(playData);
  const level = Number(demoDataInfo?.level);

  if (
    !isBuiltInPlayData(playDataId) ||
    !Number.isInteger(level) ||
    level <= 0
  ) {
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

  beginUiAction(state, "save");
  try {
    const record = await apiFetch(`${API_BASE}/${playDataId}/${level}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demo, source: "user", result: "success" }),
    });
    state.currentRecord = record;
    finishUiAction(state);
    scheduleRefresh(state);
  } catch (_error) {
    finishUiAction(state, { error: true });
    void checkBackendHealth(state);
  }
}

function shouldSaveUserCompletion(state) {
  return !state.agentRunning && state.busyAction !== "agent";
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

function arrayLength(value) {
  return Array.isArray(value) ? value.length : 0;
}

function createOverlay(state) {
  const existing = document.getElementById(OVERLAY_ID);
  if (existing) {
    existing.remove();
  }
  document
    .querySelectorAll(".recording-debug-bar")
    .forEach((element) => element.remove());

  const overlay = document.createElement("section");
  overlay.id = OVERLAY_ID;
  overlay.className = "recording-rail";
  overlay.setAttribute("aria-label", "Recording");
  for (const { action, icon, label, title = label, onClick } of RAIL_BUTTONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recording-rail-button";
    button.dataset.action = action;
    button.dataset.icon = icon;
    button.setAttribute("aria-label", label);
    button.title = title;
    state.els[action] = button;
    if (onClick) {
      button.addEventListener("click", (event) => onClick(state, event));
    }
    overlay.appendChild(button);
  }
  document.body.appendChild(overlay);
  const debugBar = document.createElement("div");
  debugBar.className = "recording-debug-bar";
  debugBar.hidden = true;
  debugBar.setAttribute("aria-live", "polite");
  document.body.appendChild(debugBar);

  state.els.overlay = overlay;
  state.els.debugBar = debugBar;
  window.addEventListener(
    "keydown",
    (event) => handlePlaybackDebugKeyDown(state, event),
    true,
  );
  document.addEventListener("fullscreenchange", () =>
    handleFullscreenChange(state),
  );
  document.addEventListener("webkitfullscreenchange", () =>
    handleFullscreenChange(state),
  );
  window.addEventListener("focus", () => void recoverBackendOnFocus(state));
  agentController.bindButton(state, state.els.agent);

  syncOverlayState(state);
}

async function refreshWhenLevelChanges(state) {
  syncPlaybackState(state);
  const gameLevel = getCurrentGameLevel();
  if (gameLevel && gameLevel !== state.currentGameLevel) {
    await refreshStatus(state);
    return;
  }
  syncOverlayState(state);
  if (!gameLevel && state.currentGameLevel) {
    state.currentGameLevel = "";
    clearRecordSelection(state, { stopPlayback: true });
    finishUiAction(state);
  }
}

async function initializeBackend(state) {
  if (await checkBackendHealth(state)) {
    await refreshStatus(state);
  }
}

async function recoverBackendOnFocus(state) {
  if (state.backendStatus !== "offline") {
    return;
  }
  if (await checkBackendHealth(state)) {
    await refreshStatus(state, true);
  }
}

async function checkBackendHealth(state) {
  if (state.backendCheckPromise) {
    return state.backendCheckPromise;
  }

  state.backendStatus = "checking";
  syncOverlayState(state);
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    BACKEND_HEALTH_TIMEOUT_MS,
  );
  state.backendCheckPromise = fetch("/api/health", {
    cache: "no-store",
    signal: controller.signal,
  })
    .then(async (response) => {
      const body = await response.json().catch(() => null);
      return response.ok && body?.ok === true;
    })
    .catch(() => false)
    .then((online) => {
      state.backendStatus = online ? "online" : "offline";
      syncOverlayState(state);
      return online;
    })
    .finally(() => {
      window.clearTimeout(timeout);
      state.backendCheckPromise = null;
    });
  return state.backendCheckPromise;
}

function scheduleRefresh(state) {
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(
    () => void refreshStatus(state, true),
    400,
  );
}

async function refreshStatus(state, force = false, preferredRecordId = null) {
  const context = getCurrentContext();
  if (!context) {
    state.currentGameLevel = "";
    clearRecordSelection(state, { stopPlayback: true });
    finishUiAction(state);
    return;
  }

  const gameLevel = formatGameLevel(context);
  const gameLevelChanged = gameLevel !== state.currentGameLevel;
  if (!force && gameLevel === state.currentGameLevel && !state.busyAction) {
    return;
  }
  state.currentGameLevel = gameLevel;

  if (state.backendStatus !== "online") {
    if (gameLevelChanged) {
      clearRecordSelection(state);
    }
    finishUiAction(state);
    return;
  }

  const previousRecordId = preferredRecordId ?? state.currentRecord?.id;
  beginUiAction(state, "refresh");
  try {
    const result = await apiFetch(
      `${API_BASE}/${context.playData}/${context.level}/records`,
      { cache: "no-store" },
    );
    setRecordList(
      state,
      Array.isArray(result.records) ? result.records : [],
      previousRecordId,
    );
    finishUiAction(state);
  } catch (error) {
    if (error.status === 404) {
      clearRecordSelection(state, { stopPlayback: true });
      finishUiAction(state);
      return;
    }
    if (gameLevelChanged) {
      clearRecordSelection(state, { stopPlayback: true });
    }
    finishUiAction(state, { error: true });
    void checkBackendHealth(state);
  }
}

function clearRecordSelection(state, { stopPlayback = false } = {}) {
  state.currentRecord = null;
  state.records = [];
  state.selectedRecordIndex = 0;
  state.selectedTraceSummary = null;
  clearSelectedTraceTicks(state);
  if (stopPlayback) {
    stopPlaybackVideoRecording(state, { download: false });
    clearPlaybackDebugState(state);
  }
}

function setRecordList(state, records, preferredRecordId = null) {
  state.records = records;
  if (!records.length) {
    clearRecordSelection(state);
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
    const response = await apiFetch(
      `/api/agent/traces/${encodeURIComponent(traceId)}`,
    );
    if (response?.version !== 4 || !Array.isArray(response.run?.steps)) {
      throw new Error("Expected a v4 trace response");
    }
    const trace = response.run;
    if (
      state.selectedTraceLoadId !== traceId ||
      state.currentRecord?.traceId !== traceId
    ) {
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
    void checkBackendHealth(state);
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
  return getFiniteNumber(step?.state?.tick);
}

function clearSelectedTraceTicks(state) {
  state.selectedTraceId = "";
  state.selectedTraceTicks = [];
  state.selectedTraceLoadId = "";
}

async function selectAdjacentRecord(state, delta) {
  if (!canNavigateStoredRecords(state)) {
    return;
  }
  const gameLevel = getCurrentGameLevel();
  const previousRecordId = state.currentRecord?.id;
  await refreshStatus(state, true);
  if (state.uiError || gameLevel !== getCurrentGameLevel()) {
    return;
  }
  const count = state.records.length;
  if (!count || !state.records.some((record) => record.id === previousRecordId)) {
    return;
  }
  state.selectedRecordIndex =
    (state.selectedRecordIndex + delta + count) % count;
  state.playbackGameLevel = "";
  stopPlaybackVideoRecording(state, { download: false });
  clearStoredDemoStopTimer(state);
  applySelectedRecord(state);
  finishUiAction(state);
}

async function playOrToggleCurrentRecording(
  state,
  event = null,
  { startPaused = false } = {},
) {
  const context = getCurrentContext();
  if (!context) {
    clearPlaybackDebugState(state);
    finishUiAction(state);
    return;
  }

  if (isWrapperPlaybackActive(state)) {
    toggleStoredPlaybackPause(state);
    return;
  }

  beginUiAction(state, "play");
  let videoCapture = null;
  try {
    if (!state.currentRecord) {
      await refreshStatus(state, true);
    }
    const record = state.currentRecord;
    if (!record) {
      finishUiAction(state);
      return;
    }
    const demo = normalizeDemo(record.demo, context.playData, context.level);
    videoCapture = isPlaybackVideoRecordingRequested(event)
      ? await requestPlaybackVideoCapture()
      : null;
    startStoredDemo(state, demo, context);
    state.playbackGameLevel = formatGameLevel(context);
    state.playbackPhase = "playing";
    state.currentRecord = record;
    if (videoCapture) {
      startPlaybackVideoRecording(state, record, videoCapture);
    }
    if (startPaused) {
      pauseStoredPlayback(state);
    }
    finishUiAction(state);
  } catch (_error) {
    stopMediaStream(videoCapture?.stream);
    finishUiAction(state, { error: true });
    void checkBackendHealth(state);
  }
}

async function deleteCurrentRecording(state) {
  if (state.busyAction || state.agentRunning || isWrapperPlaybackActive(state)) {
    return;
  }
  const context = getCurrentContext();
  if (!context) {
    clearPlaybackDebugState(state);
    finishUiAction(state);
    return;
  }

  if (state.backendStatus !== "online") {
    syncOverlayState(state);
    return;
  }
  const selectedRecordId = state.currentRecord?.id;
  if (!selectedRecordId) {
    return;
  }
  const gameLevel = getCurrentGameLevel();
  await refreshStatus(state, true, selectedRecordId);
  if (state.uiError || gameLevel !== getCurrentGameLevel() ||
      state.currentRecord?.id !== selectedRecordId) {
    return;
  }
  const record = state.currentRecord;
  if (!record || !confirmRecordingDelete(record)) {
    return;
  }
  beginUiAction(state, "delete");
  try {
    const nextRecord = getRecordAfterDelete(state);
    const recordId = record.id;
    const traceId = record.traceId;
    const query = recordId
      ? `?recordId=${encodeURIComponent(recordId)}`
      : traceId
        ? `?traceId=${encodeURIComponent(traceId)}`
        : "";
    const result = await apiFetch(
      `${API_BASE}/${context.playData}/${context.level}${query}`,
      {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmPinnedDeletion: record.pinned === true }),
      },
    );
    await refreshStatus(
      state,
      true,
      nextRecord?.id ?? result.latestRecord?.id ?? null,
    );
  } catch (_error) {
    finishUiAction(state, { error: true });
    void checkBackendHealth(state);
  }
}

function confirmRecordingDelete(record) {
  if (typeof window.confirm !== "function") {
    return false;
  }
  return window.confirm(buildRecordingDeleteConfirmation(record));
}

function buildRecordingDeleteConfirmation(record) {
  const runId = shortId(record?.traceId ?? record?.id);
  const linkedTraceWarning = record?.traceId
    ? "\n\nIts linked agent trace will also be deleted."
    : "";
  const pinnedWarning = record?.pinned === true
    ? "\n\nThis run is PINNED to protect it from removal. Deleting it will permanently remove that protected recording."
    : "";
  return `Delete ${record?.pinned === true ? "pinned" : "stored"} run ${runId}?${pinnedWarning}${linkedTraceWarning}\n\nThis cannot be undone.`;
}

function getRecordAfterDelete(state) {
  if (state.records.length <= 1) {
    return null;
  }
  const nextIndex = Math.min(
    state.selectedRecordIndex,
    state.records.length - 2,
  );
  return (
    state.records.filter(
      (_record, index) => index !== state.selectedRecordIndex,
    )[nextIndex] ?? null
  );
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
    window.setTimeout(
      () => window.showTipsText("HIT ANY KEY TO STOP DEMO", 3500),
      50,
    );
  }
  scheduleFailedDemoStop(state, demo, context);
}

function createPlaybackSaveGuard(demo, context) {
  return {
    gameLevel: formatGameLevel(context),
    actionLength: arrayLength(demo?.action),
    goldDropLength: arrayLength(demo?.goldDrop),
    bornPosLength: arrayLength(demo?.bornPos),
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

  const gameLevel = formatGameLevel({ playData, level });
  if (gameLevel !== guard.gameLevel) {
    return false;
  }

  const matchesPlayedDemo =
    arrayLength(demoDataInfo?.action) === guard.actionLength &&
    arrayLength(demoDataInfo?.goldDrop) === guard.goldDropLength &&
    arrayLength(demoDataInfo?.bornPos) === guard.bornPosLength &&
    Number(demoDataInfo?.time ?? 0) === guard.time;

  if (
    matchesPlayedDemo ||
    Number(window.playMode) === Number(window.PLAY_DEMO_ONCE)
  ) {
    state.playbackSaveGuard = null;
    return true;
  }
  return false;
}

function scheduleFailedDemoStop(state, demo, context) {
  const demoTime = Number(demo?.time);
  if (
    Number(demo?.state) === 1 ||
    !Number.isFinite(demoTime) ||
    demoTime <= 0
  ) {
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
    if (state.playbackPhase === "paused") {
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
  stopPlaybackVideoRecording(state);
  if ("ACT_STOP" in window) {
    window.keyAction = window.ACT_STOP;
  }
  if (typeof window.stopPlayTicker === "function") {
    window.stopPlayTicker();
  }
  state.playbackGameLevel = "";
  finishUiAction(state);
  if (typeof window.showTipsText === "function") {
    window.showTipsText("PLAYBACK ENDED", 2500);
  }
}

function clearStoredDemoStopTimer(state) {
  if (state.playbackStopTimer) {
    window.clearInterval(state.playbackStopTimer);
    state.playbackStopTimer = 0;
  }
}

function handlePlaybackDebugKeyDown(state, event) {
  const navigationDelta = getRecordNavigationDelta(event);
  if (navigationDelta !== 0) {
    if (!canNavigateStoredRecords(state)) {
      return;
    }
    stopKeyboardEvent(event);
    selectAdjacentRecord(state, navigationDelta);
    return;
  }

  const isSpace = event.code === "Space" || event.key === " ";
  const isPeriod = event.code === "Period" || event.key === ".";
  const isComma = event.code === "Comma" || event.key === ",";
  if (!isSpace && !isPeriod && !isComma) {
    return;
  }

  if (!isWrapperPlaybackActive(state)) {
    if (!isSpace || !canStartStoredPlaybackFromHotkey(state)) {
      return;
    }
    stopKeyboardEvent(event);
    void playOrToggleCurrentRecording(state, null, { startPaused: true });
    return;
  }

  stopKeyboardEvent(event);

  if (isSpace) {
    toggleStoredPlaybackPause(state);
    return;
  }
  if (isComma && state.playbackPhase === "paused") {
    stepStoredPlaybackSegment(state);
    return;
  }
  if (isPeriod && state.playbackPhase === "paused") {
    stepStoredPlaybackTraceStep(state);
  }
}

function getRecordNavigationDelta(event) {
  if (event.code !== "Tab" && event.key !== "Tab") {
    return 0;
  }
  return event.shiftKey ? -1 : 1;
}

function canNavigateStoredRecords(state) {
  return canNavigateRecordFacts({
    ...state,
    recordCount: Array.isArray(state.records) ? state.records.length : 0,
    autoDemoActive: isLegacyAutoDemoActive(),
  });
}

function isLegacyAutoDemoActive() {
  const playMode = Number(window.playMode);
  return playMode === Number(window.PLAY_AUTO) ||
    playMode === Number(window.PLAY_DEMO);
}

function canNavigateRecordFacts(facts) {
  return facts.recordCount >= 2 &&
    facts.backendStatus === "online" &&
    !facts.agentRunning && !facts.busyAction &&
    !facts.autoDemoActive && facts.playbackPhase === "inactive";
}

function canStartStoredPlaybackFromHotkey(state) {
  return Boolean(
    state.currentRecord &&
    !state.busyAction &&
    !state.agentRunning &&
    !isLegacyManualGameplayActive(),
  );
}

function isLegacyManualGameplayActive() {
  const playMode = Number(window.playMode);
  const gameState = Number(window.gameState);
  const isManualMode =
    playMode === Number(window.PLAY_CLASSIC) ||
    playMode === Number(window.PLAY_MODERN);
  const isActiveState = [window.GAME_RUNNING, window.GAME_PAUSE]
    .map(Number)
    .includes(gameState);
  return isManualMode && isActiveState;
}

function stopKeyboardEvent(event) {
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation?.();
}

function isWrapperPlaybackActive(state) {
  if (!state.playbackGameLevel) {
    return false;
  }
  const context = getCurrentContext();
  return Boolean(
    context &&
    formatGameLevel(context) === state.playbackGameLevel &&
    Number(window.playMode) === Number(window.PLAY_DEMO_ONCE),
  );
}

function toggleStoredPlaybackPause(state) {
  if (isPlaybackStepping(state)) {
    return;
  }
  if (state.playbackPhase === "paused") {
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
  if (
    typeof window.gamePause === "function" &&
    Number(window.gameState) !== Number(window.GAME_PAUSE)
  ) {
    window.gamePause();
  }
  if (typeof window.stopPlayTicker === "function") {
    window.stopPlayTicker();
  }
  if (typeof window.stopAllSpriteObj === "function") {
    window.stopAllSpriteObj();
  }
  state.playbackPhase = "paused";
  if (showTip && typeof window.showTipsText === "function") {
    window.showTipsText("PLAYBACK PAUSED", 0);
  }
  syncOverlayState(state);
  return true;
}

function resumeStoredPlayback(
  state,
  { showTip = true, phase = "playing" } = {},
) {
  if (!isWrapperPlaybackActive(state)) {
    clearPlaybackDebugState(state);
    return false;
  }
  if (
    typeof window.gameResume === "function" &&
    Number(window.gameState) === Number(window.GAME_PAUSE)
  ) {
    window.gameResume();
  }
  if (typeof window.startAllSpriteObj === "function") {
    window.startAllSpriteObj();
  }
  if (typeof window.startPlayTicker === "function") {
    window.startPlayTicker();
  }
  state.playbackPhase = phase;
  if (showTip && typeof window.showTipsText === "function") {
    window.showTipsText("", 1000);
  }
  syncOverlayState(state);
  return true;
}

function startPlaybackStep(state, phase, reachedTarget, timeoutMessage) {
  state.playbackStepStartedAt = performance.now();
  resumeStoredPlayback(state, { showTip: false, phase });
  syncOverlayState(state);

  const pollStep = (now) => {
    if (state.playbackPhase !== phase) return;
    if (!isWrapperPlaybackActive(state)) {
      clearPlaybackDebugState(state);
      syncOverlayState(state);
      return;
    }
    const reached = reachedTarget();
    const timedOut = now - state.playbackStepStartedAt >= PLAYBACK_STEP_TIMEOUT_MS;
    if (reached || timedOut) {
      state.playbackStepRaf = 0;
      pauseStoredPlayback(state, { showTip: !timedOut });
      if (timedOut && typeof window.showTipsText === "function") {
        window.showTipsText(timeoutMessage, 2500);
      }
      syncOverlayState(state);
      return;
    }
    state.playbackStepRaf = window.requestAnimationFrame(pollStep);
  };
  state.playbackStepRaf = window.requestAnimationFrame(pollStep);
}

function stepStoredPlaybackSegment(state) {
  if (state.playbackPhase !== "paused" || !isWrapperPlaybackActive(state)) return;
  const startRecordIdx = getFiniteNumber(window.demoRecordIdx);
  const startTick = getFiniteNumber(window.demoTickCount);
  startPlaybackStep(state, "step-action", () => {
    const currentRecordIdx = getFiniteNumber(window.demoRecordIdx);
    const currentTick = getFiniteNumber(window.demoTickCount);
    return (startRecordIdx !== null && currentRecordIdx !== null && currentRecordIdx > startRecordIdx)
      || (startRecordIdx === null && startTick !== null && currentTick !== null && currentTick > startTick);
  }, "DEMO STEP TIMEOUT");
}

function stepStoredPlaybackTraceStep(state) {
  if (state.playbackPhase !== "paused" || !isWrapperPlaybackActive(state)) return;
  const targetTick = getNextTraceStepTargetTick(state);
  if (targetTick === null) {
    if (typeof window.showTipsText === "function") {
      const message = state.selectedTraceId === state.currentRecord?.traceId && state.selectedTraceTicks.length
        ? "TRACE STEP END" : "NO TRACE STEP DATA";
      window.showTipsText(message, 2500);
    }
    return;
  }
  startPlaybackStep(state, "step-trace", () => {
    const currentTick = getFiniteNumber(window.demoTickCount);
    return currentTick !== null && currentTick >= targetTick;
  }, "TRACE STEP TIMEOUT");
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
  state.playbackPhase = "inactive";
  state.playbackStepRaf = 0;
  state.playbackStepStartedAt = 0;
}

function isPlaybackStepping(state) {
  return (
    state.playbackPhase === "step-action" ||
    state.playbackPhase === "step-trace"
  );
}

function isPlaybackVideoRecordingRequested(event) {
  return Boolean(event?.ctrlKey || event?.metaKey);
}

async function requestPlaybackVideoCapture() {
  if (!hasPlaybackVideoRecordingSupport()) {
    showPlaybackVideoTip("VIDEO RECORDING UNSUPPORTED");
    return null;
  }
  const mimeType = choosePlaybackVideoMimeType();
  if (!mimeType) {
    showPlaybackVideoTip("MP4 RECORDING UNSUPPORTED");
    return null;
  }

  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        displaySurface: "browser",
      },
      audio: true,
      preferCurrentTab: true,
      selfBrowserSurface: "include",
    });
    return {
      stream,
      mimeType,
    };
  } catch (_error) {
    showPlaybackVideoTip("VIDEO RECORDING CANCELLED");
    return null;
  }
}

function hasPlaybackVideoRecordingSupport() {
  return Boolean(
    navigator.mediaDevices?.getDisplayMedia &&
    typeof window.MediaRecorder === "function",
  );
}

function choosePlaybackVideoMimeType(mediaRecorder = window.MediaRecorder) {
  if (!mediaRecorder || typeof mediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  return (
    PLAYBACK_VIDEO_MIME_TYPES.find((mimeType) =>
      mediaRecorder.isTypeSupported(mimeType),
    ) ?? ""
  );
}

function startPlaybackVideoRecording(state, record, capture) {
  if (!capture?.stream) {
    return false;
  }

  stopPlaybackVideoRecording(state, { download: false });
  try {
    const options = capture.mimeType
      ? { mimeType: capture.mimeType }
      : undefined;
    const recorder = new window.MediaRecorder(capture.stream, options);
    state.videoRecorder = recorder;
    state.videoStream = capture.stream;
    state.videoChunks = [];
    state.videoRecording = true;
    state.videoStopping = false;
    state.videoDownloadOnStop = true;
    state.videoRecordId = String(record?.id || record?.traceId || "playback");
    state.videoMimeType = recorder.mimeType || capture.mimeType || "video/mp4";

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size > 0) {
        state.videoChunks.push(event.data);
      }
    });
    recorder.addEventListener("stop", () =>
      finalizePlaybackVideoRecording(state),
    );
    recorder.addEventListener("error", () =>
      showPlaybackVideoTip("VIDEO RECORDING ERROR"),
    );
    for (const track of capture.stream.getTracks()) {
      track.addEventListener?.("ended", () =>
        stopPlaybackVideoRecording(state),
      );
    }

    recorder.start();
    showPlaybackVideoTip("VIDEO RECORDING");
    syncOverlayState(state);
    return true;
  } catch (_error) {
    stopMediaStream(capture.stream);
    cleanupPlaybackVideoState(state);
    showPlaybackVideoTip("VIDEO RECORDING ERROR");
    return false;
  }
}

function stopPlaybackVideoRecording(state, { download = true } = {}) {
  const recorder = state.videoRecorder;
  if (
    !recorder &&
    !state.videoStream &&
    !state.videoChunks.length &&
    !state.videoRecording
  ) {
    return;
  }
  if (state.videoStopping) {
    return;
  }
  state.videoDownloadOnStop = download;
  if (recorder && recorder.state !== "inactive") {
    try {
      state.videoStopping = true;
      recorder.stop();
      return;
    } catch (_error) {
      // Fall through and clean up stale recorder state.
      state.videoStopping = false;
    }
  }
  finalizePlaybackVideoRecording(state);
}

function finalizePlaybackVideoRecording(state) {
  const chunks = state.videoChunks.slice();
  const shouldDownload = state.videoDownloadOnStop;
  const mimeType = state.videoMimeType || "video/mp4";
  const fileName = buildPlaybackVideoFileName(
    state.videoRecordId || "playback",
    new Date(),
    mimeType,
  );
  cleanupPlaybackVideoState(state);
  if (shouldDownload && chunks.length) {
    downloadPlaybackVideo(new Blob(chunks, { type: mimeType }), fileName);
    showPlaybackVideoTip("VIDEO SAVED");
  }
  syncOverlayState(state);
}

function cleanupPlaybackVideoState(state) {
  const stream = state.videoStream;
  state.videoRecorder = null;
  state.videoStream = null;
  state.videoChunks = [];
  state.videoRecording = false;
  state.videoStopping = false;
  state.videoDownloadOnStop = true;
  state.videoRecordId = "";
  state.videoMimeType = "";
  stopMediaStream(stream);
}

function stopMediaStream(stream) {
  if (!stream?.getTracks) {
    return;
  }
  for (const track of stream.getTracks()) {
    track.stop();
  }
}

function downloadPlaybackVideo(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function buildPlaybackVideoFileName(
  recordId,
  date = new Date(),
  mimeType = "video/mp4",
) {
  const safeId = getPlaybackVideoShortId(recordId);
  const timestamp = date
    .toISOString()
    .replace(/\.\d{3}Z$/, "")
    .replace(/:/g, "-");
  return `run-${safeId}-${timestamp}.${getPlaybackVideoExtension(mimeType)}`;
}

function getPlaybackVideoExtension(mimeType) {
  return String(mimeType).toLowerCase().includes("mp4") ? "mp4" : "webm";
}

function getPlaybackVideoShortId(value) {
  const rawValue = String(value || "playback");
  return (
    rawValue.split("-", 1)[0]
      .trim()
      .replace(/[^a-zA-Z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 32) || "playback"
  );
}

function showPlaybackVideoTip(message) {
  if (typeof window.showTipsText === "function") {
    window.showTipsText(message, 2500);
  }
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

function getCurrentGameLevel() {
  const context = getCurrentContext();
  return context ? formatGameLevel(context) : "";
}

function formatGameLevel(context) {
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

function beginUiAction(state, busyAction) {
  state.uiError = false;
  state.busyAction = busyAction;
  syncOverlayState(state);
}

function finishUiAction(state, { error = false } = {}) {
  state.uiError = error;
  state.busyAction = "";
  syncOverlayState(state);
}

function toggleGodModeFromRail(state) {
  if (typeof window.toggleGodMode !== "function") {
    finishUiAction(state, { error: true });
    return;
  }
  window.toggleGodMode();
  syncOverlayState(state);
}

async function toggleFullscreenFromRail(state) {
  if (!isFullscreenSupported()) {
    finishUiAction(state, { error: true });
    return;
  }

  beginUiAction(state, "fullscreen");
  try {
    if (isFullscreenActive()) {
      await exitFullscreen();
    } else {
      await enterFullscreen();
    }
    scheduleLegacyFullscreenRestart(state);
    finishUiAction(state);
  } catch (_error) {
    finishUiAction(state, { error: true });
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
  state.playbackGameLevel = "";
  stopPlaybackVideoRecording(state, { download: false });
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
    finishUiAction(state);
    scheduleRefresh(state);
  } catch (error) {
    console.error(
      "Failed to restart Lode Runner after fullscreen change",
      error,
    );
    finishUiAction(state, { error: true });
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
    root.webkitRequestFullscreen,
  );
}

function isFullscreenActive() {
  return Boolean(
    document.fullscreenElement || document.webkitFullscreenElement,
  );
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
  const playbackGameLevel = state.playbackGameLevel;
  if (!playbackGameLevel) {
    stopPlaybackVideoRecording(state, { download: false });
    clearPlaybackDebugState(state);
    return false;
  }

  const active = isWrapperPlaybackActive(state);

  if (!active) {
    state.playbackGameLevel = "";
    stopPlaybackVideoRecording(state);
    clearPlaybackDebugState(state);
    clearStoredDemoStopTimer(state);
  } else if (state.playbackPhase === "inactive") {
    state.playbackPhase = "playing";
  }
  return active;
}

function deriveOverlayViewModel(facts) {
  const busy = Boolean(facts.busyAction);
  const playbackPhase = facts.playbackPhase;
  const playbackActive = playbackPhase !== "inactive";
  const playbackPaused = playbackPhase === "paused";
  const canNavigateRecords = canNavigateRecordFacts(facts);
  const navigationBlockedTitle = facts.autoDemoActive
    ? "Stop auto-demo before selecting another run"
    : playbackActive
      ? "Stop playback before selecting another run"
      : null;
  const navigationButton = (direction) => ({
    disabled: !canNavigateRecords,
    title: navigationBlockedTitle || (canNavigateRecords
      ? `Refresh runs and select ${direction} stored run`
      : `No ${direction} stored run`),
  });
  const playTitle =
    playbackPhase === "step-action"
      ? "Stepping to next recorded action"
      : playbackPhase === "step-trace"
        ? "Stepping to next trace step"
        : playbackPaused
          ? "Resume demo playback"
          : playbackActive
            ? "Pause demo playback"
            : facts.hasRecord
              ? "Play stored recording (Ctrl-click to record video)"
              : "No stored recording for this level";
  const deleteTitle = !facts.hasRecord
    ? "No stored recording to delete"
    : playbackActive
        ? "Stop playback before deleting"
        : facts.backendStatus === "checking"
          ? "Checking server before deleting"
          : facts.backendStatus !== "online"
            ? "Server unavailable; cannot delete"
            : facts.recordPinned ? "Delete pinned recording (confirmation required)" : "Delete stored recording";

  return {
    attributes: {
      error: Boolean(facts.uiError),
      busyAction: facts.busyAction || "",
      backendStatus: facts.backendStatus,
      hasRecord: facts.hasRecord,
      playbackPhase,
      videoRecording: Boolean(facts.videoRecording),
      agentRunning: Boolean(facts.agentRunning),
      godMode: Boolean(facts.godModeActive),
      fullscreen: Boolean(facts.fullscreenActive),
    },
    buttons: {
      agent: facts.agentButtonState,
      play: {
        disabled: !facts.hasRecord || busy,
        icon: playbackPaused ? "▶" : playbackActive ? "⏸" : "▶",
        title: playTitle,
      },
      prev: navigationButton("previous"),
      next: navigationButton("next"),
      delete: {
        disabled:
          !facts.hasRecord ||
          busy ||
          playbackActive ||
          facts.backendStatus !== "online",
        title: deleteTitle,
      },
      god: {
        disabled: !facts.godModeSupported || busy,
        title: facts.godModeSupported
          ? facts.godModeActive
            ? "God mode is on"
            : "God mode is off"
          : "God mode unavailable",
      },
      fullscreen: {
        disabled: !facts.fullscreenSupported || busy,
        title: facts.fullscreenSupported
          ? facts.fullscreenActive
            ? "Exit full screen"
            : "Enter full screen"
          : "Full screen unavailable",
      },
    },
  };
}

function syncOverlayState(state) {
  if (!state.els.overlay) {
    return;
  }

  syncPlaybackState(state);
  const facts = collectOverlayFacts(state);
  const view = deriveOverlayViewModel(facts);
  applyOverlayView(state.els, view);
  syncDebugBar(state);
  if (facts.playbackPhase !== "inactive") {
    startDebugBarRefresh(state);
  } else {
    stopDebugBarRefresh(state);
  }
}

function collectOverlayFacts(state) {
  return {
    uiError: state.uiError,
    busyAction: state.busyAction,
    backendStatus: state.backendStatus,
    hasRecord: Boolean(state.currentRecord),
    recordPinned: state.currentRecord?.pinned === true,
    recordCount: state.records.length,
    autoDemoActive: isLegacyAutoDemoActive(),
    playbackPhase: state.playbackPhase,
    videoRecording: state.videoRecording,
    agentRunning: state.agentRunning,
    agentButtonState: agentController.getButtonState(state),
    godModeActive: Number(window.godMode) === 1,
    godModeSupported: typeof window.toggleGodMode === "function",
    fullscreenActive: isFullscreenActive(),
    fullscreenSupported: isFullscreenSupported(),
  };
}

function applyOverlayView(elements, view) {
  const overlay = elements.overlay;
  overlay.dataset.error = view.attributes.error ? "true" : "false";
  overlay.dataset.backendStatus = view.attributes.backendStatus;
  overlay.dataset.hasRecord = view.attributes.hasRecord ? "true" : "false";
  overlay.dataset.playbackPhase = view.attributes.playbackPhase;
  overlay.dataset.videoRecording = view.attributes.videoRecording
    ? "true"
    : "false";
  overlay.dataset.agentRunning = view.attributes.agentRunning
    ? "true"
    : "false";
  overlay.dataset.godMode = view.attributes.godMode ? "true" : "false";
  overlay.dataset.fullscreen = view.attributes.fullscreen ? "true" : "false";

  if (view.attributes.busyAction) {
    overlay.dataset.busy = view.attributes.busyAction;
  } else {
    delete overlay.dataset.busy;
  }

  for (const [name, buttonState] of Object.entries(view.buttons)) {
    const button = elements[name];
    button.disabled = buttonState.disabled;
    button.title = buttonState.title;
    button.setAttribute("aria-label", buttonState.title);
    if (buttonState.icon) {
      button.dataset.icon = buttonState.icon;
    }
  }
}

function syncDebugBar(state) {
  const debugBar = state.els.debugBar;
  if (!debugBar) {
    return;
  }
  if (
    !state.currentRecord ||
    state.agentRunning ||
    state.busyAction === "agent"
  ) {
    debugBar.hidden = true;
    debugBar.textContent = "";
    return;
  }

  debugBar.hidden = false;
  debugBar.textContent = formatDebugOverlay(state);
}

function formatDebugOverlay(state) {
  const record = state.currentRecord;
  return (
    `${state.selectedRecordIndex + 1}/${Math.max(state.records.length, 1)}: ` +
    [
      [
        formatRecordTraceId(record),
        record.pinned === true ? "📌" : "",
        formatRecordResult(record.result),
      ].filter(Boolean).join(" "),
      formatSavedAt(record.savedAt),
      formatDemoTime(record.demo?.time),
      formatPlaybackProgress(state),
    ].join(" | ")
  );
}

function formatRecordResult(result) {
  if (result === "success") {
    return "✅";
  }
  if (result === "failure") {
    return "❌";
  }
  return "❔";
}

function formatRecordTraceId(record) {
  if (!record?.traceId && record?.source === "user") {
    return "user";
  }
  return shortId(record?.traceId);
}

function shortId(value) {
  if (typeof value !== "string" || !value) {
    return "none";
  }
  return value.split("-", 1)[0].slice(0, 8);
}

function formatSavedAt(value) {
  if (typeof value !== "string" || !value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hours}:${minutes}`;
}

function formatDemoTime(value) {
  const time = Number(value);
  if (!Number.isFinite(time) || time <= 0) {
    return "-";
  }
  const rawSeconds = time / LEGACY_TICKS_PER_SECOND;
  const lowerSeconds = Math.floor(rawSeconds);
  const totalSeconds =
    rawSeconds - lowerSeconds === 0.5
      ? lowerSeconds + (lowerSeconds % 2)
      : Math.round(rawSeconds);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
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

function traceStepPosition(state, currentTick) {
  if (state.selectedTraceId !== state.currentRecord?.traceId || !state.selectedTraceTicks.length) {
    return null;
  }
  if (currentTick === null) return 0;
  let count = 0;
  for (const tick of state.selectedTraceTicks) {
    if (tick > currentTick) break;
    count += 1;
  }
  return count;
}

function getTracePlaybackProgress(state, total) {
  const progress = traceStepPosition(state, getFiniteNumber(window.demoTickCount));
  return progress === null ? "-" : Math.min(Math.max(progress, 0), total);
}

function getNextTraceStepTargetTick(state) {
  const currentTick = getFiniteNumber(window.demoTickCount);
  if (currentTick === null) return null;
  const progress = traceStepPosition(state, currentTick);
  return progress === null ? null : state.selectedTraceTicks[progress] ?? null;
}

function getDemoRecordProgress(total) {
  const currentIndex = getFiniteNumber(window.demoRecordIdx);
  if (currentIndex === null) {
    return 0;
  }
  return Math.min(Math.max(Math.floor(currentIndex), 0), total);
}

function getDemoStepCount(demo) {
  return Math.floor(arrayLength(demo?.action) / 2);
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
    const detail = typeof body?.detail === "string" ? body.detail : null;
    const error = new Error(detail || body?.error || response.statusText);
    error.status = response.status;
    throw error;
  }
  return body;
}

export const _test = {
  startPlaybackStep,
  stepStoredPlaybackSegment,
  stepStoredPlaybackTraceStep,
  clearRecordSelection,
  refreshStatus,
  buildRecordingDeleteConfirmation,
  buildPlaybackVideoFileName,
  canNavigateStoredRecords,
  canStartStoredPlaybackFromHotkey,
  choosePlaybackVideoMimeType,
  copyArray,
  deriveOverlayViewModel,
  extractTraceStepTicks,
  formatDebugOverlay,
  formatGameLevel,
  formatDemoTime,
  formatPlaybackProgress,
  formatRecordResult,
  formatRecordTraceId,
  getRecordNavigationDelta,
  getNextTraceStepTargetTick,
  getTracePlaybackProgress,
  getTraceStepTick,
  ensureEvaluationGodMode,
  normalizeDemo,
  shouldSaveUserCompletion,
  shortId,
};
