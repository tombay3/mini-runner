# Guard-policy experiment: status and evidence

The six reviewed correction groups are now included in `main`. Disposable
reproducers and unresolved cycle evidence remain on `guard-dev`. Offline regressions and some live activations
support their specific behavior. They do not establish that all guard-safety
bugs are fixed or that survival has improved.

The next investigation is where the runner loses guard clearance or escape
options before critical pressure. Begin with measurement and diagnosis; no new
gameplay correction is approved. The compound ladder-cycle proposal remains
deferred because it was broader than a low-level, low-complexity fix.

[guard-safety.md](./guard-safety.md) contains the safety rules, investigation
workflow, tools, and broader roadmap. This file records concrete evidence and
implementation status.

## Promotion audit and commit boundaries

The six correction groups below were approved together as durable changes. Their offline behavior is established, permanent safety controls run
under `npm test`, and recorded live activations cover the selection and escape
changes. No additional paid runs are required for this local-correctness review.
Survival improvement and exhaustive guard-distance coverage remain unproven.

| Correction group | Offline and live evidence | Audit decision |
| --- | --- | --- |
| Separated cross-row climb | Recorded hold boundaries and close/high-risk rejection controls; later campaigns did not reproduce the long hold. Exact historical geometry has no matched live replay. | Ready for local-correctness approval; no claim of death prevention. |
| Clearance ranking, including low-risk bonus | Permanent tests cover preserved/reduced clearance, multiple and trapped guards, and unchanged candidate availability. Live cross-row choices followed the intended order. | Ready as a bounded preference; broader progress benefit remains open. |
| Defensive-choice selection | Permanent tests verify score replacement, out-of-scope controls, and final validation. `2a15066a` recorded three intended replacements. | Review with the retreat-loop exception below, not as an isolated rule. |
| Restored escape climb | Permanent tests now cover restoration, recent repetition, extra routes, duration, physical rejection, and high/critical safety. `df738083` changed row in one activation. | Ready for the narrow restoration; no future-route guarantee. |
| Post-gold reversal | Permanent tests cover both upward candidate ID forms and retain descent after horizontal arrival. | Ready as a focused history-recognition fix. |
| Dig during retreat loops | Permanent tests cover activation, changed gold, wider movement, insufficient cycles, multiple higher choices, and illegal digging. `a9cffb0c` executed the dig and trapped the guard. | Ready with its selection prerequisites. |

`main` contains one amended `Add guard safety and update dash` commit combining
Dashboard updates, all six corrections, prompt changes, permanent tests, and
these documents with the earlier evaluator and ladder-entry fixes. The removed
`ascii_map.py` is no longer imported by the dashboard or notebook.

`guard-dev` retains a separate `Experiment:` commit containing both reproducers,
trace-derived fixtures, usage notes, and the unresolved compound-cycle evidence.
Those disposable tools are excluded from `main`; permanent `npm test` coverage
runs without them. The audit added regression coverage without changing the
already evaluated gameplay behavior.

Historical source revisions below identify the evaluated code before history
rewrites. Preserve that provenance in the cohort catalog rather than replacing
it with current commit hashes.

## Implemented corrections and their evidence

| Correction included in `main` | Evidence and limits |
| --- | --- |
| Short climb under separated medium cross-row pressure | `3dcb7b7d` and `403fbec1` exposed a safety-rejection defect. The exception allows a climb of at most six ticks with the required horizontal clearance; high/critical, same-row, and close cross-row controls remain. |
| Guard-clearance ranking | At `403fbec1` display step 135, the right route reduced projected minimum distance from four cells to three and moved away from gold. The left route preserved four cells and approached gold. Offline ranking now favors left; its historical survival outcome is unknown. |
| Low-risk clearance preference | A four-point bonus favors progress that preserves separation; safely separated distance-reducing moves remain available. A five-run sample produced one completion, three deaths, and one step limit, which does not establish improvement. |
| Bounded selection priorities | Historical deaths exposed dig 112, retreat 108, and progress 90, yet the model chose progress. The backend now enforces the demonstrated medium-risk preferences. `2a15066a` confirmed three replacements, then died after five critical holds. |
| Restore a filtered low-risk escape climb | At `2a15066a` raw step 39, vertical-loop filtering left only an eight-tick move toward a closing guard. The Candidate restores one previously safe climb of at most six ticks under narrow conditions and recent-candidate controls. `df738083` step 39 selected it and changed row. All nine campaign runs later died. |
| Prevent post-gold ladder reversal | Recognizes upward `exit_ladder_route_` actions as well as `climb_ladder_` actions, preventing immediate reversal at the recorded boundary. The separate legal ladder-entry descent correction is already on `main`. |
| Preserve dig during repeated downward retreats | The backend keeps a requested safe dig when downward retreat is its only higher-scored competitor and recent history proves the bounded cycle. One live activation executed the dig and trapped the approaching guard; another guard caused the later death. |

Some `403fbec1` waits were justified while a guard approached and fell into a
hole. Later same-row convergence exhausted the safe candidates. Those terminal
holds do not prove that a safe terminal move existed or that an earlier
unexecuted action would have prevented death.

## Latest guard campaign: defensive dig in a retreat loop

Four paid normal-mode Classic 1:1 attempts used historical source `275efe6`,
`openai:gpt-5-nano`, candidate limit 7, maximum action length 20, temperature 1,
and a 300-step limit. The evaluator started a fresh backend and reused the
unchanged frontend. All reports had valid mode/context and monotonic timelines.
The campaign stopped at the target activation in run 4, leaving one approved
attempt unused.

| Trace | Outcome | Evidence |
| --- | --- | --- |
| `91e368a2` | Guard death after 197 decisions | No target activation; later high/critical pinch retained emergency safety. |
| `9de4cb06` | Step limit after 300 decisions | No target activation; mixed ladder/row cycle reproduced offline below. |
| `31f89c1c` | Guard death after 224 decisions | No target activation; convergence retained trap waits and emergency holds. |
| `a9cffb0c` | Guard death after 60 decisions | Target activated at raw step 37 without fallback. Dig executed; the approaching guard fell into the hole and dropped gold. A different guard later killed the runner. |

At `a9cffb0c` raw step 37, the runner was at `(4,12)` with a closing medium-risk
same-row guard four cells to the right. Candidates were downward retreat 118,
dig right 112, and retreat left 108. The model requested dig right; validation
preserved it and emitted eight ticks. This verifies the local selection change,
not survival improvement.

The originating defect was in `df738083` raw steps 28 and 44: the model requested
a valid dig, but backend score enforcement replaced it with retreat 118. The
new exception requires:

- A requested defensive dig whose reason says the closing guard can fall.
- Exactly one higher-scored candidate: `retreat_from_guard_down`.
- At least two down-retreat/up-ladder transitions in recent relevant history.
- No gold change and a horizontal range of at most one cell.
- Successful final physical and guard-safety validation.

Controls retain ordinary score enforcement when these conditions fail. Observed
high/critical and same-row rejection remained active. Medium cross-row ladder
choices also appeared, with the higher-scored clearance route available and
selected; no regression was found in the reviewed decisions.

Aggregate reports were saved outside rolling trace retention:

- `/tmp/guard-loop-275efe6-stage1.json` (runs 1 and 2)
- `/tmp/guard-loop-275efe6-stage2-run3.json`
- `/tmp/guard-loop-275efe6-stage2-run4.json`

The cohort catalog records the four runs under
`normal-loop-aware-defensive-dig-candidate` and applicable control cohorts.
The latest read-only catalog check reports consistent links and zero uncataloged
traces.

## Open finding: compound ladder cycle

The offline reproducer captures `9de4cb06` raw steps 137–138. The runner started
left toward ladder `(20,6)` and gold below-left. On the next decision, continuing
left and returning to ladder `(25,6)` were both safe and exposed. Distance scoring
plus the low-risk clearance bonus ranked the return 104 over continuing left 99.
The model followed that order. Downward movement at the departed ladder had
already been physically rejected, so the return led upward, away from the target.

Repeated row and column changes evaded both loop detectors: horizontal detection
requires one row and vertical detection requires one column. A pure vertical
cycle was finally detected at step 186, 48 decisions after the first reversal.

This is a broader interaction between loop classification and route scoring,
rather than a demonstrated low-level safety or candidate-availability bug.
Proposals to recognize ladder-target returns or preserve unfinished routes were
not approved. No correction was implemented. Keep the reproducer as evidence;
do not treat this proposal as the next authorized change.

## Next investigation and evidence limits

Review guard-distance losses before a pinch: compare all guards, motion, terrain,
action duration, available/rejected candidates, scores, model request, validated
action, and the next state. Look for unsafe approach, retreat toward a second
guard, late loss of a row-changing option, or repeated safe movement without
progress. Isolate one supported defect before proposing a correction.

The `scripts/reproduce_guard_safety.py` on `guard-dev` tests recorded
risk, clearance measurements, candidate filtering, and safety controls. The
`scripts/reproduce_guard_selection.py` on `guard-dev` tests prompt
facts and backend validation. They do not replay the engine or prove what an
unexecuted move would have caused. Live runs test the full V2 path; stochastic
outcomes do not provide matched counterfactuals.

Evaluator infrastructure now bounds OpenAI requests at 90 seconds with no
automatic retry, and an evaluator attempt at 1800 seconds by default, writing a
failure report on expiry. Provider failures are infrastructure evidence. Future
campaigns need fixed source, an approved budget, explicit acceptance/stop rules,
sparse monitoring, and evidence-backed catalog updates.
