# Project Assessment

The original GitHub repository `SimonHung/LodeRunner_TotalRecall` is preserved in `public/game/*` with only minimal modifications.  Its CreateJS runtime remains the gameplay source of truth.

- Standalone browser-only Web-based platform game clone, written in pure-Vanilla Javascript
- Open-source HTML5 "Total Recall" remake of the classic 1983 retro game **Lode Runner**
- Goal: collect gold while avoiding enemies with ladders/ropes, and digging traps
- Game-modes: Challenge, Training, Edit and Demo Mode, with 5 complete level sets
- codebase: game loop, state management, CreateJS canvas, asset loading, user input
- existing entrypoint at lodeRunner.html, loading ordered global scripts and states

Analyze entire codebase to understand its current functionality to make an overall assessment. Document its Architecture, technology stack and notable info in one page

## 1. Overall Assessment and Functionality

The `LodeRunner_TotalRecall` repository is a comprehensive and faithful **HTML5 remake of the classic 1983 game Lode Runner**. The project's primary goal is to preserve the original game's experience while making it accessible in any modern web browser. It is not just a simple clone; it's a "Total Recall" package that bundles multiple versions and features of the Lode Runner series.

**Current Functionality:**

* **Multiple Game Modes:** The project supports four distinct modes:
    * **Challenge Mode:** For competing with other players.
    * **Training Mode:** Allows the player to select and practice any level.
    * **Edit Mode:** A full-featured level editor for creating and saving custom levels.
    * **Demo Mode:** Automatically plays back solutions for completed levels.
* **Multiple Game Versions:** It includes the complete level sets from five different official and fan-made games:
    1.  Classic Lode Runner (150 Levels)
    2.  Professional Lode Runner (150 Levels)
    3.  Revenge of Lode Runner (17 Levels)
    4.  Lode Runner Fan Book (66 Levels)
    5.  Championship Lode Runner (51 Levels)
* **Theming & Controls:** It provides two visual themes (APPLE-II and Commodore 64) and two different keyboard control schemes (emulating APPLE-II and NES behaviors).

**Overall Assessment:**
The project is a mature and feature-rich client-side application. Its main strength is its completeness as an archive and playable history of the Lode Runner series. The codebase is written in a classic, "vanilla" style, prioritizing functionality over modern development paradigms.

## 2. Architecture, Technology Stack, and Notable Info

Here is a one-page summary documenting the project's technical details.

* **Project:** Lode Runner - Total Recall
* **Description:** A high-fidelity HTML5 remake of the classic Lode Runner series.
* **Live/Playable:** The game can be played locally by running a simple web server.

### Technology Stack

* **Core Language:** **JavaScript (96.0%)**
    * The game logic, state management, and rendering are all handled using **plain "vanilla" JavaScript** (likely ES5/ES6).
    * There is **no evidence of modern frameworks** (like React, Vue, or Angular) or state management libraries (like Redux or MobX).
* **Structure:** **HTML (0.5%)**
    * A single `lodeRunner.html` file likely serves as the entry point, defining the canvas and loading all necessary scripts.
* **Minor Components:** **C++ (3.5%)**
    * This small percentage likely refers to utility scripts or tools included in the `tools` directory, not the core game engine itself, which is pure JavaScript.

### Architecture

* **Client-Side Monolith:** The application is a traditional, monolithic frontend application. It runs entirely in the user's web browser.
* **Script-Include Structure:** The architecture does not use modern JavaScript modules (like `import`/`export`). Instead, logic is separated into multiple `.js` files (e.g., `lodeRunner.def.js`, `lodeRunner.demo.js`, `lodeRunner.colorTheme.js`). These files are likely loaded sequentially via `<script>` tags in the main HTML file.
* **Global Namespace:** This structure typically relies on a shared global namespace (`window` object) for communication between its different "modules" (e.g., `window.lodeRunner` might be a global object holding all game logic).
* **Rendering:** The game is rendered to an **HTML5 `<canvas>` element**, with the main game loop and rendering logic controlled by JavaScript.

### Source files Analysis

* **Core Engine & Definitions**: These files define the game loop, states, constants, and the main entry point:
    * lodeRunner.main.js
    * lodeRunner.def.js
    * lodeRunner.key.js
    * lodeRunner.misc.js

* **Game Entities**: These files likely contain the logic for the player and enemies:
    * lodeRunner.runner.js
    * lodeRunner.guard.js
    * lodeRunner.iconClass.js

* **Game Mechanics & Data**: These files manage levels, menus, storage, and graphics:
    * lodeRunner.storage.js
    * lodeRunner.preload.js
    * lodeRunner.menu.js
    * lodeRunner.colorTheme.js

* **Game Loop (lodeRunner.main.js)**: The engine is driven by CreateJS's Ticker which fires the mainTick() loop. playGame() advances the state of the game, managing time, digging, and delegating movement to moveRunner() and moveGuard().
* **Grid System (lodeRunner.def.js & main.js)**: The game runs on a 28x16 grid (NO_OF_TILES_X x NO_OF_TILES_Y). The map[x][y] array tracks the state using dual layers: .base (what the tile inherently is, like BLOCK_T or EMPTY_T) and .act (active state, like RUNNER_T or GUARD_T occupying the tile).
* **Input Handling (lodeRunner.key.js)**: Keyboard events are trapped and translated into global keyAction states (ACT_LEFT, ACT_DIG_RIGHT, etc.), which moveRunner() processes on the next tick. It also includes extensive hotkeys for debugging, god mode, theme switching, and gamepads.
* **Entity Movement (runner.js & guard.js)**: how the AI works in lodeRunner.guard.js (using the movePolicy matrix and bestMove() pathfinding logic), and how player collisions, digging, and smooth grid movement are handled in lodeRunner.runner.js.  Movement handles both logical grid positions (pos.x, pos.y) and sub-tile smooth transitions (pos.xOffset, pos.yOffset), making sure entities align with ladders and bars perfectly.
* **Data & Mechanics (lodeRunner.storage.js)**: localStorage to save high scores, user levels, and game states, lodeRunner.menu.js for the UI flow.
* **Assets & Themes (colorTheme.js & preload.js)**: CreateJS SpriteSheet objects handle the retro animations. lodeRunner.colorTheme.js dynamically manipulates canvas pixels (getImageData/putImageData) to swap between the Apple-II and C64 color palettes.

### Notable Information

* **Legacy runtime:** The original game is still playable as a static web app on `/game/lodeRunner.html`.
* **Wrapper runtime:** leverage the legacy game as executor, recorder, renderer, and playback engine.
* **Python Backend:** Record & playback and the LLM agent use Flask APIs and JSON stores under `__data1`.
* **Game Assets:** includes sounds, level data, and bundled demo data as-is from legacy runtime.
* All development happens in the wrapper/backend. Legacy files only need to expose existing runtime state.
* The legacy runtime remains authoritative for game physics, guard AI, terminal success/failure.
