# User Recording JSON Store and Wrapper Playback

## Summary
Add a persisted user recording feature around the legacy game without editing `public/game/*`. The wrapper will capture successful user runs from the existing recording pipeline, save them through a Flask API to `data/recordings.json`, and play stored recordings for the current game version and level through the existing demo playback engine.

This will be a wrapper-owned playback mode, not a new legacy `PLAY_*` constant. The wrapper will drive playback through existing `PLAY_DEMO_ONCE` behavior because `startGame()` only supports the built-in modes.

## Key Changes
- Add `app.py` with Flask routes under `/api/recordings`.
- Add `requirements.txt` for Flask.
- Keep `data/recordings.json` as the mutable JSON file store.
- Keep Vite proxying `/api` to Flask on `localhost:5000`.

- Add wrapper recording logic in `src`, loaded from `src/app.js` after legacy scripts load.
- Runtime-patch `window.updatePlayerDemoData(playData, demoDataInfo)` so completed built-in `PLAY_CLASSIC` and `PLAY_MODERN` runs are saved to the Flask API.
- Do not persist failed runs by default, since the legacy game records them into `curDemoData` but does not promote them as usable demos.

- Add a small Vite-owned overlay in `src/style.css`.
- Show whether a stored user recording exists for the current `playData` and `curLevel`.
- Provide controls to refresh status and play the stored recording for the current level.
- Keep all controls outside legacy canvas menus.

## API and Data
- `GET /api/recordings` returns the full store.
- `GET /api/recordings/<playData>/<level>` returns one record or `404`.
- `PUT /api/recordings/<playData>/<level>` upserts one record.
- `DELETE /api/recordings/<playData>/<level>` removes one record if delete UI is included.

The store shape will be:

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
        "source": "user",
        "demo": {}
      }
    }
  }
}
```

## Playback Flow
- Overlay reads `window.playData` and `window.curLevel`.
- It fetches `/api/recordings/<playData>/<curLevel>`.
- It injects the stored `demo` into `window.playerDemoData[curLevel - 1]`.
- It sets `window.playMode = window.PLAY_DEMO_ONCE`, calls existing demo setup through `startGame(1)`, and lets the legacy runtime return to Training mode afterward.

## Test Plan
- Run Flask API on port `5000` and Vite dev server on port `8283`.
- Verify API reads/writes `data/recordings.json`.
- Run `npm run build`.
- Finish a built-in Challenge or Training level and confirm the JSON store is updated.
- Reload the page and confirm the overlay detects the stored record.
- Play the stored recording and confirm it replays through existing demo playback.
- Confirm `public/game/*` remains unchanged.

## Assumptions
- Persisted recordings are successful completed runs only.
- JSON persistence uses Flask in `app.py`, proxied by Vite.
- Store path is `data/recordings.json`.
- Initial playback scope is current selected level only.
- UI lives in the Vite wrapper overlay.
