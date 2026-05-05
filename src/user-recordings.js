const INSTALL_KEY = "__lodeRunnerUserRecordings";
const API_BASE = "/api/recordings";
const AGENT_API = "/api/agent/next-action";
const OVERLAY_ID = "user-recording-overlay";
const AGENT_PLAY_DATA = 1;
const AGENT_LEVEL = 1;
const AGENT_MAX_ITERATIONS = 240;
const AGENT_HISTORY_LIMIT = 24;

export function installUserRecordings() {
  if (window[INSTALL_KEY]?.installed) {
    return window[INSTALL_KEY];
  }

  const state = {
    installed: true,
    currentKey: "",
    currentRecord: null,
    currentState: "idle",
    busyAction: "",
    agentRunning: false,
    agentAbort: null,
    agentPlanner: null,
    saveTimer: 0,
    refreshTimer: 0,
    els: {},
  };
  window[INSTALL_KEY] = state;

  createOverlay(state);
  patchRecordingSave(state);
  void refreshStatus(state);
  state.refreshTimer = window.setInterval(() => void refreshWhenLevelChanges(state), 1200);

  return state;
}

function patchRecordingSave(state) {
  const original = window.updatePlayerDemoData;
  if (typeof original !== "function" || original.__userRecordingPatched) {
    return;
  }

  function patchedUpdatePlayerDemoData(playData, demoDataInfo) {
    const result = original.apply(this, arguments);
    void saveCompletedRecording(state, playData, demoDataInfo);
    return result;
  }

  patchedUpdatePlayerDemoData.__userRecordingPatched = true;
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
  overlay.setAttribute("aria-label", "User recordings");
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
  `;
  document.body.appendChild(overlay);

  state.els.overlay = overlay;
  state.els.play = overlay.querySelector("[data-action='play']");
  state.els.refresh = overlay.querySelector("[data-action='refresh']");
  state.els.delete = overlay.querySelector("[data-action='delete']");
  state.els.agent = overlay.querySelector("[data-action='agent']");

  state.els.play.addEventListener("click", () => void playCurrentRecording(state));
  state.els.refresh.addEventListener("click", () => void refreshStatus(state, true));
  state.els.delete.addEventListener("click", () => void deleteCurrentRecording(state));
  state.els.agent.addEventListener("click", () => void toggleAgent(state));

  syncOverlayState(state);
}

async function refreshWhenLevelChanges(state) {
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
    startStoredDemo(demo, context);
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

async function toggleAgent(state) {
  if (state.agentRunning) {
    state.agentAbort?.abort();
    return;
  }
  await runAgent(state);
}

async function runAgent(state) {
  const hooks = window.lodeRunnerAgentHooks;
  if (!hooks?.isSupportedContext?.(AGENT_PLAY_DATA, AGENT_LEVEL)) {
    setUiState(state, "error");
    return;
  }

  state.agentRunning = true;
  state.agentAbort = new AbortController();
  state.agentPlanner = null;
  setUiState(state, state.currentRecord ? "available" : "missing", "agent");

  const history = [];
  let failureReason = "agent stopped";

  try {
    hooks.startLevel(AGENT_PLAY_DATA, AGENT_LEVEL);

    for (let iteration = 0; iteration < AGENT_MAX_ITERATIONS; iteration += 1) {
      if (state.agentAbort.signal.aborted) {
        failureReason = "agent cancelled";
        break;
      }

      const before = hooks.snapshot();
      const terminal = getTerminalResult(hooks);
      if (terminal) {
        await finishAgentRun(state, hooks, terminal.demo, terminal.result, terminal.reason);
        return;
      }

      const response = await apiFetch(AGENT_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playData: AGENT_PLAY_DATA,
          level: AGENT_LEVEL,
          snapshot: before,
          history,
        }),
        signal: state.agentAbort.signal,
      });
      const action = normalizeAgentAction(response.action);
      state.agentPlanner = response.planner ?? null;
      history.push({
        keyCode: action.keyCode,
        ticks: action.ticks,
        reason: action.reason,
        tick: before.tick,
        state: before.gameStateName,
      });
      while (history.length > AGENT_HISTORY_LIMIT) {
        history.shift();
      }

      hooks.step(action.keyCode, action.ticks);
      const afterTerminal = getTerminalResult(hooks);
      if (afterTerminal) {
        await finishAgentRun(
          state,
          hooks,
          afterTerminal.demo,
          afterTerminal.result,
          afterTerminal.reason,
        );
        return;
      }
    }
    failureReason = failureReason === "agent stopped" ? "agent max iterations reached" : failureReason;
  } catch (error) {
    failureReason = getErrorMessage(error);
  }

  try {
    const failedDemo = hooks.dumpFailure(failureReason);
    await saveAgentResult(state, failedDemo, "failure", failureReason);
  } catch (_error) {
    setUiState(state, "error");
  } finally {
    hooks.stop({ resumeTicker: false });
    state.agentRunning = false;
    state.agentAbort = null;
    syncOverlayState(state);
  }
}

async function finishAgentRun(state, hooks, demo, result, reason) {
  try {
    await saveAgentResult(state, demo, result, reason);
  } finally {
    hooks.stop({ resumeTicker: false });
    state.agentRunning = false;
    state.agentAbort = null;
    syncOverlayState(state);
  }
}

function normalizeAgentAction(action) {
  if (!action || typeof action !== "object") {
    throw new Error("agent returned no action");
  }
  const keyCode = Number(action.keyCode);
  const ticks = Number(action.ticks);
  if (!Number.isInteger(keyCode) || !Number.isInteger(ticks)) {
    throw new Error("agent returned invalid action");
  }
  return {
    keyCode,
    ticks: Math.max(1, Math.min(20, ticks)),
    reason: String(action.reason ?? ""),
  };
}

function getTerminalResult(hooks) {
  const demo = hooks.getRecordedDemo?.();
  if (demo?.level === AGENT_LEVEL && Number(demo.time) > 0) {
    if (Number(demo.state) === 1) {
      return { demo, result: "success", reason: "finished" };
    }
    if (Number(demo.state) === 0) {
      return { demo, result: "failure", reason: "runner dead" };
    }
  }
  const snapshot = hooks.snapshot?.();
  if (snapshot?.gameStateName === "runner_dead") {
    return { demo: hooks.dumpFailure?.("runner dead"), result: "failure", reason: "runner dead" };
  }
  return null;
}

async function saveAgentResult(state, demoData, result, reason) {
  const demo = normalizeDemo(demoData, AGENT_PLAY_DATA, AGENT_LEVEL);
  demo.state = result === "success" ? 1 : 0;
  const solver = {
    provider: state.agentPlanner?.provider ?? "openai",
    model: state.agentPlanner?.model ?? null,
    generatedAt: state.agentPlanner?.generatedAt ?? new Date().toISOString(),
    responseId: state.agentPlanner?.responseId ?? null,
    failureReason: result === "failure" ? reason : null,
  };
  const record = await apiFetch(`${API_BASE}/${AGENT_PLAY_DATA}/${AGENT_LEVEL}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      demo,
      source: "agent",
      result,
      solver,
    }),
  });
  state.currentRecord = record;
  state.currentKey = getContextKey({ playData: AGENT_PLAY_DATA, level: AGENT_LEVEL });
  setUiState(state, result === "success" ? "available" : "error");
  scheduleRefresh(state);
}

function startStoredDemo(demo, context) {
  if (typeof window.startGame !== "function") {
    throw new Error("legacy startGame is unavailable");
  }

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

function syncOverlayState(state) {
  const overlay = state.els.overlay;
  if (!overlay) {
    return;
  }

  const hasRecord = Boolean(state.currentRecord);
  overlay.dataset.state = state.currentState;
  overlay.dataset.hasRecord = hasRecord ? "true" : "false";

  if (state.busyAction) {
    overlay.dataset.busy = state.busyAction;
  } else {
    delete overlay.dataset.busy;
  }

  state.els.play.disabled = !hasRecord || Boolean(state.busyAction);
  state.els.delete.disabled = !hasRecord || Boolean(state.busyAction);
  state.els.refresh.disabled = Boolean(state.busyAction);
  state.els.agent.disabled =
    (!isAgentSupported() && !state.agentRunning) ||
    (Boolean(state.busyAction) && state.busyAction !== "agent");

  state.els.play.title = hasRecord ? "Play stored recording" : "No stored recording for this level";
  state.els.delete.title = hasRecord ? "Delete stored recording" : "No stored recording to delete";
  state.els.refresh.title = getRefreshTitle(state.currentState);
  state.els.agent.title = state.agentRunning
    ? "Cancel AI agent"
    : "Solve Classic level 1 with AI agent";
}

function isAgentSupported() {
  const context = getCurrentContext();
  return Boolean(
    context &&
      context.playData === AGENT_PLAY_DATA &&
      context.level === AGENT_LEVEL &&
      window.lodeRunnerAgentHooks?.isSupportedContext?.(context.playData, context.level),
  );
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

function getErrorMessage(error) {
  if (error?.name === "AbortError") {
    return "agent cancelled";
  }
  return error instanceof Error ? error.message : String(error);
}
