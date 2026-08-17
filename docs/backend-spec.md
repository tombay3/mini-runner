# Backend Spec

## Summary
`app.py` provides local Flask APIs for recording persistence, agent planning, trace retrieval, model configuration, logging, and raw model I/O debugging.

Current backend layers:

- `candidates`: extracts normalized facts, then generates and scores candidate actions.
- `reasoning_tools`: deterministic movement, guard, dig, and route helpers.
- `loop_tools`: deterministic stationary, horizontal, and vertical cycle detection and suppression.
- `prompt`: formats the current state summary and eligible candidate list, including compact loop status.
- `service`: orchestrates one model call, generic candidate validation, and trace assembly.

Mutable local stores:

- `__data1/recordings.json` replayable user and agent demos.  Agent recordings reference traces with `traceId`.
- `__data1/agent-traces.json` agent traces of latest runs.
- `__data1/agent-debug.log` when debug logging is enabled.

## Recording API
- `GET /api/recordings`: return the full recording store.
- `GET /api/recordings/<playData>/<level>`: return the newest matching record or `404`.
- `GET /api/recordings/<playData>/<level>/records`: return all retained matching records newest-first, each with compact linked trace metadata when available.
- `PUT /api/recordings/<playData>/<level>`: save a new unpinned record and retain all pinned
  records plus the 10 newest unpinned records. Updating the same id preserves its stored pin.
- `DELETE /api/recordings/<playData>/<level>`: delete the newest matching record and linked trace when present.
- `DELETE /api/recordings/<playData>/<level>?recordId=<recordId>`: delete the selected record and linked trace when present.
- `DELETE /api/recordings/<playData>/<level>?traceId=<traceId>`: delete the agent record whose id matches the trace id and delete that trace.

Deleting a pinned recording returns `409` and does not delete its linked trace.

Recording store shape:

```json
{
  "version": 1,
  "updatedAt": "2026-05-28T00:00:00.000Z",
  "records": {
    "<recordId>": {
      "id": "<recordId>",
      "playData": 1,
      "level": 1,
      "savedAt": "2026-05-28T00:00:00.000Z",
      "source": "agent",
      "result": "failure",
      "pinned": false,
      "traceId": "<traceId>",
      "solver": {},
      "demo": {}
    }
  }
}
```

Agent recordings use `traceId` as `id`. User recordings use `user:<timestamp>`. To pin or
unpin a completed run, edit only its `pinned` field in `recordings.json` while no agent run is
active. Missing fields are equivalent to `false`. A pinned agent recording also protects its
linked trace from pruning; pin state is never copied into `agent-traces.json`, and a missing
linked trace is not recreated.
The browser normally creates UUID trace IDs. On HTTP contexts where
`crypto.randomUUID()` is unavailable, it constructs the same UUID format with
`crypto.getRandomValues()`. If neither Web Crypto method is available, the final fallback
is `<8hex>-<timestamp>`. Short IDs are always the first eight-character segment.

## Agent Planning API
`POST /api/agent/next-action` appends one trace step and returns one legacy action:

```json
{
  "action": { "keyCode": 39, "ticks": 8, "reason": "..." },
  "planner": {
    "modelProfile": "openai",
    "provider": "openai",
    "model": "openai:gpt-4.1-mini",
    "mode": "candidate-selection"
  },
  "traceId": "...",
  "stepCount": 2,
  "candidateId": "..."
}
```

## Backend Agent Flow
- The endpoint supports Classic `playData=1`, `level=1`. Its flow is:
  `snapshot + history -> candidate analysis -> LLM candidate choice -> action validation -> response`.
- Candidate generation and loop filtering happen deterministically in Python before the LLM call.
- `agent-traces.json` records compact state summaries, eligible candidates, the selected candidate,
  generic validation, loop-filter evidence, and model metadata.

## Trace API And Store
- `GET /api/agent/traces/<trace_id>`: return one retained trace run.
- `GET /api/agent/runs/<playData>/<level>`: return latest trace metadata and saved recording for that context.

The trace store has this shape:

```json
{
  "version": 3,
  "updatedAt": "2026-05-28T00:00:00.000Z",
  "runs": {
    "<traceId>": {
      "id": "<traceId>",
      "createdAt": "...",
      "updatedAt": "...",
      "playData": 1,
      "level": 1,
      "model": {},
      "config": {},
      "stepCount": 0,
      "latestAction": {},
      "outcome": {
        "result": "failure",
        "reason": "runner dead",
        "finalState": {}
      },
      "steps": []
    }
  }
}
```

When an agent recording is saved, the linked trace run is finalized with `outcome`.
`outcome.finalState` is a compact post-action terminal snapshot containing the runner,
all guards (including offsets, motion, and carried gold), gold state, tick, game state, and
god-mode state. This preserves the evidence needed to classify a fatal or successful final
action without storing the full terrain grid again.

The browser-generated run ID is also used as the trace ID when planning fails before the
first model response. In that case the backend creates a zero-step trace containing model
metadata and the terminal failure outcome, so provider/configuration failures are retained
instead of producing an unlinked recording error.

`step.state` is a prompt-parity summary rather than a full snapshot. It contains:

- `gameState`, `tick`, and `godMode`;
- compact `runner` and `gold` objects;
- `primaryProgressTarget` and compact `guardRisk` with the selected pressure guard and nearby guards;
- movement booleans;
- dynamic support under adjacent horizontal tiles, including whether movement would enter an open dug hole;
- open-hole coordinates and legacy refill frame/time exposed by the agent hook for timed floor-wait candidates;
- ladder detail and a compact route-access summary, including guard-blocked drop entry.

Each step also stores `candidates`, `selectedCandidateId`, `selectedCandidateKind`,
`validation`, `action`, and `loopMonitor`. Full terrain, guard lists,
movement details, dig analysis, and raw model messages are not stored in `step.state`.
`guardRisk.pressureGuard` is the highest-priority mobile threat after guard-state adjustment
(`in_hole` is low immediate pressure). All compact guards use the same `relativeX`, `relativeY`,
`motion`, and `closing` fields.

`loopMonitor.active` identifies confirmed loops. `type` is one of `stationary_repeat`,
`horizontal_cycle`, or `vertical_cycle`; `evidence` records recent positions, candidates,
key codes, and progress facts; and `suppressedCandidates` records choices removed before the
model call. Patterns below the confirmed-loop threshold are not stored or shown. Confirmed loop
actions are removed from the eligible candidate list.

Dashboard loading, derived after-state, event markers, and UI behavior are documented in
[Trace dashboard](./trace-dashboard.md).

The trace store keeps up to 10 newest runs. Run-level `model` records the resolved
model/profile/provider, and run-level `config` records the planning controls used for the
run. Model and config are not duplicated on every step.


## Model Profiles
The backend uses `aisuite` for provider/model abstraction. Resolution order is:

1. explicit request `model`;
2. request `modelProfile` (the browser derives this from `?profile=...`, runtime options,
   or public config);
3. `public/agent-config.json` `agent.modelProfile`;
4. `AGENT_MODEL_PROFILE`;
5. `AGENT_DEFAULT_MODEL`, which requires `provider:model` format.

Supported profiles:

- `openai`: `OPENAI_MODEL`, `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`.
- `minimax`: `MINIMAX_MODEL`, `MINIMAX_API_KEY`, optional `MINIMAX_BASE_URL` or `MINIMAX_API_BASE`.
- `gemini`: `GEMINI_MODEL`, `GEMINI_API_KEY`, optional `GEMINI_API_BASE`.

Dotenv files are reconciled before each backend planning request:

1. `~/.env`
2. `<repo>/.env`
3. `~/.env.local`
4. `<repo>/.env.local`

Examples:

```sh
AGENT_MODEL_PROFILE=openai
OPENAI_MODEL=gpt-4.1-mini
OPENAI_API_KEY=...

AGENT_MODEL_PROFILE=minimax
MINIMAX_MODEL=MiniMax-M2.1
MINIMAX_API_KEY=...
MINIMAX_API_BASE=https://api.minimax.io/v1

AGENT_MODEL_PROFILE=gemini
GEMINI_MODEL=gemini-flash-lite-latest
GEMINI_API_KEY=...

# No profile: explicit provider prefix is required.
AGENT_DEFAULT_MODEL=openai:gpt-4.1-mini
OPENAI_API_KEY=...
```

## Public Agent Config
`public/agent-config.json` is a non-secret local experiment file read by both the browser wrapper and Flask backend. It is served publicly, so it must never contain API keys, secret-bearing base URLs, or credentials.

Current shape:

```json
{
  "agent": {
    "playData": 1,
    "level": 1,
    "maxPlaybackTimeSeconds": 120,
    "maxSteps": 300,
    "historyLimit": 24,
    "modelProfile": null
  },
  "backend": {
    "candidateLimit": 7,
    "maxActionTicks": 20,
    "temperature": 1
  }
}
```

Backend fields:

- `backend.candidateLimit`: number of sorted candidates sent to the model.
- `backend.maxActionTicks`: maximum ticks in one candidate action. Values above 20 are capped because the legacy hook caps one agent step at 20 ticks.
- `backend.temperature`: model sampling temperature for candidate selection.

Browser fields:

- `agent.playData` and `agent.level`: requested runtime context. The current backend still accepts only Classic `1:1`.
- `agent.maxPlaybackTimeSeconds`: AI run limit in legacy game-time seconds.
- `agent.maxSteps`: emergency backend-decision step cap. Classic level 1 defaults to 300 so guard-heavy normal-mode runs can finish while still remaining bounded.
- `agent.historyLimit`: recent browser history entries sent to the backend.
- `agent.modelProfile`: optional non-secret profile name. URL `?profile=...` and `window.__lodeRunnerAgentOptions.modelProfile` override it.

The backend reloads this JSON before each planning request. The browser fetches it before
starting each AI run. Invalid or missing values fall back to defaults in `agent/config.py`;
`maxActionTicks` is always capped at the legacy limit of 20.

Environment-only settings:

- Provider credentials and secret-bearing model configuration stay in `.env` / `.env.local`.
- `AGENT_DEBUG_LOG`, `APP_LOG_LEVEL`, `AGENT_MODEL_PROFILE`, and `AGENT_DEFAULT_MODEL` remain environment variables.

## Logging And Debug I/O
`agent/logging_utils.py` configures low-noise Python logs before Flask is created.

- app logger namespace: `loderunner.agent`
- root logger level: `WARNING`
- Werkzeug access logs: `WARNING`
- format: single-line `key=value`

`python app.py --debug` sets `APP_LOG_LEVEL=DEBUG` and `AGENT_DEBUG_LOG=1` before logging
is configured. Setting `AGENT_DEBUG_LOG=1` directly also enables debug-level app logging.
`npm run api` selects the project `.venv` Python on macOS/Linux or Windows and enables
Flask's source reloader. Python changes restart the development server automatically
while the interactive Flask debugger remains disabled.
Raw prompts and model outputs are written to `__data1/agent-debug.log` with 10-entry
rotation. Each block includes trace id, model, prompt, final message, optional
provider reasoning content or OpenAI Responses API reasoning summary, parse error,
and selected candidate id. OpenAI-profile calls use the Responses API with a low
reasoning effort and request an explicit brief decision rationale; that declared
rationale is used when the provider does not return a reasoning summary. This is
observable model output, not hidden chain-of-thought. Raw model I/O is never
written to stdout or `agent-traces.json`.

## Offline Analytics

`scripts/trace-analytics.ipynb` reads the current flat recording and trace stores without
modifying them. It builds recording, run, step, and candidate data frames; joins recordings
to traces by `traceId`; and charts outcomes, model usage, run duration, candidate selection,
loop-filter events, and generic fallbacks. Notebook dependencies are included in `requirements.txt`.
