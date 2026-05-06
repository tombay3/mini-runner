# LLM Step Agent
## Summary
Implement the LLM agent as an interactive loop driven by the browser wrapper, with the legacy game as executor and recorder. Add `public/game/lodeRunner.agentHooks.js`, load it after `lodeRunner.main.js`, and keep existing legacy files unchanged.

The agent targets Classic level 1. It asks the backend LLM for one short action at a time, steps the legacy game manually, and saves the resulting demo on both success and failure. Successful recordings are replayable solutions; failed recordings are preserved for debugging.

## Key Changes
- Add `public/game/lodeRunner.agentHooks.js`.
  - Load it in `src/app.js` immediately after `/game/lodeRunner.main.js`.
  - Expose `window.lodeRunnerAgentHooks`.
  - Provide `startLevel(playData, level)`, `step(keyCode, ticks)`, `snapshot()`, `stop({ resumeTicker })`, `getRecordedDemo()`, `dumpFailure(reason)`, and `isSupportedContext(playData, level)`.
  - Start Classic level 1 through `PLAY_MODERN` with `playData = 1`, `curLevel = 1`, `levelData = getPlayVerData(1)`, and `startGame(1)`.
  - Stop the normal ticker after startup so wrapper code advances the game through `mainTick()` manually.
  - Keep `recordMode = RECORD_KEY` so the existing demo recorder captures actions, guard gold, and respawn positions.
  - On non-terminal agent failure, call the existing record dump path with a failed state so `curDemoData.state = 0`.

- Extend Flask in `app.py`.
  - Add `POST /api/agent/next-action`.
  - Use OpenAI Responses API with Structured Outputs where available, called server-side using standard-library HTTP.
  - Require `OPENAI_API_KEY` and `OPENAI_MODEL`; missing config returns `503`.
  - Accept only Classic level 1 for v1; unsupported requests return `400`.
  - Return `{ action: { keyCode, ticks, reason }, planner }`.
  - Clamp `ticks` to `1..20`.
  - Allowed keycodes: stop, left, right, up, down, dig-left, dig-right.

- Extend existing recording persistence.
  - `PUT /api/recordings/<playData>/<level>` accepts optional `source`, `solver`, and `result`.
  - Normal user recordings continue to default to `source: "user"` and `result: "success"` when `demo.state === 1`.
  - Agent recordings save with `source: "agent"`.
  - Agent success saves `result: "success"` and `demo.state = 1`.
  - Agent failure saves `result: "failure"`, `demo.state = 0`, and `solver.failureReason`.

- Extend `src/recording.js`.
  - Add a fourth rail icon for AI solve.
  - Enable it only for Classic level 1.
  - On click:
    - enter `busy="agent"`
    - call `lodeRunnerAgentHooks.startLevel(1, 1)`
    - loop through `snapshot()` → `/api/agent/next-action` → `step(keyCode, ticks)`
    - stop on success, death, invalid action, timeout, max iterations, or cancellation
  - On success:
    - get `curDemoData` through `getRecordedDemo()`
    - save it to `/api/recordings/1/1` with `source: "agent"` and `result: "success"`
  - On failure:
    - call `dumpFailure(reason)` if needed
    - get failed `curDemoData`
    - save it to `/api/recordings/1/1` with `source: "agent"` and `result: "failure"`
  - Keep normal Play/Refresh/Delete behavior unchanged; failed recordings can still be played back for debugging.

- Extend `src/style.css`.
  - Add visual state for `data-action="agent"` and `data-busy="agent"`.
  - Keep the rail fixed and CSS-first.

## Prompt And Snapshot
- Prompt includes:
  - puzzle rules from `docs/puzzle-game.md`
  - tile legend and allowed keycodes
  - current 28x16 grid
  - runner position/action
  - guard positions/actions/hasGold
  - remaining gold and `goldComplete`
  - current tick/time/game state
  - recent action history
- The model returns strict JSON only:
  - `keyCode`
  - `ticks`
  - `reason`
- Backend validates shape; legacy runtime validates behavior.

## Test Plan
- Backend:
  - `.venv/bin/python -m py_compile app.py`
  - missing OpenAI config returns `503`
  - unsupported level returns `400`
  - mocked valid action normalizes correctly
  - `PUT /api/recordings/1/1` stores `source`, `solver`, and `result`
  - failed demo with `state = 0` is accepted

- Frontend/build:
  - `npm run build`
  - verify `lodeRunner.agentHooks.js` loads after `lodeRunner.main.js`
  - verify the agent icon appears and is enabled only for Classic level 1
  - verify agent mode stops the normal ticker and steps through hooks
  - verify snapshots include live map, runner, guard, gold, and state data
  - verify successful finish saves `source: "agent"`, `result: "success"`
  - verify death, timeout, invalid action, or cancellation saves `source: "agent"`, `result: "failure"`
  - verify existing user record, play, refresh, delete, and playback still work

## Assumptions
- `public/game/lodeRunner.agentHooks.js` is the only planned new legacy-side file.
- Existing legacy files are changed only if hook loading or manual stepping exposes a small compatibility issue.
- Agent runs Classic level 1 through Training/Modern mode to avoid challenge-mode life and score side effects.
- The legacy runtime remains authoritative for game physics, guard AI, recording, success, and failure.
- Agent-generated success or failure recordings may overwrite the Classic level 1 recording slot.
