# Repository Instructions

## Project Boundaries

- Treat `public/game/` as the legacy runtime and authoritative game engine. Avoid changing it unless the task requires legacy behavior changes.
- Prefer wrapper and backend changes in `src/`, `agent/`, `app.py`, and `public/agent-config.json`.
- `public/LLM_GAME_RULES.md` is an LLM gameplay prompt, not a coding-instruction file.
- Classic `playData=1`, `level=1` is the only supported agent context.

## Agent Architecture

- Maintain the V2 candidate flow: backend analysis and candidate generation, LLM `candidateId` selection, backend validation and key/tick translation.
- Do not restore raw-key planning, V1 compatibility, schema migration, or fallback formats unless explicitly requested.
- Keep raw prompt/model I/O out of traces; use `AGENT_DEBUG_LOG=1` for model-I/O diagnostics.
- Use `docs/backend-spec.md` for the trace contract; `docs/trace-dashboard.md` describes views and indicators.

## Data And Config

- Keep secrets in `.env` or `.env.local`; keep non-secret experiment controls in `public/agent-config.json`.
- `__data1/recordings.json` and `__data1/agent-traces.json` use flat stores. Recordings retain all pinned runs plus the newest 10 unpinned runs; traces retain runs linked by pinned recordings plus the newest 10 other runs. Agent recording IDs match their trace IDs.
- Do not rewrite generated data unless the task explicitly targets runtime data or schemas.
- New traces do not store Git provenance. Record it in a launch manifest before experiments and link it through the cohort catalog; otherwise mark it unknown.
- Before trace/cohort review, run `npm run cohorts:check` (read-only). Report uncataloged runs or stale links rather than assuming the catalog is complete. See `docs/trace-cohort.md` for catalog maintenance.
- When a requested run-review or campaign includes cataloging, reconcile with `npm run cohorts:check -- --write`, record evidence-backed provenance/classification for the reviewed run, and check again before reporting completion. Never infer a historical source revision from current HEAD. Pin changes require no catalog edit.

## Editing And Validation

- Inspect the affected code before editing and preserve unrelated worktree changes.
- Prefer focused changes; update the relevant existing document when public behavior, APIs, config, or schemas change.
- Choose commit buckets by intent: `Candidate:` is for experimental proposals; concrete bug fixes use `Fix:`. See [commit buckets](docs/llm-agent.md#commit-buckets).
- Keep `npm test` smoke-only, with shared small fixtures; avoid source-code inspection, exact wording assertions, and exhaustive gameplay matrices. Passing it does not establish gameplay improvement.
- Run `npm test`, `npm run build` for frontend changes, and Python compilation checks for backend changes.
- Run `git diff --check` before handoff, and report any checks that could not run.
