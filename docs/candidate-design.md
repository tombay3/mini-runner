# Candidate design

The backend proposes short actions. The model chooses one `candidateId`; the backend
checks the choice and returns a key and tick count. The legacy game engine executes it.
Only Classic `playData=1, level=1` is supported.

Use this document for planning rules. See the [backend specification](backend-spec.md)
for API and trace fields, [agent lifecycle](llm-agent.md) for requests, and
[test guide](sanity-tests.md) for validation.

## Decision flow

1. Analyze the live snapshot and recent history.
2. Propose actions from movement, gold, ladders, digs, holes, and guard pressure.
3. Bound durations; check physical and guard safety; apply loop filtering.
4. Merge equivalent proposals and apply final recovery checks and ranking.
5. Expose the highest-ranked candidates up to the configured limit.
6. Ask the model to select an exposed ID, validate it, then return one action.

The planner uses current geometry, not map-specific routes or a second game simulator.
Targets are local waypoints. A candidate's name, score, or explanation does not prove
that it reaches gold or the exit safely.

## Candidate contract

| Field | Meaning |
| --- | --- |
| `id` | Deterministic ID from intent, local target, and first action. |
| `kind` | Tactical intent, such as collecting gold or climbing a ladder. |
| `lane` | Safety, progress, or environment category. |
| `score` | Backend ranking preference. The model may choose a lower score. |
| `target` | Local objective, when present. |
| `action` | Validated short key/tick input. |
| `reasons` | Backend explanation grounded in the analyzed state. |

`CandidateBuilder` in [candidates.py](../agent/candidates.py) records each proposal in
`candidateAudit`. Dispositions distinguish exposure, limit truncation, physical or
safety rejection, deduplication, and loop suppression. Audits and score breakdowns
are internal; compact nonexposed events appear in traces.

## Candidate classification matrix

[candidate_lanes.json](../agent/candidate_lanes.json) owns the lane mapping.

| Lane | Candidate kinds |
| --- | --- |
| Safety | `defensive_dig`, `emergency_hold`, `escape_through_open_hole`, `evade_edge_ladder`, `evade_open_hole`, `retreat_from_guard`, `wait_for_guard_clearance`, `wait_for_trap_resolution` |
| Progress | `align_ladder`, `climb_ladder`, `collect_current_tile_gold`, `collect_same_row_gold`, `descend_route`, `exit_ladder_route`, `god_mode_progress`, `low_risk_horizontal_progress`, `route_access_dig`, `route_access_follow` |
| Environment | `wait_and_recheck`, `wait_for_dig_completion`, `wait_for_floor_refill` |

Unknown kinds display as `other` in diagnostics; this is not a candidate lane.
Use specific waits for active digs, floor refill, guard clearance, and trap resolution.
Generic waiting is a last recheck, not a route plan.

## Safety checks

Physical checks and guard checks precede model selection. Ranking never replaces them.
Guard analysis keeps every visible guard with valid coordinates, sorted by distance;
secondary checks use that full list. The primary pressure guard is selected separately.

### Guard movement and action duration

| Situation | Rule |
| --- | --- |
| Aligned secondary guard approaching vertically | Under medium-or-higher primary pressure, reject up toward a high/critical guard above moving down/falling, or down toward one below moving up/climbing out. Existing rejection reasons take priority. Trapped, stationary, moving-away, lateral, or unknown motion does not trigger this rule. |
| High/critical guard climbing out below in the same column | Reject horizontal movement toward its center. Use both actors' offsets, including for secondary guards. God mode is exempt. |
| High-risk guard separated below by intact floor | Permit a horizontal burst of at most four ticks when both actors are vertically centered, the guard is at least two rows below and moving horizontally or stopped, and both terrain and live grid show solid floor across their corridor plus two cells of padding. Open holes, active digging, missing evidence, or another high/critical guard without the same separation prevent this exception. Existing same-row and other safety checks remain active; risk labels are unchanged. |
| Overall medium pressure; horizontal action | A burst of at most four ticks may pass directional rejection only if every medium-risk guard preserves at least two cells of horizontal clearance under worst-case mutual approach. Any high/critical guard or missing required coordinate/offset blocks the exception. Cross-row medium guards constrain it too. |
| Horizontal proposal rejected by guard checks | Try shorter durations from longest to shortest within that same medium-clearance bound. Recheck endpoint, physical, and guard safety, then loop filtering. Keep the longest passing burst; otherwise keep the rejection. IDs, targets, and score policies stay fixed; audits retain proposed and validated durations. |
| Climb toward a medium-risk guard on another row | Allow at most six ticks; high/critical guards block the exception. For an adjacent-row guard with predicted endpoint distance at most five cells, require at least three columns of horizontal separation. Closer pressure and longer actions remain rejected. Low-risk trapped guards do not block this climb. |

Classic cells are 40 units wide. The medium horizontal bound assumes each actor can
approach by eight units per tick. One integer tick limit serves both short-action
checks and duration retries. It bounds the next action, not a complete escape route.
God mode gains no new exception from this calculation.

### Digs, holes, and waits

- Ordinary digs require zero offsets. Physical movement, support, occupancy, and
  guard checks still apply to defensive digs.
- A supported, vertically centered runner may dig off-center in normal mode when
  ordinary choices are exhausted, medium-or-higher same-row pressure exists on both
  sides, or another closing guard needs a trap. Two-sided pressure does not require
  an empty shortlist. The engine centers the dig; trap waits remain available.
- For defensive digging, a descending pressure guard within three cells takes
  priority over a farther same-row guard. A nearer or equally close same-row guard
  keeps priority.
- A high/critical guard below qualifies through risk only when moving up or climbing
  out. Independent `guardCouldFall` evidence still qualifies, including from a
  same-row secondary guard. Lateral movement below alone is insufficient.
- `escape_through_open_hole` requires a fully open hole (`frameIndex: 0`). Unknown
  frames and visible refill animation block it; this does not predict hole lifetime.
- In normal mode, trap-resolution waits recheck every two ticks while a guard is
  aligned with and falling into a nearby hole, including after it moves below the row.
  Do not cross before capture. Other closing guards still undergo defensive-dig checks.
- A fully open hole three tiles away also counts as a trap if a closing same-row
  guard is within one column of it or is already falling into it. Refilling holes
  do not qualify. This avoids a redundant nearer dig; progress resumes after capture.
- Before emergency hold, a two-tick upward retreat may finish ladder centering onto
  a non-ladder tile when a high/critical guard is below. If ordinary choices are
  exhausted under diagonal high/critical pressure, try a four-tick horizontal
  retreat away from the guard. Both still require normal validation.

### Access routing

Scan both sides once and rank access options by safety, distance, and preferred side.
An existing opening takes priority over a new dig; distance does not break ties
between existing openings. Openings and planned digs retain different interception
horizons. Assess new-dig threats only when no existing-opening result is returned.
Trapped-guard policy and missing-data defaults remain caller-specific.

## Scoring and deduplication

[scoring.py](../agent/scoring.py) holds named base scores and ladder-distance scoring.
Values are heuristics, not measured probabilities. `scoreBreakdown` lists actual signed
components that sum to the effective score. Centralizing values does not tune them.

Candidates merge only when their normalized key/tick action, kind, and target match.
Combine unique reasons; retain the winning proposal's score breakdown rather than
adding scores. Different intents remain separate even if their first input matches.

Apply ranking to the full admitted pool before truncation:

| Adjustment | Conditions and effect |
| --- | --- |
| Low-risk clearance bonus | Add +4 to directional progress when the projected minimum distance to active guards stays equal or increases. Trapped guards are excluded. A separated approach gets no penalty from this bonus rule. |
| Medium cross-row penalty | Subtract 12 from horizontal progress when overall medium pressure comes from another row and projection reduces minimum distance to an active guard. This affects preference, not admission. Vertical ladder actions are excluded. |
| Same-burst gold bonus | In normal low-risk play, add +4 if exactly one admitted same-row gold action reaches the pickup window within its existing duration, opposite the original leading ladder-alignment direction. The bonus may move it inside the exposure limit. |
| Same-column retreat tie-break | Under normal cross-row pressure, compare an admitted left/right retreat pair only when both share the highest score and duration. Prefer a side only if its minimum guard distance is strictly greater both during and at the end of the burst. Keep scores and other ranking positions. |
| Recent ladder-return penalty | After gold completion in normal low-risk play, subtract 30 from returning to a recent ascent when another progress candidate exists. Skip this adjustment with any admitted safety candidate or active loop recovery. See memory rules below. |

Ladder alignment keeps its ordinary distance/fine-alignment score during loop
recovery. Being identified as the cycle's target earns no bonus, including when
the existing progress exception preserves that candidate from suppression.

Clearance adjustments and retreat tie-breaking share a tile-based forecast at eight
ticks per cell, using observed guard motion. Motion vectors are resolved once per
forecast. This is a ranking estimate, not a physics simulation or safety guarantee.
`rankingTieBreak` records both forecasts, winner, duration, projection rate, and any
order change. It and score breakdowns are diagnostics, not model prompt fields.

## State and ladder geometry

### Gold and exit targets

`goldTarget` is the preferred visible gold objective, excluding guard-carried gold.
It appears consistently in generation, model context, and traces; it is not a verified route.

After gold completion, `exitTarget: {x,y,tile:"S"}` identifies the next exit waypoint.
The runtime hook reads the loaded map because live exit tiles change from `S` to `H`.
It requires a unique top-row exit column connected through `S`/`H` tiles:

- Below the span, target its lowest connected `S`.
- Alongside it, target the runner's row.
- On the connected ladder, target the top.

Ignore disconnected lower exits. Missing or ambiguous exits leave the target unknown.
This context does not change scores, safety, generation, or `goldTarget` selection.

### Choosing and entering ladders

| Situation | Planning rule |
| --- | --- |
| Low-risk connected ladder with a brick-blocked target side | Use the sole known opening toward an off-column gold target, even if gold is below. Omit descent into the same closed shaft; at a ladder mouth require an admitted lateral candidate toward the target. Unknown terrain, missing/same-column targets, two openings, exit routing, and higher pressure keep their separate rules. |
| Known target prefers a physically blocked direction | At low risk retain the opposite direction only when explicitly legal. Shaft-opening preferences and exit routing retain priority. |
| No known target row; low risk | Continue an immediately preceding successful `climb_ladder` or `descend_route` if its after-tick and full runner pose match the snapshot, vertical motion followed the action, and the direction is explicitly legal. Waits, stale history, blocked actions, and safety retreats do not qualify. No persistent direction is added. |
| Traversable top entry above an active ladder | Expose bounded `descend_route`, including during exit routing. Entry metadata includes `onDownEntry`, `entryDirection`, and `ladderY`; alignment targets the runner row. Omit entry descent for one decision immediately after climbing out of that same ladder, including a multi-row climb through its entry row. Horizontal arrivals remain eligible. |
| Known target at or above the runner | Omit alignment to a downward-only top entry. Below-row or unknown targets retain it. |
| Recent ascent followed by horizontal departure | At low risk omit alignment back to the departed ladder for one decision, only if the chosen ladder ahead remains available, motion reduced target distance, and gold did not change. Treat upward `climb_ladder` and `exit_ladder_route` alike. Do not re-arm on later horizontal actions or suppress other families. |
| Unsupported edge sidestep | In normal mode, omit `evade_edge_ladder` into known empty space with known empty space below when an upward safety retreat has already passed physical, guard, and loop checks. Supported, unknown-terrain, god-mode, and otherwise-unavailable upward-retreat cases retain their separate behavior. Record a safety rejection. |

On-ladder recommendation metadata and explanations use the chosen direction, not
the geometry helper's default. Claim movement toward gold only when that direction
points toward the target; otherwise describe a row change.

### Exit routing

After gold completion, a continuous active ladder reaching row 0 qualifies as
`exit_ladder_route` for horizontal alignment. Use the usual 4/6/8-tick distance rule,
not a fixed 20 ticks. Explicit `S` routes keep their existing durations. This rule
does not apply before completion, to ladders stopping below row 0, or to upward scores.
If validation rejects an alignment, try the next eligible ladder; stop at the first
admitted route. Final ranking and candidate limits still apply.

An upward exit climb uses a six-tick recheck when a descending low-risk guard is at
most six cells above in the same continuous column. Other exit climbs keep their
duration and score. Hidden exits remain inactive until gold completion.

## Loop handling

Loop reports use up to 10 recent decisions. Only the contiguous complete history
suffix counts: a missing candidate ID, key, runner position, or gold count breaks
it. Never join evidence across a gap. Active digs prevent loop confirmation.
All loop types require unchanged gold count; progress here uses tiles, not offsets.

| Type | Evidence |
| --- | --- |
| `stationary_repeat` | No row change, plus repeated access dig twice, generic stop-wait three times, the same non-progress candidate four times, or one tile for six decisions. Environment-progress actions or a dominated window are exempt, except emergency hold after six same-tile decisions with a generic wait in the last six. |
| `horizontal_cycle` | Either the full window stays on one row with at least six positions within a four-tile range and four horizontal reversals, or the latest six positions independently satisfy those row/range/reversal bounds and end within two tiles of their start. Older row changes do not veto the latter. The latest environment-progress action or retreat-dominated history prevents confirmation. |
| `vertical_cycle` | One column, two or three rows with the current row revisited, at least six up/down actions and four direction runs. The last six candidate kinds must be ladder movement or guard retreat. |

Environment progress includes emergency hold, guard retreat, floor refill, guard
clearance, dig completion, and trap-resolution waits. A dominated window has at
least three such actions and more than half its decisions in that category.
Horizontal and stationary detectors retain their distinct exemptions.

### Suppression and recovery

- Suppress the repeated route and generic wait. Vertical cycles also suppress the
  reported repeated ladder directions; horizontal routes to the same cycle target
  are suppressed regardless of whether that target is an object or coordinate pair.
- Never suppress `emergency_hold`. Preserve a repeated guard retreat by ID.
- Preserve the repeated horizontal route if it reduced distance to its unreached
  target. Reaching the target or ceasing to approach restores ordinary suppression.
- If horizontal targets end in `A → B → A → B`, suppress the predicted return to `A`
  only after validation, and only if another ordinary candidate remains. Do not
  suppress both endpoints or create another loop type.
- A vertical-cycle exception may restore one already validated climb when the sole
  remaining progress action moves toward a closing low-risk guard on the same row.
  Guard distance must be greater than one and at most seven cells; the climb is at
  most six ticks and absent from the last eight chosen IDs. Other routes, cross-row
  or non-closing guards, and medium-or-higher pressure retain ordinary suppression.
  Physical and guard checks still apply; this does not prove a safe future route.

### Ladder-return memory

The recent-return preference uses up to 24 history entries, separately from loop
confirmation. A fresh ascent can survive same-row alignment and stationary defensive
digs, dig-completion waits, and trap-resolution waits. Each stationary action must
preserve the full runner pose without collecting gold; history must match the
current tick and pose. Penalize alignment back to the ladder or descent into that
shaft, and clear a conflicting recommendation. Admission and action durations stay
fixed. A sole progress choice keeps its score.

## Selection validation

[service.py](../agent/service.py) parses the returned JSON and looks up the exposed ID.
A known choice that passes physical and guard checks is retained, even if its score
is lower. Invalid JSON, absent/unknown IDs, or an invalid/unsafe selected action use
the first backend-ranked candidate. Validation checks the plan; it does not execute physics.

The trace separates requested ID, selected ID, rationale, fallback, issued action,
exposed candidates, and nonexposed events. Loop detail and score breakdowns stay
internal. See the [trace contract](backend-spec.md#trace-api-and-store).

## Failure classification

Classify the evidence before changing prompts or scores:

| Gap | Meaning | Start with |
| --- | --- | --- |
| Coverage | Useful legal action absent | Generation and filters |
| Selection | Useful candidate offered but not chosen | Scoring or model guidance |
| Execution | Issued input had an unexpected runtime effect | Engine timing and physics |
| State | Required observation or assessment missing | Snapshot and analysis |
| Loop filter | Repetition missed or useful action suppressed | Detection and suppression evidence |

## Evidence limits

Short clearance bounds, observed direction, and target-distance reduction do not
prove survival or completion. A historical matched continuation showed short
approaches followed by escape from a known stall; its first eight actions replayed
exactly. That is local evidence, not a general safety claim. Batch 3 validation
likewise used bounded continuations, not a level-completion study.

Validate simplification against a frozen source baseline. Accept simpler code when
differences are understood and relevant validation shows no demonstrated regression;
gameplay improvement is not required. Keep sample sizes and uncovered cases explicit.
