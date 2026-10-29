# Recording And Playback

## Summary
The wrapper adds stored-run selection and playback around the legacy demo engine. The legacy game
still records and replays demos; the wrapper persists records and provides debug controls.

## Icon Rail
`src/recording.js` owns the left wrapper rail:

- `AI`: start or cancel the game agent.
- `Play`: play, pause, or resume the recording.
- `Ctrl`/`Command` + `Play`: play the recording and record as video.
- `Prev` / `Next`: cycle through the records for the current level.
- `Delete`: delete the recording.
- `Star`: toggle legacy god mode.
- `Fullscreen`: enter or exit fullscreen and restart the legacy game.

The rail is wrapper-owned UI and does not modify legacy menus.

### State And Availability

The wrapper derives button state from the current game level, selected recording, active
operation, playback phase, and backend availability. State uses `currentGameLevel` to identify `<playData>:<level>`, such as `1:1`.

- `AI` is disabled while backend availability is offline.
- Clicking an active red `AI` button cancels the current agent run.

Visual style is consistent across the rail:

- neutral: available but inactive;
- blue rail: a wrapper operation is busy;
- red rail: the latest wrapper operation failed;
- green: active playback or god mode;
- amber: paused playback or action/trace stepping;
- red button: active AI run or browser video recording;
- green outline: active fullscreen;
- muted red: enabled Delete action.

## Stored Run Selection
The wrapper loads `GET /api/recordings/<playData>/<level>/records` and keeps a selected record index.

- Records are sorted newest-first.
- Manual completions are saved as user records; agent completions are saved only by the agent flow.
- Prev/next buttons and Tab/Shift-Tab shortcuts cycles through retained records
- Play and delete operate on the selected record.
- Delete asks for confirmation before sending the selected record id; agent record ids are their trace ids.

## Playback Flow
When Play starts a selected record:

1. the wrapper normalizes the stored `demo`;
2. writes it into `window.playerDemoData[curLevel - 1]`;
3. sets `window.playMode = window.PLAY_DEMO_ONCE`;
4. calls the legacy `startGame(1)` path.

Ctrl-clicking Play, or Command-clicking on macOS, requests browser display capture before
playback starts. The browser controls the source picker; current-tab capture cannot be
forced. If capture is allowed, the wrapper records until playback ends or is cancelled and
downloads `run-<short-id>-<timestamp>.mp4`. Recording requires browser-native MP4 support;
if MP4 encoding is unavailable or capture is denied, normal playback still starts without
video recording.

## Debug Overlay
The top debug line appears as UI overlay when a stored run is selected, except while an AI run is
being recorded. It shows selected-run metadata and playback progress.
The ribbon groups the run ID, optional `📌` pin marker, and result icon before the saved time,
demo duration, and playback progress: `1/9: b86760a1 📌 ✅ | 10-25 01:14 | 0:49 | steps 149`.

Agent playback compares `window.demoTickCount` with ticks loaded from
`/api/agent/traces/<traceId>`. User playback uses the demo action cursor:
`keys <demoRecordIdx>/<demo.action.length / 2>`.

## Playback Debug Controls
Keyboard shortcuts (hotkeys) control the selected stored recording:

- `Tab`: select the next stored run when rail navigation is available.
- `Shift-Tab`: select the previous stored run when rail navigation is available.
- `Space`: when playback is inactive, start the selected recording already paused; otherwise pause or resume playback.
- `,`: while paused, advance one recorded key/action segment (`demo.action` in `recordings.json`) → pause again.
- `.`: while paused, advance one trace step (`run.steps` in `agent-traces.json`) → pause again.

Trace steps and demo key events have different boundaries. One trace step may
cross zero, one, or several recorded action segments.

## Fullscreen Restart
The legacy game computes canvas and icon geometry during `init()`. Entering or leaving fullscreen
restarts from the welcome flow so that sizing runs for the new viewport. Before `window.init()`, the
wrapper removes stale legacy canvas overlays but keeps the root `#canvas` and wrapper rail.
