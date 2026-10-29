# V4 agent context handoff

Use [Backend specification](backend-spec.md#trace-api-and-store) as the sole trace
contract and [Candidate design](candidate-design.md) for behavior. V4 is the only
supported shape. Read current source and these contracts when refreshing context.

## Boundaries

- Maintain backend candidate generation, model candidateId selection, validation, and keys/ticks.
- Classic playData=1, level=1 only; preserve legacy physics and gameplay behavior.
- Engine snapshots and raw wrapper history have separate contracts; translate at their boundaries.
- Do not add migrations, compatibility aliases, adapters, or historical-field handling.
- Existing store deletion is a separate user-controlled operation.

## Current field conventions

- Observed entities: state.runner and state.guards; their action fields describe engine state.
- Assessed threats: state.threat contains risk, primaryThreat, and guardAssessments.
  Aggregate risk exists only at state.threat.risk. Missing assessments remain unknown,
  including terminal snapshots, which omit threat context.
- Candidates: id, kind, lane, score, target, reasons, offeredAction.
  Model offeredAction contains name/ticks; trace offeredAction also contains keyCode.
- Step issuedAction contains backend-issued keyCode/ticks and does not certify engine execution.
- excludedProposals contains candidateId, kind, status, proposedAction, reason.
  Each row is an excluded proposal occurrence; repeated candidate IDs remain separate rows.
  Statuses: safety_rejection, physical_rejection, deduplicated, loop_suppressed,
  limit_truncated. proposedAction contains the original keyCode/ticks.
- Gold: remaining, complete, visible. goldTarget identifies visible gold; exitTarget
  identifies an exit waypoint. carryingGold is true only for a positive carrying counter.
- Movement: physicalDirections and openHoles; physical availability does not establish safety.
- Route ladder: preferredDirection, nearestRowEntry, atDownwardEntry, adjacentToLadder.
  digAccess separates digAvailable/digAction from entryAvailable/entryAction and guard blocking.
- Recent history entries use issuedAction, tileChanged, offsetChanged, remainingGoldDelta.
  Repeated-candidate measurements use targetDistanceReduced, targetTileReached, and {x,y}.
- Known empty arrays, false and zero survive compaction; unknown optional context may
  be omitted. Unknown history measurements remain null.
- Model context and trace share assessment, candidate, route and history names.
  The trace adds observed guards, identifiers, timestamps and issued/proposed inputs.

## Consumers and validation

Shared model formatters live in agent/prompt.py; trace serialization in agent/traces.py;
storage and APIs in app.py. Keep dashboard, notebook, evaluator and replay consumers aligned.
The notebook needs only fields relevant to its candidate analysis.
Record experiment provenance in launch manifests and the cohort catalog.

Run npm test, npm run build, Python compilation, npm run test:regression,
notebook top-to-bottom execution without saved outputs, npm run cohorts:check,
and git diff --check. Use final-shape fixtures when existing traces are incompatible.
Checks establish representation consistency, not gameplay improvement. Paid evaluation
requires authorization under the current workstream.
