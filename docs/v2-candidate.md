# V2 Candidate-Action Lode Runner Agent

## Summary
V2 is the current agent architecture. It replaced the earlier free-form raw-keyCode planner with a candidate-action planner for Classic level 1.

The backend computes a small set of legal, useful candidates from the live snapshot. The LLM chooses one `candidateId`. The backend translates that candidate into `{ keyCode, ticks }`. The legacy browser runtime remains the only executor and recorder.

This intentionally excludes demo-path guidance, few-shot examples, Python simulation, full pathfinding, default `aisuite` tool-calling, and runtime multi-model benchmarking.

## Key Changes

### Backend Agent Flow
- Keep `/api/agent/next-action` as the browser-facing endpoint.
- Internally use:
  `snapshot + history -> candidate analysis -> LLM candidate choice -> backend action translation -> guard validation -> response`.
- Keep `aisuite` as the single-model provider abstraction.
- Disable automatic tool-heavy reasoning from the normal runtime path; candidate generation happens deterministically in Python before the LLM call.
- Keep traces, but restructure them around:
  `snapshotSummary`, `primaryProgressTarget`, `stallReport`, `candidates`, `selectedCandidateId`, `translatedAction`, `validation`, and `planner`.

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
- Backend rejects unknown candidate IDs and can fall back to the highest-ranked non-blocked candidate with trace `fallbackUsed=true`.

### Candidate Generation
- Generate candidates from existing snapshot facts:
  terrain grid, runner position, guard positions, gold positions, `goldComplete`, `godMode`, current ladder, legal movement, legal dig, and recent history.
- Current candidate kinds include:
  `collect_same_row_gold`, `align_ladder`, `climb_ladder`, `route_access_dig`, `route_access_follow`, `descend_route`, `continue_fall`, `defensive_dig`, `retreat_from_guard`, `godmode_progress`, `exit_ladder_route`, `wait_or_stop`.
- Only emit candidates whose first action is physically valid from the current snapshot.
- Use simple ranking:
  if `goldComplete=true`: exit ladder route first.
  if non-god-mode critical guard danger: valid climb, defensive dig, retreat.
  otherwise: same-row gold, current ladder climb, align ladder, route-access dig, route progress.
  in god mode: progress candidates outrank survival candidates unless movement is physically blocked.
- Return only the top 4-7 candidates to the LLM.

### Stall Supervisor
- `agent/stall_tools.py` produces a deterministic `stallReport`.
- Current stall types include:
  `horizontal_oscillation`, `vertical_ladder_oscillation`, `same_candidate_no_progress`, `same_tile_no_progress`, `route_access_loop`, `exit_ladder_loop`, and `wait_loop`.
- Candidate generation uses the report to suppress or penalize loop candidates and boost recovery candidates.
- Service-level validation retries once when the model chooses a blocked candidate, then falls back to the highest-ranked non-blocked candidate when possible.

### Prompt Simplification
- Make `agent/prompt.py` present only:
  current concise state summary, candidate list, selection rules, and strict JSON output contract.
- Move durable gameplay policy into `public/AGENT_RULES.md`, but keep it shorter because candidates already encode legality.
- Remove prompt sections that duplicate candidate analysis, especially detailed movement/dig/escape/route-access blocks.
- Keep terrain grid optional or minimized. V2 prefers object-centric summaries, progress targets, candidate targets, and stall reports over asking the model to parse the full board every step.

### Streamlining `agent/`
- Current backend layers:
  `candidates`: extracts normalized facts and generates/scored candidate actions.
  `reasoning_tools`: deterministic movement, guard, dig, and route helpers.
  `stall_tools`: deterministic loop/stall diagnosis and recovery hints.
  `prompt`: formats candidate-selection prompt.
  `service`: orchestrates model call, candidate validation, retry/fallback, and trace assembly.
- Most V1 one-off guardrails are retired because candidates encode legality. Persistent-loop handling lives in `stall_tools`.
- Keep service validation focused:
  selected candidate exists, selected candidate is not stall-blocked, translated action is physically valid, ticks are bounded, and unsupported level returns `400`.
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
