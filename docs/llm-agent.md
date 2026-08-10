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
`agent/service.py` validates the request, resolves the model, generates eligible candidates,
calls the model once, applies generic selection validation, and assembles the trace step.

The model chooses a candidate id and never supplies raw key codes:

```json
{ "candidateId": "climb_ladder_27_14_up" }
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
- compact loop report derived from recent history.

The generated candidate shape is:

```json
{
  "id": "collect_same_row_gold_17_14_right",
  "kind": "collect_same_row_gold",
  "score": 100,
  "target": { "x": 17, "y": 14, "tile": "$" },
  "firstAction": { "keyCode": 39, "ticks": 8, "reason": "same-row gold is 3 tiles to the right" }
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
- `wait_for_floor_refill`: advance a required dug brick's legacy refill timer while holding on its safe side; the candidate id includes refill frame/time so timed environmental progress is not mistaken for a stationary repeat. During exit routing, direction comes from the fixed Classic row waypoint rather than a gold target.
- `wait_for_dig_completion`: advance an already-started legacy dig in two-tick increments; its frame-signatured id bridges the animation interval before the target appears in `openHoles`. While `activeDig` is present, this is the exclusive candidate so movement cannot cross a hole that opens mid-action.
- `wait_for_trap_resolution`: hold when an existing nearby open hole already separates the same-row pressure guard; poll at eight ticks when far, four at medium range, and two during immediate falling geometry so safety remains responsive without exhausting the decision cap. The backend makes this state exclusive so model selection cannot abandon a safe established trap for a route-changing action. A same-row guard beginning `up`/`climb_out` no longer counts as separated, which restores physical escape candidates before contact.
- `classic_gold_route`: use the fixed upper, lower, or left-side Classic ladder waypoints when nearest-ladder greed is insufficient.
  On row 1 it also returns to the `x=7` descent entry when the only remaining gold is guard-carried,
  avoiding targetless fallback stops while retaining the rule that carriers are not direct targets.

After `goldComplete`, deterministic `exit_ladder_route` climbs use the legacy 20-tick action ceiling. Horizontal exit alignment scales to the remaining tile distance, capped at 20 ticks, so it keeps the decision-count benefit without repeatedly overshooting a nearby waypoint.
- `descend_route`: move down, drop from a rope, or continue a forced fall toward lower gold.
- `defensive_dig`: dig a trap under non-god-mode guard pressure.
- A centered, legal defensive trap is decisive when a high-risk same-row guard is closing from
  exactly three tiles away. Retreat candidates are withheld in that geometry so model selection
  cannot abandon a prepared capture, including when the guard carries the remaining gold.
- `retreat_from_guard`: move or climb away from medium/high/critical guard danger in non-god mode, including adjacent-row pressure.
- At an edge ladder, a legal defensive trap against a closing same-row guard takes precedence over descending, because the progress route would immediately climb back into the unchanged pressure state.
- `escape_through_open_hole`: under high/critical pressure, or when a closing same-row medium guard has driven the runner to an adjacent opening on the retreat side, intentionally enter that dug opening above the bottom terrain boundary to change rows and break contact. It is withheld when a guard occupies or borders either the open-hole row or the landing row, because a climbing or horizontally moving guard can cross the descent lane. Ordinary movement candidates—and every bottom-boundary hole—remain prohibited.
- When guards have equal risk, same-row pressure takes precedence over cross-row pressure so retreat and digging are oriented against the imminent collision. Explicit legacy `openHoles` entries block ordinary horizontal actions even when the active terrain grid temporarily obscures the hole, except while a guard is fully `in_hole` and temporarily supports crossing that cell. A supported hole is not considered a separating trap for another guard, because that guard can cross it too; exclusive trap waiting ends and guard-safe movement is restored.
- At a horizontal edge, a nearby below-row guard moving onto the runner's ladder column triggers a short inward step before defensive digging, preventing the guard from climbing directly into a stationary runner.
- A centered runner at a horizontal edge may prepare a defensive trap for a closing same-row guard at distance five. The one-tile extension applies only at the edge, where ordinary retreat would leave the runner off-center before the general distance-four trap window opens.
- When one adjacent floor is already an empty open hole and a cross-row guard is not closing, `evade_open_hole` takes a short step onto the solid side instead of digging a second hole and boxing the runner between two traps.
- That solid-side escape is suppressed when it points toward a nearby guard descending onto the runner's row. If the runner is centered and the landing-side brick is engine-diggable, a proactive `defensive_dig` trap is offered before same-row contact; off-center dig commands are rejected because the legacy engine cannot start them reliably.
- `god_mode_progress`: last-resort direct horizontal progress in god mode, emitted only when structured Classic, collection, ladder, access, and descent generation produces no candidate.
- `exit_ladder_route`: route to or climb the revealed `S` exit ladder after `goldComplete=true`.
- `wait_or_stop`: low-score fallback when no better progress/safety candidate exists.
- `emergency_hold`: final two-tick completeness fallback used only when every physical action and ordinary wait has been filtered; it prevents a structural empty-candidate failure while the legacy engine resolves contact.

Generation rules:

- `add(...)` normalizes each `firstAction`, clamps ticks to `public/agent-config.json` `backend.maxActionTicks`, rejects physically invalid or guard-unsafe first actions, deduplicates ids, and removes actions identified by the active loop report.
- In normal mode, candidates toward a same-row medium/high/critical guard are suppressed. Cross-row directional blocking begins at high risk; medium cross-row horizontal progress remains available but is capped at four ticks for quick reassessment. Dig and vertical escape durations are unchanged.
- An adjacent same-row guard moving `up` or `climb_out` also blocks upward movement: following it into its escape lane can recreate immediate contact on the row above. Continuing down remains eligible when terrain permits.
- When a pressure guard is vertically aligned on another row, the generator offers short left/right retreats wherever terrain permits. `emergency_hold` is reserved for a genuinely boxed state and keys its id to guard geometry.
- `pressureGuard` is the highest-priority mobile threat used for candidate safety. Every compact guard uses the same relative-position schema. A guard in `in_hole` state is low immediate pressure until it begins climbing out.
- Defensive digging is emitted only for high/critical pressure or when the dig affordance confirms the guard can fall into that hole. Medium spacing alone no longer creates chains of temporary holes that block the solver's own route.
- The bottom terrain row is never offered for route/access digging. A bottom-row `defensive_dig` is allowed only when the affordance confirms an approaching guard can fall into it; ordinary movement still refuses to enter the resulting inescapable hole.
- Safety checks consider every nearby medium/high/critical same-row guard, not only the nearest pressure guard. When guards pinch from both sides, horizontal moves toward either guard are suppressed and a legal defensive trap receives priority.
- Under high/critical primary pressure, the backend also treats an opposite same-row guard closing from within seven tiles as an imminent pinch even if its current distance risk is still low. Movement toward that guard is filtered before it can leave the runner off-center; a centered defensive trap remains eligible.
- Horizontal route and retreat actions use prospective endpoint safety under medium-or-higher pressure. When a closing guard is behind and the action approaches a terminal level edge with no vertical escape or an unoccupied bottom-row hole, the burst is shortened to center on the current safe tile; if continuing cannot center the runner, the candidate is rejected before selection. Physical validation accounts for that sub-tile centering horizon, so an adjacent hole does not suppress a move that stops before entering it. An edge tile with a usable ladder remains eligible, and an urgent `evade_edge_ladder` move is exclusive over conflicting defensive digs.
- After all gold is collected on Classic level 1, exit routing follows explicit row waypoints through ladder columns `27 → 20 → 25 → 18`. This covers the bottom platform, middle ladder chain, upper ladder, row-3 rope traversal, and revealed `S`; generic nearby-ladder scoring cannot redirect an otherwise safe exit candidate.
- Before following an opened access hole, the backend checks for guards close enough below the hole to intercept the committed fall. An unsafe entry is replaced by a two-tick `wait_for_guard_clearance` candidate whose identity tracks the blocking guard's coordinate and offsets.
- Route access evaluates both left and right dig/follow cells. A guard-clear side outranks the side facing the gold, and dig planning uses a longer interception horizon to account for the dig animation plus the committed fall.
- Horizontal movement also compares structural brick support with the active grid across the action horizon. A burst approaching a temporarily open dug brick is shortened to stop one tile before it; once adjacent, ordinary collection/alignment candidates are withheld until the floor refills. Only `route_access_follow` may intentionally enter that hole.
- Candidate scoring is heuristic. Higher scores go first, then ids break ties. The prompt receives the top `backend.candidateLimit` candidates.
- Candidates with identical normalized key/tick actions are collapsed to the highest-ranked intent before truncation.
- removes confirmed loop actions before sorting and prompt truncation.
- Only legal first actions should be emitted. Legality comes from movement and dig affordances in `agent/reasoning_tools.py`.
- Vertical movement is not legal in normal mode when its adjacent destination tile is
  occupied by a guard. God mode retains the legacy pass-through behavior.
- Before gold completion, gold collection and route progress dominate. After gold completion, exit-ladder routing dominates.
- In god mode, guard contact is non-lethal, so progress candidates outrank survival spacing unless terrain physically blocks movement.
- Candidate coverage is empirical: if a failure trace lacks the correct first action, add or refine candidate generation; if the correct candidate exists but is not chosen, adjust scoring, loop filtering, or prompt selection. See `docs/candidate-design.md` for the design notes.

## Prompt Format
`public/LLM_GAME_RULES.md` contains short durable gameplay priorities. `agent/prompt.py` formats one candidate-selection prompt per backend decision.

The prompt tells the model:

- the backend already checked candidate legality, movement feasibility, dig feasibility, god-mode behavior, and route-access opportunities;
- it must choose one candidate id from the provided list;
- it must not invent key codes, actions, or alternate moves;
- it must return JSON only.

Required model output:

```json
{ "candidateId": "candidate_id_here" }
```

Prompt sections:

- compact state summary;
- primary progress target;
- candidate list;
- strict JSON output contract.

The state summary includes context, runner state, remaining gold, the primary target, compact
guard risk, and loop status. Each eligible choice exposes only id, kind, score, optional target,
and the backend action reason. Loop-causing actions are removed before prompt construction.

The prompt does not ask the model to parse the full board `terrainGrid` or invent raw key events during normal runtime. The board has already been reduced into structured state and candidates.

## Loop Filtering
`agent/loop_tools.py` is a deterministic filter inside candidate generation. It examines the
last 10 history entries and emits one compact `loopReport` with `active`, `type`,
evidence, suppression rules, and the candidates actually suppressed during generation.

There are only three loop types:

- `stationary_repeat`: a candidate or tile repeats without route or gold progress;
- `horizontal_cycle`: bounded left/right cycling without row or gold progress;
- `vertical_cycle`: repeated ladder direction runs without gold progress, including multi-action
  three-row patterns such as `down, down, up, up` and mixed `descend_route`/`climb_ladder`
  reversals. Recovery preserves guard-driven retreats and
  suppresses the progress-climb direction that reverses back into the same ladder state, including
  when the remaining gold is guard-carried and no visible primary target exists.

Repeated macro movement is not a loop while its encoded target distance decreases, and reaching
the target clears the signal. This progress rule also applies while route movement alternates with
guard-driven horizontal retreats. A repeated `retreat_from_guard` tail is classified as safety
movement rather than a hard horizontal loop. Dynamic waits and safety retreats are environment-
progress kinds; loop filtering may remove a confirmed non-progress route id but never removes a
safety retreat. Entering a dig/trap animation wait or bounded emergency hold also clears a stale
horizontal-cycle signal so the filter cannot suppress the only safe action after geometry changes.
An emergency hold does not clear an already alternating same-tile `wait_or_stop` stall; that pattern
remains a `stationary_repeat` until real movement or an environment change occurs.

The service retains one generic fallback for malformed JSON, unknown candidate ids, and actions that
fail final physical or guard-safety validation. That fallback operates only over the already eligible
candidate list.

Trace integration:

- run-level `model` stores the resolved model/profile/provider for the trace;
- run-level `config` stores the public agent config used for the trace;
- `step.state` mirrors the prompt's current-state facts for playback/debug alignment.
  - `gameState`, `tick`, `godMode`
  - compact `runner`, `gold`, `primaryProgressTarget`, and `guardRisk`
  - movement booleans only, not movement target/details
  - ladder detail string and route-access summary

- `step.loopMonitor` stores the compact loop report, evidence, and suppressed candidate summaries.
- `step.validation` stores generic selection and safety validation only.

## God Mode
God mode is the legacy `godMode` global toggled by `SHIFT-G`, `CTRL-Z`, or the wrapper star button.  Saved demos include legacy god-mode state through normal demo recording data.

If god mode is enabled before clicking `AI`, candidate generation treats guard contact as non-lethal, ranks progress over survival-only spacing, and still rejects physically impossible moves.
