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
See [store retention](../docs/backend-spec.md#trace-api-and-store) and [dashboard views](README.md#inspecting-a-trace).

## Check the catalog

Run `npm run cohorts:check` before reviewing traces.

| Command | What it does |
| --- | --- |
| `npm run cohorts:check` | Read-only check of live pairs, catalog membership, and archive paths. Reports complete live pairs without catalog entries. Does not read archive contents. |
| `npm run cohorts:check -- --write` | Creates a missing catalog or updates its availability status. Preserves historical entries and findings; backs up an existing catalog as `.bak`. Does not review or catalog new runs for you. |
| `npm run cohorts:check -- --verify-archives` | Reads linked local archives and checks that the recording and trace match. Use before reproduction or after transferring archives. |

Use the default `__data1` or set `AGENT_DATA_DIR`. Review only complete live recording/trace pairs. Keep active and orphaned traces out of gameplay cohorts. Record launcher failures in the campaign report.

If the checker reports stale availability or policy, use `--write` when updating the catalog. It preserves historical IDs and findings, including runs whose evidence is missing locally. Avoid concurrent catalog edits. Use `--verify-archives` to check linked IDs, streams, decisions, final tick, level and mode. Replay separately to verify gameplay against a revision.

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

Pin new evaluation runs by default. Keep ordinary completed games in the live stores. Archive a complete pair when it serves a specific future use:

- Preserve a representative baseline, evidence of a fix, or an unresolved failure.
- Prepare a run for replay or hybrid comparison.
- Protect needed evidence before unpinning or deleting live data.

Keep the campaign manifest and aggregate report. Archive a whole campaign only on explicit request. Save the selected pair under `__data3`, preserve the full run ID and available launch manifest, record the reason in the findings, and verify the archive links. When transferring an investigation, copy both objects and their catalog references together.

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

## Deferred archive improvements

Saving a pair and updating its catalog links are separate manual steps today. The proposed next step is one folder per full run ID and one repeatable command that copies both objects, verifies them, then records their links. Existing archives keep their original paths. Revisit stored availability flags after the new workflow has proved reliable.
