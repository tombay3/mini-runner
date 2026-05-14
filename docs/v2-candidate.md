# V2 Candidate-Action Lode Runner Agent

## Summary
Refactor the current LLM agent from “free-form raw keyCode planner plus many guardrails” into a simpler candidate-action planner for Classic level 1. The backend will compute a small set of legal, useful candidates from the live snapshot; the LLM will choose one `candidateId`; the backend will translate that candidate into `{ keyCode, ticks }`; the legacy browser runtime remains the only executor and recorder.

This intentionally excludes demo-path guidance, few-shot examples, Python simulation, full pathfinding, and runtime multi-model benchmarking for v2.

## Key Changes

### Backend Agent Flow
- Keep `/api/agent/next-action` as the browser-facing endpoint.
- Internally replace raw action planning with:
  `snapshot + history -> candidate analysis -> LLM candidate choice -> backend action translation -> guard validation -> response`.
- Keep `aisuite` as the single-model provider abstraction.
- Disable or remove automatic tool-heavy reasoning from the normal runtime path; candidate generation should happen in Python before the LLM call.
- Keep traces, but restructure them around:
  `snapshotSummary`, `candidates`, `selectedCandidateId`, `translatedAction`, `validation`, and `planner`.

### Candidate Model
- Add a backend candidate representation with fields like:
  `id`, `kind`, `label`, `goal`, `target`, `firstAction`, `preconditions`, `stopConditions`, `score`, `risk`, `reason`.
- Candidate `firstAction` is the only thing translated to the legacy runtime for the current step.
- Candidate IDs must be stable, descriptive, and unique per step, for example:
  `collect_gold_17_14_right`, `align_ladder_27_14_right`, `climb_ladder_27_14_up`, `route_access_dig_right`, `godmode_progress_left`.
- LLM output must be strict JSON:
  ```json
  { "candidateId": "collect_gold_17_14_right", "reason": "Nearest same-row gold is reachable by moving right." }
  ```
- Backend rejects unknown candidate IDs. Optional v2 fallback: if the LLM returns invalid JSON or unknown ID, choose the highest-scored candidate and mark trace `fallbackUsed=true`.

### Candidate Generation
- Generate candidates from existing snapshot facts:
  terrain grid, runner position, guard positions, gold positions, `goldComplete`, `godMode`, current ladder, legal movement, legal dig, and recent history.
- Start with these candidate kinds:
  `collect_same_row_gold`, `align_ladder`, `climb_ladder`, `route_access_dig`, `descend_route`, `defensive_dig`, `retreat_from_guard`, `godmode_progress`, `exit_ladder_route`, `wait_or_stop`.
- Only emit candidates whose first action is physically valid from the current snapshot.
- Use simple ranking:
  if `goldComplete=true`: exit ladder route first.
  if non-god-mode critical guard danger: valid climb, defensive dig, retreat.
  otherwise: same-row gold, current ladder climb, align ladder, route-access dig, route progress.
  in god mode: progress candidates outrank survival candidates unless movement is physically blocked.
- Return only the top 4-7 candidates to the LLM.

### Prompt Simplification
- Make `agent/prompt.py` present only:
  current concise state summary, candidate list, selection rules, and strict JSON output contract.
- Move durable gameplay policy into `public/AGENT_RULES.md`, but keep it shorter because candidates already encode legality.
- Remove prompt sections that duplicate candidate analysis, especially detailed movement/dig/escape/route-access blocks.
- Keep terrain grid optional or minimized. For v2, prefer object-centric summaries and candidate targets over asking the model to parse the full board every step.

### Streamlining `agent/`
- Split current reasoning logic into clearer layers:
  `state_analysis`: extracts normalized live facts from snapshot/history.
  `candidates`: generates and scores candidate actions.
  `prompt`: formats candidate-selection prompt.
  `service`: orchestrates model call, candidate validation, trace assembly.
- Retire most one-off guardrails once candidates enforce legality:
  repeated ladder vetoes, route-access side mismatch, reason/keyCode mismatch, route-access tick repair, and many god-mode progress retries should become unnecessary.
- Keep only minimal validation:
  selected candidate exists, translated action is still physically valid, ticks are bounded, and unsupported level returns `400`.
- Keep old helper functions only if reused by candidate generation; otherwise delete or quarantine them after tests pass.

## API / Interface Changes
- Request shape can remain compatible:
  browser still sends `snapshot`, `history`, and optional `options`.
- Response still includes:
  `action`, `planner`, `traceId`.
- Add response/debug fields:
  `candidateId`, `candidate`, and optional `candidates` summary for trace/debug visibility.
- No changes to legacy `public/game/*` executor behavior.
- No changes to recording schema are required, except traces will become candidate-centric.

## Test Plan
- Backend unit checks:
  - Candidate generator emits same-row gold candidate at Classic level 1 start.
  - Candidate generator emits `align_ladder` then `climb_ladder` near `(27,14)`.
  - Candidate generator emits `route_access_dig` when lower gold requires access digging.
  - God mode ranks progress over retreat when guard contact is non-lethal.
  - Non-god-mode critical guard pressure still emits defensive candidates first.
  - Unknown candidate ID is rejected or falls back to top candidate with trace marker.
- Prompt checks:
  - Prompt contains candidate list and strict `candidateId` output contract.
  - Prompt no longer asks the model to invent raw `keyCode`.
  - Prompt is materially shorter than the current full affordance prompt.
- Integration checks:
  - `.venv/bin/python -m py_compile agent/*.py`.
  - `npm run build`.
  - Start Classic level 1 agent mode and confirm `/api/agent/next-action` returns translated `{ keyCode, ticks }`.
  - Verify success and failure recordings still save.
  - Verify traces show candidates, selected candidate, translated action, and validation result.
- Regression checks:
  - Agent icon, recording playback, delete, refresh, god-mode star, and fullscreen rail behavior remain unchanged.
  - Unsupported levels still return `400`.
  - Existing user recording/playback flow remains independent of agent mode.

## Assumptions
- V2 remains scoped to Classic `playData=1`, `level=1`.
- The LLM chooses among backend-generated candidates only; it does not output raw keyCodes.
- No demo-path guidance, few-shot examples, pathfinding, Python simulation, or runtime model benchmarking in v2.
- The legacy game remains authoritative for physics, guard behavior, terminal state, demo recording, and playback.
- `aisuite` remains useful as provider abstraction, but not as a multi-tool reasoning framework on every step.
