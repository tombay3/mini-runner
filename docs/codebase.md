# Codebase Overview

## Summary
Mini Runner adds an LLM agent, replay tools, and diagnostics around the preserved Lode Runner
runtime. The legacy engine still runs the game; the wrapper and backend only observe state, choose
short actions, and save the result.

### Core Layers
- `public/game/*`: legacy gameplay, rendering, menus, input, editor, demo recording, and demo playback.
- `src/*`: Vite wrapper frontend, recording/playback rail, browser AI loop, and host styles.
- `app.py`: Flask API for recordings, traces, model calls, and local JSON stores.
- `agent/*`: candidate-agent backend analysis, prompting, model calls, traces, and loop filtering.
- `trace-dash.py`: read-only Streamlit and pandas trace dashboard.
- `scripts/*`: direct sanity checks, real-browser agent evaluator, and development launchers.
- `trace-analytics.ipynb`: read-only trace analytics notebook.

### Bootstrap Flow
1. Vite serves `index.html`.
2. `index.html` provides the root `<canvas id="canvas">`.
3. `src/app.js` inserts `<base href="/game/">`, loads ordered legacy scripts from `/game`, loads `lodeRunner.agentHooks.js` after `lodeRunner.main.js`, then calls `window.init()`.
4. The legacy runtime creates additional canvases and icon layers on `document.body`.

## Legacy Runtime
Important legacy files:
- `lodeRunner.main.js`: initialization, canvas sizing, state machine, map build, and `mainTick()`.
- `lodeRunner.runner.js`: runner movement, digging, gold pickup, collisions, and exit ladder behavior.
- `lodeRunner.guard.js`: guard movement, chase logic, trapping, gold carrying, and respawn.
- `lodeRunner.demo.js`: demo recording and playback.
- `lodeRunner.menu.js` and `lodeRunner.iconClass.js`: menus, side icons, mode transitions, and UI dialogs.
- `lodeRunner.storage.js`: local game settings, scores, custom levels, and editor state.

The legacy runtime is load-order dependent and uses shared globals.

## Game Data
Tile maps use fixed 28x16 ASCII grids:
- space / `.` empty
- `#` diggable brick
- `@` solid non-diggable block
- `H` ladder
- `-` rope
- `X` trap or dug hole
- `S` exit ladder
- `$` gold
- `0` guard
- `&` runner

Example game data:
```json
[
  "                  S         ",
  "                  S         ",
  "#######H#######   S         ",
  "       H----------S         ",
  "       H    ##H   #######H##",
  "       H    ##H          H  ",
  "       H    ##H          H  ",
  "##H#####    ########H#######",
  "  H                 H       ",
  "  H                 H       ",
  "#########H##########H       ",
  "         H          H       ",
  "         H----------H       ",
  "    H######         #######H",
  "    H                      H",
  "############################"
]
```

Legacy demo record:
```json
"demo": { "action": [], "level": 1, "ai": 4, "time": 90, "state": 1, "godMode": 0, "goldDrop": [], "bornPos": [] }
```
`demo.action` is a flat array of `[tick, keyCode, tick, keyCode, ...]` pairs.

## Wrapper Frontend
The Vite frontend is the bridge between the legacy runtime and the backend. It owns the AI and
playback controls, starts and advances the game through the hook, sends snapshots, and stores the
finished recording. It does not implement game physics or guard behavior. See [Recording and
playback](./record-playback.md) for the UI and [LLM agent](./llm-agent.md#browser-and-hook-lifecycle)
for the request lifecycle.

The frontend provides:

- recording persistence and selected-run playback;
- top debug overlay and playback pause/step controls;
- god-mode and fullscreen convenience buttons;
- browser-side AI solve loop;
- agent traces and opt-in raw model I/O debug logging through the Flask backend.

### Runtime Flow

Legacy snapshot → deterministic analysis → legal candidate generation/scoring → LLM selects
`candidateId` → generic validation fallback → legacy `keyCode`/`ticks` execution →
recording and trace persistence.

1. [src/agent.js](../src/agent.js) starts the configured game context through [public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js).
2. The hook starts the legacy game in Training/Modern playback context, stops the normal ticker, and exposes manual `snapshot()` / `step()` control.
3. The browser sends `playData`, `level`, `snapshot`, bounded `history`, `runId`, and optional model selection to `/api/agent/next-action`.
4. [app.py](../app.py) validates the request and calls `plan_next_action()`.
5. [agent/service.py](../agent/service.py) resolves the model and orchestrates candidate planning.
6. [agent/candidates.py](../agent/candidates.py), [agent/reasoning_tools.py](../agent/reasoning_tools.py), and [agent/loop_tools.py](../agent/loop_tools.py) analyze the snapshot/history, remove confirmed loop actions, and produce ranked eligible candidates.
7. [agent/prompt.py](../agent/prompt.py) asks the LLM to choose one candidate by ID.
8. The backend validates the selected candidate, applies one generic fallback for malformed or unsafe selection, and returns one bounded legacy action.
9. The browser steps the legacy runtime and repeats until success, failure, cancellation, the configured legacy playback-time limit, or the configured step limit.
10. [src/agent.js](../src/agent.js) saves the final successful or failed demo through the recording API.

## Agent Backend

`app.py` exposes the local API used by the frontend. The agent backend accepts a snapshot and
recent history, builds legal choices, asks the model to select one, validates the result, and saves
trace data. It does not simulate the game: the legacy runtime remains the authority for movement,
collisions, and terminal states.

See [Backend specification](./backend-spec.md) for APIs, configuration, and stored data;
[Candidate design](./candidate-design.md) for candidate rules; and [LLM agent](./llm-agent.md) for
the decision flow.

### Backend Modules

- [agent/config.py](../agent/config.py): constants, allowed keycodes, model normalization, default model lookup.
- [agent/service.py](../agent/service.py): request validation, `aisuite` client wrapper, one model call, candidate selection, and generic validation fallback.
- [agent/candidates.py](../agent/candidates.py): normalized analysis and candidate generation/ranking.
- [agent/reasoning_tools.py](../agent/reasoning_tools.py): deterministic snapshot helpers for movement, guard pressure, digging, route access, and progress facts.
- [agent/loop_tools.py](../agent/loop_tools.py): compact stationary, horizontal, and vertical cycle detection plus candidate suppression.
- [agent/prompt.py](../agent/prompt.py): compact candidate-selection prompt.
- [agent/traces.py](../agent/traces.py): compact trace serialization for `state`, candidates,
  selection, validation, action, and loop-monitor evidence.
- [agent/errors.py](../agent/errors.py): request/config/execution error types.
- [agent/logging_utils.py](../agent/logging_utils.py): low-noise Python logging setup.

## Architecture

The architecture keeps each layer responsible for one part of a decision:

- **Legacy runtime:** starts the game, applies keys, and decides what physically happens.
- **Frontend:** controls the run, captures snapshots, calls the backend, applies returned actions,
  and saves recordings.
- **Backend:** turns live state into legal candidates, validates the selected candidate, and writes
  traces.
- **Model:** selects from the supplied candidates; it cannot send raw keys or invent a route.
- **Tooling:** reads saved recordings and traces without changing a run.

The main boundary is the planner request: the frontend sends a snapshot and bounded history; the
backend returns one key/tick action. The following snapshot is the evidence of what that action
actually did. This avoids a second game simulator and keeps the legacy engine authoritative.

The main risk is drift between legacy state, browser snapshots, candidate analysis, and recorded
ticks. Hooks, compact traces, loop evidence, and trace-aligned playback make that boundary
inspectable.

## Related Docs
- [Legacy runtime](./legacy-runtime.md)
- [Puzzle game rules](./puzzle-game.md)
- [LLM game agent](./llm-agent.md)
- [Candidate design](./candidate-design.md)
- [Backend spec](./backend-spec.md)
- [Trace dashboard](./trace-dashboard.md)
- [Recording and playback](./record-playback.md)
- [Sanity tests](./sanity-tests.md)
