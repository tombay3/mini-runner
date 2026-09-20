# Demo scoring experiment: completed extraction and audit reference

## Task and boundaries

The Linux extraction campaign is complete according to its reported summary. The
current task is a training-partition coverage audit, not another extraction run.
Read [the final Linux handoff](demo-scoring-linux-handoff.md) for the full context,
eight-step workflow, audit requirements, and subsequent scoring roadmap. This file
retains the extraction setup, dataset contract, and recovery reference.

Linux is the authoritative development environment on pooh-dev. Preserve the reported
modified trace-analytics.ipynb and user-owned staged changes. Keep original data and
labels immutable, and save derived audits separately under ignored __data2. Do not
inspect validation/test examples to develop the audit's fixes or labeling policy.
Scoring changes, training, paid model campaigns, and production multi-level support
remain pending review.

Base revision: 72d5735; extraction handoff: 796a22c; 150-level supervisor: ad066c6;
sandbox-safe test fix: 2343bde. Verify actual campaign source and dirty fingerprint
from its manifest; do not infer them from current HEAD. Inspect revision and worktree
before synchronizing and preserve local work. The documentation commit previously
identified as 0ab7c25 is being replaced by a user-approved amendment containing both
handoff documents. If Linux already pulled that superseded commit, an ordinary
fast-forward pull will not apply the amendment; reconcile only that verified replaced
commit while preserving user changes. Do not overwrite additional Linux commits.

## Reported completed dataset

Dataset ID: 20260920-010128. Linux reported 150 completed, zero quarantines/retries/
validation errors, passing pilot and 20-level gate, partitions 90 train / 30 validation
/ 30 test, and 6,045.839 seconds elapsed. Across 16,296 decisions: 788 exact exposed,
7,132 duration mismatches, 8,317 missing candidates, and 59 suppressed/rejected.
The 788 exact labels include held-out partitions; calculate training-only counts.
These results establish reported extraction integrity, not scoring quality.

Original location:

    /home/tomchin/runner1-experiments/demo-scoring/20260920-010128

Requested location for the completed data:

    /home/tomchin/3po/ducky/run-8283/__data2/demo-scoring/20260920-010128

The move was not confirmed in this conversation. Locate the existing dataset and
verify its manifest and artifact hashes. Do not duplicate it or rewrite embedded
original paths merely because its physical location changed.

The next audit should categorize duration/missing-candidate cases and exact-label
distribution using training levels only, with representative level/tick evidence.
Do not assume a missing exact action is physically impossible or that demo choices
are uniquely optimal. Report evidence and propose the smallest next experiment.

Pending development remains explicitly ordered: behavior-preserving scoring inventory
and truthful score breakdowns; evaluator-only top-score selection; gameplay baselines;
then a small learned ranker if the audited labels support it. These features are not
implemented by demo extraction and are not authorized merely by this reference.

The runner starts its own temporary loopback asset server and headless Chromium.
Flask and Vite are unnecessary. It loads legacy scripts without the recording wrapper,
restricts browser requests to local GETs, and runs analysis in a Python subprocess
that blocks socket connections and imports no provider service. No paid gameplay
model calls or writes to __data1/ are allowed. Runtime stores are hashed before/after.

## Extraction setup and commands (reference for separately approved future runs)

Do not execute this section for the completed dataset's audit. The audit does not
require starting Chromium, Flask, Vite, or another extraction campaign.

Use Node 20+, Python 3.10+, and distribution-installed Chromium with its OS libraries.
playwright-core does not download a browser. No model API credentials are required.

    git pull --ff-only origin pooh-dev
    npm ci
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    npm test
    npm run demos:test
    npm run demos:campaign -- --browser-executable /usr/bin/chromium --output /home/USER/runner1-experiments/demo-scoring/classic-150

Replace executable/home paths with the real paths. Preserve an existing virtualenv;
create it only if absent. Run as a regular user with Chromium's sandbox enabled.
Use tmux and the Linux host's sleep-prevention policy to survive SSH disconnects.
Do not use macOS caffeinate. Do not edit code while extraction runs.

The supervisor automatically runs pilot → initial 20 → remaining 130. Detailed
per-level output goes to campaign.log. It prints only the final JSON summary.
Local process/progress checks occur every five minutes without model calls.
Codex should poll no more often than every five minutes, avoid repeated log reads,
and report only completion or an unrecoverable stop.

Worker exit is detected immediately. Recognized browser disconnect/crash errors
(exit 75), SIGSEGV, and SIGABRT permit at most two retries for the whole campaign,
persisted across resumes. Other failures—including watchdog expiration, validation,
source changes, integrity violations, and code defects—stop without retry.
Each replay has a duration-based watchdog. No progress at a single five-minute
check alone is not grounds to kill a long level. Never repair code or relax gates.

To resume an interrupted campaign with the SAME source, configuration and runtime:

    npm run demos:campaign -- --resume --browser-executable /usr/bin/chromium --output /home/USER/runner1-experiments/demo-scoring/classic-150

Omit --output initially to create a dated directory under
~/runner1-experiments/demo-scoring/. Resume always requires an explicit path.
--python or DEMO_PYTHON overrides .venv/bin/python; CHROME_PATH selects Chromium.
For a separate level-1 smoke test use demos:campaign -- --pilot and a separate output
directory. Direct demos:extract retains its 20-level default and supports --all for
150 levels without supervision. Old schema-1 datasets cannot resume with this
schema-2 runner; use a new directory after updating.

## Replay, labels, and partitions

Only wfastDemoData1 is included. Verify its level-1 replay fields against
docs/fast-demo1.json and count that fixture once. Exclude smaller demo collections.
Player names and IP addresses are not exported.

Replay recorded mode, AI version, key/tick events, gold drops and respawns at ordinary
demo speed (currently 35 ticks/second). The pilot compares control checkpoints against
sampled playback. Both must reproduce the terminal tick/outcome and checkpoints,
with complete gold for successful demos. Sample before action changes and no more
than maxActionTicks apart; enforce context, mode, and increasing ticks. Export demo
ticks as tick/timing.recordTick and retain the original counter as legacyRecordTick.

Initial levels: 1 + round(i * 149 / 19), i=0..19. All 20 must pass replay/integrity
checks before expansion. Initial quarantines block expansion after that batch.
During expansion, quarantine individual replay mismatches and continue. Systemic
browser/adapter failures stop. Candidate-match coverage has no pass threshold.

Fix partitions for all 150 before extraction. Keep the original 20 first and append
other levels ascending. Every fifth assignment is test, every fifth starting at
the fourth is validation, the others training (90/30/30 absent map duplicates).
Identical map hashes inherit the first assignment; level 1 stays in training.
splits.json records intended/actual assignments and duplicate links.

Analyze candidates after playback. Capture scores/actions, rejection/suppression
audits, pre-final-filter pool, eligible ranked pool, shortlist, and analysis features.
History uses observed transitions without invented candidate IDs; ID-dependent loop
detection consequently has less information than in an agent run.

Exact validated key/duration matches are action-equivalence labels, not proof of
optimality or intent. Multiple matches form a positive set. Same-key/different-duration
matches are ambiguous and excluded from training by default. Report exposed,
truncated, suppressed/rejected, duration mismatch and missing-candidate cases
separately. Do not change candidate timing to inflate coverage.

## Output and recovery

New extraction and extraction-resume outputs must remain outside repository worktrees.
Completed data may be moved into ignored __data2 for read-only analysis. The current
extractor rejects in-worktree resume targets, so moving completed data does not make
the new location an accepted resume target. Save derived reports in a separate audit
directory and retain the original dataset unchanged.

Extraction artifact layout:

    <dataset>/
      manifest.json
      splits.json
      levels/classic-NNN/
        metadata.json
        states.jsonl
        decisions.jsonl
        checkpoints.jsonl
        coverage.json
      reports/summary.json
      reports/failure.json       # if an extraction attempt failed
      campaign.log
      supervisor.json
      campaign-summary.json

Manifest: actual source revision/status, dirty-diff fingerprint, source/runtime
hashes, config, schema, splits, level status and artifact hashes. Metadata: sanitized
demo, map/demo hashes, terminal proof, checkpoint hashes, validation and timings.
Decisions link to states by tick. Old failure evidence remains; use current manifest
and supervisor status to determine the final result.

Write level directories atomically. Resume verifies and skips completed/quarantined
levels and retries interrupted levels. Preserve previous artifacts under .previous-*.
Source/config/runtime changes require a new dataset. Transfer generated data separately
from Git, retaining hashes. Training must reference an exact dataset version.

Exclusive .campaign.lock and .extract.lock prevent simultaneous writers. After a
crash, inspect hostname/PID and confirm inactivity before clearing that single lock.
Automatic retry clears only its own exited worker's lock after confirming the PID
is dead. Never remove another process's lock or overwrite dataset provenance.

Final report: completed/quarantined levels, retries, integrity failures, splits,
coverage counts, usable labels, elapsed time, and dataset/log paths. A 100-level
estimate excludes setup/control replay and is only indicative. Training-readiness
flags are review signals, not permission to train or proof of scoring quality.

For implementation changes: npm test, focused experiment tests, Python compilation
for Python edits, git diff --check, and build for frontend edits. Documentation-only
updates need document/link and whitespace checks, not replay campaigns. Use
[Experiment], [Candidate], and [Promotion] boundaries and obtain approval for commits,
pushes, and promotion. Amend shared commits only with explicit approval; the current
final-documentation amendment is such an approved exception.

## Current Linux kickoff: training-only audit

Read AGENTS.md, docs/demo-scoring-linux-handoff.md, and this reference. Preserve the
notebook and staged changes. Verify the dataset's actual location, provenance and
integrity, then perform section 6 of the final handoff using training levels only.
Store reproducible audit reports separately under __data2. Reusable audit tooling
may be prepared for review; do not commit or push it without approval. Do not rerun
extraction, change candidates/scoring/labels, inspect held-out behavior for tuning,
or train. Return a concise evidence-backed report and the smallest next experiment.
