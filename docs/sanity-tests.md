# Sanity Tests

## Purpose

`npm test` is a fast **smoke check**, not a comprehensive gameplay regression suite.
It exercises local functions and the Flask test client without starting services, a browser,
the legacy engine or a model call. Small synthetic fixtures check that the main paths still work.

```sh
npm test
```

The existing launcher uses the project virtual environment directly:
`.venv/bin/python` on Linux/macOS or `.venv/Scripts/python.exe` on Windows.
A missing environment produces setup guidance; it does not fall back to system Python.

## Backend smoke

`scripts/sanity_backend.py` shares a temporary recording/trace-store setup. It checks:

- health and supported-context request validation;
- one trace write/read and recording save/finalize/list lifecycle;
- pin/unpin, pinned deletion protection and linked-trace deletion;
- pinned retention plus the ten newest unpinned runs.

It never writes to real `__data1`. Trace shape is checked through stored/API output, not source-code inspection.

## Candidate smoke

`scripts/sanity_candidates.py` runs ordinary-progress, guarded and post-gold exit fixtures through
the same output check: a nonempty bounded pool, unique IDs, finite scores, valid key/tick actions,
unchanged input and basic trace serialization. It does not assert exact scores or tactical choices.

## Frontend/helper smoke

`scripts/sanity_frontend.mjs` uses the existing helper exports and a small resettable fake window.
It checks config/action limits, game-time limits, completion waiting for its recording refresh,
basic mode switching, non-mutating demo normalization, trace playback alignment and one evaluator summary.

## Trace data check

`scripts/sanity_traces.mjs` remains a separate read-only check of the four local data files:
recording/trace structure and ID links, cohort links and readable debug-log format.
Missing files are reported as uninitialized; uncataloged traces are warnings.
It respects `AGENT_DATA_DIR`; run it while data writers are idle.

## Coverage boundaries and validation

The smoke suite intentionally omits detailed guard/loop/scoring regressions, prompt/UI wording,
formatting variants and configuration-shape assertions. Passing it does not establish safety,
completion reliability or protection against every previously observed gameplay bug.
Add a focused reproducer when investigating a concrete defect rather than rebuilding a large matrix.

After implementation changes, run `npm test`, relevant Python compilation, `npm run build`
for browser-wrapper changes and `git diff --check`. For a separate real-browser boot check, use
`npm run eval -- --smoke`; actual model-driven trials require their own approval and budget.
See [Evaluator](evaluator.md). No browser or paid runs are part of the default smoke suite.
