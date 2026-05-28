# Codebase Overview

## Summary
This repository runs Lode Runner Total Recall through a root Vite wrapper while preserving the original CreateJS runtime under `public/game/*`.

Current layers:

- `public/game/*`: legacy gameplay, rendering, menus, input, editor, demo recording, and demo playback.
- `src/*`: Vite wrapper boot, recording/playback rail, browser AI loop, and host styles.
- `app.py`: Flask API for recordings, traces, model calls, and local JSON stores.
- `agent/*`: candidate-agent backend analysis, prompting, model calls, traces, and stall handling.

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

Legacy demo records use:

```json
{ "level": 1, "ai": 4, "time": 90, "state": 1, "godMode": 0, "action": [], "goldDrop": [], "bornPos": [] }
```

`demo.action` is a flat array of `[tick, keyCode, tick, keyCode, ...]` pairs.

## Wrapper Responsibilities
The wrapper adds tooling without replacing legacy gameplay:

- recording persistence and selected-run playback;
- top debug overlay and playback pause/step controls;
- god-mode and fullscreen convenience buttons;
- browser-side AI solve loop;
- agent traces and raw model I/O debug logging through the Flask backend.

Fullscreen changes restart the legacy game from the welcome flow so `init()` recalculates canvas and icon geometry.

## Current Docs
- [Assessment](./assessment.md)
- [Puzzle game rules](./puzzle-game.md)
- [LLM candidate agent](./llm-agent.md)
- [Backend spec](./backend-spec.md)
- [Recording and playback](./record-playback.md)
