# Recording JSON API

## Summary
The wrapper persists replayable demos through the Flask API while leaving `public/game/*` as the gameplay source of truth.

Current mutable store:

- [__data1/recordings.json](../__data1/recordings.json)

The store keeps one latest recording per `playData` / `level` slot. User recordings and agent recordings share the same replay path.

## API
- `GET /api/recordings`: returns the full store.
- `GET /api/recordings/<playData>/<level>`: returns one record or `404`.
- `PUT /api/recordings/<playData>/<level>`: upserts one record.
- `DELETE /api/recordings/<playData>/<level>`: removes one record.

Agent trace helpers:

- `GET /api/agent/traces/<trace_id>`: returns the latest retained trace payload.
- `GET /api/agent/runs/<playData>/<level>`: returns latest run metadata plus saved recording if present.

## Record Shape
Records are stored by numeric string keys:

```json
{
  "version": 1,
  "updatedAt": "2026-05-03T00:00:00.000Z",
  "recordings": {
    "1": {
      "1": {
        "playData": 1,
        "level": 1,
        "savedAt": "2026-05-03T00:00:00.000Z",
        "source": "agent",
        "result": "failure",
        "solver": {
          "traceId": "..."
        },
        "traceRef": "...",
        "demo": {}
      }
    }
  }
}
```

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

## Agent Recording Flow
[src/agent.js](../src/agent.js) runs the AI loop through [public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js).

At the end of an agent run:

- success saves `source="agent"` and `result="success"`.
- failure saves `source="agent"` and `result="failure"`.
- solver metadata and `traceRef` link the recording to the latest agent trace.

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

## Wrapper UI
The recording UI is a CSS-first left icon rail in [src/recording.js](../src/recording.js) and [src/style.css](../src/style.css).

Current rail actions:

- `AI`: run the Classic level 1 agent.
- `Play`: play the stored recording.
- `Refresh`: refresh recording availability.
- `Delete`: delete the stored recording.
- `Star`: toggle legacy god mode.
- `Fullscreen`: enter/exit fullscreen and soft-reinitialize the legacy game.

The UI stays outside legacy canvas menus and does not modify `public/game/*`.
