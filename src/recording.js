import { createAgentController } from "./agent.js";

const INSTALL_KEY = "__lodeRunnerRecording";
const API_BASE = "/api/recordings";
const OVERLAY_ID = "recording-overlay";
const FULLSCREEN_RESTART_DELAY_MS = 180;
const FAILED_DEMO_STOP_POLL_MS = 100;

const agentController = createAgentController({
  apiFetch,
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
    currentState: "idle",
    busyAction: "",
    playbackKey: "",
    saveTimer: 0,
    refreshTimer: 0,
    fullscreenRestartTimer: 0,
    playbackStopTimer: 0,
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
      data-action="refresh"
      data-icon="↻"
      aria-label="Refresh recording status"
      title="Refresh recording status"
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

  state.els.overlay = overlay;
  state.els.play = overlay.querySelector("[data-action='play']");
  state.els.refresh = overlay.querySelector("[data-action='refresh']");
  state.els.delete = overlay.querySelector("[data-action='delete']");
  state.els.agent = overlay.querySelector("[data-action='agent']");
  state.els.god = overlay.querySelector("[data-action='god']");
  state.els.fullscreen = overlay.querySelector("[data-action='fullscreen']");

  state.els.play.addEventListener("click", () => void playCurrentRecording(state));
  state.els.refresh.addEventListener("click", () => void refreshStatus(state, true));
  state.els.delete.addEventListener("click", () => void deleteCurrentRecording(state));
  state.els.god.addEventListener("click", () => toggleGodModeFromRail(state));
  state.els.fullscreen.addEventListener("click", () => void toggleFullscreenFromRail(state));
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
    setUiState(state, "idle");
  }
}

function scheduleRefresh(state) {
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(() => void refreshStatus(state), 400);
}

async function refreshStatus(state, force = false) {
  const context = getCurrentContext();
  if (!context) {
    state.currentKey = "";
    state.currentRecord = null;
    setUiState(state, "idle");
    return;
  }

  const key = getContextKey(context);
  if (!force && key === state.currentKey && state.currentState !== "idle" && !state.busyAction) {
    return;
  }
  state.currentKey = key;

  setUiState(state, state.currentRecord ? "available" : "idle", "refresh");
  try {
    const record = await apiFetch(`${API_BASE}/${context.playData}/${context.level}`);
    state.currentRecord = record;
    setUiState(state, "available");
  } catch (error) {
    if (error.status === 404) {
      state.currentRecord = null;
      setUiState(state, "missing");
      return;
    }
    state.currentRecord = null;
    setUiState(state, "error");
  }
}

async function playCurrentRecording(state) {
  const context = getCurrentContext();
  if (!context) {
    setUiState(state, "idle");
    return;
  }

  setUiState(state, state.currentRecord ? "available" : "missing", "play");
  try {
    const record =
      state.currentRecord ??
      (await apiFetch(`${API_BASE}/${context.playData}/${context.level}`));
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
    setUiState(state, "idle");
    return;
  }

  setUiState(state, state.currentRecord ? "available" : "missing", "delete");
  try {
    await apiFetch(`${API_BASE}/${context.playData}/${context.level}`, { method: "DELETE" });
    state.currentRecord = null;
    setUiState(state, "missing");
  } catch (_error) {
    setUiState(state, "error");
  }
}

function startStoredDemo(state, demo, context) {
  if (typeof window.startGame !== "function") {
    throw new Error("legacy startGame is unavailable");
  }

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

  if (typeof window.anyKeyStopDemo === "function") {
    window.anyKeyStopDemo();
  }
  window.startGame(1);
  if (typeof window.showTipsText === "function") {
    window.setTimeout(() => window.showTipsText("HIT ANY KEY TO STOP DEMO", 3500), 50);
  }
  scheduleFailedDemoStop(state, demo, context);
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
    if (Number(window.demoTickCount) >= demoTime) {
      stopFailedDemoPlayback(state);
    }
  }, FAILED_DEMO_STOP_POLL_MS);
}

function stopFailedDemoPlayback(state) {
  clearStoredDemoStopTimer(state);
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
    return false;
  }

  const context = getCurrentContext();
  const matchesContext = Boolean(context && getContextKey(context) === playbackKey);
  const isDemoOnce = Number(window.playMode) === Number(window.PLAY_DEMO_ONCE);
  const active = matchesContext && isDemoOnce;

  if (!active) {
    state.playbackKey = "";
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
  const godModeActive = Number(window.godMode) === 1;
  const godModeSupported = typeof window.toggleGodMode === "function";
  const fullscreenActive = isFullscreenActive();
  const fullscreenSupported = isFullscreenSupported();
  overlay.dataset.state = state.currentState;
  overlay.dataset.hasRecord = hasRecord ? "true" : "false";
  overlay.dataset.playback = playbackActive ? "true" : "false";
  overlay.dataset.godMode = godModeActive ? "true" : "false";
  overlay.dataset.fullscreen = fullscreenActive ? "true" : "false";

  if (state.busyAction) {
    overlay.dataset.busy = state.busyAction;
  } else {
    delete overlay.dataset.busy;
  }

  state.els.play.disabled = !hasRecord || Boolean(state.busyAction);
  state.els.delete.disabled = !hasRecord || Boolean(state.busyAction);
  state.els.refresh.disabled = Boolean(state.busyAction);
  const agentButtonState = agentController.getButtonState(state);
  state.els.agent.disabled = agentButtonState.disabled;
  state.els.god.disabled = !godModeSupported || Boolean(state.busyAction);
  state.els.fullscreen.disabled = !fullscreenSupported || Boolean(state.busyAction);

  state.els.play.title = playbackActive
    ? "Stored recording is playing"
    : hasRecord
      ? "Play stored recording"
      : "No stored recording for this level";
  state.els.delete.title = hasRecord ? "Delete stored recording" : "No stored recording to delete";
  state.els.refresh.title = getRefreshTitle(state.currentState);
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
}

function getRefreshTitle(uiState) {
  switch (uiState) {
    case "available":
      return "Stored recording available";
    case "missing":
      return "No stored recording for this level";
    case "error":
      return "Recording API unavailable";
    default:
      return "Refresh recording status";
  }
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
