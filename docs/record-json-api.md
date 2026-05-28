# Recording JSON API

## Summary
The wrapper persists replayable demos through the Flask API while leaving `public/game/*` as the gameplay source of truth.

Mutable store:

- [__data1/recordings.json](../__data1/recordings.json)

The store is a flat V2-only map of up to 10 newest records. There is no nested `playData` / `level` bucket schema and no migration from older shapes.

## API
- `GET /api/recordings`: returns the full flat store.
- `GET /api/recordings/<playData>/<level>`: returns the newest matching record or `404`.
- `PUT /api/recordings/<playData>/<level>`: saves a new flat record and prunes the store to 10 newest records.
- `DELETE /api/recordings/<playData>/<level>`: deletes the newest matching record and its linked trace when present.
- `DELETE /api/recordings/<playData>/<level>?traceId=<traceId>`: deletes that record id and the matching agent trace.

Agent trace helpers:

- `GET /api/agent/traces/<trace_id>`: returns one retained trace run.
- `GET /api/agent/runs/<playData>/<level>`: returns latest run metadata plus saved recording if present.

## Store Shape
```json
{
  "version": 1,
  "updatedAt": "2026-05-28T00:00:00.000Z",
  "records": {
    "<recordId>": {
      "id": "<recordId>",
      "playData": 1,
      "level": 1,
      "savedAt": "2026-05-28T00:00:00.000Z",
      "source": "agent",
      "result": "failure",
      "traceId": "<traceId>",
      "solver": {},
      "demo": {}
    }
  }
}
```

Record ids:

- Agent recordings use `traceId` as `id`.
- User recordings use `user:<timestamp>` unless an explicit `id` is sent.
- Incoming `traceRef` is accepted only as a temporary request alias and is stored as `traceId`.

`source` is usually:

- `user`: manual successful built-in runs captured from the legacy recording pipeline.
- `agent`: AI runs saved by [src/agent.js](../src/agent.js), including success and failure demos.

`result` is usually:

- `success`: completed replayable solution.
- `failure`: debugging replay from an aborted, killed, timed-out, or stalled agent run.

## User Recording Flow
[src/recording.js](../src/recording.js) patches `window.updatePlayerDemoData(playData, demoDataInfo)` after the legacy scripts load.

Manual user recordings are persisted only when the legacy runtime promotes a completed built-in run:

- `PLAY_CLASSIC`
- `PLAY_MODERN`

Failed manual attempts are not saved by default.
Stored-demo playback started from the wrapper `Play` button is also not saved as a new user recording, even if the replay completes successfully.

## Agent Recording Flow
[src/agent.js](../src/agent.js) runs the AI loop through [public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js).

At the end of an agent run:

- success saves `source="agent"` and `result="success"`.
- failure saves `source="agent"` and `result="failure"`.
- `traceId` links the recording to the matching agent trace.
- the recording `id` is the same value as `traceId`.

Solver metadata is intentionally logical/user-facing:

- `modelProfile`
- `provider`
- `model`
- `generatedAt`
- `responseId`
- `traceId`
- `failureReason` for failed runs

Obsolete transport details such as `aisuiteProvider` and `aisuiteModel` are backend internals and are not persisted in recording solver metadata.

Agent failures are intentionally persisted because they are useful for debugging stalls, deaths, and bad planning choices.

## Playback Flow
The wrapper playback button:

1. fetches `/api/recordings/<playData>/<curLevel>`.
2. injects the stored `demo` into `window.playerDemoData[curLevel - 1]`.
3. sets legacy playback through `PLAY_DEMO_ONCE`.
4. calls the existing legacy start path.

Playback still uses the legacy demo engine. The wrapper does not introduce a new legacy `PLAY_*` constant.

## Deletion
The delete button removes the current stored recording.

- If the current record has `traceId`, the wrapper calls `DELETE ...?traceId=<traceId>`.
- The backend deletes the flat record whose `id` equals that value.
- The backend also deletes the matching retained trace run.
- The response includes `latestRecord`, which lets the rail fall back to the next newest matching recording when one exists.

## Wrapper UI
The recording UI is a CSS-first left icon rail in [src/recording.js](../src/recording.js) and [src/style.css](../src/style.css).

Current rail actions:

- `AI`: run the Classic level 1 agent.
- `Play`: play the stored recording.
- `Refresh`: refresh recording availability.
- `Delete`: delete the current stored recording and linked agent trace when `traceId` exists.
- `Star`: toggle legacy god mode.
- `Fullscreen`: enter/exit fullscreen and soft-reinitialize the legacy game.

The UI stays outside legacy canvas menus and does not modify `public/game/*`.
