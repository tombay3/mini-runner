# Model comparison roadmap

This document records the staged model upgrade and its acceptance decisions. For current measurements use the [SQLite contract](backend-spec.md#local-model-metrics) and [analytics guide](../analytics/README.md).


**Stages A–E approved for offline implementation, November 5, 2026.** Compare how selectors play Classic 1:1,
how long they take, and what their calls cost. Hold candidate generation, scoring,
shortlist size, timing, safety checks, and loop handling fixed. The
[task specification](model-upgrade-tasks.md) owns implementation contracts and acceptance checks.

## Starting point and scope

On this Mac, `lego-dev` at `d675b12` uses Responses for the named OpenAI profile
and aisuite for the other provider paths. Browser request timing goes to the console.
The existing JSON recordings, V4 traces, and cohort catalog supply gameplay evidence.
New SQLite records will supply usage, cost, timing, and measurement coverage.

Use OpenAI and Gemini as the direct providers. Move the named OpenAI profile to
Chat Completions and keep the short gameplay rationale. Retire the Responses-only
debug summary. Per the November 5 scope decision, retire direct MiniMax and leave
MiniMax access for a later explicit OpenRouter configuration. Never automatically
redirect a direct provider setting to a gateway account.

## Roadmap for approval

| Stage | Deliverable | Review evidence |
| --- | --- | --- |
| A. Direct selectors | Freeze current behavior, separate selection from transport, and migrate OpenAI and Gemini to one chat adapter. | Matched fixtures verify prompt, shortlist, selection, fallback, and issued action. A frozen hybrid smoke run works with the new client. |
| B. End-to-end measurement | Connect the model request, backend decision, browser observation, and campaign in SQLite. | A model-free run can be followed from request to final state. Interrupted and missing observations stay visible. Hybrid data is isolated. |
| C. Comparison report | Use one calculation for evaluator JSON and notebook results. | Hand-calculated fixtures verify costs, latency, outcomes, and missing-data counts. |
| D. Additional selectors | Add OpenAI Decisions first, then OpenRouter using the chat adapter from A. | The same candidate IDs and ordering reach each selector. Fixtures verify typed refusals, routing, usage, and charges. |
| E. Offline acceptance | Run the integrated checks and prepare a bounded live-test proposal. | Show which paths passed offline, which need live evidence, exact endpoints, maximum calls, and spend. |
| F. Live verification | After separate approval, exercise only the approved paths. | Report actual model/provider identity, valid actions, measured usage, and remaining gaps. |

## Why this sequence

- **One direct chat path first.** Measuring Responses before retiring it could produce
  a before/after protocol baseline, but would require instrumenting two transports and
  collecting fresh comparable calls. Use migrated chat as the first measured baseline.
  Historical traces still support gameplay investigations. Historical costs remain unknown.
- **One working measurement path before broader reporting.** Start with one fake request
  through final observation, then cover manual runs, evaluator campaigns, and hybrid
  continuations. A schema-only milestone cannot reveal a lost final observation.
- **Two kinds of comparison.** Fixed decision inputs isolate differences in offered and
  chosen actions. Autonomous runs show downstream play after trajectories diverge.
  Use the small live check for integration. Any later quality campaign needs matched
  controls, a declared sample and stopping rule, and its own approval.
- **One adapter per protocol.** OpenRouter reuses Chat Completions with explicit routing.
  Decisions gets its own typed adapter. Recheck SDK support before scheduling that work.
  Defer TypeSafe/Jev, automatic routing, product spending limits, dashboard changes,
  reporting APIs, billing reconciliation, and historical metrics import.

## Approval boundary

Approval of A–E authorizes offline work with mocked providers and temporary stores.
F needs a separate decision on accounts, data sent, models, maximum calls and spend.
Credentials are needed only for the live stage. Keep commits, pushes, promotion, and
larger paid campaigns subject to separate approval. Earlier campaign budgets do not transfer.

## Implementation checkpoint

Stages A–D are implemented in the worktree. SDK 3.46.0 is installed in the project
virtualenv. Stage D continues because the latest published SDK exposes Decisions.
OpenAI and Gemini use shared chat, Decisions uses typed Choice, and OpenRouter
uses explicit provider routing. Direct MiniMax is retired.

Stage E checks include real SDK serialization against mocked HTTP responses, smoke
and regression suites, frontend build, Python compilation, notebook execution with
outputs saved outside the repository, and frozen baseline/current hybrid replay.
Cancellation during an in-flight mocked request and late observation delivery are
covered by additional local checks. No live inference call has been made.

Rate estimates currently cover standard direct GPT-5 nano chat, direct Gemini Flash-Lite chat and short standard
Decisions requests with known cache counts and no cache writes. Other rates remain
unknown. OpenRouter-reported charges are retained when returned. The price snapshot
records its rates and date. Metrics and JSON playback evidence have separate lifecycles.

## Stage F campaign — up to 20 full live runs

The user authorized up to 20 full paid runs on November 5 and requested an iterative
campaign with a Luna monitor. This replaces the earlier two-call integration draft.
The run allowance is cumulative across the campaign and any follow-up batches.
A run can contain up to 300 model calls. The full allowance can therefore contain
up to 6,000 calls. There is no separately approved dollar cap yet. Record spending
and missing-price coverage throughout. Do not interpret a prior $1 proposal as approved.

### Proposed model panel

| Arm | Profile and API | Model | Readiness |
| --- | --- | --- | --- |
| Baseline | openai / Chat Completions | gpt-5-nano | Credentials configured; live access remains to be checked. |
| Typed selector | openai-decisions / Decisions | gpt-6-luna | SDK 3.46.0 supports the endpoint; credentials configured. |
| Second provider | gemini / compatible Chat Completions | Currently gemini-flash-lite-latest | Credentials configured. Confirm this alias or choose a concrete model before paid execution. Record the returned model. |

OpenRouter and MiniMax are deferred for this campaign because the gateway credentials,
model and serving endpoint are unconfigured. They can use reserve slots only after the
user supplies those choices and approves the revised panel. Keep the total at 20.

### Allocation and iteration

| Round | Full run slots | Purpose and next decision |
| --- | --- | --- |
| Admission | 1 per arm, 3 total | Check real model access, candidate selection, terminal recording, trace correlation, pinning, usage, and metrics coverage. A failure uses its slot. Pause on provider errors or measurement/integrity gaps before repeating that path. |
| Balanced comparison | 4 more per admitted arm, 12 total | Reach 5 attempts per arm. Alternate arms in a fixed round-robin order. Review admission before proceeding. |
| Reserve | Up to 5 total | Resolve a specific integration failure or gather a declared matched follow-up. State the question and allocation before starting. Keep these results separate if source, controls or model panel change. |

Starting each attempt reserves one slot in a persisted ledger, even if it fails before
inference. A started attempt is never replaced or refunded automatically. Disable the
evaluator's page-reload retry for this campaign. Stop at 20 started attempts across all
batches. Stop on readiness/integrity failure and record partial attempts separately.
Do not spend reserve slots simply because they remain available.

### Fixed controls and evidence

- Use Classic 1:1 in normal mode, from the initial state, with the existing 120-second
  game-time limit, 300-decision cap, 24-entry browser history, 7 candidates and 20-tick
  maximum action. A full run ends on completion, death or its configured limit.
- Freeze source including new untracked modules, dependency versions, public config,
  prompt rules and per-arm effective settings before the first paid attempt. Capture
  code hashes and worktree provenance in the launch manifest. Run an owned backend
  without source reloading and verify its source identity. Hold the comparison source
  fixed across admitted arms. Fixes start a separately identified batch.
- Send compact gameplay state/history, supplied candidates and gameplay guidance to
  the selected account. Keep credentials local. Keep raw model I/O out of traces.
- Pin every persisted evaluation recording. Reconcile the catalog, add only complete
  matching pairs, and record failures before a complete pair in the campaign ledger.
  Archive selected supporting cases only when a future investigation needs them.
- Track completion, deaths/limits, gold, decisions and game ticks, plus provider/backend/
  browser timing, usage, charges or supported estimates, missing coverage, fallbacks,
  refusals, loops and candidate availability. Report every started slot.
- Compare complete gameplay attempts with explicit counts of infrastructure failures
  and interrupted runs. Five runs per arm give exploratory evidence. Models and API
  protocols differ together, so an outcome gap cannot be attributed solely to the API.

### Ownership and pause points

The main agent launches attempts, reviews evidence, diagnoses failures and maintains
provenance/catalog entries. One gpt-6-luna subagent at low reasoning reads campaign
files for routine monitoring and sends compact status changes. It has no provider,
write or process-control responsibility. Check active progress about every five minutes
and act promptly on a failure. Keep the monitor idle while waiting for user input.

Pause after admission for review, on a required model/account decision, on integrity or
coverage failures, and before reserve allocation. The user may pause at any time.
Resuming approves the concrete next step presented at that pause within the remaining
20-run allowance. It does not authorize new accounts, extra runs, commits or pushes.

Current state: goal created, Luna monitor assigned, zero paid run slots used. Awaiting
panel confirmation/resume before admission. A detailed dollar estimate depends on
actual prompt sizes, output lengths, cache usage and the selected Gemini model.

### Admission outcome and next review gate

Four slots are used. Nano died after 118 actions on the original batch. Decisions
then encountered the Choice minimum-option constraint. The approved singleton
correction passed offline replay and profile regressions. Its live Decisions run
succeeded in 184 actions with 110 provider calls. Gemini collected all gold but died
after 224 actions with 129 calls. Both corrected runs have complete action observations.

See `__data3/stage-f-admission-20261105/admission-review.md` and the linked campaign
reports. Cost coverage is partial for Decisions cache writes and missing for Gemini.
A proposed thirteen-run round would give five same-source attempts per model using
five nano, four Decisions and four Gemini attempts. Campaign usage would become
seventeen of twenty. Await explicit resume at this review gate.

### Comparison round approval

The user explicitly approved the thirteen-run round and clarified that future goal
resumption is explicit approval of the presented next step. Source hashes remain
the singleton-fix hashes. Slot 5 hit a local Node entry-point symlink mismatch before
browser or provider dispatch. It is retained as an infrastructure slot with zero
provider requests. The launch path was resolved and the remaining twelve originally
scheduled attempts were assigned slots 6–17. The later user-directed review gate
supersedes that schedule; no further attempts are queued.

### User-directed singleton comparison

The user requested three full fixed-arm nano runs and review immediately afterward.
Slots 8, 11 and replacement slot 15 are complete and pinned: one success and two
deaths, with 6/6, 6/6 and 5/6 gold respectively. Their 629 observed actions used
363 model calls and 266 direct singleton actions, with no provider failures.
Slot 14 was interrupted when stopping the controller also caused the execution
supervisor to terminate its evaluator child. It has no recording and remains
infrastructure evidence, with 74 model requests and one unobserved issued action.
Its final engine state is unknown; it is excluded from gameplay comparisons.

The offline comparison recovered 747 exact decision snapshots and bounded histories
from the retained control and three fixed nano recordings. Before/after candidate
pools and issued actions were identical for the same supplied recorded selections,
including 318 singleton states. The fix avoided 318 simulated model calls and
changed zero issued keys or durations. This establishes local action equivalence
on those inputs. Independent live model choices can vary; one control and three
fixed runs cannot establish a causal gameplay improvement.

All thirteen saved campaign pairs passed engine replay at 2,270 decision boundaries
and their endpoints. Catalog and data checks pass. The review report is
`__data3/stage-f-admission-20261105/nano-singleton-review.md`; detailed equivalence
results are in `singleton-equivalence.json` alongside it.

Fifteen ledger slots were used. Corrected-source results were nano 1/3, Decisions
4/4 and Gemini 1/4. The user cleared the goal before any further paid runs.

### Proposed next batch — Luna across two APIs

Hold the provider (OpenAI) and requested model (`gpt-6-luna`) constant. Compare
`openai:gpt-6-luna` (Chat Completions profile) with
`openai-decisions:gpt-6-luna` (Decisions profile). Set `OPENAI_MODEL=gpt-6-luna`
for the Chat arm. Check both adapters offline, including effective request settings,
before freezing the source, Classic 1:1 controls, candidate order and singleton rule.

Propose four new full games in Chat, Decisions, Decisions, Chat order. Keep the
fifth slot in reserve. Check the first Chat request for endpoint compatibility and
record returned model identity. An infrastructure failure uses its slot and triggers
review. Report new runs separately from the four historical Decisions wins.

Compare wins, gold, first differing issued action, distinct-action divergences,
validation fallbacks, request latency and cost with cache coverage. Compare choices
on the common trajectory up to the first differing action. Later steps can present
different game states. This measures the two configured API paths, including their
different response contracts. The batch awaits a new launch instruction.

### Luna API batch completed

The user authorized execution after refreshing repository context. Slots 16–19
completed under frozen revision e6042d5 in Chat, Decisions, Decisions, Chat order.
Both APIs won 2/2 with zero validation fallbacks. Chat averaged 8m55s per game;
Decisions averaged 4m33s. All four saved pairs are pinned and cataloged, and replay
verified 769 decision boundaries and four endpoints. Shared metrics pricing remains
incomplete for Luna Chat and Decisions cache writes. Nineteen cumulative slots are
used; one remains unused. No further runs are queued.

The first different action appeared at step 66/tick 279 for slots 16/17 and step
80/tick 363 for slots 19/18. States and candidate pools matched at those points.
The analysis stays in the batch report rather than notebooks. See
`__data3/stage-f-admission-20261105/luna-api-20261112/review.md` and its launch manifest
for setup, limitations, usage and validation.

### Debug failure traces

Replayed all **seven pinned failures** offline. All **1,398 decision boundaries** and all seven terminal states matched the recordings.

| Trace | What the replay established |
|---|---|
| `1d432bb9` | Seven emergency holds followed a trap wait at the left edge. At the final step, a guard blocked right and the edge safety rule rejected left. |
| `645d66cb` | **The clearest avoidable immediate death.** At step 177, the selected left move died at tick 884. The offered right move reached tick 885 alive, then died at tick 908 under neutral input. The backend already ranked right higher, 101 to 100. This supports a better choice at that step, but does not establish a winning continuation or justify a scoring change. |
| `8cc142af` | A dig-completion wait led to three emergency holds. The final pool contained only hold. Archived `7b4a2fad` also ended in a row-12 hold, at a different position. |
| `af65e3c3` | A second closing guard blocked leftward retreat during the final hold sequence. Archived `78ce39a1` ended with the same runner pose and hold ID. Only the final step matched consecutively. |
| `af86c997` | The ladder reversal at steps 238–240 was a confirmed historical bug. Current code recognizes a climb that crosses the entry row, and its regression tests pass. The later death followed 14 emergency holds. |
| `babed39e` | A second closing guard blocked rightward retreat, mirroring `af65e3c3`. Neither trace established a safe escape by relaxing that rule. |
| `df562c4e` | The last three candidate IDs all issued **right for four ticks**. Changing the final selection could not change the action. The earlier exit/retreat oscillation remains deferred with the compound-loop work. |

I saved the findings and archive correlations for all seven traces in the [cohort catalog](/Users/tomchin/3po/ducky/run-8283/__data1/trace-cohorts.json). Smoke tests, regressions, compilation, and archive verification passed. The goal is complete. All replays were offline, with zero paid gameplay calls.
