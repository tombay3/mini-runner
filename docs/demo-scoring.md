# Demo scoring roadmap

## Objective and current stage

Improve candidate scoring across collection, navigation, ladders, digging, transitions,
safety, recovery, and exits. Replace Codex-authored heuristic score constants with an
explicit, measurable policy supported by demonstration evidence and controlled gameplay
tests.

Preserve the V2 runtime:

    state analysis
    → candidate generation and filtering
    → ranking and shortlist
    → LLM candidateId selection
    → validation
    → key/tick execution

The completed extraction does not show that current scores are good or that the demos
are ready for training. The immediate task is a read-only coverage audit using training
levels only. Do not change scoring, candidates, labels, or validation during that audit.

The intended progression is:

1. Audit label quality and candidate coverage.
2. Fix the largest verified candidate-generation gaps.
3. Centralize existing scores and expose truthful score components without changing
   totals, ordering, shortlist membership, or fallback behavior.
4. Add evaluator-only deterministic top-score selection to separate scoring behavior
   from LLM selection.
5. Establish deterministic gameplay baselines.
6. Train a small ranker only if the audited labels provide useful coverage.
7. Validate normal-mode safety and LLM integration before promotion.

## Why this work is needed

Existing numeric scores are deterministic Codex-authored constants. They were not
selected by the user, learned from data, or mathematically optimized.

Scores affect candidate ordering, seven-item shortlist exposure, model context, and
fallback selection. The model can still choose a lower-ranked candidate. An LLM
gameplay result therefore mixes candidate availability, scoring, model selection,
validation, execution timing, and loop filtering. Diagnose those factors separately.

The Classic demo extraction completed successfully:

| Measurement | Result |
|---|---:|
| Levels completed / quarantined | 150 / 0 |
| Retries / validation errors | 0 / 0 |
| Train / validation / test | 90 / 30 / 30 |
| Sampled decisions | 16,296 |
| Exact exposed key-duration matches | 788 |
| Same-key duration mismatches | 7,132 |
| Missing candidates | 8,317 |
| Matching suppressed/rejected proposals | 59 |
| Elapsed time | 6,045.839 seconds (~1h 40m 46s) |

The 788 exact matches are 4.8% of all samples and include held-out partitions. Their
training-only count is not yet established. More than half the samples have no matching
eligible key action under the extractor's conservative classification. Scoring cannot
rank an action that is unavailable.

Duration mismatches may provide action-prefix evidence, but are not automatically
training labels. See [what the labels mean](demo-scoring-experiment.md#what-the-labels-mean).

## Dataset and provenance

Authoritative current dataset:

    /home/tomchin/3po/ducky/run-8283/__data2/demo-scoring/20260920-010128

Treat the original dataset and labels as immutable. Verify historical source revision,
dirty-worktree fingerprint, controls, runtime versions, partitions, and artifact hashes
from its manifest. Never infer extraction provenance from current HEAD or rewrite old
absolute paths after relocation.

The [extraction record](demo-scoring-experiment.md#dataset-layout) lists the dataset
artifacts and validation checks.

Store derived audit output separately:

    __data2/demo-scoring-audits/<audit-id>/

Record dataset identity, audit code revision, configuration, and output hashes. Keep
generated datasets and reports out of Git. Leave __data1 untouched.

The [extraction design](demo-scoring-experiment.md#extraction-design) identifies the
included demo source and exclusions.

## Immediate task: training-only coverage audit

Use only the 90 training levels for exploratory analysis. Validation and test artifacts
may be checked for integrity but not inspected to design labels or fixes.

Produce a reproducible report with:

1. Training-only exact-label counts by level, demonstrated key, candidate kind/lane,
   rank, score margin, state category, and number of equivalent matches.
2. Duration mismatch counts by demonstrated duration versus candidate duration,
   shorter/longer direction, sampling boundary, and supported movement state.
3. Missing-candidate categories: no matching key proposed; matching proposal filtered,
   rejected, merged, or suppressed; sample during an ongoing action; unsupported
   maneuver; or unknown when evidence is insufficient.
4. Concrete training examples with level, tick, source artifact, state, demonstrated
   action, proposal audit, eligible pool, and shortlist.
5. Two bounded proposals: the largest well-supported candidate gap, and a conservative
   demonstrated-action-prefix label rule with added training count and safeguards.
6. The smallest next experiment, expected gain, acceptance checks, and limitations.

Preserve counts and denominators. Separate observations from inference. A missing
classification does not itself prove physical impossibility. Reusable audit tooling may
be prepared for review, but commit and push require approval.

## Extraction and test harness

The [extraction record](demo-scoring-experiment.md) covers replay, offline candidate
analysis, validation, supervision, rerun commands, and checks. Extraction does not
require Flask or Vite and does not write to __data1.

## Scoring roadmap

### 1. Make current scores explainable without behavior changes

Inventory every score branch. Centralize constants and adjustments while preserving
exact totals, ordering, shortlist membership, deduplication, and fallback behavior.
Add truthful provenance; a fixed score is a named base value, not an invented
risk/progress breakdown.

### 2. Add deterministic evaluator selection

Add evaluator-only --selector top-score using the existing stable tie-break. Preserve
generation, filtering, safety, validation, and action translation. Keep LLM selection
as the production default and record selector mode in provenance.

### 3. Establish baselines

Measure completion, remaining gold, deaths, time, decisions, no-progress spans, loops,
suppressions, fallbacks, candidate availability, selected rank, and score margins.
Separate coverage, ranking, state-analysis, timing, and loop-filter failures.

### 4. Train only if the audited evidence supports it

Start with a regularized linear ranker over general state/candidate features. Respect
positive sets and exclude ambiguous labels by default. Do not use level IDs, route
tables, future demo data, or terminal outcomes as runtime inputs. Fit preprocessing on
training data, tune with validation, and reserve test levels for one frozen proposal.
Consider a small tree ranker only if the linear model clearly underfits.

### 5. Validate gameplay and LLM integration

Offline agreement is insufficient because autonomous play reaches new states. Test
deterministic top-score gameplay first, then small approved LLM comparisons.
Normal-mode safety is required before promotion. Paid runs require explicit approval.

## Ownership and workflow

Linux /home/tomchin/3po/ducky/run-8283 on pooh-dev is the single active writer. macOS
may fetch and review but should not edit concurrently. Preserve manual and staged work;
ask before overwriting or committing it.

Commit prefixes:

- [Experiment]: analysis tools and exploratory infrastructure.
- [Candidate]: one behavioral hypothesis under validation.
- [Promotion]: one approved durable result intended for main.

Ask before commit, push, promotion, or rewriting shared history. Amend only unshared
boundaries unless explicitly authorized. Promote one clean commit rather than merging
the experimental branch wholesale.

Work in this order: verify evidence; audit training data; review and approve one small
experiment; validate it against fixed cohorts; synchronize approved boundaries; prepare
one explicit Promotion commit.

Earlier god-mode work isolated guard-derived model and heuristic inputs while guards
remained physically present. These normal-mode demos may contain guard-driven choices.
Keep mode and guard features explicit; do not train a guard-neutral policy blindly.
