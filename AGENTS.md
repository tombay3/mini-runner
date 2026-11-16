# Repository instructions

## Where to make changes

- `public/game/` is the authoritative legacy engine. Change it only when the task requires legacy
  behavior changes. Prefer `src/` for browser controls, `agent/` for planning, and `app.py` for
  APIs and storage.
- The agent supports only Classic `playData=1`, `level=1`. Keep the V2 decision flow. Python
  generates candidates, the model selects a `candidateId`, Python validates it and returns a key
  and tick count, and the browser steps the engine.
- Keep raw-key planning, V1 compatibility, schema migrations, and alternate fallback formats out
  of scope unless explicitly requested. [Candidate design](docs/candidate-design.md)
- `public/LLM_GAME_RULES.md` guides the gameplay model. Keep secrets in `.env` or `.env.local` and
  non-secret experiment controls in `public/agent-config.json`.
- Use the [backend specification](docs/backend-spec.md#trace-api-and-store) for the V4 storage
  contract and the [dashboard guide](analytics/README.md) for derived indicators. Keep raw
  prompts and model responses out of traces. Enable `AGENT_DEBUG_LOG=1` for model I/O diagnostics.

## Keep run evidence intact

- Preserve generated data unless the task explicitly targets runtime data or schemas. The flat
  stores in `__data1/` link each agent recording to its trace by the same ID.
- `recordings.json` owns pins. Keep all pinned recordings and the newest ten unpinned recordings.
  In `agent-traces.json`, keep traces linked to pinned recordings plus the newest ten other runs.
- Before an experiment, capture the revision and worktree state in a launch manifest and link it
  from the catalog. Mark unavailable provenance unknown. Never infer a historical revision from
  current HEAD.
- Pin new evaluation and experiment runs through the recording API or CLI after persistence unless
  the user requests otherwise. Pin changes need no catalog edit.
- Archive a complete recording/trace pair for a specific future comparison, reproducer, or
  unresolved investigation. Keep ordinary completed and pinned runs in the live stores. Archive an
  entire campaign only on explicit request.
  [Archive criteria](analytics/cohorts.md#when-to-archive-a-live-run)

## Review and catalog runs

1. Run `npm run cohorts:check` read-only before review. Report uncataloged pairs, stale links, and
   missing evidence.
2. Add only complete, matching recording/trace pairs to gameplay cohorts or replay archives.
   Exclude active and orphaned traces from new-run review lists. Record infrastructure-only
   failures in campaign logs or reports.
3. When cataloging is requested, run `npm run cohorts:check -- --write`, record evidence-backed
   provenance and classification, then check again. Preserve historical findings, groups,
   comparisons, and verified archive links when live data is deleted or unavailable.
   [Cohort workflow](analytics/cohorts.md)

## Edit and validate

- Inspect affected code first. Preserve unrelated worktree edits and update the existing
  documentation when public behavior, APIs, configuration, or schemas change.
- Choose commit prefixes by intent. Use `Fix:` for a demonstrated bug and `Candidate:` for a
  proposed gameplay change. [Commit conventions](docs/llm-agent.md#commit-buckets)
- Run `npm test`. Keep smoke checks small and behavioral, using shared fixtures. Avoid source
  inspection, exact wording assertions, and exhaustive gameplay matrices. Use focused regressions
  for the affected behavior. Gameplay improvement requires gameplay evidence.
- Run `npm run build` for frontend changes and Python compilation checks for backend changes. Run
  `git diff --check` before handoff and report any checks you could not run.
  [Validation guide](docs/sanity-tests.md)
