# Classic Level 1 LLM Game Rules

## Objective

- Before `goldComplete=true`, choose concrete progress toward remaining visible gold.
- After `goldComplete=true`, choose progress toward or upward on the revealed exit ladder.

## Selection Policy

- Apply execution gates first, then guard-risk policy, then compare progress candidates.
- At low guard risk, prefer concrete collection, ladder, route-access, descent, or exit progress over retreating, holding, or waiting.
- At medium guard risk, choose progress only when its supplied candidate reasons identify a guard-safe route; otherwise prefer safety.
- Under high or critical guard risk, prefer a valid row-changing escape, defensive dig, or movement away from the pressure guard over progress.
- Resume concrete progress as soon as guard danger and execution gates clear; do not continue retreating after safety is restored.
- Candidate targets, scores, and reasons are backend-derived and authoritative; do not reject an indirect-looking first action or invent an unsupported route interpretation.
- `legalDirections` describes physically available movement, not necessarily
  guard-safe executable choices; prefer the explicit safety candidate when the
  prompt identifies an active execution gate.
- While a dig is active, choose `wait_for_dig_completion`; while a trap is being
  resolved, choose `wait_for_trap_resolution` unless the prompt exposes a
  higher-priority safety action.
- `side` says where a guard is relative to the runner; only `motion` says where it is moving.
- In normal mode, never move toward a same-row guard under medium, high, or critical pressure.
- Under high or critical guard danger, prefer a valid row-changing climb or descent over horizontal retreat.
- When a high or critical guard is directly above or below the runner, and the opposite ladder direction is legal, prefer that row-changing retreat over waiting.
- In god mode, guard contact is non-lethal, so progress normally outranks retreat and defensive digging.
- Use `wait_or_stop` only when no valid progress or safety candidate exists.
