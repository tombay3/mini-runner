# Guard safety: development guide

Keep the runner making useful progress while preserving enough guard clearance
and a usable escape route. Distance alone cannot establish safety: row access,
guard motion, ladders, holes, other guards, and action duration also matter.
Classic `playData=1`, `level=1` is the only supported context.

The six reviewed correction groups are now included in `main`.
That does not establish that all guard-safety bugs are fixed or that survival
has improved. Disposable harnesses and unresolved experiment evidence remain on `guard-dev`. See [guard-policy-progress.md](./guard-policy-progress.md) for status,
decision windows, and live evidence.

## Next investigation: guard distance and escape options

Investigate where the runner loses useful separation or escape options **before
pressure becomes critical**. Start with offline measurements and one concrete
case, then classify the first supported defect.

Look for:

- Progress that reduces clearance when another safe route preserves it.
- Retreat from one guard that approaches another guard.
- Actions long enough for a guard to intercept before the next decision.
- A useful row change or repositioning candidate omitted or filtered too early.
- Repeated movement that preserves distance but makes no useful progress.

Do not introduce a blanket minimum-distance rule. A safely separated move may
reduce distance and still be useful. Earlier escape planning and terrain-aware
lookahead are broader policy work; consider them only when simpler corrections
are insufficient. The proposed compound ladder-cycle correction remains
deferred because it was not a low-level, low-complexity fix.

## Findings that guide the investigation

| Finding | What it establishes |
| --- | --- |
| `3dcb7b7d` and `403fbec1`: separated medium cross-row guards blocked short climbs | Safety rejection removed a candidate before scoring. The bounded climb exception addresses this boundary. |
| `403fbec1` display step 135: two safe ladder routes had different clearance effects | Ranking can favor useful progress that preserves clearance. The unexecuted alternative's survival outcome is unknown. |
| Defensive dig 112 lost to progress 90 in historical deaths | Exposing a safe candidate and assigning a higher score did not ensure model selection. Bounded backend selection now enforces the demonstrated preferences. |
| `2a15066a` raw step 39: loop filtering removed a short escape climb | Candidate filtering can leave only progress toward a closing guard. A narrow restoration has offline coverage and one live activation. |
| `df738083`: backend replaced a requested dig with repeated downward retreat | Selection must account for the demonstrated retreat cycle. Preserving the dig worked in one later live activation. |
| Terminal convergence left only emergency holds | Exhaustion at death does not prove a safe terminal action existed. Inspect earlier decisions rather than weakening critical safety. |

## Locate the first defect

Follow the V2 path: threat analysis → candidate generation → physical and guard
checks → scoring → model `candidateId` choice → backend validation → key/tick
action. Compare the requested action, validated action, and next observed state.

| Observation | Question |
| --- | --- |
| Useful move absent | Did threat analysis, route generation, loop filtering, or the candidate limit remove it? |
| Move rejected | Is rejection justified by terrain, guard reach, endpoint, and duration? |
| Weaker safe move selected | Is the defect in scoring, prompt information, model selection, or backend replacement? |
| Only hold remains | When was the last useful escape lost? Was a safe alternative available then? |

`closing=false` means the current analysis did not find horizontal same-row
approach. A guard on another row may still climb, descend, or intercept.
Revalidate historical findings against current code; similar deaths need not
share a cause.

## Measurements and safety rules

For every progress candidate and the selected hold or retreat, measure all
visible guards. Record current distance, minimum predicted distance during the
action, endpoint distance, distance change, row relationship, motion, trapped
state, closing state, interception risk, and useful progress. Also report safe
progress available during holds, guard-based rejections, candidate-limit
exclusions, and repeated no-progress states.

Separate raw distance reduction from crossing a safety boundary. The harness
uses a bounded straight-line projection from duration and motion; it does not
simulate terrain or future guard decisions. Report projected conditions
separately from observed approach, interception, or collision.

Preserve these rules:

- Keep existing contact, high/critical, same-row, and same-column protections.
  Check secondary guards as well as the pressure guard.
- Rank already-valid routes by clearance. Keep safely separated low/medium-risk
  progress available even when distance decreases.
- Measure trapped guards, but do not treat their current trapped motion as
  active approach pressure in the clearance preference.
- Exclude guard-owned gold and unsafe access routes.
- Keep justified trap waits and emergency holds. Replace a hold only when a
  validated useful alternative exists.
- Preserve V2 candidate selection and final validation. Avoid legacy-runtime
  and public trace-schema changes.

## Tools, validation, and promotion

| Tool | Purpose and limit |
| --- | --- |
| Traces, recordings, and [cohort catalog](./trace-cohort.md) | Establish source provenance and the recorded decision sequence. One trajectory cannot prove what another action would have done. |
| `scripts/reproduce_guard_safety.py` and its fixture on `guard-dev` | Check recorded risk, candidate availability, clearance, filtering, and safety controls. Recorded movement affordances are inputs, not an engine replay. |
| `scripts/reproduce_guard_selection.py` and its fixture on `guard-dev` | Check prompt facts, backend replacement, and validation. Default mode is offline; optional online mode costs model calls. |
| Permanent regressions and `npm test` | Verify the correction and safety controls. Passing checks do not prove survival benefit. |
| Normal-mode evaluator | Test the full V2 path on fixed source and configuration. Treat provider failures separately from gameplay failures. |

Run `npm run cohorts:check` before trace review. Record exact historical source
provenance; never infer it from current HEAD. Keep aggregate reports outside
rolling trace retention. Reconcile and classify the catalog after a reviewed
campaign, then check again.

Each plan should name the decision window, defect classification, one proposed
correction, safety controls, acceptance checks, and run budget. Diagnose and
reproduce offline first. Request approval before a gameplay correction, paid
campaign, trace mutation, or promotion; an explicitly approved budget governs
that campaign. Monitor at startup and batch completion unless a failure needs
attention. Stop spending runs once a qualifying failure disproves acceptance.

Validate with the offline reproducers, `npm test`, Python compilation for backend
changes, frontend build for frontend changes, and `git diff --check`.

Use `Experiment:` for disposable diagnostics and trace fixtures, `Candidate:`
for gameplay changes under evaluation, and `Promotion:` for approved durable
changes prepared for `main`. Use ordinary prefixes such as `Docs:` for general
maintenance. Keep production code, permanent tests, and relevant documentation
together; exclude disposable harnesses from promotion. Prefer squash and rebase
with a recovery branch and a verified unchanged file tree for history cleanup.
