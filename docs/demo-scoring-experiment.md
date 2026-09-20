# Demo scoring experiment: Linux handoff

## Purpose and source

Extract replay states and candidate-ranking evidence without model calls. This phase
validates the pipeline on Classic level 1, then extracts 20 Classic levels. Training,
weight changes, production multi-level support, and promotion are deferred.

Base revision: `72d5735` on `pooh-dev`, including the Linux ladder-entry fix.
Before starting, inspect `git status --short --branch` and `git log -3 --oneline`.
Use the approved handoff commit containing these scripts. If Linux has advanced,
report the additional commits; never reset or infer the historical source from HEAD.
The manifest records the actual revision, worktree status, diff fingerprint, source
content hashes (including uncommitted extractor code), configuration, and runtimes.

The command serves an isolated page containing the existing legacy scripts in their
normal bootstrap order. It does not load the application or recording wrapper and
does not start Flask or Vite. Existing servers need no restart. Browser traffic is
restricted to read-only requests to its private local asset server. Candidate analysis
uses a local Python subprocess importing only the candidate pipeline; socket connects
are prohibited. Existing `__data1/` files are hashed before/after, never rewritten.

## Linux setup and commands

Use Node 20+ and Python 3.10+. In the `pooh-dev` checkout:

```bash
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm test
npm run demos:test
```

Install Chromium and its OS dependencies using the Linux distribution's package
manager. Pass the actual executable (commonly `/usr/bin/chromium` or
`/usr/bin/chromium-browser`). `playwright-core` does not download a browser.
The experiment needs no model credentials. Do not disable Chromium's sandbox to
work around a host configuration problem; run under a regular user.

```bash
# Pilot only: two ordinary-speed level-1 replays and offline candidate analysis.
npm run demos:extract -- --pilot \
  --browser-executable /usr/bin/chromium \
  --output /home/USER/runner1-experiments/demo-scoring/pilot-20

# Continue the SAME dataset after the pilot gate passes.
npm run demos:extract -- --resume \
  --browser-executable /usr/bin/chromium \
  --output /home/USER/runner1-experiments/demo-scoring/pilot-20
```

Replace `/home/USER` with the actual home directory. Alternatively omit `--output`
on the initial invocation to use `~/runner1-experiments/demo-scoring/<dataset-id>`.
The command prints the resulting path. `--resume` always requires that explicit path.
Omit `--pilot` on the first invocation to run both phases automatically. `--python`
or `DEMO_PYTHON` can select a Python executable; the default is `.venv/bin/python`.
`CHROME_PATH` is an alternative to `--browser-executable`.

Keep the Linux host awake using its normal host policy. Run inside `tmux` if the SSH
connection may close. The batch command owns progress and recovery; a Codex goal is
optional supervision, not a dependency. It reports each completed level and emits
a heartbeat every 30 seconds. No macOS `caffeinate` command is used on Linux.

## Sampling, labels, and partitions

Only `wfastDemoData1` is used. Its level-1 replay fields must exactly match
`docs/fast-demo1.json`. The fixture is counted once. The smaller demo collections
are excluded. Player names, IPs, and other player metadata are not exported.

Twenty levels are selected as `1 + round(i * 149 / 19)`, for `i=0..19`.
Every fifth selection is test; every fifth starting at the fourth is validation;
the rest are training (12/4/4). Identical map hashes inherit the first map's split,
keeping level 1 in training. `splits.json` records intended and actual assignments.
Reserve test levels before training; do not tune on their coverage examples.

Playback uses recorded AI, god mode, key/tick events, gold drops, and respawns.
Ordinary demo speed is retained (currently 35 ticks/second). Headless does not mean
accelerated. Samples precede action changes and occur at most `maxActionTicks`
apart. Snapshots use the demo tick as `tick` and `timing.recordTick`; the original
recording tick is retained as `legacyRecordTick` because recording is disabled.

Candidate analysis happens after playback, so Python latency cannot affect the game.
The adapter captures proposed scores/actions, rejection and suppression audits,
the pool before final loop filtering, the eligible ranked pool, the exposed shortlist,
and state-analysis features. It reconstructs bounded history from observed snapshots
and actions. It never invents candidate IDs; ID-dependent loop detection consequently
has less information than during an actual agent run.

Exact validated key/duration matches are high-confidence **action-equivalence** labels,
not proof of optimality or intent. Multiple exact candidates form a positive set.
Same-key/different-duration candidates are ambiguous and excluded by default.
The report separates exact exposed, exact truncated, suppressed/rejected, duration
mismatch, and missing-candidate samples. Clipped final actions can lower exact-match
coverage. Do not change candidate timing merely to improve these labels.

## Output, resume, and integrity gates

All artifacts live outside repository worktrees:

```text
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
```

Metadata includes sanitized demo data, source demo/map hashes, terminal evidence,
validation, replay time and analysis time. Decision rows link by tick to states and
include their observed history, pools/audits, features, and matching labels.
The manifest includes file hashes, per-level states, and the pilot gate result.
The report estimates 100-level cost from observed replay plus analysis time; pilot
control replay and browser startup are excluded. This estimate needs more than one
level before it is representative. `readyForTrainingReview` is a review signal, not
approval to train or evidence of a good learned policy.

Level output is staged and renamed atomically. Resume verifies completed file hashes,
skips intact completed levels, and retries interrupted/quarantined levels. Previous
failed artifacts are retained under `.previous-*`. Source/config/runtime changes
require a new dataset directory. Do not silently resume after amending code.

An exclusive `.extract.lock` prevents simultaneous writers. After a crash, inspect
its PID/hostname and confirm that extraction is inactive before removing that single
lock file. Normal completion and handled failures release the lock. Do not delete
partial or previous artifacts as routine cleanup; they remain diagnostic evidence.

The pilot compares ordinary control playback (checkpoints only) against sampled
playback. Both must reproduce the recorded terminal tick and outcome, with matching
state checkpoints and complete gold for a successful demo. Samples must have monotonic
ticks, correct Classic level and mode, and bounded gaps. Candidate coverage has no
arbitrary pass threshold. Any unexpected network request, browser/adapter error, or
store mutation fails the campaign. Other levels with replay mismatches are quarantined
while subsequent levels continue. Report failures; do not repair demos or engine data.

Before handoff: `npm test`, `npm run demos:test`, Python compilation, and
`git diff --check`. Run `npm run build` if frontend code changes. Report checks that
could not run. Commit boundary: `[Experiment] Add offline demo extraction pilot`.
Ask the user before committing and pushing. Never rewrite shared Linux commits.

## Linux task prompt

Read AGENTS.md and this document. Verify the handoff revision and preserve existing
changes. Run the level-1 pilot, then the documented 20-level extraction if its gates
pass. Use no paid model calls and leave existing `__data1/` stores untouched. Keep
outputs in the external dataset directory and make execution resumable. Report
completed/failed levels, split sizes, usable labels, candidate gaps, replay/analysis
timing, output location, and training readiness. Stop before scorer training. Ask
for approval at commit boundaries, before pushing, and before promotion or rewriting
shared commits. Transfer generated data separately from Git, preserving file hashes.
