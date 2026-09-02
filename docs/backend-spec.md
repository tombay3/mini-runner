# Backend Specification

## Summary
`app.py` is the local Flask API for recordings, agent planning, traces, model configuration, and
debug logging. Use this document for endpoint contracts, configuration, and stored run data.

Backend layers:

- `candidates`: extracts normalized facts, then generates and scores candidate actions.
- `reasoning_tools`: deterministic movement, guard, dig, and route helpers.
- `loop_tools`: deterministic stationary, horizontal, and vertical cycle detection and suppression.
- `prompt`: formats the current state summary and eligible candidate list, including compact loop status.
- `service`: orchestrates one model call, generic candidate validation, and trace assembly.

Local data stores:

- `__data1/recordings.json` replayable user and agent demos.  Agent recordings reference traces with `traceId`.
- `__data1/agent-traces.json` retained agent traces.
- `__data1/agent-debug.log` when debug logging is enabled.

## Recording API
- `GET /api/recordings`: return the full recording store.
- `GET /api/recordings/<playData>/<level>`: return the newest matching record or `404`.
- `GET /api/recordings/<playData>/<level>/records`: return all retained matching records newest-first, each with compact linked trace metadata when available.
- `PUT /api/recordings/<playData>/<level>`: save a new unpinned record and retain all pinned
  records plus the 10 newest unpinned records. Updating the same id preserves its stored pin.
- `PATCH /api/recordings/<playData>/<level>/pin`: set `pinned` using a full or unique-prefix
  `recordId` and a boolean `pinned` value.
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

Agent recordings use `traceId` as `id`. User recordings use `user:<timestamp>`. With the backend
running, pin or unpin a retained Classic 1:1 run by full id or unique prefix:

```bash
npm run trace:pin -- 3dcb7b7d
npm run trace:unpin -- 3dcb7b7d
```

The API body is `{ "recordId": "3dcb7b7d", "pinned": true }`. Toggling a pin does not prune
or delete anything immediately; an unpinned run becomes eligible for normal retention pruning
when later data is saved. Missing fields are equivalent to `false`. A pinned agent recording
also protects its linked trace from pruning; pin state is never copied into `agent-traces.json`,
and a missing linked trace is not recreated.
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
    "model": "openai:gpt-5-nano",
    "mode": "candidate-selection"
  },
  "traceId": "...",
  "stepCount": 2,
  "candidateId": "..."
}
```

## Backend Agent Flow
- `snapshot + history -> candidate analysis -> LLM candidate choice -> action validation -> response`.
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

Run data with outcome:

- Each run stores `model`, `config`, `stepCount`, `latestAction`, and `outcome`.
- `outcome.finalState` stores the terminal runner, guard, gold, tick, game-state, and god-mode
  data needed to classify success or failure.

Step data:

- `step.state` is a compact prompt-parity summary of game state, runner, gold, movement, ladder,
  progress target, guard risk, open holes, and route access.
- `candidates` contains the legal backend choices, including each candidate's ID, kind, lane,
  score, target, and first action.
- The step also records the selected candidate, validation, action, and loop status. Raw model
  messages and the full terrain grid are not stored.
- `guardRisk` identifies the highest-priority mobile threat as `pressureGuard` and summarizes
  nearby guards with `relativeX`, `relativeY`, `motion`, and `closing`. Guard pressure is adjusted
  before candidate generation; `in_hole` has low immediate pressure.

Loop data:

- `loopMonitor` stores confirmed loop status, type, evidence, and `suppressedCandidates`.
- Loop-filter behavior is defined in [candidate design](./candidate-design.md#loop-handling).

Dashboard loading, derived after-state, event markers, and UI behavior are documented in
[Trace dashboard](./trace-dashboard.md).

Retention and run metadata:

- The trace store keeps up to 10 newest runs.
- Run-level `model` and `config` are stored once, not repeated on every step.
- See [retention and missing links](./trace-dashboard.md#retention-and-missing-links) for
  retention behavior.


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
OPENAI_MODEL=gpt-5-nano
OPENAI_API_KEY=...

AGENT_MODEL_PROFILE=minimax
MINIMAX_MODEL=MiniMax-M2.1
MINIMAX_API_KEY=...
MINIMAX_API_BASE=https://api.minimax.io/v1

AGENT_MODEL_PROFILE=gemini
GEMINI_MODEL=gemini-flash-lite-latest
GEMINI_API_KEY=...

# No profile: explicit provider prefix is required.
AGENT_DEFAULT_MODEL=openai:gpt-5-nano
OPENAI_API_KEY=...
```

## Public Agent Config
`public/agent-config.json` is a non-secret runtime file read by the browser wrapper and Flask
backend. Because it is public, it must not contain API keys, secret-bearing URLs, or credentials.

Example configuration:

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

- `agent.playData` and `agent.level`: requested runtime context, validated by the backend.
- `agent.maxPlaybackTimeSeconds`: AI run limit in legacy game-time seconds.
- `agent.maxSteps`: emergency backend-decision step cap, keeping guard-heavy normal-mode runs bounded.
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

- `python app.py --debug` enables debug logging and model-I/O diagnostics.
- `AGENT_DEBUG_LOG=1` enables the diagnostics without Flask debug mode.
- `npm run api` uses the project virtual environment and Flask source reloading; the interactive
  Flask debugger remains disabled.
- Debug model I/O is written to `__data1/agent-debug.log` with 10-entry rotation. Entries include
  the trace ID, model, prompt, final message, reasoning summary when available, parse errors, and
  selected candidate ID.
- OpenAI calls request a brief observable rationale. Raw model I/O is never written to stdout or
  `agent-traces.json`.

## Offline Analytics

Jupyter notebook `trace-analytics.ipynb` reads the flat recording and trace stores without
modifying them. It builds recording, run, step, and candidate data frames; joins recordings
to traces by `traceId`; and charts outcomes, model usage, run duration, candidate selection,
loop-filter events, and generic fallbacks. Notebook dependencies are included in `requirements.txt`.

## Related References

- [Candidate contract and lanes](./candidate-design.md#candidate-contract)
- [Candidate classification matrix](./candidate-design.md#candidate-classification-matrix)
- [Backend planner and candidate generation](./llm-agent.md#backend-planner-and-candidate-generation)
- [Prompt and model output](./llm-agent.md#prompt-and-model-output)
- [Safety, loops, and god mode](./llm-agent.md#safety-loops-and-god-mode)
- [Loop handling](./candidate-design.md#loop-handling)
- [Trace dashboard and retention](./trace-dashboard.md#retention-and-missing-links)
- [Evaluator reports](./evaluator.md#reports-and-retention)
