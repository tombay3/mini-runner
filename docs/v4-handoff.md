# V4 agent context handoff

Use [Backend specification](backend-spec.md#trace-api-and-store) as the sole trace
contract and [Candidate design](candidate-design.md) for behavior. V4 is the only
supported trace shape. Read current source rather than relying on earlier chat examples.

## Working boundaries

- V2 agent flow: generate candidates, select `candidateId`, validate, issue keys/ticks.
- Classic `playData=1`, `level=1` only. Do not change legacy game physics.
- This cleanup changes representation, not candidate admission, scores, timing,
  safety policy, or loop detection. Guard gold observations use positive carrying counters.
- `goldTarget` is a visible-gold objective; `exitTarget` is an exit approach/climb target.
- Distinguish actual `state.guards` from assessed `state.threat`.

## Current field conventions

- Candidate: `id`, `kind`, `lane`, `score`, `target`, `reasons`, `action`.
  Model action: `{name,ticks}`; trace candidate action: `{name,keyCode,ticks}`.
- Step `action` is backend-issued `{keyCode,ticks}`; candidate `action` is an offer.
- Candidate explanations live in `reasons`. Nonexposed proposal events use their own `reason`.
- Gold: `{remaining,complete,visible}`. Guard gold: boolean `carryingGold`.
- Threat: `risk`, `primaryThreat`, `guards`; guards include `approachingOnSameRow`.
- Movement: `physicalDirections`, `openHoles`. Physical availability is not safety.
- Route: `ladder` and `digAccess`. Ladder hints use `preferredDirection`,
  `nearestRowEntry`, `atDownwardEntry`. Dig access separates `digAvailable`/`digAction`
  from `entryAvailable`/`entryAction` and their guard-blocking indicators.
- Recent history uses named `action`, `tileChanged`, `offsetChanged`,
  `remainingGoldDelta`, `targetDistanceReduced`, `targetTileReached`, and `{x,y}` targets.
- Known empty arrays, false and zero survive compaction. Unknown optional context
  may be omitted; unknown recent-history measurements remain null.

## Refactor change map

The **before** column is developer reference only. **After** is the sole supported
V4 shape; there are no compatibility aliases or migrations. Paths below apply to
model context and its stored trace counterpart unless a narrower scope is stated.

| Area | Before | After | Meaning / cleanup |
| --- | --- | --- | --- |
| Trace candidate | `candidates[].firstAction` | `candidates[].action` | One offered bounded input; matches the model's existing action name. |
| Candidate explanation | `firstAction.reason` | Removed; consolidated into `candidates[].reasons` | One explanation list, including action-specific details. |
| Candidate purpose | `candidates[].intents` | Removed; retain `candidates[].kind` | The list duplicated the kind under current merge rules. |
| Candidate target | `candidates[].targets` | Removed; retain singular `candidates[].target` | One local candidate target; no redundant target array. |
| Gold objective | `primaryProgressTarget` | `goldTarget` | Preferred visible-gold objective, separate from exit guidance. |
| Trace gold | `state.gold.remainingCount` | `state.gold.remaining` | Matches model context. |
| Trace gold | `state.gold.visiblePositions` | `state.gold.visible` | Matches model context; preserves position metadata. |
| Threat | `threat.pressureGuard` | `threat.primaryThreat` | Prioritized threat, not necessarily nearest or approaching. |
| Assessed guards | `threat.nearbyGuards` | `threat.guards` | All guards with valid coordinates, sorted by distance; not a nearby-only subset. |
| Assessed guard | `closing` | `approachingOnSameRow` | Horizontal approach on the runner's row, not general convergence. |
| Model guard | `hasGold` | `carryingGold` | Boolean: only a positive engine carrying counter means held gold. |
| Observed trace guard | `carryingGold` using counter truthiness | `carryingGold` using counter `> 0` | Same field name; negative cooldowns now correctly mean false. |
| Movement | `movement.legalDirections` | `movement.physicalDirections` | Physical availability does not establish guard safety. |
| Route section | `route.access` | `route.digAccess` | Access through digging or an existing opening. |
| Dig access | `access.available` | `digAccess.digAvailable` | Availability of an access dig. |
| Dig access | `access.recommendedAction` | `digAccess.digAction` | Proposed access-dig input. |
| Opening entry | `access.followAvailable` | `digAccess.entryAvailable` | Availability of entry into an existing opening. |
| Opening entry | `access.followAction` | `digAccess.entryAction` | Input for entering the opening. |
| Opening entry | `access.followBlockedByGuard` | `digAccess.entryBlockedByGuard` | Guard pressure blocks entry. |
| Drop threat | `access.dropThreat.nearest` | `digAccess.dropThreat.nearestGuard` | Explicitly identifies the nested guard. |
| Ladder | `ladder.nearest` | `ladder.nearestRowEntry` | Local same-row ladder access point. |
| Ladder | `ladder.recommendedAction` | `ladder.preferredDirection` | Local hint, not a candidate-selection command. |
| Ladder | `ladder.onDownEntry` | `ladder.atDownwardEntry` | Runner is above a downward ladder entry. |
| Recent history entry | `keyCode`, `ticks` | `action: {name, ticks}` | Readable input names in model context and `recentProgress`. |
| Recent history entry | `tileMotion`, `offsetMotion` | `tileChanged`, `offsetChanged` | Coordinate changes, not evidence of useful progress. |
| Recent history entry | `goldCountDelta` | `remainingGoldDelta` | After minus before; negative means fewer remaining gold. |
| Repeated candidate | `madeProgress` | `targetDistanceReduced` | Reduced tile distance, not general gameplay progress. |
| Repeated candidate | `targetReached` | `targetTileReached` | Tile match only; offsets are excluded. |
| Repeated candidate | `target: [x, y]` | `target: {x, y}` | Consistent coordinate representation. |

`exitTarget`, `candidateEvents`, and step-level `action` are retained.
Engine snapshots and raw wrapper history keep their own contracts; the history
rows above describe the formatted `recentProgress` payload, not those raw inputs.

## Ownership and consumers

- `agent/prompt.py`: shared model formatters; `agent/traces.py`: trace serialization.
- `app.py`: storage, APIs, validation. Engine snapshots and raw replay streams remain
  separate contracts; translate explicitly at their boundaries, not via trace compatibility code.
- Update `trace-dash.py`, `trace-analytics.ipynb`, evaluator and hybrid scripts with the contract.
- Run/cohort provenance starts with a new launch manifest. Do not infer old provenance from HEAD.

## Data and validation

The user approved a clean reset of recordings, traces, cohorts, cohort backup, and all
historical experiment contents in `__data3`. There is no migration or retained local
archive. Start fresh evidence; do not reconstruct deleted comparisons from chat memory.

Run `npm test`, `npm run build`, Python compilation, `node scripts/hybrid-runtime.mjs --test`,
notebook top-to-bottom execution without saving outputs, `npm run cohorts:check`,
and `git diff --check`. Smoke checks do not establish gameplay improvement.
Paid evaluator runs require separate authorization. Leave this refactor uncommitted for review.
