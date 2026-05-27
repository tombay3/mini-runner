# Agent Prompt Format

## Current Status
The current V2 prompt is candidate-centric. The backend no longer asks the model to invent raw `keyCode` / `ticks` moves from a full board. Instead, Python analysis generates legal candidate actions and the model chooses one `candidateId`.

The layered snapshot format is still important because candidate generation and traces use it, but the prompt only renders the compact state needed to choose among candidates.

## Prompt Ownership
- [public/AGENT_RULES.md](../public/AGENT_RULES.md): durable gameplay policy and high-level solving priorities.
- [agent/prompt.py](../agent/prompt.py): current state summary, candidate list, optional stall report, and strict JSON output contract.
- [agent/candidates.py](../agent/candidates.py): candidate generation and scoring.
- [agent/stall_tools.py](../agent/stall_tools.py): oscillation/loop/stall diagnosis and recovery hints.

## V2 Prompt Shape
The prompt asks for JSON only:

```json
{ "candidateId": "candidate_id_here", "reason": "brief explanation" }
```

The prompt includes:

- current level and god-mode state
- runner position and offset
- remaining visible gold
- primary progress target
- guard risk summary
- movement summary
- route-access summary
- stall summary
- top candidate choices
- recent behavior tail

The prompt does not ask the model to parse the full `terrainGrid` during normal V2 runtime.

## Snapshot Layers
[public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js) still exposes structured snapshot layers:

- `dimensions`: fixed Classic level dimensions, usually `28 x 16`.
- `terrainGrid`: structural terrain with runner, guards, and gold separated out.
- `runner`: live runner position, action, offsets, and centered state.
- `guards`: live guard positions, offsets, actions, and carried-gold state.
- `gold`: visible gold, carried gold, remaining count, and completion state.
- `timing`: record tick, game time, tick phase, and ticks-per-second context.
- `godMode`: whether legacy god mode is active for the run.

These fields are primarily consumed by backend analysis and trace serialization.

## Terrain Notes
The raw terrain model keeps terrain and dynamic entities separate:

- `.` empty
- `#` diggable brick
- `@` solid non-diggable block
- `H` visible ladder
- `-` rope
- `S` hidden exit ladder, shown to prompt logic only after `goldComplete=true`
- `X` dug hole or trap

Candidate generation should use coordinate facts and movement affordances rather than relying on the LLM to visually count grid columns.

## Historical Note
Earlier agent versions rendered a full terrain grid and asked the model to return raw keycodes. That approach caused repeated coordinate mistakes and oscillation. V2 keeps the full snapshot available for deterministic backend logic, but gives the model a smaller selection task.
