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
            "stepCount",
            "demoTime",
            "failureReason",
            "godMode",
            "show_score",
            "recordTime",
            "model",
        ]
        cols_present = [c for c in display_cols if c in overview_runs_df.columns]
        view = overview_runs_df[cols_present].copy()
        view = view.rename(
            columns={
                "traceId_short": "traceId",
                "stepCount": "steps",
                "demoTime": "time",
                "failureReason": "reason",
                "godMode": "god",
                "show_score": "score",
                "recordTime": "record",
            }
        )
        if "savedAt" in view.columns:
            saved_at = pd.to_datetime(view["savedAt"], utc=True, errors="coerce")
            view["savedAt"] = saved_at.map(
                lambda value: ""
                if pd.isna(value)
                else value.to_pydatetime().astimezone().strftime("%m-%d %H:%M:%S")
            )

        row_h, header_h = 35, 38
        st.dataframe(
            view,
            width="stretch",
            hide_index=True,
            height=header_h + row_h * len(view),
            column_config={
                "god": st.column_config.CheckboxColumn("god"),
                "score": st.column_config.CheckboxColumn("score"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="run_overview_table",
        )


def _stall_stories(trace_df: pd.DataFrame) -> list[tuple[int, str]]:
    """Return (display_step, narrative paragraph) for confirmed stalls."""
    stalled = trace_df[trace_df["stall_stalled"].fillna(False)].sort_values(
        "stepIndex"
    )
    if stalled.empty:
        return []

    all_steps = trace_df.sort_values("stepIndex").reset_index(drop=True)
    stories = []

    for _, row in stalled.iterrows():
        sidx = int(row["stepIndex"])
        display_step = sidx + 1

        rx = row.get("runner_x")
        ry = row.get("runner_y")
        pos_str = f"({rx}, {ry})" if rx is not None else "unknown position"

        stype = row.get("stall_type") or "unknown pattern"
        sev = row.get("stall_severity") or "unknown"
        blocked = row.get("stall_blockedKinds") or ""
        blocked_str = (
            f" The stall supervisor blocked: **{blocked}**." if blocked else ""
        )

        sel_kind = row.get("selectedCandidateKind") or "unknown"
        sel_id = row.get("selectedCandidateId") or ""
        reason = row.get("action_reason") or ""
        keycode = int(row.get("action_keyCode") or 0)
        action_str = KEY_MAP.get(keycode, f"key {keycode}")

        retry = row.get("stall_retryAttempted", False)
        fallback = row.get("fallbackUsed", False)
        fallback_reason = row.get("fallbackReason") or ""

        # What happened next?
        next_rows = all_steps[all_steps["stepIndex"] > sidx].head(1)
        if not next_rows.empty:
            nr = next_rows.iloc[0]
            nkc = int(nr.get("action_keyCode") or 0)
            next_action = KEY_MAP.get(nkc, f"key {nkc}")
            next_kind = nr.get("selectedCandidateKind") or "unknown"
            next_still_stalled = nr.get("stall_stalled", False)
            next_str = (
                f"On the next step the agent chose **{next_action}** via `{next_kind}`"
                + (" — still stalled." if next_still_stalled else " — stall cleared.")
            )
        else:
            next_str = "This was the final step."

        response_parts = []
        if retry:
            response_parts.append("retried the LLM call")
        if fallback:
            fb_detail = f" ({fallback_reason})" if fallback_reason else ""
            response_parts.append(f"used a fallback candidate{fb_detail}")
        response_str = (
            "The agent " + " and ".join(response_parts) + "."
            if response_parts
            else "The agent proceeded without retry or fallback."
        )

        para = (
            f"🔴 **Stall** — severity `{sev}`, pattern `{stype}`\n\n"
            f"The runner was at {pos_str}.{blocked_str} "
            f"The agent selected **{action_str}** via `{sel_kind}`"
            + (f" (`{sel_id}`)" if sel_id else "")
            + (f': *"{reason}"*' if reason else "")
            + f". {response_str} {next_str}"
        )
        stories.append((display_step, para))

    return stories


def _observation_text(row) -> str:
    """Summarize trace-only pre-stall observations without implying enforcement."""
    parts = []
    if row.get("observation_shortHorizontalOscillation", False):
        parts.append("short horizontal oscillation")
    if row.get("observation_repeatedCandidate", False):
        candidate_id = row.get("observation_repeatedCandidateId") or "unknown candidate"
        streak = int(row.get("observation_sameCandidateStreak") or 0)
        progress = "progressing" if row.get("observation_targetProgress", False) else "not progressing"
        reached = ", target reached" if row.get("observation_targetReached", False) else ""
        parts.append(f"repeated `{candidate_id}` ×{streak} ({progress}{reached})")
    return "; ".join(parts)


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
            # Build stall index for this trace
            stall_set = set(
                int(r["stepIndex"])
                for _, r in trace_steps.iterrows()
                if r.get("stall_stalled", False)
            )
            stall_indices = sorted(stall_set)

            def _step_label(i, row):
                base = f"Step {int(row['stepIndex']) + 1}"
                if int(row["stepIndex"]) in stall_set:
                    return f"⚠️ {base} [stalled]"
                return base

            step_labels = [
                _step_label(i, r) for i, (_, r) in enumerate(trace_steps.iterrows())
            ]
            n_steps = len(step_labels)

            # Stall stories, keyed by display step, rendered inline in each
            # stalled step's expander (left column, under Reasoning).
            stall_stories = dict(_stall_stories(trace_steps))

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

                sel_kind = step_row.get("selectedCandidateKind") or "—"
                sel_id = step_row.get("selectedCandidateId", "—")
                stall_sev = step_row.get("stall_severity") or "none"
                stall_type = step_row.get("stall_type") or "—"
                fallback = "✓" if step_row.get("fallbackUsed", False) else "✗"
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
                if stall_sev not in ("none", ""):
                    stat_bits.append(
                        f"stall {stall_sev}"
                        + (f" ({stall_type})" if stall_type != "—" else "")
                    )
                observation_text = _observation_text(step_row)
                if observation_text:
                    stat_bits.append("observed")
                if step_row.get("fallbackUsed", False):
                    stat_bits.append("fallback")
                if not step_row.get("valid_actionGuardSafe", True):
                    stat_bits.append("guard-unsafe")

                clock_str = _step_clocks[chosen_idx]
                step_label = (
                    f"Step {display_step}" + " · ".join(stat_bits) + f" — `{sel_id}` ({clock_str})"
                )
                if stall_sev not in ("none", ""):
                    step_label = f"⚠️ {step_label}"

                with steps_panel.expander(step_label, expanded=False):
                    details_col, candidates_col = st.columns([30, 70])

                    with details_col:
                        choice_reason = step_row.get("valid_choiceReason", "")
                        if choice_reason:
                            st.markdown(f"**Reasoning:** {choice_reason}")
                        if display_step in stall_stories:
                            st.markdown(stall_stories[display_step])
                        if observation_text:
                            st.markdown(f"**Trace observation:** {observation_text}")
                        if not step_row.get("valid_actionGuardSafe", True):
                            st.error("The requested action failed backend guard-safety validation.")

                    with candidates_col:
                        cands = step_row.get("candidates_raw", [])
                        if cands:
                            cand_df = pd.DataFrame(
                                [
                                    {
                                        "candidate": c.get("kind", "")
                                        + (
                                            "\u00a0\u00a0✅"
                                            if c.get("id") == sel_id
                                            else ""
                                        ),
                                        "score": c.get("score", 0),
                                        "goal": c.get("goal", ""),
                                    }
                                    for c in sorted(
                                        cands,
                                        key=lambda x: x.get("score", 0),
                                        reverse=True,
                                    )
                                ]
                            )
                            st.dataframe(cand_df, width="stretch", hide_index=True)


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
