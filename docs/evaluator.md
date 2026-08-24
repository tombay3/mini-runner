# Agent evaluator

## Purpose

`npm run evaluate` runs repeatable attempts through the browser wrapper and legacy runtime. It
starts required services when needed and records snapshots, ticks, terminal state, recordings, and
traces.

The evaluator is an evidence tool, not a completion requirement. It can assess completion,
selection behavior, candidate coverage, loop recovery, or decision-sequence diversity depending on
the evaluation goal.

## Usage

```sh
# One or more normal evaluator attempts
npm run evaluate -- --runs 5

# Stop early after a requested number of successful attempts
npm run evaluate -- --runs 10 --target 5

# Use a specific profile, browser, or visible browser session
npm run evaluate -- --profile openai --browser /path/to/chrome --headful

# Verify wrapper/backend/runtime startup without an LLM call
npm run evaluate -- --smoke

# Keep an aggregate report outside rolling trace retention
npm run evaluate -- --runs 20 --output /tmp/evaluation-20.json
```

Chrome is discovered from common paths. Set `EVAL_BROWSER_EXECUTABLE` or pass `--browser` when it
is installed elsewhere. `--smoke` checks infrastructure only; normal evaluation can consume
substantial provider time and quota.

`--target N` stops after `N` successes or when `--runs` is exhausted. Runs and target values are
positive integers with a maximum of 100.

## Reports and retention

Each attempt records:

- outcome, decision count, game time, and trace/recording IDs;
- model metadata and normal-mode evidence;
- candidates, scores, selections, fallbacks, and audits; and
- loop evidence, rationale correlation, and a decision-sequence fingerprint.

Failures before the first planner decision remain useful: they are recorded as zero-step traces
with the backend or provider error and requested model metadata.

Exit status is `0` for a completed evaluation that meets an optional target, `1` for
infrastructure/execution failure, `2` for an unmet requested target, `3` for missing normal-mode
evidence, and `4` for a context or tick-timeline violation.

Trace and recording stores retain pinned entries plus the newest unpinned runs. Use `--output` for
an aggregate that must outlive rolling retention.
