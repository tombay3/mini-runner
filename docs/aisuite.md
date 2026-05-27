# `aisuite` and the V2 Candidate Agent

## Summary
The backend now uses `aisuite` as a provider/model abstraction for the Lode Runner AI agent. It does not use `aisuite` as a game executor, a default tool-calling framework, or a runtime benchmark harness.

The current agent is V2 candidate-based:

- The browser and legacy CreateJS runtime remain authoritative for physics, guard AI, state transitions, success/failure, and demo recording.
- The backend computes a short list of legal candidate actions from the live snapshot.
- The LLM chooses one `candidateId`.
- The backend translates that candidate into `{ keyCode, ticks }`.
- The browser steps the legacy runtime and records the resulting demo.

Current scope is Classic `playData=1`, `level=1`.

## Model Configuration
`aisuite` calls require a concrete model string. There is no useful project-side "factory default" if no model is configured.

Model resolution order:

1. Request-level `model`, currently sent only if `window.__lodeRunnerAgentOptions.model` is set in the browser. This preserves the legacy explicit-model override.
2. Request-level `modelProfile`, sent from `window.__lodeRunnerAgentOptions.modelProfile` or `?profile=...`.
3. `AGENT_MODEL_PROFILE`.
4. `AGENT_DEFAULT_MODEL`.

Request-level `model` and `AGENT_DEFAULT_MODEL` must use `provider:model` format, for example `openai:gpt-4.1-mini`. Bare model names are rejected for generic/default model selection.

Before each backend planning request, the server reconciles dotenv files so local model-profile changes are picked up without restarting Flask. Load order is:

1. `~/.env`
2. `<repo>/.env`
3. `~/.env.local`
4. `<repo>/.env.local`

Later files override earlier files. Removed dotenv-managed keys are also cleared or restored to their original process value. This means `.env.local` is the preferred place for quick local switching, for example moving `AGENT_MODEL_PROFILE=gemini` or `AGENT_MODEL_PROFILE=minimax` out of the shared/base `.env`.

The only documented agent URL parameter is `?profile=openai|minimax|gemini`. The older `?agentModelProfile=...` spelling remains a backward-compatible alias.

Supported profiles:

- `openai`: uses `OPENAI_MODEL`, plus `OPENAI_API_KEY` and optional `OPENAI_BASE_URL`.
- `minimax`: uses native `aisuite` MiniMax provider from pinned PR commit `4b07ed91ef8a8fdcccb6a7a89823d38386c54f82`, with `MINIMAX_MODEL`, `MINIMAX_API_KEY`, and optional `MINIMAX_BASE_URL` or `MINIMAX_API_BASE`.
- `gemini`: uses the `aisuite` OpenAI provider with Google AI Studio's OpenAI-compatible endpoint, with `GEMINI_MODEL`, `GEMINI_API_KEY`, and optional `GEMINI_API_BASE`.

The current `aisuite` `google:` provider is Vertex AI based and requires Google Cloud project credentials. The project therefore routes Gemini profile calls through Gemini's OpenAI-compatible endpoint instead of `google:`.

In the current local setup, model env vars are expected to come from the user-level environment, such as `~/.env` loaded by local shell bootstrap scripts.

If no model can be resolved, `/api/agent/next-action` returns a configuration error instead of attempting a model call.

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
GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...

# No profile: explicit provider prefix is required.
AGENT_DEFAULT_MODEL=openai:gpt-4.1-mini
OPENAI_API_KEY=...
```

Runtime tuning in [agent/config.py](../agent/config.py):

- `AGENT_MAX_TICKS` clamps a single translated candidate action. It limits how many manual legacy ticks the browser advances for one backend decision.
- `AGENT_TEMPERATURE` is passed to the `aisuite` chat completion call. Raising it can make candidate selection more varied, but the model still chooses only from backend-generated candidate IDs.

## Runtime Flow
One AI solve attempt spans many backend requests:

1. [src/agent.js](../src/agent.js) starts Classic level 1 through [public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js).
2. The hook starts the legacy game in Training/Modern playback context, stops the normal ticker, and exposes manual `snapshot()` / `step()` control.
3. The browser sends `playData`, `level`, `snapshot`, `history`, `runId`, optional `model`, and optional `modelProfile` to `/api/agent/next-action`.
4. [app.py](../app.py) validates the request and calls `plan_next_action()`.
5. [agent/service.py](../agent/service.py) resolves the model and orchestrates candidate planning.
6. [agent/candidates.py](../agent/candidates.py), [agent/reasoning_tools.py](../agent/reasoning_tools.py), and [agent/stall_tools.py](../agent/stall_tools.py) analyze the snapshot/history and produce ranked candidates.
7. [agent/prompt.py](../agent/prompt.py) asks the LLM to choose one candidate by ID.
8. The backend validates the selected candidate, applies stall retry/fallback logic if needed, and returns one bounded legacy action.
9. The browser steps the legacy runtime and repeats until success, failure, cancellation, or the iteration limit.
10. [src/agent.js](../src/agent.js) saves the final successful or failed demo through the recording API.

## Backend Module Map
Current backend agent modules:

- [agent/config.py](../agent/config.py): constants, allowed keycodes, model normalization, default model lookup.
- [agent/service.py](../agent/service.py): request validation, `aisuite` client wrapper, model call, candidate selection orchestration, retry/fallback handling.
- [agent/candidates.py](../agent/candidates.py): normalized analysis and candidate generation/ranking.
- [agent/reasoning_tools.py](../agent/reasoning_tools.py): deterministic snapshot helpers for movement, guard pressure, digging, route access, and progress facts.
- [agent/stall_tools.py](../agent/stall_tools.py): deterministic oscillation/loop/stall detection and recovery hints.
- [agent/prompt.py](../agent/prompt.py): compact candidate-selection prompt.
- [agent/traces.py](../agent/traces.py): trace serialization and compact snapshot summaries.
- [agent/errors.py](../agent/errors.py): request/config/execution error types.
- [agent/logging_utils.py](../agent/logging_utils.py): low-noise Python logging setup.

## Candidate Model
The LLM no longer invents raw keycodes. It selects one backend-generated candidate.

Candidate fields include:

- `id`
- `kind`
- `label`
- `goal`
- `target`
- `firstAction`
- `score`
- `risk`
- `reason`
- stall metadata such as `stallBlocked` or `stallRecovery`

Typical candidate kinds:

- `collect_same_row_gold`
- `align_ladder`
- `climb_ladder`
- `route_access_dig`
- `route_access_follow`
- `descend_route`
- `continue_fall`
- `defensive_dig`
- `retreat_from_guard`
- `godmode_progress`
- `exit_ladder_route`
- `wait_or_stop`

The prompt output contract is strict JSON:

```json
{ "candidateId": "collect_gold_17_14_right", "reason": "Nearest same-row gold is reachable by moving right." }
```

The backend rejects unknown candidate IDs. If the model fails to choose a usable candidate, the service can retry once or fall back to the highest-ranked non-blocked candidate, with trace metadata showing `fallbackUsed`.

## Stall Supervisor
V2 avoids V1's open-ended raw-action guardrail sprawl, but it still needs deterministic stall tooling. Persistent loops are handled by [agent/stall_tools.py](../agent/stall_tools.py), not by asking the model to call tools.

The stall supervisor can classify:

- `horizontal_oscillation`
- `vertical_ladder_oscillation`
- `same_candidate_no_progress`
- `same_tile_no_progress`
- `route_access_loop`
- `exit_ladder_loop`
- `wait_loop`

The resulting `stallReport` can:

- block specific candidate IDs, kinds, or directions
- boost recovery candidates
- add a compact prompt note
- trigger one retry if the model picks a blocked candidate
- fall back to the highest-ranked non-blocked candidate
- fail early if no recovery candidate exists

This keeps the default runtime deterministic and traceable while still addressing looping behavior.

## Prompting
[public/AGENT_RULES.md](../public/AGENT_RULES.md) contains durable gameplay policy. [agent/prompt.py](../agent/prompt.py) focuses on current state, candidate options, optional stall report, and the strict JSON output contract.

The V2 prompt is intentionally smaller than the older prompt. It prefers object-centric state and candidate targets over asking the model to parse the full 28x16 board every step.

The model should reason over the supplied candidates, not generate raw moves. Candidate legality, movement feasibility, dig feasibility, god-mode behavior, and route-access opportunities are computed before the model call.

## API Surface
### `POST /api/agent/next-action`
Runtime planning endpoint.

Request fields:

- `playData`
- `level`
- `snapshot`
- `history`
- optional `runId`
- optional `model`
- optional `modelProfile`

Current limits:

- only Classic `playData=1`, `level=1`
- only `runMode="single"` if `runMode` is supplied
- no current benchmark mode
- no current benchmark-model request handling

Response fields include:

- `action`
- `planner`
- `traceId`
- `stepCount`
- `candidateId`
- `candidate`
- `candidates`

### `GET /api/agent/traces/<trace_id>`
Returns the retained agent trace.

### `GET /api/agent/runs/<playData>/<level>`
Returns latest run metadata and the saved recording for that level if present.

## Trace and Recording Storage
Current stores:

- [__data1/recordings.json](../__data1/recordings.json): replayable user and agent demos.
- [__data1/agent-traces.json](../__data1/agent-traces.json): latest retained agent trace.

Trace retention is intentionally shallow. A new run replaces the previous retained trace. Recordings keep only the latest record for each `playData` / `level` slot.

Trace steps are candidate-centric and include:

- compact snapshot summary
- `primaryProgressTarget`
- `stallReport`
- generated candidates
- selected candidate
- translated action
- validation/retry/fallback outcome
- model profile/provider metadata

Recordings reference traces with `traceRef` and can include solver metadata such as source, result, model, provider, failure reason, and trace ID.

## What Is Not Current Runtime Behavior
These older design ideas are not part of the current V2 runtime:

- raw `keyCode` / `ticks` generation by the LLM
- default `aisuite` tool-calling loops
- runtime multi-model benchmarking
- browser-side model comparison UI
- Python-side game simulation
- few-shot demo-path prompting
- full deterministic pathfinding

Those ideas may still be useful later, but the current implementation deliberately keeps the LLM's job narrow: choose the best candidate from a short backend-generated list.
