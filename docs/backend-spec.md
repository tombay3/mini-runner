# Backend Specification

## Summary
`app.py` serves the local planning, recording, and trace APIs. This document owns
the endpoint, configuration, and stored-data contracts.
Flask listens on `0.0.0.0:8485`; the debugger is disabled.

Backend layers:

- `candidates`: extracts normalized facts, then generates and scores candidate actions.
- `reasoning_tools`: deterministic movement, guard, dig, and route helpers.
- `loop_tools`: deterministic stationary, horizontal, and vertical cycle detection and suppression.
- `prompt`: formats the current state summary and eligible candidate list, including compact loop status.
- `planner` selects a sole candidate directly or asks the model to choose. It validates the action and assembles the step trace.
- `llm_client` sends Chat Completions and Decisions requests and parses each API’s response.

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

Deleting a pinned recording returns `409` unless the request selects an explicit
`recordId` (or `traceId`) and sends JSON `{"confirmPinnedDeletion": true}`.
The wrapper uses a stronger confirmation for pinned runs; confirmed deletion removes
the recording and its linked trace together.

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
`POST /api/agent/next-action` requires a JSON object with supported context, a
snapshot object, and optional history/model/run fields. Non-object bodies return
a JSON `400` error. A valid request appends one trace step and returns one action:

```json
{
  "action": { "keyCode": 39, "ticks": 8, "reason": "..." },
  "planner": {
    "profile": "openai",
    "provider": "openai",
    "modelId": "gpt-5-nano",
    "api": "chat_completions",
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
  decision/fallback, nonexposed candidate events, loop status, and run metadata.

## Trace API And Store
- `GET /api/agent/traces/<trace_id>`: return `{ "version": 4, "run": <run> }`.
- `GET /api/agent/runs/<playData>/<level>`: return latest trace metadata and saved recording for that context.

This section is the canonical trace API/store reference. `app.py` owns storage, endpoints and
run metadata; `agent/traces.py` serializes steps and terminal state, using model-input formatters
from `agent/prompt.py`. The supported context is Classic `playData=1, level=1`.
Dashboard views and indicators belong in [Trace dashboard](../analytics/README.md);
reviewed findings and comparison groups belong in [Trace cohorts](../analytics/cohorts.md).

The trace store shape is:

```json
{
  "version": 4,
  "updatedAt": "2026-05-28T00:00:00.000Z",
  "runs": {
    "<traceId>": {
      "id": "<traceId>",
      "createdAt": "...",
      "updatedAt": "...",
      "playData": 1,
      "level": 1,
      "model": { "profile": "openai", "provider": "openai", "modelId": "gpt-5-nano", "api": "chat_completions" },
      "config": { "candidateLimit": 7, "maxActionTicks": 20, "temperature": 1 },
      "outcome": null,
      "steps": []
    }
  }
}
```

Run data with outcome:

- Each run stores `model` and `config` once, plus `steps` and nullable `outcome`.
- Model and backend controls are fixed within a run. Changing either requires a new run;
  finalized runs reject further appends.
- A run finalized without planning has null model/config.
- `stepCount` and `latestAction` are derived API/view summaries, not stored run fields.
- A terminal outcome is `{result, reason, finalState}`; `null` means no recorded terminal outcome.
- `outcome.finalState` stores the terminal runner, guard, gold, tick, game-state, and god-mode
  data needed to classify success or failure, or null when no final snapshot exists.
  Terminal snapshots contain observations and omit threat assessments; consumers display missing risk as unknown.

The step shape is:

```text
{
  createdAt,
  state: {
    tick, gameState, godMode,
    runner: {x, y, xOffset, yOffset, action},
    guards: [{id, x, y, xOffset, yOffset, action, carryingGold}],
    gold: {remaining, complete, visible: [{x, y, ...}]},
    goldTarget, exitTarget, threat, movement, route
  },
  candidates: [{id, kind, lane, score, target, reasons,
                offeredAction: {keyCode, ticks, name}}],
  decision: {requestedId, selectedId, rationale,
             fallback: null | {code: "candidate_fallback", message}},
  issuedAction: {keyCode, ticks},
  loop: {active, type, suppressedCount},
  excludedProposals: [{candidateId, kind, status, proposedAction: {keyCode, ticks}, reason}],
  recentProgress: optional bounded model-input summary
}
```

Step data:

- `step.state` contains `tick`, `gameState`, `godMode`, `runner`, `guards`, `gold`, and assessed `threat`.
  Planned steps also retain model-input `goldTarget`, `exitTarget`, `threat`, `movement`, and
  `route`, using the prompt formatters. `exitTarget` is the next approach or climb
  waypoint; see [exit waypoint selection](./candidate-design.md#state-and-ladder-geometry).
  `guards` contains the engine's observed entities;
  `threat` includes individual risk/motion under `primaryThreat` and `guardAssessments`.
  `threat.guardAssessments` retains all guards with valid coordinates, sorted by
  distance; it is not limited to four entries.
  `movement` includes physical directions and open holes; `route` includes ladder
  and dig-access information. Empty objects and unknown optional values may be omitted;
  empty lists, false and zero are retained as known observations. Gold positions retain
  supplied model metadata such as tile/source. Missing observations remain unknown.
  When history is available, `step.recentProgress` retains the bounded progress summary
  supplied to the model.
- `candidates` contains the exposed executable backend choices, including each candidate's ID, kind, lane,
  score, full target, reasons, and offeredAction (including its name).
  Model-input reasons are retained in full in the single `reasons` list.
- `decision` contains `requestedId`, `selectedId`, `rationale`, and nullable `fallback:{code,message}`.
  The only fallback code is `candidate_fallback`. Rationale and fallback message
  are each bounded to 240 characters.
- Step `issuedAction` contains the backend-issued `keyCode` and `ticks`; it does not certify engine
  execution. Candidate `offeredAction` is the offered input. `loop` contains `active`, `type`, and the
  model-input `suppressedCount`.
- `excludedProposals` contains nonexposed `{candidateId,kind,status,proposedAction:{keyCode,ticks},reason}` rows,
  with statuses `safety_rejection`, `physical_rejection`, `deduplicated`, `loop_suppressed`, and
  `limit_truncated`. Each event is a nonexposed proposal occurrence, using its proposed action;
  repeated IDs remain separate occurrences. Events carry no scores, lanes, targets or audit payload.
  Physical rejection reasons describe the blocked move or open hole. Event reasons are capped at 240 characters. Exposed/proposed audit rows are not emitted as events.
- Step index and selected kind are derived. Raw model messages, provider reasoning, terrain,
  non-model analysis, score breakdowns, and candidate audits are not stored in traces.

### Model state context

The model receives the following compact context. Trace state retains the same
`goldTarget`, `exitTarget`, `threat`, `movement`, and `route` structures.

```text
game: {playData, level, gameState, godMode}
runner: {x, y, xOffset, yOffset, action}
gold: {remaining, complete, visible: [{x, y, ...}]}
goldTarget: {x, y, ...}
exitTarget: {x, y, tile}
threat: {
  risk,
  primaryThreat: guard,
  guardAssessments: [guard]
}
guard: {id?, x, y, relativeX, relativeY, distance, motion,
        approachingOnSameRow, risk, carryingGold}
movement: {
  physicalDirections: [left|right|up|down],
  openHoles: {left|right: {openDugHoleDistance,
              hole: {x, y, distance, occupiedByTrappedGuard}}}
}
route: {
  ladder: {onLadder, atDownwardEntry, onExitLadder, adjacentToLadder, preferredDirection,
           nearestRowEntry: {x, y, tile, distance, direction, entryDirection, ladderY}},
  digAccess: {digAvailable, digAction, entryAvailable, entryAction,
              entryBlockedByGuard, digBlockedByGuard, accessCell,
              dropThreat: {unsafe, nearestGuard: guard}, reason}
}
loop: {active, type, suppressedCount}
```

- `primaryThreat` prioritizes assessed risk, same-row pressure, then distance;
  it need not be the nearest guard. `approachingOnSameRow` only describes horizontal
  approach on the runner's row, not a general future interception prediction.
- `carryingGold` is true only for a positive engine carrying counter. Negative
  cooldowns do not represent held gold. Raw counters remain engine/replay data.
- `physicalDirections` does not certify guard safety or candidate admission.
  An empty list means no physically available direction; omission means unknown.
- `nearestRowEntry` is a local access point. `preferredDirection` is a local hint;
  it does not override exposed candidates or execution gates.
- `digAvailable` concerns creating access; `entryAvailable` concerns entering an
  existing opening. These are separate operations, not contradictory availability flags.
- `goldTarget` is a preferred visible-gold objective, not a verified route.
  `exitTarget` is an approach/climb waypoint, not necessarily the final destination.
- Top-level trace `state.guards` retains actual engine observations. `threat` retains
  decision assessments. Aggregate risk exists only at `state.threat.risk`. Missing terminal assessments remain unknown.
- Candidate `offeredAction` has `name` and `ticks` in model context; traces additionally
  retain its `keyCode`. `kind`, `lane`, `score`, `target` and `reasons` are shared.

### Recent progress context

When history exists, the model and trace share `recentProgress`:

```text
entries: [{candidateId, issuedAction: {name, ticks},
           before: {x, y, xOffset, yOffset}, after: {x, y, xOffset, yOffset},
           tileChanged, offsetChanged, remainingGoldDelta}]
repeatedCandidate: {candidateId, entryCount, target: {x, y},
                    startDistance, endDistance, distanceChange,
                    targetDistanceReduced, targetTileReached}
```

This contains at most eight entries. `repeatedCandidate` describes the consecutive
tail sharing the latest candidate ID. Deltas are after minus before; a negative
gold delta means collection and a negative distance delta means closer to the
candidate target. `targetTileReached` ignores offsets. Distance reduction is not
proof of safety or gameplay progress. Missing measurements are null here, rather
than invented zeroes. Historical candidate IDs are observations, not current choices.

Derived view/API fields include one-based display step, selected kind (lookup by `selectedId`),
request membership, fallback status, last action, after-state and elapsed time. They are not
duplicated in stored steps. Game time uses 16 ticks per second; wall-clock duration uses timestamps.

For example, an unknown requested ID records the intervention separately from execution:

```json
{
  "decision": {
    "requestedId": "missing-id", "selectedId": "collect_same_row_gold_17_14_right",
    "rationale": "Move toward gold.",
    "fallback": {"code": "candidate_fallback", "message": "unknown candidateId: missing-id"}
  },
  "issuedAction": {"keyCode": 39, "ticks": 4}
}
```

A safety rejection remains a nonexposed event with no score:

```json
{
  "candidateId": "retreat_from_guard_up", "kind": "retreat_from_guard",
  "status": "safety_rejection", "proposedAction": {"keyCode": 38, "ticks": 6},
  "reason": "Approaching secondary guard."
}
```

### Candidate score diagnostics

Only exposed candidates' scalar `score` is persisted in traces. `candidateAudit`, `scoreBreakdown`,
`proposedScore`, `proposedScoreBreakdown`, `scoreStage`, and `rankingTieBreak` are internal
diagnostics.

`score` is the effective integer ranking value. Internal `scoreBreakdown` contains
the named policy, total and actual signed components. Components sum to the total;
fixed base values are not split into invented risk/progress factors.

`candidateAudit` keeps `proposedScore` and `proposedScoreBreakdown` separate from
the effective `score` and `scoreBreakdown`. Its `scoreStage` identifies the internal scoring stage:

| Stage | Meaning |
|---|---|
| `proposal` | Ranking adjustments have not been applied. Rejected or duplicate-ID proposals may stop here. |
| `validated` | The pre-shortlist score includes applicable adjustments, even if the candidate is later loop-suppressed or truncated. |


A merged candidate keeps the winning proposal's breakdown, not the sum of merged
scores. `rankingTieBreak` instead explains order among equal-score retreats: both
predicted guard distances, winner, duration, ticks per cell and order-change flag. It
does not add a numeric score component or certify safety. The forecast uses tile
coordinates at eight ticks per cell, not full physics simulation.

See [current ranking rules](candidate-design.md#scoring-and-deduplication).

### Loop diagnostics

- `loop` stores confirmed status and type; suppression is recorded in `excludedProposals`.
- Loop-filter behavior is defined in [candidate design](./candidate-design.md#loop-handling).

Dashboard loading, derived after-state, event markers, and UI behavior are documented in
[Trace dashboard](../analytics/README.md).

Retention and run metadata:

- The trace store keeps runs linked by pinned recordings plus the newest 10 other runs.
- Recordings keep all pinned records plus the newest 10 unpinned records; recordings alone own pin state.
- [Retention and missing links](../analytics/README.md#retention-and-missing-links) explains how
  the dashboard presents unavailable evidence.


## Model identity

Planner responses, recording solver metadata and trace model objects use
profile, provider, modelId and api. The provider identifies the service receiving the request. The model ID is the exact submitted ID, without a service prefix. API values are chat_completions and decisions. Display labels use profile:modelId.

## Model Profiles
The backend uses a shared Chat Completions adapter for direct OpenAI and Gemini. Resolution order is:

1. explicit request `model`;
2. request `modelProfile` (the browser derives this from `?profile=...`, runtime options,
   or public config);
3. `public/agent-config.json` `agent.modelProfile`;
4. `AGENT_MODEL_PROFILE`;
5. `AGENT_DEFAULT_MODEL`, which requires `provider:model` format.

Supported profiles:

- `openai`: `OPENAI_MODEL`, `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`.
- `gemini`: `GEMINI_MODEL`, `GEMINI_API_KEY`, optional `GEMINI_API_BASE`.
- `openai-decisions`: `OPENAI_API_KEY`, optional `OPENAI_DECISIONS_MODEL` (currently only `gpt-6-luna`) and `OPENAI_BASE_URL`. It uses a typed choice over the ordered candidate IDs. Refusal and malformed answers use the ordinary candidate fallback; confidence and probabilities are diagnostics only.
- `openrouter`: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (explicit `vendor/model` slug), and `OPENROUTER_PROVIDER` (one provider slug). The endpoint is fixed at `https://openrouter.ai/api/v1`; routing uses `only`, disables fallback, and requires support for submitted parameters. OpenRouter includes usage automatically. The adapter records the serving provider when supplied. A base provider slug can match several variants or regions; specify the full endpoint slug when a comparison requires one variant or region.

The repository configuration and examples contain only the explicit `openai:` prefix; the former aisuite registry accepted additional provider prefixes, which now require review and explicit support. Explicit model IDs support `openai:model`; use named profiles to select Decisions or OpenRouter; other direct prefixes, including retired MiniMax, are rejected. Historical traces remain readable. The adapter uses a 90-second timeout and no automatic retries (the former aisuite path could retry). Temperature is omitted for OpenAI GPT-5 model IDs because those reasoning models may reject it; effective settings record only parameters sent. Custom endpoints are classified as custom gateways with unknown serving provider for price attribution. Chat returns the requested JSON gameplay rationale; Responses reasoning summaries are no longer requested.

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

- `APP_LOG_LEVEL` uses standard Python level names and aliases; unrecognized names fall
  back to `INFO` at startup and refresh. `AGENT_DEBUG_LOG` overrides the level to `DEBUG`.
- `python app.py --debug` enables debug logging and model-I/O diagnostics.
- `AGENT_DEBUG_LOG=1` enables the diagnostics without Flask debug mode.
- `npm run api` uses the project virtual environment and Flask source reloading; the interactive
  Flask debugger remains disabled.
- Debug model I/O is written to `__data1/agent-debug.log` with 10-entry rotation. The model line uses `profile:model-id`, retaining the supplied model identifier when the profile is unavailable. Entries include
  prompt/model output and correlation identifiers only, with no selected-candidate
  or error headers.
- OpenAI calls request a brief observable rationale. Raw model I/O is never written to stdout or
  `agent-traces.json`.

## Local model metrics

**SQLite schema version 2** (`PRAGMA user_version = 2`) has two tables. Each run counts its attempted decisions and owns its model calls. Normal gameplay writes to `__data1/metrics.sqlite3`. Set `AGENT_METRICS_PATH` to select another file. God-mode tests skip ingestion. The evaluator keeps launch provenance, attempts and persistence checks in its result.

### `runs` — one row per measured game

| Column | SQLite type | Meaning |
|---|---|---|
| `id` | TEXT PRIMARY KEY | Run ID shared with the V4 trace and agent recording. |
| `profile`, `model_id` | TEXT | Configured project profile and submitted model ID. Together they identify a notebook group. |
| `api`, `gateway` | TEXT | Configured API and route, such as `decisions` and `direct`. Both are fixed for the run. |
| `gw_provider`, `gw_model` | TEXT | Serving provider and returned model ID. Each starts unknown, takes its first known value and becomes `Mixed` if known values disagree. |
| `saved_at` | TEXT | Recording save timestamp. NULL until finalization. Migrated games use the old run end time when the recording timestamp is unavailable. |
| `result`, `reason` | TEXT | Recorded outcome and optional reason. The report uses both to classify gameplay losses. |
| `initial_gold`, `final_gold` | INTEGER | Gold remaining at the first measured snapshot and at finalization. Their difference is gold collected. |
| `wall_ms` | REAL | Whole-game elapsed time in milliseconds, supplied at finalization. |
| `decisions` | INTEGER NOT NULL | Attempt count. Defaults to zero and increments at decision start, including forced moves and attempts that fail. |

### `model_calls` — one row per attempted model call

| Column | SQLite type | Meaning |
|---|---|---|
| `id` | TEXT PRIMARY KEY | Local request ID allocated before dispatch. |
| `run_id` | TEXT NOT NULL | Foreign key to `runs.id`, indexed by `calls_run`. |
| `diverged` | INTEGER | 1 for a lower-scoring requested candidate whose action differs from every top action, 0 for other evaluable choices, NULL when the request cannot be scored. |
| `status` | TEXT NOT NULL | Starts as `pending`. Completion records `ok`, `error`, `refusal` or `parse_error`. |
| `latency_ms` | REAL | Elapsed milliseconds for this model request. |
| `input_tokens`, `output_tokens` | INTEGER | Provider-reported totals. Add these two fields for total token usage. |
| `cached_tokens`, `cache_write_tokens` | INTEGER | Input tokens served from cache and written to cache, respectively. Both are input breakdowns. |
| `reasoning_tokens` | INTEGER | Reasoning portion of output tokens. |

Missing measurements are NULL. A reported zero is a measured value. Cost estimates use notebook tariffs.

### Reporting and retention

Both comparison notebooks use the same Table 1 query. A run qualifies when it has a save timestamp, a gameplay win or loss, and at least one request with all request statuses equal to `ok`. A gameplay win has `result = 'success'`. A gameplay loss has `result = 'failure'` and a reason of `runner dead`, `runner_dead`, `agent max playback time reached` or `agent safety step limit reached`. [Shared query](../agent/metrics.py)

The run foreign key uses `ON DELETE CASCADE`. SQLite retention is independent of trace and recording pruning. To explicitly remove one
run and its child measurements, use `.venv/bin/python -m agent.metrics delete --run ID`.

## Offline analytics

See the [notebook guide](../analytics/README.md) for trace, model and cost comparison scopes.

## Related References

- [Candidate contract and lanes](./candidate-design.md#candidate-contract)
- [Candidate classification matrix](./candidate-design.md#candidate-classification-matrix)
- [Backend planner and candidate generation](./llm-agent.md#backend-planner-and-candidate-generation)
- [Prompt and model output](./llm-agent.md#prompt-and-model-output)
- [Safety, loops, and god mode](./llm-agent.md#safety-loops-and-god-mode)
- [Loop handling](./candidate-design.md#loop-handling)
- [Trace dashboard and retention](../analytics/README.md#retention-and-missing-links)
- [Evaluator reports](./evaluator.md#reports-and-retention)

### Single-candidate decisions

When only one validated candidate remains, the backend selects it directly for every
profile. Trace `requestedId` is null, `selectedId` identifies the offered candidate,
and fallback is null. The response planner mode is `backend-forced`. SQLite records
one attempted decision and zero model calls. Pools
with two or more candidates continue through the configured model. This also avoids
the Decisions Choice endpoint’s minimum of two options.
