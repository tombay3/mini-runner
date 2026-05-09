# Classic Level 1 Agent Rules

This file is intentionally short and easy to edit. It is read directly into the LLM prompt for the Classic level 1 agent. Add, remove, or rewrite instructions here to steer the agent.

## Goal

- Collect all gold.
- After the last gold is collected, take the exit route.

## Movement Basics

- The runner can move left, right, up, and down.
- The runner can climb ladders, move across ropes, and fall.
- The runner cannot jump.
- The runner can dig down-left or down-right into brick.

## Danger Basics

- Touching a guard kills the runner.
- A short retreat is valid only when danger is immediate.
- Repeating the same retreat direction without gaining space, gold, or a route change is usually a mistake.

## Decision Rubric

1. First avoid immediate death.
2. If danger is not immediate, prefer nearby safe gold.
3. Same-row gold is a high-priority progress target.
4. Visible ladders on the runner row are strong route options.
5. If the runner is stalled on one row, change the route instead of repeating the same retreat.

## Classic Level 1 Bias

- Once the runner is not in immediate lethal danger, favor nearby gold, reachable ladders, or changing row or route over more retreat.
- Do not drift along the bottom row without collecting nearby gold.
- Do not ignore obvious nearby gold on the current row.
- Do not get trapped into left-edge or right-edge oscillation.
- If a reachable ladder can break the stall safely, prefer climbing it over another retreat.

## Output Style

- Choose one short action burst.
- Keep the action focused on survival first, then progress.
- Prefer simple progress over elaborate long-term plans when a nearby gold or ladder is already available.
