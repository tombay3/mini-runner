# Low-Noise Python Logging for the Agent Backend

## Summary
Add Python logging to the Flask backend for observability and debugging, but keep it intentionally narrow: log operational events plus one compact summary per agent planning step, while leaving detailed reasoning and tool-call history in the existing trace store.

Use a dedicated application logger configuration that is initialized **before** `Flask(__name__)` is created, so Flask does not implicitly bootstrap the root logger in an uncontrolled way. Suppress normal Werkzeug access-log chatter and keep request-path visibility through explicit agent summary logs and error logs.

## Key Changes
- Add a small backend logging module under `agent/` that owns:
  - logger setup
  - formatter selection
  - per-module logger retrieval
  - Flask/Werkzeug logger normalization
- Configure logging before Flask app creation in `app.py`.
  - Do not rely on `logging.basicConfig()` after `app = Flask(__name__)`.
  - Create a dedicated app logger namespace, for example `loderunner.agent`.
  - Set `propagate = False` on the app logger to avoid duplicate emission through the root logger.
  - Remove or bypass Flask’s default handler if attached.
- Keep the root logger minimal.
  - Root level should stay at `WARNING` to avoid third-party noise.
  - The application logger should use `INFO` by default, with optional `DEBUG` support via env var.
  - Werkzeug logger should be raised to `WARNING` so per-request access lines are suppressed.
- Use plain-text single-line logs with stable `key=value` fields.
  - Recommended fields: `event`, `trace_id`, `run_id`, `play_data`, `level`, `model`, `run_mode`, `result`, `status`, `error`.
  - Keep messages compact and grep-friendly.

## Logging Behavior
- Log these startup/config events:
  - backend startup complete
  - missing default model config
  - unsupported provider/model configuration
  - trace store / recording store read-write failures
- Log these runtime agent events at `INFO`:
  - `agent_request_received` for `/api/agent/next-action` with `trace_id` or `run_id`, `model`, and `run_mode`
  - `agent_step_selected` with chosen `keyCode`, `ticks`, `model`, `trace_id`, and whether benchmark mode was used
  - `agent_benchmark_selected` when run mode is benchmark, with chosen model and candidate count
  - `agent_recording_saved` when final success/failure demo is persisted with `traceRef`
- Log these failures at `WARNING` or `ERROR`:
  - invalid request payloads
  - model execution failures
  - invalid model output / normalization failures
  - trace persistence failures
  - recording persistence failures
- Do not log:
  - full snapshots
  - full prompt bodies
  - full tool transcripts
  - per-tick browser state
  - normal access log lines from Werkzeug

## Flask Root Logger Workaround
- Initialize logging explicitly before importing or instantiating Flask app objects that may touch `app.logger`.
- Use `logging.config.dictConfig()` or equivalent explicit handler setup instead of ad hoc `basicConfig`.
- After app creation:
  - normalize `app.logger.handlers` so only the intended handler is active
  - set `app.logger.propagate = False`
  - set the `werkzeug` logger level to `WARNING`
- Do not depend on Flask’s `default_handler` behavior as the primary sink.

## Interfaces and Configuration
- Add env-driven controls:
  - `APP_LOG_LEVEL` default `INFO`
  - optional `APP_LOG_FORMAT` but v1 default is plain text only
- No API contract changes are required.
- Existing trace storage remains the source of detailed reasoning history; logs are only operational summaries.

## Test Plan
- Backend checks:
  - startup with valid config emits one startup log line
  - missing model config emits a single clear error without duplicate lines
  - `/api/agent/next-action` emits one compact request log and one compact result log
  - benchmark mode emits one selection summary log, not one verbose line per candidate tool turn
  - invalid request returns `400` and emits one warning log
  - model execution failure returns `502` or `503` and emits one error log
  - saved recording emits a single success/failure persistence log with `traceRef`
- Noise checks:
  - repeated agent requests do not produce Werkzeug access-log clutter
  - trace store continues to hold detailed reasoning so logs stay short
  - no duplicate log lines from root/app logger propagation
- Verification approach:
  - run the Flask app locally
  - hit `/api/health`, `/api/agent/next-action`, and recording endpoints
  - inspect stdout/stderr for one-line event logs only

## Assumptions
- Logging is for local development and lightweight backend observability, not external log aggregation.
- Plain-text `key=value` logs are preferred over JSON for now.
- Per-step agent summary logs are desired, but detailed reasoning remains only in the trace store.
- Normal Werkzeug access logs should be suppressed except for warnings and errors.
