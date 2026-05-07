# `aisuite` and the Hybrid Lode Runner Agent

## Summary
This project now uses `aisuite` as the **backend LLM abstraction and lightweight agent orchestration layer** for the Lode Runner AI solver.

The important boundary is unchanged:
- the **browser and legacy game runtime** remain the source of truth for game physics, state transitions, guard AI, level completion, and demo recording
- the **Python backend** plans only the **next bounded move burst**
- the backend may use `aisuite` tools internally while reasoning, but it never executes the game itself

The first implementation remains scoped to Classic `playData=1`, `level=1`.

## Why `aisuite`
The earlier backend used a direct OpenAI-only HTTP call. `aisuite` was introduced to improve three things:

- **Provider abstraction**: model selection is now based on `provider:model` strings instead of one hard-coded OpenAI route.
- **Lightweight agentic tool loops**: the backend can run short internal reasoning loops with Python callables via `max_turns`.
- **Benchmarking and traces**: the backend can compare multiple model candidates and preserve richer run metadata.

`aisuite` is being used here as a **backend composition layer**, not as a full agents framework and not as a game executor.

## What `aisuite` Does Here
For each browser call to `/api/agent/next-action`, the backend:

1. validates the request and level scope
2. resolves the requested model or default model
3. builds a text prompt from:
   - rules in [puzzle-game.md](/Users/tomchin/3po/ducky/run-8283/docs/puzzle-game.md:1)
   - current snapshot
   - recent action history
4. creates a short `aisuite` completion run
5. optionally allows the model to call internal reasoning helpers
6. parses and normalizes the final JSON action
7. appends the step to a run-level trace store
8. returns the chosen action to the browser

The browser then executes the action through the existing legacy hook surface in [lodeRunner.agentHooks.js](/Users/tomchin/3po/ducky/run-8283/public/game/lodeRunner.agentHooks.js:1).

## What `aisuite` Does Not Do
- It does **not** replace the browser step loop in [agent.js](/Users/tomchin/3po/ducky/run-8283/src/agent.js:1).
- It does **not** run the legacy game engine in Python.
- It does **not** independently validate movement, digging, guard AI, or level completion.
- It does **not** provide a browser-side compare/workbench UI in v1.

## Backend Module Map
The backend agent logic is now split across these modules:

- [config.py](/Users/tomchin/3po/ducky/run-8283/agent/config.py:1)
  - agent constants
  - allowed keycodes
  - default model lookup
  - benchmark model lookup
  - model string normalization
- [aisuite_client.py](/Users/tomchin/3po/ducky/run-8283/agent/aisuite_client.py:1)
  - wraps `aisuite.Client()`
  - validates `provider:model`
  - exposes backend completion creation
- [prompt.py](/Users/tomchin/3po/ducky/run-8283/agent/prompt.py:1)
  - loads puzzle rules
  - builds the external planner prompt
- [reasoning_tools.py](/Users/tomchin/3po/ducky/run-8283/agent/reasoning_tools.py:1)
  - defines internal Python helper tools for `aisuite`
- [service.py](/Users/tomchin/3po/ducky/run-8283/agent/service.py:1)
  - orchestrates single-model and benchmark runs
  - converts model output to normalized action objects
  - assembles planner metadata and step traces
- [traces.py](/Users/tomchin/3po/ducky/run-8283/agent/traces.py:1)
  - serializes step-level trace payloads
  - summarizes snapshots for persistence
- [validation.py](/Users/tomchin/3po/ducky/run-8283/agent/validation.py:1)
  - validates API input
  - normalizes final `keyCode` / `ticks` / `reason`
- [errors.py](/Users/tomchin/3po/ducky/run-8283/agent/errors.py:1)
  - request/config/execution error classes

## Internal Reasoning Tools
`aisuite` is only allowed to call **pure reasoning helpers** that inspect snapshot/history data. It does not receive direct stepping control.

Initial tool set:
- `summarize_snapshot`
  - compact runner/guard/gold/game-state summary
- `detect_looping`
  - identifies recent repetitive action bursts
- `assess_guard_risk`
  - estimates immediate danger from nearby guards
- `suggest_subgoal`
  - suggests a short-term puzzle objective
- `evaluate_last_action`
  - labels the previous action as progress, neutral, or failure-like

These tools are rebuilt per request from the live browser snapshot and recent history.

## Prompting Model
The external prompt still asks for exactly one next action burst. The model is told:
- it may use helper tools first
- the final answer must be JSON only
- the JSON must contain:
  - `keyCode`
  - `ticks`
  - `reason`

The backend still enforces:
- allowed keycodes only
- `ticks` clamped to the configured maximum
- `reason` shortened to a bounded string

## Model Strings and Configuration
Models are configured in `provider:model` form, for example:

- `openai:gpt-4o-mini`
- `openai:gpt-4.1-mini`
- `anthropic:claude-3-5-sonnet-20240620`

If a model is supplied without a provider, the backend normalizes it to `openai:<model>` for compatibility with the earlier OpenAI-only setup.

Current environment knobs:
- `AGENT_DEFAULT_MODEL`
  - preferred default for runtime requests
- `OPENAI_MODEL`
  - fallback default if `AGENT_DEFAULT_MODEL` is absent
- `AGENT_BENCHMARK_MODELS`
  - comma-separated additional models for benchmark mode
- provider-specific API keys such as `OPENAI_API_KEY`

The backend rejects unsupported providers before attempting a live model call.

## Run Modes
### `single`
One model handles the request and returns one bounded action.

### `benchmark`
Multiple models are evaluated against the same snapshot.

Current benchmark policy:
- include the requested primary model first
- add request-level `benchmarkModels`
- add env-configured benchmark models
- discard invalid candidates
- if the requested primary model returns a valid action, it wins
- otherwise, choose the first remaining valid candidate
- persist all candidate summaries into benchmark metadata

This is a **backend-only compare mode** in v1. The browser UI does not expose a compare dashboard yet.

## Runtime Request Flow
One AI run in the browser spans **many** backend requests.

### Browser side
The browser agent loop in [agent.js](/Users/tomchin/3po/ducky/run-8283/src/agent.js:1):
- starts Classic level 1 through `lodeRunnerAgentHooks`
- captures live snapshots
- sends history and a stable `runId`
- executes returned actions
- detects finish or failure using the legacy runtime
- saves the final recording with solver metadata and `traceRef`

Optional browser configuration can be supplied through:
- `window.__lodeRunnerAgentOptions.model`
- `window.__lodeRunnerAgentOptions.runMode`
- `window.__lodeRunnerAgentOptions.benchmarkModels`

### Backend side
For each step request, [app.py](/Users/tomchin/3po/ducky/run-8283/app.py:1):
- validates scope and payload
- calls `plan_next_action()`
- appends a step trace to the run-level trace store
- returns:
  - `action`
  - `planner`
  - `traceId`
  - optional `benchmark`
  - `stepCount`

## API Surface
### `POST /api/agent/next-action`
Primary runtime planning endpoint.

Request fields:
- `playData`
- `level`
- `snapshot`
- `history`
- optional `runId`
- optional `model`
- optional `runMode`
- optional `benchmarkModels`

Response fields:
- `action`
- `planner`
- `traceId`
- optional `benchmark`
- `stepCount`

### `GET /api/agent/traces/<trace_id>`
Returns the aggregated run-level trace for one AI session.

### `GET /api/agent/runs/<playData>/<level>`
Returns:
- the latest agent run metadata for that level
- the saved recording for that level, if present

### Existing recording API extensions
`PUT /api/recordings/<playData>/<level>` now accepts:
- `source`
- `result`
- `solver`
- `traceRef`

## Trace Storage Design
The backend stores agent traces separately from replay recordings.

Current stores:
- `__data1/recordings.json`
  - replayable user and agent demos
- `__data1/agent-traces.json`
  - aggregated multi-step AI reasoning runs

This separation exists because a single AI run may generate many planning calls before the final replayable demo is known.

### Run-level trace shape
Each run in `agent-traces.json` stores:
- `id`
- `createdAt`
- `updatedAt`
- `playData`
- `level`
- `requestedModel`
- `runMode`
- `stepCount`
- `latestAction`
- `latestPlanner`
- `latestBenchmark`
- `steps`

Each stored step contains:
- compact snapshot summary
- short history tail
- selected action
- planner metadata
- benchmark summary if applicable
- final model message
- intermediate `aisuite` messages
- response id/model metadata

### Latest-run index
The trace store also keeps a `latestRuns` index keyed by `playData:level` so the most recent AI session for a level can be found quickly.

## Recording Integration
The legacy runtime is still the authority for success or failure. After the browser AI run ends:

- the legacy game recorder produces `curDemoData`
- the browser saves the final recording through the existing recording API
- the saved agent recording now includes:
  - `source: "agent"`
  - `result: "success"` or `"failure"`
  - `solver`
  - `traceRef`

The `solver` metadata can contain:
- provider
- chosen model
- generated timestamp
- response id
- benchmark summary
- failure reason
- `traceId`

This lets a replayable or failed demo be tied back to the aggregated planning run that produced it.

## Validation and Failure Modes
Current backend validations include:
- only Classic `playData=1`, `level=1`
- request body must be structured correctly
- `model` must be a string if present
- `runMode` must be `single` or `benchmark`
- `benchmarkModels` must be an array of strings
- final action must use an allowed keycode
- final `ticks` must be an integer and is clamped to the configured max

Error categories:
- request errors return `400`
- missing or invalid backend configuration returns `503`
- model/provider execution failures return `502`

## Current Scope and Limits
This implementation is intentionally conservative:
- Classic level 1 only
- browser remains the executor
- no Python-side simulator
- no browser-side benchmark viewer
- no direct model comparison UI

The backend module split is intended to support later expansion to:
- more Classic levels
- more built-in level sets
- broader benchmark policies
- richer trace exploration
- more configurable agent surfaces
