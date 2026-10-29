# Model upgrade: technical task specification

Status: pending implementation. Reviewed 2026-11-04 against `lego-dev` at `77fa974`.
Parent scope: [Model upgrade plan](model-upgrade-plan.md).

## Execution decisions and preparation

- Execute on this Mac's `lego-dev` with one main agent and sequential cheaper subagents.
- Deliver existing Responses accounting first, then OpenAI Decisions, then OpenRouter.
  TypeSafe/Jev is a later increment; its account/endpoint is not yet selected.
- Include a small paid integration check after offline validation. Present exact models,
  call count, estimated charge, and a maximum authorized spend for approval before calling.
  This operational approval does not add budget enforcement to the application.
- Prepare OpenAI credentials locally, then OpenRouter credentials and a desired model/serving
  endpoint. Never put keys in task prompts or reports. Confirm account access before live tests.
- Do not reuse paid-run authorization from `docs/cleanup-batch.md` for this work.
- No SQLite server installation is needed. Outputs stay local and ignored. No historical import.
- The baseline smoke and regression suites passed during this review. Rerun if source changes.
  Local main and lego-dev matched; remote references were not fetched. Linux pooh-dev differs.

## Main-agent responsibilities

The main agent owns architecture, contracts, integration, scope decisions, and approval requests.
Review each subagent's diff and evidence before assigning the next task. Freeze contracts before
delegating consumers. A subagent may propose a contract change but must not silently make it.

Use Luna low for mechanical extraction, fixtures, and documentation; Luna medium for bounded
adapter, SQL, and collection tasks. These are starting settings, not a quality guarantee.
Escalate unresolved API ambiguity or repeated test failures to the main agent. Do not let a
subagent expand into planner changes. Use a fresh bounded task prompt rather than forwarding
the entire historical conversation. Do not spawn agents merely to wait for processes.

Each task returns changed files, tests/results, remaining limitations, and any contract issue.
Subagents do not commit, push, restart shared services, modify live stores, or make paid calls.
Only the main agent integrates shared files and presents independently reviewable commit boundaries.

## Contracts to freeze before implementation

### Client and selection boundary

Keep `plan_next_action` and request validation as the public backend entry points. Selection owns
candidate generation and action validation; transport modules have no gameplay policy.

`llm_client.py` dispatches by API protocol to `llm_clients/chat_completions.py`, `responses.py`,
or `decisions.py`. Model names, gateway, endpoint, credential references, and routing controls
belong to resolved configuration. Preserve existing profile/model resolution precedence.

Normalize candidate ID, optional declared rationale, parse/refusal status, requested/resolved
model, gateway, serving provider, API, request ID, effective settings, usage, and provider elapsed
time. Retain provider-native data only inside the adapter/debug path. Reasoning summaries remain
debug-only. Both generative APIs report usage; their field names differ. Do not add hosted tools,
conversation chaining, streaming, or multiple output choices in this scope.

The initial split preserves transport requests and error behavior. Later adapters use explicit
timeouts and zero automatic retries; document any difference from the old aisuite path. Typed
API refusal is recorded distinctly and passes through selection's existing fallback policy.
No fallback to a different model/provider. Preserve the distinction between protocol failure
and an invalid candidate selection. Unsupported parameters must never be marked effective.

### Metrics ownership and lifecycle

SQLite uses four primary tables: campaigns, runs, decisions, and model_requests. Campaign membership
is optional. A decision ID is allocated before dispatch and can exist without a saved trace step.
Track attempted decisions separately from issued actions and observed executed actions.

The backend owns model/request measurements and decision outcomes. The browser owns round-trip
duration and observed after-action progress. The evaluator owns campaign identity and launch
metadata. Repeated updates use stable identifiers and must be idempotent. Do not infer historical
source from HEAD or mistake a reused backend for freshly loaded source.

Carry the prior action's compact observation in the next action request, and the final observation
with recording finalization. Return a metrics decision ID with each action. These additive fields
are optional so older clients still operate; absence means partial coverage. Never use telemetry
to alter selection/history. Report missing last observations when the browser closes unexpectedly.

Campaign registration/finalization may use narrow write-only backend endpoints; these are ingestion,
not the deferred reporting API. Validate only bounded metadata and identifiers; accept no client
filesystem paths or SQL. Reports use local Python queries against the actual backend database.

Set an explicit backend metrics path, defaulting beside its recordings store. Hybrid launchers must
set this path before the first metrics operation. Test isolation explicitly: changing JSON store
paths alone must not leave metrics pointing at production. Do not change JSON retention semantics.

Use standard sqlite3, schema version 1, WAL, foreign keys, short transactions, parameterized SQL,
and a bounded lock wait. Queries open existing databases read-only and never create empty stores.
Keep schema setup separate from reads. Unknown newer schemas are reported without rewriting data.

Start requests before provider dispatch; finish them on success/error. Unfinished records remain
unresolved rather than being relabeled as free or successful. Do not guess death/cancellation from
elapsed time. A metrics failure must not prevent gameplay: propagate a sticky partial-coverage
flag through results, preserve logs, and do not invent a completed record if the database is down.
Reports check pending requests, expected/observed counts, and flags. Database failure may leave
coverage unknown even when a separate campaign report preserves the warning.

### Costs and aggregation

Keep token subsets and provider definitions explicit. Null means unknown, zero means measured zero.
Snapshot price source/date/currency/rates with estimates; do not retroactively reprice old requests.
Keep reported charges and estimates separate and never sum them as two expenses. Use exact decimal
arithmetic for cost calculations. Unsupported pricing rules yield an unknown estimate.

Shared SQL/Python queries compute counts, sums, weighted cost/token, and latency percentiles using
one documented percentile method. Include measured sample counts and missing-data counts. Never
divide a partial cost numerator by all tokens or silently treat missing charges as zero. Campaign
cost per success uses campaign spend including failures; zero successes yields undefined, not zero.
Reports distinguish gateway/API/model/provider/settings, game time, model time, and total wall time.
SQLite retains metrics until explicit cleanup; cleanup never deletes recordings or traces.

## Delegable work packages

Tasks run in order. Each row is one assignment; shared regression files have one writer at a time.
All tasks require the parent plan, frozen contracts, exact starting revision, and their listed scope.

| ID / effort | Owned work | Depends on | Acceptance evidence |
| --- | --- | --- | --- |
| T0 / main | Freeze interfaces, task boundaries, baseline configuration and source; confirm API support | User starts implementation | Reviewed contract and baseline smoke/regression results; no secrets in artifacts |
| T1 / low | Extract selection and client code from service; update imports and existing tests | T0 | Same mocked request, selected action, fallback, prompt, and trace projections; only volatile timestamps excluded |
| T2 / medium | Implement SQLite repository, schema initialization, CRUD lifecycle, explicit cleanup | T0, T1 | Temporary DB tests for duplicate updates, nulls, lock/concurrency, isolation, unknown schema, and incomplete requests |
| T3 / medium | Instrument backend request/decision/run lifecycle and failure coverage | T2 | Fake provider success/error persists truthful counts; simulated DB failure still returns the original action |
| T4 / medium | Collect browser round-trip/after-action/final observation metrics | T3 | Wrapper tests for normal finish, cancel, provider failure, missing finalization, duplicate observation; build passes |
| T5 / medium | Add campaign metadata ingestion; wire evaluator and hybrid metrics paths | T3, T4 | Mock/manual/evaluator identifiers correlate; hybrid test writes only its temporary DB; abrupt endings remain partial |
| T6 / medium | Implement price snapshots, normalized usage accounting, common SQL queries, JSON report output | T2–T5 | Hand-calculated fixtures cover token subsets, unequal request sizes, nulls, mixed prices, zero successes, and percentiles |
| T7 / low | Add notebook cost/latency comparison cells and concise documentation | T6 | Execute against synthetic SQL data without saving outputs; charts/tables label coverage and comparison controls |
| T8 / medium | Add native OpenAI Decisions adapter and profile | T1, T6 | Mock Choice/refusal/error responses normalize correctly; candidate IDs/order/context are preserved; usage reaches SQL |
| T9 / medium | Implement shared Chat Completions and OpenRouter configuration/routing/cost support | T8 | Mock direct and gateway responses; verify requested controls, returned provider, charges, and existing profile precedence |
| T10 / low | Remove aisuite after main-agent parity review; update dependencies and docs | T9 | No runtime/test import depends on aisuite; OpenAI/MiniMax/Gemini required paths pass mocked contract checks |
| T11 / low + main review | Run integrated offline acceptance and draft live-check proposal | T10 | Smoke/regressions, compile, build, notebook, and diff checks pass; no live DB writes or paid calls |
| T12 / main; routine execution delegable | Run explicitly approved live integration check | T11 + new paid approval | Calls stay within approved scope; real IDs, usage, cost availability, actions, and lifecycle correlate; no extra attempts |
| Later / medium | Add Jev System One adapter | Separate start decision | Confirm account/endpoint first; reuse common client and metrics contracts |

Use the two established regression scripts rather than new per-area test runners. Keep default
smoke checks small. T8/T9 may require focused package dependency updates owned by that task;
T10 removes aisuite only after the main agent confirms required provider parity.

## Subagent assignment template

> Implement task <ID> from docs/model-upgrade-tasks.md at revision <HEAD>.
> Read AGENTS.md and the parent plan. Your owned files are <explicit list>.
> Use the supplied frozen contracts and fixtures; preserve unrelated changes.
> Complete only this task and run <focused checks>. Use temporary stores and mock providers.
> Do not commit, push, call paid models, restart shared services, or edit outside your ownership.
> If a contract is insufficient, report the exact gap to the main agent before changing it.
> Return files changed, behavior preserved/changed, checks, and remaining limitations.

## Approval and completion gates

The main agent reviews all task outputs and reruns relevant integration checks at meaningful
boundaries. It requests commit approval after a concrete reviewed diff, and separate approval
before paid calls. Retain user ownership of staged edits. No production promotion is implied.

The first release is complete when existing profiles plus Decisions/OpenRouter work with offline
contracts, metrics correlate across manual/evaluator/hybrid origins, reports identify incomplete
coverage, and the separately approved live checks are reported. Broad success-rate campaigns,
Jev, automatic model routing, budget enforcement, billing reconciliation, and dashboard changes
remain outside that release.

References: [model/effort guidance](https://developers.openai.com/api/docs/guides/model-selection),
[Responses versus Chat Completions](https://developers.openai.com/api/docs/guides/migrate-to-responses),
[Decisions](https://developers.openai.com/api/docs/guides/decisions),
[Jev through OpenRouter](https://openrouter.ai/docs/guides/community/typesafe-sdk).
