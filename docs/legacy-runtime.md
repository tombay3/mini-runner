# Legacy Runtime Assessment

This document assesses the original
[`SimonHung/LodeRunner_TotalRecall`](https://github.com/SimonHung/LodeRunner_TotalRecall)
codebase preserved under `public/game/`. It intentionally focuses on the legacy game before
the Vite wrapper, Flask backend, and LLM agent were introduced.

- Standalone browser-based platform game written in vanilla JavaScript
- Open-source HTML5 Total Recall remake of the classic 1983 game **Lode Runner**
- Goal: collect gold while using ladders, ropes, and digging to avoid guards
- Challenge, Training, Edit, and Demo modes
- Five bundled level sets
- CreateJS canvas rendering, game loop, state management, asset loading, and input
- Original entry point at `lodeRunner.html`, with ordered global scripts

## Overall Assessment And Functionality

`LodeRunner_TotalRecall` is a comprehensive and faithful HTML5 remake of the classic game.
Its main strength is its completeness as a playable archive of multiple Lode Runner releases,
not only a single-level clone.

### Game Modes

- **Challenge Mode:** compete for scores and progress through levels.
- **Training Mode:** select and practice individual levels.
- **Edit Mode:** create, test, save, and share custom levels.
- **Demo Mode:** play recorded solutions for supported levels.

### Game Versions

1. Classic Lode Runner: 150 levels
2. Professional Lode Runner: 150 levels
3. Revenge of Lode Runner: 17 levels
4. Lode Runner Fan Book: 66 levels
5. Championship Lode Runner: 51 levels

The runtime also provides Apple II and Commodore 64 themes, keyboard control variants,
gamepad support, local high scores, and browser-local user levels.

## Technology Stack

- **JavaScript:** gameplay, state management, input, rendering orchestration, menus, editor,
  demos, and storage.
- **CreateJS:** EaselJS canvas display, TweenJS animation, PreloadJS asset loading, and
  SoundJS audio.
- **HTML:** static entry point and root canvas.
- **C++ tools:** offline disk/puzzle parsers used to extract level data; they are not part of
  the browser runtime.

The legacy application uses no frontend framework or module system. Scripts are loaded in a
fixed order and communicate through shared global variables and functions.

## Architecture

### Core Engine

- `lodeRunner.main.js`: initialization, canvas sizing, state machine, map construction,
  display layers, timing, and `mainTick()`.
- `lodeRunner.def.js`: tile, action, key, game-state, storage, and sizing constants.
- `lodeRunner.key.js`: keyboard input, pause/resume, hotkeys, themes, speed, and god mode.
- `lodeRunner.misc.js`: browser, sound, timing, and utility helpers.

### Entities And Physics

- `lodeRunner.runner.js`: movement, falling, ladder/rope behavior, digging, gold pickup,
  collision checks, hole filling, and exit-ladder reveal.
- `lodeRunner.guard.js`: chase policy, movement, gold carrying/dropping, trapping, climbing
  from holes, death, and respawn.

Actors use grid coordinates plus sub-tile `xOffset` and `yOffset` values for smooth
movement. The fixed 28x16 `map[x][y]` grid has two layers:

- `base`: structural/objective tile such as brick, ladder, rope, trap, or gold.
- `act`: current active occupancy, including runner and guards.

### Data, UI, And Persistence

- `lodeRunner.demo.js`: legacy demo recording and playback using flat tick/key pairs.
- `lodeRunner.menu.js` and `lodeRunner.iconClass.js`: menus, dialogs, and side controls.
- `lodeRunner.edit.js`: custom-level editor and test flow.
- `lodeRunner.storage.js`: localStorage-backed settings, scores, and user levels.
- `lodeRunner.preload.js` and `lodeRunner.colorTheme.js`: assets, sprite sheets, sounds,
  and palette/theme handling.
- `lodeRunner.v.*.js`: bundled level maps.

## Legacy Assessment

The runtime is mature, feature-rich, and self-contained. Its global, load-order-dependent
architecture makes isolated changes difficult, but it faithfully centralizes gameplay rules
and demo behavior. For the current Mini Runner integration, it should remain the authority
for physics, guard AI, terminal states, rendering, recording, and playback.
