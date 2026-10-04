# Trace Dashboard

`trace-dash.py` is a read-only Streamlit dashboard for Classic `playData=1, level=1` recordings
and agent traces. Compare runs, inspect decisions and locate suspicious events without changing
gameplay or stored evidence.

## Observability workflow

| Section | Purpose | Useful evidence |
| --- | --- | --- |
| **1 — Run Overview** | Roll up and compare retained runs. | Outcomes, steps, game time, gold, candidate availability, model departures, warnings and loops. |
| **2 — Trace Inspector** | Drill down into a selected decision. | Pre-action state, exposed candidates, requested and executed choices, reasons, suppression and safety rejections. |
| **3 — Run Signals** | Find anomaly/event windows worth reviewing. | Progress delays, constrained choices, loops, stationary stalls, model departures and validation interventions, with step links and copyable context. |

Start with the overview, use a signal to jump to a decision, then inspect surrounding steps.
Signals identify evidence windows, not confirmed bugs or proof that a rejected action was safe.

## Documentation ownership

| Document | Owns |
| --- | --- |
| [Backend specification](backend-spec.md#trace-api-and-store) | Canonical trace API/store contract, field meanings and retention; implemented by `app.py` and `agent/traces.py`. |
| This document | Dashboard loading, derived columns, markers, signals and navigation; `trace-dash.py` is the UI implementation reference. |
| [Trace cohorts](trace-cohort.md) | Reviewed provenance, findings, comparison groups and investigation workflow. |
| [Evaluator](evaluator.md) | Run collection, controls, validation and evaluator reports. |

Keep stored-field definitions in the backend specification. Derive dashboard and notebook summaries
from that contract rather than duplicating fields in the store.

## Start and load data

Run from the repository root:

```sh
npm run dash
```

The default folder is `__data1`. Set `AGENT_DATA_DIR` or use the sidebar to select a folder containing
`recordings.json` and `agent-traces.json`. Relative paths resolve from the repository root. The sidebar
shows recording count, store update time and loading warnings. Press **Reload data** after an external
import or edit: each folder's loaded data is cached until reload.

Loading starts from recordings and joins traces by full `traceId`. Trace model metadata takes
precedence over recording `solver` metadata. Validate the trace store's integer `version: 4` and
`runs` dictionary. Missing stores or loading failures produce warnings.

The dashboard builds `runs_df` (recordings joined to run metadata) and `steps_df` (decisions, state,
actions, candidate events and derived after-state). After-state is the next step's state, or
`outcome.finalState` for the final action. An absent final state or model context remains unknown;
do not reconstruct it or modify archived evidence.

## Section 1: Run Overview

Rows are newest-first by recording `savedAt`. Selecting a row sets the trace shown in Sections 2
and 3; the newest row is the default. Short IDs are display labels, not replacements for stored
full IDs. Manual recordings display `user`; pinned recordings append `📌`.

The header appends `(average x steps · m:ss)` across stored recording rows, including pinned runs.
Steps are rounded to a whole number; game time is averaged from raw ticks before display rounding.
Missing times are omitted from the time average, not counted as zero. Sections 2 and 3 instead
show the selected run's `(n steps · m:ss)`.

| Column | Meaning |
| --- | --- |
| `#`, `traceId`, `savedAt` | Row number, short trace ID and local timestamp (`MM-DD HH:MM`). |
| `steps` | Recorded decisions; not elapsed time or progress. |
| `outcome` | Failure/stop reason, with `✅` for completion and `⭐` for god mode. |
| `time` | Observed game time (`gameTime`), using 16 ticks per second. A run stopped alive has an unknown eventual outcome. |
| `🧈` | Initial remaining gold minus terminal remaining gold; missing counts stay blank. |
| `🎯` | Average exposed candidates per step, not necessarily distinct actions. |
| `✨` | Model divergences: steps meeting the lower-score, distinct-action request test below. |
| `⚠️` | Steps with replacement, non-null fallback or loop suppression; count each step once. |
| `🔁` | Active confirmed loop steps; count each step once. |
| `record` | Wall-clock trace duration: `updatedAt - createdAt`, separate from game time. |
| `model` | Resolved model identifier. |

### Event markers

`✨` requires an exposed requested candidate below the highest exposed score, with a `(keyCode,
ticks)` action different from every top-score candidate's action. Unknown IDs, equal top scores and
equivalent top actions do not qualify. This test concerns the **requested** choice; inspect
`decision.selectedId` and fallback to confirm execution. It is stricter than the offline count of
all executed lower-score selections.

`⚠️` covers replacement when a nonempty requested ID differs from the selected ID, a non-null
fallback, or loop suppression. Safety rejection alone marks its candidate row, not the whole step.
`🔁` comes from `loop.active`, not inferred repeated movement.

## Section 2: Trace Inspector

Each decision has an expander in a fixed-height scrollable panel. Its title shows the one-based
step number, executed key/ticks, runner position, remaining gold, reported risk, selected candidate
ID and pre-action game clock (`state.tick / 16`). The same `✨`, `⚠️` and `🔁` markers apply.

The candidate table separates exposed choices from loop-suppression and safety-rejection events.
Requested, executed, fallback, lower-score and suppression markers remain beside the relevant
reason. IDs identify candidate kind, so the compact table omits that redundant column. Structured
targets remain in the trace but are not displayed here.

Only exposed `candidates` contribute to counts, lanes, singleton classifications and distinct-action
counts. Event rows have blank scores and are not available model choices:

- Loop-suppression rows use the first event per ID; their derived list/count is deduplicated.
- Safety-rejection rows preserve repeated occurrences, including repeated IDs.
- Raw `candidateEvents` retains every occurrence. Other statuses remain in the trace without
  dedicated table rows.

The selected candidate's `firstAction.reason` explains the action. Intervention details come from
`decision.fallback`; the brief model rationale comes from `decision.rationale`. Preserve these
distinctions rather than presenting a request as an executed choice.

## Section 3: Run Signals

The candidate summary counts safety-only, progress-only and mixed-lane decisions, candidate
singletons, forced safety/progress, and decisions with at least two distinct executable actions.
These describe available choices, not an independent safety score.

| Signal | Evidence shown |
| --- | --- |
| **Progress delay** | First signal when present, starting with `x golds ·`, then longest no-gold/wait intervals and delay from gold completion to terminal state. |
| **Safety constraints** | Safety-rejection occurrences and repeated candidate-kind/action restrictions. |
| **Confirmed loops** | Active loop steps, contiguous episodes and longest duration. |
| **Stationary stalls** | At least five game seconds of unchanged runner position and offsets, with singleton, forced-safety, emergency-hold or common-rejection evidence. |
| **Model divergence** | Requested departures from top-scored distinct actions, score gaps and lane changes, using the `✨` predicate. |
| **Validation results** | Fallbacks and replaced requests, without treating them as executed model choices. |

Each signal has a representative step or range and a button that jumps to its starting step.
**Copy** includes `RUN CONTEXT`, `Candidates` and `EVENTS`: full trace ID, outcome, steps, timing,
observations and step references. Confirm causes against candidates, guards, terrain and subsequent
states before proposing a gameplay change.

## Retention and missing links

`recordings.json` owns pins. Recordings retain all pinned runs plus the newest ten unpinned runs;
traces retain pinned-linked runs plus the newest ten others. A pin protects existing evidence but
does not recreate a missing trace. See the [backend contract](backend-spec.md#trace-api-and-store).

A recording with a missing trace stays visible without inspectable steps. Trace-only runs are not
selectable because the overview starts from recordings. Manual recordings have no trace data.
Store rotation does not establish whether an archive exists: use full IDs and recorded archive
paths in the [cohort workflow](trace-cohort.md) to locate retained evidence.

## Changes and validation

Preserve selection, manual rows, pins, missing links, reload/cache and copy/jump controls when
changing a view. Check repeated safety rejections, unique suppression rows, fallback and
equivalent-action cases, empty traces and missing terminal states. Do not infer observations or
persist derived view fields. The dashboard has no map panel.

Run `npm test`, Python compilation and `git diff --check`; verify the affected view with Streamlit's
testing tools. Frontend builds apply when browser-wrapper code changes. Raw prompt/model I/O
belongs in opt-in `agent-debug.log`, not traces; see
[backend logging](backend-spec.md#logging-and-debug-io).
