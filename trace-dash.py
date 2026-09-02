import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st


# ── Data loading and DataFrame builders ─────────────────────────────────────
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
    fallback_used = bool(validation.get("fallbackUsed", False))
    return {
        "lower_score_request": bool(
            requested_score is not None
            and candidate_scores
            and requested_score < max(candidate_scores)
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
                    "state_tick": state.get("tick"),
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


def _candidate_reason(
    candidate: dict,
    *,
    selected_id: str,
    requested_id: str,
    requested_below_top_score: bool,
    candidate_replaced: bool,
    fallback_used: bool,
    fallback_reason: str,
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

    original_reason = (candidate.get("firstAction") or {}).get("reason", "")
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

# Label suffix: which run Sections 2-3 are inspecting (defaults to the first
# run on fresh load, before any row has been ticked).
_inspect_label = ""
if selected_trace and not runs_df.empty and "traceId" in runs_df.columns:
    _match = runs_df[runs_df["traceId"] == selected_trace]
    if not _match.empty:
        _row = _match.iloc[0]
        _short = _row.get("traceId_short", str(selected_trace)[:8])
        _result = _row.get("result", "")
        _inspect_label = (
            f" · inspecting `{_short}`"
            + (f" · {_result}" if _result else "")
            + ("" if _sel_rows else " (default)")
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
            "activeLoopCount",
            "recordTime",
            "model",
        ]
        cols_present = [c for c in display_cols if c in overview_runs_df.columns]
        view = overview_runs_df[cols_present].copy()
        # Display-only row number, kept separate from persisted trace IDs.
        view.insert(0, "#", range(1, len(view) + 1))
        if "traceId_short" in view.columns and "source" in overview_runs_df.columns:
            view.loc[overview_runs_df["source"].eq("user"), "traceId_short"] = "user"
        if "traceId_short" in view.columns and "pinned" in overview_runs_df.columns:
            pinned_rows = overview_runs_df["pinned"].eq(True)
            view.loc[pinned_rows, "traceId_short"] = (
                view.loc[pinned_rows, "traceId_short"].astype(str) + " 📌"
            )
        if "result" in view.columns:
            view["result"] = view["result"].eq("success")
        view = view.rename(
            columns={
                "traceId_short": "traceId",
                "result": "▶",
                "stepCount": "steps",
                "demoTime": "time",
                "failureReason": "reason",
                "godMode": "★",
                "averageCandidateCount": "🎯",
                "lowerScoreRequestCount": "✨",
                "warningStepCount": "⚠️",
                "activeLoopCount": "🔁",
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
                "▶": st.column_config.CheckboxColumn("▶", width=30),
                "reason": st.column_config.TextColumn("reason", width=200),
                "★": st.column_config.CheckboxColumn("★", width=30),
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
            "🎯 average candidates/step · ✨ model selection · "
            "⚠️ replacement/suppression · 🔁 active loop"
        )


# ── Section 2: Trace Inspector ───────────────────────────────────────────────
_s2_label = "🔍 Section 2 — Trace Inspector"
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
    _suffix = f" ({_n} steps"
    if _d:
        _suffix += f" · {_d}"
    _suffix += ")"
    _s2_label += _suffix

with st.expander(_s2_label, expanded=False):
    if steps_df.empty:
        st.info("No trace data found.")
    elif not selected_trace:
        st.info("Select a run above.")
    else:
        selected_trace = st.session_state.get("selected_trace")
        trace_steps = steps_df[steps_df["traceId"] == selected_trace].sort_values(
            "stepIndex"
        )

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

            for chosen_idx in range(n_steps):
                step_row = trace_steps.iloc[chosen_idx]
                keycode = int(step_row.get("action_keyCode") or 0)
                key_label = KEY_MAP.get(keycode, f"key {keycode}")
                ticks = int(step_row.get("action_ticks") or 0)

                sel_id = str(_display_scalar(step_row.get("selectedCandidateId"), "—"))
                requested_id = str(
                    _display_scalar(step_row.get("requestedCandidateId"), "")
                )
                cands = step_row.get("candidates_raw", [])
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

                with steps_panel.expander(step_label, expanded=False):
                    fallback_reason = str(
                        _display_scalar(step_row.get("fallbackReason"), "")
                    ).strip()

                    before_pos = f"({rx}, {ry})"
                    after_x = _display_scalar(step_row.get("after_runner_x"), None)
                    after_y = _display_scalar(step_row.get("after_runner_y"), None)
                    outcome_bits = [
                        (
                            f"pos {before_pos} → ({after_x}, {after_y})"
                            if after_x is not None and after_y is not None
                            else f"pos {before_pos} → pending"
                        )
                    ]
                    after_gold = _display_scalar(
                        step_row.get("after_gold_remaining"), None
                    )
                    if after_gold is not None:
                        outcome_bits.append(
                            f"gold {_display_scalar(gold)} → {after_gold}"
                        )
                    before_risk = _display_scalar(step_row.get("risk_level"))
                    after_risk = _display_scalar(step_row.get("after_risk_level"), None)
                    if after_risk is not None:
                        outcome_bits.append(f"risk {before_risk} → {after_risk}")
                    before_state = _display_scalar(step_row.get("game_state"), None)
                    after_state = _display_scalar(
                        step_row.get("after_game_state"), None
                    )
                    if after_state is not None and after_state != before_state:
                        outcome_bits.append(
                            f"state {before_state or '—'} → {after_state}"
                        )
                    terminal_result = str(
                        _display_scalar(step_row.get("terminal_result"), "")
                    )
                    if terminal_result:
                        terminal_reason = str(
                            _display_scalar(step_row.get("terminal_reason"), "")
                        )
                        terminal = f"result {terminal_result}"
                        if terminal_reason:
                            terminal += f" ({terminal_reason})"
                        outcome_bits.append(terminal)
                    if cands or suppressed_candidates:
                        outcome_col, candidates_col = st.columns([1, 3])
                        with outcome_col:
                            st.markdown("**Outcome:** " + " · ".join(outcome_bits))
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
                            cand_df = pd.DataFrame(
                                [
                                    {
                                        "▶": c.get("id") == sel_id,
                                        "candidate": c.get("id", ""),
                                        "score": (
                                            c.get("score")
                                            if isinstance(c.get("score"), (int, float))
                                            and not c.get("_suppressed_only")
                                            else None
                                        ),
                                        "reason": _candidate_reason(
                                            c,
                                            selected_id=sel_id,
                                            requested_id=requested_id,
                                            requested_below_top_score=requested_below_top_score,
                                            candidate_replaced=candidate_replaced,
                                            fallback_used=fallback_used,
                                            fallback_reason=fallback_reason,
                                            suppressed_ids=suppressed_ids,
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
                                    "▶": st.column_config.CheckboxColumn("▶", width=30),
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
                        st.markdown("**Outcome:** " + " · ".join(outcome_bits))


# ── Section 3: Candidate Score Breakdown ─────────────────────────────────────
with st.expander("📊 Section 3 — Candidate Score Breakdown", expanded=False):
    if steps_df.empty:
        st.info("No trace data available.")
    elif not selected_trace:
        st.info("Select a run above.")
    else:
        selected_trace = st.session_state.get("selected_trace")
        s4_steps = steps_df[steps_df["traceId"] == selected_trace]

        cands_df = get_candidates_df(s4_steps)

        if cands_df.empty:
            st.info("No candidate data available.")
        else:
            # Win rate per kind
            kind_stats = (
                cands_df.groupby("kind")
                .agg(
                    total=("kind", "count"),
                    selected=("selected", "sum"),
                    avg_score=("score", "mean"),
                )
                .reset_index()
            )
            kind_stats["win_rate_%"] = (
                kind_stats["selected"] / kind_stats["total"] * 100
            ).round(1)
            kind_stats["avg_score"] = kind_stats["avg_score"].round(1)
            kind_stats = kind_stats.sort_values("win_rate_%", ascending=False)
            kind_stats = kind_stats.rename(columns={"kind": "candidate"})
            st.dataframe(kind_stats, width="stretch", hide_index=True)
