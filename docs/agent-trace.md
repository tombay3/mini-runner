# Agent Trace Store

## Summary
`agent-traces.json` is the detailed debugging store for the Lode Runner LLM agent. It records each backend planning step for the latest retained agent run, including snapshot summaries, generated candidates, the selected candidate, model metadata, stall handling, and validation outcome.

The trace store is diagnostic data, not replay data. Replayable demos live in [__data1/recordings.json](../__data1/recordings.json) and reference traces through `traceRef`.

## Store Location
The Flask backend stores traces at:

- [__data1/agent-traces.json](../__data1/agent-traces.json)

The path is currently defined in [app.py](../app.py):

- `TRACE_STORE_PATH = <repo>/__data1/agent-traces.json`
- `TRACE_STORE_VERSION = 1`

## Retention
Trace retention is intentionally shallow.

- A new agent run replaces the previous persisted run in `runs`.
- `latestRuns` keeps the latest run metadata by context key, such as `"1:1"`.
- The current implementation targets Classic `playData=1`, `level=1`, so the store usually contains only one latest run.
- Recordings are retained separately and may point to the latest trace through `traceRef`.

This keeps local debugging manageable while avoiding a growing trace history file.

## API
Trace-related API routes are implemented in [app.py](../app.py).

`GET /api/agent/traces/<trace_id>`

Returns the retained trace run for `trace_id`, or `404` if that trace is no longer retained.

`GET /api/agent/runs/<playData>/<level>`

Returns latest run metadata plus the saved recording for that `playData` / `level` if either exists.

`POST /api/agent/next-action`

Creates/appends one step in the current trace run and returns:

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

## Top-Level Shape
The trace store shape is:

```json
{
  "version": 1,
  "updatedAt": "2026-05-27T21:02:24.221Z",
  "latestRuns": {
    "1:1": {
      "traceId": "...",
      "playData": 1,
      "level": 1,
      "runMode": "single",
      "requestedModel": "openai:gpt-5.4-nano",
      "updatedAt": "...",
      "stepCount": 2,
      "latestAction": {}
    }
  },
  "runs": {
    "<traceId>": {}
  }
}
```

## Run Shape
Each run under `runs[traceId]` contains:

- `id`: trace/run id.
- `createdAt`: first step timestamp.
- `updatedAt`: last persisted step timestamp.
- `playData`: numeric play data id.
- `level`: numeric level.
- `requestedModel`: resolved model string used for the run.
- `runMode`: currently `single`.
- `steps`: ordered list of step traces.
- `stepCount`: number of stored planning steps.
- `latestAction`: action returned by the latest step.
- `latestPlanner`: planner metadata from the latest step.

`stepCount` is the total number of backend planning steps. Individual steps are zero-indexed with `stepIndex`, so a run with `stepCount = 2` has step indexes `0` and `1`.

## Step Shape
Each step is produced by [agent/traces.py](../agent/traces.py), then [app.py](../app.py) adds `stepIndex`, `playData`, and `level`.

Important fields:

- `createdAt`: step timestamp.
- `stepIndex`: zero-based position within the run.
- `playData` / `level`: added by the Flask route before persistence.
- `runMode`: currently `single`.
- `requestedModel`: requested/resolved model string.
- `selectedModel`: model used for the actual call.
- `snapshot`: compact summarized live game state.
- `analysis`: full normalized backend state analysis used to generate candidates.
- `candidates`: full candidate list considered by the model.
- `selectedCandidate`: candidate chosen after model selection, validation, retry, or fallback.
- `validation`: selected-candidate validation and fallback metadata.
- `historyTail`: compact recent browser-executed action history.
- `action`: final translated `{ keyCode, ticks, reason }` returned to the browser.
- `planner`: model/provider and candidate-selection metadata.
- `guardrail`: current stall-supervisor metadata.
- `finalMessage`: final model message when available.
- `intermediateMessages`: normally empty in V2 because default runtime does not use tool-calling loops.
- `response`: compact provider response id/model.

Planner model metadata is logical, not transport-specific. Current planner fields include:

- `modelProfile`: selected profile, such as `openai`, `minimax`, `gemini`, or `explicit`.
- `provider`: logical provider used for user-facing metadata.
- `model`: logical `provider:model` string.
- `modelSource`: where model selection came from, such as request or config.
- `mode`: currently `candidate-selection`.
- `generatedAt`: provider response creation timestamp when available.
- `responseId`: provider response id when available.
- `selectedCandidateId` / `selectedCandidateKind`
- `fallbackUsed` / `fallbackReason`
- `candidateCount`
- `stallSupervisor`

Obsolete transport fields such as `aisuiteProvider` and `aisuiteModel` are not stored in trace planner metadata. For example, Gemini may be routed through an OpenAI-compatible transport internally, but the trace records the logical provider/model as `gemini`.

## Snapshot Summary
The `snapshot` field is a compact summary generated by [agent/traces.py](../agent/traces.py) using [agent/candidates.py](../agent/candidates.py) analysis.

Typical fields:

- `gameState`: state name such as `running`.
- `tick`: legacy `recordCount` tick.
- `godMode`: whether legacy god mode was active.
- `goldCount`: remaining gold count.
- `goldComplete`: whether exit phase is active.
- `runner`: runner position/action summary.
- `guards`: guard position/action summaries.
- `gold`: visible gold and guard-carried gold.
- `nearestGold`: nearest gold candidates.
- `primaryProgressTarget`: current best progress target.
- `rowLadders`: visible ladders on the runner row.
- `risk`: guard-risk summary.
- `movement`: current legal movement affordances.
- `dig`: current legal dig affordances.
- `ladder`: current ladder affordance.
- `routeAccess`: route-access digging/follow-up affordance.
- `stallReport`: deterministic stall/loop diagnosis.

The trace does not store the full raw browser snapshot in `snapshot`; it stores a normalized debugging summary. The richer normalized state is under `analysis`.

## Candidate Data
V2 is candidate-centric. The LLM does not invent raw `keyCode` / `ticks`.

Each candidate usually includes:

- `id`: stable candidate id for this step.
- `kind`: candidate type, such as `collect_same_row_gold` or `climb_ladder`.
- `label`: short readable label.
- `goal`: what the candidate is trying to accomplish.
- `target`: coordinate/object target when applicable.
- `firstAction`: translated action candidate with `keyCode`, `ticks`, and `reason`.
- `score`: ranking score after candidate generation and stall adjustments.
- `risk`: compact risk classification.
- `reason`: why the candidate exists.
- optional stall metadata such as blocked/recovery information.

The model returns a `candidateId`. The backend validates it and translates the candidate’s `firstAction` into the response action.

## Validation And Stall Metadata
`validation` describes how the selected candidate was accepted or changed.

Common fields:

- `knownCandidate`: whether the model-selected id matched a generated candidate.
- `requestedCandidateId`: candidate id returned by the model.
- `selectedCandidateId`: candidate id finally used.
- `actionValid`: whether the translated action remained physically valid.
- `fallbackUsed`: whether the backend used a fallback candidate.
- `fallbackReason`: why fallback occurred.
- `stallBlocked`: whether the model-selected candidate was blocked by stall tooling.
- `stallBlockReason`: why the candidate was blocked.
- `stallReportType`: detected stall type.
- `stallSeverity`: `none`, `watch`, or `stalled`.

`planner.stallSupervisor` and `guardrail` expose the same high-level stall-supervisor outcome for easier inspection.

Current stall types may include:

- `horizontal_oscillation`
- `vertical_ladder_oscillation`
- `same_candidate_no_progress`
- `same_tile_no_progress`
- `route_access_loop`
- `exit_ladder_loop`
- `wait_loop`

## Timing And Step Counts
There are several different counters:

- `stepCount`: number of backend planning decisions persisted for the run.
- `stepIndex`: zero-based index of a persisted step.
- `snapshot.tick`: legacy `recordCount` tick at the planning snapshot.
- `action.ticks`: number of legacy manual ticks the browser should step for that chosen action.
- `demo.time`: persisted recording duration in legacy recorded ticks.

The frontend AI loop also has limits documented in [docs/llm-agent.md](./llm-agent.md), including `AGENT_MAX_STEPS` and a 2-minute legacy playback-time cap.

## Trace And Recording Link
Agent recordings are stored in [__data1/recordings.json](../__data1/recordings.json).

An agent recording may include:

- `source: "agent"`
- `result: "success"` or `"failure"`
- `solver.traceId`
- `traceRef`
- `demo`

`traceRef` is the bridge from a saved recording to the latest retained diagnostic trace. Because trace retention is shallow, an old recording may reference a trace id that is no longer present after a newer agent run.

## Trace Versus Logs
Detailed agent diagnosis belongs in traces, not logs.

Logs, documented in [docs/logging.md](./logging.md), are intentionally compact and operational:

- request received
- step selected
- recording saved
- config/model errors
- trace/recording persistence errors

Traces carry the expensive debugging details:

- candidate lists
- model messages
- stall reports
- validation/fallback outcomes
- compact game-state summaries

## Reading A Trace
For quick inspection:

1. Check `latestRuns["1:1"].traceId`.
2. Open `runs[traceId].stepCount` to see total backend decisions.
3. Inspect `runs[traceId].latestAction` and `latestPlanner`.
4. Inspect the last item in `runs[traceId].steps`.
5. Compare `snapshot.runner`, `snapshot.gold`, `snapshot.primaryProgressTarget`, and `snapshot.stallReport`.
6. Compare `candidates`, `selectedCandidate`, `validation`, and `action`.

Useful one-liner:

```sh
python3 - <<'PY'
import json
data = json.load(open("__data1/agent-traces.json"))
latest = data["latestRuns"]["1:1"]["traceId"]
run = data["runs"][latest]
print(latest, run["stepCount"], run.get("latestAction"))
PY
```

## Current Limitations
Current trace behavior is intentionally local and simple:

- one retained run at a time
- no long-term run archive
- no browser-side trace viewer
- no full raw snapshot persistence in the compact `snapshot` field
- no default `aisuite` tool-calling transcript because V2 does not use tool-heavy planning
- no runtime benchmark trace because benchmark mode is not current behavior

If longer-term analysis becomes useful, the next practical step would be appending timestamped trace files or adding a small trace browser, not expanding runtime logs.
