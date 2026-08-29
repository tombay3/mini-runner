# Lode Runner Agent Rules

## Objective

- Before `goldComplete=true`, choose concrete progress toward remaining visible gold.
- After `goldComplete=true`, choose progress toward or upward on the revealed exit ladder.

## Selection Policy

- Apply execution gates first, then compare progress candidates.
- Prefer concrete collection, ladder, route-access, descent, or exit progress over holding or waiting.
- Candidate targets, scores, and reasons are backend-derived and authoritative; do not reject an indirect-looking first action or invent an unsupported route interpretation.
- `legalDirections` describes physically available movement; choose only a supplied executable candidate.
- While a dig is active, choose `wait_for_dig_completion`.
- Use `wait_or_stop` only when no valid progress candidate exists.
