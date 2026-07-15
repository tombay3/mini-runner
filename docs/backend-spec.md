# Backend Spec

## Summary
`app.py` provides local Flask APIs for recording persistence, agent planning, trace retrieval, model configuration, logging, and raw model I/O debugging.

Current backend layers:

- `candidates`: extracts normalized facts, then generates and scores candidate actions.
- `reasoning_tools`: deterministic movement, guard, dig, and route helpers.
- `stall_tools`: deterministic oscillation/loop/stall diagnosis and recovery hints.
- `prompt`: formats current state summary, candidate list, optional stall report.
- `service`: orchestrates model call, candidate validation, retry/fallback, and trace assembly.

Mutable local stores:

- `__data1/recordings.json` replayable user and agent demos.  Agent recordings reference traces with `traceId`.
- `__data1/agent-traces.json` agent traces of latest runs.
- `__data1/agent-debug.log` when debug logging is enabled.

## Recording API
- `GET /api/recordings`: return the full recording store.
- `GET /api/recordings/<playData>/<level>`: return the newest matching record or `404`.
- `GET /api/recordings/<playData>/<level>/records`: return all retained matching records newest-first, each with compact linked trace metadata when available.
- `PUT /api/recordings/<playData>/<level>`: save a new record and prune to 10 newest records.
- `DELETE /api/recordings/<playData>/<level>`: delete the newest matching record and linked trace when present.
- `DELETE /api/recordings/<playData>/<level>?recordId=<recordId>`: delete the selected record and linked trace when present.
- `DELETE /api/recordings/<playData>/<level>?traceId=<traceId>`: delete the agent record whose id matches the trace id and delete that trace.

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
      "traceId": "<traceId>",
      "solver": {},
      "demo": {}
    }
  }
}
```

Agent recordings use `traceId` as `id`. User recordings use `user:<timestamp>`.

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
  "candidateId": "...",
  "candidate": {},
  "candidates": [],
  "validation": {}
}
```

## Backend Agent Flow
- The endpoint supports Classic `playData=1`, `level=1`. Its flow is:
  `snapshot + history -> candidate analysis -> LLM candidate choice -> action validation -> response`.
- Candidate generation and stall analysis happen deterministically in Python before the LLM call.
- `agent-traces.json` is the diagnostic store for the V2 Lode Runner candidate agent. It records recent backend planning steps, compact state summaries, generated candidate summaries, the selected candidate, validation, stall supervision, and model metadata.

## Trace API And Store
- `GET /api/agent/traces/<trace_id>`: return one retained trace run.
- `GET /api/agent/runs/<playData>/<level>`: return latest trace metadata and saved recording for that context.

The trace store has this shape:

```json
{
  "version": 1,
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
      "steps": []
    }
  }
}
```

`step.state` is a prompt-parity summary rather than a full snapshot. It contains:

- `gameState`, `tick`, and `godMode`;
- compact `runner` and `gold` objects;
- `primaryProgressTarget` and compact `guardRisk`;
- movement booleans;
- ladder detail and a compact route-access summary.

Each step also stores `candidates`, `selectedCandidateId`, `selectedCandidateKind`,
`validation`, `action`, `stallSupervisor`, and `historyTail`. Full terrain, guard lists,
movement details, dig analysis, and raw model messages are not stored in `step.state`.

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
    "maxSteps": 200,
    "historyLimit": 24,
    "modelProfile": null
  },
  "backend": {
    "candidateLimit": 7,
    "maxActionTicks": 20,
    "temperature": 0.5
  },
  "prompt": {
    "showCandidateScores": true
  }
}
```

Backend fields:

- `backend.candidateLimit`: number of sorted candidates sent to the model.
- `backend.maxActionTicks`: maximum ticks in one candidate action. Values above 20 are capped because the legacy hook caps one agent step at 20 ticks.
- `backend.temperature`: model sampling temperature for candidate selection.
- `prompt.showCandidateScores`: whether prompt candidate lines include numeric `score=...`. Scores remain in traces either way.

Browser fields:

- `agent.playData` and `agent.level`: requested runtime context. The current backend still accepts only Classic `1:1`.
- `agent.maxPlaybackTimeSeconds`: AI run limit in legacy game-time seconds.
- `agent.maxSteps`: emergency backend-decision step cap.
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
Raw prompts and model outputs are written to `__data1/agent-debug.log` with 10-entry
rotation. Each block includes trace id, model, retry flag, prompt, final message, optional
provider reasoning content, parse error, and selected candidate id. Raw model I/O is never
written to stdout or `agent-traces.json`.

## Offline Analytics

`scripts/trace-analytics.ipynb` reads the current flat recording and trace stores without
modifying them. It builds recording, run, step, and candidate data frames; joins recordings
to traces by `traceId`; and charts outcomes, model usage, run duration, candidate selection,
stalls, and fallbacks. Notebook dependencies are included in `requirements.txt`.
