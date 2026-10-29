# Pending: model service, SQLite metrics, and model comparisons

Status: planned, not implemented. Reviewed 2026-11-04 against `lego-dev` at `77fa974`.

Execution details and delegable work packages: [Technical task specification](model-upgrade-tasks.md).

## Objective and decisions

Compare model selection quality, cost, and latency using the same candidate flow.
Add OpenAI Decisions first, OpenRouter for general chat models second, and
TypeSafe/Jev later. New chat models should normally require configuration, not another adapter.

- Measure tokens and spending; do not add token budgets or dollar limits.
- Collect accounting and gameplay metrics for all new agent runs, including manual
  browser runs and evaluator campaigns. Isolated hybrid experiments use their own database.
- Start fresh without importing historical runs. Retain metrics until explicitly deleted.
- Use shared Python queries, campaign reports, and notebook analytics. Reporting APIs
  and dashboard changes are deferred.
- Continue gameplay on database failure, while marking measurement coverage incomplete.
- Preserve existing OpenAI, MiniMax, and Gemini access during migration.
- Keep candidate generation, scores, shortlist limits, safety checks, action timing,
  and loop handling fixed while comparing selectors.
- Paid calls, commits, pushes, and promotion require separate approval. Preserve
  manual edits and user-owned staged changes.
- Implement on this Mac's `lego-dev`, with one main agent and sequential, bounded
  cheaper subagents. Include a small paid integration check only after its budget
  and model list are approved. Earlier cleanup-campaign approval does not cover this work.

## Refreshed baseline and roadmap

On review, the checkout was clean. Local `lego-dev`, `main`, and their stored remote
references pointed to `77fa974`; no remote fetch was performed. `pooh-dev` pointed
to `5111e40` and has source differences, so it is not an interchangeable baseline.
Both `npm test` and `npm run test:regression` passed without model calls.

The service still uses aisuite except for native OpenAI Responses. SQLite accounting
is not implemented. Browser request timing currently goes only to console logs;
Flask store paths are fixed and hybrid experiments redirect them explicitly.
Collection must therefore include browser observations and an explicit metrics path.

Delivery order (the numbered sections below describe subsystems, not dependencies):

1. Main agent locks shared contracts and freezes the current behavior baseline.
2. Split the service while retaining its transports.
3. Add SQLite metrics, lifecycle collection, queries, and reports on existing Responses.
4. Add OpenAI Decisions using the existing OpenAI SDK after checking its support.
5. Add shared Chat Completions/OpenRouter support, then remove aisuite after parity checks.
6. Review offline results and request approval for a small paid integration check.
7. Consider TypeSafe/Jev as a later increment; account/endpoint choice remains deferred.

Before implementation, prepare local provider credentials without posting them in chat.
OpenAI access is needed first, then an OpenRouter account and explicit model/endpoint
choices. Live access and prices must be checked before the paid approval request.
No database installation is needed; the plan uses Python's standard SQLite library.

## Architecture and implementation order

### 1. Split the service

Keep request validation and orchestration in `agent/service.py`. Move candidate
generation, selection validation, fallback, and action/trace assembly into
`agent/selection.py`. Put provider calls, response parsing, usage, timing, and
errors in `agent/llm_client.py`.

Keep `llm_client.py` as the shared dispatcher/result boundary. Group transport code
by protocol under `agent/llm_clients/`: `chat_completions.py`, `responses.py`, and
`decisions.py`. Add a System One module only in the later Jev increment. OpenRouter
is a gateway configuration with routing/cost extensions, not one module per model.
Responses and Chat Completions both supply token usage; normalize their different
fields. Preserve existing Responses reasoning summaries in debug output. Hosted tools,
server-side conversations, and multiple generated answers are outside this upgrade.

First validate this split without changing existing requests or behavior. Normalize
client results into candidate ID, optional rationale, requested/resolved model,
request ID, usage, timing, and completion status. Native responses stay inside
provider/debug code; raw model I/O remains excluded from traces.

### 2. Replace aisuite and add OpenRouter

Review the pinned aisuite fork before removing it. Use small adapters organized
by API protocol:

| Adapter | Purpose |
| --- | --- |
| Chat Completions | OpenRouter models and compatible direct endpoints |
| OpenAI Responses | Existing OpenAI selection and reasoning features |
| OpenAI Decisions | Typed candidate selection, added after accounting |
| TypeSafe System One | Jev through direct TypeSafe or OpenRouter |

After the OpenAI Decisions increment, use OpenRouter as the default route for new general chat models. Existing direct
MiniMax/Gemini profiles should use shared transport where compatible; do not silently
switch their billing account or endpoint. Verify compatibility before removing the
old paths. Credentials remain in environment files. Model, endpoint, and supported
settings are configuration; a model name alone does not select an API protocol.

For comparison campaigns, select an explicit model and serving endpoint, disable
provider/model fallbacks, and require support for supplied parameters. Record gateway,
API protocol, serving provider, requested/resolved model, and effective settings.
Unsupported settings must not be reported as applied. Use explicit timeouts and
disable client retries initially. Provider errors stop the attempt; malformed or
unknown choices retain the existing recorded fallback behavior.

### 3. Add SQLite collection, analysis, and reports

Use Python's standard SQLite library and an ignored `metrics.sqlite3` under the run's
configured data directory, defaulting to `__data1`. Isolated experiments use their own
directory. Keep recordings and full traces in their existing JSON stores.

Use short transactions, parameterized queries, WAL mode, a bounded busy timeout, and
per-operation connections. Version the schema and apply explicit migrations
transactionally; never reset an existing database automatically.

Store four related entities:

| Entity | Contents |
| --- | --- |
| Campaign | Launch identity, controls, recorded provenance, lifecycle, aggregate completeness |
| Run | Trace/recording ID, mode/context, origin, outcome, terminal tick, gold, decisions, wall time |
| Decision | Sequence/tick, selected candidate kind, candidate/filter counts, fallback, loop indicators, timing, observed progress |
| Model request | Decision link, requested/resolved model, gateway/API/provider, settings, request ID, usage, cost, timing, status |

Manual runs need no campaign. Use stable IDs and uniqueness constraints so repeated
finalization cannot duplicate requests or outcomes. Record request starts before
dispatch and completion afterward; preserve unresolved requests as incomplete.
Finalize run summaries on success, failure, cancellation, or evaluator interruption
when that event is observed. Capture compact metrics without raw prompts, responses,
complete snapshots, or duplicate recordings. Missing measurements remain null.

A database failure must not change the selected action or interrupt gameplay. Log it
and propagate an incomplete-metrics indicator through run results and campaign reports.
Show coverage and exclude incomplete measurements from claims requiring complete
accounting. Missing rows must not silently become zero usage.

Retain metrics independently of trace pruning. Provide explicit cleanup by run/campaign
ID; do not add an automatic retention job.

Accounting and timing:

- Retain reported input/output, cached-input, cache-write, and reasoning counts where
  available. Preserve provider definitions; do not double-count token subsets.
- Missing usage or price is unknown, not zero. Preserve failures with unknown charges.
- Compute estimated cost from a dated, sourced price table keyed by gateway/provider, API,
  model, and applicable rate categories. Snapshot rates with the accounting record.
- Store provider/gateway-reported charges separately. OpenRouter inference charges
  do not establish the full invoice cost, including account-level fees.
- Report weighted cost per token using total cost divided by corresponding total
  tokens. Separate input/output rates where attribution permits. Include measurement
  coverage, cost per decision/attempt, and campaign cost per success, including failures.
- Measure provider time, backend decision time, browser round-trip time, total run
  wall time, and engine ticks/game time. Report median/p95 latency; browser round-trip
  overhead is not a pure network measurement. Use monotonic elapsed measurements
  within each process and UTC timestamps for correlation.

Implement one shared Python query/report layer. Use SQL for filtering, joins, counts,
sums, and grouped aggregates, with a consistent Python calculation for percentiles.
Extend evaluator summaries and notebook comparisons with these metrics, outcome,
gold progress, decisions, candidate availability, fallbacks, and loops. Show sample
counts and measurement coverage. Filter by campaign, run, date, model, API, serving
provider, mode, and controls; distinguish comparisons with different configurations.
Historical missing measurements stay unknown. Billing reconciliation, reporting APIs,
and dashboard work remain deferred.

### 4. Add OpenAI Decisions

Add a separate `openai-decisions` profile using one Choice question over exposed
candidate IDs. Reuse state/history context and gameplay guidance, omitting chat-only
JSON/rationale instructions. Keep the existing Responses profile available.

The current guide specifies `gpt-6-luna`; verify supported models and SDK availability
when implementing. Comparing it with existing nano Responses changes both model and
API, so reports must not attribute differences solely to the endpoint. Handle typed
refusals explicitly as failed selections; record them before applying the existing
selection fallback. Capture usage and endpoint-specific pricing.

### 5. Add Jev later

Add a `jev` profile using one System One Choice question over the same candidates.
Support direct TypeSafe or OpenRouter through endpoint/credential configuration.
Read typed choices directly rather than manufacturing chat-completion text.
The first implementation defers this adapter. Confirm the account/endpoint and
live-validation scope when starting the later increment.

For both typed APIs, retain probabilities/confidence as diagnostics and leave generated
rationale empty. Do not assume confidence is comparable across providers or predicts
survival. Confidence thresholds, automatic escalation, and dynamic routing are deferred.

## Validation and comparison

Use small mocked checks for transport normalization, unchanged selection behavior,
option mapping, invalid choices/refusals, timeouts, effective settings, missing usage,
token subsets, price snapshots, weighted aggregates, null coverage, duplicate finalization,
concurrent writes, interruptions, database failures, and isolation between experiments.
Verify manual and evaluator runs populate the same metric definitions without changing
JSON retention. Run repository sanity tests, Python compilation, notebook execution
without saving outputs, and `git diff --check`; build the frontend if instrumentation changes.

Each roadmap stage is independently reviewable. No paid requests are part of offline
validation. Prepare a small live integration check and ask for its call/dollar budget
before execution; full campaigns need a separate approval. After approval, compare runs
on fixed source and controls. Compare completion, gold, decisions, ticks, latency, cost,
fallbacks, and loops. Faster inference reduces waiting in the current stepped engine;
it does not itself establish improved survival. Provider latency claims are not local results.

## Coding-agent efficiency

Add short workflow guidance: economical models for scoped mechanical work; stronger
reasoning for architecture and difficult diagnosis; compact handoffs with revision,
scope, checks, and stop conditions; scripted campaigns and summaries; five-minute
monitoring with failure detection in the runner. Reuse offline evidence before paid runs.
Coding-agent consumption stays separate from gameplay API cost. No coding-agent runner
or usage-import tooling is included.

## Verified references

Recheck capabilities, model availability, and pricing when implementation begins.

- [OpenRouter quickstart](https://openrouter.ai/docs/quickstart): shared API for chat models.
- [Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection): endpoint selection, fallbacks, and required parameters.
- [Usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting): reported tokens, cache usage, and request charges.
- [TypeSafe SDK through OpenRouter](https://openrouter.ai/docs/guides/community/typesafe-sdk): System One compatibility and additional cost/provider metadata.
- [OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions): typed choices, supported model, usage, and endpoint pricing.
- [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice): typed candidate choices and probability diagnostics.
