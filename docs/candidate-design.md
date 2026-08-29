# State-driven Candidate Design

## Summary

The backend supplies short legal actions; the model selects one `candidateId` from that list. It
does not send raw keys, simulate physics, or invent routes outside the supplied candidates.

This document defines how candidates are built, grouped, filtered, ranked, and diagnosed. See
[Agent evaluator](./evaluator.md) for repeatable runtime evaluation.

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

Scores order candidates before prompt truncation and define deterministic fallback order; they are
not proof that a candidate is correct. A model may choose a lower-scored legal candidate when its
local tradeoff is better.

Validation enforces two narrow medium-risk preferences after the model returns a
`candidateId`. When a closing same-row guard can fall into an exposed defensive
dig, a non-safety or lower-scored safety choice is replaced by the highest-scored
exposed safety candidate. One bounded exception preserves a requested
guard-can-fall dig when downward retreat is its sole higher-scored alternative
and recent history contains at least two retreat-down/up-ladder cycles with no
gold or horizontal progress. When the pressure guard is cross-row, no safety
candidate is exposed, and the model selects a horizontal ladder alignment, a
lower-scored ladder choice is replaced by the highest-scored exposed horizontal
ladder alignment. Ties keep the model's choice. Active dig/trap/floor waits, god
mode, other risk levels, and secondary medium-or-higher same-row guards bypass
these preferences. Physical and guard-safety validation still runs on the
resulting candidate. The validation trace records the model's requested ID and
any replacement reason; candidate generation, scores, and the V2 `candidateId`
contract are unchanged.

Under overall low guard risk, a directional progress candidate receives a four-point bonus when a
bounded projection preserves or increases its distance from every active low-risk guard. The
projection samples the runner action and observed guard motion at eight ticks per grid cell. Guards
already in holes do not participate. The bonus explains itself in the candidate reasons; it does
not penalize or reject safely separated progress that reduces distance, and it does not change any
medium, high, critical, same-row, or route-interception rejection.

Under overall medium pressure from a guard on another row, horizontal progress
receives a twelve-point penalty when the same bounded projection reduces the
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
| Progress | `align_ladder`, `climb_ladder`, `collect_current_tile_gold`, `collect_same_row_gold`, `descend_route`, `exit_ladder_route`, `low_risk_horizontal_progress`, `route_access_dig`, `route_access_follow` | Collect, change route or row, access terrain, descend, or use the exit. |
| Environment | `wait_and_recheck`, `wait_for_dig_completion`, `wait_for_floor_refill` | Advance changing terrain or briefly recheck when no other candidate is available. |

Active digs, floor refill, guard clearance, and trap resolution use state-specific waits with
bounded rechecks rather than the generic `wait_and_recheck` action.

## State and Ladder Geometry

Analysis exposes its computed `primaryProgressTarget` to candidate generation, the prompt, and
traces. Visible ladder routes include ordinary active ladder tiles and traversable top entries
where an active ladder begins one row below. Entry metadata includes `onDownEntry`,
`entryDirection`, and `ladderY`; the horizontal alignment target remains on the runner row.
When the runner is aligned on a traversable top entry, candidate generation exposes a bounded
`descend_route` to the underlying ladder, including after gold collection during exit routing.
It omits that descent for the single decision immediately after the runner climbed out through
the same ladder, preventing a direct undo while preserving
entries reached horizontally. Hidden exit ladders remain inactive until gold is complete. Discovery
does not force a descent, commit to a route, or change loop suppression.
When a known progress target is above or on the runner row, alignment to a downward-only
top entry is omitted because it cannot advance toward that target; below-row and unknown
targets retain the entry.

After climbing out of a ladder, a progressing horizontal alignment away from that ladder omits
the ladder just exited from the immediately following decision. The omission applies only when the
chosen alignment target remains ahead, movement actually reduced its distance, gold did not change,
and decision risk is low. It does not re-arm on later horizontal decisions or suppress other candidate
families, so it is a bounded transition correction rather than route commitment.

## God-mode Threat Isolation

The existing `godMode` flag makes tactical guard pressure neutral: decision analysis uses low
risk, no pressure guard, and no nearby-threat list, while retaining runner-edge geometry. Actual
observations remain separately available as `observedGuardRisk`. Normal-mode decisions continue
to use observed threats unchanged.

God-mode model context omits guard threats, trapped-guard occupancy flags, and route-threat
details. Generated candidate wording is guard-neutral, and the bounded emergency fallback uses
the stable ID `emergency_hold` rather than a guard-derived signature. IDs are the same in the
prompt, validation, and trace; there is no alias layer.

The isolated prompt uses `public/LLM_GAME_RULES_NEUTRAL.md`, which describes collection, terrain,
and execution without mentioning guards or special modes. Its wrapper omits risk-policy
instructions, and its game context omits `godMode` rather than reporting a false mode. The
shared progress fallback uses `low_risk_horizontal_progress`; collection, ladder alignment, and
fallback actions use the same ordering, timing, and scores in guard-free states in both modes.
An active loop is not bypassed by a separate god-mode progress fallback.
Normal-mode prompts continue to use the unchanged `public/LLM_GAME_RULES.md`. There is no
instruction to ignore guards and no filtering of the model's response text.

This is threat-input isolation, not guard-free gameplay. Movement and dig checks still use the
actual snapshot, including occupancy and holes. Guards still move and carry/drop gold; carried
gold is not presented as visible collectible gold, and remaining counts are not adjusted.

New trace states retain **observed** `guardRisk` and include `guardThreatIgnored` (`true` in god
mode, `false` in normal mode). Physical guard details remain in diagnostic traces even when
omitted from the model context. Existing stores are not rewritten; older traces lack the flag
and should not be assumed to use this isolation behavior.

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

The trace records `loopMonitor` evidence and `suppressedCandidates`. Each suppressed item contains
its ID, kind, direction, and reason, so an evaluator can distinguish loop filtering from a missing
candidate.

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
After the LLM returns a `candidateId`, `agent/service.py` validates the choice before sending an action to the browser. This validation is planner-level bookkeeping, not legacy physics execution.

The model response falls back when its JSON cannot be parsed or its `candidateId` is absent from
the supplied candidates. A known candidate also falls back if its action is no longer physically
valid or would move into guard pressure.

A ladder climb toward a cross-row medium-risk guard remains available for one bounded action for at most six ticks. High/critical guards block the exception. A medium-risk guard whose
adjacent-row endpoint distance is at most five cells must have at least three columns of horizontal
clearance; closer cross-row pressure and longer actions retain the conservative rejection. Low-risk guards already trapped in holes do not block the climb.

The fallback is the first backend-ranked candidate. The trace records the requested and selected
IDs, whether the requested ID was known, and the fallback reason before executing one short
key/tick action.

Traces keep model choice, validation, candidate availability, and audit results separate. The
backend owns legality, safety, and legacy execution; the model selects among legal candidates.
