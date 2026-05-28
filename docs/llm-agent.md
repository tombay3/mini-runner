# LLM Candidate Agent

## Summary
The AI agent is a browser-driven loop with a backend candidate planner. The browser and legacy runtime execute the game; the backend selects one short action at a time.

Current scope: Classic `playData=1`, `level=1`.

## Browser Loop
`src/agent.js`:

- starts Classic level 1 through `window.lodeRunnerAgentHooks.startLevel(1, 1)`;
- captures `snapshot()` from the legacy runtime;
- sends snapshot, history, and run id to `POST /api/agent/next-action`;
- applies returned `{ keyCode, ticks }` through `step()`;
- stops on success, failure, cancellation, 2 minutes of legacy gameplay time, or 200 backend decisions;
- saves success and failure demos through the recording API.

The active red `AI` rail button aborts the current run.

## Legacy Hook Surface
`public/game/lodeRunner.agentHooks.js` exposes:

- `startLevel(playData, level)`
- `step(keyCode, ticks)`
- `snapshot()`
- `stop({ resumeTicker })`
- `getRecordedDemo()`
- `dumpFailure(reason)`
- `isSupportedContext(playData, level)`

The hook starts the existing Training/Modern flow, stops the normal ticker, preserves god mode when enabled, and lets the wrapper advance the game manually.

## Backend Planner
`agent/service.py` validates the request, resolves the model, generates candidates, calls the model, validates the selected candidate, applies stall retry/fallback behavior, and assembles the trace step.

The model chooses a candidate id:

```json
{ "candidateId": "climb_ladder_27_14_up", "reason": "Standing on the ladder, climb to change rows." }
```

The backend translates it into a legacy action:

```json
{ "keyCode": 38, "ticks": 6, "reason": "..." }
```

## Candidate Generation
`agent/candidates.py` ranks legal candidates from snapshot facts:

- runner position and movement state;
- guard positions and risk;
- visible and guard-carried gold;
- `goldComplete`;
- `godMode`;
- movement and dig feasibility;
- ladder, rope, terrain, and route affordances;
- recent history and stall report.

Candidate kinds include same-row gold collection, ladder alignment/climbing, route-access digging/following, descent, defensive digging, guard retreat, god-mode progress, exit routing, and wait/stop fallback.

Only physically valid first actions should be emitted.

## Prompt Format
`public/AGENT_RULES.md` contains short gameplay priorities. `agent/prompt.py` formats:

- compact state summary;
- primary progress target;
- candidate list;
- optional stall report;
- strict JSON output contract.

The prompt does not ask the model to parse the full board or invent raw key events during normal runtime.

## Stall Handling
`agent/stall_tools.py` detects repeated non-progress patterns:

- horizontal oscillation;
- vertical ladder oscillation;
- same candidate or same tile with no progress;
- route-access dig loop;
- exit-ladder loop;
- wait loop.

The stall report can block repeated candidates, boost recovery candidates, add a retry note, and fall back to the highest-ranked non-blocked candidate.

## God Mode
God mode is a legacy feature toggled by `SHIFT-G`, `CTRL-Z`, or the wrapper star button. The source of truth is the legacy `godMode` global.

If god mode is enabled before clicking `AI`, `startLevel()` restores it after the legacy start path resets hotkey state. Candidate generation treats guard contact as non-lethal, ranks progress over survival-only spacing, and still rejects physically impossible moves.

Saved demos include legacy god-mode state through normal demo recording data.

## Recording
The legacy runtime records demos. The wrapper persists final agent results with:

- `source: "agent"`;
- `result: "success"` or `"failure"`;
- `traceId`;
- `solver` model metadata;
- `demo`.

Failed runs are saved intentionally for debugging.
