# LLM Candidate Agent

## Summary
The AI agent is a browser-driven loop with a backend candidate planner. The browser and
legacy runtime execute the game; the backend selects one short action at a time. Current
scope is Classic `playData=1`, `level=1`.

## Browser Loop
`src/agent.js`:

- starts Classic level 1 through `window.lodeRunnerAgentHooks.startLevel(1, 1)`;
- captures `snapshot()` from the legacy runtime;
- sends snapshot/state/summary, history, and run id to `POST /api/agent/next-action`;
- applies returned `{ keyCode, ticks }` through `step()`;
- stops on success, failure, cancellation, `public/agent-config.json` `agent.maxPlaybackTimeSeconds`, or `agent.maxSteps`;
- saves success and failure demos through the recording API.

The final recording request also sends a compact terminal snapshot. The backend attaches it
to the linked trace as `outcome.finalState`, including all guard positions and offsets. This
is intentionally richer than ordinary per-step trace state because the final action has no
following planning request from which its post-action state could otherwise be recovered.
The hook captures this snapshot at `finish` or `runner_dead` before advancing the extra tick
required to finalize the legacy demo, preserving the actual collision or completion geometry.

The active red `AI` rail button aborts the current run.
The browser also reads `agent.historyLimit`, `agent.playData`, `agent.level`, and optional `agent.modelProfile` from `public/agent-config.json` before each new AI run.

### Legacy Hook Surface
`public/game/lodeRunner.agentHooks.js` exposes:

- `startLevel(playData, level)`
- `step(keyCode, ticks)`
- `snapshot()`
- `stop({ resumeTicker })`
- `getRecordedDemo()`
- `getTerminalSnapshot()`
- `dumpFailure(reason)`
- `isSupportedContext(playData, level)`
- `isReady()`

The hook starts the existing Training/Modern flow, stops the normal ticker, preserves god mode when enabled, and lets the wrapper advance the game manually.
`isReady()` becomes true only after the legacy CreateJS asset queue has completed; automated
and manual starts use it to avoid racing `startGame()` against incomplete legacy objects.
Before constructing Classic level 1, `startLevel()` also cancels the cover-page idle-demo
timer and any existing game ticker. This prevents asynchronous demo mode from changing the
level or tick timeline while the backend is deciding.

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
- `activeDig`: the in-progress legacy dig target and animation frame state before it becomes an open hole.
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

The model chooses a candidate id and never supplies raw key codes:

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
- guard positions, relative side, current motion, closing state, and risk;
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
- `collect_current_tile_gold`: center a partially offset runner on gold sharing its grid coordinate without crossing an adjacent open hole.
- `climb_ladder`: climb up/down when already on an active ladder.
- `align_ladder`: move horizontally to a visible same-row ladder.
- `route_access_dig`: dig a legal access hole toward lower off-row gold.
- `route_access_follow`: move into an already opened access route.
- `wait_for_guard_clearance`: pause briefly when a guard can intercept an opened access drop, then reassess before entering.
- `wait_for_floor_refill`: advance a required dug brick's legacy refill timer while holding on its safe side; the candidate id includes refill frame/time so timed environmental progress is not mistaken for a runner stall. During exit routing, direction comes from the fixed Classic row waypoint rather than a gold target.
- `wait_for_dig_completion`: advance an already-started legacy dig in two-tick increments; its frame-signatured id bridges the animation interval before the target appears in `openHoles`. While `activeDig` is present, this is the exclusive candidate so movement cannot cross a hole that opens mid-action.
- `wait_for_trap_resolution`: hold when an existing nearby open hole already separates the same-row pressure guard; poll at eight ticks when far, four at medium range, and two during immediate falling geometry so safety remains responsive without exhausting the decision cap. The backend makes this state exclusive so model selection cannot abandon a safe established trap for a route-changing action. A same-row guard beginning `up`/`climb_out` no longer counts as separated, which restores physical escape candidates before contact.
- `classic_upper_gold_route`: when `(23,3)` is the remaining visible target, commit to the Classic ladder chain through `x=20` on the middle rows and `x=25` on rows 4–6 instead of oscillating between nearer left ladders.
- `classic_lower_gold_route`: when a dropped/visible gold is on row 14, follow the reverse Classic descent entries at `x=25`, `x=20`, and `x=27`; for the left-side gold at `(7,12)`, rows 9–11 commit to the x=20 descent ladder instead of oscillating at the dead-end x=2 ladder. These routes include below-row ladder entries that ordinary same-row ladder discovery cannot see.
- `finish_exit_climb`: at `(18,0)` with a positive vertical offset, continue upward through the final sub-tile distance even though tile-level `canMoveUp` is false at the map boundary.

After `goldComplete`, deterministic `exit_ladder_route` climbs use the legacy 20-tick action ceiling. Horizontal exit alignment scales to the remaining tile distance, capped at 20 ticks, so it keeps the decision-count benefit without repeatedly overshooting a nearby waypoint.
- `continue_fall`: keep falling or drop from a rope toward lower gold.
- `descend_route`: move down when down is valid and remaining gold is below.
- `defensive_dig`: dig a trap under non-god-mode guard pressure.
- `retreat_from_guard`: move or climb away from medium/high/critical guard danger in non-god mode, including adjacent-row pressure.
- At an edge ladder, a legal defensive trap against a closing same-row guard takes precedence over descending, because the progress route would immediately climb back into the unchanged pressure state.
- `cross_row_pressure_hold`: a two-tick emergency hold used only when a high/critical guard is on another row and every ordinary candidate has been filtered out; its id tracks guard geometry so each changed safety state is reassessed.
- `escape_through_open_hole`: under high/critical pressure, or when a closing same-row medium guard has driven the runner to an adjacent opening on the retreat side, intentionally enter that dug opening above the bottom terrain boundary to change rows and break contact. It is withheld when a guard occupies or borders either the open-hole row or the landing row, because a climbing or horizontally moving guard can cross the descent lane. Ordinary movement candidates—and every bottom-boundary hole—remain prohibited.
- When guards have equal risk, same-row pressure takes precedence over cross-row pressure so retreat and digging are oriented against the imminent collision. Explicit legacy `openHoles` entries block ordinary horizontal actions even when the active terrain grid temporarily obscures the hole, except while a guard is fully `in_hole` and temporarily supports crossing that cell. A supported hole is not considered a separating trap for another guard, because that guard can cross it too; exclusive trap waiting ends and guard-safe movement is restored.
- At a horizontal edge, a nearby below-row guard moving onto the runner's ladder column triggers a short inward step before defensive digging, preventing the guard from climbing directly into a stationary runner.
- A centered runner at a horizontal edge may prepare a defensive trap for a closing same-row guard at distance five. The one-tile extension applies only at the edge, where ordinary retreat would leave the runner off-center before the general distance-four trap window opens.
- When one adjacent floor is already an empty open hole and a cross-row guard is not closing, `evade_open_hole` takes a short step onto the solid side instead of digging a second hole and boxing the runner between two traps.
- That solid-side escape is suppressed when it points toward a nearby guard descending onto the runner's row. If the runner is centered and the landing-side brick is engine-diggable, a proactive `defensive_dig` trap is offered before same-row contact; off-center dig commands are rejected because the legacy engine cannot start them reliably.
- `godmode_progress`: move through non-lethal guard contact toward gold or ladder progress in god mode.
- `exit_ladder_route`: route to or climb the revealed `S` exit ladder after `goldComplete=true`.
- `wait_or_stop`: low-score fallback when no better progress/safety candidate exists.
- `emergency_hold`: final two-tick completeness fallback used only when every physical action and ordinary wait has been filtered; it prevents a structural empty-candidate failure while the legacy engine resolves contact.

Generation rules:

- `add(...)` normalizes each `firstAction`, clamps ticks to `public/agent-config.json` `backend.maxActionTicks`, rejects physically invalid or guard-unsafe first actions, deduplicates ids, and applies stall score adjustments.
- In normal mode, candidates toward a same-row medium/high/critical guard are suppressed. Cross-row directional blocking begins at high risk; medium cross-row horizontal progress remains available but is capped at four ticks for quick reassessment. Dig and vertical escape durations are unchanged.
- When a pressure guard is vertically aligned on another row, the generator offers short left/right retreats wherever terrain permits. `cross_row_pressure_hold` is reserved for a genuinely boxed state and is treated as dynamic environment progress while its guard-geometry signature changes.
- The true nearest guard takes precedence over a farther same-row guard when safety is evaluated. Neutral input remains legal while the runner is already falling, because it advances the forced fall and preserves a valid reassessment step when no directional action is physically available.
- Guard state refines geometric risk: `nearestGuard` remains the closest observable guard, while `pressureGuard` is the highest-priority mobile threat used for candidate safety. A guard in `in_hole` state is low immediate pressure until it begins climbing out, so the solver can continue above a contained guard instead of falsely stalling at an edge.
- Defensive digging is emitted only for high/critical pressure or when the dig affordance confirms the guard can fall into that hole. Medium spacing alone no longer creates chains of temporary holes that block the solver's own route.
- The bottom terrain row is never offered for route/access digging. A bottom-row `defensive_dig` is allowed only when the affordance confirms an approaching guard can fall into it; ordinary movement still refuses to enter the resulting inescapable hole.
- Safety checks consider every nearby medium/high/critical same-row guard, not only the nearest pressure guard. When guards pinch from both sides, horizontal moves toward either guard are suppressed and a legal defensive trap receives priority.
- Under high/critical primary pressure, the backend also treats an opposite same-row guard closing from within seven tiles as an imminent pinch even if its current distance risk is still low. Movement toward that guard is filtered before it can leave the runner off-center; a centered defensive trap remains eligible.
- After all gold is collected on Classic level 1, exit routing follows explicit row waypoints through ladder columns `27 → 20 → 25 → 18`. This covers the bottom platform, middle ladder chain, upper ladder, row-3 rope traversal, and revealed `S`; generic nearby-ladder scoring cannot redirect an otherwise safe exit candidate.
- Before following an opened access hole, the backend checks for guards close enough below the hole to intercept the committed fall. An unsafe entry is replaced by a two-tick `wait_for_guard_clearance` candidate whose identity tracks the blocking guard's coordinate and offsets.
- Route access evaluates both left and right dig/follow cells. A guard-clear side outranks the side facing the gold, and dig planning uses a longer interception horizon to account for the dig animation plus the committed fall.
- Horizontal movement also compares structural brick support with the active grid across the action horizon. A burst approaching a temporarily open dug brick is shortened to stop one tile before it; once adjacent, ordinary collection/alignment candidates are withheld until the floor refills. Only `route_access_follow` may intentionally enter that hole.
- Candidate scoring is heuristic. Higher scores go first, then ids break ties. The prompt receives the top `backend.candidateLimit` candidates.
- `prompt.showCandidateScores` controls whether numeric scores are visible to the model. Scores are always retained in traces and debug output.
- uses the stall report to suppress or penalize loop candidates and boost recovery candidates.
- Only legal first actions should be emitted. Legality comes from movement and dig affordances in `agent/reasoning_tools.py`.
- Vertical movement is not legal in normal mode when its adjacent destination tile is
  occupied by a guard. God mode retains the legacy pass-through behavior.
- Before gold completion, gold collection and route progress dominate. After gold completion, exit-ladder routing dominates.
- In god mode, guard contact is non-lethal, so progress candidates outrank survival spacing unless terrain physically blocks movement.
- Candidate coverage is empirical: if a failure trace lacks the correct first action, add or refine candidate generation; if the correct candidate exists but is not chosen, adjust scoring, stall handling, or prompt selection. See `docs/candidate-design.md` for the design notes.

## Prompt Format
`public/LLM_GAME_RULES.md` contains short durable gameplay priorities. `agent/prompt.py` formats one candidate-selection prompt per backend decision.

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

The state summary includes current context, runner coordinate/action/offset, remaining visible gold, primary progress target, guard risk, nearest and pressure guards, nearby guards, nearest same-row guard, movement booleans, ladder detail, route-access interception detail, and compact stall status.

For the nearest same-row guard, `side` means only where the guard is relative to the
runner. `motion` is the guard's current legacy movement action, and `closing` is a
backend-derived boolean. The prompt states this distinction explicitly so `side:left`
cannot be interpreted as “moving left.”

The candidate list shown to the model includes each id, kind, risk, translated first action,
optional target, goal, reason, and stall annotations. If
`prompt.showCandidateScores=true`, it also includes numeric `score=...` as a priority hint.
Candidate-level `reason` is generated by backend candidate logic; `firstAction.reason` is
the same reason normalized for execution/tracing. Scores still determine sorting,
truncation, and fallback when hidden from the prompt.

If a stall is confirmed, the prompt includes the stall type, recent positions, recent candidate ids, blocked candidates/kinds, preferred recovery kinds, ladder direction restrictions, and recovery hint. Preliminary observations remain trace-only and are not shown to the model.

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
- vertical ladder oscillation, including mixed `climb_ladder`/`retreat_from_guard` up-down cycles;
- same candidate or same tile with no progress;
- route-access dig loop;
- exit-ladder loop;
- wait loop.

Severity values:

- `none`: no stall signal.
- `stalled`: confirmed loop/non-progress pattern.

The stall report includes:

- `recentPositions`, `recentCandidateIds`, and `recentKeyCodes`;
- `recentXRange` and `directionChanges`;
- `sameTileStreak` and `sameCandidateStreak`;
- repeated-candidate target, start/end distance, progress, and target-reached status;
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
- `retreat_from_guard` remains available during horizontal oscillation because immediate safety takes precedence over loop suppression. Monotonic repeated retreat is exempt from same-candidate/same-tile stalls so it can reach a finite edge or changed guard geometry; true direction-changing retreat loops remain covered by horizontal-oscillation detection.
- Guard-signature `cross_row_pressure_hold` and `emergency_hold` ids retain their full candidate-kind classification, so bounded environment-resolution waits are not misidentified as ordinary same-tile stalls.
- Repeating a candidate does not trigger a warning while its target distance is decreasing, and reaching the target clears the warning so the next macro action can take over.
- Preliminary repeated-candidate and short-oscillation observations are stored only in `step.stallSupervisor.observations`; they do not affect prompts, scores, validation, retries, or fallback.
- Explicit `wait_for_floor_refill` and `wait_for_guard_clearance` candidates represent environmental progress and are exempt from same-tile runner-stall classification.
- Candidate IDs, kinds, and directions are blocked only for confirmed `stalled` reports.
- A short-tail detector catches recent left/right alternation without waiting for older positions to leave the full 10-action window.

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

- `step.stallSupervisor` stores confirmed stall severity/type and enforcement metadata plus trace-only observations about repeated candidates and short horizontal oscillation.
- `step.validation` stores the selected candidate's stall validation result, including whether the accepted candidate was stall-blocked before retry/fallback.

## God Mode
God mode is the legacy `godMode` global toggled by `SHIFT-G`, `CTRL-Z`, or the wrapper star button.  Saved demos include legacy god-mode state through normal demo recording data.

If god mode is enabled before clicking `AI`, candidate generation treats guard contact as non-lethal, ranks progress over survival-only spacing, and still rejects physically impossible moves.
