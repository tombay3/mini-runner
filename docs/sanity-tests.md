# Sanity Tests

## Summary
`npm test` runs lightweight direct-function sanity tests for the wrapper frontend and Flask
backend. These tests are intended as a fast regression check after wrapper/API refactors.
They do not execute the legacy game engine, run browser UI automation, or call the LLM
planning endpoint.

Use `npm run evaluate -- --smoke` for the separate real-browser boot check, or
`npm run evaluate` for actual model-driven normal-mode trials. See
[Agent evaluation](./evaluation.md).

```bash
npm test
```

The command runs:

```bash
node scripts/sanity.mjs
```

The launcher uses the project virtual environment directly, so shell activation is not required:

- macOS/Linux: `.venv/bin/python`
- Windows: `.venv/Scripts/python.exe`

If `.venv` is missing, the launcher exits with setup guidance instead of falling back to a
system Python that may not have Flask or other project dependencies installed.

## Backend Coverage
`scripts/sanity_backend.py` uses Flask `app.test_client()` and redirects recording/trace stores into a temporary directory. It does not write to real `__data1`.

Notable checks:

- `GET /api/health` returns a healthy response.
- Recording save/list/delete behavior works against the flat `records` store.
- User recordings and agent recordings are normalized differently; agent recordings require `traceId`.
- Deleting an agent recording also deletes its linked trace run.
- Saving an agent recording finalizes its linked trace with result, reason, and compact
  terminal runner/guard state.
- Recording and trace retention keep only the newest 10 entries.
- Invalid recording payloads and invalid agent request payloads are rejected with request errors.

## Frontend Coverage
`scripts/sanity_frontend.mjs` imports `_test` helper exports from `src/agent.js` and `src/recording.js`. It stubs only the minimal `window` state needed for pure helper behavior.

Notable checks:

- Public agent config normalization clamps limits and preserves model profile selection.
- Agent actions are validated and tick counts are clamped.
- AI playback time limits use legacy game time, with `recordTick` fallback.
- History snapshots are summarized into compact runner/gold state.
- Terminal snapshots preserve compact runner, guard, and gold state for outcome diagnosis.
- Model profile precedence is URL `?profile=...`, then `window.__lodeRunnerAgentOptions`, then public config.
- Stored demos are normalized without mutating source arrays.
- Playback progress aligns agent traces by trace step ticks and user demos by recorded key events.
- Overlay state derives button availability from backend status, cached recordings, busy actions,
  and the current playback phase.
- AI button state distinguishes server checking, server offline, supported context, and an active
  cancellable run.
- Playback video filenames and MIME selection stay stable for browser tab recording.

## When To Run
Run `npm test` after changes to:

- recording APIs or JSON store handling;
- wrapper playback controls, overlay state, or video recording helpers;
- agent browser loop configuration and action normalization;
- trace loading, trace progress, or selected-run navigation.

For release-style checks, also run:

```bash
npm run build
git diff --check
```
