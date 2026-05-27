# God Mode and the Agent

## Summary
God mode is the existing legacy feature, not a wrapper-only mode. The wrapper adds a star button for convenience and the agent preserves god mode when it starts a run.

The current V2 candidate agent treats god mode as a planning signal: guard contact is non-lethal, so progress candidates should outrank survival-only retreat or trap behavior unless movement is physically blocked.

## Legacy Behavior
Existing legacy hotkeys still apply:

- `SHIFT-G`
- `CTRL-Z`

Both call the legacy `toggleGodMode()` path. The source of truth remains the legacy globals:

- `godMode`
- `godModeKeyPressed`
- `sometimePlayInGodMode`

The wrapper does not replace collision physics. Legacy `setRunnerDead()` already avoids ending the run when `godMode` is active.

## Wrapper Star Button
[src/recording.js](../src/recording.js) adds a star button to the left icon rail.

The star button:

- calls `window.toggleGodMode()` when available
- syncs state from `window.godMode`
- follows hotkey changes
- disables while wrapper actions are busy

[src/style.css](../src/style.css) gives the active star a distinct yellow style.

## Agent Startup
[public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js) captures whether god mode was active before `startGame(1)`.

This matters because the legacy start path resets hotkey state. If god mode was active before clicking `AI`, `startLevel()` restores:

- `godMode = 1`
- `godModeKeyPressed = 1`
- `sometimePlayInGodMode = 1`

The saved demo can therefore reflect that the agent run used god mode.

## Agent Planning
The snapshot includes `godMode`. Backend analysis and candidate generation use it to alter ranking and feasibility:

- guard-occupied movement can be considered passable when terrain otherwise allows it
- progress toward gold, ladders, route access, and exit should outrank spacing/retreat
- defensive digging is still available, but should not dominate when guard contact is non-lethal
- non-god-mode survival rules remain strict

Current V2 prompting does not need a large separate god-mode rule block. God-mode behavior is primarily encoded in deterministic candidate generation and stall handling, with concise state/rules exposed to the model.

## Current Limits
- God mode is optional and must be enabled before clicking `AI` if the agent run should use it.
- God mode is a solving aid, not a separate replay mode.
- The agent is still scoped to Classic `playData=1`, `level=1`.
