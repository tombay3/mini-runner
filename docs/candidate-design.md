# Candidate Design Notes

## Summary
The V2 agent constrains the model to backend-generated candidate actions. This deliberately trades an open raw-key action space for a smaller, safer set of legal and purposeful choices.

The model is not asked to reproduce spatial math or legacy physics. Candidate generation
answers, "What legal useful moves exist right now?" Candidate scoring answers, "Which moves
look promising by simple rules?" The LLM answers, "Given these choices and the current
context, which candidate should we commit to?"

This intentionally excludes demo-path guidance, few-shot examples, Python simulation, full pathfinding.

## Candidate Data
The V2 agent is candidate-centric. The model chooses a generated `candidateId`; it does not invent raw key codes.

Each persisted candidate summary includes:

- `id`
- `kind`
- `score`
- `target`
- `firstAction`

## Scoring
The heuristic scoring acts as the tactical engine, while the LLM acts as the strategic engine.

Scores are useful because they:

- order candidates before the list is truncated for the prompt;
- encode local progress and safety priorities;
- provide deterministic fallback ordering when the model response is invalid;
- make traces easier to debug when the model chooses against backend ranking.

Scores are always visible to the selector and retained in traces. Candidates that normalize to
the same key/tick action are collapsed to the highest-ranked intent before prompt truncation.

Known heuristic limits:

- Heuristics are greedy and can contribute to oscillation loops.
- Heuristics struggle when risk and reward are both high.
- Heuristics generally penalize doing nothing (`wait_or_stop`).

Repeated macro candidates are evaluated against their encoded target coordinates. Continued
movement that reduces target distance is progress, not a loop. Ladder alignment scoring also
favors nearby ladders so a distant alternate route does not tie with an almost-reached ladder.
Vertical-cycle detection compares direction runs rather than individual key events, so legacy
ladder traversal that needs multiple decisions per direction still reveals a repeated cycle.
Mixed climb/guard-retreat cycles preserve the safety retreat and suppress the reversing climb.
Confirmed loops remove the exact loop-causing candidate before prompt construction. A horizontal
cycle does not suppress `retreat_from_guard`: immediate safety remains authoritative. Conversely,
a confirmed non-progress route id is eligible for suppression, while any encoded reduction in its
target distance clears the horizontal loop signal even when safety retreats occurred earlier.
Entering a dig/trap animation wait or bounded emergency hold ends the stale horizontal signal;
these actions reflect changed environment geometry and must not be removed as the repeated id.
An in-progress legacy dig is environmental progress, not an idle wait. The hook exposes its
animation frame as `activeDig`, and `wait_for_dig_completion` advances it in bounded increments
until the brick becomes an observable open hole. It is the exclusive candidate during that
interval because other movement is evaluated against the pre-hole grid and can become unsafe
when the brick opens mid-action.
Once gold is complete, an open hole that intersects the fixed Classic exit waypoint route uses
the same frame-signatured `wait_for_floor_refill` behavior as collection routing.
When an open hole already lies between the runner and a same-row pressure guard,
`wait_for_trap_resolution` advances guard/hole geometry by eight ticks at long range, four at
medium range, and two during immediate contact, falling, or climb-out. Redundant adjacent
defensive digging and route-changing movement are suppressed; trap resolution is exclusive
until the separating geometry changes. A guard beginning `up`/`climb_out` on the runner's row
ends that state immediately so a physical escape candidate can run before contact.
A hole occupied by a fully trapped guard is also not a separator: the trapped guard temporarily
supports crossings by both the runner and other guards, so ordinary guard-safe retreat remains
available instead of waiting for a barrier that no longer exists.
When a closing same-row guard creates medium pressure and the runner's retreat side ends at an
adjacent empty hole, the backend emits the same threat-checked intentional drop used for emergency
escapes. This prevents safe row-changing geometry from collapsing into repeated stops.
At an edge ladder, a legal defensive trap against a closing guard suppresses downward retreat:
the ordinary gold route immediately climbs that ladder again and otherwise recreates the same
pressure state without changing guard control.
If the only solid escape side leads toward a nearby guard descending onto the runner's row,
the escape is suppressed and a centered proactive defensive trap is preferred. Dig candidates
are not emitted while the runner has a horizontal or vertical sub-tile offset because the legacy
engine cannot reliably begin a dig until the runner is centered.
A legal centered trap against a high-risk closing guard at distance three is exclusive over
ordinary retreat. This prevents the selector from abandoning a prepared capture—especially of a
guard carrying the last gold—for a retreat that recreates the same pressure elsewhere.
An adjacent same-row guard moving `up` or `climb_out` makes an upward reversal unsafe. The runner
must not follow the guard into its escape lane; a legal downward continuation remains available.
Horizontal route and retreat bursts also enforce a prospective endpoint invariant under pressure.
With a closing guard behind, a terminal edge with no projected vertical escape or an unoccupied
bottom-row hole ahead cannot be approached to an off-center endpoint: the burst stops at the current
tile center when possible, otherwise the candidate is removed. The physical open-hole check includes
the runner's sub-tile offset, allowing that shortened action when it cannot yet enter an adjacent
hole. An edge tile with a usable ladder remains eligible; once the guard below threatens that ladder
column, `evade_edge_ladder` is exclusive over a conflicting defensive dig so the selector cannot
replace the escape with unsafe geometry.
The isolated upper-right gold at `(23,3)` uses a Classic-specific waypoint candidate through
the `x=20` and `x=25` ladder chain; nearest-ladder greed alone can send a displaced runner
back toward the left network and exhaust the step budget. After collecting the top-left gold
at `(4,1)`, the same route first returns right to the `x=7` row-1 descent entry; the ladder
begins on the row below and therefore is not discoverable as a same-row ladder. That return also
applies when no gold is visible because the final piece is guard-carried; the solver re-enters the
level rather than issuing generic stops or treating the carrier as a directly collectible target.
At the `x=7` row-1 entry, carried-only recovery emits a short downward Classic route and continues
down the ladder instead of reversing upward toward the carrier. Guard-carried positions are excluded
from ordinary descent and route-access gold tests. If the guard drops gold onto the runner while the
runner still has a positive ladder `yOffset`, collection first finishes that vertical alignment.
In god mode, direct horizontal `god_mode_progress` is a last-resort fallback only. It is not emitted
when a structured Classic route, same-row collection, ladder alignment, access, or descent candidate
already exists; chasing an off-row target's x-coordinate must not reverse a valid ladder approach.
Visible row-14 gold uses the reverse fixed descent chain (`x=25` → `x=20` → `x=27`).
When `(7,12)` remains and the runner is already below it on rows 13–14, the route uses the
viable `x=27` ladder; `x=4` is a dead end from below. While an explicit Classic route is active,
conflicting generic ladder-alignment candidates are omitted from model selection.
The row-6 `x=20` and row-12 `x=27` entries begin on the row below, so they cannot be
recovered reliably from same-row ladder proximity alone.
At the revealed exit, `exit_ladder_route` also bridges a positive `(18,0)` `yOffset` after
ordinary tile-level upward affordance becomes false.

Scores should not be treated as proof of correctness. If a high-score candidate creates a loop, fix candidate coverage, scoring, or loop filtering rather than assuming the model can infer the correction from text alone.

## Necessary And Sufficient Candidates
The candidate set is not provably complete by inspection. It is an empirical interface that should be validated against Classic level 1 failures.

A candidate kind is necessary when a successful route sometimes requires that class of first action and no existing kind expresses it cleanly. For example, `route_access_dig` is necessary because digging can open descent/access routes to lower gold, not only trap guards.

A candidate set is sufficient when every important state has at least one legal candidate that makes real progress or avoids immediate failure. It does not need every possible raw move.

High cross-row guard pressure must not produce an empty candidate set. If every ordinary action is
filtered, `emergency_hold` advances two ticks and keys its identity to guard geometry.

Practical sufficiency checks:

- Inspect failed traces and ask whether the correct first action was available as a candidate.
- Compare against successful human or demo play and confirm each required first action maps to an existing kind.
- Watch for states where only `wait_or_stop` is emitted.
- Watch for repeated generic fallback, candidate suppression, or no progress candidate in traces.
- Compare highest-score behavior against LLM-selected behavior to separate candidate coverage problems from selection problems.

## Failure Classification
Every recurring failure should be classified before adding more prompt text or guardrails:

- `Coverage gap`: the correct action is absent from the candidate list.
- `Selection gap`: the correct candidate exists but the model or ranking chooses another candidate.
- `Execution gap`: the candidate maps to a legal action, but ticks/timing/legacy physics make it ineffective.
- `State gap`: snapshot or analysis omits a fact needed to generate or rank the right candidate.
- `Loop-filter gap`: repeated non-progress is not detected or the loop-causing candidate is not removed.

This classification keeps the candidate approach constrained without making it blind.

## Selection Validation
After the LLM returns a `candidateId`, `agent/service.py` validates the choice before sending an action to the browser. This validation is planner-level bookkeeping, not legacy physics execution.

`validation` explains how the candidate was accepted or changed:

- `knownCandidate`
- `requestedCandidateId`
- `selectedCandidateId`
- `fallbackUsed`
- `fallbackReason`

Validation records:

- the candidate id requested by the model;
- the candidate id actually selected by the backend;
- whether the requested id was known;
- whether fallback was used and why.

The backend still revalidates the selected action before translation, but successful checks
are not duplicated as trace fields.

`requestedCandidateId` and `selectedCandidateId` can differ when the model returns invalid JSON,
chooses an unknown candidate, or chooses an unsafe or physically invalid action. Confirmed loop
actions never enter the model-visible list. This separates candidate coverage, model selection,
generic fallback, safety validation, and loop-filter behavior in traces.

Normal-mode route access is also prospective: an opened descent hole is not offered as a
follow candidate while a nearby guard below can intercept the fall. The candidate set exposes
an explicit short guard-clearance wait instead, preserving the V2 selection boundary while
letting the backend reassess the moving threat before committing.

Physical validity includes dynamic occupancy: in normal mode, a vertical action is not
offered when the adjacent ladder/drop destination is currently occupied by a guard. The
nearest guard on any row is also retained in prompt-parity trace state so a global critical
risk cannot appear without spatial context.

## Design Bias
Prefer adding or refining candidates when the correct first action is missing. Prefer scoring or
loop-filter changes when the correct candidate exists but is not selected. Prefer action translation
changes when the candidate is right but the legacy runtime does not execute it effectively.

Avoid returning to raw key planning as the default path. The current model role is candidate selection, not physics, pathfinding, or executor control.
