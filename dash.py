import streamlit as st
import pandas as pd
import os

from loader import load_data, get_candidates_df

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
            view.loc[
                overview_runs_df["source"].eq("user"), "traceId_short"
            ] = "user"
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
            "🎯 average candidates/step · ✨ lower-score request · "
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

            # Cumulative elapsed clock time (m:ss) at the START of each step.
            # Each step's action_ticks is how long *that* step's action ran,
            # so the clock at step N = sum of ticks for steps 0..N-1 / 16 fps.
            def _fmt_clock(total_seconds: int) -> str:
                m = int(total_seconds) // 60
                s = int(total_seconds) % 60
                return f"{m}:{s:02d}"

            _cumulative_ticks = 0
            _step_clocks: list[str] = []
            for _, _sr in trace_steps.iterrows():
                _step_clocks.append(_fmt_clock(_cumulative_ticks // 16))
                _cumulative_ticks += int(_sr.get("action_ticks") or 0)

            # Scrollable panel holding every step (no pagination)
            steps_panel = st.container(height=560)

            for chosen_idx in range(n_steps):
                step_row = trace_steps.iloc[chosen_idx]
                keycode = int(step_row.get("action_keyCode") or 0)
                key_label = KEY_MAP.get(keycode, f"key {keycode}")
                ticks = int(step_row.get("action_ticks") or 0)

                sel_id = str(
                    _display_scalar(step_row.get("selectedCandidateId"), "—")
                )
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
                suppressed_candidates = step_row.get(
                    "loop_suppressedCandidates", []
                )
                if not isinstance(suppressed_candidates, list):
                    suppressed_candidates = []
                candidate_suppressed = bool(
                    step_row.get("event_candidateSuppressed", False)
                )
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
                    stat_bits.append("candidate replaced")
                if candidate_suppressed:
                    stat_bits.append("candidate suppressed")
                if requested_below_top_score:
                    stat_bits.append("lower-score request")

                clock_str = _step_clocks[chosen_idx]
                step_label = (
                    f"Step {display_step}"
                    + " · ".join(stat_bits)
                    + f" — `{sel_id}` ({clock_str})"
                )
                event_icons = []
                if loop_active:
                    event_icons.append("🔁")
                if candidate_replaced or candidate_suppressed:
                    event_icons.append("⚠️")
                if requested_below_top_score:
                    event_icons.append("✨")
                if event_icons:
                    step_label = f"{' '.join(event_icons)} {step_label}"

                with steps_panel.expander(step_label, expanded=False):
                    fallback_used = bool(step_row.get("fallbackUsed", False))
                    if fallback_used or (requested_id and requested_id != sel_id):
                        replacement = f"**Validation:** LLM requested `{requested_id or '—'}`"
                        replacement += f" → backend executed `{sel_id}`"
                        fallback_reason = str(
                            _display_scalar(step_row.get("fallbackReason"), "")
                        )
                        if fallback_reason:
                            replacement += f" — {fallback_reason}"
                        st.markdown(replacement)

                    suppressed_lines = []
                    for suppressed_candidate in suppressed_candidates:
                        if not isinstance(suppressed_candidate, dict):
                            continue
                        suppressed_id = str(suppressed_candidate.get("id") or "")
                        if not suppressed_id:
                            continue
                        suppressed_reason = str(
                            suppressed_candidate.get("reason") or ""
                        ).strip()
                        detail = f"`{suppressed_id}`"
                        if suppressed_reason:
                            detail += f" — {suppressed_reason}"
                        suppressed_lines.append(detail)

                    if len(suppressed_lines) == 1:
                        st.markdown(f"**Suppressed:** {suppressed_lines[0]}")
                    elif suppressed_lines:
                        st.markdown(
                            "**Suppressed:**\n\n"
                            + "\n".join(f"- {line}" for line in suppressed_lines)
                        )

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
                    after_risk = _display_scalar(
                        step_row.get("after_risk_level"), None
                    )
                    if after_risk is not None:
                        outcome_bits.append(f"risk {before_risk} → {after_risk}")
                    before_state = _display_scalar(step_row.get("game_state"), None)
                    after_state = _display_scalar(step_row.get("after_game_state"), None)
                    if after_state is not None and after_state != before_state:
                        outcome_bits.append(f"state {before_state or '—'} → {after_state}")
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
                    if cands:
                        outcome_col, candidates_col = st.columns([1, 3])
                        with outcome_col:
                            st.markdown("**Outcome:** " + " · ".join(outcome_bits))
                        with candidates_col:
                            cand_df = pd.DataFrame(
                                [
                                    {
                                        "▶": c.get("id") == sel_id,
                                        "candidate": c.get("id", ""),
                                        "score": c.get("score", 0),
                                        "reason": (c.get("firstAction") or {}).get(
                                            "reason", ""
                                        ),
                                    }
                                    for c in cands
                                ]
                            )
                            st.dataframe(
                                cand_df,
                                width="stretch",
                                hide_index=True,
                                column_config={
                                    "▶": st.column_config.CheckboxColumn(
                                        "▶", width=30
                                    ),
                                    "candidate": st.column_config.TextColumn(
                                        "candidate", width=150
                                    ),
                                    "score": st.column_config.NumberColumn(
                                        "score", width=50
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
