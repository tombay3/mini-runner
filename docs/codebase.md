# LodeRunner_TotalRecall Codebase Context

No files were changed during the contextualization pass. This document is the runtime-first handoff for the current `LodeRunner_TotalRecall` codebase.

## Environment

- Entrypoint is [public/game/lodeRunner.html:1](../public/game/lodeRunner.html), a plain HTML page that loads ordered global scripts and calls `init()` on body load.
- The game is not currently wired as a normal Vite app. Verification: `npm run build` fails with `Could not resolve entry module "index.html"`, so the repo is effectively a static HTML app wrapped by Vite config rather than a Vite entrypoint.

## Load Order

- Boot/data first:
  [public/game/lodeRunner.wData.js:1](../public/game/lodeRunner.wData.js),
  CreateJS libs,
  [public/game/flag32Id.js:1](../public/game/flag32Id.js),
  [public/game/lodeRunner.gameVerName.js:1](../public/game/lodeRunner.gameVerName.js)
- Content second:
  version files `lodeRunner.v.*.js` define built-in level arrays.
- Core globals/utilities next:
  [public/game/lodeRunner.storage.js:1](../public/game/lodeRunner.storage.js),
  [public/game/lodeRunner.def.js:1](../public/game/lodeRunner.def.js),
  [public/game/lodeRunner.key.js:1](../public/game/lodeRunner.key.js),
  [public/game/lodeRunner.misc.js:1](../public/game/lodeRunner.misc.js)
- UI/game systems:
  hi-score, info, menu, icon classes, runner, guard, demo, demoData1, edit, preload, theme/color selector, gamepad
- Orchestration last:
  [public/game/lodeRunner.main.js:64](../public/game/lodeRunner.main.js),
  [public/game/lodeRunner.win.js:1](../public/game/lodeRunner.win.js),
  [public/game/lodeRunner.share.js:1](../public/game/lodeRunner.share.js)
- Practical rule: this codebase is load-order dependent. Later scripts assume earlier globals already exist.

## Architecture Brief

- Initialization lives in [public/game/lodeRunner.main.js:64](../public/game/lodeRunner.main.js). `init()` sizes the canvas, creates the stage, loads local state, initializes menus/demo/edit metadata, then starts the cover-page preload flow.
- Asset bootstrapping lives in [public/game/lodeRunner.preload.js:38](../public/game/lodeRunner.preload.js). It loads cover assets first, then all theme sprites, icons, sounds, and sprite sheets, and finally enables play UI.
- The runtime loop is in `mainTick()` in [public/game/lodeRunner.main.js:1338](../public/game/lodeRunner.main.js). It is a state machine over `GAME_*` constants, not an entity/component architecture.
- Map construction is centralized in `buildLevelMap()` in [public/game/lodeRunner.main.js:389](../public/game/lodeRunner.main.js). Each tile becomes `map[x][y] = { base, act, bitmap }`, with `base` for terrain and `act` for dynamic occupancy.
- Runner behavior is in [public/game/lodeRunner.runner.js:8](../public/game/lodeRunner.runner.js). It owns movement rules, dig/fill-hole lifecycle, gold pickup, collision checks, and hidden-ladder reveal triggers.
- Guard AI is in [public/game/lodeRunner.guard.js:28](../public/game/lodeRunner.guard.js). It uses grid/path heuristics plus version-sensitive behavior gated by `AI_VERSION` and `curAiVersion`.
- Menus and mode switching are split between [public/game/lodeRunner.menu.js:1633](../public/game/lodeRunner.menu.js) and [public/game/lodeRunner.iconClass.js:1](../public/game/lodeRunner.iconClass.js). Menu dialogs choose mode/version/level; icon classes pause runtime, open dialogs, and resume.
- The editor is a full mode, not a small overlay. [public/game/lodeRunner.edit.js:55](../public/game/lodeRunner.edit.js) owns custom-map editing, test mode, save/load, copy/paste, and re-entry into gameplay.

## Feature Ownership

- Game constants, tile encoding, play/game states, storage keys: [public/game/lodeRunner.def.js:1](../public/game/lodeRunner.def.js)
- Main startup, stage lifecycle, map build, game loop, transitions, level progression: [public/game/lodeRunner.main.js:64](../public/game/lodeRunner.main.js)
- Asset and sprite/sound bootstrapping: [public/game/lodeRunner.preload.js:38](../public/game/lodeRunner.preload.js)
- Player movement/dig/hole/gold: [public/game/lodeRunner.runner.js:8](../public/game/lodeRunner.runner.js)
- Guard movement/AI/reborn/trap handling: [public/game/lodeRunner.guard.js:28](../public/game/lodeRunner.guard.js)
- Menus, version selection, play-mode entry, backup/restore dialogs: [public/game/lodeRunner.menu.js:1633](../public/game/lodeRunner.menu.js)
- Toolbar icons and pause/resume wrappers: [public/game/lodeRunner.iconClass.js:1](../public/game/lodeRunner.iconClass.js)
- Local persistence, custom levels, test-level state, theme/repeat/gamepad/player settings: [public/game/lodeRunner.storage.js:1](../public/game/lodeRunner.storage.js)
- Demo recording/playback and bundled fast-demo ingestion: [public/game/lodeRunner.demo.js:1](../public/game/lodeRunner.demo.js), [public/game/lodeRunner.wData.js:1](../public/game/lodeRunner.wData.js)
- Share URL format and import path: [public/game/lodeRunner.share.js:1](../public/game/lodeRunner.share.js)
- Themes, recoloring, theme selector, gamepad, input, info/help/high score: `colorTheme`, `colorSelector`, `gamepad`, `key`, `info`, `hiscore`

## State And Data Map

- Play modes in [public/game/lodeRunner.def.js:86](../public/game/lodeRunner.def.js):
  `PLAY_CLASSIC`, `PLAY_MODERN`, `PLAY_DEMO`, `PLAY_EDIT`, `PLAY_TEST`, `PLAY_AUTO`, `PLAY_DEMO_ONCE`
- Game states in [public/game/lodeRunner.def.js:89](../public/game/lodeRunner.def.js):
  `GAME_START`, `GAME_RUNNING`, `GAME_FINISH`, `GAME_FINISH_SCORE_COUNT`, `GAME_WAITING`, `GAME_PAUSE`, `GAME_NEW_LEVEL`, `GAME_RUNNER_DEAD`, `GAME_OVER_ANIMATION`, `GAME_OVER`, `GAME_NEXT_LEVEL`, `GAME_PREV_LEVEL`, `GAME_LOADING`, `GAME_WIN`
- Tile encoding is fixed 28x16 ASCII maps:
  space empty, `#` brick, `@` solid, `H` ladder, `-` rope, `X` trap, `S` hidden ladder, `$` gold, `0` guard, `&` runner
- Built-in content format:
  each `lodeRunner.v.*.js` exports an array of concatenated 16-row strings
- Demo format:
  `{ level, ai, time, state, godMode, action[], goldDrop[], bornPos[] }`
- Local storage keys:
  last play mode, classic progress, modern progress, demo progress, first-run marker, modern scores, custom-level progress/scores, edit metadata, per-level custom maps, transient test map, hi-score table, last score, player name, UID, theme mode, per-theme color, repeat-action mode, gamepad mode
- Custom-level lifecycle:
  editor writes transient state to `STORAGE_TEST_LEVEL`, successful save commits into `STORAGE_USER_LEVEL###` plus `STORAGE_EDIT_INFO`, and test/play modes rehydrate from that transient state

## External Boundaries

- Runtime gameplay is fully local once assets are present.
- “World demo” data is bundled in UTF-16 [public/game/lodeRunner.wData.js:1](../public/game/lodeRunner.wData.js), and `getDemoData()` in [public/game/lodeRunner.misc.js:275](../public/game/lodeRunner.misc.js) reads those globals directly.
- Share links are local URL encodings of compressed maps plus metadata in [public/game/lodeRunner.share.js:1](../public/game/lodeRunner.share.js).
- Backup/restore for custom levels is browser-side file import/export through menu dialogs, not a server workflow.
- Hi-scores are local-only in current repo state.

## Risks For Future Changes

- Highest risk is mutable shared global state. Most files read and write the same globals without module boundaries.
- Load order is semantic, not cosmetic. Moving scripts or converting piecemeal to modules will break hidden dependencies quickly.
- Mode switching is distributed across `main`, `menu`, `iconClass`, `edit`, and `demo`; gameplay changes often need coordinated edits in more than one file.
- Editor/test/play flows share persistent transient state. Changing custom-level behavior means touching both `edit.js` and `storage.js`.
- Theme changes are runtime bitmap rewrites, not CSS skinning. Visual changes usually involve `preload`, `colorTheme`, `iconClass`, and asset assumptions.
- There is a likely broken edge in share mode: [public/game/lodeRunner.share.js:103](../public/game/lodeRunner.share.js) assigns `PLAY_DATA_SHARE`, but that constant is not defined anywhere in the loaded runtime. Treat share-path work as fragile until that is resolved.
- The repo includes Vite config, but packaging assumptions do not match the actual HTML entry structure. Any build-system work should be handled as a separate task from gameplay changes.

## Code Generation Handoff

- Stable extension seams:
  new gameplay rules usually belong in `runner.js`, `guard.js`, or `main.js`;
  new menus/dialogs in `menu.js`;
  new toolbar actions in `iconClass.js`;
  new persisted settings in `storage.js` plus `def.js`;
  new built-in content in `lodeRunner.v.*.js`
- Fragile seams:
  anything that changes startup order, global names, mode transitions, or `map[x][y]` semantics
- Practical rule for follow-up work:
  decide first whether the change is engine, mode/UI, persistence, or content. That classification predicts the files that must change together better than the file names do.

## Verification

Verification was completed by cross-checking the runtime scripts, bundled data formats, and the current packaging behavior.
