# Low-Noise Python Logging

## Summary
The Flask backend uses narrow, single-line Python logging for operational visibility. Detailed agent diagnosis belongs in the trace store, not stdout.

Logging is initialized before `Flask(__name__)` is created so Flask does not implicitly configure the root logger in an uncontrolled way.

## Logger Setup
[agent/logging_utils.py](../agent/logging_utils.py) owns:

- logger setup
- formatter selection
- per-module logger retrieval
- Flask/Werkzeug logger normalization

The root logger stays quiet. The application logger uses the `loderunner.agent` namespace and does not propagate to root.

Configuration:

- `APP_LOG_LEVEL`, default `INFO`
- `AGENT_DEBUG_LOG=1`, enables raw model I/O debug logging and forces app logs to `DEBUG`
- plain text `key=value` output
- Werkzeug access logs suppressed to `WARNING`

`python app.py --debug` is a shortcut for setting `AGENT_DEBUG_LOG=1` and `APP_LOG_LEVEL=DEBUG` before Flask logging is configured.

## What Gets Logged
Expected low-noise events:

- backend startup
- missing model configuration
- unsupported or invalid model configuration
- invalid agent request payloads
- one `agent_step_selected` event per successful planning response
- one `agent_recording_saved` event when success/failure demos are persisted
- trace/recording store read-write failures
- model execution failures

Common fields:

- `event`
- `trace_id`
- `play_data`
- `level`
- `model`
- `result`
- `status`
- `error`

## What Does Not Get Logged
Do not log:

- full snapshots
- full prompts
- raw model responses
- full candidate lists
- full traces
- per-tick browser state
- normal Werkzeug access lines

Candidate details, stall reports, model choice metadata, and retry/fallback outcomes are stored in [__data1/agent-traces.json](../__data1/agent-traces.json).

When `AGENT_DEBUG_LOG=1` is enabled, raw prompts and model outputs are written to `__data1/agent-debug.log` with a 10-entry rotation. They are not emitted to stdout.

## Current Agent Context
The current runtime is the V2 candidate agent. Normal logs should summarize the candidate step, not reproduce the candidate prompt or trace.

There is no current runtime benchmark mode, and default planning does not use `aisuite` tool-calling loops. If those modes return later, their detailed output should still go to traces, not logs.

## Verification
Useful checks:

- startup emits one clear startup/config line, without duplicates
- `/api/agent/next-action` emits one result/error line
- invalid request returns `400` and emits one warning
- model/config failures return `502` or `503` and emit one compact error
- repeated browser steps do not produce Werkzeug access-log clutter
