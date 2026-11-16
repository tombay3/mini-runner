# Gameplay analytics

Run these tools from the repository root with the project Python environment active. Use `npm run notebook` to start Jupyter, then [open Jupyter](http://localhost:8081/) and choose a notebook. Use `npm run dash` to [open the dashboard](http://localhost:8601/).

| Question | Open | Evidence |
|---|---|---|
| Which selector wins, and how quickly? | [Model comparison](compare-model.ipynb) | Table 1 groups eligible SQLite games by profile and submitted model ID. Table 2 shows individual games with live traces. |
| What did the measured tokens cost at the configured rates? | [Cost comparison](compare-cost.ipynb) | Tables 1 and 2 use the same eligible SQLite games for spend and tariffs. Table 3 shows estimated cost per game with a live trace. |
| Which actions did the backend offer? | [Trace analytics](trace-analytics.ipynb) | Table 1 counts steps by lane availability. Table 2 classifies singletons. Table 3 summarizes each live trace, including recorded steps from partial games. |
| What happened at a particular step? | [Trace dashboard](trace-dashboard.py) | Select a recording, follow a signal to its step and inspect the offered candidates and subsequent state. |
| Has this behavior been reviewed or archived? | [Cohort guide](cohorts.md) | Look up the full run ID for findings, provenance, comparisons and replay evidence. |

## Reading the comparison tables

SQLite keeps measurements when a trace ages out of the live store. The shared query includes saved gameplay wins and recognized losses with at least one model call, all successful. God-mode tests skip SQLite ingestion. Missing gold or timing affects the corresponding metric. Set `AGENT_METRICS_PATH` to select a different database. [Schema and eligibility rules](../docs/backend-spec.md#local-model-metrics)

- **Model.** The label combines the project profile and submitted model ID. It distinguishes the two Luna API routes.
- **Decisions and calls.** Every planning attempt counts as a decision. A forced singleton contributes zero model calls.
- **Time.** Minutes/game measures wall time. Request latency averages the per-game median, giving each game equal weight.
- **Divergence.** A scored request diverges when its candidate scores below the maximum and its key or tick count differs from every top-scoring action. Divergences/game divides counted divergences by games. Divergence rate divides them by scored calls. An unavailable requested ID has no comparable score.
- **Cost.** The notebook applies its input and output rates to measured tokens. Effective USD per million tokens uses total estimated spend divided by total tokens, scaled by one million. Missing rates or usage make the full estimate unknown.

## Inspecting a trace

The dashboard joins recordings to traces by full ID. Use the default `__data1`, set `AGENT_DATA_DIR`, or choose a folder in the sidebar. Relative folder paths resolve from the repository root. **Reload data** refreshes both stores.

| View | How to read it |
|---|---|
| Run Overview | Select a recording by save time. Gold measures initial minus final remaining gold. Game time uses 16 ticks per second. The clock column measures elapsed trace time. Pins mark recordings protected from rotation. |
| Trace Inspector | Each step shows the state before the action, its candidates, the model request, the backend selection and the issued key/ticks. Use the next step or terminal snapshot to see what happened afterward. Missing terminal evidence stays unknown. |
| Run Signals | Jump to progress delays, safety constraints, confirmed loops, stationary stalls of at least five game seconds, divergences or validation interventions. Copy the run context and step range for investigation. |

The ✨ marker uses the divergence rule above. ⚠️ counts a step once for a replaced request, fallback or loop suppression. 🔁 marks a confirmed active loop. Only exposed candidates count toward lane availability. The inspector shows one loop-suppression row per candidate ID and preserves repeated safety-rejection events. Mixed lanes require each lane to offer a key/tick action absent from the other.

## Retention and missing links

A recording without a linked trace still appears in the overview. A trace without a recording can contribute steps to trace analytics but has no selectable dashboard row. Pins protect existing evidence. For an older run, follow the catalog's archive links. [Trace store contract](../docs/backend-spec.md#trace-api-and-store) · [Archive lookup](cohorts.md#find-historical-replay-data)

The trace serializer, prompt formatter and evaluator share candidate and action conventions. When changing stored evidence, verify the affected notebook and dashboard against actual traces and use matched replay or evaluation for gameplay claims. [Candidate design](../docs/candidate-design.md) · [Evaluator reports](../docs/evaluator.md) · [Validation](../docs/sanity-tests.md)
