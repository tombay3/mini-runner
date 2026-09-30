# Demo scoring experiment

## Scope

This is the extraction record and rerun guide. For the current stage, results,
authoritative dataset, audit boundary, and ownership rules, see the
[demo scoring roadmap](demo-scoring.md).

## What the labels mean

- Exact exposed: an eligible shortlisted candidate matched the demonstrated key and
  duration. Multiple matches are an action-equivalence set, not a known intent.
- Duration mismatch: an eligible candidate used the same key for a different duration.
  A shorter action may be a valid prefix of a recorded hold; a longer one may cross
  the next key change. Digging, falling, ladders, and target changes need specific
  evidence before treating either as a training label.
- Missing candidate: no eligible candidate used the demonstrated key at that sample.
  This does not distinguish generator gaps from ongoing-action sampling or other causes.
- Suppressed/rejected: a matching proposal existed but did not reach the eligible pool.

The [roadmap's audit section](demo-scoring.md#immediate-task-training-only-coverage-audit)
sets the current analysis boundary. A successful demo records one workable route; it
does not prove unique optimality or make every alternative a negative label.

## Extraction design

The campaign used wfastDemoData1: 150 Classic demonstrations. fast-demo1.json duplicates
Classic level 1 replay fields and was counted once. Other wData collections and the
smaller demo files were excluded.

Pipeline:

    recorded demo
    → isolated legacy replay in headless Chromium
    → state sampling at key changes / maxActionTicks
    → offline Python candidate analysis
    → immutable per-level artifacts
    → aggregate manifest and report

The runner starts a temporary loopback asset server. It needs neither Flask nor Vite,
loads no recording wrapper, makes no gameplay-model calls, and does not write __data1.
Candidate analysis runs after replay, imports no provider service, and blocks sockets.

The adapter exports state, observed history, proposal audit, pre-final-filter pool,
eligible ranked pool, shortlist, and match classification. It never invents candidate
IDs for demo history, so ID-dependent loop logic has less context than an agent run.

## Dataset layout

    <dataset>/
      manifest.json
      splits.json
      campaign-summary.json
      campaign.log
      reports/summary.json
      levels/classic-NNN/
        metadata.json
        states.jsonl
        decisions.jsonl
        checkpoints.jsonl
        coverage.json

Derived evidence belongs in:

    __data2/demo-scoring-audits/<audit-id>/

Record source dataset identity, audit code revision, configuration, and output hashes.
Generated data stays out of Git.

## Validation already completed

The campaign validated:

- Two matching level-1 pilot replays.
- Recorded terminal outcome and tick.
- Complete gold for successful demos.
- AI version, mode, Classic context, monotonic ticks, and bounded sampling intervals.
- Matching checkpoint hashes between control and sampled replay.
- Twenty successful gate levels before expanding to 150.
- Source/config/runtime compatibility and before/after __data1 hashes.
- Atomic output, artifact hashes, resume behavior, and lock ownership.
- Browser request isolation and Python network blocking.

Supporting commands:

- npm run demos:extract: direct pilot, 20-level, all-150, and resume modes.
- npm run demos:campaign: unattended pilot → 20-level gate → 150.
- npm run demos:test: extraction and supervisor regression suite.
- npm test: repository sanity checks.

## Future extraction reference

A new extraction requires separate approval and a fresh directory outside repository
worktrees. It uses Node 20+, Python 3.10+, distribution Chromium, npm dependencies, and
the project virtualenv. Flask and Vite remain unnecessary.

    npm test
    npm run demos:test
    npm run demos:campaign -- \
      --browser-executable /usr/bin/chromium \
      --output /home/USER/runner1-experiments/demo-scoring/<dataset-id>

Resume only when source, configuration, runtime, and completed-file hashes match:

    npm run demos:campaign -- --resume \
      --browser-executable /usr/bin/chromium \
      --output /home/USER/runner1-experiments/demo-scoring/<dataset-id>

The supervisor checks progress every five minutes, logs per-level details, and prints
one final report. It retries only recognized browser/process crashes, at most twice.
Validation, watchdog, source, integrity, and code failures stop the campaign. Never
remove a lock without confirming its recorded PID and hostname are inactive.

## Change checks

Follow the [roadmap's ownership rules](demo-scoring.md#ownership-and-workflow).
For changes run npm test, focused experiment tests, Python compilation where relevant,
npm run build for frontend edits, and git diff --check. Documentation-only edits need
link/content review and git diff --check; they do not require another replay campaign.
