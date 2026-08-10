# Trace Dashboard

## Purpose

`dash.py` and `loader.py` provide a read-only Streamlit and pandas debugger for retained
recordings and agent traces. They are isolated from the legacy runtime, Vite wrapper, Flask
backend, and solver. The dashboard reads the flat JSON stores without modifying them.

Run it from the repository root:

```sh
streamlit run dash.py --server.port 5100
```

The data folder defaults to `__data1`. Set `AGENT_DATA_DIR` or use the sidebar field to read
another folder containing `recordings.json` and `agent-traces.json`. Relative paths resolve
from the repository root. Streamlit caches each loaded folder until **Reload data** is pressed.

## Data Model

`loader.py` builds three pandas views:

- `runs_df`: recording rows joined to trace metadata by `traceId`;
- `steps_df`: flattened trace steps with action, validation, loop, state, outcome, and candidate data;
- the candidate dataframe returned by `get_candidates_df()`: one row per eligible candidate.

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

Inside an expanded step:

- **Validation** appears only when the requested and executed candidates differ or a fallback ran;
- **Suppressed** lists only non-empty loop-suppression results;
- **Outcome** compares pre-action state with the derived after-state for position, gold, risk,
  game-state changes, and terminal result;

Candidate IDs retain the candidate kind as their prefix, so the per-step table omits the redundant
`kind` column. Structured targets remain in the raw trace but are omitted from this compact view.

## Section 3: Candidate Score Breakdown

For the selected trace, the candidate breakdown groups eligible candidates by kind and shows:

- total appearances;
- number selected;
- average score;
- selection percentage (`win_rate_%`).

## Retention And Missing Links

`recordings.json` is the pin authority. It retains every pinned recording plus the newest 10
unpinned recordings. `agent-traces.json` retains traces linked by pinned recordings plus the
newest 10 other traces, without storing pin fields itself. A recording whose linked trace is
already missing remains visible in Section 1 but does not recreate that trace and has no
inspectable steps. Trace-only runs are not selectable while the run overview is
recording-driven. Manual recordings have no linked trace and therefore no Section 2 or Section
3 data.
