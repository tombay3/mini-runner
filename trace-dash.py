import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, cast

import pandas as pd
import streamlit as st

from ascii_map import (
    find_selected_candidate,
    has_coordinate_geometry,
    render_ascii_map,
)


# ── Data loading and DataFrame builders ─────────────────────────────────────
def _parse_ts(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(val, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _trace_id_short(value: Any) -> str:
    text = str(value or "")
    return text.split("-", 1)[0][:8]


def _as_dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return default


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return None


def _step_event_flags(step: dict) -> dict[str, bool]:
    step = _as_dict(step)
    validation = _as_dict(step.get("validation"))
    loop = _as_dict(step.get("loopMonitor"))
    candidates = _as_dict_list(step.get("candidates"))
    requested_id = validation.get("requestedCandidateId") or ""
    selected_id = step.get("selectedCandidateId", "")
    suppressed_ids = [
        str(item.get("id", ""))
        for item in _as_list(loop.get("suppressedCandidates"))
        if isinstance(item, dict) and item.get("id")
    ]
    candidate_replaced = bool(requested_id and str(requested_id) != str(selected_id))
    candidate_suppressed = bool(suppressed_ids)
    fallback_used = bool(validation.get("fallbackUsed", False))
    return {
        "lower_score_request": _is_meaningful_lower_score_request(
            candidates, str(requested_id)
        ),
        "warning": candidate_replaced or candidate_suppressed or fallback_used,
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
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            errors.append(f"recordings.json: {e}")
    else:
        errors.append(f"recordings.json not found in {folder}")

    trace_path = folder_path / "agent-traces.json"
    if trace_path.exists():
        try:
            traces_raw = json.loads(trace_path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            errors.append(f"agent-traces.json: {e}")
    else:
        errors.append(f"agent-traces.json not found in {folder}")

    recordings_raw = _as_dict(recordings_raw)
    traces_raw = _as_dict(traces_raw)
    runs_df, steps_df = _build_dataframes(recordings_raw, traces_raw)
    meta = {
        "rec_updated_at": recordings_raw.get("updatedAt"),
        "rec_version": recordings_raw.get("version"),
        "errors": errors,
    }
    return runs_df, steps_df, meta


def _build_dataframes(recordings_raw: dict, traces_raw: dict):
    recordings_raw = _as_dict(recordings_raw)
    traces_raw = _as_dict(traces_raw)
    records = _as_dict(recordings_raw.get("records"))
    trace_runs = _as_dict(traces_raw.get("runs"))

    run_rows = []
    for rec_id, rec_value in records.items():
        rec = _as_dict(rec_value)
        solver = _as_dict(rec.get("solver"))
        demo = _as_dict(rec.get("demo"))
        trace_id = rec.get("traceId")
        trace = _as_dict(trace_runs.get(trace_id)) if isinstance(trace_id, str) else {}
        trace_steps = _as_list(trace.get("steps"))
        event_flags = [_step_event_flags(step) for step in trace_steps]
        average_candidate_count = (
            round(
                sum(
                    len(_as_dict_list(_as_dict(step).get("candidates")))
                    for step in trace_steps
                )
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

        def _fmt_mm_ss(total_seconds: int | None) -> str:
            if total_seconds is None:
                return ""
            m = total_seconds // 60
            s = total_seconds % 60
            return f"{m}:{s:02d}"

        record_time = _fmt_mm_ss(record_time_s)
        demo_time_ticks = demo.get("time")
        try:
            if not isinstance(demo_time_ticks, (int, float, str)):
                raise TypeError
            demo_time_s = round(float(demo_time_ticks) / 16)
        except (TypeError, ValueError):
            demo_time_s = None
        demo_time = _fmt_mm_ss(demo_time_s)

        model_info = _as_dict(trace.get("model"))

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
                "loopActiveSteps": sum(flag["loop_active"] for flag in event_flags),
                "demoTime": demo_time,
                "recordTime": record_time,
            }
        )

    runs_df = pd.DataFrame(run_rows) if run_rows else pd.DataFrame()

    step_rows = []
    for trace_id, trace_value in trace_runs.items():
        trace = _as_dict(trace_value)
        steps = _as_list(trace.get("steps"))
        model_info = _as_dict(trace.get("model"))
        outcome = _as_dict(trace.get("outcome"))
        final_state = _as_dict(outcome.get("finalState"))
        for step_idx, step_value in enumerate(steps):
            step = _as_dict(step_value)
            action = _as_dict(step.get("action"))
            loop = _as_dict(step.get("loopMonitor"))
            suppressed = _as_list(loop.get("suppressedCandidates"))
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
            validation = _as_dict(step.get("validation"))
            model_selection = _as_dict(step.get("modelSelection"))
            safety_rejections = [
                {
                    "candidateId": str(item.get("candidateId")),
                    "kind": item.get("kind"),
                    "detail": str(item.get("detail") or "").strip(),
                    "action_keyCode": _as_dict(item.get("proposedAction")).get(
                        "keyCode"
                    ),
                    "action_ticks": _as_dict(item.get("proposedAction")).get("ticks"),
                }
                for item in _as_list(step.get("candidateAudit"))
                if isinstance(item, dict)
                and item.get("disposition") == "safety_rejection"
                and item.get("candidateId")
            ]
            state = _as_dict(step.get("state"))
            candidates = _as_dict_list(step.get("candidates"))

            selected_id = step.get("selectedCandidateId", "")
            selected_kind = step.get("selectedCandidateKind", "")
            event_flags = _step_event_flags(step)

            risk = _as_dict(state.get("guardRisk"))
            runner = _as_dict(state.get("runner"))
            after_state = (
                _as_dict(_as_dict(steps[step_idx + 1]).get("state"))
                if step_idx + 1 < len(steps)
                else final_state
            )
            after_runner = _as_dict(after_state.get("runner"))
            after_risk = _as_dict(after_state.get("guardRisk"))
            state_gold = _as_dict(state.get("gold"))
            after_gold = _as_dict(after_state.get("gold"))
            is_final_step = step_idx + 1 == len(steps)

            step_rows.append(
                {
                    "traceId": trace_id,
                    "stepIndex": step_idx,
                    "state_tick": state.get("tick"),
                    "after_state_tick": after_state.get("tick"),
                    "action_keyCode": action.get("keyCode"),
                    "action_ticks": action.get("ticks"),
                    "action_reason": action.get("reason", ""),
                    "selectedCandidateId": selected_id,
                    "selectedCandidateKind": selected_kind,
                    "requestedCandidateId": validation.get("requestedCandidateId")
                    or "",
                    "candidateCount": len(candidates),
                    "fallbackUsed": validation.get("fallbackUsed", False),
                    "fallbackReason": validation.get("fallbackReason") or "",
                    "reasoningContent": (
                        model_selection.get("reasoningContent")
                        if isinstance(model_selection.get("reasoningContent"), str)
                        else ""
                    ),
                    "declaredRationale": (
                        model_selection.get("declaredRationale")
                        if isinstance(model_selection.get("declaredRationale"), str)
                        else ""
                    ),
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
                    "candidateSafetyRejections": safety_rejections,
                    "state_raw": state,
                    "runner_x": runner.get("x"),
                    "runner_y": runner.get("y"),
                    "runner_xOffset": runner.get("xOffset"),
                    "runner_yOffset": runner.get("yOffset"),
                    "risk_level": risk.get("risk", ""),
                    "gold_remaining": state_gold.get("remainingCount"),
                    "gold_complete": state_gold.get("complete"),
                    "game_state": state.get("gameState", ""),
                    "after_runner_x": after_runner.get("x"),
                    "after_runner_y": after_runner.get("y"),
                    "after_runner_xOffset": after_runner.get("xOffset"),
                    "after_runner_yOffset": after_runner.get("yOffset"),
                    "after_risk_level": after_risk.get("risk", ""),
                    "after_gold_remaining": after_gold.get("remainingCount"),
                    "after_gold_complete": after_gold.get("complete"),
                    "after_game_state": after_state.get("gameState", ""),
                    "terminal_result": outcome.get("result", "")
                    if is_final_step
                    else "",
                    "terminal_reason": outcome.get("reason", "")
                    if is_final_step
                    else "",
                    "model": model_info.get("model", ""),
                    "provider": model_info.get("provider", ""),
                    "candidates_raw": candidates,
                }
            )

    steps_df = pd.DataFrame(step_rows) if step_rows else pd.DataFrame()
    return runs_df, steps_df


def _is_true(value: Any) -> bool:
    try:
        return False if pd.isna(value) else bool(value)
    except (TypeError, ValueError):
        return False


def _action_signature(value: Any) -> tuple[int, int] | None:
    action = _as_dict(value)
    key_code = _safe_number(action.get("keyCode"))
    ticks = _safe_number(action.get("ticks"))
    if key_code is None or ticks is None:
        return None
    return int(key_code), int(ticks)


def _candidate_signatures(candidates: list[dict[str, Any]]) -> set[tuple[int, int]]:
    return {
        signature
        for candidate in candidates
        if (signature := _action_signature(candidate.get("firstAction"))) is not None
    }


def _is_meaningful_lower_score_request(
    candidates: list[dict[str, Any]], requested_id: str
) -> bool:
    """Return whether a model request chose a lower-scored distinct action."""
    signatures = _candidate_signatures(candidates)
    if len(signatures) < 2:
        return False
    requested = next(
        (
            candidate
            for candidate in candidates
            if str(candidate.get("id") or "") == requested_id
        ),
        None,
    )
    if requested is None:
        return False
    requested_score = _safe_number(requested.get("score"))
    requested_signature = _action_signature(requested.get("firstAction"))
    scored = [
        (candidate, score)
        for candidate in candidates
        if (score := _safe_number(candidate.get("score"))) is not None
    ]
    if requested_score is None or requested_signature is None or not scored:
        return False
    top_score = max(score for _, score in scored)
    top_signatures = _candidate_signatures(
        [candidate for candidate, score in scored if score == top_score]
    )
    return requested_score < top_score and requested_signature not in top_signatures


def _contiguous_ranges(positions: list[int]) -> list[tuple[int, int]]:
    if not positions:
        return []
    ranges = []
    start = previous = positions[0]
    for position in positions[1:]:
        if position != previous + 1:
            ranges.append((start, previous))
            start = position
        previous = position
    ranges.append((start, previous))
    return ranges


def _range_ticks(rows: list[pd.Series], start: int, end: int) -> int | None:
    start_tick = _safe_number(rows[start].get("state_tick"))
    end_tick = _safe_number(rows[end].get("after_state_tick"))
    if start_tick is None or end_tick is None or end_tick < start_tick:
        return None
    return int(end_tick - start_tick)


def _range_rank(rows: list[pd.Series], interval: tuple[int, int]) -> tuple[int, int]:
    start, end = interval
    ticks = _range_ticks(rows, start, end)
    return (ticks if ticks is not None else -1, end - start + 1)


def _longest_range(
    rows: list[pd.Series], ranges: list[tuple[int, int]]
) -> tuple[int, int] | None:
    return max(ranges, key=lambda interval: _range_rank(rows, interval), default=None)


def _display_step(row: pd.Series) -> int:
    return _safe_int(row.get("stepIndex")) + 1


def _range_label(rows: list[pd.Series], interval: tuple[int, int]) -> str:
    start, end = interval
    first = _display_step(rows[start])
    last = _display_step(rows[end])
    return f"Step {first}" if first == last else f"Steps {first}–{last}"


def _format_tick_duration(ticks: int | None) -> str:
    if ticks is None:
        return "duration unavailable"
    seconds = round(ticks / 16)
    return f"{seconds} sec"


def _candidates_text(choice: dict[str, int]) -> str:
    return (
        "Candidates: "
        f"safety lane {choice['safety_only']} · "
        f"progress lane {choice['progress_only']} · "
        f"both lanes {choice['both']} · "
        f"{choice['candidate_singleton']} singletons · "
        f"{choice['forced_safety']} forced safety · "
        f"{choice['forced_progress']} forced progress · "
        f"{choice['multi_action_decision']} non-singletons on "
        f"{choice['steps']} steps"
    )


def _signal(
    title: str,
    evidence: str,
    rows: list[pd.Series],
    interval: tuple[int, int],
    *,
    range_after_first_clause: bool = False,
) -> dict[str, Any]:
    start, _ = interval
    return {
        "title": title,
        "evidence": evidence,
        "range": _range_label(rows, interval),
        "stepIndex": _safe_int(rows[start].get("stepIndex")),
        "rangeAfterFirstClause": range_after_first_clause,
    }


def _signal_line(signal: dict[str, Any], *, markdown: bool = False) -> str:
    title = str(signal["title"])
    evidence = str(signal["evidence"])
    range_text = f"({signal['range']})"
    if signal.get("rangeAfterFirstClause"):
        first, separator, rest = evidence.partition(" · ")
        evidence = f"{first} {range_text}"
        if separator:
            evidence += f"{separator}{rest}"
    else:
        evidence = f"{evidence} {range_text}"
    rendered_title = f"**{title}**" if markdown else title
    return f"{rendered_title} — {evidence}"


def _build_run_signals(
    trace_steps: pd.DataFrame,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Summarize candidates and return one window per signal category."""
    ordered = trace_steps.sort_values("stepIndex")
    rows = [row for _, row in ordered.iterrows()]
    choice = {
        "steps": len(rows),
        "safety_only": 0,
        "progress_only": 0,
        "both": 0,
        "candidate_singleton": 0,
        "forced_safety": 0,
        "forced_progress": 0,
        "multi_action_decision": 0,
    }
    if not rows:
        return choice, []

    row_candidates: list[list[dict[str, Any]]] = []
    row_signatures: list[set[tuple[int, int]]] = []
    for row in rows:
        candidates = _as_dict_list(row.get("candidates_raw"))
        signatures = _candidate_signatures(candidates)
        row_candidates.append(candidates)
        row_signatures.append(signatures)
        lanes = {str(candidate.get("lane") or "other") for candidate in candidates}
        has_safety = "safety" in lanes
        has_progress = "progress" in lanes
        availability = (
            "both"
            if has_safety and has_progress
            else "safety_only"
            if has_safety
            else "progress_only"
            if has_progress
            else None
        )
        if availability is not None:
            choice[availability] += 1
        choice["candidate_singleton"] += len(candidates) == 1
        if len(candidates) == 1:
            singleton = candidates[0]
            singleton_kind = str(singleton.get("kind") or "")
            singleton_lane = str(singleton.get("lane") or "other")
            if singleton_kind in {
                "wait_for_dig_completion",
                "wait_for_trap_resolution",
            }:
                pass
            elif singleton_kind == "emergency_hold" or singleton_lane == "safety":
                choice["forced_safety"] += 1
            elif singleton_lane == "progress":
                choice["forced_progress"] += 1
        choice["multi_action_decision"] += len(signatures) >= 2

    signals: list[dict[str, Any]] = []

    # Safety rejection pressure, including the longest repeated kind/action.
    rejection_step_positions = []
    safety_rejected_count = 0
    rejection_positions: dict[tuple[str, int, int], list[int]] = {}
    for position, row in enumerate(rows):
        rejections = _as_dict_list(row.get("candidateSafetyRejections"))
        if rejections:
            rejection_step_positions.append(position)
            safety_rejected_count += len(rejections)
        step_signatures = set()
        for rejection in rejections:
            key_code = _safe_number(rejection.get("action_keyCode"))
            ticks = _safe_number(rejection.get("action_ticks"))
            kind = str(rejection.get("kind") or "")
            if kind and key_code is not None and ticks is not None:
                step_signatures.add((kind, int(key_code), int(ticks)))
        for signature in step_signatures:
            rejection_positions.setdefault(signature, []).append(position)
    if rejection_step_positions:
        repeated: list[tuple[tuple[int, int], tuple[str, int, int]]] = []
        for signature, positions in rejection_positions.items():
            repeated.extend(
                (interval, signature) for interval in _contiguous_ranges(positions)
            )
        if repeated:
            rejection_interval, rejection_signature = max(
                repeated,
                key=lambda item: (
                    item[0][1] - item[0][0] + 1,
                    _range_rank(rows, item[0])[0],
                ),
            )
            kind, _, _ = rejection_signature
            streak_steps = rejection_interval[1] - rejection_interval[0] + 1
            detail = f" · {kind} safety-rejected {streak_steps} times"
        else:
            rejection_interval = (
                rejection_step_positions[0],
                rejection_step_positions[0],
            )
            detail = ""
        signals.append(
            _signal(
                "Safety constraints",
                f"{safety_rejected_count} safety rejections on "
                f"{len(rejection_step_positions)} steps{detail}",
                rows,
                rejection_interval,
            )
        )

    # Confirmed loop steps are counted separately from contiguous episodes.
    loop_positions = [
        position
        for position, row in enumerate(rows)
        if _is_true(row.get("loop_active"))
    ]
    loop_ranges = _contiguous_ranges(loop_positions)
    loop_interval = _longest_range(rows, loop_ranges)
    if loop_interval is not None:
        signals.append(
            _signal(
                "Confirmed loops",
                f"{len(loop_positions)} active steps on {len(loop_ranges)} episodes · "
                f"longest {_format_tick_duration(_range_ticks(rows, *loop_interval))}",
                rows,
                loop_interval,
            )
        )

    # Progress context: no-gold time, bounded waits/holds, and terminal delay.
    no_gold_groups: list[tuple[int, int]] = []
    no_gold_start: int | None = None
    previous_gold: int | float | None = None
    for position, row in enumerate(rows):
        before = _safe_number(row.get("gold_remaining"))
        after = _safe_number(row.get("after_gold_remaining"))
        unchanged = before is not None and after is not None and before == after
        if unchanged and (
            no_gold_start is None or (position > 0 and previous_gold == before)
        ):
            if no_gold_start is None:
                no_gold_start = position
        else:
            if no_gold_start is not None:
                no_gold_groups.append((no_gold_start, position - 1))
            no_gold_start = position if unchanged else None
        previous_gold = after if unchanged else None
    if no_gold_start is not None:
        no_gold_groups.append((no_gold_start, len(rows) - 1))
    no_gold_interval = _longest_range(rows, no_gold_groups)

    wait_kinds = {
        "emergency_hold",
        "wait_for_dig_completion",
        "wait_for_floor_refill",
        "wait_for_trap_resolution",
    }
    wait_ranges = _contiguous_ranges(
        [
            position
            for position, row in enumerate(rows)
            if str(row.get("selectedCandidateKind") or "") in wait_kinds
        ]
    )
    wait_interval = _longest_range(rows, wait_ranges)
    if wait_interval is not None:
        wait_ticks = _range_ticks(rows, *wait_interval)
        wait_steps = wait_interval[1] - wait_interval[0] + 1
        if not ((wait_ticks is not None and wait_ticks >= 32) or wait_steps >= 3):
            wait_interval = None

    complete_position = None
    complete_start_tick = None
    for position, row in enumerate(rows):
        if _is_true(row.get("gold_complete")) or row.get("gold_remaining") == 0:
            complete_position = position
            complete_start_tick = _safe_number(row.get("state_tick"))
            break
        if (
            _is_true(row.get("after_gold_complete"))
            or row.get("after_gold_remaining") == 0
        ):
            complete_position = position
            complete_start_tick = _safe_number(row.get("after_state_tick"))
            break
    complete_interval = (
        (complete_position, len(rows) - 1) if complete_position is not None else None
    )
    complete_ticks = None
    if complete_interval is not None:
        final_tick = _safe_number(rows[-1].get("after_state_tick"))
        if (
            complete_start_tick is not None
            and final_tick is not None
            and final_tick >= complete_start_tick
        ):
            complete_ticks = int(final_tick - complete_start_tick)

    progress_parts = []
    progress_intervals = []
    if no_gold_interval is not None:
        progress_parts.append(
            f"no gold {_format_tick_duration(_range_ticks(rows, *no_gold_interval))}"
        )
        progress_intervals.append(no_gold_interval)
    if wait_interval is not None:
        progress_parts.append(
            f"wait/hold {_format_tick_duration(_range_ticks(rows, *wait_interval))}"
        )
        progress_intervals.append(wait_interval)
    if complete_interval is not None and complete_ticks is not None:
        progress_parts.append(
            f"gold complete→terminal {_format_tick_duration(complete_ticks)}"
        )
        progress_intervals.append(complete_interval)
    progress_interval = _longest_range(rows, progress_intervals)
    if progress_interval is not None:
        signals.append(
            _signal(
                "Progress delay",
                " · ".join(progress_parts),
                rows,
                progress_interval,
            )
        )

    # Stationary stalls: the runner's position and offsets do not change for
    # a sustained window.  Gold is intentionally not part of this detector;
    # unchanged gold is covered by Progress delay above.
    stationary_positions = []
    for position, row in enumerate(rows):
        state_values = (
            _safe_number(row.get("runner_x")),
            _safe_number(row.get("runner_y")),
            _safe_number(row.get("runner_xOffset")),
            _safe_number(row.get("runner_yOffset")),
        )
        after_values = (
            _safe_number(row.get("after_runner_x")),
            _safe_number(row.get("after_runner_y")),
            _safe_number(row.get("after_runner_xOffset")),
            _safe_number(row.get("after_runner_yOffset")),
        )
        if all(value is not None for value in state_values + after_values):
            stationary_positions.append(
                position if state_values == after_values else None
            )
    stationary_ranges = _contiguous_ranges(
        [position for position in stationary_positions if position is not None]
    )
    stationary_ranges = [
        interval
        for interval in stationary_ranges
        if (ticks := _range_ticks(rows, *interval)) is not None and ticks >= 5 * 16
    ]
    stationary_interval = _longest_range(rows, stationary_ranges)
    if stationary_interval is not None:
        start, end = stationary_interval
        window_rows = rows[start : end + 1]
        window_candidates = [
            _as_dict_list(row.get("candidates_raw")) for row in window_rows
        ]
        window_signatures = [
            _candidate_signatures(candidates) for candidates in window_candidates
        ]
        selected_by_row = []
        for row, candidates, signatures in zip(
            window_rows, window_candidates, window_signatures
        ):
            selected_id = str(row.get("selectedCandidateId") or "")
            selected = next(
                (
                    candidate
                    for candidate in candidates
                    if str(candidate.get("id") or "") == selected_id
                ),
                None,
            )
            selected_by_row.append((row, selected, signatures))

        wait_kinds = {
            "emergency_hold",
            "wait_for_dig_completion",
            "wait_for_floor_refill",
            "wait_for_trap_resolution",
        }
        non_action_wait_kinds = {
            "wait_for_dig_completion",
            "wait_for_floor_refill",
            "wait_for_trap_resolution",
        }
        emergency_only = all(
            str(row.get("selectedCandidateKind") or "") == "emergency_hold"
            for row, _, _ in selected_by_row
        )
        forced_safety = all(
            len(signatures) == 1
            and str(_as_dict(selected).get("lane") or "") == "safety"
            and str(row.get("selectedCandidateKind") or "") not in non_action_wait_kinds
            for row, selected, signatures in selected_by_row
        )
        one_action_each = all(
            len(signatures) == 1 for _, _, signatures in selected_by_row
        )

        common_rejections = None
        for row in window_rows:
            row_rejections = {
                (
                    str(rejection.get("kind") or ""),
                    _safe_int(rejection.get("action_keyCode"), -1),
                    _safe_int(rejection.get("action_ticks"), -1),
                )
                for rejection in _as_dict_list(row.get("candidateSafetyRejections"))
            }
            common_rejections = (
                row_rejections
                if common_rejections is None
                else common_rejections & row_rejections
            )
        common_rejection = next(iter(common_rejections or ()), None)

        if emergency_only or one_action_each or common_rejection is not None:
            evidence_parts = []
            if emergency_only:
                evidence_parts.append("emergency hold")
            elif forced_safety:
                evidence_parts.append("forced safety")
            elif one_action_each:
                evidence_parts.append("action singleton")
            evidence_parts.append("runner state unchanged")
            duration = _format_tick_duration(_range_ticks(rows, start, end))
            evidence_parts.append(f"longest {duration}")
            signals.append(
                _signal(
                    "Stationary stalls",
                    " · ".join(evidence_parts),
                    rows,
                    stationary_interval,
                )
            )

    # Compare model requests only when distinct executable actions were visible.
    divergences = []
    for position, (row, candidates) in enumerate(zip(rows, row_candidates)):
        requested_id = str(row.get("requestedCandidateId") or "")
        if not _is_meaningful_lower_score_request(candidates, requested_id):
            continue
        requested = next(
            (
                candidate
                for candidate in candidates
                if str(candidate.get("id") or "") == requested_id
            ),
            None,
        )
        requested_score = _safe_number(
            requested.get("score") if requested is not None else None
        )
        requested_signature = _action_signature(
            requested.get("firstAction") if requested is not None else None
        )
        scored = [
            (candidate, score)
            for candidate in candidates
            if (score := _safe_number(candidate.get("score"))) is not None
        ]
        if requested_score is None or requested_signature is None or not scored:
            continue
        top_score = max(score for _, score in scored)
        top_candidates = [
            candidate for candidate, score in scored if score == top_score
        ]
        requested_lane = str(
            (requested.get("lane") or "other")
            if requested is not None
            else "other"
        )
        top_lanes = {
            str(candidate.get("lane") or "other") for candidate in top_candidates
        }
        divergences.append(
            {
                "position": position,
                "gap": top_score - requested_score,
                "lane_change": requested_lane not in top_lanes,
            }
        )
    if divergences:
        largest = max(divergences, key=lambda item: (item["gap"], -item["position"]))
        lane_changes = [item for item in divergences if item["lane_change"]]
        target = lane_changes[0] if lane_changes else largest
        lane_change_detail = (
            f" · {len(lane_changes)} lane changes" if lane_changes else ""
        )
        interval = (target["position"], target["position"])
        signals.append(
            _signal(
                "Model divergence",
                f"{len(divergences)} lower-score requests on "
                f"{choice['multi_action_decision']} choices · "
                f"largest score gap {largest['gap']:g}{lane_change_detail}",
                rows,
                interval,
            )
        )

    # Validation outcomes: report intervention counts without exposing IDs or reasons.
    validation_positions = [
        position
        for position, row in enumerate(rows)
        if _is_true(row.get("fallbackUsed"))
        or _is_true(row.get("event_candidateReplaced"))
    ]
    if validation_positions:
        fallback_count = sum(_is_true(row.get("fallbackUsed")) for row in rows)
        replacement_count = sum(
            _is_true(row.get("event_candidateReplaced")) for row in rows
        )
        validation_parts = []
        if fallback_count:
            fallback_label = "fallback" if fallback_count == 1 else "fallbacks"
            validation_parts.append(f"{fallback_count} {fallback_label}")
        if replacement_count:
            replacement_label = (
                "replacement" if replacement_count == 1 else "replacements"
            )
            validation_parts.append(f"{replacement_count} {replacement_label}")
        first_position = validation_positions[0]
        signals.append(
            _signal(
                "Validation results",
                " · ".join(validation_parts),
                rows,
                (first_position, first_position),
            )
        )

    return choice, signals


def _candidate_reason(
    candidate: dict,
    *,
    selected_id: str,
    requested_id: str,
    requested_below_top_score: bool,
    candidate_replaced: bool,
    fallback_used: bool,
    fallback_reason: str,
    reasoning_content: str,
    declared_rationale: str,
    suppressed_ids: set[str],
) -> str:
    """Prefix a candidate reason with compact semantic markers and context."""
    candidate_id = str(candidate.get("id") or "")
    markers = []
    semantic_reasons = []

    if candidate_id == requested_id and requested_below_top_score:
        markers.append("✨")
    if candidate_id == requested_id and candidate_replaced:
        markers.append("⚠️")
        semantic_reasons.append(
            f"Validation replaced this requested candidate; backend executed "
            f"{selected_id or 'none'}."
        )
    elif candidate_id == selected_id and fallback_used:
        markers.append("⚠️")
        semantic_reasons.append(fallback_reason or "Fallback used.")
    if candidate_id in suppressed_ids:
        markers.append("🔁")

    if candidate_id == requested_id and requested_below_top_score:
        original_reason = (
            str(reasoning_content or "").strip()
            or str(declared_rationale or "").strip()
        )
    else:
        original_reason = _as_dict(candidate.get("firstAction")).get("reason", "")
    return " ".join(
        part
        for part in [
            " ".join(markers),
            *semantic_reasons,
            str(original_reason or "").strip() or "No reason provided.",
        ]
        if part
    )


# ── Streamlit dashboard ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="Runner Dash",
    page_icon="🎮",
    layout="wide",
)

KEY_MAP = {
    37: "← Left",
    38: "↑ Up",
    39: "→ Right",
    40: "↓ Down",
    32: "Space (wait)",
    65: "A (dig-left)",
    83: "S (dig-right)",
}

_WORKSPACE_ROOT = os.path.abspath(os.path.dirname(__file__))


def _display_scalar(value, fallback="—"):
    if value is None or value == "":
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    if (
        not isinstance(value, (str, bool))
        and hasattr(value, "is_integer")
        and value.is_integer()
    ):
        return int(value)
    return value


def _resolve_folder(path: str) -> str:
    """Return an absolute path; relative paths are anchored to the workspace root."""
    p = os.path.expanduser(path.strip())
    if not os.path.isabs(p):
        p = os.path.join(_WORKSPACE_ROOT, p)
    return p


def _render_step_ascii_map(state_raw, selected_candidate):
    if has_coordinate_geometry(state_raw):
        st.code(
            render_ascii_map(state_raw, selected_candidate),
            language="text",
        )
    else:
        st.info("No coordinate geometry recorded for this step.")


def _queue_trace_jump(trace_id: str, step_index: int) -> None:
    nonce = _safe_int(st.session_state.get("trace_jump_nonce")) + 1
    st.session_state["trace_jump_nonce"] = nonce
    st.session_state["trace_jump"] = {
        "traceId": trace_id,
        "stepIndex": step_index,
        "nonce": nonce,
    }


# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("🎮 Agent Dash")
st.sidebar.markdown("---")

default_folder = os.environ.get("AGENT_DATA_DIR", "__data1")
folder = st.sidebar.text_input(
    "Data folder path",
    value=default_folder,
    help="Path to the folder containing recordings.json and agent-traces.json",
)

st.sidebar.markdown("---")

if st.sidebar.button("🔄 Reload data"):
    st.cache_data.clear()


@st.cache_data(show_spinner="Loading data…")
def cached_load(folder_path: str):
    return load_data(folder_path)


runs_df, steps_df, meta = cached_load(_resolve_folder(folder))

# Section 1 is newest-first. Keep this ordered frame as the selection source so
# a displayed row always resolves to the trace shown in Sections 2-3.
overview_runs_df = runs_df
if not runs_df.empty and "savedAt" in runs_df.columns:
    overview_runs_df = runs_df.sort_values(
        "savedAt", ascending=False, na_position="last"
    ).reset_index(drop=True)

# Sidebar summary
if not runs_df.empty:
    st.sidebar.markdown(f"**Runs loaded:** {len(runs_df)}")
    if meta.get("rec_updated_at"):
        st.sidebar.markdown(f"**Updated:** `{meta['rec_updated_at'][:19]}`")

if meta.get("errors"):
    for err in meta["errors"]:
        st.sidebar.warning(err)

if runs_df.empty and steps_df.empty:
    st.info(
        f"No data found in **{folder}**. "
        "Set the data folder in the sidebar to a path containing "
        "`recordings.json` and `agent-traces.json`."
    )
    st.stop()


# ── Global trace selection (shared by Sections 1-3) ──────────────────────────
# Resolved BEFORE Section 1 renders so the expander label can name the run.
# A ticked row lives in the table's widget state; a stale selection (e.g. after
# a data reload or folder change) is replaced by a deterministic default.
_valid_traces = []
if not overview_runs_df.empty and "traceId" in overview_runs_df.columns:
    _valid_traces = overview_runs_df["traceId"].tolist()
elif not steps_df.empty:
    _valid_traces = list(steps_df["traceId"].unique())

_sel_rows = []
_tbl = st.session_state.get("run_overview_table")
if _tbl is not None:
    try:
        _sel_rows = _tbl.selection.rows
    except AttributeError:
        _sel_rows = _tbl.get("selection", {}).get("rows", [])

if _sel_rows and _sel_rows[0] < len(_valid_traces):
    st.session_state["selected_trace"] = _valid_traces[_sel_rows[0]]

if st.session_state.get("selected_trace") not in _valid_traces:
    st.session_state["selected_trace"] = _valid_traces[0] if _valid_traces else None

selected_trace = st.session_state.get("selected_trace")

_inspect_label = ""
if selected_trace and not runs_df.empty and "traceId" in runs_df.columns:
    _match = runs_df[runs_df["traceId"] == selected_trace]
    if not _match.empty:
        _row = _match.iloc[0]
        _short = _row.get("traceId_short", str(selected_trace)[:8])
        _result = _row.get("result", "")
        _inspect_label = f" · inspecting `{_short}`" + (
            f" · {_result}" if _result else ""
        )


# ── Section 1: Run Overview ───────────────────────────────────────────────────
with st.expander(f"📋 Section 1 — Run Overview{_inspect_label}", expanded=True):
    if runs_df.empty:
        st.info("No recordings found.")
    else:
        display_cols = [
            "traceId_short",
            "savedAt",
            "result",
            "demoTime",
            "stepCount",
            "failureReason",
            "godMode",
            "averageCandidateCount",
            "lowerScoreRequestCount",
            "warningStepCount",
            "loopActiveSteps",
            "recordTime",
            "model",
        ]
        cols_present = [c for c in display_cols if c in overview_runs_df.columns]
        view = cast(pd.DataFrame, overview_runs_df.loc[:, cols_present].copy())
        # Display-only row number, kept separate from persisted trace IDs.
        view.insert(
            0,
            "#",
            pd.Series(range(1, len(view) + 1), index=view.index),
        )
        if "traceId_short" in view.columns and "source" in overview_runs_df.columns:
            view.loc[overview_runs_df["source"].eq("user"), "traceId_short"] = "user"
        if "traceId_short" in view.columns and "pinned" in overview_runs_df.columns:
            pinned_rows = overview_runs_df["pinned"].eq(True)
            view.loc[pinned_rows, "traceId_short"] = (
                view.loc[pinned_rows, "traceId_short"].astype(str) + " 📌"
            )
        if "failureReason" not in view.columns:
            view["failureReason"] = ""
        for row_index in view.index:
            markers = []
            if "result" in view.columns and view.at[row_index, "result"] == "success":
                markers.append("✅")
            if "godMode" in view.columns and view.at[row_index, "godMode"] == True:
                markers.append("★")
            reason = str(
                _display_scalar(view.at[row_index, "failureReason"], "")
            ).strip()
            view.at[row_index, "failureReason"] = " ".join(
                markers + ([reason] if reason else [])
            )
        view = view.drop(columns=["result", "godMode"], errors="ignore")
        view = view.rename(
            columns={
                "traceId_short": "traceId",
                "stepCount": "steps",
                "demoTime": "time",
                "failureReason": "reason",
                "averageCandidateCount": "🎯",
                "lowerScoreRequestCount": "✨",
                "warningStepCount": "⚠️",
                "loopActiveSteps": "🔁",
                "recordTime": "record",
            }
        )
        if "savedAt" in view.columns:
            saved_at = pd.to_datetime(view["savedAt"], utc=True, errors="coerce")
            view["savedAt"] = saved_at.map(
                lambda value: (
                    ""
                    if pd.isna(value)
                    else value.to_pydatetime().astimezone().strftime("%m-%d %H:%M")
                )
            )

        row_h, header_h = 35, 38
        st.dataframe(
            view,
            width="stretch",
            hide_index=True,
            height=header_h + row_h * len(view),
            column_config={
                "#": st.column_config.NumberColumn("#", width=30),
                "reason": st.column_config.TextColumn("reason", width=200),
                "🎯": st.column_config.NumberColumn("🎯", width=30, format="%.1f"),
                "✨": st.column_config.NumberColumn("✨", width=30),
                "⚠️": st.column_config.NumberColumn("⚠️", width=30),
                "🔁": st.column_config.NumberColumn("🔁", width=30),
                "model": st.column_config.TextColumn("model", width=100),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="run_overview_table",
        )
        st.caption(
            "🎯 average candidates/step · ✨ model requests · "
            "⚠️ replacement/suppression · 🔁 active loop steps"
        )


# ── Section 2: Trace Inspector ───────────────────────────────────────────────
_jump = _as_dict(st.session_state.get("trace_jump"))
_jump_matches = bool(
    selected_trace
    and _jump.get("traceId") == selected_trace
    and _safe_number(_jump.get("stepIndex")) is not None
)
_jump_step_index = _safe_int(_jump.get("stepIndex"), -1) if _jump_matches else -1
_jump_nonce = _safe_int(_jump.get("nonce")) if _jump_matches else 0
_s2_label = "🔍 Section 2 — Trace Inspector"
_s2_label += _inspect_label
_trace_stats_suffix = ""
if selected_trace and not steps_df.empty:
    _n = len(steps_df[steps_df["traceId"] == selected_trace])
    _d = ""
    if (
        not runs_df.empty
        and "traceId" in runs_df.columns
        and "demoTime" in runs_df.columns
    ):
        _row = runs_df[runs_df["traceId"] == selected_trace]
        if not _row.empty:
            _d = str(_row.iloc[0].get("demoTime") or "")
    _trace_stats_suffix = f" ({_n} steps"
    if _d:
        _trace_stats_suffix += f" · {_d}"
    _trace_stats_suffix += ")"
    _s2_label += _trace_stats_suffix

_s2_key = f"trace_inspector_jump_{_jump_nonce}" if _jump_matches else "trace_inspector"
with st.expander(_s2_label, expanded=_jump_matches, key=_s2_key):
    if steps_df.empty:
        st.info("No trace data found.")
    elif not selected_trace:
        st.info("Select a run above.")
    else:
        selected_trace = st.session_state.get("selected_trace")
        trace_steps = cast(
            pd.DataFrame,
            steps_df.loc[steps_df["traceId"] == selected_trace, :],
        ).sort_values(by="stepIndex")

        if trace_steps.empty:
            st.warning("No steps found for this trace.")
        else:
            n_steps = len(trace_steps)

            # Engine-recorded clock time (m:ss) at the START of each step.
            def _fmt_clock(total_seconds: int) -> str:
                m = int(total_seconds) // 60
                s = int(total_seconds) % 60
                return f"{m}:{s:02d}"

            _step_clocks = [
                _fmt_clock(int(_sr.get("state_tick") or 0) // 16)
                for _, _sr in trace_steps.iterrows()
            ]

            # Scrollable panel holding every step (no pagination)
            steps_panel = st.container(height=560)

            _jump_rendered = False
            for chosen_idx in range(n_steps):
                step_row = trace_steps.iloc[chosen_idx]
                keycode = _safe_int(step_row.get("action_keyCode"))
                key_label = KEY_MAP.get(keycode, f"key {keycode}")
                ticks = _safe_int(step_row.get("action_ticks"))

                sel_id = str(_display_scalar(step_row.get("selectedCandidateId"), "—"))
                requested_id = str(
                    _display_scalar(step_row.get("requestedCandidateId"), "")
                )
                cands = _as_dict_list(step_row.get("candidates_raw"))
                requested_below_top_score = bool(
                    step_row.get("event_lowerScoreRequest", False)
                )
                candidate_replaced = bool(
                    step_row.get("event_candidateReplaced", False)
                )
                suppressed_candidates = step_row.get("loop_suppressedCandidates", [])
                if not isinstance(suppressed_candidates, list):
                    suppressed_candidates = []
                candidate_suppressed = bool(
                    step_row.get("event_candidateSuppressed", False)
                )
                fallback_used = bool(step_row.get("fallbackUsed", False))
                loop_active = bool(step_row.get("loop_active", False))
                loop_type = step_row.get("loop_type") or "—"
                rx = step_row.get("runner_x")
                ry = step_row.get("runner_y")
                gold = step_row.get("gold_remaining")

                display_step = int(step_row["stepIndex"]) + 1
                stat_bits = [
                    f" **`{key_label}`**",
                    f"{ticks}t",
                    f"pos ({rx}, {ry})",
                    f"gold {gold}",
                    f"risk {step_row.get('risk_level', '—')}",
                ]
                if loop_active:
                    stat_bits.append(f"`loop {loop_type}`")
                if candidate_replaced:
                    stat_bits.append("replaced")
                if candidate_suppressed:
                    stat_bits.append("suppressed")
                if fallback_used:
                    stat_bits.append("fallback")
                if requested_below_top_score:
                    stat_bits.append("lower-score")

                clock_str = _step_clocks[chosen_idx]
                step_label = (
                    f"Step {display_step}"
                    + " · ".join(stat_bits)
                    + f" — `{sel_id}` ({clock_str})"
                )
                event_icons = []
                if loop_active:
                    event_icons.append("🔁")
                if bool(step_row.get("event_warning", False)):
                    event_icons.append("⚠️")
                if requested_below_top_score:
                    event_icons.append("✨")
                if event_icons:
                    step_label = f"{' '.join(event_icons)} {step_label}"

                _is_jump_target = bool(
                    _jump_matches
                    and _safe_int(step_row.get("stepIndex"), -1) == _jump_step_index
                )
                _step_key = (
                    f"trace_jump_target_{_jump_nonce}"
                    if _is_jump_target
                    else f"trace_step_{display_step}"
                )
                with steps_panel.expander(
                    step_label,
                    expanded=_is_jump_target,
                    key=_step_key,
                ):
                    fallback_reason = str(
                        _display_scalar(step_row.get("fallbackReason"), "")
                    ).strip()

                    state_raw = step_row.get("state_raw")
                    if not isinstance(state_raw, dict):
                        state_raw = {}
                    selected_candidate = find_selected_candidate(cands, sel_id)
                    safety_rejections = _as_dict_list(
                        step_row.get("candidateSafetyRejections")
                    )
                    if cands or suppressed_candidates or safety_rejections:
                        map_col, candidates_col = st.columns([1, 3])
                        with map_col:
                            _render_step_ascii_map(state_raw, selected_candidate)
                        with candidates_col:
                            suppressed_ids = {
                                str(item.get("id") or "")
                                for item in suppressed_candidates
                                if isinstance(item, dict) and item.get("id")
                            }
                            display_candidates = list(cands)
                            displayed_ids = {
                                str(candidate.get("id") or "")
                                for candidate in display_candidates
                                if isinstance(candidate, dict)
                            }
                            # Loop metadata can suppress a candidate that was
                            # not included in the backend's evaluated list.
                            for suppressed_candidate in suppressed_candidates:
                                if not isinstance(suppressed_candidate, dict):
                                    continue
                                suppressed_id = str(
                                    suppressed_candidate.get("id") or ""
                                )
                                if suppressed_id and suppressed_id not in displayed_ids:
                                    display_candidates.append(
                                        {
                                            "id": suppressed_id,
                                            "kind": suppressed_candidate.get(
                                                "kind", "suppressed"
                                            ),
                                            "score": None,
                                            "firstAction": {
                                                "reason": suppressed_candidate.get(
                                                    "reason", ""
                                                )
                                            },
                                            "_suppressed_only": True,
                                        }
                                    )
                            for safety_rejection in safety_rejections:
                                display_candidates.append(
                                    {
                                        "id": safety_rejection.get("candidateId"),
                                        "kind": safety_rejection.get(
                                            "kind", "safety_rejection"
                                        ),
                                        "score": None,
                                        "_safety_rejection": True,
                                        "_safety_rejection_detail": safety_rejection.get(
                                            "detail", ""
                                        ),
                                    }
                                )
                            cand_df = pd.DataFrame(
                                [
                                    {
                                        "candidate": (
                                            "✅ "
                                            if str(c.get("id") or "") == sel_id
                                            else ""
                                        )
                                        + str(c.get("id") or ""),
                                        "score": (
                                            c.get("score")
                                            if isinstance(c.get("score"), (int, float))
                                            and not c.get("_suppressed_only")
                                            else None
                                        ),
                                        "reason": (
                                            (
                                                "⚠️ "
                                                + str(
                                                    c.get(
                                                        "_safety_rejection_detail",
                                                        "Safety rejection",
                                                    )
                                                    or "Safety rejection"
                                                )
                                            )
                                            if c.get("_safety_rejection")
                                            else _candidate_reason(
                                                c,
                                                selected_id=sel_id,
                                                requested_id=requested_id,
                                                requested_below_top_score=requested_below_top_score,
                                                candidate_replaced=candidate_replaced,
                                                fallback_used=fallback_used,
                                                fallback_reason=fallback_reason,
                                                reasoning_content=str(
                                                    _display_scalar(
                                                        step_row.get(
                                                            "reasoningContent"
                                                        ),
                                                        "",
                                                    )
                                                ),
                                                declared_rationale=str(
                                                    _display_scalar(
                                                        step_row.get(
                                                            "declaredRationale"
                                                        ),
                                                        "",
                                                    )
                                                ),
                                                suppressed_ids=suppressed_ids,
                                            )
                                        ),
                                    }
                                    for c in display_candidates
                                ]
                            )
                            st.dataframe(
                                cand_df,
                                width="stretch",
                                hide_index=True,
                                column_config={
                                    "candidate": st.column_config.TextColumn(
                                        "candidate", width=150
                                    ),
                                    "score": st.column_config.NumberColumn(
                                        "score", width=50, format="%.0f"
                                    ),
                                    "reason": st.column_config.TextColumn(
                                        "reason", width=400
                                    ),
                                },
                            )
                    else:
                        _render_step_ascii_map(state_raw, selected_candidate)
                _jump_rendered = _jump_rendered or _is_jump_target

            if _jump_rendered:
                steps_panel.html(
                    f"""
                    <script>
                    requestAnimationFrame(() => {{
                      document.querySelector(
                        ".st-key-trace_jump_target_{_jump_nonce}"
                      )?.scrollIntoView({{behavior: "smooth", block: "center"}});
                    }});
                    </script>
                    """,
                    unsafe_allow_javascript=True,
                )
            if _jump_matches:
                st.session_state.pop("trace_jump", None)


# ── Section 3: Run Signals ───────────────────────────────────────────────────
with st.expander(
    f"📡 Section 3 — Run Signals{_inspect_label}{_trace_stats_suffix}",
    expanded=False,
):
    if steps_df.empty:
        st.info("No trace data available.")
    elif not selected_trace:
        st.info("Select a run above.")
    else:
        selected_trace = st.session_state.get("selected_trace")
        signal_steps = cast(
            pd.DataFrame,
            steps_df.loc[steps_df["traceId"] == selected_trace, :],
        )
        if signal_steps.empty:
            st.info("No steps found for this trace.")
        else:
            choice, run_signals = _build_run_signals(signal_steps)
            choice_text = _candidates_text(choice)

            run_row = runs_df[runs_df["traceId"] == selected_trace]
            result = ""
            if not run_row.empty:
                result = str(run_row.iloc[0].get("result") or "")
            ordered_signal_steps = [
                row for _, row in signal_steps.sort_values("stepIndex").iterrows()
            ]
            elapsed = (
                _format_tick_duration(
                    _range_ticks(ordered_signal_steps, 0, len(ordered_signal_steps) - 1)
                )
                if ordered_signal_steps
                else "duration unavailable"
            )
            event_lines = [_signal_line(signal) for signal in run_signals]
            copy_lines = [
                "RUN CONTEXT",
                f"trace: {selected_trace}",
                f"result: {result or 'unknown'}",
                f"steps: {choice['steps']}",
                f"elapsed: {elapsed}",
                choice_text,
                "EVENTS",
                *(event_lines or ["No diagnostic run signals found."]),
            ]
            copy_text = "\n".join(copy_lines)
            summary_col, copy_col = st.columns(
                [6.4, 0.8],
                vertical_alignment="center",
            )
            summary_col.caption(choice_text)
            copy_col.html(
                f"""
                <button id="run-signals-copy" type="button" style="width:100%">
                  Copy
                </button>
                <textarea id="run-signals-copy-text" style="display:none">{
                    escape(copy_text)
                }</textarea>
                <script>
                (() => {{
                  const button = document.getElementById("run-signals-copy");
                  const source = document.getElementById("run-signals-copy-text");
                  button.addEventListener("click", async () => {{
                    if (navigator.clipboard) {{
                      await navigator.clipboard.writeText(source.value);
                    }} else {{
                      source.style.display = "block";
                      source.select();
                      document.execCommand("copy");
                      source.style.display = "none";
                    }}
                    button.textContent = "Copied";
                    setTimeout(() => {{ button.textContent = "Copy"; }}, 1200);
                  }});
                }})();
                </script>
                """,
                unsafe_allow_javascript=True,
            )

            if not run_signals:
                st.info("No diagnostic run signals found.")
            else:
                for signal_index, signal in enumerate(run_signals):
                    event_col, action_col = st.columns(
                        [6.4, 0.8],
                        vertical_alignment="center",
                    )
                    event_col.markdown(_signal_line(signal, markdown=True))
                    action_col.button(
                        f"Step {int(signal['stepIndex']) + 1}",
                        key=f"run_signal_{signal_index}",
                        on_click=_queue_trace_jump,
                        args=(str(selected_trace), int(signal["stepIndex"])),
                        width="stretch",
                    )
