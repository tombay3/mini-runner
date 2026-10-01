# Guard-safety reproducer reference

This document describes the diagnostic harness in `experiment: guard reproducer`.
The harness preserves confirmed decision boundaries and safety controls while
the broader guard-distance investigation continues. It does not replay the game
or prove that an unexecuted action would have prevented a death.

## Files and commands

| File | Purpose |
| --- | --- |
| `scripts/reproduce_guard_safety.py` | Replays recorded guard-state, candidate-validation, clearance, and filtering boundaries. |
| `scripts/fixtures/guard-safety-holds.json` | Sanitized recorded states, proposals, movement affordances, controls, and source provenance. |
| `scripts/reproduce_guard_selection.py` | Checks backend selection rules, prompt facts, and final candidate validation. |
| `scripts/fixtures/guard-selection-boundary.json` | Sanitized score and selection boundaries from retained decisions. |

Run the offline checks from the repository root:

```bash
.venv/bin/python -B scripts/reproduce_guard_safety.py
.venv/bin/python -B scripts/reproduce_guard_selection.py
npm test
```

The two Python commands run 15 guard-safety tests and six selection tests. Their
default modes do not call a model, mutate traces, or run gameplay. The
guard-safety harness reads only its fixture. Treat the printed
`main->candidate` columns as the fixture's recorded baseline disposition versus
the checked-out code; the label does not establish the source revision of the
current `main` branch.

`reproduce_guard_selection.py` also has an explicit online mode:

```bash
.venv/bin/python -B scripts/reproduce_guard_selection.py \
  --online --output /tmp/guard-selection-report.json
```

Online mode sends at most three reconstructed decisions to the configured
OpenAI model, writes the report after each decision, and stops when the bounded
selection rule fails. It costs model calls and requires separate approval. It
tests model choice only; it does not execute the selected game action.

## What the guard-safety harness measures

The harness evaluates every visible guard for each retained candidate. It
projects runner and guard motion over the candidate duration using eight ticks
per grid cell and Manhattan distance. It reports:

- distance before the action, minimum projected distance during it, and endpoint
  distance;
- distance change and whether the action reduces clearance;
- row relationship, guard motion, closing state, and trapped state;
- projected approach, interception, collision, and safety-boundary crossing;
- progress toward the recorded target; and
- recorded rejection, shortlist displacement, hold, retreat, and repeated-cycle
  behavior where the fixture contains it.

Raw distance reduction is not automatically unsafe. A safely separated action
may reduce distance while making useful progress. A guard in a hole remains in
the measurement set, but its trapped motion is not treated as active approach
pressure for clearance ranking.

The projection is deliberately bounded. It uses recorded movement affordances,
action duration, row relationship, and guard motion. It does not simulate
terrain, offsets, future guard decisions, complete candidate generation, or
engine timing. Projected interception and collision are diagnostic labels, not
observed events unless the retained trace establishes them.

## Retained cases

The guard fixture groups evidence by the boundary it tests:

| Fixture group | Retained evidence |
| --- | --- |
| `cases` | Non-closing cross-row holds, including the bounded short-climb correction. |
| `distanceCases` | Guards ahead, behind, cross-row, moving toward or away, and trapped; routes with different clearance effects; safe distance reduction; projected interception; justified holding; and safe progress available during a hold. |
| `convergenceSequence` | retreat sequence in which useful choices disappear after reversal and terminal convergence leaves emergency holds. |
| `pinchEntryCases` and `latestPinchBoundary` | Three historical medium-risk defensive-dig selection misses and the `2a15066a` escape climb removed by loop filtering. |
| `postGoldReversalBoundary` | Immediate ladder reversal after collecting gold. |
| `compoundLadderCycleBoundary` | mixed row/column ladder cycle missed by the narrow loop detectors. This remains deferred policy work. |
| `secondaryLadderGuardBoundary` | validation accepted descent toward a high-risk secondary guard while primary pressure came from another guard. No correction is approved. |

The selection fixture retains five decision cases. Its offline checks cover the
demonstrated defensive-dig preference, gating by risk and candidate shape,
historical lower-score selections outside the rule, propagation of the new
reason into the prompt, and the medium cross-row clearance control. Its online
case list is bounded to three recorded decisions.

## Safety controls and established findings

The suite keeps the following distinctions explicit:

- Separated medium cross-row pressure may permit a short climb, while close,
  same-row, high-risk, and critical controls remain rejected.
- Two legal routes can make similar progress but have different minimum guard
  clearance. Ranking may prefer the route that preserves clearance.
- A defensive candidate with a higher backend score can still lose at model
  selection; candidate availability and selection are separate defects.
- Loop filtering can remove a short escape before pressure becomes critical.
- A justified critical trap wait must remain available when movement is unsafe.
- Guard-owned gold is not a valid progress target.
- Terminal candidate exhaustion does not prove that a safe terminal move existed.
  Investigation must look earlier for the first lost escape.
- Primary-pressure analysis can mask a secondary same-column guard. The fixture
  reproduces this gap without authorizing a generic multi-guard rule.

These assertions characterize specific recorded boundaries. They do not claim
complete guard safety, improved survival, or a counterfactual outcome.

## Adding a case

Use broad scans and trace review to discover a suspicious decision; do not grow
the fixture into a trace archive. Add a case only when it preserves a meaningful
boundary and useful controls.

For each new case:

1. Record the trace or dataset source, exact historical revision, raw/display
   step or level/tick, and supported Classic context.
2. Retain the smallest state, movement affordances, candidates, scores, request,
   validation result, and next observation needed to establish the boundary.
3. State whether the assertion characterizes recorded behavior, checks current
   behavior, or encodes a proposed correction.
4. Add nearby controls for risk, separation, direction, trapped state, duration,
   and candidate legality where they distinguish the proposed rule.
5. Do not infer terrain, missing candidates, engine events, or survival outcomes
   absent from the source evidence.

Run both reproducers, `npm test`, Python compilation for backend changes, and
`git diff --check`. Run `npm run cohorts:check` before reviewing trace evidence.
Preserve historical source revisions; never replace them with current `HEAD`.

## Commit and promotion boundary

The scripts and trace-derived fixtures are diagnostic material in an
`Experiment:` commit. They may remain on `guard-dev` or be transferred for an
offline audit, but they are excluded from a durable promotion unless explicitly
approved. A confirmed gameplay correction belongs in a separate `Candidate:`
commit with focused permanent regression coverage. An approved durable change
is then prepared as a `Promotion:` commit without disposable fixtures.
