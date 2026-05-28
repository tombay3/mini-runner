# LLM Candidate Agent

## Summary
The current Lode Runner agent is an interactive browser-driven loop with a V2 candidate planner on the backend.

The legacy game remains the executor and recorder. The backend does not simulate Lode Runner. It only selects one short action at a time for Classic `playData=1`, `level=1`.

## Browser Loop
[src/agent.js](../src/agent.js) owns the outer solve loop:

- starts Classic level 1 through `window.lodeRunnerAgentHooks.startLevel(1, 1)`.
- captures `snapshot()` from the legacy runtime.
- sends snapshot/history/run ID to `/api/agent/next-action`.
- applies the returned `{ keyCode, ticks }` through `step()`.
- stops on success, failure, cancellation, or 2 minutes of legacy playback/game time.
- cancels the current run if the active red `AI` rail button is clicked again.
- saves both success and failure demos through `/api/recordings/1/1`.

Current frontend limits:

- `AGENT_MAX_PLAYBACK_TIME = 2 * 60`.
- Playback time is checked against both legacy visible `gameTime >= 120` and recorded-demo ticks `recordTick >= 1920`.
- `AGENT_MAX_STEPS = 200` as an emergency safety guard if legacy time stops advancing.
- `AGENT_HISTORY_LIMIT = 24`.
- optional model override via `window.__lodeRunnerAgentOptions.model`.
- optional profile override via `window.__lodeRunnerAgentOptions.modelProfile` or `?profile=...`.
- `?profile=...` is the only documented agent URL parameter; `?agentModelProfile=...` remains a backward-compatible alias.

Current backend tuning:

- `AGENT_MAX_TICKS = 20` clamps one returned candidate action to at most 20 legacy manual ticks.
- `AGENT_TEMPERATURE` controls LLM sampling for candidate selection; lower values are more deterministic, higher values can explore less-obvious candidates.
- dotenv files are reconciled before backend planning requests, so `.env.local` model-profile changes or removals are picked up on the next AI run without restarting Flask.

## Legacy Hook Surface
[public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js) exposes:

- `startLevel(playData, level)`
- `step(keyCode, ticks)`
- `snapshot()`
- `stop({ resumeTicker })`
- `getRecordedDemo()`
- `dumpFailure(reason)`
- `isSupportedContext(playData, level)`

`startLevel()` runs Classic level 1 through the existing Training/Modern flow, stops the normal ticker, preserves god mode if it was enabled before AI entry, and lets the wrapper advance the game manually.

## Backend Planner
[agent/service.py](../agent/service.py) orchestrates:

1. request validation
2. model resolution through `aisuite`
3. candidate generation
4. candidate-selection prompt
5. selected-candidate validation
6. stall retry/fallback handling
7. trace assembly

The LLM returns a candidate ID, not raw keycodes:

```json
{ "candidateId": "climb_ladder_27_14_up", "reason": "Standing on the row-14 ladder, climb to change route." }
```

The backend translates that candidate into the legacy action returned to the browser:

```json
{
  "action": { "keyCode": 38, "ticks": 6, "reason": "..." },
  "candidateId": "climb_ladder_27_14_up",
  "traceId": "..."
}
```

## Candidate Generation
[agent/candidates.py](../agent/candidates.py) generates a small ranked list from normalized snapshot facts:

- runner position and movement state
- guard positions and risk
- visible gold and guard-carried gold
- `goldComplete`
- `godMode`
- movement feasibility
- dig feasibility
- current ladder/rope/terrain affordances
- recent history
- stall report

Candidate kinds include:

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

Only physically valid first actions should be emitted.

## Stall Handling
Persistent loops are handled by deterministic stall tooling in [agent/stall_tools.py](../agent/stall_tools.py).

Detected patterns include:

- horizontal oscillation
- vertical ladder oscillation
- same candidate with no progress
- same tile with no progress
- route-access dig loop
- exit-ladder loop
- wait loop

The stall report can block repeated candidates, boost recovery candidates, add a retry note to the prompt, and trigger fallback to the highest-ranked non-blocked candidate.

## Prompting
[public/AGENT_RULES.md](../public/AGENT_RULES.md) contains short durable gameplay policy.

[agent/prompt.py](../agent/prompt.py) formats the current candidate-selection prompt. The prompt is intentionally compact:

- current state summary
- progress target
- candidate list
- optional stall report
- strict JSON output contract

The model is not asked to parse the full board or invent raw input bursts in normal V2 runtime.

## Model Configuration
The backend uses `aisuite` for provider/model abstraction.

Model resolution order:

1. request-level `model`
2. request-level `modelProfile`
3. `AGENT_MODEL_PROFILE`
4. `AGENT_DEFAULT_MODEL`

Supported profiles:

- `openai`
- `minimax`
- `gemini`

Request-level `model` and `AGENT_DEFAULT_MODEL` must use `provider:model` format, for example `openai:gpt-4.1-mini`. Profile-specific variables such as `OPENAI_MODEL`, `MINIMAX_MODEL`, and `GEMINI_MODEL` do not use provider prefixes. Missing model/profile config returns a backend configuration error.

## Recording
The legacy runtime records the demo. The wrapper only persists the final `curDemoData`.

Saved agent recordings include:

- `source: "agent"`
- `result: "success"` or `"failure"`
- `solver`
- `traceId`
- `demo`

The recording `solver` stores logical model metadata such as `modelProfile`, `provider`, `model`, `responseId`, `traceId`, and optional `failureReason`. Obsolete transport fields such as `aisuiteProvider` / `aisuiteModel` are not stored in recordings.

Failed runs are saved intentionally for debugging.
