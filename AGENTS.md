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

## Data And Config

- Keep secrets in `.env` or `.env.local`; keep non-secret experiment controls in `public/agent-config.json`.
- `__data1/recordings.json` and `__data1/agent-traces.json` use flat stores retaining the newest 10 runs. Agent recording IDs match their trace IDs.
- Do not rewrite generated data unless the task explicitly targets runtime data or schemas.

## Editing And Validation

- Inspect the affected code before editing and preserve unrelated worktree changes.
- Prefer focused changes; update the relevant existing document when public behavior, APIs, config, or schemas change.
- Run `npm test` for sanity checks, `npm run build` for frontend changes, and Python compilation checks for backend changes.
- Run `git diff --check` before handoff, and report any checks that could not run.
