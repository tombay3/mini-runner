# Demo scoring experiment: unattended Linux campaign

## Task and boundaries

Run a level-1 pilot, validate 20 Classic levels, then automatically extract all 150
levels in wfastDemoData1. Defer scorer training, deeper analysis, code iteration,
candidate/label changes, and production multi-level support.

Base revision: 72d5735. Initial extraction handoff: 796a22c. Pull the latest approved
pooh-dev commit containing demos:campaign. Inspect revision and worktree first;
preserve unexpected changes and report them rather than resetting.

The runner starts its own temporary loopback asset server and headless Chromium.
Flask and Vite are unnecessary. It loads legacy scripts without the recording wrapper,
restricts browser requests to local GETs, and runs analysis in a Python subprocess
that blocks socket connections and imports no provider service. No paid gameplay
model calls or writes to __data1/ are allowed. Runtime stores are hashed before/after.

## Linux setup and commands

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

Keep all artifacts outside repository worktrees:

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

Before handoff: npm test, npm run demos:test, Python compilation, git diff --check;
build if production frontend changes. Use [Experiment] boundaries and obtain approval
for new commits/pushes. Never rewrite shared Linux commits.

## Linux Codex prompt (Luna, Low reasoning)

Read AGENTS.md and this document. Verify the approved checkout and preserve changes.
Set up dependencies and Chromium, run tests, then launch the unattended 150-level
campaign. Resolve routine executable-path/dependency issues only. Do not modify
code, candidates, labels, gates or scoring. Let the supervisor handle retries and
five-minute monitoring. Do not report individual levels. Report once on completion
or an unrecoverable stop, with dataset path, counts, coverage, integrity and timing.
Defer analysis, code iteration and training. Do not start Flask/Vite or modify
__data1/. If setup needs interactive authority you lack, stop and explain the blocker.
