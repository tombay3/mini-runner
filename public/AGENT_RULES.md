# Classic Level 1 Agent Rules

Choose one backend-generated candidate. Do not invent actions, keycodes, or coordinates.

## Goal

- Collect all gold first.
- After `goldComplete=true`, choose exit-ladder candidates.

## Candidate Ranking

- Prefer candidates that collect visible gold.
- Prefer candidates that change row through a ladder or valid route-access dig.
- Prefer current-ladder climb candidates over leaving the ladder horizontally.
- Prefer route-access dig when remaining gold is below and no same-row gold or ladder route is available.
- Use stop/wait only when every progress or safety candidate is worse.

## Guard Policy

- In normal mode, immediate guard danger can outrank progress.
- In god mode, guard contact is non-lethal, so progress usually outranks retreat or defensive digging.
- Do not choose repeated spacing or retreat when a progress candidate is available.

## Stall Policy

- If recent actions oscillate around a ladder or target, choose the candidate that precisely aligns or climbs.
- If a candidate is labeled as anti-stall or fine-alignment, prefer it over broad horizontal movement.

## Output

Return only:
`{"candidateId":"...","reason":"..."}`
