# Recording And Playback

## Summary
The wrapper adds stored recording selection and playback around the legacy demo engine. The legacy game still records and replays demos; the wrapper persists records, selects retained runs, and provides debugging controls.

## Icon Rail
`src/recording.js` owns the left wrapper rail:

- `AI`: start or cancel the Classic level 1 agent.
- `Play`: play, pause, or resume the selected stored recording.
- `Ctrl`/`Command` + `Play`: play the selected stored recording and record the browser tab.
- `Prev` / `Next`: cycle through retained records for the current level.
- `Delete`: delete the selected recording and its linked trace when present.
- `Star`: toggle legacy god mode.
- `Fullscreen`: enter or exit fullscreen and restart the legacy game.

The rail is wrapper-owned UI and does not modify legacy menus.

### State And Availability

The wrapper derives button state from the current game level, selected recording, active
operation, playback phase, and backend availability. The composite game-level identity is
named `currentGameLevel` and formatted as `<playData>:<level>`, for example `1:1`.

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
- Prev/next cycles through retained records.
- Play and delete operate on the selected record.
- Delete sends the selected record id; agent record ids are their trace ids.

## Playback Flow
When Play starts a selected record:

1. the wrapper normalizes the stored `demo`;
2. writes it into `window.playerDemoData[curLevel - 1]`;
3. sets `window.playMode = window.PLAY_DEMO_ONCE`;
4. calls the legacy `startGame(1)` path.

Ctrl-clicking Play, or Command-clicking on macOS, requests browser display capture before
playback starts. The browser controls the source picker; current-tab capture cannot be
forced. If capture is allowed, the wrapper records until playback ends or is cancelled and
downloads `run-<short-id>-<timestamp>.webm` (or `.mp4` when that is the selected recorder
format). Denying capture still starts normal playback.

## Debug Overlay
The top gutter overlay appears when a stored run is selected, except while an AI run is
being recorded. It shows selected-run metadata and playback progress:

```text
run 2/10 | agent failure | trace 46d79a4d | model minimax:MiniMax-M2.1 | demo 90s | steps 3/18
```

For agent recordings, progress is aligned by comparing `window.demoTickCount` with trace step ticks loaded from `/api/agent/traces/<traceId>`. For user recordings without traces, progress uses the legacy demo action cursor: `keys <demoRecordIdx>/<demo.action.length / 2>`.

## Playback Debug Controls
Keyboard shortcuts apply only during wrapper-started stored playback:

- `Space`: pause or resume playback.
- `.`: while paused, advance one recorded key/action segment (`demo.action` in `recordings.json`) → pause again.
- `,`: while paused, advance one trace step (`run.steps` in `agent-traces.json`) → pause again.

Trace stepping is aligned by trace step tick, which can cross zero, one, or many recorded demo action segments because trace steps and demo key events are different timelines.

## Fullscreen Restart
The legacy game computes canvas and icon geometry during `init()`. Entering or exiting fullscreen restarts from the welcome flow so the legacy sizing code reruns against the new viewport.  Before calling `window.init()`, the wrapper removes stale legacy-created canvas overlays while preserving the root `#canvas` and wrapper rail.
