const AGENT_API = "/api/agent/next-action";
const AGENT_PLAY_DATA = 1;
const AGENT_LEVEL = 1;
const AGENT_MAX_ITERATIONS = 240;
const AGENT_HISTORY_LIMIT = 24;

export function createAgentController(deps) {
  return {
    initState(state) {
      state.agentRunning = false;
      state.agentAbort = null;
      state.agentPlanner = null;
      state.agentTraceId = null;
      state.agentRunId = null;
    },

    bindButton(state, button) {
      button.addEventListener("click", () => void toggleAgent(state, deps));
    },

    getButtonState(state) {
      const supported = isAgentSupported(deps.getCurrentContext);
      return {
        disabled:
          (!supported && !state.agentRunning) ||
          (Boolean(state.busyAction) && state.busyAction !== "agent"),
        title: state.agentRunning ? "Cancel AI agent" : "Solve Classic level 1 with AI agent",
      };
    },
  };
}

async function toggleAgent(state, deps) {
  if (state.agentRunning) {
    state.agentAbort?.abort();
    return;
  }
  await runAgent(state, deps);
}

async function runAgent(state, deps) {
  const hooks = window.lodeRunnerAgentHooks;
  if (!hooks?.isSupportedContext?.(AGENT_PLAY_DATA, AGENT_LEVEL)) {
    deps.setUiState(state, "error");
    return;
  }

  state.agentRunning = true;
  state.agentAbort = new AbortController();
  state.agentPlanner = null;
  state.agentTraceId = null;
  state.agentRunId = createRunId();
  deps.setUiState(state, state.currentRecord ? "available" : "missing", "agent");

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
        await finishAgentRun(state, deps, hooks, terminal.demo, terminal.result, terminal.reason);
        return;
      }

      const response = await deps.apiFetch(AGENT_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playData: AGENT_PLAY_DATA,
          level: AGENT_LEVEL,
          snapshot: before,
          history,
          runId: state.agentRunId,
          ...getAgentRequestOptions(),
        }),
        signal: state.agentAbort.signal,
      });
      const action = normalizeAgentAction(response.action);
      state.agentPlanner = response.planner ?? null;
      state.agentTraceId = response.traceId ?? state.agentRunId;

      hooks.step(action.keyCode, action.ticks);
      const after = hooks.snapshot();
      history.push({
        keyCode: action.keyCode,
        ticks: action.ticks,
        reason: action.reason,
        tick: before.tick,
        state: before.gameStateName,
        afterTick: after?.tick,
        afterState: after?.gameStateName,
        before: summarizeHistorySnapshot(before),
        after: summarizeHistorySnapshot(after),
      });
      while (history.length > AGENT_HISTORY_LIMIT) {
        history.shift();
      }

      const afterTerminal = getTerminalResult(hooks);
      if (afterTerminal) {
        await finishAgentRun(
          state,
          deps,
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
    await saveAgentResult(state, deps, failedDemo, "failure", failureReason);
  } catch (_error) {
    deps.setUiState(state, "error");
  } finally {
    hooks.stop({ resumeTicker: false });
    state.agentRunning = false;
    state.agentAbort = null;
    state.agentRunId = null;
    deps.syncOverlayState(state);
  }
}

async function finishAgentRun(state, deps, hooks, demo, result, reason) {
  try {
    await saveAgentResult(state, deps, demo, result, reason);
  } finally {
    hooks.stop({ resumeTicker: false });
    state.agentRunning = false;
    state.agentAbort = null;
    state.agentRunId = null;
    deps.syncOverlayState(state);
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

function summarizeHistorySnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") {
    return {};
  }
  const runner = snapshot.runner ?? {};
  const gold = snapshot.gold ?? {};
  return {
    tick: snapshot.tick,
    state: snapshot.gameStateName,
    goldCount: gold.remainingCount ?? snapshot.goldCount,
    goldComplete: gold.complete ?? snapshot.goldComplete,
    runner: {
      x: runner.x,
      y: runner.y,
      xOffset: runner.xOffset,
      yOffset: runner.yOffset,
      action: runner.actionName,
    },
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

async function saveAgentResult(state, deps, demoData, result, reason) {
  const demo = deps.normalizeDemo(demoData, AGENT_PLAY_DATA, AGENT_LEVEL);
  demo.state = result === "success" ? 1 : 0;
  const solver = {
    provider: state.agentPlanner?.provider ?? "openai",
    model: state.agentPlanner?.model ?? null,
    generatedAt: state.agentPlanner?.generatedAt ?? new Date().toISOString(),
    responseId: state.agentPlanner?.responseId ?? null,
    traceId: state.agentTraceId ?? null,
    failureReason: result === "failure" ? reason : null,
  };
  const record = await deps.apiFetch(`${deps.recordingApiBase}/${AGENT_PLAY_DATA}/${AGENT_LEVEL}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      demo,
      source: "agent",
      result,
      solver,
      traceRef: state.agentTraceId ?? null,
    }),
  });
  state.currentRecord = record;
  state.currentKey = deps.getContextKey({ playData: AGENT_PLAY_DATA, level: AGENT_LEVEL });
  deps.setUiState(state, result === "success" ? "available" : "error");
  deps.scheduleRefresh(state);
}

function isAgentSupported(getCurrentContext) {
  const context = getCurrentContext();
  return Boolean(
    context &&
      context.playData === AGENT_PLAY_DATA &&
      context.level === AGENT_LEVEL &&
      window.lodeRunnerAgentHooks?.isSupportedContext?.(context.playData, context.level),
  );
}

function getErrorMessage(error) {
  if (error?.name === "AbortError") {
    return "agent cancelled";
  }
  return error instanceof Error ? error.message : String(error);
}

function getAgentRequestOptions() {
  const options = window.__lodeRunnerAgentOptions;
  if (!options || typeof options !== "object") {
    return {};
  }

  const requestOptions = {};
  if (typeof options.model === "string" && options.model.trim()) {
    requestOptions.model = options.model.trim();
  }
  return requestOptions;
}

function createRunId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `trace-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}
