# Backend Spec

## Summary
`app.py` provides local Flask APIs for recording persistence, agent planning, trace retrieval, model configuration, logging, and raw model I/O debugging.

Mutable local stores:

- `__data1/recordings.json`
- `__data1/agent-traces.json`
- `__data1/agent-debug.log` when debug logging is enabled

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
  "planner": {},
  "traceId": "...",
  "stepCount": 2,
  "candidateId": "...",
  "candidate": {},
  "candidates": [],
  "validation": {}
}
```

The endpoint supports Classic `playData=1`, `level=1`.

## Trace API And Store
- `GET /api/agent/traces/<trace_id>`: return one retained trace run.
- `GET /api/agent/runs/<playData>/<level>`: return latest trace metadata and saved recording for that context.

Trace store shape:

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
      "stepCount": 0,
      "latestAction": {},
      "steps": []
    }
  }
}
```

The trace store keeps up to 10 newest runs. Each step stores compact state, candidate summaries, selected candidate, validation, action, planner metadata, stall supervisor data, and recent browser history.

## Model Profiles
The backend uses `aisuite` for provider/model abstraction. Resolution order:

1. request-level `model`;
2. request-level `modelProfile`;
3. `AGENT_MODEL_PROFILE`;
4. `AGENT_DEFAULT_MODEL`.

Request-level `model` and `AGENT_DEFAULT_MODEL` require `provider:model` format.

Supported profiles:

- `openai`: `OPENAI_MODEL`, `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`.
- `minimax`: `MINIMAX_MODEL`, `MINIMAX_API_KEY`, optional `MINIMAX_BASE_URL` or `MINIMAX_API_BASE`.
- `gemini`: `GEMINI_MODEL`, `GEMINI_API_KEY`, optional `GEMINI_API_BASE`.

Dotenv files are reconciled before each backend planning request:

1. `~/.env`
2. `<repo>/.env`
3. `~/.env.local`
4. `<repo>/.env.local`

The browser may select a profile with `window.__lodeRunnerAgentOptions.modelProfile` or `?profile=openai|minimax|gemini`. Secrets remain server-side.

Runtime tuning:

- `AGENT_MAX_TICKS`: maximum legacy ticks for one translated candidate action.
- `AGENT_TEMPERATURE`: model sampling temperature for candidate selection.

## Logging And Debug I/O
`agent/logging_utils.py` configures low-noise Python logs before Flask is created.

- app logger namespace: `loderunner.agent`
- root logger level: `WARNING`
- Werkzeug access logs: `WARNING`
- format: single-line `key=value`

Environment controls:

- `APP_LOG_LEVEL`
- `AGENT_DEBUG_LOG=1`

`python app.py --debug` enables raw model I/O debug logging and sets app logs to `DEBUG`.

Raw prompts and model outputs are written to `__data1/agent-debug.log` with 10-entry rotation. They are not emitted to stdout and are not embedded in `agent-traces.json`.
