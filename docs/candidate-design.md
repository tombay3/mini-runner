# State-driven Candidate Design

## Summary

The backend builds short validated actions; the LLM selects one `candidateId`.
The backend validates that choice and translates it to keys and ticks. The model
cannot send raw keys or invent a route outside the supplied candidates.

Candidates are derived from the live terrain grid, runner state, visible gold, guards, ladders,
ropes, holes, and active digs. They do not use map names, coordinates, fixed dimensions, or
precomputed topology.

## Candidate Contract

Each candidate supplied to the model contains:

- `id`: deterministic identifier based on kind, local target, and first action;
- `kind` and `lane`: tactical intent and its safety, progress, or environment lane;
- `score`: backend heuristic ranking;
- `target`: local objective metadata when applicable;
- `firstAction`: the validated short key/tick action;
- `reasons`: backend-derived context for the candidate.

The builder records every proposal in `candidateAudit`. A proposal is exposed, truncated by the
candidate limit, rejected for physical or safety reasons, deduplicated, or loop-suppressed. This
makes a missing candidate distinguishable from one that was deliberately filtered.

## Scoring and Deduplication

Scores set shortlist order and deterministic fallback order. They are heuristic
preferences, not proof that a choice is safe or correct; the LLM can choose a
lower-scored candidate.

`agent/scoring.py` holds named base values and the ladder-distance formula.
`scoreBreakdown` records the effective integer total and actual signed components:
base, ladder-distance bonus, guard-clearance adjustments and the narrow gold bonus
when applied. Components sum to the score; fixed values are not presented as
invented risk or progress calculations. Centralizing the constants does not tune them.

After score/ID sorting and truncation, two bounded rules can reorder exposed choices:

- **Gold bonus:** in normal mode at low risk, add +4 when exactly one exposed
  same-row gold action reaches the pickup window within its existing duration,
  opposite the original top ladder-alignment direction. Membership and durations
  stay unchanged.
- **Retreat tie-break:** under normal cross-row guard pressure, an exposed
  same-column left/right retreat pair must have equal highest scores and equal durations.
  Prefer a side only if its predicted minimum guard distance is strictly greater both
  during and at the end of the burst. Scores, other positions and membership stay
  unchanged. `rankingTieBreak` records both forecasts, winner, duration, projection
  rate and whether order changed. The rule lives in `agent/candidates.py`.

Score and tie-break explanations are diagnostic fields, not LLM prompt fields.
Audit entries distinguish proposed and effective scores; a merged candidate keeps
the winning proposal's breakdown rather than adding the proposals' scores.

All vertical actions in normal mode reject movement toward an
aligned, approaching secondary high/critical guard: up toward a guard above moving
down/falling, or down toward a guard below moving up/climbing out. This requires
medium/high/critical primary pressure. Existing rejection reasons take precedence;
trapped, stationary, moving-away, lateral or missing threat evidence does not trigger
this rule. Candidate intent does not exempt progress or recovery movement from the
same check. Scores, durations and primary-guard selection are unchanged. Rejected
proposals retain their proposed score and rejection reason.

Guard analysis retains every visible guard with valid coordinates, sorted by
distance. Secondary safety checks and clearance scoring use this full list;
the primary pressure-guard selection is unchanged.

Horizontal actions reject movement toward the center of an adjacent high/critical
guard climbing out below in the same column. Both actors' offsets determine the
direction; this covers primary/secondary guards and exempts god mode.

Under overall low guard risk, directional progress receives +4 when its predicted
distance from every active low-risk guard stays the same or increases. The bounded
projection uses the runner action and observed guard motion at eight ticks per cell;
guards in holes are excluded. Candidate reasons explain the bonus.

Safely separated progress that reduces distance receives no penalty or rejection
from this rule. Medium, high, critical, same-row and route-interception rejection
rules remain unchanged.

Under overall medium pressure from a guard on another row, horizontal progress
receives a -12 adjustment when the same bounded projection reduces the
minimum distance to any active guard. This is a ranking preference: the candidate
remains exposed, and a clearance-preserving alternative keeps its original score.
Vertical ladder actions are excluded so the bounded cross-row climb correction
retains its established behavior. Same-row and high/critical threats continue
through hard safety validation.

Candidates with identical normalized key/tick actions are merged only when kind and target match.
Their intents, targets, and reasons are retained. Semantically different candidates remain visible
even when their first action happens to be the same.

## Candidate Classification Matrix

`agent/candidate_lanes.json` is the authoritative lane mapping. Safety candidates handle immediate
guard or hole threats; progress candidates collect gold, change route or row, access terrain,
descend, or use the revealed exit; environment candidates wait and recheck when the state may
change or no ordinary action is available. Unknown kinds use `other` in diagnostics and are not a
candidate lane.

| Lane category | Candidate kinds | Meaning |
|---|---|---|
| Safety | `defensive_dig`, `emergency_hold`, `escape_through_open_hole`, `evade_edge_ladder`, `evade_open_hole`, `retreat_from_guard`, `wait_for_guard_clearance`, `wait_for_trap_resolution` | Avoid immediate guard or hole danger, or wait for a safety condition to clear. |
| Progress | `align_ladder`, `climb_ladder`, `collect_current_tile_gold`, `collect_same_row_gold`, `descend_route`, `exit_ladder_route`, `god_mode_progress`, `low_risk_horizontal_progress`, `route_access_dig`, `route_access_follow` | Collect, change route or row, access terrain, descend, or use the exit. |
| Environment | `wait_and_recheck`, `wait_for_dig_completion`, `wait_for_floor_refill` | Advance changing terrain or briefly recheck when no other candidate is available. |

Active digs, floor refill, guard clearance, and trap resolution use state-specific waits with
bounded rechecks rather than the generic `wait_and_recheck` action.
In normal mode, trap resolution also waits while a guard is aligned with and falling into
the nearby open hole, even after it moves to the row below. Recheck every two ticks until
capture completes; this does not make the hole safe to cross early. Opposite-side closing
guards still use the existing defensive-dig checks.

A fully open hole three tiles away also counts as a trap when a closing same-row
guard is at most one column from it, or the guard is already falling into it.
This normal-mode check prevents a redundant nearer dig from blocking the runner's
route. It excludes refilling holes, preserves the existing capture rechecks, and
releases progress once the guard is trapped.

Ordinary digs require zero offsets. In normal mode, a supported, vertically centered
runner may start an off-center defensive dig when ordinary choices are exhausted
or a second closing guard needs a trap. The engine centers the dig; trap waits remain
available. Movement, occupancy, and guard checks still apply.

Before an emergency hold, a two-tick upward retreat may finish pending ladder
alignment onto a non-ladder tile when a high/critical guard is below.
If no ordinary action remains under diagonal high/critical pressure, try a four-tick
horizontal retreat away from the guard; existing validation still applies.

## State and Ladder Geometry

In normal mode, omit an `evade_edge_ladder` sidestep into known empty space with
known empty space below when an upward safety retreat has already passed physical,
guard and loop checks. Keep supported sidesteps and sideways escape when that
upward retreat is unavailable. Unknown terrain and god mode are unchanged. The
candidate audit records the omitted sidestep as a safety rejection; scores and
durations do not change.

At low decision risk, a connected active ladder with a brick-blocked target side
uses its sole known opening toward an off-column gold target. This can keep ascent
available even when gold is below. Progress descent into the same closed shaft is
omitted; at a ladder mouth this requires an already validated lateral candidate
toward the target. Unknown terrain, missing/same-column targets, two available
openings, exit routing, and medium/high/critical threat decisions retain the
existing policy. Safety retreats remain separate. The rule reads current terrain;
it adds no route commitment, timing changes, score changes or loop detector.
When a known off-row gold target prefers a physically blocked ladder direction,
low-risk planning retains the opposite direction only if it is explicitly legal.
Unknown movement affordances, exit routing, shaft-opening preferences, and
medium/high/critical decisions retain their existing policy and safety validation.

Analysis exposes its computed `primaryProgressTarget` to candidate generation, the prompt, and
traces.

Visible ladder routes include ordinary active ladder tiles and traversable top entries
where an active ladder begins one row below. Entry metadata includes `onDownEntry`,
`entryDirection`, and `ladderY`; the horizontal alignment target remains on the runner row.
When the runner is aligned on a traversable top entry, candidate generation exposes a bounded
`descend_route` to the underlying ladder, including after gold collection during exit routing.
It omits that descent for one decision immediately after climbing out through the
same ladder, preventing a direct undo. Entries reached horizontally remain available.
At low decision risk, the existing post-ascent departure check treats upward
`climb_ladder` and `exit_ladder_route` actions alike: after one horizontal
alignment toward a still-available ladder ahead, it omits alignment back to the
departed ladder for that decision. Existing history, movement, geometry, and
unchanged-gold checks remain; no persistent commitment or new loop detector is added.
Hidden exit ladders remain inactive until gold is complete. Discovery
does not force a descent, commit to a route, or change loop suppression.

After gold collection, the engine converts hidden exit tiles from `S` to `H`.
For horizontal alignment, a continuous active ladder column reaching row 0 is an
`exit_ladder_route` with the existing exit-alignment score. Its movement uses the
ordinary 4/6/8-tick distance rule rather than a fixed 20 ticks. This check does not
run before gold completion, affect ladders stopping below row 0 or rescore valid
upward exit actions. Explicit `S` routes keep their existing durations.
Exit alignment considers the next eligible ladder when validation or loop
filtering rejects a proposal. It stops after the first admitted route;
candidate limits and final selection still apply.

An upward exit action uses a six-tick recheck instead of 20 ticks only when a
descending low-risk guard is at most six cells above in the same continuous
ladder column. Other exit climbs retain their existing duration and score.

When a known progress target is above or on the runner row, alignment to a downward-only
top entry is omitted because it cannot advance toward that target; below-row and unknown
targets retain the entry.

After climbing out of a ladder, a progressing horizontal alignment away from that ladder omits
the ladder just exited from the immediately following decision. The omission applies only when the
chosen alignment target remains ahead, movement actually reduced its distance, gold did not change,
and decision risk is low. It does not re-arm on later horizontal decisions or suppress other candidate
families, so it is a bounded transition correction rather than route commitment.

## Loop Handling

Loop detection examines the most recent 10 recorded decisions. An active dig prevents loop
confirmation. All loop types require no gold-count change; environment waits and guard retreats are
treated conservatively so normal state changes are not mistaken for a loop.

A loop is confirmed as one of:

- **`stationary_repeat`**: the runner stays on one row without gold progress and either repeats
  `route_access_dig` twice, repeats `wait_and_recheck` three times, repeats the same non-progress
  candidate four times, or remains on one tile for six steps.
- **`horizontal_cycle`**: the runner stays on one row without gold progress and has at least six
  positions, four horizontal reversals, and a four-tile range. A recent six-step pattern must also
  finish within two tiles of where it started. It does not confirm while environment progress or
  guard retreat dominates the recent history.
- **`vertical_cycle`**: the runner remains on one ladder column, revisits two or three rows without
  gold progress, and has at least six up/down actions with four alternating direction runs. The
  last six candidates must be ladder movement or guard retreat.

After confirmation, the backend removes the repeated route, `wait_and_recheck`, and—when vertical
movement is cycling—the repeated ladder direction. Horizontal suppression also removes routes to
the same cycle target. `emergency_hold` is never suppressed, and a repeated guard retreat is not
suppressed by candidate ID. A horizontal route that reduced distance to its unreached target on
the latest action also remains eligible; reaching the target or failing to reduce distance restores
ordinary suppression.

One bounded vertical exception keeps a previously validated climb when a closing low-risk guard
is on the runner's row within seven cells and the only remaining progress candidate moves toward
that guard. The climb must take at most six ticks and must not have been selected in the recent
eight-decision loop window. Other available routes, a non-closing or cross-row guard, and
medium-or-higher pressure leave ordinary loop suppression in place. Physical and guard-safety
validation still precede this exception; it does not guarantee a safe future route.

When an existing horizontal-cycle report contains an alternating target sequence `A → B → A → B`,
candidate finalization suppresses only the predicted return to `A` for that decision. The suppression
is deferred until validation is complete and applies only when another validated ordinary
candidate remains. It does not create a new loop type or suppress both endpoints together.

The v4 trace records `loop:{active,type}` and `candidateEvents` with status `loop_suppressed`,
ID, kind, action, and reason. Direction is derived from the action; detailed loop evidence is not
stored.

## Failure Classification

Classify a recurring trace failure before changing prompts or scores:

- **Coverage gap:** a useful legal first action was absent.
- **Selection gap:** the useful candidate was exposed but not selected.
- **Execution gap:** a legal action did not have the intended runtime effect.
- **State gap:** the snapshot or analysis omitted a fact needed for generation or ranking.
- **Loop-filter gap:** non-progress repetition was not detected or was not removed.

This keeps changes evidence-driven. Prefer candidate coverage for absent actions, scoring or prompt
work for exposed-but-unselected candidates, execution fixes for timing/physics problems, and loop
changes only for confirmed repeated state patterns.

## Selection Validation

After the LLM returns a `candidateId`, `agent/service.py` validates it before sending
one key/tick action to the browser. This checks the plan; it does not execute physics.

The backend preserves a known choice that passes physical and guard checks, even
when another candidate has a higher score. Earlier medium-risk score overrides
could prevent useful route choices; the current baseline restores model discretion.
Scores, candidate generation, execution gates and the V2 contract remain unchanged.

The model response falls back when its JSON cannot be parsed or its `candidateId` is absent from
the supplied candidates. A known candidate also falls back if its action is no longer physically
valid or would move into guard pressure.

A climb toward a cross-row medium-risk guard is allowed only within these bounds:

- One action of at most six ticks; high/critical guards block the exception.
- If an adjacent-row guard's predicted endpoint distance is at most five cells,
  horizontal separation must be at least three columns.

Closer cross-row pressure and longer actions remain rejected. Low-risk guards
already trapped in holes do not block the climb.

The fallback is the first backend-ranked candidate. The v4 trace records requested and
selected IDs and nullable fallback code/message in `decision`; known-ID status is derived from
the exposed candidates before executing one short key/tick action.

V4 traces keep decision/fallback, exposed candidates, and nonexposed events separate; audits and
score breakdowns remain internal diagnostics. The
backend owns legality, safety, and legacy execution; the model selects among legal candidates.
