# Trace cohorts

The catalog at `__data1/trace-cohorts.json` keeps findings from game runs, links to
saved data, and groups of runs used to answer the same question. These groups are
called **cohorts**; a run can belong to several.

**Keep the recording and trace if you may need to reproduce a bug.** The catalog
preserves what we learned after live data is deleted, but cannot reproduce gameplay
by itself. Archiving is a separate, explicit operation.

## Files and ownership

| Location | Contents |
| --- | --- |
| `__data1/recordings.json` | Live recordings and pin state |
| `__data1/agent-traces.json` | Live traces with recorded decisions |
| `__data1/trace-cohorts.json` | Findings, source-code information, groups, comparisons, and archive links |
| `__data3/` | Machine-local archives and investigation files |

These files do not need a Git commit. Deleting live data must preserve catalog
entries and groups. Pin changes need no catalog edit; unpinned data can age out
through rolling retention. The dashboard reads the live stores, not the catalog.
See [store retention](backend-spec.md) and [dashboard views](trace-dashboard.md).

## Check the catalog

Run `npm run cohorts:check` before reviewing traces.

| Command | What it does |
| --- | --- |
| `npm run cohorts:check` | Read-only check of live pairs, catalog membership, and archive paths. Reports complete live pairs without catalog entries. Does not read archive contents. |
| `npm run cohorts:check -- --write` | Creates a missing catalog or updates its availability status. Preserves historical entries and findings; backs up an existing catalog as `.bak`. Does not review or catalog new runs for you. |
| `npm run cohorts:check -- --verify-archives` | Reads linked local archives and checks that the recording and trace match. Use before reproduction or after transferring archives. |

No command scans archive folders or creates an archive. Missing local archives and
historical member IDs without detailed entries are quietly skipped and preserved.
Malformed references and inconsistent membership are still reported.

Active or orphaned traces without a complete recording/trace pair are excluded
from new-run review lists. Do not add them to gameplay cohorts or replay archives;
keep infrastructure failures in campaign logs and reports. `--write` does not
delete live data, archive files, or historical findings when a pair is unavailable.

“Catalog availability or policy needs updating” means saved `dataStatus` values
or checker-maintained policy differ from the current check. For example, a deleted
live pair may now be available only in an archive. `--write` saves those updates;
it does not diagnose runs, repair archive contents, or remove obsolete files.

All modes use `AGENT_DATA_DIR` when set; otherwise they use `__data1`. Missing live
store files count as empty stores and are not recreated. Avoid `--write` while
another task is editing the catalog.

Archive verification checks IDs, recording streams, trace decisions, final tick,
level, and mode. It does **not** replay gameplay, confirm findings, or prove that a
recording will replay correctly against another code revision.

## Review runs and update findings

1. **Check and read.** Run the quick check, then read earlier catalog findings and
   the relevant recording and trace. Dashboard signals identify places to inspect;
   they do not prove a bug.
2. **Define the question.** For example: does a change reduce repeated waits without
   losing gold progress? Use existing Classic 1:1 runs first. Compare matching mode,
   model, and controls, and explain any code or configuration differences.
3. **Record the evidence.** Add findings under `traces[full UUID]`, citing display
   steps (starting at 1) or game ticks. Separate observations from suspected causes.
   Use the launch manifest or recorded historical evidence for the source revision,
   never the current HEAD. Mark missing information as unknown.
4. **Group comparisons.** Add a cohort with a stable ID, such as
   `20261007-wait-review-baseline`. Keep both its `traceIds` and each run's `cohortIds`
   consistent. Use separate groups for baseline and changed code where useful.
   Record the conclusion, sample size, and limits—or state that review is incomplete.
5. **Save and check.** When cataloging is requested, run `--write`, update findings
   and `updatedAt`, then check again. Report any live runs still needing review.

Preserve earlier findings. The checker does not judge their accuracy or whether a
comparison is fair. Cataloging does not authorize gameplay changes, pin changes,
or paid evaluations.

## When to archive a live run

**Archive selected runs with a concrete future use, not every completed run.**
Saving, pinning, cataloging, or requesting debugging does not automatically create
or require an archive. Review with the user is not a prerequisite; the deciding
question is what investigation or comparison needs the full data.

| Trigger | When to archive | Examples |
| --- | --- | --- |
| Preserve campaign evidence | A selected run supports a finding or future comparison. | Representative baseline, evidence of a fix, suspected regression, or distinct unresolved failure. |
| Prepare a reproducer | A run is selected for replay or testing alternative decisions. | Save the original pair before a hybrid comparison; its preparation step captures both in `input.json`. |
| Remove useful live data | A run still has a debugging purpose but is about to be unpinned or deleted. | Verify an existing archive or save the pair before removing an unresolved example or needed baseline. |

Keep ordinary completed or unreviewed runs in the live stores and pin new evaluation
runs by default. Pinned runs survive rolling retention, so retention alone does not
justify an archive copy. Routine successes and duplicate failures usually need no
separate archive.

Keep the campaign launch manifest and aggregate report for its setup and results.
Archive full pairs only for selected supporting examples, unless the user explicitly
requests every run. Record the reason in the catalog findings so later work can
understand why the archive was kept.

Save both objects under `__data3`, in a bundle or separate store backups. Keep the
full run UUID and available launch manifest. Add `archive` references to the catalog
and run `--verify-archives`. A report alone is not a replay backup; an existing
complete archive does not need another copy.

Archives differ between machines. When transferring an investigation, copy the
recording, trace, and catalog references together.

## Find historical replay data

Look up the full run UUID in the catalog. Try the live stores first, then follow
its `archive` references. For a bundle containing both objects:

```json
"archive": {
  "recording": {"path": "__data3/example/evidence.json", "keys": ["recording"]},
  "trace": {"path": "__data3/example/evidence.json", "keys": ["trace"]}
}
```

`keys` identifies the object inside the JSON file. For separate store backups,
use `["records", "<full UUID>"]` and `["runs", "<full UUID>"]`. Paths are relative
to the repository root, even when `AGENT_DATA_DIR` is set.

If links are missing, manually search catalogs and backups under `__data3` and
verify the pair before adding references. Older `evidence` and `artifacts` fields
are notes, not links the checker follows. Keep original archives unchanged and
record a fresh launch manifest for any new continuation.

## Catalog fields

An empty catalog starts as:

```json
{"version": 1, "updatedAt": null, "cohorts": {}, "traces": {}}
```

| Location | Fields and meaning |
| --- | --- |
| Root | `version: 1`, `updatedAt` (UTC), `cohorts`, `traces`. The checker maintains `policy`. |
| `cohorts[id]` | `title`, `question`, `traceIds` (full UUIDs), `result` (conclusion and limits). |
| `traces[id]` | `reviewedAt`, `classification`, `cohortIds`, `findings` (steps/ticks), optional `compareWith` (full UUIDs). |
| Run source | `sourceRevision`, `sourceState` (`clean`, `dirty`, or `unknown`), `sourceFingerprint`, `evidenceLimit`. Use null for unavailable source values and explain uncertainty. |
| Run context and result | `context`: level, mode, model, controls. `outcome`: result, decision count, final tick, remaining gold where known. These are review notes, not a replacement for the trace. |
| `archive` | Recording and trace references as shown above. |
| `dataStatus` | Checker-maintained: `live` means a matching live pair; `archived` means linked files exist locally; `missing` means neither is available. Not proof of successful replay. |

Record source revision and local changes in a launch manifest before experiments;
new traces do not store them. Do not duplicate pin state in the catalog.

## Choose the next investigation

| Question | Start with |
| --- | --- |
| What happened, and have we seen it before? | Recording, trace, earlier findings, and current code |
| Does current logic handle this state differently? | Offline fixture with the required state and history |
| Does a change improve gameplay or reduce recurrence? | Matched replay or new runs, stating what the comparison can establish |
| Is evidence missing? | Recover archives before considering another run |

Before rerunning, state what question existing evidence cannot answer. An old
failure does not prove a current bug, and a summary is not an engine checkpoint.

Useful request examples:

- **Review and catalog:** “Review `<trace IDs>` for `<question>`. Cite steps, update
  findings and groups, and check the catalog. Do not change gameplay or start runs.”
- **Diagnose:** “Debug `<trace ID>`, steps `<start–end>`. Observed `<behavior>`;
  expected `<behavior>`. Check previous findings. Propose a fix without applying it.”
- **Review the store:** “Rank unresolved anomalies and possible regressions across
  retained runs. Note comparison limits and missing coverage. Update the catalog.”
- **Review retention:** “Recommend redundant runs to unpin while preserving useful
  baselines and unresolved examples. Wait for approval before changing pins.”

Include the run ID and scope when handing work to another session. Run Signals
help locate an issue but do not replace the full data.

## Future simplification — not implemented

The main weakness is that saving data, adding findings, and maintaining archive
links are separate manual tasks. More checks alone cannot recover missing data.
A simpler workflow would use:

- **One archive folder per run**, named by its full UUID, containing the recording,
  trace, and available launch information. Predictable paths replace custom JSON
  references for new archives.
- **One command to preserve a run.** Copy both objects, verify them, then update the
  catalog. Failure leaves live data untouched; repeating the command is safe.
- **A catalog focused on findings and groups.** Check local availability when needed
  instead of storing a status that can become stale. Keep historical findings even
  when their data is unavailable on this machine.

Keep routine checks fast: check structure and expected files. Read archive contents
only for explicit verification, such as before reproduction or after transfer.
Unavailable historical data should not fail routine tests.

Introduce the folder convention and preservation command first, use them for new
investigations, then simplify the catalog once the workflow proves reliable. Avoid
a large archive migration or another supervisor. Existing archives and links must
remain usable during the transition.

Related: [Evaluator workflow](evaluator.md) · [Trace dashboard](trace-dashboard.md) ·
[Candidate design](candidate-design.md)
