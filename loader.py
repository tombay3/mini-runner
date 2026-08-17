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


def _step_event_flags(step: dict) -> dict[str, bool]:
    validation = step.get("validation", {})
    loop = step.get("loopMonitor", {})
    candidates = step.get("candidates", [])
    requested_id = validation.get("requestedCandidateId") or ""
    selected_id = step.get("selectedCandidateId", "")
    candidate_scores = [
        candidate.get("score")
        for candidate in candidates
        if isinstance(candidate.get("score"), (int, float))
    ]
    requested_score = next(
        (
            candidate.get("score")
            for candidate in candidates
            if candidate.get("id") == requested_id
            and isinstance(candidate.get("score"), (int, float))
        ),
        None,
    )
    suppressed_ids = [
        str(item.get("id", ""))
        for item in (loop.get("suppressedCandidates") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    candidate_replaced = bool(requested_id and requested_id != selected_id)
    candidate_suppressed = bool(suppressed_ids)
    return {
        "lower_score_request": bool(
            requested_score is not None
            and candidate_scores
            and requested_score < max(candidate_scores)
        ),
        "warning": candidate_replaced or candidate_suppressed,
        "loop_active": bool(loop.get("active", False)),
        "candidate_replaced": candidate_replaced,
        "candidate_suppressed": candidate_suppressed,
    }


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
        solver = rec.get("solver") or {}
        demo = rec.get("demo", {})
        trace_id = rec.get("traceId")
        trace = trace_runs.get(trace_id, {})
        trace_steps = trace.get("steps", [])
        event_flags = [_step_event_flags(step) for step in trace_steps]
        average_candidate_count = (
            round(
                sum(len(step.get("candidates") or []) for step in trace_steps)
                / len(trace_steps),
                1,
            )
            if trace_steps
            else None
        )

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

        model_info = trace.get("model") or {}

        run_rows.append(
            {
                "id": rec_id,
                "traceId": trace_id,
                "traceId_short": _trace_id_short(trace_id),
                "result": rec.get("result", ""),
                "source": rec.get("source", ""),
                "pinned": rec.get("pinned") is True,
                "level": rec.get("level"),
                "playData": rec.get("playData"),
                "savedAt": saved_at,
                "createdAt": created_at,
                "model": solver.get("model") or model_info.get("model", ""),
                "provider": solver.get("provider") or model_info.get("provider", ""),
                "modelProfile": solver.get("modelProfile")
                or model_info.get("modelProfile", ""),
                "failureReason": solver.get("failureReason", ""),
                "stepCount": trace.get("stepCount", len(trace_steps)),
                "godMode": bool(demo.get("godMode", 0)),
                "averageCandidateCount": average_candidate_count,
                "lowerScoreRequestCount": sum(
                    flag["lower_score_request"] for flag in event_flags
                ),
                "warningStepCount": sum(flag["warning"] for flag in event_flags),
                "activeLoopCount": sum(flag["loop_active"] for flag in event_flags),
                "demoTime": demo_time,
                "recordTime": record_time,
            }
        )

    runs_df = pd.DataFrame(run_rows) if run_rows else pd.DataFrame()

    step_rows = []
    for trace_id, trace in trace_runs.items():
        steps = trace.get("steps", [])
        model_info = trace.get("model", {})
        outcome = trace.get("outcome") or {}
        final_state = outcome.get("finalState") or {}
        for step_idx, step in enumerate(steps):
            action = step.get("action", {})
            loop = step.get("loopMonitor", {})
            suppressed = loop.get("suppressedCandidates", [])
            suppressed_candidates = [
                {
                    "id": str(item.get("id")),
                    "kind": item.get("kind"),
                    "direction": item.get("direction"),
                    "reason": item.get("reason"),
                }
                for item in suppressed
                if isinstance(item, dict) and item.get("id")
            ]
            validation = step.get("validation", {})
            state = step.get("state", {})
            candidates = step.get("candidates", [])

            selected_id = step.get("selectedCandidateId", "")
            selected_kind = step.get("selectedCandidateKind", "")
            event_flags = _step_event_flags(step)

            risk = state.get("guardRisk", {})
            runner = state.get("runner", {})
            after_state = (
                steps[step_idx + 1].get("state") or {}
                if step_idx + 1 < len(steps)
                else final_state
            )
            after_runner = after_state.get("runner", {})
            after_risk = after_state.get("guardRisk", {})
            is_final_step = step_idx + 1 == len(steps)

            step_rows.append(
                {
                    "traceId": trace_id,
                    "stepIndex": step_idx,
                    "action_keyCode": action.get("keyCode"),
                    "action_ticks": action.get("ticks"),
                    "action_reason": action.get("reason", ""),
                    "selectedCandidateId": selected_id,
                    "selectedCandidateKind": selected_kind,
                    "requestedCandidateId": validation.get("requestedCandidateId") or "",
                    "candidateCount": len(candidates),
                    "fallbackUsed": validation.get("fallbackUsed", False),
                    "fallbackReason": validation.get("fallbackReason") or "",
                    "event_lowerScoreRequest": event_flags["lower_score_request"],
                    "event_warning": event_flags["warning"],
                    "event_candidateReplaced": event_flags["candidate_replaced"],
                    "event_candidateSuppressed": event_flags["candidate_suppressed"],
                    "loop_active": event_flags["loop_active"],
                    "loop_type": loop.get("type") if loop.get("active") else None,
                    "loop_suppressedIds": ",".join(
                        item["id"] for item in suppressed_candidates
                    ),
                    "loop_suppressedCandidates": suppressed_candidates,
                    "runner_x": runner.get("x"),
                    "runner_y": runner.get("y"),
                    "risk_level": risk.get("risk", ""),
                    "gold_remaining": state.get("gold", {}).get("remainingCount"),
                    "game_state": state.get("gameState", ""),
                    "after_runner_x": after_runner.get("x"),
                    "after_runner_y": after_runner.get("y"),
                    "after_risk_level": after_risk.get("risk", ""),
                    "after_gold_remaining": after_state.get("gold", {}).get(
                        "remainingCount"
                    ),
                    "after_game_state": after_state.get("gameState", ""),
                    "terminal_result": outcome.get("result", "") if is_final_step else "",
                    "terminal_reason": outcome.get("reason", "") if is_final_step else "",
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
                    "selected": cand.get("id") == selected_id,
                    "reason": (cand.get("firstAction") or {}).get("reason", ""),
                }
            )

    return pd.DataFrame(rows) if rows else pd.DataFrame()
