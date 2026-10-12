# Agent evaluator

## Purpose

`npm run eval` runs repeatable attempts through the browser wrapper and legacy runtime. It
starts required services when needed and records snapshots, ticks, terminal state, recordings, and
traces.

The evaluator is an evidence tool, not a completion requirement. It can assess completion,
selection behavior, candidate coverage, loop recovery, or decision-sequence diversity depending on
the evaluation goal.

## Usage

```sh
# One or more normal evaluator attempts
npm run eval -- --runs 5

# Run and validate god-mode attempts
npm run eval -- --profile openai --runs 1 --god-mode

# Stop early after a requested number of successful attempts
npm run eval -- --runs 10 --target 5

# Use a specific profile, browser, or visible browser session
npm run eval -- --profile openai --browser /path/to/chrome --headful

# Verify wrapper/backend/runtime startup without an LLM call
npm run eval -- --smoke

# Keep an aggregate report outside rolling trace retention
npm run eval -- --runs 20 --output /tmp/evaluation-20.json
```

Chrome is discovered from common paths. Set `EVAL_BROWSER_EXECUTABLE` or pass `--browser` when it
is installed elsewhere. `--smoke` checks infrastructure only; normal evaluation can consume
substantial provider time and quota.

`--target N` stops after `N` successes or when `--runs` is exhausted. Runs and target values are
positive integers with a maximum of 100.

Each attempt has a 60-minute wall-clock timeout by default. Override it with
`--run-timeout-min N`. For example, `--run-timeout-min 120` allows two hours.

An attempt finishes only after its saved recording has been refreshed in the wrapper.
The evaluator checks readiness before every attempt, using `--startup-timeout-sec N`
(default 30, maximum 300), and includes wrapper status when that check fails. It does not retry
an attempt merely because the wrapper is busy.

Normal mode remains the default. `--god-mode` enables god mode through the existing runtime toggle
before smoke validation and before every attempt. Reports record the requested mode plus recording
step, and terminal evidence; a mismatch is an evaluation failure.

## Hybrid reproducer

`npm run eval:reproduce` replays a retained Classic 1:1 recording to a decision
boundary, verifies the state/history, then can continue with normal model calls.
The prefix is reproducible; model choices and native guard events after handoff
remain variable. Control uses `--control-ref` (default `HEAD`); fix uses the local
worktree unless `--fix-ref` selects an immutable revision. Both need the current
V4 backend. Normal mode and god mode are supported. Recording, trace, and
replayed game must agree on mode and Classic 1:1. Continuation checks mode/context
before each request and after each action, and verifies recording mode before
saving. Smoke replay distinguishes a natural terminal from a running decision
boundary at the same tick. Original stores remain read-only.

Focused offline checks: `node scripts/hybrid-runtime.mjs --test`.
They cover both modes, context mismatches, terminal boundaries, and startup
failures. Owned Vite is cleaned up even if browser shutdown fails.

```sh
npm run eval:reproduce -- prepare --trace <trace-id-or-prefix> --tick <tick> \
  --control-ref main --paid-budget 2 --output __data3/<fresh-experiment>
npm run eval:reproduce -- preflight --output __data3/<fresh-experiment>
```

`prepare`, `preflight`, `smoke`, and `verify-smoke` make no paid calls. Run those
checks before `pair 1`, the only command that starts paid continuations. The
budget defaults to zero and is frozen at preparation; each continuation may
make multiple requests. Model/profile must match the historical trace.

Paid execution needs explicit budget and provider-data approval. Ask the owner
to stop any existing Flask backend; the tool starts its own isolated backend,
reuses running Vite, and keeps Chromium sandboxed. Generated source snapshots,
traces, recordings and file-based `status` stay under ignored `__data3`.
Snapshots contain private environment links; do not publish entire directories.

Use `review` after each pair before starting another, then `finish` to close the
experiment. These commands take the same `--output` directory. Inspect an
existing lock and its owner before resuming; never remove a live owner's lock
or resume failed integrity checks blindly. Do not change prepared code/runtime.

## Reports and retention

Each attempt records:

- outcome, decision count, game time, and trace/recording IDs;
- model metadata and requested-mode evidence;
- candidates, scores, selections, fallbacks, and audits; and
- loop evidence and rationale correlation.

Failures before the first planner decision remain useful: they are recorded as zero-step traces
with the backend or provider error and requested model metadata.

Exit status is `0` for a completed evaluation that meets an optional target, `1` for
infrastructure/execution failure, `2` for an unmet requested target, `3` for missing requested-mode
evidence, and `4` for a context or tick-timeline violation.

Trace and recording stores retain pinned entries plus the newest unpinned runs. Use `--output` for
an aggregate that must outlive rolling retention.
