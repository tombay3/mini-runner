# Add God-Mode Support for the LLM Agent

## Summary
Use the existing legacy god-mode implementation instead of creating a new mode. Add a wrapper star button that calls the existing toggle path, preserve god mode when the AI agent starts, and expose god-mode state in the agent snapshot so `prompt.py` can add conditional guidance only when god mode is active.

## Key Changes
- Preserve legacy behavior:
  - Keep existing hotkeys: `SHIFT-G` and `CTRL-Z` already call `toggleGodMode()`.
  - Use the existing global `godMode`, `godModeKeyPressed`, and `sometimePlayInGodMode`.
  - Do not change collision physics: legacy `setRunnerDead()` already ignores guard death when `godMode` is enabled.
- Update `public/game/lodeRunner.agentHooks.js`:
  - Add `godMode` and `godModeKeyPressed` to `snapshot()`.
  - In `startLevel()`, capture whether `godMode` was active before calling `startGame(1)`, because `startGame()` calls `initHotKeyVariable()` and resets god mode.
  - If god mode was active at AI entry, restore `godMode = 1`, `godModeKeyPressed = 1`, and `sometimePlayInGodMode = 1` after `startGame(1)` so the agent run and saved demo reflect god-mode usage.
- Update `agent/prompt.py`:
  - Add a conditional `God mode:` section only when `snapshot.godMode` is true.
  - Tell the model that guard contact will not kill the runner in this run, so it can deprioritize retreat/digging for survival and focus on collecting gold, route changes, ladders, ropes, digging for access, and exit routing.
  - Keep normal danger and guard-risk sections for non-god-mode runs.
- Update wrapper rail in `src/recording.js`:
  - Add a final yellow star button after delete.
  - The star calls legacy `window.toggleGodMode()` when available.
  - Sync the star state from `window.godMode`, including after hotkey toggles, by extending the existing periodic rail refresh.
  - Disable the star when legacy toggle support is unavailable or while another wrapper action is busy.
- Update `src/style.css`:
  - Add yellow active styling for the star button when `data-god-mode="true"`.
  - Keep the star visually distinct from the yellow demo-playback `▶` state by using a stronger filled/star-specific style.

## Interface / Behavior
- The star button is UI sugar over the existing legacy god-mode hotkey behavior.
- If god mode is active before clicking `AI`, the agent run starts in god mode even though legacy `startGame()` normally resets hotkey variables.
- Agent recordings should continue using the existing demo field `godMode`; successful or failed god-mode agent runs should persist `godMode: 1` through the existing recording path.
- If god mode is not active before clicking `AI`, no god-mode prompt guidance is added.

## Test Plan
- Static checks:
  - `.venv/bin/python -m py_compile agent/*.py`
  - `node --check public/game/lodeRunner.agentHooks.js`
  - `npm run build`
- Legacy behavior checks:
  - `SHIFT-G` and `CTRL-Z` still toggle god mode.
  - The star button toggles the same state and displays the same legacy tip text.
  - Star active styling follows both button toggles and hotkey toggles.
- Agent checks:
  - With god mode off, AI snapshot includes `godMode: false` and prompt contains no god-mode section.
  - With god mode on before clicking `AI`, `startLevel()` preserves `godMode: true` after `startGame(1)`.
  - Prompt includes god-mode-specific strategy guidance only in that case.
  - Guard collision during a god-mode agent run does not end the run through `GAME_RUNNER_DEAD`.
  - Saved agent demo includes `godMode: 1` when god mode was used.

## Assumptions
- God mode is intended as an optional solving aid, not the default agent behavior.
- The star button should not introduce a separate wrapper-only god-mode flag; legacy globals remain the source of truth.
- God-mode prompt guidance should reduce survival anxiety but still acknowledge guards can block paths, carry gold, and affect routing.
