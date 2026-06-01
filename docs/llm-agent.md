# LLM Candidate Agent

## Summary
The AI agent is a browser-driven loop with a backend candidate planner. The browser and legacy runtime execute the game; the backend selects one short action at a time. Current scope: Classic `playData=1`, `level=1`.

## Browser Loop
`src/agent.js`:

- starts Classic level 1 through `window.lodeRunnerAgentHooks.startLevel(1, 1)`;
- captures `snapshot()` from the legacy runtime;
- sends snapshot/state/summary, history, and run id to `POST /api/agent/next-action`;
- applies returned `{ keyCode, ticks }` through `step()`;
- stops on success, failure, cancellation, `public/agent-config.json` `agent.maxPlaybackTimeSeconds`, or `agent.maxSteps`;
- saves success and failure demos through the recording API.

The active red `AI` rail button aborts the current run.
The browser also reads `agent.historyLimit`, `agent.playData`, `agent.level`, and optional `agent.modelProfile` from `public/agent-config.json` before each new AI run.

### Legacy Hook Surface
`public/game/lodeRunner.agentHooks.js` exposes:

- `startLevel(playData, level)`
- `step(keyCode, ticks)`
- `snapshot()`
- `stop({ resumeTicker })`
- `getRecordedDemo()`
- `dumpFailure(reason)`
- `isSupportedContext(playData, level)`

The hook starts the existing Training/Modern flow, stops the normal ticker, preserves god mode when enabled, and lets the wrapper advance the game manually.

## Snapshot Structure
`src/agent.js` calls `window.lodeRunnerAgentHooks.snapshot()` before each backend planning request and sends the returned object to `POST /api/agent/next-action`.

Inside `public/game/lodeRunner.agentHooks.js`, `snapshotTerrainGrid()` reads the legacy structural layer `map[x][y].base` and converts each tile through `terrainChar(cell.base)`. It is the structural terrain view, not the live actor/objective view.

Important snapshot fields:

- `dimensions`: fixed Classic level dimensions, currently `{ "width": 28, "height": 16 }`.
- `playData` and `level`: current legacy level context.
- `gameStateName`: readable legacy state such as `running`, `finish`, or `runner_dead`.
- `tick`, `time`, and `timing`: legacy recording tick and gameplay time.
- `godMode`: whether legacy god mode is active for this run.
- `runner`: runner coordinates, offsets, current action, and centered/offset summary.
- `guards`: guard coordinates, offsets, action, gold-carrying state, and same-row relation to the runner.
- `gold`: visible gold coordinates, guard-carried gold, remaining count, and completion state.
- `terrainGrid`: structural grid with visible gold, guards, and runner removed.

`terrainGrid` uses `(0,0)` at the top-left. Each row is exactly 28 characters, `x` increases right, and `y` increases down. Visible gold, guards, and runner are represented separately in `gold`, `guards`, and `runner`.

Tile legend:

- space: empty
- `#`: diggable brick
- `@`: solid non-diggable brick
- `H`: visible ladder
- `-`: rope
- `S`: hidden exit ladder in the raw snapshot
- `X`: trap/false brick

Classic `playData=1`, `level=1` sample:

```json
[
  "                  S         ",
  "                  S         ",
  "#######H#######   S         ",
  "       H----------S         ",
  "       H    ##H   #######H##",
  "       H    ##H          H  ",
  "       H    ##H          H  ",
  "##H#####    ########H#######",
  "  H                 H       ",
  "  H                 H       ",
  "#########H##########H       ",
  "         H          H       ",
  "         H----------H       ",
  "    H######         #######H",
  "    H                      H",
  "############################"
]
```

## Backend Planner
`agent/service.py` validates the request, resolves the model, generates candidates, calls the model, validates the selected candidate, applies stall retry/fallback behavior, and assembles the trace step.

The model chooses a candidate id:

```json
{ "candidateId": "climb_ladder_27_14_up", "reason": "Standing on the ladder, climb to change rows." }
```

The backend translates it into a legacy action for the current step:

```json
{ "keyCode": 38, "ticks": 6, "reason": "..." }
```

## Candidate Generation
`agent/candidates.py` turns the live snapshot and recent action history into a compact set of backend-generated choices. The model chooses only from these choices; it does not invent key codes.

The first step is `analyze_state(snapshot, history)`, which normalizes:

- runner position and movement state;
- guard positions and risk;
- visible and guard-carried gold;
- `goldComplete`;
- `godMode`;
- movement and dig feasibility;
- ladder, rope, terrain, and route affordances;
- recent history and stall report.

The generated candidate shape is:

```json
{
  "id": "collect_same_row_gold_17_14_right",
  "kind": "collect_same_row_gold",
  "goal": "Collect same-row gold at (17,14).",
  "target": { "x": 17, "y": 14, "tile": "$" },
  "firstAction": { "keyCode": 39, "ticks": 8, "reason": "same-row gold is 3 tiles to the right" },
  "risk": "none",
  "reason": "same-row gold is 3 tiles to the right"
}
```

Candidate ids are deterministic and descriptive. Most ids combine kind, target coordinate, and first action, such as `align_ladder_27_14_right` or `climb_ladder_27_14_up`.

Candidate kinds:

- `collect_same_row_gold`: move left/right toward visible same-row gold.
- `climb_ladder`: climb up/down when already on an active ladder.
- `align_ladder`: move horizontally to a visible same-row ladder.
- `route_access_dig`: dig a legal access hole toward lower off-row gold.
- `route_access_follow`: move into an already opened access route.
- `continue_fall`: keep falling or drop from a rope toward lower gold.
- `descend_route`: move down when down is valid and remaining gold is below.
- `defensive_dig`: dig a trap under non-god-mode guard pressure.
- `retreat_from_guard`: move or climb away from high/critical same-row guard danger in non-god mode.
- `godmode_progress`: move through non-lethal guard contact toward gold or ladder progress in god mode.
- `exit_ladder_route`: route to or climb the revealed `S` exit ladder after `goldComplete=true`.
- `wait_or_stop`: low-score fallback when no better progress/safety candidate exists.

Generation rules:

- `add(...)` normalizes each `firstAction`, clamps ticks to `public/agent-config.json` `backend.maxActionTicks`, rejects physically invalid first actions, deduplicates ids, and applies stall score adjustments.
- Candidate scoring is heuristic. Higher scores go first, then ids break ties. The prompt receives the top `backend.candidateLimit` candidates.
- `prompt.showCandidateScores` controls whether numeric scores are visible to the model. Scores are always retained in traces and debug output.
- uses the stall report to suppress or penalize loop candidates and boost recovery candidates.
- Only legal first actions should be emitted. Legality comes from movement and dig affordances in `agent/reasoning_tools.py`.
- Before gold completion, gold collection and route progress dominate. After gold completion, exit-ladder routing dominates.
- In god mode, guard contact is non-lethal, so progress candidates outrank survival spacing unless terrain physically blocks movement.
- Candidate coverage is empirical: if a failure trace lacks the correct first action, add or refine candidate generation; if the correct candidate exists but is not chosen, adjust scoring, stall handling, or prompt selection. See `docs/candidate-design.md` for the design notes.

## Prompt Format
`public/AGENT_RULES.md` contains short durable gameplay priorities. `agent/prompt.py` formats one candidate-selection prompt per backend decision.

The prompt tells the model:

- the backend already checked candidate legality, movement feasibility, dig feasibility, god-mode behavior, and route-access opportunities;
- it must choose one candidate id from the provided list;
- it must not invent key codes, actions, or alternate moves;
- it must return JSON only.

Required model output:

```json
{ "candidateId": "candidate_id_here", "reason": "brief explanation" }
```

Prompt sections:

- compact state summary;
- primary progress target;
- candidate list;
- optional stall report;
- recent behavior tail;
- optional retry instruction;
- strict JSON output contract.

The state summary includes current context, runner coordinate/action/offset, remaining visible gold, primary progress target, guard risk, movement booleans, ladder detail, route-access detail, and compact stall status.

The candidate list shown to the model includes each id, kind, risk, translated first action, optional target, goal, reason, and stall annotations. If `prompt.showCandidateScores=true`, it also includes numeric `score=...` as a priority hint. Candidate-level `reason` is generated by backend candidate logic; `firstAction.reason` is the same reason normalized for execution/tracing.

If a stall is active, the prompt includes the stall type, recent positions, recent candidate ids, blocked candidates/kinds, preferred recovery kinds, ladder direction restrictions, and recovery hint. The model is explicitly told not to choose blocked candidates when severity is `stalled`.

The prompt does not ask the model to parse the full board `terrainGrid` or invent raw key events during normal runtime. The board has already been reduced into structured state and candidates.

## Stall Handling
`agent/stall_tools.py` is the deterministic supervisor around candidate generation and selection. It does not replace the candidate planner; it detects repeated non-progress patterns, penalizes bad repeats, and provides recovery guidance.

`build_stall_report(analysis, history)` looks at the last 10 history entries and derives:

- recent runner positions from each action's `after.runner`;
- recent gold counts;
- recent candidate ids;
- recent key codes;
- row changes, x-range, direction changes, same-tile streak, and same-candidate streak.

Detected stall types:

- horizontal oscillation;
- vertical ladder oscillation;
- same candidate or same tile with no progress;
- route-access dig loop;
- exit-ladder loop;
- wait loop.

Severity values:

- `none`: no stall signal.
- `watch`: early warning, such as repeated candidates or bounded motion that is not yet a hard stall.
- `stalled`: confirmed loop/non-progress pattern.

The stall report includes:

- `recentPositions`, `recentCandidateIds`, and `recentKeyCodes`;
- `recentXRange` and `directionChanges`;
- `sameTileStreak` and `sameCandidateStreak`;
- blocked candidate ids/kinds;
- blocked ladder directions for vertical ladder oscillation;
- preferred recovery candidate kinds;
- optional oscillation target and recovery hint.

The resulting `stallReport` can:

- block specific candidate IDs, kinds, or directions
- boost recovery candidates
- add a compact prompt note
- trigger one retry if the model picks a blocked candidate
- fall back to the highest-ranked non-blocked candidate
- fail early if no recovery candidate exists

This keeps the default runtime deterministic and traceable while still addressing looping behavior.

Candidate integration:

- `score_adjustment(...)` subtracts score from blocked candidates.
- Preferred recovery kinds get a score boost.
- `wait_or_stop` is heavily penalized during confirmed stalls.
- Some repeated route-access candidates are suppressed before emission.
- Horizontal oscillation recovery allows repeated committed progress candidates such as `align_ladder`; reaching a ladder often requires repeating the same direction for several steps.

Service integration:

- If the model selects a blocked candidate, `agent/service.py` retries once with a concise stall-aware instruction.
- If the retry still selects a blocked candidate, the service falls back to the highest-ranked non-blocked candidate and marks fallback metadata in the trace.
- If no candidate can be safely selected, the backend fails the step so the browser saves a debugging failure recording instead of burning the run limit.

Trace integration:

- run-level `model` stores the resolved model/profile/provider for the trace;
- run-level `config` stores the public agent config used for the trace;
- `step.state` mirrors the prompt's current-state facts for playback/debug alignment.
  - `gameState`, `tick`, `godMode`
  - compact `runner`, `gold`, `primaryProgressTarget`, and `guardRisk`
  - movement booleans only, not movement target/details
  - ladder detail string and route-access summary

- `step.stallSupervisor` stores stall severity/type, blocked candidates, preferred recovery kinds, retry status, and fallback-after-retry metadata.
- `step.validation` stores the selected candidate's stall validation result, including whether the accepted candidate was stall-blocked before retry/fallback.

## God Mode
God mode is the legacy `godMode` global toggled by `SHIFT-G`, `CTRL-Z`, or the wrapper star button.  Saved demos include legacy god-mode state through normal demo recording data.

If god mode is enabled before clicking `AI`, candidate generation treats guard contact as non-lethal, ranks progress over survival-only spacing, and still rejects physically impossible moves.
