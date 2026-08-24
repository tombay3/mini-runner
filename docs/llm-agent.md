# LLM Game agent

## Scope and decision flow

The agent chooses one short, validated action at a time for the runtime context configured in
`public/agent-config.json`. It works from live state only: it has no map-specific route, fixed
coordinates, or precomputed topology.

Each decision follows this flow:

1. The frontend captures a live snapshot and requests a short action.
2. The backend analyzes local geometry and generates legal candidates.
3. The model selects one supplied `candidateId`.
4. The backend validates that selection and returns one key/tick action.
5. The browser advances the runtime and records the trace outcome.

The model does not provide raw keys or full routes. It chooses a descriptive candidate ID; the
backend converts that choice to a key and duration.

## Browser and hook lifecycle

`src/agent.js` starts the game through `window.lodeRunnerAgentHooks`, takes a snapshot before each
request, applies the returned action, and stops at a terminal state, cancellation, or configured
limit.

The hook surface is:

- `startLevel(playData, level)`;
- `step(keyCode, ticks)`;
- `snapshot()`;
- `stop({ resumeTicker })`;
- `getRecordedDemo()` and `getTerminalSnapshot()`;
- `dumpFailure(reason)`, `isSupportedContext(playData, level)`, and `isReady()`.

The hook starts the legacy runtime and advances it one action at a time. `isReady()` prevents a
start before assets load. A terminal snapshot keeps the final runner, guard, and gold state because
there is no following request to capture it.

See [runtime flow and module ownership](./codebase.md#runtime-flow) for the wrapper and legacy
runtime boundary.

## Snapshot contract

The snapshot separates structural terrain from live state. It includes:

- live `dimensions`, `playData`, `level`, `gameStateName`, tick, and time;
- `runner` position, offsets, and action;
- `guards` with position, offsets, motion, and carried-gold state;
- `gold` with visible positions, carried gold, remaining count, and completion;
- `activeDig` and open-hole timing information;
- `terrainGrid`, containing only structural terrain.

The terrain grid uses a top-left origin: `x` increases right and `y` increases down. It includes
brick, ladders, ropes, exits, and empty space; runner, guards, gold, and active digs remain live
fields outside the grid.

## Gameplay reference

This is maintainer reference, not prompt text. The active prompt rules are in
`public/LLM_GAME_RULES.md`; general game rules are in [Puzzle game](./puzzle-game.md#core-rules).

- Collect visible gold before using the revealed exit. Gold held by a guard is live state, not a
  terrain target.
- A ladder or rope is usable only when the live movement state allows it. The runner cannot jump.
- Dig only into a confirmed diggable brick. Falling, offsets, and open holes can make a short move
  unsafe even when the grid looks open.
- When danger and execution gates clear, prefer a concrete progress candidate over waiting or
  repeated retreat.

## Backend planner and candidate generation

`agent/service.py` validates the request, resolves the model, generates candidates, asks the model
to choose one, validates that choice, and records the step.

`agent/candidates.py` builds the candidate list. It checks movement and guard safety, records why
proposals were filtered, removes duplicates and confirmed loop actions, ranks the remaining
choices, and applies the prompt limit.

Candidate lanes, filtering, scoring, validation, and failure diagnosis are defined in
[Candidate design](./candidate-design.md).

## Prompt and model output

`agent/prompt.py` combines the gameplay rules, compact state, and candidate list. The required
response is JSON with a `candidateId`. OpenAI profiles may also return a short rationale.

The rationale is diagnostic output, not hidden reasoning. Debug logging can correlate it with the
offered candidates, scores, safety lane, and fallback; see [Logging and debug I/O](./backend-spec.md#logging-and-debug-io).

## Safety, loops, and god mode

The backend checks movement, digging, guard safety, open-hole timing, and action length before the
model sees a candidate.

Loop filtering detects stationary, horizontal, and vertical repetition without progress. Its
confirmation and suppression rules are in [Loop handling](./candidate-design.md#loop-handling).

In god mode, guard contact is non-lethal, so progress can take priority over spacing from guards.
The mode is recorded in snapshots and evaluator reports; normal-mode evaluations must verify it is
off.

## Configuration and traces

`public/agent-config.json` holds non-secret runtime and experiment settings. Provider credentials
stay in `.env` or `.env.local`; see [Public agent config](./backend-spec.md#public-agent-config).

Each trace step records compact state, candidates, selection, validation, loop data, and candidate
audit. Agent recording IDs match trace IDs. See [Trace API and store](./backend-spec.md#trace-api-and-store)
for data fields and [Agent evaluator](./evaluator.md) for evaluation and retention.
