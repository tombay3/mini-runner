# Model comparison implementation and acceptance

This document records the staged model upgrade and its acceptance decisions. For current measurements use the [SQLite contract](backend-spec.md#local-model-metrics) and [analytics guide](../analytics/README.md).


**Stages A–E approved for offline implementation.** The [roadmap](model-upgrade-plan.md) owns scope, stage order,
and approval boundaries. This file defines how to implement and verify each stage.

Work on this Mac’s `lego-dev`. Before editing, record current HEAD, local changes,
config, and versions of relevant dependencies. The November 5 offline suites passed
at `d675b12`. Keep user edits and staging intact. The main agent owns interfaces and
integration. Use sequential, bounded subagent assignments when implementing, with
one writer per shared file. Use one GPT-6.1 Terra subagent at medium reasoning at a time. Each handoff names the revision, files, checks, and stop condition.
Subagents return a diff and evidence. The main agent handles approvals and shared services.

## Contracts to freeze before implementation

### Client and selection boundary

Keep `plan_next_action` and request validation as the public backend entry points. Selection owns
candidate generation and action validation. The client owns API requests and response parsing.

`llm_client.py` uses Chat Completions for direct chat and OpenRouter, and the
Decisions API for typed candidate selection.
Defer System One until Jev. Keep gateway, model, endpoint, credentials, and routing
in resolved configuration. Preserve resolution precedence for retained paths, including explicit OpenAI IDs,
the OpenAI and Gemini profiles, and their configured credentials/base URLs. Inventory
explicit provider prefixes before deleting aisuite, whose registry currently accepts
more than the named profiles. Flag other observed dependencies for review. Reject
retired MiniMax settings with an actionable config/request error before dispatch.
Never echo credentials. Historical MiniMax traces remain readable and replayable;
a new model continuation requires a supported, explicitly chosen endpoint.

Normalize candidate ID, optional declared rationale, parse/refusal status, requested/resolved
model, gateway, serving provider, API, request ID, effective settings, usage, and provider elapsed
time. The chat migration preserves the declared JSON gameplay rationale and retires the
Responses-only debug summary. Omit a Responses adapter. Track missing usage fields as null.

First characterize the current client with mocks, then change transports in a separately
reviewable diff. Keep candidate generation in its existing modules. Extract only the
selection orchestration needed to separate gameplay policy from transport. Later adapters use explicit
timeouts and zero automatic retries; document any difference from the old aisuite path. Typed
API refusal is recorded distinctly and passes through selection's existing fallback policy.
No fallback to a different model/provider. Preserve the distinction between protocol failure
and an invalid candidate selection. Unsupported parameters must never be marked effective.

### Measurement and reporting

The upgrade introduced persistent measurements and offline comparisons. The backend records game outcomes and model calls. The evaluator keeps launch provenance and verifies run IDs. Hybrid trials use an isolated database. Notebook comparisons read SQLite and calculate cost from recorded usage and configured tariffs. See the linked contracts above for current fields, eligibility and units.

## Stage checks and ownership

Use the two existing regression scripts and small shared fixtures. Keep smoke coverage
small. Each stage below has one reviewable outcome. Former task IDs are included so
existing notes can still be located.

| Stage | Former tasks | Implementation and acceptance |
| --- | --- | --- |
| A. Direct selectors | T0–T3 | Characterize named OpenAI Responses, explicit OpenAI chat, Gemini’s OpenAI-compatible endpoint, and retired MiniMax behavior. Migrate to shared chat, verify precedence, endpoint, optional settings, parse errors and fallback, then remove aisuite after review. Update profile docs and the README’s baseline description. |
| B. End-to-end measurement | T4–T7 | Implement schema v1 and one complete model-free action first. Extend it to cancellation, failure before the first trace step, repeated or late observations, finalization, database lock/failure, and concurrent writes. Exercise manual, evaluator, and isolated hybrid origins. Verify explicit cleanup by run or campaign. |
| C. Comparison report | T8–T9 | Use the same read-only SQL/Python queries for JSON and notebook output. With synthetic data, verify unequal request sizes, token subsets, mixed rates, unknown charges, incomplete attempts, and zero successes. Show cost per request, decision, attempt and success, plus completion, gold, decisions, ticks, loops and fallbacks. Show totals with coverage and median/p95 with sample sizes. |
| D. Additional selectors | T10–T11 | Add a Decisions Choice over the exposed IDs, then configure OpenRouter on shared chat. Test each independently. Preserve candidate order and gameplay context, adapt only protocol-specific instructions, and distinguish refusal, malformed choice, and transport failure. |
| E. Offline acceptance | T12 | Run smoke, focused regressions, compilation, frontend build, model-free hybrid checks, notebook execution without saved outputs, and diff checks. Use temporary data. Draft the live proposal with per-path calls, model, serving endpoint, data sent, estimate, maximum spend, and stop conditions. |
| F. Live verification | T13 | Obtain fresh approval. Record each attempted call, including failures, without automatic retries. Report which direct and gateway paths were actually exercised, observed charges and coverage, and any unresolved compatibility issue. |

### Stage-specific decisions

**A — Hybrid reproducibility.** Update the smoke stub that patches
`AisuiteAgentClient.create_completion`. For new frozen arms, enumerate nested adapter
files from each arm’s own source, create parent directories, and hash the copied bytes.
Exercise both worktree and revision arms from their frozen copies. Record the dependency
set used by each arm. Historical control code importing aisuite needs a compatible
environment or an explicit preflight failure before any paid continuation. Keep old
manifests intact.

**B — Storage and evidence.** Keep the recording and trace stores as the authority
for playback and gameplay evidence. Allocate and persist a request start before
dispatch when storage is available. Never hold a SQLite transaction across a model
call. An abort after dispatch can leave the request billed and its action unobserved.
Keep these facts separate. Compare the campaign’s expected attempts with observed
runs so a completely missing metrics row still reduces coverage. Keep price snapshots,
campaign provenance, and compact metrics free of secrets or raw model I/O.

**C — Fair comparisons.** Group by source/config, mode, model, protocol, serving
provider and effective settings. Keep manual, full-run and forked-continuation
results separate. Count issued actions separately from observed progress. Report
fallbacks separately from valid model choices. Success rate uses completed and
failed gameplay attempts with explicit counts for interrupted or infrastructure-only
attempts. Compare cost per success only when spend coverage is complete. Different
models on different APIs support a combined comparison. Attributing a difference to
the API alone requires holding the model fixed.

**D — Provider-specific checks.** The implementation uses OpenAI SDK 3.46.0, which exposes
`client.decisions.create`. Real SDK request serialization and typed response parsing
are tested with mocked HTTP transports. Live account access remains a Stage F check.
Keep confidence/probabilities diagnostic and rationale empty on typed choices.
Pin OpenRouter’s serving endpoint, disable provider/model fallbacks, require support
for sent parameters, and record returned provider and cost only when supplied.
[Decisions guide](https://developers.openai.com/api/docs/guides/decisions) ·
[OpenRouter routing](https://openrouter.ai/docs/guides/routing/provider-selection) ·
[Usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)

**E–F — Live scope.** Supply credentials locally only when testing an approved account.
If a path lacks live access, report its offline coverage and leave live acceptance open.
A smoke run establishes connectivity and accounting. Measuring gameplay quality requires
a separate campaign. Pin saved evaluation runs and follow the
[cohort policy](../analytics/cohorts.md) for cataloging and selective archives.

## Stage F execution gate

The [20-run campaign](model-upgrade-plan.md#stage-f-campaign--up-to-20-full-live-runs)
supersedes the earlier two-call proposal. Use the cumulative slot ledger as the run
authority and disable page-reload retries. Before paid admission, confirm the model
panel and capture frozen source/dependency identity. Run failures use slots and pause
the affected path for review. Explicit resume approves the presented next step.
The user cleared the campaign goal after 15 slots. The next proposed batch pairs
GPT-6 Luna on Chat Completions and Decisions. Follow the
[Luna comparison plan](model-upgrade-plan.md#proposed-next-batch--luna-across-two-apis)
for the two profiles, controls, run order and reporting. Paid execution is deferred.
