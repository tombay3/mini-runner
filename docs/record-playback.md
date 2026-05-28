# Recording And Playback

## Summary
The wrapper adds stored recording selection and playback around the legacy demo engine. The legacy game still records and replays demos; the wrapper persists records, selects retained runs, and provides debugging controls.

## Icon Rail
`src/recording.js` owns the left wrapper rail:

- `AI`: start or cancel the Classic level 1 agent.
- `Play`: play, pause, or resume the selected stored recording.
- `Prev` / `Next`: cycle through retained records for the current level.
- `Delete`: delete the selected recording and linked trace when present.
- `Star`: toggle legacy god mode.
- `Fullscreen`: enter or exit fullscreen and restart the legacy game.

The rail is wrapper-owned UI and does not modify legacy menus.

## Stored Run Selection
The wrapper loads `GET /api/recordings/<playData>/<level>/records` and keeps a selected record index.

- Records are sorted newest-first.
- Prev/next cycles through retained records.
- Play and delete operate on the selected record.
- Delete uses `recordId` when available and falls back to `traceId` for agent records.

## Playback Flow
When Play starts a selected record:

1. the wrapper normalizes the stored `demo`;
2. writes it into `window.playerDemoData[curLevel - 1]`;
3. sets `window.playMode = window.PLAY_DEMO_ONCE`;
4. calls the legacy `startGame(1)` path.

Wrapper-started playback is guarded so replay completion does not create a new user recording.

## Debug Overlay
The top gutter overlay shows selected-run metadata and playback progress:

```text
run 2/10 | agent failure | trace 46d79a4d | model minimax:MiniMax-M2.1 | demo 90s | steps 3/18
```

The overlay is hidden while the AI agent is actively recording a run. It is visible when a stored record is selected and updates live during wrapper-started playback.

For agent recordings, progress is aligned by comparing `window.demoTickCount` with trace step ticks loaded from `/api/agent/traces/<traceId>`. For user recordings without traces, progress uses the legacy demo action cursor: `keys <demoRecordIdx>/<demo.action.length / 2>`.

## Playback Debug Controls
Keyboard shortcuts apply only during wrapper-started stored playback:

- `Space`: pause or resume playback.
- `.`: while paused, advance one recorded action segment and pause again.

One recorded action segment means the next consumed `[tick, keyCode]` pair in `demo.action`.

## Failed Demo Stop
Failed agent demos are persisted for debugging. During failed-demo playback, the wrapper stops playback when the legacy demo cursor reaches the stored failed demo time.

## Fullscreen Restart
The legacy game computes canvas and icon geometry during `init()`. Entering or exiting fullscreen restarts from the welcome flow so the legacy sizing code reruns against the new viewport.

Before calling `window.init()`, the wrapper removes stale legacy-created canvas overlays while preserving the root `#canvas` and wrapper rail.
