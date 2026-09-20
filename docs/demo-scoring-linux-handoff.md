# Final Linux handoff: demonstration data and candidate scoring

Prepared 2026-09-20 from the parent and side-conversation context.
This document transfers context and a staged roadmap. It does not authorize executing
every proposed development phase at once. The immediate next task is the read-only
training-data coverage audit described below.

## 1. Objective and rationale

Improve candidate scoring across game situations using explicit policy, measurable
features, demonstration evidence, and controlled gameplay evaluation. Earlier work
focused on ladder/horizontal oscillation; the scoring effort should cover collection,
navigation, digging, transitions, safety, recovery, and exit behavior.

The existing numeric scores are Codex-authored constants and heuristic bands. They
were introduced during code generation, not chosen by the user or learned through
optimization. Their computation can be deterministic while their values remain
unvalidated policy choices. Do not describe them as user-approved preferences.

Current scores influence candidate ordering and shortlist exposure, appear in model
context, and influence fallback selection. The model can select a lower-ranked
candidate. Thus gameplay results with the LLM mix scoring quality, candidate coverage,
model selection, and runtime behavior.

The user prefers low complexity, small changes, incremental tests, and evidence-based
decisions. Do not start by replacing the planner or adding a complex learning system.

## 2. Ownership and working conventions

- Linux is the intended authoritative environment for subsequent experiment work:
  repository `/home/tomchin/3po/ducky/run-8283`, branch `pooh-dev`.
- Keep one active writer to that branch. macOS can review/fetch; avoid concurrent edits.
- Read the current AGENTS.md and preserve user changes. In particular, Linux reported
  `M trace-analytics.ipynb`. Do not edit, stage, or commit it without explicit approval.
- The user owns staged changes. Ask before overwriting or including them in a commit.
- Commit prefixes are `[Experiment]`, `[Candidate]`, and `[Promotion]`.
  Experiment means exploratory tooling/data work; Candidate means a proposed behavior
  improvement under validation; Promotion means the reviewed durable result for main.
  These are commit labels, not separate branches or a mandatory promotion ladder.
- Keep coherent commit boundaries. Ask approval before committing, pushing, promotion,
  or rewriting shared history. Prefer squash/rebase and amending within an unshared
  boundary. Do not amend or force-push already-shared Linux commits without approval.
- Durable promotion should be one clean, approved commit to main. A branch containing
  experiments is not automatically eligible for wholesale merging.
- Communicate in concise technical prose: conclusion, evidence, limitation, next step.

### Eight-step working workflow

1. **Linux owns development.** Use the Linux pooh-dev checkout as the only active
   writer. Avoid simultaneous macOS edits. This final documentation handoff is the
   user-requested exception; subsequent development happens on Linux.
2. **Freeze the extraction evidence.** Preserve the completed dataset and verify
   its source revision and dirty-file fingerprint from manifest.json. The expected
   handoff revision was 2343bde; record what the manifest actually proves.
3. **Audit before changing behavior.** Inspect training levels only, categorize
   coverage gaps, and propose the smallest next experiment. Defer scoring changes
   and training until that evidence has been reviewed.
4. **Separate tools from generated evidence.** Prepare reusable analysis tools in
   [Experiment] commits; keep datasets and generated reports in ignored __data2.
   Dataset partitions and original labels remain fixed during the audit.
5. **Validate one behavioral hypothesis at a time.** After approval, prepare a
   bounded [Candidate] change and compare it against fixed training/validation
   cohorts. Keep behavior-preserving instrumentation in its own boundary.
6. **Synchronize approved boundaries.** Obtain approval, commit, and push each
   completed boundary. macOS may fetch and review without editing the shared branch.
   Prefer a compact history; do not rewrite already-shared commits without approval.
7. **Promote only the durable result.** Prepare one clean, squashed [Promotion]
   commit for explicit approval before applying it to main. Exclude experimental
   scaffolding and generated evidence that are not part of the durable change.
8. **Protect manual work.** Preserve the reported modified trace-analytics.ipynb
   and all user-owned staged changes. Do not edit, stage, overwrite, or commit that
   notebook or include staged user changes without explicit approval.

## 3. Existing implementation and boundaries

Preserve the legacy engine in `public/game/`. Prefer wrapper/backend changes where
needed. The production agent supports Classic playData=1, level=1; multi-level demo
extraction is an offline experiment, not production multi-level support.

Preserve V2: state analysis → candidate generation → LLM candidateId selection →
backend validation → key/tick execution. Any deterministic selector discussed below
is an explicit evaluator-only extension, not a silent change to the production path.
Do not restore raw-key planning, V1 compatibility, or alternate fallback schemas.

At the inspected revision, candidate finalization applies loop filtering, sorts by
descending score with candidate ID as a stable tie-break, and exposes the configured
shortlist. Normal selection calls the model before validation/fallback. Recheck current
code before changing these assumptions.

Existing experiment tools:

- `npm run demos:extract`: direct extraction; 20 levels by default, `--all` for 150,
  `--pilot` for level 1, and `--resume` with an explicit output path.
- `npm run demos:campaign`: local supervisor, default pilot → 20-level gate → 150.
- `npm run demos:test`: extraction and supervisor regression checks.
- `docs/demo-scoring-experiment.md`: setup, dataset contract, execution and recovery.

Relevant history, to verify against the Linux checkout:

| Commit | Purpose |
|---|---|
| 72d5735 | Linux post-gold ladder-entry fix; extraction base |
| 796a22c | Initial offline demo extraction pilot |
| ad066c6 | Gated 150-level campaign and local supervisor |
| 2343bde | Socket-blocking test made compatible with restricted Linux execution |

The test fix avoids allocating an OS socket when testing the blocking function.
It does not relax runtime network isolation or Chromium permissions.

## 4. Completed campaign: reported evidence

Linux reported the following result; this conversation did not directly inspect the
Linux artifacts. Verify the manifest and artifact hashes before relying on provenance.

| Measurement | Reported value |
|---|---:|
| Completed / quarantined | 150 / 0 |
| Retries / validation errors | 0 / 0 |
| Pilot and 20-level gate | Passed |
| Train / validation / test levels | 90 / 30 / 30 |
| Exact exposed matches | 788 |
| Duration mismatches | 7,132 |
| Missing candidates | 8,317 |
| Suppressed or rejected | 59 |
| Total sampled decisions | 16,296 |
| Usable exact labels | 788 (4.8% of samples) |
| Elapsed | 6,045.839 seconds, about 1h 40m 46s |

Original dataset location:

    /home/tomchin/runner1-experiments/demo-scoring/20260920-010128

The user was given a manual move command to place completed data at:

    /home/tomchin/3po/ducky/run-8283/__data2/demo-scoring/20260920-010128

The move was not confirmed in this conversation. Inspect both locations and establish
which is current. Do not create a second dataset or assume the move occurred.
Likewise, 2343bde was the expected code available before execution; the manifest's
actual revision and dirty-worktree fingerprint are authoritative. Do not assign the
current HEAD as historical provenance.

Key artifacts: manifest.json, splits.json, campaign-summary.json, campaign.log,
reports/summary.json, and per-level metadata.json, states.jsonl, decisions.jsonl,
checkpoints.jsonl, coverage.json.

The results validate replay/extraction integrity as reported. They do not establish
that current scores are good, labels are sufficient, or candidates cover expert play.

## 5. Dataset handling and interpretation

Keep original extraction artifacts immutable. Store new audits in a separate ignored
directory, for example `__data2/demo-scoring-audits/<audit-id>/`. Record the dataset
identity, source revision, audit code revision, configuration, and output hashes.
Check that __data2 is ignored before placing large outputs there. Do not use /tmp as
the only copy of evidence needed for later training. Never modify existing __data1.

The extractor currently rejects in-repository output for extraction/resume. Moving a
completed dataset into __data2 is appropriate for read-only analysis, but does not
make that new location an accepted extraction-resume target. Recorded old absolute
paths may remain as historical evidence; resolve current paths without rewriting
the source dataset.

Source inventory established earlier:

- lodeRunner.wData.js contains 434 entries across five collections (150/51/150/17/66).
- This campaign uses only the 150 Classic entries in wfastDemoData1.
- docs/fast-demo1.json is a replay-data duplicate of its Classic level-1 demo.
- demoData1.js contains 15 recordings across 14 level numbers; demoData2.js contains
  33 recordings. The earlier comparison found no identical level/action sequences
  against wData. Verify their map collections and replay validity before using them.
- Different recordings of the same map belong in the same dataset partition.

Current samples occur at demo action changes and at gaps no greater than maxActionTicks.
History is reconstructed from observed transitions without inventing candidate IDs.
Consequently, ID-dependent loop rules have less evidence than during actual agent play.
The exported proposed/filtered/eligible pools and audit dispositions must be interpreted
at their corresponding stages rather than treated as interchangeable candidate sets.

Exact key/duration matching is a conservative labeling convention. It can reject a
shorter action that follows the same movement. A same-key candidate is not by itself
proof of the same target or intended maneuver. Missing-candidate classification does
not prove physical impossibility; inspect proposal, filtering, and sampling evidence.
Multiple exact candidates form an action-equivalence set, not a uniquely known intent.
Successful demos do not prove every demonstrated action optimal or every alternative bad.

## 6. Immediate next task: training-partition coverage audit

Use only training levels for exploratory state/decision inspection. Existing whole-
dataset aggregate counts above are already known; do not inspect held-out examples
to design fixes. Verify file integrity as needed without using held-out behavior to tune.

Produce a reproducible report covering:

1. Distribution of exact labels by training level, action key, candidate kind/lane,
   rank, score margin, and meaningful state categories. Identify concentration and
   multiple-equivalent-candidate cases. The full 788 includes held-out labels; calculate
   the training-only count rather than treating all 788 as available training examples.
2. Duration mismatch distributions: demonstrated interval versus candidate duration,
   shorter/longer actions, key-change boundaries versus interval sampling, and ongoing
   digging/falling/ladder transitions where the record supports classification.
3. Missing-candidate categories: no proposal in that direction, filtered/rejected
   alternatives, ongoing-action sampling, or unsupported maneuvers. Use 'unknown'
   when evidence does not establish a cause. Distinguish inference from observation.
4. Representative training examples with level, tick, source file, state, proposal
   audit, eligible candidates, and demonstrated action. Retain counts and denominators.
5. The smallest next experiment, its hypothesis, acceptance checks, and expected gain.

Do not change scoring, candidate generation, dataset labels, or validation gates as
part of the audit. Reusable audit tooling may be prepared separately for review;
committing or pushing it requires approval. A proposal to change labeling must describe
how it preserves intent and avoids inventing expert preferences.

## 7. Scoring roadmap retained from the original discussion

### A. Inventory and centralize scoring without behavior changes

Map all score-producing branches and their conditions. Move scattered policy constants
and adjustments into one small scoring module or named policy definitions. Preserve
exact totals, ordering/ties, candidate exposure, deduplication outcomes, and fallbacks.

Add score provenance/components to candidate audit data. Components must describe the
actual computation. For an existing fixed score, a named base value is an honest
breakdown; do not invent objective/risk/continuity contributions that the code never
computed. Future feature categories can include objective progress, topology, continuity,
reversal risk, action duration and cost when implemented and validated.

Verify equality on representative states and existing regressions. Keep instrumentation
and behavioral scoring changes in separate boundaries. Assess trace/prompt schema impact;
do not automatically add verbose component details to the model prompt.

### B. Add evaluator-only top-score selection

Implement a diagnostic selector, proposed interface `--selector top-score`, that selects
the highest-ranked eligible candidate with the existing stable tie-break. Retain state
analysis, candidate generation, filtering, validation, and action translation. Preserve
LLM selection as the default production behavior. Record selector mode in provenance.

This is not implemented by the demo extractor. Demo playback follows recorded actions;
top-score evaluation is a new autonomous gameplay experiment. Keep those datasets distinct.

Use it to measure scoring without stochastic LLM selection or gameplay model costs.
Selection is deterministic for identical inputs; full gameplay reproducibility also
requires controlling engine randomness, initial state, and history. Verify normal/god
mode explicitly. Do not bypass safety or loop filters to inflate success.

### C. Establish baselines before changing weights

Measure completion, remaining gold, deaths, game time, decisions, no-progress spans,
loops/reversals/suppressions, fallbacks, candidate coverage, selected rank and score margins.
Separate coverage gaps, ranking errors, state-analysis errors, execution/timing problems,
and loop-filter effects. Scoring cannot rank an unavailable action into existence.

Keep legality and hard safety constraints separate from ranking preferences. An explicit
priority ordering was suggested as an alternative to arbitrary overlapping bands:
required transition, objective progress, observed progress, continuity, topology/distance,
action cost, stable tie-break. This remains a proposal, not an approved replacement.

### D. Try a small learned scorer when labels are understood

Start with a regularized linear ranker over general state/candidate features. Use an
established optimizer; a novel algorithm, large network, RL system, or LLM fine-tuning
is not needed for the first experiment. Fit weights against confidently matched demo
choices, respecting positive sets and acknowledging that unchosen options are not
known to be worse. Exclude ambiguous labels by default.

Avoid level IDs, literal route tables, future demo information, and terminal outcomes
as runtime input features. Fit preprocessing on training data only. Reserve complete
levels/map families across splits, not random adjacent frames. Use validation for
model/feature selection and save test evaluation for a frozen proposal.

If a linear model clearly underfits, consider a small tree ranker later. Codex can
write/supervise the training scripts; the Codex SDK is optional workflow automation,
not the algorithm that fits scoring weights. Keep model-call costs separate from
local training/extraction costs.

### E. Validate actual gameplay and then the LLM integration

Offline ranking agreement is insufficient: fresh rollouts expose unfamiliar states
after the policy departs from a demo. Evaluate autonomous top-score gameplay, then
small approved LLM comparisons with matched controls. Normal-mode safety validation
is required before durable promotion. Obtain approval before paid model campaigns.

Change one scoring dimension or one clearly bounded candidate hypothesis at a time.
Version dataset, feature schema, score policy, selector, configuration, source/dirty
state and engine provenance. Do not merge evidence from materially different planners
or modes into one success rate without separation.

## 8. Guard-mode context and earlier loop work

Earlier experiments used god mode with guard information isolated from both model
inputs and decision heuristics; guards still physically existed in the legacy engine.
This was intended to isolate navigation/loop issues, not to claim guard-free physics.
The user explicitly opposed prompting the model to 'ignore guards'; isolation should
remove guard-derived decision inputs instead. Verify current implementation before
claiming that any existing revision provides this isolation.

Normal-mode demos may include guard-driven choices. Removing guard features can make
those choices unexplained; do not train a guard-neutral policy blindly on all normal-
mode demonstrations. Keep mode/features/labels explicit and test normal-mode behavior
separately. No instruction here authorizes reapplying archived loop commitments,
forced transitions, prompt changes, or suppression experiments.

## 9. Execution and development discipline

For future long batches, launch the runner itself in a detached tmux session. Its
five-minute monitoring and bounded retries are local script work, not model turns.
Codex quota exhaustion need not stop that detached process; Linux must stay awake.
Quota reset is not an automatic campaign restart. Inspect process, locks and manifest
before resuming. Do not duplicate active runs or remove locks of live/unknown owners.

Give one startup confirmation and a final completion/failure summary for unattended
batches; detailed level logs belong on disk. Stop on integrity failures rather than
automatically changing code or tolerances. Linux setup/execution previously used Luna
Low; deeper audit/development needs an appropriate reasoning setting, chosen separately.

Follow current repository checks: npm test; focused experiment tests; Python compilation
for Python changes; npm run build for frontend changes; git diff --check. Explain any
unrun checks. If reviewing runtime traces/cohorts, first run npm run cohorts:check and
follow docs/trace-cohort.md. The extracted demo dataset is separate from that trace store.

## 10. Kickoff for the next Linux development session

The user approved amending the final documentation commit previously identified as
0ab7c25 so that both handoff documents reflect the completed extraction and audit
phase. Fetch before synchronizing. A checkout still at 2343bde can fast-forward.
If Linux already has the superseded 0ab7c25, a fast-forward pull cannot apply its
replacement. Preserve notebook/staged work and reconcile only that replaced commit;
do not overwrite or automatically rebase additional Linux commits. This is a
one-time approved documentation rewrite, not permission for future force-pushes.

Read AGENTS.md, this handoff, and docs/demo-scoring-experiment.md. Establish the actual
dataset location and historical provenance from its manifest. Preserve the notebook,
staged changes, original dataset, and validation/test partitions. Perform the training-
only coverage audit in section 6, saving separate reproducible reports under __data2.
Do not rerun extraction or begin scoring/training changes merely because this document
describes the roadmap. Return evidence, limitations, and the smallest proposed next
experiment. Retain the behavior-preserving scoring inventory and evaluator-only
top-score mode as explicit pending work. Obtain approval at commit/push boundaries.
