# Testing and validation

## Commands

Run from the repository root with the project `.venv` installed:

| Command | Scope | Side effects |
| --- | --- | --- |
| `npm test` | Backend/frontend smoke checks | Temporary stores and small fixtures; no services or model calls |
| `npm run test:regression` | Focused Python and JavaScript regressions | Temporary files and inert child processes; no model calls |
| `npm run data:check` | Local recording, trace, cohort, and debug-log checks | Read-only; run while writers are idle |
| `npm run cohorts:check` | Catalog availability and links | Read-only; reports uncataloged traces |
| `npm run build` | Browser-wrapper build | Writes generated build output |
| `npm run eval -- --smoke` | Real-browser wrapper/backend/engine startup | Starts or reuses services; no model calls |

Python commands use `.venv/bin/python` on Linux/macOS or
`.venv/Scripts/python.exe` on Windows. A missing environment produces setup guidance;
the launchers do not fall back to system Python.

## Backend smoke

`scripts/sanity_backend.py` uses the Flask test client and temporary stores. It checks:

- Health, supported requests, and JSON errors for invalid request bodies.
- Trace write/read and recording save/finalize/list behavior.
- Pinning, pinned deletion protection, linked-trace deletion, and retention.
- Candidate output and basic trace serialization.

Production `__data1` is never written. Tests inspect outputs, not source-code text.

## Candidate smoke

Three small fixtures cover ordinary progress, guard pressure, and post-gold exit state.
They require a nonempty bounded pool, unique IDs, finite scores, valid actions,
unchanged input, and serializable traces. They do not assert tactical choices or
exact scores.

## Frontend/helper smoke

`scripts/sanity_frontend.mjs` checks configuration/action limits, game-time limits,
mode switching, demo copying, trace alignment, and one evaluator summary. A small
CreateJS hook fixture checks exit-target extraction; it does not run a full game.

## Focused regressions

Exactly two shared scripts hold regressions:

- `scripts/regression_backend.py`: planner, guard, ladder, loop, provider, and parsing cases.
- `scripts/regression.mjs`: wrapper lifecycle/stepping, launcher behavior, and hybrid runtime cases.

The JavaScript entry point runs the Python suite first and propagates failures.
Detailed planner cases live outside the default smoke run. Both suites reuse small
fixtures; avoid per-area runners or a configurable gameplay-scenario framework.

Run relevant regressions during active development. As risk decreases, select runs
by the changed area; retain useful tests. Remove tests when obsolete, redundant,
or tied to implementation details, not simply because confidence has increased.
Passing deterministic tests does not establish autonomous gameplay improvement.

## Trace data check

`npm run data:check` invokes `scripts/sanity_traces.mjs` against `__data1`, or
`AGENT_DATA_DIR`. It checks recording/trace structure, IDs, cohort links, and debug-log
readability. It is separate from code smoke tests:

- Missing files mean uninitialized data.
- Missing linked traces and uncataloged traces produce warnings.
- Malformed stores, mismatched agent IDs, and stale cohort links fail.

The cohort checker owns reconciliation; the data check never rewrites stores.

## Coverage boundaries and validation

After changes, run `npm test`, relevant regressions, Python compilation, and
`git diff --check`. Run `npm run build` for browser-wrapper changes. Use temporary
stores and dummy provider configuration; model calls require a separate run budget.

Smoke checks intentionally omit broad guard/scoring matrices and exact prompt/UI
wording. Real-browser smoke verifies startup, not successful gameplay. See
[Evaluator](evaluator.md) for browser and paid-run controls.

## Behavior-preserving planner cleanup

Freeze the pre-edit source and configuration, including uncommitted changes. Check
cohort links, then recover engine snapshots and bounded history from retained
recordings. Verify observed states and terminal outcomes against traces first.
Historical traces may come from older code; use the frozen source as the comparison.

Compare candidate order, IDs, scores, actions, explanations, analysis/audits, loop
reports, both prompt modes, and selection/fallback trace projections. Omit volatile
timestamps only. Fixed-action playback alone does not prove planner equivalence.
Keep comparison artifacts outside tracked source and live stores; report uncovered paths.

## Planner policy simplification

Inspect changes to scores, order, membership, actions, and durations separately.
Rank the full admitted pool before truncation; check the leading choice at smaller
limits. Clearance forecasts are ranking estimates, not physical safety guarantees.

For changed leading choices, replay the recorded prefix and compare baseline/changed
bursts at the decision boundary. Report immediate collisions and progress separately
from longer recovery or completion. If paid evidence is needed, use matched hybrid
continuations with an early-stop bound where possible. Follow the workstream's
current authorization and budget.
