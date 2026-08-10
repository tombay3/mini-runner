# Codebase Overview

## Summary
This repository runs Lode Runner Total Recall through a root Vite wrapper while preserving the original CreateJS runtime under `public/game/*`.

Current layers:

- `public/game/*`: legacy gameplay, rendering, menus, input, editor, demo recording, and demo playback.
- `src/*`: Vite wrapper boot, recording/playback rail, browser AI loop, and host styles.
- `app.py`: Flask API for recordings, traces, model calls, and local JSON stores.
- `agent/*`: candidate-agent backend analysis, prompting, model calls, traces, and loop filtering.
- `dash.py` and `loader.py`: read-only Streamlit and pandas trace dashboard.
- `scripts/*`: direct sanity checks, real-browser agent evaluator, and a read-only trace analytics notebook.

## Root Boot Flow
1. Vite serves `index.html`.
2. `index.html` provides the root `<canvas id="canvas">`.
3. `src/app.js` inserts `<base href="/game/">`, loads ordered legacy scripts from `/game`, loads `lodeRunner.agentHooks.js` after `lodeRunner.main.js`, then calls `window.init()`.
4. The legacy runtime creates additional canvases and icon layers on `document.body`.

The wrapper uses same-document globals. It does not iframe the game and does not convert legacy scripts into modules.

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

Classic `playData=1`, `level=1` sample:

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

Legacy demo records use:

```json
"demo": { "action": [], "level": 1, "ai": 4, "time": 90, "state": 1, "godMode": 0, "goldDrop": [], "bornPos": [] }
```

`demo.action` is a flat array of `[tick, keyCode, tick, keyCode, ...]` pairs.

## Wrapper Responsibilities
The wrapper adds tooling without replacing legacy gameplay:

- recording persistence and selected-run playback;
- top debug overlay and playback pause/step controls;
- god-mode and fullscreen convenience buttons;
- browser-side AI solve loop;
- agent traces and opt-in raw model I/O debug logging through the Flask backend.

### Runtime Flow

Legacy snapshot → deterministic analysis → legal candidate generation/scoring → LLM selects
`candidateId` → generic validation fallback → legacy `keyCode`/`ticks` execution →
recording and trace persistence.

1. [src/agent.js](../src/agent.js) starts Classic level 1 through [public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js).
2. The hook starts the legacy game in Training/Modern playback context, stops the normal ticker, and exposes manual `snapshot()` / `step()` control.
3. The browser sends `playData`, `level`, `snapshot`, bounded `history`, `runId`, and optional model selection to `/api/agent/next-action`.
4. [app.py](../app.py) validates the request and calls `plan_next_action()`.
5. [agent/service.py](../agent/service.py) resolves the model and orchestrates candidate planning.
6. [agent/candidates.py](../agent/candidates.py), [agent/reasoning_tools.py](../agent/reasoning_tools.py), and [agent/loop_tools.py](../agent/loop_tools.py) analyze the snapshot/history, remove confirmed loop actions, and produce ranked eligible candidates.
7. [agent/prompt.py](../agent/prompt.py) asks the LLM to choose one candidate by ID.
8. The backend validates the selected candidate, applies one generic fallback for malformed or unsafe selection, and returns one bounded legacy action.
9. The browser steps the legacy runtime and repeats until success, failure, cancellation, the configured legacy playback-time limit, or the configured step limit.
10. [src/agent.js](../src/agent.js) saves the final successful or failed demo through the recording API.

### Backend Module Map
Current backend agent modules:

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

## Current Assessment

The architecture has a useful separation of responsibilities: the legacy engine owns
physics and execution, deterministic Python code owns legal action construction, the LLM
chooses among constrained candidates, and the wrapper owns orchestration and replay. The
backend does not maintain a second game simulator.

The main technical risk is synchronization across legacy global state, browser snapshots,
candidate heuristics, trace history, and recorded tick timelines. Structured hooks, compact
traces, loop-filter evidence, and tick-aligned playback controls make these boundaries
observable and debuggable.

Current agent scope remains intentionally narrow: Classic `playData=1`, `level=1`.

## Current Docs
- [Legacy runtime](./legacy-runtime.md)
- [Puzzle game rules](./puzzle-game.md)
- [LLM candidate agent](./llm-agent.md)
- [Candidate design](./candidate-design.md)
- [Backend spec](./backend-spec.md)
- [Trace dashboard](./trace-dashboard.md)
- [Recording and playback](./record-playback.md)
- [Sanity tests](./sanity-tests.md)
