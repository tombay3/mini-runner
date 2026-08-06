import json
import os
from pathlib import Path
import pandas as pd
from datetime import datetime, timezone


def _parse_ts(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _trace_id_short(value):
    text = str(value or "")
    return text.split("-", 1)[0][:8]


def load_data(folder: str):
    folder_path = Path(folder)
    errors = []

    recordings_raw = {}
    traces_raw = {}

    rec_path = folder_path / "recordings.json"
    if rec_path.exists():
        try:
            recordings_raw = json.loads(rec_path.read_text())
        except Exception as e:
            errors.append(f"recordings.json: {e}")
    else:
        errors.append(f"recordings.json not found in {folder}")

    trace_path = folder_path / "agent-traces.json"
    if trace_path.exists():
        try:
            traces_raw = json.loads(trace_path.read_text())
        except Exception as e:
            errors.append(f"agent-traces.json: {e}")
    else:
        errors.append(f"agent-traces.json not found in {folder}")

    runs_df, steps_df = _build_dataframes(recordings_raw, traces_raw)
    meta = {
        "rec_updated_at": recordings_raw.get("updatedAt"),
        "rec_version": recordings_raw.get("version"),
        "errors": errors,
    }
    return runs_df, steps_df, meta


def _build_dataframes(recordings_raw: dict, traces_raw: dict):
    records = recordings_raw.get("records", {})
    trace_runs = traces_raw.get("runs", {})

    run_rows = []
    for rec_id, rec in records.items():
        solver = rec.get("solver", {})
        demo = rec.get("demo", {})
        trace_id = rec.get("traceId")
        trace = trace_runs.get(trace_id, {})

        saved_at = _parse_ts(rec.get("savedAt"))
        created_at = _parse_ts(trace.get("createdAt"))
        updated_at = _parse_ts(trace.get("updatedAt"))

        record_time_s = None
        if updated_at and created_at:
            record_time_s = round((updated_at - created_at).total_seconds())

        def _fmt_mm_ss(total_seconds: int) -> str:
            if total_seconds is None:
                return ""
            m = total_seconds // 60
            s = total_seconds % 60
            return f"{m}:{s:02d}"

        record_time = _fmt_mm_ss(record_time_s)
        demo_time_ticks = demo.get("time")
        try:
            demo_time_s = round(float(demo_time_ticks) / 16)
        except (TypeError, ValueError):
            demo_time_s = None
        demo_time = _fmt_mm_ss(demo_time_s)

        model_info = trace.get("model", {})

        run_rows.append(
            {
                "id": rec_id,
                "traceId": trace_id,
                "traceId_short": _trace_id_short(trace_id),
                "result": rec.get("result", ""),
                "source": rec.get("source", ""),
                "level": rec.get("level"),
                "playData": rec.get("playData"),
                "savedAt": saved_at,
                "createdAt": created_at,
                "model": solver.get("model") or model_info.get("model", ""),
                "provider": solver.get("provider") or model_info.get("provider", ""),
                "modelProfile": solver.get("modelProfile")
                or model_info.get("modelProfile", ""),
                "failureReason": solver.get("failureReason", ""),
                "stepCount": trace.get("stepCount", len(trace.get("steps", []))),
                "godMode": bool(demo.get("godMode", 0)),
                "demoTime": demo_time,
                "recordTime": record_time,
                "show_score": trace.get("config", {}).get("showCandidateScores", False),
            }
        )

    runs_df = pd.DataFrame(run_rows) if run_rows else pd.DataFrame()

    step_rows = []
    for trace_id, trace in trace_runs.items():
        steps = trace.get("steps", [])
        model_info = trace.get("model", {})
        for step_idx, step in enumerate(steps):
            action = step.get("action", {})
            stall = step.get("stallSupervisor", {})
            observations = stall.get("observations", {})
            validation = step.get("validation", {})
            state = step.get("state", {})
            candidates = step.get("candidates", [])

            selected_id = step.get("selectedCandidateId", "")
            selected_kind = step.get("selectedCandidateKind", "")

            risk = state.get("guardRisk", {})
            runner = state.get("runner", {})

            step_rows.append(
                {
                    "traceId": trace_id,
                    "stepIndex": step_idx,
                    "action_keyCode": action.get("keyCode"),
                    "action_ticks": action.get("ticks"),
                    "action_reason": action.get("reason", ""),
                    "selectedCandidateId": selected_id,
                    "selectedCandidateKind": selected_kind,
                    "candidateCount": len(candidates),
                    "fallbackUsed": validation.get("fallbackUsed", False),
                    "fallbackReason": validation.get("fallbackReason") or "",
                    "stall_stalled": bool(stall.get("stalled", False)),
                    "stall_severity": "stalled" if stall.get("stalled", False) else "none",
                    "stall_type": stall.get("type") if stall.get("stalled", False) else None,
                    "stall_retryAttempted": stall.get("retryAttempted", False),
                    "stall_fallbackAfterRetry": stall.get("fallbackAfterRetry", False),
                    "stall_blockedKinds": ",".join(
                        stall.get("blockedCandidateKinds", [])
                    ),
                    "observation_shortHorizontalOscillation": bool(
                        observations.get("shortHorizontalOscillation", False)
                    ),
                    "observation_repeatedCandidate": bool(
                        observations.get("repeatedCandidate", False)
                    ),
                    "observation_sameCandidateStreak": observations.get(
                        "sameCandidateStreak", 0
                    ),
                    "observation_repeatedCandidateId": observations.get(
                        "repeatedCandidateId"
                    ),
                    "observation_targetProgress": bool(
                        observations.get("targetProgress", False)
                    ),
                    "observation_targetReached": bool(
                        observations.get("targetReached", False)
                    ),
                    "valid_actionValid": validation.get("actionValid", True),
                    "valid_actionGuardSafe": validation.get("actionGuardSafe", True),
                    "valid_stallBlocked": validation.get("stallBlocked", False),
                    "valid_stallSeverity": validation.get("stallSeverity", "none"),
                    "valid_choiceReason": validation.get("choiceReason", ""),
                    "runner_x": runner.get("x"),
                    "runner_y": runner.get("y"),
                    "risk_level": risk.get("risk", ""),
                    "gold_remaining": state.get("gold", {}).get("remainingCount"),
                    "model": model_info.get("model", ""),
                    "provider": model_info.get("provider", ""),
                    "candidates_raw": candidates,
                }
            )

    steps_df = pd.DataFrame(step_rows) if step_rows else pd.DataFrame()
    return runs_df, steps_df


def get_candidates_df(steps_df: pd.DataFrame) -> pd.DataFrame:
    if steps_df.empty or "candidates_raw" not in steps_df.columns:
        return pd.DataFrame()

    rows = []
    for _, row in steps_df.iterrows():
        selected_id = row.get("selectedCandidateId", "")
        for cand in row.get("candidates_raw", []):
            rows.append(
                {
                    "traceId": row["traceId"],
                    "stepIndex": row["stepIndex"],
                    "candidateId": cand.get("id", ""),
                    "kind": cand.get("kind", ""),
                    "score": cand.get("score", 0),
                    "stallBlocked": cand.get("stallBlocked", False),
                    "stallRecovery": cand.get("stallRecovery", False),
                    "selected": cand.get("id") == selected_id,
                    "goal": cand.get("goal", ""),
                    "reason": cand.get("reason", ""),
                }
            )

    return pd.DataFrame(rows) if rows else pd.DataFrame()
