# Trace Dashboard

## Purpose

`trace-dash.py` provides a read-only Streamlit dashboard for recordings and agent traces. It reads the flat JSON stores without modifying the game, backend, or stores.

Run it from the repository root:

```sh
npm run dash
```

The data folder defaults to `__data1`. Set `AGENT_DATA_DIR` or use the sidebar field to read
another folder containing `recordings.json` and `agent-traces.json`. Relative paths resolve
from the repository root. Streamlit caches each loaded folder until **Reload data** is pressed.

## Data Model

`trace-dash.py` builds two pandas views used by the dashboard:

- `runs_df`: recording rows joined to trace metadata by `traceId`;
- `steps_df`: flattened trace steps with action, validation, loop, state, outcome, and candidate data.

Demo time is converted from legacy ticks at 16 ticks per second. Record time is the trace's
`updatedAt - createdAt` wall-clock duration. For a non-final action, the dashboard derives
after-state from the next trace step; the final action uses `outcome.finalState`. This avoids
duplicating derived after-state data in the trace store.

## Sidebar

The sidebar contains the data-folder path, manual reload button, loaded recording count, store
update time, and JSON loading warnings. If neither store produces data, the page stops after
showing the expected file names.

## Section 1: Run Overview

The run table is sorted by `savedAt`, newest first. Selecting one row sets the trace inspected
by Sections 2 and 3; the newest row is the default. Manual recordings display `user` instead
of an empty trace ID.

Columns are:

- `traceId`: first eight characters of an agent trace ID, or `user`, with `📌` appended when
  its recording is pinned;
- `savedAt`: local timestamp in `MM-DD HH:MM` format;
- `result`, `time`, `steps`, and failure `reason`;
- `★`: whether the recorded demo used god mode;
- `🎯`: average number of candidates per trace step;
- `✨`: number of steps where the LLM requested a candidate below the highest available score;
- `⚠️`: number of steps with candidate replacement or loop suppression;
- `🔁`: number of steps with an active confirmed loop;
- `record`: trace wall-clock duration;
- `model`: resolved model identifier.

## Section 2: Trace Inspector

The inspector presents every step in a fixed-height scrollable panel. Each expander title shows
the pre-action step number, legacy action and ticks, runner position, remaining gold, guard risk,
selected candidate ID, and cumulative demo clock at the start of the step.

Step-title markers are:

- `🔁`: `loopMonitor.active` is true;
- `⚠️`: validation replaced the requested candidate or loop filtering suppressed a candidate;
- `✨`: the requested candidate's score was below the highest eligible candidate score.

Inside an expanded step, the ASCII map shows recorded runner, target, waypoint, guard, visible-gold,
and route geometry. The adjacent candidate table includes eligible choices, loop-suppressed
candidates, and safety-rejected candidates. Requested, executed, fallback, lower-score, and
loop-suppression markers remain inline with the relevant candidate reason.

Candidate IDs retain the candidate kind as their prefix, so the per-step table omits the redundant
`kind` column. Structured targets remain in the raw trace but are omitted from this compact view.

## Section 3: Run Signals

Run Signals summarizes safety/progress lane availability, singleton types, and non-singleton steps
where the model received at least two distinct executable actions.

The diagnostic text copied by the section's `Copy` action is organized as `RUN CONTEXT`, `Candidates`, and `EVENTS` so it can be pasted into
a debugging conversation without occupying dashboard space.

Signals cover safety constraints, confirmed loops, delayed progress, model/heuristic divergence,
validation results, and sustained stationary stalls. A stationary stall requires
at least five seconds of unchanged runner position and offsets; its evidence may include an
emergency hold, forced safety, or an action singleton. Each populated row
identifies a representative step or range and can navigate to its starting step in the Trace Inspector.


## Retention And Missing Links

`recordings.json` is the pin authority; `agent-traces.json` does not store pin fields. Both retain
pinned runs plus the newest unpinned runs. See [Trace API and store](./backend-spec.md#trace-api-and-store)
for the exact retention rule.

A recording with a missing trace remains visible but has no inspectable steps. Trace-only runs are
not selectable because the overview starts from recordings. Manual recordings have no trace data.
