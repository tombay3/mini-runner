# Batch 4: Small cleanup consolidation — scope finalized

Current status: all 26 entries are implemented and validation passed.
Completion evidence is summarized below.

## Execution authorization

- Scope and validation plan are approved. Continue through routine fixes without
  manual approval pauses; resuming the goal implies approval.
- Replace the backend when needed and reuse the frontend. Isolate validation stores.
- Game-data transmission and up to 30 cumulative paid runs are authorized: 8 were
  used before Batch 4; 22 remain. Use hybrid continuations with early stops where
  possible, and spend only when a validation question needs gameplay evidence.
- Luna monitors progress through files only. Keep the legacy engine unchanged.

## Acceptance rules

- Each item must be a relatively small, local change with a clear reduction in
  complexity, duplication, redundant work, or inconsistency.
- Prefer existing functions, short loops, and simple helpers over new frameworks.
- Preserve gameplay behavior where practical. Any possible behavior difference
  must be identified explicitly; passing validation is not proof of no regression.
- Keep detector semantics, history windows, safety defaults, ordering, API fields,
  and error behavior unless a specific exception is approved.
- Preserve the legacy game engine and unrelated worktree changes.

## Existing work, outside the new inventory

The prior small planner cleanup is implemented, validated, and uncommitted in
`agent/candidates.py`, `agent/loop_tools.py`, `agent/reasoning_tools.py`, and
`docs/candidate-design.md`. Its recorded comparison found zero differences across
2,074 decision states plus focused cases; smoke, compilation, diff, and cohort
checks passed. Evidence is in the local ignored directory
`__data3/planner-cleanup-next/`. This does not validate future additions.

## Approved code and documentation items

IDs remain stable as the user approves, defers, or removes items.

| ID | Location | Proposed change | Status | Constraint |
| --- | --- | --- | --- | --- |
| P1 | agent/candidates.py | Consolidate mirrored horizontal retreat construction. | Implemented and verified | Preserve left/right order, scores, reasons, eligibility. |
| P2 | agent/candidates.py | Calculate ladder target direction once and reuse for reason and scoring. | Implemented and verified | Preserve values and candidate order. |
| P3 | agent/loop_tools.py | Move known candidate kinds to a module-level tuple. | Implemented and verified | Preserve matching order and existing unknown-kind handling. |
| A1 | agent/service.py | Share identical Markdown-fence removal in response parsers. | Implemented and verified | Keep distinct validation and errors. |
| A2 | agent/config.py | Share credential/base-URL assembly and use one profile-to-resolver dispatch map. | Implemented and verified | Keep profile-required versus explicit-optional credentials and environment precedence. |
| A3 | agent/logging_utils.py, agent/debug_io.py | Share debug and numeric log-level resolution; remove identical format branches. | Implemented and verified | Preserve valid levels/aliases and debug override; unknown levels consistently use INFO. |
| A4 | agent/prompt.py | Remove unused state/candidate formatting wrappers. | Implemented and verified | Recheck callers before removal. |
| A5 | agent/service.py | Consolidate optional string-field validation. | Implemented and verified | Preserve validation order and errors. |
| A6 | agent/service.py | Remove dead post-fallback assignments and redundant error-class reassignment. | Implemented and verified | No fallback-policy change. |
| C1 | src/recording.js | Share action/trace stepping lifecycle and numeric trace-position lookup. | Implemented and verified | Keep completion conditions, messages, scheduling, cancellation, and timeout behavior. Largest item. |
| C2 | src/agent.js | Share identical agent-run cleanup. | Implemented and verified | Keep existing finally boundaries and cleanup order. |
| C3 | src/recording.js | Consolidate repeated recording-selection resets. | Implemented and verified | Preserve caller differences in stopping playback and finishing UI actions. |
| C4 | app.py | Share common trace-summary fields. | Implemented and verified | Preserve response-specific fields. |
| C5 | app.py | Share ordered recording lookup/filtering and context matching across recording/trace operations. | Implemented and verified | Preserve timestamp ties, ordering, and early-return efficiency. |
| C6 | app.py | Share optional-ID validation and game-context normalization. | Implemented and verified | Preserve field-specific errors and endpoint handling. |
| C7 | scripts/api.mjs, scripts/notebook.mjs | Share virtualenv discovery and Python process forwarding. | Implemented and verified | Preserve arguments, installation guidance, signals, and exit codes. |
| C8 | trace-dash.py | Share repeated JSON loading; hoist duration formatter out of record loop. | Implemented and verified | Preserve errors, formatting, and malformed-data handling. |
| C9 | app.py: next_agent_action() | Normalize logging context to a dictionary before reading runId in error handlers. | Implemented and verified | Invalid non-object JSON must return the intended 400 response; retain other error statuses/messages. Concrete bug fix. |
| D1 | agent/loop_tools.py, agent/candidates.py | Local detector/recovery structural cleanup; see expanded proposal below. | Implemented and verified | Small changes with demonstrated simplification; any behavior difference must be explicit and approved. |
| DOC1 | docs/*.md and README.md | Review every document and rewrite dense, repetitive, or jargon-heavy content in plain, concise, scannable prose after implementation; see closing-work instructions. | Implemented and verified | Preserve meaningful rules, rationale, limitations, and evidence links; verify against final code. |

## Documentation closing work — approved

DOC1 covers every `docs/*.md` file and the root `README.md`, including this
tracker. Perform the cleanup after Batch 4 implementation so the documents reflect
the final code. Complete it before handoff; publication is not a prerequisite.

- Review every in-scope file. For documents other than `candidate-design.md`,
  apply targeted cleanup: shorten dense passages, simplify jargon, and improve
  organization where needed while retaining already clear content. Full rewrites
  of those documents are not required.
- Fully rewrite `candidate-design.md`, including its structure and prose, while
  preserving the substantive design rules, rationale, and evidence described below.
- Use plain, concise technical prose. Shorten long paragraphs, remove repetition,
  explain necessary technical terms, and replace over-complicated jargon with
  concrete descriptions. Preserve exact identifiers where needed for code lookup.
- Give each document a clear purpose and descriptive headings. Use short sections,
  lists for steps, and tables for comparisons where they improve readability.
- Make README a clear entry point for setup, running the project, and finding
  detailed documentation. Link to authoritative explanations instead of copying
  them across documents. Update navigation and anchors when sections change.
- Organize candidate-design.md around overview/flow, candidate generation, safety
  checks, ranking/selection, loop recovery, and limitations. Give other documents
  structures appropriate to their subjects rather than imposing this outline.
- Preserve API/config/schema contracts, commands, operational requirements,
  ownership and ordering constraints, safety/recovery rules, useful rationale,
  limitations, and evidence links. Concision must not erase behavioral distinctions.
- Keep historical evidence clearly distinguished from current design. Move detail
  to appropriate linked records when useful; do not discard provenance, experiment
  outcomes, or approvals merely to shorten prose. Preserve this tracker's stable
  item IDs, approvals, scope, and validation commitments.
- Track each reviewed file and whether it was rewritten or already clear. Validate
  technical claims against the final code, check internal links/anchors and paths,
  and review for omitted constraints, contradictions, or unsupported claims.
  Documentation alone requires no gameplay runs.

## D1 expanded proposal

The first proposal was too narrowly limited to two calculation optimizations.
Behavior preservation is preferred, but is not an absolute batch acceptance rule.

- Flatten `_is_stationary_repeat` into a clear exemption gate and trigger checks,
  making the emergency-hold exception explicit. Retain its special handling.
- Simplify `_restore_guard_escape_climb` bookkeeping so restoration versus final
  suppression recording is explicit; avoid redundant candidate membership checks
  where the single-climb invariant already establishes the outcome. Retain audit
  updates and cleanup of deferred suppression records.
- Reuse `runner_coordinates(..., include_offsets=True)` in the recent-motion
  branch of `choose_ladder_direction`, replacing duplicated coordinate parsing
  and per-field comparisons while retaining unknown-data checks.
- Retain the two small calculation changes: reuse `noGoldChange` and compute
  cycle-target horizontal bounds once.

These are structural opportunities, not permission to merge detector policies.
During drafting, reject any extraction that merely moves complexity or requires
many parameters. If a simpler implementation changes behavior, describe that
specific difference for approval rather than silently widening policy scope.

## Expansion boundaries

A2 retains separate provider resolvers and Gemini transport mapping. C5 preserves
ordering, timestamp ties, exact-ID precedence, and prefix ambiguity. C2 keeps the
existing async error/finally boundaries. No prompt/trace schema merger, validation
framework, or evaluator/reproducer process-lifecycle unification is included.

## Deferred and separate work

| Area | Disposition | Reason |
| --- | --- | --- |
| Broader detector/recovery redesign and progress unification | Deferred | Changes policy and spans multiple detectors/callers. |
| Cross-policy safety defaults | Deferred | Small textual edits can have broad behavioral effects. |
| Full ladder reversal/memory unification | Deferred | Distinct memory lifetimes and eligibility require policy decisions. Local mechanical duplication may be reconsidered as a concrete item. |
| Trapped-guard drop policy | Deferred | Investigation rather than cleanup. |
| Evaluator/reproducer server lifecycle unification | Deferred | Different ownership, logging, reuse, and shutdown guarantees. |
| Shared retention algorithm or cross-layer numeric normalization | Deferred | Different ordering, pinning, and coercion contracts. |
| Invalid-request error logging in app.py | Included as C9 | Explicitly approved concrete bug fix; retain separate validation expectations from behavior-preserving cleanup. |

## Validation plan — approved

Run one bundled validation pass after implementation. Repeat affected checks only
after fixes or for unresolved findings. Detailed evidence lives in
`__data3/batch4-validation/`; smoke checks remain small.

### Baseline and evidence

- Before implementation, freeze the affected current working-tree sources and
  relevant non-secret configuration, with hashes and a manifest identifying HEAD
  plus the existing uncommitted planner cleanup. HEAD alone is not the baseline.
- Keep detailed comparison harnesses/results in ignored `__data3/batch4-validation/`
  or temporary directories. Keep committed smoke tests small and behavioral.
- Run read-only `npm run cohorts:check` before reviewing retained evidence. Report
  uncataloged runs/stale links. Use copied fixtures and temporary stores for writes;
  do not rewrite production recordings, traces, or the catalog for validation.

### Coverage

| Items | Validation | Acceptance |
| --- | --- | --- |
| P1–P3, D1; planner effects of A1–A6 | One offline baseline/current comparison over the existing 2,074 retained/recent decision inputs, subject to fixture availability. Compare candidate order/IDs/actions/scores/reasons, analysis, loop reports, audits, both prompt modes, selection/fallback projections, and input immutability. Omit only known volatile timestamps. Add a small focused set for stationary-repeat exemptions, zero/one/multiple deferred climbs, restoration versus suppression, and known/missing ladder-motion coordinates. | No unexplained differences. If fixtures are unavailable, report reduced coverage rather than claiming the prior count. |
| A1, A4–A6 | Exercise plain/fenced JSON, malformed/non-object responses, missing choices/content, invalid/unknown candidate IDs, optional request-field types, and reasoning extraction. Compare baseline outputs/errors; verify removed wrappers have no callers. | Existing parsing, prompt, validation, and fallback contracts retained. |
| A2 | Isolated environment fixtures for each profile and explicit OpenAI/Minimax configuration: required/optional credentials, model normalization, base-URL precedence, Gemini transport mapping, unknown profiles, and request/config error classification. Stub provider clients; use dummy credentials. | Same resolved configuration and errors; no model/network calls. |
| A3 | Fresh-process startup and runtime refresh with ordinary levels, aliases, debug override, and an unrecognized level. Check effective logger/handler levels and debug enablement. | Existing valid configurations retained; approved difference is consistent INFO fallback for unrecognized levels. |
| C1–C3 | Deterministic wrapper checks with controlled animation frames, time, hooks, and API responses. Cover action/trace step completion, unknown tick/end-of-trace, timeout, cancellation/playback ending, and pause/resume. Cover success/failure/cancellation/persistence-error cleanup and empty/offline/missing-record reset states. Follow with a short real-browser check of both stepping modes and pause/resume on a copied recording, including a trace boundary. | Same final state, action/trace boundaries, cleanup, and observable UI behavior. No stale animation callbacks or running flags. Assess engine state at equivalent boundaries; do not require identical wall-clock rendering times. |
| C4–C6 | Flask test client with temporary recording/trace stores: list/latest summaries, equal timestamps, mixed contexts, exact/prefix/ambiguous IDs, missing records, pin/delete confirmation, and normal lookup/delete. Compare response fields/status and persisted effects with baseline. | Same ordering, context isolation, ID resolution, errors, retention and pin protection. |
| C7 | Launch an inert Python child through the shared launcher in isolation; verify arguments, working directory, missing-virtualenv diagnostics, nonzero exit propagation, and signal termination on the host platform. | Existing launch contract retained. Report other platforms as untested; do not claim Windows runtime coverage from Linux. |
| C8 | Load temporary valid/missing/malformed files and compare dashboard dataframes, metadata/errors, and duration formatting against baseline. | Same dashboard values and error reporting; no production data writes. |
| C9 | Flask test client submits nonempty JSON array/string/number/bool and null/empty-object cases; verify a valid request through a stub planner. | Invalid non-object bodies return the intended JSON 400 response without an error-handler crash or model call; valid request behavior retained. |

### Required checks and regression handling

- Run `npm test`, `npm run build`, Python compilation for changed Python modules,
  and `git diff --check`. Run once on the completed bundle; repeat affected checks
  after fixes. Add only a few durable smoke regressions where useful, particularly
  C9 and the A3 approved behavior change; keep detailed comparisons out of npm test.
- Review the resulting diff for actual reduction in complexity, duplication, and
  redundant work. Passing tests alone does not justify an abstraction that makes
  maintenance harder or exceeds the approved small-change scope.
- A3's INFO fallback and C9's invalid-body 400 response are expected differences.
  Investigate all others. A small gameplay difference may be acceptable if it is
  an understood consequence of simpler code, has focused boundary coverage, and
  shows no regression in relevant continuation evidence. It does not need to
  improve gameplay. Record understood small differences within approved scope;
  defer broader policy changes.
- No paid gameplay runs planned by default. Offline equality does not require
  another paid campaign. If a gameplay difference cannot be resolved offline,
  use affected-state replay or a bounded paired hybrid continuation with early
  stopping under the recorded cumulative quota. Record the question and case first.
- Report item coverage, baseline identity, expected/unexpected differences, failed
  or unavailable checks, and limitations. No claim of universal regression freedom.

### Approval status

The user approved and launched the finalized implementation and validation scope.

## Scripts and test-scope review — approved

S1–S6 are approved, bringing the tracker to 26 entries (S3 expands C7). Scope
is finalized and execution is underway. Evaluate the suite by the behavior it protects, not
by line count or perceived regression confidence alone.

Testing recommendation: keep useful deterministic regressions during and after
active development, but separate their invocation from smoke checks now. Keep
`npm test` as a small code smoke suite. Add an explicit regression command for
focused planner/wrapper/tool cases, and an explicit read-only data-check command
for `sanity_traces.mjs`; keep `cohorts:check` available separately. During Batch 4,
run smoke plus relevant regressions. Later reduce run frequency according to the
changed area, not by deleting tests simply because confidence increased. Remove
only obsolete, redundant, or implementation-mirroring assertions with an identified
reason. Large experimental comparisons remain outside the committed smoke suite.

| ID | Proposal | Value / boundary | Status |
| --- | --- | --- | --- |
| S1 | Separate smoke, focused regression, and local-data checks into explicit entry points. Add exactly two shared regression scripts: scripts/regression_backend.py and scripts/regression.mjs. Move detailed Python planner cases out of sanity_backend.py; review frontend sanity checks on the same basis. | Moderate organization change, minimal behavioral change. Keep request/candidate/trace/persistence essentials in smoke. Preserve useful assertions and report the before/after test inventory. npm test would no longer depend on live local data; data checks remain an explicit validation step. | Implemented and verified |
| S2 | Consolidate small repeated test fixtures and isolate variant mutations. | Reuse compact runner/guard/history builders only where duplication is demonstrated; create fresh mutable state per case. Use short named case tables for true input/output variants, not a configurable scenario framework. | Implemented and verified |
| S3 | Extend C7's shared virtualenv-path discovery to sanity.mjs. | Reuse path/existence mechanics; preserve the smoke runner's synchronous fail-fast execution and its installation guidance. Do not force synchronous tests and asynchronous service launchers into one process abstraction. | Implemented and verified |
| S4 | Simplify repeated report tally updates in evaluate-agent.mjs with one small local increment helper. | Retain counts, special statuses, report fields, and insertion order; remove the redundant selectedKind alias where straightforward. No metric or decision-classification redesign. | Implemented and verified |
| S5 | Make the hybrid reproducer preflight Python snippet readable as multiline code, and expand dense statements in touched preflight/dispatch sections. | Local readability change; preserve arguments, frozen-source imports, outputs, budget checks, and state transitions. Do not rewrite the experiment controller or change historical frozen manifests. | Implemented and verified |
| S6 | Move embedded hybrid-runtime runChecks tests into the shared scripts/regression.mjs entry point from S1; create no hybrid-specific test script. | Removes test-only imports and the runtime-to-reproducer test dependency from the runtime module. Document the new test command; preserve all existing cases, including startup-failure checks. Keep model-free execution. | Implemented and verified |

File-count constraint (user approved): add exactly two regression test scripts,
one per language: `scripts/regression_backend.py` and `scripts/regression.mjs`.
The Python script holds backend/planner regressions; the JavaScript script holds
frontend, evaluator, launcher, and hybrid regressions. Move detailed Python cases
out of `sanity_backend.py` so that file returns to smoke-only coverage. S6's hybrid
tests go into the shared JavaScript script, with no separate hybrid test script.
Use one regression command to run both scripts and propagate failures. Reuse small
fixtures from existing modules where practical; avoid per-area runners or new
fixture modules merely to relocate code. A data-check command invokes the existing
sanity_traces.mjs directly. This replaces the earlier one-script-total constraint.

No additional abstraction is recommended for the small trace-pin command or the
cohort reconciliation writer. Preserve reconciliation's guarded writes and ownership
rules; the similar live-data checks and schema validators have different contracts.
Evaluator/reproducer process-lifecycle unification remains deferred.

Extend validation with: a before/after case inventory for S1/S6;
execution of smoke, regression, and explicit data checks; independent fixture-state
checks for S2; baseline report equality on small trace fixtures for S4; and zero-model
preflight/runtime checks for S5/S6. New data review still requires cohorts:check.
These checks support the approved S1–S6 scope alongside the existing validation plan.

## Integration checks before handoff

- Ensure the single regression command actually runs both language suites and
  propagates failures. Preserve a before/after case inventory so moving tests does
  not silently drop coverage. Document smoke/regression/data commands under DOC1.
- Check source-copy and hash manifests against any new shared production/tool
  modules introduced by refactoring. The hybrid tool currently hashes two named
  tool files and copies root-level agent modules; extend fresh-manifest coverage
  only if new dependencies require it. Preserve historical frozen evidence.
- Keep the already validated uncommitted planner cleanup identifiable in baseline
  records; new Batch 4 validation compares against that working-tree state.

These are integration requirements of approved refactors, not additional refactor
proposals. No further must-do cleanup item was established in this final scope check.

## Pre-Batch-4 unstaged inventory

Recorded before implementation; nothing staged or committed. Local snapshot:
`__data3/worktree-checkpoint/20261028T223759Z/` (ignored, not a Git commit or remote backup).

| File | Existing change | Evidence / handling |
| --- | --- | --- |
| agent/candidates.py | Shared ladder-history parsing, consolidated defensive digs, cached guard vectors, common medium-pressure tick bound, and simpler predicted-return filtering. | Exact source hash matches prior validated cleanup. Preserve as baseline. |
| agent/loop_tools.py | Parse complete history once; share coordinates and direction-run calculation; remove redundant helpers/condition. | Exact source hash matches prior validated cleanup. Preserve as baseline. |
| agent/reasoning_tools.py | One access-option scan and ordering function; defer new-dig threat calculations until needed. | Exact source hash matches prior validated cleanup. Preserve as baseline. |
| docs/candidate-design.md | 16 added lines describing shared history, clearance, and access calculations. | Documentation accompanying the prior cleanup; full rewrite remains DOC1 work. |
| docs/sanity-tests.md | Deletes the concluding paragraph about accepting simplification without requiring gameplay improvement and reporting validation limits. | Origin unknown from available session evidence. Preserve this independent edit; the acceptance rule remains in this tracker. |
| docs/cleanup-batch.md | Untracked Batch 4 scope, approvals, validation plan, and this inventory. | Pre-implementation planning artifact; now also tracks results. |

The three source hashes were rechecked against the prior VALIDATION.json and match.
Its 2,074-state comparison and focused checks apply to those exact source bytes;
no new gameplay validation was run for this inventory. The snapshot contains file
copies, a tracked-files patch, and a manifest with SHA-256 hashes and HEAD. Preserve
it when starting Batch 4 so existing edits can be distinguished from new changes.

## Approval record

The user approved P1–P3, A1–A6, C1–C9, expanded D1, DOC1, and S1–S6, then
finalized scope and launched the goal. The A2/A3/C1/C5 expansions and validation
plan are approved. DOC1 means targeted cleanup across docs and README, with a full
candidate-design rewrite. S1/S6 require exactly two shared regression scripts,
one Python and one JavaScript. Later instructions authorize unattended execution,
raise the cumulative paid quota to 30, and prefer early-stop hybrid runs.

The original scope and approval history are preserved in the pre-edit baseline
copy of this tracker and the conversation. This concise record governs execution.

## Batch 4 results

All 26 approved entries are implemented and verified. Detailed reports and the
frozen baseline are under `__data3/batch4-validation/`; `VALIDATION.json` indexes
coverage, expected differences, limits, and source hashes.

| Evidence | Result |
| --- | --- |
| Planner comparison | 1,890 retained + 184 recent decision inputs; no differences in pools, prompts, analysis/audits, loops, or selection/fallback projections |
| Focused contracts | 960 stationary combinations, 18 climb-restoration cases, 4 ladder-motion cases; parser/provider/request/API/dashboard/logging checks passed |
| Existing boundaries | 120 duration, 3 missing-offset, 3 incomplete-history, 8 access-option cases; 35 helper and 12 loop-history cases passed |
| Browser playback | Copied recording reached identical baseline/current action and trace boundaries; pause/resume passed |
| Tooling | Ten evaluator reports identical; final model-free hybrid prepare/preflight passed |
| Test migration | No original Python check or hybrid test definition lost; exactly two shared regression scripts added |
| Required checks | Smoke, regressions, build, compilation, data, cohort, and diff checks passed |
| Documentation | All 16 Markdown files reviewed; candidate design fully rewritten; others received targeted cleanup; local links checked |
| Paid work at initial completion | Zero new runs/model calls; later follow-up below uses two runs |

Expected differences are the approved INFO fallback for unrecognized log levels,
correct JSON 400 responses for invalid non-object planning requests, and separated
smoke/regression/data commands. No planner output difference was observed. Evidence
does not prove all possible states safe or establish completion rates. Launcher
behavior was executed on Linux only.

The earlier unstaged cleanup remains incorporated and identifiable in the frozen
baseline and pre-Batch-4 snapshot. The independent sanity-guide deletion remains
preserved in that snapshot; the current guide was updated under DOC1. No legacy
engine changes, staging, commits, or production-data rewrites were made.

## Follow-up validation

The user renamed the shared launcher to `scripts/launch-python.mjs`; all callers
and launcher regressions were updated. Smoke and regression checks passed after
the rename (`__data3/batch4-validation/rename-report.json`). The earlier validation
report records the original filename and source hashes at Batch 4 completion.

The user then requested two paid runs for broader integration coverage. The matched
hybrid probe uses the frozen pre-Batch-4 baseline and current code at trace
`e723bd87-223b-44fc-bb9a-8b9822b0ab77`, tick358. It is capped at30 decisions per
arm, with earlier stops on gold collection or return to the fork pose. Evidence
is under `__data3/batch4-paid-probe/`. Fresh engine replay of all ten current-store
recordings is included as a separate model-free check.

Follow-up results: control collected one gold in 24 decisions; changed reached the
30-decision cap with no gold. Both stopped alive. All 90 prefix boundaries and 24/30
continuation boundaries plus final states replayed exactly. The planners remained
identical on all 54 live decision inputs. Keep the progress gap explicit; one pair
does not establish a causal regression or equal completion rates.

Fresh replay of all 10 stored recordings passed at 1,890 decision boundaries and all
terminal states. Two paid runs and 54 model calls were used; cumulative paid usage
is 10 of 30, leaving 20. See `__data3/batch4-paid-probe/REVIEW.md` and
`ASSESSMENT.json`. No additional paid runs were started. The normal backend is
restored and the existing frontend was reused.

Local commit authorized after follow-up validation; no push requested.
