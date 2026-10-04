# Cohort catalog and workflow

## Purpose

The cohort catalog records what we have learned from retained game runs: which code and controls
produced them, what behavior they show, and which runs are useful comparisons. A cohort is a group
of traces used to investigate the same behavior or evaluate a change. A trace can belong to more
than one group.

The coding agent checks this catalog before investigating a trace to reuse earlier findings and
avoid treating an already-addressed defect as a new problem. Findings must still be checked against
the recorded evidence and current code. Dashboard and notebook anomaly flags are starting points,
not confirmed bugs.

## Data ownership

All three files are local to `__data1/`; the catalog is transient and does not need a Git commit.

| File | Owns |
| --- | --- |
| `recordings.json` | Pin state |
| `agent-traces.json` | Available traces and recorded decisions |
| `trace-cohorts.json` | Reviewed provenance, findings, group membership, and comparisons |

Pin changes require no catalog update. Unpinned traces remain subject to rolling retention.
The dashboard reads the recording and trace stores, not the cohort catalog.

## Create a cohort

Start with one concrete question, such as whether a change reduces repeated waits without losing
gold progress. Use existing Classic 1:1 traces first. Create separate cohorts for baseline and
changed code when comparing them; keep mode, model, and controls matched or explain differences.

1. Run `npm run cohorts:check`. If the catalog does not exist, create it with the empty structure
   below. The command does not create a catalog or review new traces automatically.
2. Choose a stable cohort ID, such as `20261007-wait-review-baseline`. Add its title, question,
   and full trace IDs under `cohorts`. Every ID must exist in `agent-traces.json`.
3. Review each trace and add or update its entry under `traces`. Use the recorded launch manifest
   or existing catalog evidence for provenance; never use current HEAD as a substitute.
   Preserve earlier findings and list every applicable cohort in the trace's `cohortIds`.
4. Record observations with display-step numbers (starting at 1) or exact game ticks. Separate
   observed behavior from suspected causes; state sample size and missing evidence. Update the
   cohort's `result` with the conclusion, or say the review is incomplete.
5. Update `updatedAt`, then run `npm run cohorts:check` again. Resolve stale links and report
   unreviewed traces. `--write` performs mechanical cleanup, not interpretation or cohort creation.

An empty catalog is:

```json
{"version": 1, "updatedAt": null, "cohorts": {}, "traces": {}}
```

Catalog fields follow this convention; the checker validates only part of it:

| Location | Fields |
| --- | --- |
| Root | `version: 1`, `updatedAt` (UTC timestamp), `cohorts`, `traces`; `policy` is maintained by reconciliation |
| `cohorts[cohortId]` | `title`, `question`, `traceIds` (full IDs), `result` (concise conclusion and evidence limits) |
| `traces[traceId]` | `reviewedAt`, `sourceRevision`, `sourceState` (`clean`, `dirty`, or `unknown`), `sourceFingerprint`, `context`, `outcome`, `classification`, `cohortIds`, `evidenceLimit` |
| Optional trace findings | `findings` (brief observations with steps/ticks), `compareWith` (full trace IDs) |

`sourceRevision` and `sourceFingerprint` belong to reviewed catalog evidence, not trace fields.
Experiment launchers should capture the revision and local-change fingerprint in a manifest
before running. Cataloging is not automatic: without recorded evidence, use null values and
`sourceState: "unknown"`, and explain uncertainty in `evidenceLimit`. `context` records level,
mode, model and relevant controls; `outcome` summarizes
the recorded result, decision count, terminal tick, and remaining gold where available. These are
review notes, not replacements for the original trace. Do not duplicate pin state in the catalog.

Keep membership consistent in both directions: a cohort's `traceIds` and each trace's `cohortIds`.
The checker does not enforce that agreement or verify provenance, findings, or comparison fairness;
the reviewing agent must check them. Cataloging does not authorize fresh runs or gameplay changes.

## Maintenance

- `npm run cohorts:check` — read-only; reports stale links and uncataloged traces, exiting nonzero
  when attention is needed.
- `npm run cohorts:check -- --write` — removes duplicated retention metadata and references to
  missing traces. Writes only the catalog and saves its previous version as `.bak`.

Both commands respect `AGENT_DATA_DIR`. Do not reconcile while another task edits the catalog.

The expected workflow in `AGENTS.md` is:

1. Check the catalog and read relevant findings before investigating.
2. Review the trace against its source revision, mode, model, and controls.
3. When cataloging is requested, reconcile and update the run's full-ID entry, evidence, comparison
   links, and cohort membership. Record unknown provenance explicitly; do not infer it from HEAD.
4. Check again and report any runs still needing review.

This is not automatic: there is no watcher or evaluator hook. The command catches missing entries
and stale references, but cannot diagnose runs or verify existing interpretations. Natural-language
requests are sufficient; the coding agent can run the commands for you.

## Reuse Evidence Before Rerunning

Use existing traces to explain recorded behavior and fixtures to test current logic against the
same inputs. Request a fresh run when the unanswered question concerns actual changed gameplay,
recurrence, or evidence that cannot be recovered. A summary is not a complete engine checkpoint,
and an old failure does not prove a current defect.

Before rerunning, state: **What question will this run answer that existing evidence cannot?**
Compare matching modes, models, and controls, identifying code differences explicitly.

| Question | Starting point |
| --- | --- |
| What happened in this run? | Trace and recording |
| Have we seen or addressed this pattern? | Catalog, supporting traces, and current code |
| Does current candidate logic handle the same input differently? | Deterministic fixture with sufficient reconstructed state/history |
| Does a change improve actual gameplay? | Fresh run on fixed code with matching controls |
| Is the failure intermittent or more general? | Additional matched runs |
| Is evidence incomplete or invalid? | Recover missing evidence first; rerun if necessary |

## Whole-store goals

| Goal | Useful request |
| --- | --- |
| Anomaly triage | Identify suspicious behavior across retained traces. Rank investigation candidates, distinguish addressed defects from potentially current issues, and cite steps. |
| Regression review | Compare recent runs with relevant baselines, accounting for revision, mode, model, and controls. Flag uncontrolled comparisons. |
| Coverage review | Identify well-tested behaviors, missing evidence, and the question that would justify another run. |
| Retention review | Recommend redundant traces to unpin while preserving useful baselines and unresolved examples. Wait for approval before unpinning. |

Add scope explicitly: “Update the catalog,” “diagnosis only,” or “propose a fix.” Diagnosis does not
authorize gameplay changes, pin changes, or paid evaluations.

## Pointing out an anomaly

Send the trace ID, suspicious display-step range if known, observed versus expected behavior, and
the requested scope. Copying the dashboard's **Run Signals** is a useful handoff, but it does not
replace the full trace. The trace ID alone is enough to start if its data remains available.

Pin evidence that must survive an investigation. When switching conversations, include the ID and
scope again rather than relying on shared chat memory.

## Copyable Prompts

### Check Or Repair The Catalog

> Check whether the cohort catalog matches the current stores. Report uncataloged traces and stale
> references. Do not change any files or pin states.

> Reconcile the cohort catalog with the current stores. Preserve diagnostic findings, report runs
> still needing review, and do not change recordings, traces, or pin states.

### Review A New Run And Catalog It

> Create a cohort to investigate `<question>` using `<trace IDs>`. Follow the creation convention
> above, review recorded provenance and controls, and record findings with steps/ticks and evidence
> limits. Update the catalog and check it afterward. Do not change gameplay or start new runs.

> Review `<trace ID>` against its relevant baselines. Verify provenance and controls, identify the
> strongest findings with display-step references, and update its cohort entry and membership.
> Mark uncertain provenance explicitly. Do not change gameplay or start new runs.

### Triage The Entire Store

> Review all retained traces for suspicious anomalies. Rank the strongest investigation candidates,
> distinguish historical addressed defects from potentially current unresolved issues, and cite
> representative steps. Update the cohort catalog, but do not change gameplay or run evaluations.

> Compare recent traces against relevant baselines for possible regressions. Account for source
> revision, mode, model, and controls. State where comparisons are not controlled.

> Review coverage across the retained traces. Which behaviors are well evidenced, which evidence
> is redundant, and what unanswered question would justify the next run? Do not run it yet.

### Diagnose A Specific Anomaly

> Diagnose `<trace ID>`, steps `<start–end>`. I observed `<behavior>` but expected `<behavior>`.
> Use the attached Run Signals as a starting point. Check prior findings and current code;
> classify the cause as coverage, scoring/selection, state, validation/execution, or loop handling
> where evidence permits. Do not implement a fix or start an evaluator run.

> Investigate the highest-priority unresolved anomaly and, if practical, add a focused deterministic
> regression fixture. Propose the smallest correction, but pause before changing gameplay behavior.

### Retention Review

> Recommend redundant traces to unpin, preserving distinct current baselines and unresolved failure
> examples. Explain each recommendation. Do not change retention until I approve.

Related: [Trace dashboard](trace-dashboard.md) · [Candidate design](candidate-design.md)
