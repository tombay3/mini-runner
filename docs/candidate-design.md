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
- `stallBlocked`
- `stallRecovery`
- `target`
- `firstAction`
- `goal`
- `reason`

## Scoring
The heuristic scoring acts as the tactical engine, while the LLM acts as the strategic engine.

Scores are useful because they:

- order candidates before the list is truncated for the prompt;
- encode local progress bias and stall recovery knowledge;
- provide deterministic fallback when the model returns invalid JSON or chooses a blocked candidate;
- make traces easier to debug when the model chooses against backend ranking.

Score visibility in the prompt is configurable through `public/agent-config.json`
`prompt.showCandidateScores`. Final scores remain in candidate objects and traces either
way. Showing score is a pragmatic default: without a numeric priority signal, some models
overfit candidate wording and ignore the backend's tactical ranking.

Known heuristic limits:

- Heuristics are greedy and can contribute to oscillation loops.
- Heuristics struggle when risk and reward are both high.
- Heuristics generally penalize doing nothing (`wait_or_stop`).

Repeated macro candidates are evaluated against their encoded target coordinates. Continued
movement that reduces target distance is progress, not a stall. Ladder alignment scoring also
favors nearby ladders so a distant alternate route does not tie with an almost-reached ladder.
Only confirmed stalls produce blocked candidate metadata. Preliminary repetition and
short-oscillation observations remain trace-only and never enter the model prompt.
Confirmed horizontal stalls do not block the whole `retreat_from_guard` kind: a safety
retreat must remain eligible when it is the only guard-safe action, while repeated candidate
ids and non-progress waits can still be suppressed.
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
escapes. This prevents safe row-changing geometry from collapsing into repeated fallback stops.
At an edge ladder, a legal defensive trap against a closing guard suppresses downward retreat:
the ordinary gold route immediately climbs that ladder again and otherwise recreates the same
pressure state without changing guard control.
If the only solid escape side leads toward a nearby guard descending onto the runner's row,
the escape is suppressed and a centered proactive defensive trap is preferred. Dig candidates
are not emitted while the runner has a horizontal or vertical sub-tile offset because the legacy
engine cannot reliably begin a dig until the runner is centered.
The isolated upper-right gold at `(23,3)` uses a Classic-specific waypoint candidate through
the `x=20` and `x=25` ladder chain; nearest-ladder greed alone can send a displaced runner
back toward the left network and exhaust the step budget.
Visible row-14 gold uses the reverse fixed descent chain (`x=25` → `x=20` → `x=27`).
The row-6 `x=20` and row-12 `x=27` entries begin on the row below, so they cannot be
recovered reliably from same-row ladder proximity alone.
At the revealed exit, `(18,0)` can still have a positive `yOffset`; `finish_exit_climb`
bridges that sub-tile boundary state after ordinary tile-level upward affordance becomes false.

Scores should not be treated as proof of correctness. If a high-score candidate creates a loop, fix candidate coverage, scoring, or stall handling rather than assuming the model can infer the correction from text alone.

## Necessary And Sufficient Candidates
The candidate set is not provably complete by inspection. It is an empirical interface that should be validated against Classic level 1 failures.

A candidate kind is necessary when a successful route sometimes requires that class of first action and no existing kind expresses it cleanly. For example, `route_access_dig` is necessary because digging can open descent/access routes to lower gold, not only trap guards.

A candidate set is sufficient when every important state has at least one legal candidate that makes real progress or avoids immediate failure. It does not need every possible raw move.

High cross-row guard pressure must not turn a safely separated, nonterminal position into an empty candidate set. If all ordinary movement, dig, route, and collection choices are filtered, `cross_row_pressure_hold` preserves the position for two ticks and keys its identity to the guard geometry so the next changed state is evaluated afresh.

Practical sufficiency checks:

- Inspect failed traces and ask whether the correct first action was available as a candidate.
- Compare against successful human or demo play and confirm each required first action maps to an existing kind.
- Watch for states where only `wait_or_stop` is emitted.
- Watch for repeated fallback, repeated blocked choices, or no progress candidate in traces.
- Compare highest-score behavior against LLM-selected behavior to separate candidate coverage problems from selection problems.

## Failure Classification
Every recurring failure should be classified before adding more prompt text or guardrails:

- `Coverage gap`: the correct action is absent from the candidate list.
- `Selection gap`: the correct candidate exists but the model or ranking chooses another candidate.
- `Execution gap`: the candidate maps to a legal action, but ticks/timing/legacy physics make it ineffective.
- `State gap`: snapshot or analysis omits a fact needed to generate or rank the right candidate.
- `Stall gap`: repeated non-progress is not detected or the recovery candidate is not boosted/selected.

This classification keeps the candidate approach constrained without making it blind.

## Selection Validation
After the LLM returns a `candidateId`, `agent/service.py` validates the choice before sending an action to the browser. This validation is planner-level bookkeeping, not legacy physics execution.

`validation` explains how the candidate was accepted or changed:

- `knownCandidate`
- `requestedCandidateId`
- `selectedCandidateId`
- `actionValid`
- `actionGuardSafe`
- `fallbackUsed`
- `fallbackReason`
- `stallBlocked`
- `stallBlockReason`
- `stallReportType`
- `stallSeverity`
- `choiceReason`

Validation records:

- the candidate id requested by the model;
- the candidate id actually selected by the backend;
- whether the requested id was known;
- whether fallback was used and why;
- whether the translated first action is still physically valid;
- whether the action passes the normal-mode same-row guard safety boundary;
- whether the stall supervisor blocked the candidate;
- the model's reason text.

`requestedCandidateId` and `selectedCandidateId` can differ when the model returns invalid JSON, chooses an unknown candidate, chooses an unsafe or physically invalid action, or repeats a stall-blocked candidate. This makes traces explain whether a bad run came from candidate coverage, model selection, fallback behavior, safety validation, or stall supervision.

Normal-mode route access is also prospective: an opened descent hole is not offered as a
follow candidate while a nearby guard below can intercept the fall. The candidate set exposes
an explicit short guard-clearance wait instead, preserving the V2 selection boundary while
letting the backend reassess the moving threat before committing.

Physical validity includes dynamic occupancy: in normal mode, a vertical action is not
offered when the adjacent ladder/drop destination is currently occupied by a guard. The
nearest guard on any row is also retained in prompt-parity trace state so a global critical
risk cannot appear without spatial context.

## Design Bias
Prefer adding or refining candidates when the correct first action is missing. Prefer scoring/stall changes when the correct candidate exists but is not selected. Prefer action translation changes when the candidate is right but the legacy runtime does not execute it effectively.

Avoid returning to raw key planning as the default path. The current model role is candidate selection, not physics, pathfinding, or executor control.
