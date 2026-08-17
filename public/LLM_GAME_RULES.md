# Classic Level 1 LLM Game Rules

## Objective

- Before `goldComplete=true`, choose concrete progress toward remaining visible gold.
- After `goldComplete=true`, choose progress toward or upward on the revealed exit ladder.

## Selection Policy

- Prefer collecting gold, using the correct ladder direction, or opening and following a route-access path over waiting or repeating a retreat.
- In normal mode, immediate guard danger may outrank progress.
- `legalDirections` describes physically available movement, not necessarily
  guard-safe executable choices; prefer the explicit safety candidate when the
  prompt identifies an active execution gate.
- While a dig is active, choose `wait_for_dig_completion`; while a trap is being
  resolved, choose `wait_for_trap_resolution` unless the prompt exposes a
  higher-priority safety action.
- `side` says where a guard is relative to the runner; only `motion` says where it is moving.
- In normal mode, never move toward a same-row guard under medium, high, or critical pressure.
- Under high or critical guard danger, prefer a valid row-changing climb or descent over horizontal retreat.
- In god mode, guard contact is non-lethal, so progress normally outranks retreat and defensive digging.
- Use `wait_or_stop` only when no valid progress or safety candidate exists.
