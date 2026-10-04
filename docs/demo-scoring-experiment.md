# Demo scoring experiment record

## Scope

This document records extraction, audit, validation, and recovery details. See
[Demo scoring](demo-scoring.md) for the conclusions and deferred roadmap.

The completed dataset is retained at:

    __data2/demo-scoring/20260920-010128

Keep the original artifacts and labels unchanged. Store derived audits under:

    __data2/demo-scoring-audits/<audit-id>/

## Using the data beyond Classic 1:1

The `demo-dev` branch retains these tools on top of the published baseline. The
150-level dataset is local generated data, not part of the commit. Copy it
separately when moving to another machine, preserving its manifest and artifacts.
Offline replay and analysis cover Classic levels 1–150; live agent support remains
limited to `playData=1`, `level=1` until the wrapper, backend and evaluator context
checks are deliberately extended. Reanalysis alone does not enable later levels.

For incremental work on 1:2, 1:3 and onward, use the matching `classic-NNN`
directory. For example, 1:2 is `levels/classic-002`. Check `metadata.json` for
`playData`, `level`, `demo.godMode`, `demo.ai`, `mapHash` and `validation.valid`.
Check `splits.json` before using a level to design a fix. A held-out level used
for development must be recorded as such and cannot remain an independent
validation/test result for that change.

| Artifact | Use during debugging |
| --- | --- |
| `manifest.json` | Identify extraction code, config, runtime and per-level file hashes. Verify these before using a copied dataset. |
| `metadata.json` | Check the map, demo version, mode, terminal result and replay validation. `demo.action` stores alternating tick/key-code values; `goldDrop` and `bornPos` retain additional replay events. |
| `states.jsonl` | Inspect full sampled runner, guard, terrain, gold, dig and hole state. Sampling occurs at key changes and at bounded intervals, with a terminal sample. |
| `decisions.jsonl` | Inspect historical demonstrated actions, proposals, rejections, eligible candidates, shortlist and match classification. These reflect the extraction code, not later fixes. |
| `checkpoints.jsonl` | Compare replay state and timeline evidence when investigating runtime drift. |
| `coverage.json` | Find levels or action groups with missing candidates, duration differences or filtered proposals; then inspect individual decisions. |

### Reanalyse one level with the checked-out code

`scripts/demo-candidates.py` reads one JSON payload from stdin and writes
`{decisions, coverage}` to stdout. It uses the current `agent/` files, imports no
provider service, and blocks socket connections. No browser, Flask or Vite is
needed. Run from a checkout containing the retained tools:

```sh
set -o pipefail
demo_dataset="$PWD/__data2/demo-scoring/20260920-010128"
demo_level_dir="$demo_dataset/levels/classic-002"
demo_audit="$PWD/__data2/demo-scoring-audits/<new-audit-id>"

node --input-type=module -e '
  import fs from "node:fs";
  import {verifyFiles} from "./scripts/extract-demos.mjs";
  const [dataset, dir] = process.argv.slice(1);
  const manifest = JSON.parse(fs.readFileSync(`${dataset}/manifest.json`, "utf8"));
  const meta = JSON.parse(fs.readFileSync(`${dir}/metadata.json`, "utf8"));
  const entry = manifest.levels[meta.level];
  if (entry?.status !== "completed" || !meta.validation.valid ||
      !verifyFiles(dir, entry.files)) throw new Error("Invalid or changed level artifacts");
' "$demo_dataset" "$demo_level_dir"

mkdir -p "$demo_audit"

git rev-parse HEAD > "$demo_audit/revision.txt"
git status --porcelain > "$demo_audit/worktree-status.txt"
git diff HEAD --binary > "$demo_audit/worktree.patch"
sha256sum "$demo_dataset/manifest.json" \
  "$demo_level_dir/metadata.json" "$demo_level_dir/states.jsonl" \
  public/agent-config.json > "$demo_audit/input-hashes.txt"
cp public/agent-config.json "$demo_audit/config.json"

node --input-type=module -e '
  import fs from "node:fs";
  const [dir, configPath] = process.argv.slice(1);
  const states = fs.readFileSync(`${dir}/states.jsonl`, "utf8")
    .trim().split(/\n/).filter(Boolean).map(line => JSON.parse(line));
  const {demo} = JSON.parse(fs.readFileSync(`${dir}/metadata.json`, "utf8"));
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  process.stdout.write(JSON.stringify({states, demo, config}));
' "$demo_level_dir" "$demo_audit/config.json" |
  .venv/bin/python scripts/demo-candidates.py \
    > "$demo_audit/classic-002-candidates.json"

sha256sum "$demo_audit/classic-002-candidates.json" \
  > "$demo_audit/output-hash.txt"
```

Use a fresh audit directory and stop if verification or analysis fails. Bash
`set -o pipefail` makes a failed payload command fail the pipeline. Keep the
checkout/config fixed until analysis finishes. The patch records tracked edits;
copy or hash relevant untracked code separately if the checkout is dirty.
For a code-only comparison, use `manifest.source.config` for both analyses.
Using the current config instead measures code and config together.

Compare derived rows with original decisions by level and `tick`, then compare
`demonstratedAction`, `shortlist`, `analysis.candidateAudit`,
`analysis.preFinalizationPool` and `analysis.eligiblePool`. Check key, duration,
kind and target as well as candidate ID. A matching key with another duration is
not an exact match. Preserve the original decisions and labels.

### Debug each newly supported live level

1. Before launch, record the source revision, dirty code, config, level, mode and
   model in a launch manifest. Extend the relevant context checks and evaluator
   level selection before attempting a live 1:2 run; there is no retained
   extractor `--level` flag or general live-level switch in these tools.
2. Inspect the live failure and use the demo to find a comparable situation:
   runner position/offset, terrain, remaining gold, guard motion, holes and active
   digs. Demo `tick` is the replay clock; `legacyRecordTick` preserves the original
   snapshot clock. Live and demo routes can differ, so equal ticks or coordinates
   alone do not establish equivalent decisions.
3. Reanalyse saved demo states with the proposed candidate fix. Classify the gap
   as missing generation, physical/safety rejection, deduplication, loop
   suppression, truncation, duration mismatch or selection. The adapter rebuilds
   observed demo history without candidate IDs; use real live history to confirm
   a loop-dependent bug or a state absent from the demo.
4. Make one generic, evidence-backed fix and run the new level again, with 1:1 as
   a regression check. Follow [cohort maintenance](trace-cohort.md) for live trace
   review and cataloging. Offline agreement does not establish autonomous safety
   or completion, and a demo shows one workable route rather than the best action
   in every state.

`demo-replay.mjs` exports `replayInPage` for the extractor's isolated legacy
page; it is not a standalone CLI or a live-state reset tool. `demos:extract`
supports a level-1 pilot, a fixed 20-level gate, or all 150 levels. The campaign
supervises extraction, not live evaluator runs. If replay/runtime hashes no
longer match, reanalysis alone is insufficient: arrange a fresh extraction
outside worktrees using the commands below. Changed code/config cannot resume
the old extraction manifest. The removed top-score selector is not available.

## Label definitions

- **Exact exposed:** an eligible shortlisted candidate matched the demonstrated
  key and duration. Multiple matches identify equivalent actions, not intent.
- **Duration mismatch:** an eligible candidate used the same key for another
  duration. A shorter action may be a valid prefix; a longer action may cross
  the next key change. Digging, falling, ladders, and target changes need specific
  evidence before either becomes a label.
- **Missing candidate:** no eligible candidate used the demonstrated key. The
  cause may be missing generation, sampling during an action, unsupported
  movement, or insufficient evidence.
- **Suppressed/rejected:** a matching proposal existed but did not reach the
  eligible pool.

## Extraction design

The campaign used `wfastDemoData1`: 150 Classic demonstrations. `fast-demo1.json`
duplicates Classic level 1 replay fields and was counted once. Other `wData`
collections and smaller demo files were excluded.

    recorded demo
    → isolated legacy replay in headless Chromium
    → state sampling at key changes / maxActionTicks
    → offline Python candidate analysis
    → immutable per-level artifacts
    → aggregate manifest and report

The runner starts a temporary loopback asset server. It does not require Flask or
Vite, load the recording wrapper, make gameplay-model calls, or write `__data1`.
Candidate analysis runs after replay, imports no provider service, and blocks
sockets.

The adapter exports state, observed history, proposal audit, candidates before
final filtering, eligible ranked candidates, shortlist, and match classification.
It does not invent candidate IDs for demo history, so ID-based loop checks have
less context than in an agent run.

## Dataset and provenance

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

The manifest records the extraction source revision, uncommitted-change hash,
configuration, runtime versions, partitions, and artifact hashes. Never infer
historical provenance from current HEAD. Recorded paths may refer to the original
location before the dataset moved.

Derived reports record dataset identity, audit code revision, configuration, and
output hashes. Generated artifacts remain ignored and out of Git.

## Completed validation

The campaign validated:

- Two matching level-1 pilot replays.
- Recorded terminal outcome and tick.
- Complete gold for successful demos.
- AI version, mode, Classic context, monotonic ticks, and bounded sampling.
- Matching checkpoint hashes between control and sampled replay.
- Twenty successful gate levels before expansion to 150.
- Source, configuration, runtime, and before/after `__data1` compatibility.
- Atomic output, artifact hashes, resume behavior, and lock ownership.
- Browser request isolation and Python network blocking.

## Training-only audit

Exploratory analysis used only the 90 training levels. Validation and test data
were checked for integrity but not inspected to design labels or fixes.

The audit reported exact matches by level, key, candidate kind and lane, rank,
score margin, state category, and equivalence. It classified duration differences
by direction and movement context, and missing candidates by proposal, filtering,
rejection, suppression, sampling, unsupported movement, or unknown cause.
Representative evidence retained level, tick, source artifact, state,
demonstrated action, proposal audit, eligible pool, and shortlist.

Rebuilt-branch reports are under:

- `20261001-post-sync-baseline-v1`
- `20261001-post-sync-prefix-revalidation-v1`
- `20261001-offline-top-score-v1`

All are within `__data2/demo-scoring-audits/`. Counts require denominators. A
missing-candidate classification does not prove physical impossibility.

## Scoring and top-score procedure

The scoring inventory centralized constants and recorded actual score components.
It verified that totals, ordering, shortlist membership, deduplication, filtering,
and fallback behavior remained unchanged.

The temporary evaluator-only top-score selector retained normal generation,
filtering, stable order, V2 validation, and action translation while bypassing
only model selection. Baselines measured completion, remaining gold, deaths,
time, decisions, no-progress spans, loops, suppression, fallbacks, candidate
availability, selected rank, and score margins. Coverage, ranking, state,
timing, and loop failures remained separate.

The selector was removed after the experiment. Its retained reports remain the
historical baseline; the command is no longer available.

## Commands and recovery

- `npm run demos:extract`: direct pilot, gated, full-set, and resume modes.
- `npm run demos:campaign`: unattended pilot → 20-level gate → 150 levels.
- `npm run demos:test`: extraction and supervisor regressions.
- `npm test`: repository sanity checks.

A new extraction requires separate approval and a fresh directory outside a
repository worktree. It needs Node 20+, Python 3.10+, distribution Chromium, npm
dependencies, and the project virtualenv.

    npm test
    npm run demos:test
    npm run demos:campaign -- \
      --browser-executable /usr/bin/chromium \
      --output /home/USER/runner1-experiments/demo-scoring/<dataset-id>

Resume only when source, configuration, runtime, and completed-file hashes match:

    npm run demos:campaign -- --resume \
      --browser-executable /usr/bin/chromium \
      --output /home/USER/runner1-experiments/demo-scoring/<dataset-id>

Check for an existing campaign before launch. The supervisor checks progress every
five minutes, records detailed output in `campaign.log`, and retries recognized
browser or process crashes at most twice. Validation failures, progress timeouts,
source changes, integrity failures, and code errors stop the campaign. Remove a
lock only after confirming its recorded owner is inactive on the recorded host.

## Workflow and boundaries

The experiment followed this order:

1. Verify provenance and audit training evidence without using held-out behavior.
2. Centralize scores and verify unchanged candidate behavior.
3. Run the temporary top-score baseline and classify disagreements without
   treating them as errors.
4. Consider one bounded scoring change at a time with other training levels as
   controls. No change was promoted from offline agreement alone.
5. Remove temporary evaluator support and retain the data and reports.

Linux `/home/tomchin/3po/ducky/run-8283` is the single active writer. Preserve
manual and staged work and avoid concurrent edits. Ask before behavior changes,
new extraction, label conversion, training, paid models, live runs, commits,
pushes, promotion, or shared-history changes.

For an approved live evaluator run, ask the user to stop a running Flask backend.
Let the evaluator own its backend, reuse a compatible Vite frontend, and keep
Chromium sandboxing enabled. Offline work starts no gameplay services.

Use `[Experiment]` for disposable infrastructure, `[Candidate]` for behavior under
evaluation, and `[Promotion]` for an approved durable result. Promote one clean
commit rather than an experimental branch.

Run `npm test`, focused tests, Python compilation where relevant,
`npm run build` for frontend changes, and `git diff --check`. Documentation-only
changes need link/content review and `git diff --check`; they do not require a new
extraction.
