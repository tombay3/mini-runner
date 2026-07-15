# Classic Level 1 LLM Game Rules

## Objective

- Before `goldComplete=true`, choose concrete progress toward remaining visible gold.
- After `goldComplete=true`, choose progress toward or upward on the revealed exit ladder.

## Selection Policy

- Never choose a candidate marked `stallBlocked`.
- During a stall, prefer `stallRecovery` candidates and follow the recovery hint.
- Prefer collecting gold, using the correct ladder direction, or opening and following a route-access path over waiting or repeating a retreat.
- In normal mode, immediate guard danger may outrank progress.
- In god mode, guard contact is non-lethal, so progress normally outranks retreat and defensive digging.
- Use `wait_or_stop` only when no valid progress or safety candidate exists.
