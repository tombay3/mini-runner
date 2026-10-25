from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AGENT_MAX_TICKS
from .scoring import (
    LOW_RISK_GUARD_CLEARANCE_BONUS,
    MEDIUM_CROSS_ROW_CLEARANCE_PENALTY,
    SAME_BURST_OPPOSITE_LADDER_GOLD_BONUS,
    RECENT_LADDER_RETURN_PENALTY,
    ScoreSpec,
    caller_score,
    fixed_score,
    ladder_alignment_score as ladder_alignment_score_spec,
)
from .reasoning_tools import (
    DIG_LEFT_KEYCODE,
    DIG_RIGHT_KEYCODE,
    DOWN_KEYCODE,
    LEFT_KEYCODE,
    RIGHT_KEYCODE,
    STOP_KEYCODE,
    UP_KEYCODE,
    assess_guard_risk,
    assess_emergency_hole_escape_threat,
    find_nearest_gold_candidates,
    find_row_ladders,
    get_dig_affordance,
    get_ladder_affordance,
    get_movement_affordance,
    get_route_access_affordance,
    ladder_column_reaches_top,
)
from .loop_tools import (
    build_loop_report,
    candidate_target,
    candidate_suppression_reason,
    predicted_horizontal_return_target,
    record_suppressed_candidate,
)


ACTION_NAMES = {
    STOP_KEYCODE: "stop",
    LEFT_KEYCODE: "left",
    RIGHT_KEYCODE: "right",
    UP_KEYCODE: "up",
    DOWN_KEYCODE: "down",
    DIG_LEFT_KEYCODE: "dig_left",
    DIG_RIGHT_KEYCODE: "dig_right",
}

CANDIDATE_LANES = json.loads(
    Path(__file__).with_name("candidate_lanes.json").read_text(encoding="utf-8")
)


def candidate_lane(kind: str | None) -> str:
    return CANDIDATE_LANES.get(kind or "", "other")


GUARD_PRESSURE_RISKS = {"medium", "high", "critical"}
LOW_RISK_LOOP_ESCAPE_MAX_DISTANCE = 7
GUARD_CLEARANCE_TICKS_PER_CELL = 8

MEDIUM_CROSS_ROW_CLIMB_MAX_TICKS = 6
MEDIUM_CROSS_ROW_CLIMB_MIN_HORIZONTAL_CLEARANCE = 3

PROSPECTIVE_HORIZONTAL_KINDS = {
    "align_ladder",
    "collect_same_row_gold",
    "exit_ladder_route",
    "low_risk_horizontal_progress",
    "retreat_from_guard",
}

LEGACY_SUBTILE_STEP = 8

DIG_KEYCODES = {
    "dig_left": DIG_LEFT_KEYCODE,
    "dig_right": DIG_RIGHT_KEYCODE,
}


LEFT_RETREAT_ID = "retreat_from_guard_same_column_left"
RIGHT_RETREAT_ID = "retreat_from_guard_same_column_right"
_GUARD_VECTORS = {
    "left": (-1, 0), "right": (1, 0), "up": (0, -1),
    "down": (0, 1), "fall": (0, 1),
}


def _coordinate(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _clearance_forecast(
    action: dict[str, Any], analysis: dict[str, Any], ticks_per_cell: int,
) -> dict[str, Any] | None:
    """Reuse the tile-only constant-speed proxy; this does not certify safety."""
    runner = analysis.get("runner") or {}
    x, y = _coordinate(runner.get("x")), _coordinate(runner.get("y"))
    if x is None or y is None:
        return None
    guards = []
    for guard in (analysis.get("risk") or {}).get("guards") or []:
        gx, gy = _coordinate(guard.get("x")), _coordinate(guard.get("y"))
        if guard.get("motion") != "in_hole" and gx is not None and gy is not None:
            guards.append((guard, gx, gy))
    if not guards:
        return None
    initial = min(abs(gx - x) + abs(gy - y) for _, gx, gy in guards)
    projected = []
    direction = {37: -1, 39: 1}[action["keyCode"]]
    for tick in range(1, action["ticks"] + 1):
        progress = tick / ticks_per_cell
        projected.append(min(
            abs(gx + _GUARD_VECTORS.get(g.get("motion"), (0, 0))[0] * progress - (x + direction * progress))
            + abs(gy + _GUARD_VECTORS.get(g.get("motion"), (0, 0))[1] * progress - y)
            for g, gx, gy in guards
        ))
    return {"initialMinimum": initial, "minimumDuringBurst": min(projected), "endMinimum": projected[-1]}


def rank_same_column_retreat_tie(
    candidates: list[dict[str, Any]], analysis: dict[str, Any], *, ticks_per_cell: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Reorder only an exposed equal-highest-score left/right retreat pair."""
    result = list(candidates)
    risk = analysis.get("risk") or {}
    primary = risk.get("pressureGuard") or {}
    if (
        analysis.get("godMode") or risk.get("risk") not in {"medium", "high", "critical"}
        or primary.get("relativeX") != "same" or primary.get("relativeY") not in {"above", "below"}
    ):
        return result, None
    by_id = {c["id"]: c for c in candidates}
    if LEFT_RETREAT_ID not in by_id or RIGHT_RETREAT_ID not in by_id:
        return result, None
    left, right = by_id[LEFT_RETREAT_ID], by_id[RIGHT_RETREAT_ID]
    if left["score"] != right["score"] or left["score"] != max(c["score"] for c in candidates):
        return result, None
    a, b = left["firstAction"], right["firstAction"]
    if (
        a["keyCode"] != 37 or b["keyCode"] != 39 or a["ticks"] != b["ticks"]
        or not isinstance(a["ticks"], int) or a["ticks"] < 1
    ):
        return result, None
    lf, rf = _clearance_forecast(a, analysis, ticks_per_cell), _clearance_forecast(b, analysis, ticks_per_cell)
    if lf is None or rf is None:
        return result, None
    winner = None
    if lf["minimumDuringBurst"] > rf["minimumDuringBurst"] and lf["endMinimum"] > rf["endMinimum"]:
        winner = LEFT_RETREAT_ID
    if rf["minimumDuringBurst"] > lf["minimumDuringBurst"] and rf["endMinimum"] > lf["endMinimum"]:
        winner = RIGHT_RETREAT_ID
    if winner is None:
        return result, None
    positions = [i for i, c in enumerate(candidates) if c["id"] in {LEFT_RETREAT_ID, RIGHT_RETREAT_ID}]
    ordered = [by_id[winner], by_id[RIGHT_RETREAT_ID if winner == LEFT_RETREAT_ID else LEFT_RETREAT_ID]]
    for i, c in zip(positions, ordered):
        result[i] = c
    return result, {
        "policy": "same_column_retreat_clearance_tie", "winnerId": winner,
        "leftForecast": lf, "rightForecast": rf, "ticks": a["ticks"], "ticksPerCell": ticks_per_cell,
        "orderChanged": [c["id"] for c in result] != [c["id"] for c in candidates],
        "scope": "exposed equal-highest-score pair only; no score or admission change",
    }


class CandidateBuilder:
    """Build, validate, audit, and expose candidates without changing their order."""

    def __init__(
        self,
        *,
        snapshot: dict[str, Any],
        analysis: dict[str, Any],
        max_action_ticks: int,
        limit: int,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.analysis = analysis
        self.max_action_ticks = max_action_ticks
        self.limit = limit
        self.history = history or []
        self.candidates: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._loop_suppressed_climbs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        self._seen: set[str] = set()
        self.analysis["candidateAudit"] = self.audit

    def add(
        self,
        *,
        kind: str,
        key_code: int,
        ticks: int,
        score: int | ScoreSpec,
        target: dict[str, Any] | None = None,
        reason: str,
        candidate_id: str | None = None,
    ) -> bool:
        """Return whether the proposal has a candidate in the admitted pool."""
        score_spec = score if isinstance(score, ScoreSpec) else caller_score(score, kind=kind)
        audit = {
            "kind": kind,
            "candidateId": candidate_id or make_candidate_id(
                kind, target, ACTION_NAMES[key_code]
            ),
            "lane": candidate_lane(kind),
            "target": target,
            "proposedAction": {"keyCode": key_code, "ticks": ticks},
            "disposition": "proposed",
            "proposedScore": score_spec.total,
            "proposedScoreBreakdown": score_spec.breakdown(),
            "score": score_spec.total,
            "scoreBreakdown": score_spec.breakdown(),
            "scoreStage": "proposal",
        }
        self.audit.append(audit)
        movement = self.analysis["movement"]
        dig = self.analysis["dig"]
        action = _normalize_action(
            key_code, ticks, reason, max_ticks=self.max_action_ticks
        )
        action = limit_horizontal_ticks_under_guard_pressure(action, self.analysis)
        action = limit_horizontal_ticks_before_open_hole(action, movement, kind)
        action, endpoint_rejection_detail = (
            _apply_prospective_horizontal_endpoint_safety(
                action, self.analysis, kind, snapshot=self.snapshot
            )
        )
        if action is None:
            audit["disposition"] = "safety_rejection"
            audit["detail"] = endpoint_rejection_detail or (
                "prospective endpoint safety rejected the action"
            )
            return False
        if not is_action_physically_valid(
            action,
            movement,
            dig,
            candidate_kind=kind,
            runner_x_offset=_to_int(
                _dict(self.analysis.get("runner")).get("xOffset")
            ),
        ):
            audit["disposition"] = "physical_rejection"
            return False
        guard_rejection_detail = action_guard_safety_rejection_detail(
            action, self.analysis, candidate_kind=kind
        )
        if guard_rejection_detail is not None and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE}:
            for shorter_ticks in range(action["ticks"] - 1, 0, -1):
                shorter = {**action, "ticks": shorter_ticks}
                if not _short_medium_horizontal_clearance(shorter, self.analysis):
                    continue
                shorter, _ = _apply_prospective_horizontal_endpoint_safety(
                    shorter, self.analysis, kind, snapshot=self.snapshot
                )
                if shorter is None or not is_action_physically_valid(
                    shorter, movement, dig, candidate_kind=kind,
                    runner_x_offset=_to_int(_dict(self.analysis.get("runner")).get("xOffset")),
                ):
                    continue
                if action_guard_safety_rejection_detail(
                    shorter, self.analysis, candidate_kind=kind
                ) is None:
                    action = shorter
                    guard_rejection_detail = None
                    break
        if guard_rejection_detail is not None:
            audit["disposition"] = "safety_rejection"
            audit["detail"] = guard_rejection_detail
            return False
        candidate_id = candidate_id or make_candidate_id(
            kind, target, ACTION_NAMES[key_code]
        )
        audit["candidateId"] = candidate_id
        audit["validatedAction"] = action
        if candidate_id in self._seen:
            audit["disposition"] = "deduplicated"
            audit["detail"] = "candidate id already proposed"
            return any(c["id"] == candidate_id for c in self.candidates)
        self._seen.add(candidate_id)
        candidate = {"id": candidate_id, "kind": kind, "firstAction": action}
        loop_report = self.analysis["loopReport"]
        suppression_reason = candidate_suppression_reason(candidate, loop_report)
        clearance_bonus = low_risk_guard_clearance_score_bonus(
            action, self.analysis, candidate_kind=kind
        )
        clearance_penalty = medium_cross_row_clearance_score_penalty(
            action, self.analysis, candidate_kind=kind
        )
        adjusted_spec = score_spec.with_guard_adjustments(
            bonus=clearance_bonus, penalty=clearance_penalty,
        )
        adjusted_score = adjusted_spec.total
        audit.update(
            score=adjusted_score,
            scoreBreakdown=adjusted_spec.breakdown(),
            scoreStage="validated",
        )
        reasons = [reason]
        if clearance_bonus:
            reasons.append(
                "bounded progress preserves clearance from active low-risk guards"
            )
        if clearance_penalty:
            reasons.append(
                "bounded progress consumes minimum clearance under medium cross-row pressure"
            )
        next_candidate = {
            "id": candidate_id,
            "kind": kind,
            "lane": candidate_lane(kind),
            "score": adjusted_score,
            "scoreBreakdown": adjusted_spec.breakdown(),
            "target": target,
            "firstAction": action,
            "intents": [kind],
            "reasons": reasons,
        }
        if suppression_reason:
            audit["disposition"] = "loop_suppressed"
            audit["detail"] = suppression_reason
            if loop_report.get("type") == "vertical_cycle" and kind == "climb_ladder":
                self._loop_suppressed_climbs.append(
                    (next_candidate, audit, suppression_reason)
                )
            else:
                record_suppressed_candidate(loop_report, candidate, suppression_reason)
            return False
        signature = (action["keyCode"], action["ticks"])
        for index, existing in enumerate(self.candidates):
            existing_action = existing["firstAction"]
            if signature != (existing_action["keyCode"], existing_action["ticks"]):
                continue
            if not candidates_semantically_mergeable(existing, next_candidate):
                continue
            merged = merge_candidate_metadata(existing, next_candidate)
            if (-adjusted_score, candidate_id) < (
                -int(existing["score"]), str(existing["id"])
            ):
                self.candidates[index] = {
                    **merged,
                    **next_candidate,
                    "intents": merged["intents"],
                    "reasons": merged["reasons"],
                }
            else:
                self.candidates[index] = merged
            audit["disposition"] = "deduplicated"
            audit["detail"] = f"merged into {self.candidates[index]['id']}"
            return True
        self.candidates.append(next_candidate)
        audit["disposition"] = "validated"
        return True

    def finalize(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self._restore_guard_escape_climb()
        self._reject_unsupported_edge_evasion()
        self._penalize_recent_ladder_returns()
        predicted_target = predicted_horizontal_return_target(
            self.analysis["loopReport"]
        )
        predicted_candidates = [
            candidate
            for candidate in self.candidates
            if candidate_target(str(candidate.get("id"))) == predicted_target
            and _to_int(_dict(candidate.get("firstAction")).get("keyCode"))
            in {LEFT_KEYCODE, RIGHT_KEYCODE}
        ]
        alternatives = [
            candidate
            for candidate in self.candidates
            if candidate not in predicted_candidates
            and candidate.get("kind") != "wait_and_recheck"
        ]
        if predicted_target is not None and predicted_candidates and alternatives:
            predicted_ids = {
                str(candidate.get("id")) for candidate in predicted_candidates
            }
            self.candidates = [
                candidate
                for candidate in self.candidates
                if str(candidate.get("id")) not in predicted_ids
            ]
            for candidate in predicted_candidates:
                reason = (
                    "predicted return to "
                    f"({predicted_target[0]},{predicted_target[1]}) after alternating "
                    "horizontal_cycle targets"
                )
                record_suppressed_candidate(
                    self.analysis["loopReport"], candidate, reason
                )
                for audit in self.audit:
                    if (
                        audit.get("candidateId") == candidate.get("id")
                        and audit.get("disposition") == "validated"
                    ):
                        audit["disposition"] = "loop_suppressed"
                        audit["detail"] = reason
                        break
        self.candidates.sort(key=lambda item: (-int(item["score"]), item["id"]))
        exposed = self.candidates[: self.limit]
        exposed_ids = {str(item.get("id")) for item in exposed}
        for audit in self.audit:
            if audit.get("disposition") != "validated":
                continue
            audit["disposition"] = (
                "exposed"
                if str(audit.get("candidateId")) in exposed_ids
                else "limit_truncated"
            )
        exposed = boost_same_burst_gold_opposite_ladder(exposed, self.analysis, self.audit)
        exposed, tie_break = rank_same_column_retreat_tie(
            exposed, self.analysis, ticks_per_cell=GUARD_CLEARANCE_TICKS_PER_CELL
        )
        if tie_break:
            pair_ids = {LEFT_RETREAT_ID, RIGHT_RETREAT_ID}
            exposed = [
                {**candidate, "rankingTieBreak": tie_break}
                if candidate["id"] in pair_ids else candidate
                for candidate in exposed
            ]
            for audit in self.audit:
                if audit.get("disposition") == "exposed" and audit.get("candidateId") in pair_ids:
                    audit["rankingTieBreak"] = tie_break
        return exposed, self.analysis

    def _penalize_recent_ladder_returns(self) -> None:
        if (
            not self.analysis.get("goldComplete") or self.analysis.get("godMode")
            or _dict(self.analysis.get("risk")).get("risk") != "low"
            or _dict(self.analysis.get("loopReport")).get("active")
            or any(c.get("lane") == "safety" for c in self.candidates)
        ):
            return
        arrival = recent_ladder_ascent(self.snapshot, self.history)
        if arrival is None:
            return
        x, y, from_y = arrival
        returns = []
        for candidate in self.candidates:
            target = _dict(candidate.get("target"))
            tx, ty = _to_int(target.get("x")), _to_int(target.get("y"))
            if tx == x and (
                candidate["kind"] == "align_ladder" and ty == y
                or candidate["kind"] == "descend_route" and ty is not None and y < ty <= from_y
            ):
                returns.append(candidate)
        if not returns or not any(c not in returns and c.get("lane") == "progress" for c in self.candidates):
            return
        for candidate in returns:
            breakdown = candidate["scoreBreakdown"]
            spec = ScoreSpec(
                policy=breakdown["policy"], total=candidate["score"],
                components=tuple((p["name"], p["value"]) for p in breakdown["components"]),
            ).with_component("recent_ladder_return_penalty", -RECENT_LADDER_RETURN_PENALTY)
            candidate.update(score=spec.total, scoreBreakdown=spec.breakdown())
            reason = f"returns to the ladder used to reach ({x},{y}); no row or gold progress since arrival"
            candidate["reasons"].insert(0, reason)
            candidate["firstAction"] = {**candidate["firstAction"], "reason": reason}
            ladder = _dict(self.analysis.get("ladder"))
            if ladder.get("recommendedAction") == ACTION_NAMES[candidate["firstAction"]["keyCode"]]:
                ladder.update(recommendedAction=None, detail=reason)
            for row in self.audit:
                if row.get("candidateId") == candidate["id"] and row.get("disposition") == "validated":
                    row.update(score=spec.total, scoreBreakdown=spec.breakdown())

    def _reject_unsupported_edge_evasion(self) -> None:
        if (
            self.analysis.get("godMode")
            or _dict(self.analysis.get("movement")).get("currentTile") not in {"H", "S"}
            or not any(
                candidate["kind"] == "retreat_from_guard"
                and candidate["firstAction"]["keyCode"] == UP_KEYCODE
                for candidate in self.candidates
            )
        ):
            return
        runner = _dict(self.analysis.get("runner"))
        x, y = _to_int(runner.get("x")), _to_int(runner.get("y"))
        rows = self.snapshot.get("grid")
        if x is None or y is None or not isinstance(rows, list) or not 0 <= y < len(rows) - 1:
            return
        row, below = rows[y : y + 2]
        if not isinstance(row, str) or not isinstance(below, str):
            return
        for candidate in self.candidates[:]:
            if candidate["kind"] != "evade_edge_ladder":
                continue
            target_x = x + (-1 if candidate["firstAction"]["keyCode"] == LEFT_KEYCODE else 1)
            if not (
                0 <= target_x < min(len(row), len(below))
                and row[target_x] == below[target_x] == " "
            ):
                continue
            self.candidates.remove(candidate)
            for audit in self.audit:
                if audit.get("candidateId") == candidate["id"] and audit.get("disposition") == "validated":
                    audit["disposition"] = "safety_rejection"
                    audit["detail"] = (
                        "edge-ladder sidestep has no support below; an admitted upward retreat is available"
                    )
                    break

    def _restore_guard_escape_climb(self) -> None:
        loop_report = self.analysis["loopReport"]
        restore = False
        if len(self.candidates) == 1 and len(self._loop_suppressed_climbs) == 1:
            route = self.candidates[0]
            climb, audit, _reason = self._loop_suppressed_climbs[0]
            risk = _dict(self.analysis.get("risk"))
            guard = _dict(risk.get("pressureGuard"))
            distance = _to_int(guard.get("distance"))
            toward_guard = {
                "left": LEFT_KEYCODE,
                "right": RIGHT_KEYCODE,
            }.get(guard.get("relativeX"))
            recent_ids = _dict(loop_report.get("evidence")).get("candidateIds")
            restore = bool(
                loop_report.get("type") == "vertical_cycle"
                and not self.analysis.get("godMode")
                and risk.get("risk") == "low"
                and guard.get("risk") == "low"
                and guard.get("relativeY") == "same"
                and guard.get("closing")
                and guard.get("motion") in {"left", "right"}
                and distance is not None
                and 1 < distance <= LOW_RISK_LOOP_ESCAPE_MAX_DISTANCE
                and route.get("lane") == "progress"
                and _dict(route.get("firstAction")).get("keyCode") == toward_guard
                and _dict(climb.get("firstAction")).get("keyCode") in {
                    UP_KEYCODE, DOWN_KEYCODE,
                }
                and (_to_int(_dict(climb.get("firstAction")).get("ticks")) or 0) <= 6
                and isinstance(recent_ids, list)
                and len(recent_ids) >= 8
                and climb.get("id") not in recent_ids[-8:]
            )
            if restore:
                climb["reasons"].append(
                    "short ladder exit preserves a row-changing option while a guard closes ahead"
                )
                self.candidates.append(climb)
                audit["disposition"] = "validated"
                audit.pop("detail", None)
        for climb, _audit, reason in self._loop_suppressed_climbs:
            if not restore or climb not in self.candidates:
                record_suppressed_candidate(loop_report, climb, reason)
        self._loop_suppressed_climbs.clear()


def boost_same_burst_gold_opposite_ladder(
    exposed: list[dict[str, Any]], analysis: dict[str, Any],
    audit: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reward one already-exposed pickup only when the old top ladder goes away."""
    if (
        not exposed or analysis.get("godMode")
        or _dict(analysis.get("risk")).get("risk") != "low"
        or exposed[0].get("kind") != "align_ladder"
    ):
        return exposed
    top_key = _to_int(_dict(exposed[0].get("firstAction")).get("keyCode"))
    if top_key not in {LEFT_KEYCODE, RIGHT_KEYCODE}:
        return exposed
    runner = _dict(analysis.get("runner"))
    x, y = _to_int(runner.get("x")), _to_int(runner.get("y"))
    x_offset, y_offset = _to_int(runner.get("xOffset")), _to_int(runner.get("yOffset"))
    if None in (x, y, x_offset) or y_offset != 0:
        return exposed
    eligible = []
    for candidate in exposed:
        if candidate.get("kind") != "collect_same_row_gold":
            continue
        action, target = _dict(candidate.get("firstAction")), _dict(candidate.get("target"))
        key = _to_int(action.get("keyCode"))
        ticks = _to_int(action.get("ticks"))
        gold_x, gold_y = _to_int(target.get("x")), _to_int(target.get("y"))
        if (
            key not in {LEFT_KEYCODE, RIGHT_KEYCODE} or key == top_key
            or ticks is None or ticks < 1 or gold_x is None or gold_y != y
        ):
            continue
        direction = 1 if key == RIGHT_KEYCODE else -1
        if (gold_x - x) * direction <= 0:
            continue
        start, pickup = 40 * x + x_offset, 40 * gold_x
        if any(pickup <= start + direction * LEGACY_SUBTILE_STEP * tick < pickup + 10
               for tick in range(1, ticks + 1)):
            eligible.append(candidate)
    if len(eligible) != 1:
        return exposed
    gold = eligible[0]
    breakdown = gold["scoreBreakdown"]
    spec = ScoreSpec(
        policy=breakdown["policy"], total=int(gold["score"]),
        components=tuple((part["name"], part["value"]) for part in breakdown["components"]),
    ).with_component(
        "same_burst_opposite_ladder_gold_bonus", SAME_BURST_OPPOSITE_LADDER_GOLD_BONUS,
    )
    adjusted = {**gold, "score": spec.total, "scoreBreakdown": spec.breakdown()}
    result = [adjusted if candidate is gold else candidate for candidate in exposed]
    result.sort(key=lambda item: (-int(item["score"]), item["id"]))
    for row in audit:
        if row.get("candidateId") == gold["id"] and row.get("disposition") == "exposed":
            row["score"] = spec.total
            row["scoreBreakdown"] = spec.breakdown()
            row["scoreStage"] = "exposed_rerank"
    return result


def has_opposing_same_row_guard_pressure(risk: dict[str, Any]) -> bool:
    sides = {
        guard.get("relativeX")
        for guard in risk.get("guards") or []
        if isinstance(guard, dict)
        and guard.get("relativeY") == "same"
        and guard.get("risk") in GUARD_PRESSURE_RISKS
    }
    return {"left", "right"} <= sides


def analyze_state(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    runner = _dict(snapshot.get("runner"))
    gold = _dict(snapshot.get("gold"))
    nearest_gold = find_nearest_gold_candidates(snapshot, limit=5)
    row_ladders = find_row_ladders(snapshot, limit=6)
    gold_target = find_gold_target(nearest_gold)
    risk = assess_guard_risk(snapshot)
    movement = get_movement_affordance(snapshot)
    dig = get_dig_affordance(
        snapshot, risk=risk,
        allow_off_center_defensive=(
            not snapshot.get("godMode") and has_opposing_same_row_guard_pressure(risk)
        ),
    )
    analysis = {
        "gameState": snapshot.get("gameStateName"),
        "godMode": bool(snapshot.get("godMode")),
        "goldComplete": bool(gold.get("complete", snapshot.get("goldComplete"))),
        "goldCount": snapshot.get("goldCount"),
        "runner": {
            "x": runner.get("x"),
            "y": runner.get("y"),
            "action": runner.get("actionName"),
            "xOffset": runner.get("xOffset"),
            "yOffset": runner.get("yOffset"),
        },
        "gold": {
            "remainingCount": gold.get("remainingCount"),
            "complete": gold.get("complete"),
            "visiblePositions": gold.get("visiblePositions", []),
            "carriedByGuards": gold.get("carriedByGuards", []),
        },
        "nearestGold": nearest_gold,
        "rowLadders": row_ladders,
        "goldTarget": gold_target,
        "exitTarget": _dict(snapshot.get("exitTarget")) if bool(gold.get("complete", snapshot.get("goldComplete"))) else {},
        "risk": risk,
        "movement": movement,
        "dig": dig,
        "ladder": get_ladder_affordance(snapshot, row_ladders=row_ladders),
        "routeAccess": get_route_access_affordance(
            snapshot,
            dig=dig,
            nearest_gold=nearest_gold,
            row_ladders=row_ladders,
        ),
        "activeDig": _dict(snapshot.get("activeDig")),
    }
    analysis["ladderProgressDirection"] = ladder_progress_direction(snapshot, analysis)
    analysis["loopReport"] = build_loop_report(analysis, history)
    return analysis


def generate_candidates(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    limit: int = 7,
    max_action_ticks: int = AGENT_MAX_TICKS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    analysis = analyze_state(snapshot, history)
    movement = analysis["movement"]
    dig = analysis["dig"]
    ladder = analysis["ladder"]
    route_access = analysis["routeAccess"]
    loop_report = analysis["loopReport"]
    risk = analysis["risk"]
    god_mode = bool(analysis["godMode"])
    guard_pressure = not god_mode and risk.get("risk") in GUARD_PRESSURE_RISKS
    gold_complete = bool(analysis["goldComplete"])
    runner = analysis["runner"]
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))

    builder = CandidateBuilder(
        snapshot=snapshot,
        analysis=analysis,
        max_action_ticks=max_action_ticks,
        limit=limit,
        history=history,
    )
    add = builder.add
    candidates = builder.candidates

    add_dig_completion_wait_candidate(add, analysis)
    if _dict(analysis.get("activeDig")).get("active"):
        return builder.finalize()
    add_floor_refill_wait_candidate(add, analysis)
    if add_trap_resolution_wait_candidate(add, movement, risk):
        add_opposite_trap_preparation_dig_candidate(add, snapshot, analysis)
        return builder.finalize()

    if gold_complete:
        add_exit_candidates(add, snapshot, analysis, movement)

    if guard_pressure:
        add_non_god_escape_candidates(add, snapshot, movement, dig, risk)

    if ladder.get("onLadder"):
        direction = choose_ladder_direction(snapshot, analysis, history)
        target = _dict(analysis.get("goldTarget"))
        climb_reason = ladder_reason(ladder, direction, target)
        # The geometry-only affordance does not know the target/history choice.
        # Expose that choice consistently without changing candidate policy.
        ladder["recommendedAction"] = direction
        ladder["detail"] = climb_reason
        direction_toward_target = ladder_direction_toward_target(analysis, direction)
        add(
            kind="climb_ladder",
            key_code=UP_KEYCODE if direction == "up" else DOWN_KEYCODE,
            ticks=6,
            score=(
                fixed_score("climb_ladder.vertical_cycle_toward_target")
                if direction_toward_target and loop_report.get("type") == "vertical_cycle"
                else fixed_score("climb_ladder.toward_target")
                if direction_toward_target
                else fixed_score("climb_ladder.loop_active")
                if loop_report.get("active")
                else fixed_score("climb_ladder.gold_remaining")
                if not gold_complete
                else fixed_score("climb_ladder.gold_complete")
            ),
            target={"x": runner_x, "y": runner_y, "tile": "S" if ladder.get("onExitLadder") else "H"},
            reason=climb_reason,
        )
        # A vertical-cycle filter can suppress the preferred climb direction.
        # Keep one physically valid opposite exit available so filtering does
        # not collapse an otherwise traversable ladder state to emergency_hold.
        loop_vertical = loop_report.get("type") == "vertical_cycle"
        blocked_directions = set(
            _dict(loop_report.get("suppress")).get("directions") or []
        )
        alternate = "down" if direction == "up" else "up"
        if (
            loop_vertical
            and direction in blocked_directions
            and alternate not in blocked_directions
            and movement.get("canMoveDown" if alternate == "down" else "canMoveUp")
        ):
            add(
                kind="climb_ladder",
                key_code=DOWN_KEYCODE if alternate == "down" else UP_KEYCODE,
                ticks=6,
                score=fixed_score("climb_ladder.vertical_cycle_recovery"),
                target={"x": runner_x, "y": runner_y, "tile": "H"},
                reason=(
                    f"vertical-cycle recovery: use the opposite ladder direction ({alternate})"
                ),
                candidate_id=f"climb_ladder_{runner_x}_{runner_y}_{alternate}",
            )
    if not gold_complete:
        add_gold_candidates(add, analysis, god_mode, snapshot)
        add_ladder_alignment_candidates(add, analysis, god_mode, history)
        add_route_access_candidate(add, route_access)
        add_route_access_follow_candidate(add, analysis, route_access)
        add_guard_clearance_wait_candidate(add, route_access)
    else:
        add_ladder_alignment_candidates(add, analysis, god_mode, history)

    if analysis.get("ladderProgressDirection") == "horizontal":
        target_x = _to_int(_dict(analysis.get("goldTarget")).get("x"))
        lateral_key = LEFT_KEYCODE if target_x is not None and target_x < runner_x else RIGHT_KEYCODE
        if not any(_dict(c.get("firstAction")).get("keyCode") == lateral_key for c in candidates):
            analysis["ladderProgressDirection"] = None
    add_descent_candidates(add, analysis, movement, history)

    if god_mode and not gold_complete and not candidates:
        add_god_mode_progress_candidate(add, analysis)

    # Preserve a bounded horizontal progress option for low-risk off-row
    # states when structured routes produced nothing. Without this, a legal
    # movement toward remaining gold collapses to a generic wait.
    if (
        not candidates
        and not guard_pressure
        and not loop_report.get("active")
        and not gold_complete
    ):
        add_low_risk_horizontal_progress_candidate(add, analysis)

    if not candidates and not (guard_pressure or loop_report.get("active")):
        add_wait_and_recheck_candidate(add)

    # Preserve normal choices. Before an emergency hold, try an engine-legal
    # defensive dig that can center a supported runner's horizontal offset.
    if not candidates and guard_pressure:
        recovery_dig = get_dig_affordance(
            snapshot, risk=risk, allow_off_center_defensive=True
        )
        if any(
            _dict(recovery_dig.get(side)).get("guardCouldFall")
            and not _dict(dig.get(side)).get("canDefensiveDig")
            for side in ("left", "right")
        ):
            analysis["dig"] = recovery_dig
            add_non_god_escape_candidates(add, snapshot, movement, recovery_dig, risk)

    # Finish a pending ascent before holding, without claiming another row climb.
    guard = _dict(risk.get("pressureGuard"))
    if (
        not candidates
        and not god_mode
        and movement.get("canFinishLadderClimb")
        and movement.get("currentTile") not in {"H", "S"}
        and runner.get("action") == "up"
        and guard.get("risk") in {"high", "critical"}
        and guard.get("relativeY") == "below"
    ):
        add(
            kind="retreat_from_guard",
            key_code=UP_KEYCODE,
            ticks=2,
            score=fixed_score("retreat_from_guard.up"),
            reason="finish the pending upward ladder alignment away from the guard below, then recheck",
        )

    if (
        not candidates
        and guard_pressure
        and guard.get("risk") in {"high", "critical"}
        and guard.get("relativeY") in {"above", "below"}
        and guard.get("relativeX") in {"left", "right"}
    ):
        direction = "left" if guard["relativeX"] == "right" else "right"
        add(
            kind="retreat_from_guard",
            key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
            ticks=4,
            score=fixed_score("retreat_from_guard.side"),
            reason=f"no ordinary action remains; retreat {direction} from diagonal guard pressure",
        )

    if not candidates:
        add_emergency_hold_candidate(add, risk)

    return builder.finalize()


def candidates_semantically_mergeable(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> bool:
    """Only merge duplicate actions when their model-facing intent is equivalent."""
    return (
        existing.get("kind") == incoming.get("kind")
        and existing.get("target") == incoming.get("target")
    )


def merge_candidate_metadata(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for field in ("intents", "reasons"):
        values = list(existing.get(field) or [])
        for value in incoming.get(field) or []:
            if value not in values:
                values.append(value)
        merged[field] = values
    return merged


# Candidate families: exit and progress routes

def add_exit_candidates(
    add,
    snapshot: dict[str, Any],
    analysis: dict[str, Any],
    movement: dict[str, Any],
) -> None:
    ladder = analysis["ladder"]
    runner = analysis["runner"]
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if movement.get("canFinishExitClimb"):
        add(
            kind="exit_ladder_route",
            key_code=UP_KEYCODE,
            ticks=4,
            score=fixed_score("exit_ladder_route.finish_climb"),
            target={"x": runner_x, "y": runner_y, "tile": "S"},
            reason="runner remains below the revealed exit center by a positive yOffset",
        )
        return
    if ladder.get("onExitLadder"):
        add(
            kind="exit_ladder_route",
            key_code=UP_KEYCODE,
            ticks=6,
            score=fixed_score("exit_ladder_route.on_exit_ladder"),
            target={"x": runner_x, "y": runner_y, "tile": "S"},
            reason="runner is already on the revealed exit ladder",
        )
        return
    for ladder_item in analysis["rowLadders"]:
        direction = ladder_item.get("direction")
        marked_exit = ladder_item.get("tile") == "S"
        top_connected = (
            direction in {"left", "right"}
            and ladder_column_reaches_top(snapshot, ladder_item)
        )
        if not (marked_exit or top_connected):
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE if direction == "right" else UP_KEYCODE
        accepted = add(
            kind="exit_ladder_route",
            key_code=key_code,
            ticks=(
                ticks_for_alignment(int(ladder_item["distance"]))
                if top_connected and not marked_exit
                else 20
            ),
            score=fixed_score("exit_ladder_route.align_row"),
            target={
                "x": ladder_item["x"],
                "y": ladder_item["y"],
                "tile": ladder_item.get("tile"),
            },
            reason=(
                "gold is complete and the marked exit ladder is on the runner row"
                if marked_exit
                else "gold is complete and this ladder column connects to row 0"
            ),
        )
        if accepted:
            return
    if movement.get("canMoveUp"):
        ticks = exit_climb_ticks(snapshot, analysis)
        add(
            kind="exit_ladder_route",
            key_code=UP_KEYCODE,
            ticks=ticks,
            score=fixed_score("exit_ladder_route.move_up"),
            target={"x": runner_x, "y": runner_y},
            reason=(
                "gold is complete; recheck before a descending guard closes on this ladder"
                if ticks == 6
                else "gold is complete and upward movement is valid"
            ),
        )
        return


def exit_climb_ticks(snapshot: dict[str, Any], analysis: dict[str, Any]) -> int:
    """Bound one exit climb when a close guard descends the same ladder."""
    risk = _dict(analysis.get("risk"))
    guard = _dict(risk.get("pressureGuard"))
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    guard_x = _to_int(guard.get("x"))
    guard_y = _to_int(guard.get("y"))
    distance = _to_int(guard.get("distance"))
    if (
        risk.get("risk") != "low"
        or guard.get("risk") != "low"
        or guard.get("relativeX") != "same"
        or guard.get("relativeY") != "above"
        or guard.get("motion") not in {"down", "fall"}
        or distance is None
        or distance > 6
        or None in {runner_x, runner_y, guard_x, guard_y}
        or runner_x != guard_x
    ):
        return 20
    rows = snapshot.get("terrainGrid") or []
    if not isinstance(rows, list):
        return 20
    low, high = sorted((int(runner_y), int(guard_y)))
    if any(
        not isinstance(rows[y], str)
        or int(runner_x) >= len(rows[y])
        or rows[y][int(runner_x)] not in {"H", "S"}
        for y in range(low, high + 1)
    ):
        return 20
    return 6

# Candidate families: safety and guard escape

def add_non_god_escape_candidates(
    add,
    snapshot: dict[str, Any],
    movement: dict[str, Any],
    dig: dict[str, Any],
    risk: dict[str, Any],
) -> None:
    guard = _dict(risk.get("pressureGuard"))
    side = guard.get("relativeX")
    closing = bool(guard.get("closing"))
    guard_risk = guard.get("risk")
    left_dig = _dict(dig.get("left"))
    right_dig = _dict(dig.get("right"))
    active_trap = _trap_hole_between_pressure_guard(movement, risk)
    pinch = has_opposing_same_row_guard_pressure(risk)
    left_dig_available = active_trap.get("side") != "left" and (bool(dig.get("canDigLeft")) or bool(
        left_dig.get("canDefensiveDig") and left_dig.get("guardCouldFall")
    ))
    right_dig_available = active_trap.get("side") != "right" and (bool(dig.get("canDigRight")) or bool(
        right_dig.get("canDefensiveDig") and right_dig.get("guardCouldFall")
    ))
    pressure_supports_trap = guard_risk in {"high", "critical"} and (
        guard.get("relativeY") != "below"
        or guard.get("motion") in {"up", "climb_out"}
    )
    left_trap_ready = pressure_supports_trap or bool(
        left_dig.get("guardCouldFall")
    )
    right_trap_ready = pressure_supports_trap or bool(
        right_dig.get("guardCouldFall")
    )
    edge_defensive_trap = bool(
        risk.get("runnerOnEdge")
        and closing
        and (
            (side == "left" and left_dig_available and left_trap_ready)
            or (side == "right" and right_dig_available and right_trap_ready)
        )
    )
    runner = _dict(snapshot.get("runner"))
    runner_x = _to_int(runner.get("x"))
    guard_x = _to_int(guard.get("x"))
    guard_distance = _to_int(guard.get("distance"))
    guard_motion = str(guard.get("motion") or "unknown")
    # Horizontal side retreat is only justified when the pressure guard is on
    # the runner's row.  A high/critical guard above or below may still need
    # the dedicated hole, vertical, or defensive candidates below, but must
    # not masquerade as a same-row guard and suppress ordinary progress.
    side_retreat_pressure = guard.get("relativeY") == "same"
    # A high/critical guard directly below or above can be escaped by taking
    # the opposite valid ladder direction. Treat that as vertical retreat
    # pressure too; otherwise a runner on a ladder can collapse to
    # emergency_hold even though a row-changing escape is available.
    cross_row_up_pressure = (
        guard_risk in {"high", "critical"}
        and guard.get("relativeY") == "below"
        and movement.get("canMoveUp")
    )
    cross_row_down_pressure = (
        guard_risk in {"high", "critical"}
        and guard.get("relativeY") == "above"
        and movement.get("canMoveDown")
    )
    decisive_defensive_trap = bool(
        guard_risk == "high"
        and closing
        and guard_distance == 3
        and (
            (side == "left" and left_dig_available and left_trap_ready)
            or (side == "right" and right_dig_available and right_trap_ready)
        )
    )
    imminent_landing_side = (
        side
        if guard.get("relativeY") == "above"
        and guard_motion in {"down", "fall"}
        and guard_distance is not None
        and guard_distance <= 3
        else None
    )
    edge_escape_direction = None
    if (
        guard.get("relativeY") == "below"
        and guard_distance is not None
        and guard_distance <= 3
        and runner_x is not None
        and guard_x is not None
    ):
        if (
            not movement.get("canMoveRight")
            and movement.get("canMoveLeft")
            and guard_x <= runner_x
            and guard_motion in {"right", "up", "climb_out"}
        ):
            edge_escape_direction = "left"
        elif (
            not movement.get("canMoveLeft")
            and movement.get("canMoveRight")
            and guard_x >= runner_x
            and guard_motion in {"left", "up", "climb_out"}
        ):
            edge_escape_direction = "right"
    if edge_escape_direction:
        add(
            kind="evade_edge_ladder",
            key_code=LEFT_KEYCODE if edge_escape_direction == "left" else RIGHT_KEYCODE,
            ticks=4,
            score=fixed_score("evade_edge_ladder.base"),
            reason=(
                f"guard below is moving toward the edge ladder; step {edge_escape_direction} "
                "before it enters the runner's column"
            ),
            candidate_id=f"evade_edge_ladder_{edge_escape_direction}",
        )
        # Keep evaluating vertical escape options as well. The horizontal
        # edge move can be rejected later by same-row guard safety, while an
        # available ladder retreat remains a valid way out of the pressure.
    left_open_hole = _dict(_dict(_dict(movement.get("details")).get("left")).get("openHole"))
    right_open_hole = _dict(_dict(_dict(movement.get("details")).get("right")).get("openHole"))
    hole_escape_direction = None
    if guard.get("relativeY") in {"above", "below"} and not closing:
        if (
            _to_int(left_open_hole.get("distance")) == 1
            and not left_open_hole.get("occupiedByTrappedGuard")
            and movement.get("canMoveRight")
            and _to_int(right_open_hole.get("distance")) != 1
        ):
            hole_escape_direction = "right"
        elif (
            _to_int(right_open_hole.get("distance")) == 1
            and not right_open_hole.get("occupiedByTrappedGuard")
            and movement.get("canMoveLeft")
            and _to_int(left_open_hole.get("distance")) != 1
        ):
            hole_escape_direction = "left"
    if hole_escape_direction:
        if hole_escape_direction == imminent_landing_side:
            hole_escape_direction = None
    if hole_escape_direction:
        add(
            kind="evade_open_hole",
            key_code=RIGHT_KEYCODE if hole_escape_direction == "right" else LEFT_KEYCODE,
            ticks=4,
            score=fixed_score("evade_open_hole.base"),
            reason=(
                f"adjacent empty hole blocks the opposite side; move {hole_escape_direction} "
                "while the cross-row guard is not closing"
            ),
            candidate_id=f"evade_open_hole_{hole_escape_direction}",
        )
    if guard_risk in GUARD_PRESSURE_RISKS:
        for direction, key_code, movement_key in (
            ("left", LEFT_KEYCODE, "canMoveLeft"),
            ("right", RIGHT_KEYCODE, "canMoveRight"),
        ):
            movement_detail = _dict(_dict(movement.get("details")).get(direction))
            hole = _dict(movement_detail.get("openHole"))
            hole_y = _to_int(hole.get("y"))
            terrain_height = _to_int(movement.get("terrainHeight"))
            medium_retreat_drop = (
                guard_risk == "medium"
                and closing
                and guard.get("relativeY") == "same"
                and direction != side
            )
            if (
                (guard_risk in {"high", "critical"} or medium_retreat_drop)
                and movement.get(movement_key)
                and _to_int(movement_detail.get("openDugHoleDistance")) == 1
                and hole.get("frameIndex") == 0  # Do not enter a visibly refilling hole.
                and hole_y is not None
                and terrain_height is not None
                and hole_y < terrain_height - 1
                and not assess_emergency_hole_escape_threat(snapshot, hole).get("unsafe")
            ):
                add(
                    kind="escape_through_open_hole",
                    key_code=key_code,
                    ticks=4,
                    score=fixed_score("escape_through_open_hole.base"),
                    target={"x": hole.get("x"), "y": hole.get("y"), "tile": "open_hole"},
                    reason=f"{guard_risk} guard pressure leaves an adjacent open escape hole to the {direction}",
                )
    if (
        (side_retreat_pressure or cross_row_up_pressure)
        and movement.get("canMoveUp")
        and not decisive_defensive_trap
    ):
        add(
            kind="retreat_from_guard",
            key_code=UP_KEYCODE,
            ticks=6,
            score=fixed_score("retreat_from_guard.up"),
            reason="non-god-mode guard pressure is active and up is valid",
        )
    if (
        (side_retreat_pressure or cross_row_down_pressure)
        and movement.get("canMoveDown")
        and not edge_defensive_trap
        and not decisive_defensive_trap
    ):
        add(
            kind="retreat_from_guard",
            key_code=DOWN_KEYCODE,
            ticks=6,
            score=fixed_score("retreat_from_guard.down"),
            reason="non-god-mode guard pressure is active and down is valid",
        )
    if side == "left" and left_dig_available and left_trap_ready and not edge_escape_direction:
        imminent_landing_trap = imminent_landing_side == "left"
        add(
            kind="defensive_dig",
            key_code=DIG_LEFT_KEYCODE,
            ticks=8,
            score=(
                fixed_score("defensive_dig.imminent_landing")
                if imminent_landing_trap
                else fixed_score("defensive_dig.pinch")
                if pinch
                else fixed_score("defensive_dig.edge")
                if edge_defensive_trap
                else fixed_score("defensive_dig.decisive")
                if decisive_defensive_trap
                else fixed_score("defensive_dig.default")
            ),
            reason=(
                "guard above-left is descending toward this row; dig_left now"
                if imminent_landing_trap
                else "closing same-row guard can fall into dig_left; dig now"
                if (
                    closing
                    and guard.get("relativeY") == "same"
                    and left_dig.get("guardCouldFall")
                )
                else "guard pressure from left and dig_left is legal"
            ),
        )
    if side == "right" and right_dig_available and right_trap_ready and not edge_escape_direction:
        imminent_landing_trap = imminent_landing_side == "right"
        add(
            kind="defensive_dig",
            key_code=DIG_RIGHT_KEYCODE,
            ticks=8,
            score=(
                fixed_score("defensive_dig.imminent_landing")
                if imminent_landing_trap
                else fixed_score("defensive_dig.pinch")
                if pinch
                else fixed_score("defensive_dig.edge")
                if edge_defensive_trap
                else fixed_score("defensive_dig.decisive")
                if decisive_defensive_trap
                else fixed_score("defensive_dig.default")
            ),
            reason=(
                "guard above-right is descending toward this row; dig_right now"
                if imminent_landing_trap
                else "closing same-row guard can fall into dig_right; dig now"
                if (
                    closing
                    and guard.get("relativeY") == "same"
                    and right_dig.get("guardCouldFall")
                )
                else "guard pressure from right and dig_right is legal"
            ),
        )
    if decisive_defensive_trap:
        return
    if (
        side_retreat_pressure
        and side == "left"
        and movement.get("canMoveRight")
    ):
        add(
            kind="retreat_from_guard",
            key_code=RIGHT_KEYCODE,
            ticks=6,
            score=fixed_score("retreat_from_guard.side"),
            reason=_guard_reposition_reason("left", "right", closing),
        )
    if (
        side_retreat_pressure
        and side == "right"
        and movement.get("canMoveLeft")
    ):
        add(
            kind="retreat_from_guard",
            key_code=LEFT_KEYCODE,
            ticks=6,
            score=fixed_score("retreat_from_guard.side"),
            reason=_guard_reposition_reason("right", "left", closing),
        )
    if side == "same":
        for direction, key_code, movement_key in (
            ("left", LEFT_KEYCODE, "canMoveLeft"),
            ("right", RIGHT_KEYCODE, "canMoveRight"),
        ):
            if not movement.get(movement_key):
                continue
            add(
                kind="retreat_from_guard",
                key_code=key_code,
                ticks=4,
                score=fixed_score("retreat_from_guard.same_column"),
                reason=f"guard is vertically aligned on another row; move {direction} to break its approach line",
                candidate_id=f"retreat_from_guard_same_column_{direction}",
            )


def _guard_reposition_reason(guard_side: str, move_direction: str, closing: bool) -> str:
    motion = "closing" if closing else "not currently closing"
    return (
        f"guard is on the {guard_side} and {motion}; move {move_direction} briefly, "
        "then reassess because the guard may follow and distance may not increase"
    )


# Candidate families: collection and route progress

def add_gold_candidates(
    add,
    analysis: dict[str, Any],
    god_mode: bool,
    snapshot: dict[str, Any],
) -> None:
    movement = analysis["movement"]
    for gold in analysis["nearestGold"]:
        if gold.get("source") == "guard":
            continue
        if not gold.get("sameRow"):
            continue
        direction = gold.get("direction")
        if direction == "same":
            runner = _dict(analysis.get("runner"))
            x_offset = _to_int(runner.get("xOffset")) or 0
            y_offset = _to_int(runner.get("yOffset")) or 0
            if y_offset > 0 and movement.get("canFinishLadderClimb"):
                key_code = UP_KEYCODE
                ticks = min(
                    4,
                    max(
                        1,
                        (abs(y_offset) + LEGACY_SUBTILE_STEP - 1)
                        // LEGACY_SUBTILE_STEP,
                    ),
                )
                center_reason = f"finish ladder alignment from yOffset {y_offset}"
            elif y_offset < 0 and movement.get("canMoveDown"):
                key_code = DOWN_KEYCODE
                ticks = min(
                    4,
                    max(
                        1,
                        (abs(y_offset) + LEGACY_SUBTILE_STEP - 1)
                        // LEGACY_SUBTILE_STEP,
                    ),
                )
                center_reason = f"center vertically from yOffset {y_offset}"
            else:
                key_code = (
                    LEFT_KEYCODE
                    if x_offset > 0
                    else RIGHT_KEYCODE
                    if x_offset < 0
                    else STOP_KEYCODE
                )
                ticks = (
                    min(4, max(2, (abs(x_offset) + 3) // 4))
                    if x_offset
                    else 2
                )
                center_reason = (
                    f"center from xOffset {x_offset}"
                    if x_offset
                    else "advance collision processing"
                )
            add(
                kind="collect_current_tile_gold",
                key_code=key_code,
                ticks=ticks,
                score=fixed_score("collect_current_tile_gold.base"),
                target={"x": gold["x"], "y": gold["y"], "tile": "$"},
                reason=f"gold shares the runner tile; {center_reason}",
            )
            continue
        if direction not in {"left", "right"}:
            continue
        if not same_row_terrain_path_clear(snapshot, gold):
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        add(
            kind="collect_same_row_gold",
            key_code=key_code,
            ticks=8,
            score=fixed_score("collect_same_row_gold.god_mode") if god_mode else fixed_score("collect_same_row_gold.normal"),
            target={"x": gold["x"], "y": gold["y"], "tile": "$"},
            reason=f"same-row gold is {gold['distance']} tiles to the {direction}",
        )


def same_row_terrain_path_clear(
    snapshot: dict[str, Any], target: dict[str, Any]
) -> bool:
    runner = _dict(snapshot.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    target_x = _to_int(target.get("x"))
    target_y = _to_int(target.get("y"))
    rows = snapshot.get("terrainGrid")
    if (
        runner_x is None
        or runner_y is None
        or target_x is None
        or target_y != runner_y
        or not isinstance(rows, list)
        or not (0 <= runner_y < len(rows))
    ):
        return True
    row = rows[runner_y]
    if not isinstance(row, str):
        return True
    start, end = sorted((runner_x, target_x))
    return all(x < len(row) and row[x] not in {"#", "@"} for x in range(start + 1, end))


def add_ladder_alignment_candidates(
    add,
    analysis: dict[str, Any],
    god_mode: bool,
    history: list[dict[str, Any]],
) -> None:
    movement = analysis["movement"]
    loop_report = analysis["loopReport"]
    runner_y = _to_int(_dict(analysis.get("runner")).get("y"))
    target_y = _to_int(_dict(analysis.get("goldTarget")).get("y"))
    departed_ladder = post_ascent_departed_ladder(analysis, history)
    for ladder in analysis["rowLadders"]:
        if ladder.get("tile") != "H" or ladder.get("distance") == 0:
            continue
        if (
            ladder.get("entryDirection") == "down"
            and runner_y is not None
            and target_y is not None
            and target_y <= runner_y
        ):
            continue
        if departed_ladder == {
            "x": _to_int(ladder.get("x")),
            "y": _to_int(ladder.get("y")),
        }:
            continue
        direction = ladder.get("direction")
        if direction not in {"left", "right"}:
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        distance = int(ladder.get("distance") or 0)
        fine_align = distance <= 1
        loop_target = loop_report.get("target") == {
            "x": ladder.get("x"),
            "y": ladder.get("y"),
            "kind": "ladder",
        }
        add(
            kind="align_ladder",
            key_code=key_code,
            ticks=ticks_for_alignment(distance),
            score=ladder_alignment_score_spec(
                distance,
                god_mode=god_mode,
                fine_align=fine_align,
                loop_target=loop_target,
            ),
            target={"x": ladder["x"], "y": ladder["y"], "tile": "H"},
            reason=f"visible ladder is {ladder['distance']} tiles to the {direction}",
        )


def post_ascent_departed_ladder(
    analysis: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, int] | None:
    if _dict(analysis.get("risk")).get("risk") != "low" or len(history) < 2:
        return None
    climb = _dict(history[-2])
    alignment = _dict(history[-1])
    alignment_parts = str(alignment.get("candidateId") or "").split("_")
    alignment_key = _to_int(alignment.get("keyCode"))
    direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(alignment_key)
    if (
        not str(climb.get("candidateId") or "").startswith(
            ("climb_ladder_", "exit_ladder_route_")
        )
        or _to_int(climb.get("keyCode")) != UP_KEYCODE
        or len(alignment_parts) != 5
        or alignment_parts[:2] != ["align", "ladder"]
        or alignment_parts[4] != direction
    ):
        return None
    target = (_to_int(alignment_parts[2]), _to_int(alignment_parts[3]))
    climb_before = history_runner_position(climb, "before")
    climb_after = history_runner_position(climb, "after")
    align_before = history_runner_position(alignment, "before")
    align_after = history_runner_position(alignment, "after")
    runner = _dict(analysis.get("runner"))
    current = (_to_int(runner.get("x")), _to_int(runner.get("y")))
    gold_before = _to_int(_dict(alignment.get("before")).get("goldCount"))
    gold_after = _to_int(_dict(alignment.get("after")).get("goldCount"))
    if (
        any(
            None in point
            for point in (
                target,
                climb_before,
                climb_after,
                align_before,
                align_after,
                current,
            )
        )
        or gold_before is None
        or gold_before != gold_after
    ):
        return None
    if (
        climb_before != (climb_after[0], climb_after[1] + 1)
        or climb_after != align_before
        or align_before[1] != align_after[1]
        or align_after != current
    ):
        return None

    target_remains_ahead = (
        alignment_key == LEFT_KEYCODE and target[0] < align_after[0]
    ) or (
        alignment_key == RIGHT_KEYCODE and target[0] > align_after[0]
    )
    target_is_available = any(
        ladder.get("tile") == "H"
        and (_to_int(ladder.get("x")), _to_int(ladder.get("y"))) == target
        and ladder.get("direction") == direction
        for ladder in analysis["rowLadders"]
    )
    if (
        not target_is_available
        or not target_remains_ahead
        or not analysis["movement"].get(
            "canMoveLeft" if alignment_key == LEFT_KEYCODE else "canMoveRight"
        )
        or abs(align_after[0] - target[0]) >= abs(align_before[0] - target[0])
    ):
        return None
    return {"x": climb_after[0], "y": climb_after[1]}


def history_runner_position(
    item: dict[str, Any], moment: str
) -> tuple[int | None, int | None]:
    runner = _dict(_dict(item.get(moment)).get("runner"))
    return _to_int(runner.get("x")), _to_int(runner.get("y"))


def ladder_alignment_score(
    distance: int, *, god_mode: bool, fine_align: bool, loop_target: bool
) -> int:
    """Preserve the integer helper API; generation uses the named specification."""
    return ladder_alignment_score_spec(
        distance, god_mode=god_mode, fine_align=fine_align, loop_target=loop_target
    ).total


def add_route_access_candidate(add, route_access: dict[str, Any]) -> None:
    if not route_access.get("available"):
        return
    action_name = route_access.get("recommendedAction")
    if action_name not in DIG_KEYCODES:
        return
    candidate_id = f"route_access_{action_name}"
    off_row_gold = _dict(route_access.get("offRowGoldTarget"))
    add(
        kind="route_access_dig",
        key_code=DIG_KEYCODES[action_name],
        ticks=12,
        score=fixed_score("route_access_dig.base"),
        target=off_row_gold,
        reason=str(route_access.get("reason", "legal route-access dig is available")),
        candidate_id=candidate_id,
    )


def add_route_access_follow_candidate(
    add, analysis: dict[str, Any], route_access: dict[str, Any]
) -> None:
    if not route_access.get("followAvailable"):
        return
    direction = route_access.get("followAction")
    if direction not in {"left", "right"}:
        return
    movement = analysis["movement"]
    if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
        return
    key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
    off_row_gold = _dict(route_access.get("offRowGoldTarget"))
    opened_cell = _dict(route_access.get("openedAccessCell"))
    add(
        kind="route_access_follow",
        key_code=key_code,
        ticks=8,
        score=fixed_score("route_access_follow.base"),
        target=opened_cell or off_row_gold,
        reason=str(route_access.get("reason", "access route is open; move into it")),
    )


def add_guard_clearance_wait_candidate(add, route_access: dict[str, Any]) -> None:
    if not (
        route_access.get("followBlockedByGuard") or route_access.get("digBlockedByGuard")
    ):
        return
    opened_cell = _dict(
        route_access.get("openedAccessCell") or route_access.get("plannedAccessCell")
    )
    threat = _dict(_dict(route_access.get("dropThreat")).get("nearestThreat"))
    signature = "_".join(
        str(threat.get(field, "x")) for field in ("id", "x", "y", "xOffset", "yOffset")
    )
    add(
        kind="wait_for_guard_clearance",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=fixed_score("wait_for_guard_clearance.base"),
        target=opened_cell,
        reason=str(route_access.get("reason", "guard blocks safe access-route entry")),
        candidate_id=f"wait_for_guard_clearance_{signature}",
    )


# Candidate families: execution gates and environment waits

def add_dig_completion_wait_candidate(add, analysis: dict[str, Any]) -> None:
    active_dig = _dict(analysis.get("activeDig"))
    if not active_dig.get("active"):
        return
    frame_index = _to_int(active_dig.get("frameIndex")) or 0
    frame_count = _to_int(active_dig.get("frameCount")) or 0
    target = {
        "x": active_dig.get("x"),
        "y": active_dig.get("y"),
        "tile": "#",
    }
    add(
        kind="wait_for_dig_completion",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=fixed_score("wait_for_dig_completion.base"),
        target=target,
        reason=(
            f"legacy dig at ({target['x']},{target['y']}) is still active "
            f"at frame {frame_index}/{frame_count}"
        ),
        candidate_id=(
            f"wait_for_dig_completion_{target['x']}_{target['y']}_{frame_index}_{frame_count}"
        ),
    )


def add_trap_resolution_wait_candidate(
    add, movement: dict[str, Any], risk: dict[str, Any]
) -> bool:
    trap = _trap_hole_between_pressure_guard(movement, risk)
    if not trap:
        return False
    hole = _dict(trap.get("hole"))
    guard = _dict(trap.get("guard"))
    guard_distance = _to_int(guard.get("distance"))
    guard_motion = str(guard.get("motion") or "unknown")
    if guard_motion in {"fall", "up", "climb_out"} or (
        guard_distance is not None and guard_distance <= 2
    ):
        wait_ticks = 2
    elif guard_distance is not None and guard_distance <= 4:
        wait_ticks = 4
    else:
        wait_ticks = 8
    signature = "_".join(
        str(value)
        for value in (
            trap.get("side"),
            hole.get("x"),
            hole.get("y"),
            hole.get("frameIndex"),
            hole.get("frameTime"),
            guard.get("id"),
            guard.get("x"),
            guard.get("y"),
            guard.get("xOffset"),
            guard.get("yOffset"),
            guard.get("motion"),
        )
    )
    add(
        kind="wait_for_trap_resolution",
        key_code=STOP_KEYCODE,
        ticks=wait_ticks,
        score=fixed_score("wait_for_trap_resolution.base"),
        target={"x": hole.get("x"), "y": hole.get("y"), "tile": "open_hole"},
        reason=(
            f"open hole at ({hole.get('x')},{hole.get('y')}) already separates "
            f"the {trap.get('side')}-side pressure guard"
        ),
        candidate_id=f"wait_for_trap_resolution_{signature}",
    )
    return True


def add_opposite_trap_preparation_dig_candidate(
    add, snapshot: dict[str, Any], analysis: dict[str, Any]
) -> bool:
    """Keep one preparation dig when an existing trap covers only one side."""
    movement = _dict(analysis.get("movement"))
    risk = _dict(analysis.get("risk"))
    trap = _trap_hole_between_pressure_guard(movement, risk)
    if not trap:
        return False
    trap_guard = _dict(trap.get("guard"))
    opposite = "left" if trap.get("side") == "right" else "right"
    threat = next(
        (
            _dict(guard)
            for guard in risk.get("guards") or []
            if _dict(guard).get("id") != trap_guard.get("id")
            and _dict(guard).get("relativeY") == "same"
            and _dict(guard).get("relativeX") == opposite
            and _dict(guard).get("risk") in {"high", "critical"}
            and _dict(guard).get("closing")
            and (_to_int(_dict(guard).get("distance")) or 99) <= 4
        ),
        None,
    )
    if threat is None:
        return False
    dig = _dict(_dict(analysis.get("dig")).get(opposite))
    if not dig.get("canDefensiveDig"):
        recovery = get_dig_affordance(
            snapshot, risk=risk, allow_off_center_defensive=True
        )
        dig.update(_dict(recovery.get(opposite)))
    if not dig.get("canDefensiveDig"):
        return False
    # The general affordance follows the nearest same-row guard. Here the
    # uncovered secondary guard is the one that can enter this new hole.
    dig["guardCouldFall"] = True
    action = "dig_left" if opposite == "left" else "dig_right"
    add(
        kind="defensive_dig",
        key_code=DIG_LEFT_KEYCODE if opposite == "left" else DIG_RIGHT_KEYCODE,
        ticks=8,
        score=fixed_score("defensive_dig.pinch"),
        reason=(
            f"the {trap.get('side')}-side hole covers one guard; "
            f"a second closing guard can enter {action}"
        ),
        candidate_id=f"defensive_dig_{action}",
    )
    return True


def add_floor_refill_wait_candidate(add, analysis: dict[str, Any]) -> None:
    target = _dict(analysis.get("goldTarget"))
    direction = target.get("direction")
    if direction not in {"left", "right"}:
        return
    movement = _dict(analysis.get("movement"))
    detail = _dict(_dict(movement.get("details")).get(direction))
    hole = _dict(detail.get("openHole"))
    if _to_int(hole.get("distance")) != 1 or hole.get("occupiedByTrappedGuard"):
        return
    route_access = _dict(analysis.get("routeAccess"))
    opened_access_cell = _dict(route_access.get("openedAccessCell"))
    if (
        route_access.get("followAvailable")
        and _to_int(opened_access_cell.get("x")) == _to_int(hole.get("x"))
        and _to_int(opened_access_cell.get("y")) == _to_int(hole.get("y"))
    ):
        return
    signature = "_".join(
        str(hole.get(field, "x")) for field in ("x", "y", "frameIndex", "frameTime")
    )
    add(
        kind="wait_for_floor_refill",
        key_code=STOP_KEYCODE,
        ticks=8,
        score=fixed_score("wait_for_floor_refill.base"),
        target={"x": hole.get("x"), "y": hole.get("y"), "tile": "#"},
        reason=(
            f"open dug brick at ({hole.get('x')},{hole.get('y')}) blocks safe {direction} "
            f"{'exit' if analysis.get('goldComplete') else 'gold'} progress; "
            f"refill frame {hole.get('frameIndex')} time {hole.get('frameTime')}"
        ),
        candidate_id=f"wait_for_floor_refill_{signature}",
    )


def add_descent_candidates(
    add,
    analysis: dict[str, Any],
    movement: dict[str, Any],
    history: list[dict[str, Any]],
) -> None:
    if analysis.get("ladderProgressDirection") in {"up", "horizontal"}:
        return
    runner = analysis["runner"]
    runner_y = _to_int(runner.get("y"))
    ladder = _dict(analysis.get("ladder"))
    entry = _dict(ladder.get("nearestRowLadder"))
    entry_x = _to_int(entry.get("x"))
    entry_y = _to_int(entry.get("ladderY"))
    target_y = _to_int(_dict(analysis.get("goldTarget")).get("y"))
    target_does_not_require_descent = (
        runner_y is not None and target_y is not None and target_y <= runner_y
    )
    if (
        ladder.get("onDownEntry")
        and movement.get("canMoveDown")
        and entry_x is not None
        and entry_y is not None
        and not target_does_not_require_descent
        and not just_climbed_from_entry_ladder(history, runner, entry)
    ):
        add(
            kind="descend_route",
            key_code=DOWN_KEYCODE,
            ticks=6,
            score=fixed_score("descend_route.ladder_entry"),
            target={"x": entry_x, "y": entry_y, "tile": entry.get("tile", "H")},
            reason="runner is aligned above an active ladder; descend to enter its route",
        )
    if analysis.get("goldComplete"):
        return
    lower_gold = [
        item
        for item in analysis["nearestGold"]
        if item.get("source") != "guard"
        and runner_y is not None
        and _to_int(item.get("y")) is not None
        and int(item["y"]) > runner_y
    ]
    if not lower_gold:
        return
    same_column_target = next(
        (item for item in lower_gold if item.get("direction") == "same"), None
    )
    if same_column_target and runner.get("action") == "fall":
        add(
            kind="descend_route",
            key_code=STOP_KEYCODE,
            ticks=8,
            score=fixed_score("descend_route.already_falling"),
            target={"x": same_column_target["x"], "y": same_column_target["y"], "tile": "$"},
            reason="runner is already falling in the target gold column",
        )
    elif same_column_target and movement.get("currentTile") == "-":
        add(
            kind="descend_route",
            key_code=DOWN_KEYCODE,
            ticks=8,
            score=fixed_score("descend_route.rope"),
            target={"x": same_column_target["x"], "y": same_column_target["y"], "tile": "$"},
            reason="runner is on rope above the target gold column",
        )
    if movement.get("canMoveDown"):
        target = lower_gold[0]
        add(
            kind="descend_route",
            key_code=DOWN_KEYCODE,
            ticks=8,
            score=fixed_score("descend_route.same_column") if target.get("direction") == "same" else fixed_score("descend_route.other_column"),
            target={"x": target["x"], "y": target["y"], "tile": "$"},
            reason="down movement is valid and remaining gold is below",
        )


def recent_ladder_ascent(
    snapshot: dict[str, Any], history: list[dict[str, Any]],
) -> tuple[int, int, int] | None:
    """Find a fresh ascent followed only by same-row ladder-alignment inputs."""
    fields = ("x", "y", "xOffset", "yOffset")
    pose = tuple(_to_int(_dict(snapshot.get("runner")).get(k)) for k in fields)
    tick = _to_int(snapshot.get("tick"))
    if None in pose or tick is None:
        return None
    row = pose[1]
    for item in reversed(history[-24:]):
        item = _dict(item)
        before, after = (_dict(item.get(moment)) for moment in ("before", "after"))
        a, b = (tuple(_to_int(_dict(state.get("runner")).get(k)) for k in fields)
                for state in (before, after))
        if (
            None in a or None in b or b != pose or _to_int(item.get("afterTick")) != tick
            or _to_int(before.get("goldCount")) != 0 or _to_int(after.get("goldCount")) != 0
        ):
            return None
        kind = str(item.get("candidateId") or "")
        key = _to_int(item.get("keyCode"))
        if (
            kind.startswith(("climb_ladder_", "exit_ladder_route_"))
            and key == UP_KEYCODE and a[0] == b[0] and a[1] > b[1] == row
        ):
            return b[0], b[1], a[1]
        if not (kind.startswith("align_ladder_") and key in {LEFT_KEYCODE, RIGHT_KEYCODE}
                and a[1] == b[1] == row):
            return None
        pose, tick = a, _to_int(item.get("tick"))
    return None


def just_climbed_from_entry_ladder(
    history: list[dict[str, Any]],
    runner: dict[str, Any],
    entry: dict[str, Any],
) -> bool:
    if not history:
        return False
    latest = _dict(history[-1])
    before_runner = _dict(_dict(latest.get("before")).get("runner"))
    after_runner = _dict(_dict(latest.get("after")).get("runner"))
    return bool(
        str(latest.get("candidateId") or "").startswith(
            ("climb_ladder_", "exit_ladder_route_")
        )
        and _to_int(latest.get("keyCode")) == UP_KEYCODE
        and _to_int(before_runner.get("x")) == _to_int(entry.get("x"))
        and _to_int(before_runner.get("y")) == _to_int(entry.get("ladderY"))
        and _to_int(after_runner.get("x")) == _to_int(runner.get("x"))
        and _to_int(after_runner.get("y")) == _to_int(runner.get("y"))
    )


def add_god_mode_progress_candidate(add, analysis: dict[str, Any]) -> None:
    movement = analysis["movement"]
    for target in [*analysis["nearestGold"], *analysis["rowLadders"]]:
        if target.get("source") == "guard":
            continue
        direction = target.get("direction")
        if direction not in {"left", "right"}:
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        tile = target.get("tile", "$")
        add(
            kind="god_mode_progress",
            key_code=key_code,
            ticks=8,
            score=fixed_score("god_mode_progress.loop_active") if analysis.get("loopReport", {}).get("active") else fixed_score("god_mode_progress.default"),
            target={"x": target["x"], "y": target["y"], "tile": tile},
            reason="god mode is active; progress outranks survival spacing",
        )
        return


def add_low_risk_horizontal_progress_candidate(add, analysis: dict[str, Any]) -> None:
    target = _dict(analysis.get("goldTarget"))
    direction = target.get("direction")
    if direction not in {"left", "right"}:
        return
    movement = _dict(analysis.get("movement"))
    if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
        return
    add(
        kind="low_risk_horizontal_progress",
        key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
        ticks=4,
        score=fixed_score("low_risk_horizontal_progress.base"),
        target={"x": target.get("x"), "y": target.get("y"), "tile": target.get("tile", "$")},
        reason=(
            f"no structured route is available under low guard risk; move {direction} "
            "briefly toward the remaining gold and reassess"
        ),
    )


# Candidate families: environment

def add_wait_and_recheck_candidate(add) -> None:
    add(
        kind="wait_and_recheck",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=fixed_score("wait_and_recheck.base"),
        reason="no ordinary candidate is available; wait briefly and recheck",
        candidate_id="wait_and_recheck",
    )


def add_emergency_hold_candidate(add, risk: dict[str, Any]) -> None:
    guard = _dict(risk.get("pressureGuard"))
    relative_y = guard.get("relativeY")
    signature = "_".join(
        str(guard.get(key, "unknown"))
        for key in ("id", "x", "y", "xOffset", "yOffset", "motion")
    )
    add(
        kind="emergency_hold",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=fixed_score("emergency_hold.base"),
        reason=(
            f"all ordinary actions are filtered while the pressure guard is {relative_y}"
            if relative_y in {"above", "below"}
            else "no physically valid guard-safe action remains; use a bounded emergency hold"
        ),
        candidate_id=f"emergency_hold_{signature}",
    )


# Shared candidate helpers

def ladder_progress_direction(snapshot: dict[str, Any], analysis: dict[str, Any]) -> str | None:
    """Prefer the sole target-side opening of a bounded ladder shaft at low risk."""
    if analysis.get("goldComplete") or _dict(analysis.get("risk")).get("risk") != "low":
        return None
    runner = _dict(analysis.get("runner"))
    target = _dict(analysis.get("goldTarget"))
    x, y, target_x = (_to_int(runner.get("x")), _to_int(runner.get("y")),
                      _to_int(target.get("x")))
    rows = snapshot.get("terrainGrid")
    if (x is None or y is None or target_x is None or target_x == x
        or _to_int(target.get("y")) is None or not isinstance(rows, list)):
        return None
    side = -1 if target_x < x else 1
    def cell(px: int, py: int) -> str | None:
        return rows[py][px] if (0 <= py < len(rows) and isinstance(rows[py], str)
                               and 0 <= px < len(rows[py])) else None
    def opening(delta: int) -> bool | None:
        py = y + delta
        while cell(x, py) == "H":
            neighbor = cell(x + side, py)
            if neighbor in {" ", "H", "-", "$"}:
                return True
            if neighbor not in {"#", "@"}:
                return None
            py += delta
        # Unknown terrain and falling routes cannot establish a closed shaft.
        if cell(x, py) in {" ", "-"} and cell(x + side, py) in {" ", "H", "-", "$"}:
            return True
        return False if cell(x, py) in {"#", "@"} else None
    movement = _dict(analysis.get("movement"))
    ladder = _dict(analysis.get("ladder"))
    down = opening(1)
    if ladder.get("onDownEntry") and down is False:
        return "horizontal" if movement.get("canMoveLeft" if side < 0 else "canMoveRight") else None
    if not ladder.get("onLadder") or cell(x + side, y) not in {"#", "@"}:
        return None
    up = opening(-1)
    if up is True and down is False and movement.get("canMoveUp"):
        return "up"
    if down is True and up is False and movement.get("canMoveDown"):
        return "down"
    return None


def choose_ladder_direction(
    snapshot: dict[str, Any], analysis: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    runner_y = _to_int(analysis["runner"].get("y")) or 0
    if bool(analysis["goldComplete"]):
        return "up"
    route_direction = analysis.get("ladderProgressDirection")
    if route_direction in {"up", "down"}:
        return route_direction
    target = _dict(analysis.get("goldTarget"))
    target_y = _to_int(target.get("y"))
    if target_y is None and _dict(analysis.get("risk")).get("risk") == "low" and history:
        latest = _dict(history[-1])
        fields = ("x", "y", "xOffset", "yOffset")
        before, after, runner = (
            {field: _to_int(actor.get(field)) for field in fields}
            for actor in (
                _dict(_dict(latest.get("before")).get("runner")),
                _dict(_dict(latest.get("after")).get("runner")),
                _dict(analysis.get("runner")),
            )
        )
        known = all(value is not None for actor in (before, after, runner)
                    for value in actor.values())
        key = _to_int(latest.get("keyCode"))
        direction = "down" if key == DOWN_KEYCODE else "up"
        if (
            known and key in {UP_KEYCODE, DOWN_KEYCODE}
            and str(latest.get("candidateId") or "").startswith(("climb_ladder_", "descend_route_"))
            and latest.get("afterTick") == snapshot.get("tick")
            and before["x"] == after["x"]
            and all(after[field] == runner[field] for field in fields)
            and ((after["y"] - before["y"]) * 40 + after["yOffset"] - before["yOffset"])
                * (1 if key == DOWN_KEYCODE else -1) > 0
            and _dict(analysis.get("movement")).get("canMoveDown" if direction == "down" else "canMoveUp") is True
        ):
            return direction
    if target_y is not None and target_y != runner_y:
        preferred = "up" if target_y < runner_y else "down"
        opposite = "down" if preferred == "up" else "up"
        movement = _dict(analysis.get("movement"))
        if (
            _dict(analysis.get("risk")).get("risk") == "low"
            and movement.get("canMoveUp" if preferred == "up" else "canMoveDown") is False
            and movement.get("canMoveDown" if opposite == "down" else "canMoveUp") is True
        ):
            return opposite
        return preferred
    return "up" if runner_y > 0 else "down"


def find_gold_target(nearest_gold: list[dict[str, Any]]) -> dict[str, Any] | None:
    for gold in nearest_gold:
        if gold.get("source") == "guard":
            continue
        return {
            "x": gold.get("x"),
            "y": gold.get("y"),
            "tile": "$",
            "source": gold.get("source", "visible"),
            "sameRow": gold.get("sameRow"),
            "distance": gold.get("distance"),
            "direction": gold.get("direction"),
        }
    return None


def ladder_direction_toward_target(analysis: dict[str, Any], direction: str) -> bool:
    runner_y = _to_int(analysis["runner"].get("y"))
    target_y = _to_int(_dict(analysis.get("goldTarget")).get("y"))
    if runner_y is None or target_y is None:
        return False
    return (direction == "up" and target_y < runner_y) or (direction == "down" and target_y > runner_y)


def ladder_reason(ladder: dict[str, Any], direction: str, target: dict[str, Any]) -> str:
    location = "revealed exit ladder" if ladder.get("onExitLadder") else "visible ladder"
    if target:
        return (
            f"Runner is on a {location}. "
            f"Climb {direction} toward visible gold at ({target.get('x')},{target.get('y')})."
        )
    return f"Runner is on a {location}; use {direction} to change row."


def ticks_for_alignment(distance: int) -> int:
    if distance <= 1:
        return 4
    if distance == 2:
        return 6
    return 8


def make_candidate_id(kind: str, target: dict[str, Any] | None, action_name: str) -> str:
    if target:
        x = target.get("x")
        y = target.get("y")
        if x is not None and y is not None:
            return f"{kind}_{x}_{y}_{action_name}"
    return f"{kind}_{action_name}"


def _trap_hole_between_pressure_guard(
    movement: dict[str, Any], risk: dict[str, Any]
) -> dict[str, Any]:
    guard = _dict(risk.get("pressureGuard"))
    side = guard.get("relativeX")
    if side not in {"left", "right"}:
        return {}
    if guard.get("motion") in {"up", "climb_out"}:
        return {}
    detail = _dict(_dict(movement.get("details")).get(side))
    hole = _dict(detail.get("openHole"))
    if hole.get("occupiedByTrappedGuard"):
        return {}
    distance = _to_int(hole.get("distance"))
    guard_x = _to_int(guard.get("x"))
    hole_x = _to_int(hole.get("x"))
    if guard_x is None or hole_x is None:
        return {}
    hole_y = _to_int(hole.get("y"))
    guard_y_offset = _to_int(guard.get("yOffset"))
    if distance == 3:
        # A farther trap covers only an immediately approaching guard or its
        # observed entry. Do not dig a redundant hole closer to the runner.
        same_row_entry = bool(
            guard.get("relativeY") == "same"
            and hole_y is not None
            and _to_int(guard.get("y")) == hole_y - 1
            and (
                (
                    guard.get("closing")
                    and guard.get("motion") == ("right" if side == "left" else "left")
                    and abs(guard_x - hole_x) <= 1
                )
                or (
                    guard.get("motion") == "fall"
                    and guard_x == hole_x
                    and _to_int(guard.get("xOffset")) == 0
                    and guard_y_offset is not None
                    and guard_y_offset >= 0
                )
            )
        )
        falling_below = (
            guard.get("relativeY") == "below" and guard.get("motion") == "fall"
        )
        if (
            movement.get("godMode")
            or _to_int(hole.get("frameIndex")) != 0
            or not (same_row_entry or falling_below)
        ):
            return {}
    elif distance not in {1, 2}:
        return {}
    if guard.get("relativeY") != "same":
        # Keep the trap gate through the row change, until capture completes.
        if not (
            not movement.get("godMode")
            and guard.get("relativeY") == "below"
            and guard.get("motion") == "fall"
            and guard_x == hole_x
            and hole_y is not None
            and _to_int(guard.get("y")) == hole_y
            and _to_int(guard.get("xOffset")) == 0
            and guard_y_offset is not None
            and guard_y_offset < 0
        ):
            return {}
    guard_beyond_hole = guard_x <= hole_x if side == "left" else guard_x >= hole_x
    if not guard_beyond_hole:
        return {}
    return {"side": side, "hole": hole, "guard": guard}


def is_action_physically_valid(
    action: dict[str, Any],
    movement: dict[str, Any],
    dig: dict[str, Any],
    *,
    candidate_kind: str | None = None,
    runner_x_offset: int | None = None,
) -> bool:
    key_code = action.get("keyCode")
    if key_code == STOP_KEYCODE:
        return True
    if key_code == LEFT_KEYCODE:
        if _action_reaches_open_hole(
            action,
            movement,
            "left",
            candidate_kind,
            runner_x_offset=runner_x_offset,
        ):
            return False
        return bool(movement.get("canMoveLeft"))
    if key_code == RIGHT_KEYCODE:
        if _action_reaches_open_hole(
            action,
            movement,
            "right",
            candidate_kind,
            runner_x_offset=runner_x_offset,
        ):
            return False
        return bool(movement.get("canMoveRight"))
    if key_code == UP_KEYCODE:
        return bool(movement.get("canMoveUp")) or bool(
            candidate_kind == "exit_ladder_route" and movement.get("canFinishExitClimb")
        ) or bool(
            candidate_kind == "collect_current_tile_gold"
            and movement.get("canFinishLadderClimb")
        ) or bool(
            candidate_kind == "retreat_from_guard"
            and int(action.get("ticks") or 1) <= 2
            and movement.get("canFinishLadderClimb")
            and movement.get("currentTile") not in {"H", "S"}
        )
    if key_code == DOWN_KEYCODE:
        return bool(movement.get("canMoveDown"))
    if key_code == DIG_LEFT_KEYCODE:
        return bool(dig.get("canDigLeft")) or bool(
            candidate_kind == "defensive_dig"
            and _dict(dig.get("left")).get("canDefensiveDig")
            and _dict(dig.get("left")).get("guardCouldFall")
        )
    if key_code == DIG_RIGHT_KEYCODE:
        return bool(dig.get("canDigRight")) or bool(
            candidate_kind == "defensive_dig"
            and _dict(dig.get("right")).get("canDefensiveDig")
            and _dict(dig.get("right")).get("guardCouldFall")
        )
    return False


def limit_horizontal_ticks_before_open_hole(
    action: dict[str, Any], movement: dict[str, Any], candidate_kind: str
) -> dict[str, Any]:
    if candidate_kind in {
        "route_access_follow",
        "collect_current_tile_gold",
        "escape_through_open_hole",
    }:
        return action
    key_code = action.get("keyCode")
    direction = "left" if key_code == LEFT_KEYCODE else "right" if key_code == RIGHT_KEYCODE else None
    if direction is None:
        return action
    detail = _dict(_dict(movement.get("details")).get(direction))
    distance = _to_int(detail.get("openDugHoleDistance"))
    if distance is None:
        open_hole = _dict(detail.get("openHole"))
        if not open_hole.get("occupiedByTrappedGuard"):
            distance = _to_int(open_hole.get("distance"))
    if distance is None or distance <= 1:
        return action
    safe_ticks = (distance - 1) * 4
    return {**action, "ticks": min(int(action.get("ticks") or 1), safe_ticks)}


def apply_prospective_horizontal_endpoint_safety(
    action: dict[str, Any],
    analysis: dict[str, Any],
    candidate_kind: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    safe_action, _detail = _apply_prospective_horizontal_endpoint_safety(
        action,
        analysis,
        candidate_kind,
        snapshot=snapshot,
    )
    return safe_action


def _apply_prospective_horizontal_endpoint_safety(
    action: dict[str, Any],
    analysis: dict[str, Any],
    candidate_kind: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if analysis.get("godMode") or candidate_kind not in PROSPECTIVE_HORIZONTAL_KINDS:
        return action, None
    key_code = action.get("keyCode")
    if key_code not in {LEFT_KEYCODE, RIGHT_KEYCODE}:
        return action, None
    risk = _dict(analysis.get("risk"))
    guard = _dict(risk.get("pressureGuard"))
    if guard.get("risk") not in GUARD_PRESSURE_RISKS or not guard.get("closing"):
        return action, None
    direction = "left" if key_code == LEFT_KEYCODE else "right"
    guard_behind = (
        guard.get("relativeX") == "right"
        if direction == "left"
        else guard.get("relativeX") == "left"
    )
    if not guard_behind:
        return action, None

    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    x_offset = _to_int(runner.get("xOffset")) or 0
    level_width = terrain_grid_width(snapshot) if snapshot is not None else None
    edge_position_ahead = bool(
        runner_x is not None
        and (
            (direction == "left" and runner_x <= 1)
            or (
                direction == "right"
                and level_width is not None
                and runner_x >= level_width - 2
            )
        )
    )
    edge_vertical_escape = False
    if edge_position_ahead and snapshot is not None and runner_x is not None:
        projected_runner = {
            **_dict(snapshot.get("runner")),
            "x": runner_x - 1 if direction == "left" else runner_x + 1,
            "xOffset": 0,
            "yOffset": 0,
            "actionName": "stop",
        }
        projected_movement = get_movement_affordance(
            {**snapshot, "runner": projected_runner}
        )
        edge_vertical_escape = bool(
            projected_movement.get("canMoveUp") or projected_movement.get("canMoveDown")
        )
    edge_ahead = edge_position_ahead and not edge_vertical_escape
    movement = _dict(analysis.get("movement"))
    detail = _dict(_dict(movement.get("details")).get(direction))
    hole = _dict(detail.get("openHole"))
    hole_distance = _to_int(hole.get("distance"))
    hole_y = _to_int(hole.get("y"))
    terrain_height = _to_int(movement.get("terrainHeight"))
    bottom_hole_ahead = bool(
        hole_distance is not None
        and hole_distance <= 2
        and not hole.get("occupiedByTrappedGuard")
        and hole_y is not None
        and terrain_height is not None
        and hole_y >= terrain_height - 1
    )
    if not (edge_ahead or bottom_hole_ahead):
        return action, None

    obstacle = "bottom-row hole" if bottom_hole_ahead else "level edge"
    moving_toward_center = bool(
        (direction == "left" and x_offset > 0)
        or (direction == "right" and x_offset < 0)
    )
    if not moving_toward_center:
        return (
            None,
            f"moving {direction} would reach the {obstacle} with a closing guard behind",
        )
    centering_ticks = max(
        1, (abs(x_offset) + LEGACY_SUBTILE_STEP - 1) // LEGACY_SUBTILE_STEP
    )
    if centering_ticks >= int(action.get("ticks") or 1):
        return action, None
    return (
        {
            **action,
            "ticks": centering_ticks,
            "reason": (
                f"{action.get('reason', '')}; stop centered before the {obstacle} because a closing "
                "guard is behind"
            )[:500],
        },
        None,
    )


def _action_reaches_open_hole(
    action: dict[str, Any],
    movement: dict[str, Any],
    direction: str,
    candidate_kind: str | None,
    *,
    runner_x_offset: int | None = None,
) -> bool:
    if candidate_kind in {
        "route_access_follow",
        "collect_current_tile_gold",
        "escape_through_open_hole",
    }:
        return False
    detail = _dict(_dict(movement.get("details")).get(direction))
    distance = _to_int(detail.get("openDugHoleDistance"))
    if distance is None:
        open_hole = _dict(detail.get("openHole"))
        if not open_hole.get("occupiedByTrappedGuard"):
            distance = _to_int(open_hole.get("distance"))
    if distance is None:
        return False
    runner_x_offset = _to_int(runner_x_offset)
    moving_toward_center = bool(
        (direction == "left" and (runner_x_offset or 0) > 0)
        or (direction == "right" and (runner_x_offset or 0) < 0)
    )
    centering_ticks = (
        max(1, (abs(runner_x_offset) + LEGACY_SUBTILE_STEP - 1) // LEGACY_SUBTILE_STEP)
        if runner_x_offset
        else 0
    )
    if distance == 1 and moving_toward_center and int(action.get("ticks") or 1) <= centering_ticks:
        return False
    action_span = max(1, (int(action.get("ticks") or 1) + 3) // 4)
    return distance <= action_span


def low_risk_guard_clearance_score_bonus(
    action: dict[str, Any],
    analysis: dict[str, Any],
    *,
    candidate_kind: str | None = None,
) -> int:
    """Reward directional progress that does not consume low-risk clearance."""
    if (
        analysis.get("godMode")
        or candidate_lane(candidate_kind) != "progress"
        or _dict(analysis.get("risk")).get("risk") != "low"
    ):
        return 0
    key_code = _to_int(action.get("keyCode"))
    runner_vector = {
        LEFT_KEYCODE: (-1, 0),
        RIGHT_KEYCODE: (1, 0),
        UP_KEYCODE: (0, -1),
        DOWN_KEYCODE: (0, 1),
    }.get(key_code)
    if runner_vector is None:
        return 0
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return 0

    active_guards = []
    for item in _dict(analysis.get("risk")).get("guards") or []:
        guard = _dict(item)
        guard_x = _to_int(guard.get("x"))
        guard_y = _to_int(guard.get("y"))
        if (
            guard.get("risk") != "low"
            or guard.get("motion") == "in_hole"
            or guard_x is None
            or guard_y is None
        ):
            continue
        active_guards.append((guard, guard_x, guard_y))
    if not active_guards:
        return 0

    ticks = max(1, _to_int(action.get("ticks")) or 1)
    guard_vectors = {
        "left": (-1, 0),
        "right": (1, 0),
        "up": (0, -1),
        "down": (0, 1),
        "fall": (0, 1),
    }
    for guard, guard_x, guard_y in active_guards:
        guard_vector = guard_vectors.get(str(guard.get("motion")), (0, 0))
        current_distance = abs(guard_x - runner_x) + abs(guard_y - runner_y)
        for tick in range(1, ticks + 1):
            progress = tick / GUARD_CLEARANCE_TICKS_PER_CELL
            projected_runner_x = runner_x + runner_vector[0] * progress
            projected_runner_y = runner_y + runner_vector[1] * progress
            projected_guard_x = guard_x + guard_vector[0] * progress
            projected_guard_y = guard_y + guard_vector[1] * progress
            projected_distance = abs(projected_guard_x - projected_runner_x) + abs(
                projected_guard_y - projected_runner_y
            )
            if projected_distance < current_distance:
                return 0
    return LOW_RISK_GUARD_CLEARANCE_BONUS


def medium_cross_row_clearance_score_penalty(
    action: dict[str, Any],
    analysis: dict[str, Any],
    *,
    candidate_kind: str | None = None,
) -> int:
    """Demote horizontal progress that consumes the nearest medium-risk clearance."""
    if analysis.get("godMode") or candidate_lane(candidate_kind) != "progress":
        return 0
    risk = _dict(analysis.get("risk"))
    pressure_guard = _dict(risk.get("pressureGuard"))
    if (
        risk.get("risk") != "medium"
        or pressure_guard.get("risk") != "medium"
        or pressure_guard.get("relativeY") not in {"above", "below"}
    ):
        return 0
    key_code = _to_int(action.get("keyCode"))
    runner_vector = {
        LEFT_KEYCODE: (-1, 0),
        RIGHT_KEYCODE: (1, 0),
    }.get(key_code)
    if runner_vector is None:
        return 0
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return 0

    active_guards = []
    for item in risk.get("guards") or []:
        guard = _dict(item)
        guard_x = _to_int(guard.get("x"))
        guard_y = _to_int(guard.get("y"))
        if (
            guard.get("motion") == "in_hole"
            or guard_x is None
            or guard_y is None
        ):
            continue
        active_guards.append((guard, guard_x, guard_y))
    if not active_guards:
        return 0

    guard_vectors = {
        "left": (-1, 0),
        "right": (1, 0),
        "up": (0, -1),
        "down": (0, 1),
        "fall": (0, 1),
    }
    current_minimum = min(
        abs(guard_x - runner_x) + abs(guard_y - runner_y)
        for _, guard_x, guard_y in active_guards
    )
    ticks = max(1, _to_int(action.get("ticks")) or 1)
    for tick in range(1, ticks + 1):
        progress = tick / GUARD_CLEARANCE_TICKS_PER_CELL
        projected_runner_x = runner_x + runner_vector[0] * progress
        projected_runner_y = runner_y
        projected_minimum = min(
            abs(guard_x + guard_vectors.get(str(guard.get("motion")), (0, 0))[0] * progress - projected_runner_x)
            + abs(guard_y + guard_vectors.get(str(guard.get("motion")), (0, 0))[1] * progress - projected_runner_y)
            for guard, guard_x, guard_y in active_guards
        )
        if projected_minimum < current_minimum:
            return MEDIUM_CROSS_ROW_CLEARANCE_PENALTY
    return 0


def _short_medium_horizontal_clearance(
    action: dict[str, Any], analysis: dict[str, Any],
) -> bool:
    """Bound both actors' possible approach before the next decision."""
    risk = _dict(analysis.get("risk"))
    ticks = _to_int(action.get("ticks"))
    if (
        risk.get("risk") != "medium"
        or _dict(risk.get("pressureGuard")).get("risk") != "medium"
        or action.get("keyCode") not in {LEFT_KEYCODE, RIGHT_KEYCODE}
        or ticks is None or not 1 <= ticks <= 4
    ):
        return False
    runner = _dict(analysis.get("runner"))
    guards = [_dict(risk.get("pressureGuard")), *(risk.get("guards") or [])]
    for item in guards:
        guard = _dict(item)
        if guard.get("risk") in {"high", "critical"}:
            return False
        if guard.get("risk") != "medium":
            continue
        coordinates = [_to_int(actor.get(key)) for actor in (runner, guard)
                       for key in ("x", "xOffset")]
        if any(value is None for value in coordinates):
            return False
        rx, ro, gx, go = coordinates
        # Classic tiles are 40 units wide. At most one 8-unit movement per
        # actor per tick; assume both approach, even if currently moving away.
        separation = abs((gx - rx) * 40 + go - ro)
        if separation - 2 * LEGACY_SUBTILE_STEP * ticks < 80:
            return False
    return True


def action_guard_safety_rejection_detail(
    action: dict[str, Any],
    analysis: dict[str, Any],
    *,
    candidate_kind: str | None = None,
) -> str | None:
    if analysis.get("godMode"):
        return None
    risk = _dict(analysis.get("risk"))
    guard = _dict(risk.get("pressureGuard"))
    key_code = action.get("keyCode")
    runner_offset = _to_int(_dict(analysis.get("runner")).get("xOffset"))
    # Tile-level "same column" can hide movement into a rising guard's center.
    # Apply to every horizontal candidate, including secondary threats.
    if key_code in {LEFT_KEYCODE, RIGHT_KEYCODE} and runner_offset is not None:
        for nearby in [guard, *(risk.get("guards") or [])]:
            nearby = _dict(nearby)
            guard_offset = _to_int(nearby.get("xOffset"))
            if (
                nearby.get("risk") in {"high", "critical"}
                and nearby.get("motion") == "climb_out"
                and nearby.get("relativeX") == "same"
                and nearby.get("relativeY") == "below"
                and _to_int(nearby.get("distance")) == 1
                and guard_offset is not None
                and (
                    (key_code == RIGHT_KEYCODE and runner_offset < guard_offset)
                    or (key_code == LEFT_KEYCODE and runner_offset > guard_offset)
                )
            ):
                return "horizontal movement approaches the center of an adjacent guard climbing out below"
    if guard.get("risk") not in GUARD_PRESSURE_RISKS:
        return None
    side = guard.get("relativeX")
    action_name = (
        ACTION_NAMES.get(key_code, f"key {key_code}")
        if isinstance(key_code, int)
        else f"key {key_code}"
    )
    if guard.get("risk") in {"high", "critical"} and side in {"left", "right"}:
        for nearby in risk.get("guards") or []:
            nearby = _dict(nearby)
            nearby_side = nearby.get("relativeX")
            nearby_distance = _to_int(nearby.get("distance"))
            if (
                nearby.get("relativeY") == "same"
                and nearby_side in {"left", "right"}
                and nearby_side != side
                and nearby.get("closing")
                and nearby_distance is not None
                and nearby_distance <= 7
                and (
                    (nearby_side == "left" and key_code == LEFT_KEYCODE)
                    or (nearby_side == "right" and key_code == RIGHT_KEYCODE)
                )
            ):
                return (
                    f"{action_name} moves toward a second closing same-row guard "
                    f"on the {nearby_side} at distance {nearby_distance}"
                )
    short_medium_clearance = _short_medium_horizontal_clearance(action, analysis)
    for nearby in risk.get("guards") or []:
        nearby = _dict(nearby)
        if (
            nearby.get("relativeY") != "same"
            or nearby.get("risk") not in GUARD_PRESSURE_RISKS
            or (nearby.get("risk") == "medium" and short_medium_clearance)
        ):
            continue
        if nearby.get("relativeX") == "left" and key_code == LEFT_KEYCODE:
            return (
                f"left moves toward a same-row {nearby.get('risk')} risk guard "
                f"at distance {_to_int(nearby.get('distance')) or 'unknown'}"
            )
        if nearby.get("relativeX") == "right" and key_code == RIGHT_KEYCODE:
            return (
                f"right moves toward a same-row {nearby.get('risk')} risk guard "
                f"at distance {_to_int(nearby.get('distance')) or 'unknown'}"
            )
    if (
        candidate_kind == "evade_edge_ladder"
        and guard.get("relativeY") == "below"
        and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE}
    ):
        return None
    if (
        candidate_kind == "evade_open_hole"
        and guard.get("relativeY") in {"above", "below"}
        and not guard.get("closing")
        and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE}
    ):
        return None
    if (
        guard.get("risk") == "medium"
        and guard.get("relativeY") in {"above", "below"}
        and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE}
    ):
        return None
    clear_same_row = short_medium_clearance and guard.get("relativeY") == "same"
    if side == "left" and key_code == LEFT_KEYCODE and not clear_same_row:
        return f"left moves toward the {guard.get('risk')} risk pressure guard on the left"
    if side == "right" and key_code == RIGHT_KEYCODE and not clear_same_row:
        return f"right moves toward the {guard.get('risk')} risk pressure guard on the right"
    relative_y = guard.get("relativeY")
    if (
        relative_y == "same"
        and guard.get("risk") in {"high", "critical"}
        and (_to_int(guard.get("distance")) or 0) <= 1
        and guard.get("motion") in {"up", "climb_out"}
        and key_code == UP_KEYCODE
    ):
        return "up moves toward an adjacent same-row guard climbing into the runner's cell"
    if candidate_kind == "emergency_hold" and key_code == STOP_KEYCODE:
        return None
    if (
        candidate_kind == "wait_for_dig_completion"
        and key_code == STOP_KEYCODE
        and _dict(analysis.get("activeDig")).get("active")
    ):
        return None
    if (
        candidate_kind == "wait_for_trap_resolution"
        and key_code == STOP_KEYCODE
        and _trap_hole_between_pressure_guard(
            _dict(analysis.get("movement")), risk
        )
    ):
        return None
    clear_medium_cross_row_climb = _medium_cross_row_climb_has_clearance(
        action,
        analysis,
        candidate_kind=candidate_kind,
    )
    if (
        relative_y == "above"
        and key_code == UP_KEYCODE
        and not clear_medium_cross_row_climb
    ):
        return f"up moves toward the {guard.get('risk')} risk pressure guard above"
    if (
        relative_y == "below"
        and key_code == DOWN_KEYCODE
        and not clear_medium_cross_row_climb
    ):
        return f"down moves toward the {guard.get('risk')} risk pressure guard below"
    runner_action = _dict(analysis.get("runner")).get("action")
    if (
        guard.get("risk") in {"high", "critical"}
        and key_code == STOP_KEYCODE
        and runner_action != "fall"
    ):
        return (
            f"stop remains exposed to {guard.get('risk')} guard pressure while the runner "
            "is not falling"
        )
    # A same-row primary threat must not hide a secondary guard approaching
    # along any vertical movement, regardless of candidate intent.
    # Preserve every earlier rejection cause and safety exception.
    if key_code in {UP_KEYCODE, DOWN_KEYCODE}:
        movement_y = "above" if key_code == UP_KEYCODE else "below"
        approaching_motions = (
            {"down", "fall"} if key_code == UP_KEYCODE else {"up", "climb_out"}
        )
        for nearby in risk.get("guards") or []:
            nearby = _dict(nearby)
            if (
                nearby.get("id") is not None
                and nearby.get("id") != guard.get("id")
                and nearby.get("risk") in {"high", "critical"}
                and nearby.get("relativeX") == "same"
                and nearby.get("relativeY") == movement_y
                and nearby.get("motion") in approaching_motions
            ):
                return (
                    f"{action_name} moves toward an aligned approaching "
                    f"secondary {nearby.get('risk')} guard {movement_y}"
                )
    return None


def _medium_cross_row_climb_has_clearance(
    action: dict[str, Any],
    analysis: dict[str, Any],
    *,
    candidate_kind: str | None,
) -> bool:
    """Allow one short ladder step when medium cross-row pressure is well separated."""
    if candidate_kind != "climb_ladder":
        return False
    risk = _dict(analysis.get("risk"))
    pressure_guard = _dict(risk.get("pressureGuard"))
    if pressure_guard.get("risk") != "medium":
        return False
    key_code = action.get("keyCode")
    relative_y = pressure_guard.get("relativeY")
    if not (
        (relative_y == "above" and key_code == UP_KEYCODE)
        or (relative_y == "below" and key_code == DOWN_KEYCODE)
    ):
        return False
    ticks = _to_int(action.get("ticks"))
    if ticks is None or ticks < 1 or ticks > MEDIUM_CROSS_ROW_CLIMB_MAX_TICKS:
        return False
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return False
    endpoint_y = runner_y + (-1 if key_code == UP_KEYCODE else 1)
    nearby_guards = [pressure_guard]
    nearby_guards.extend(
        _dict(item)
        for item in risk.get("guards") or []
        if isinstance(item, dict) and item.get("id") != pressure_guard.get("id")
    )
    for nearby in nearby_guards:
        if nearby.get("risk") not in GUARD_PRESSURE_RISKS:
            continue
        if nearby.get("risk") in {"high", "critical"}:
            return False
        guard_x = _to_int(nearby.get("x"))
        guard_y = _to_int(nearby.get("y"))
        if guard_x is None or guard_y is None:
            return False
        horizontal_clearance = abs(guard_x - runner_x)
        projected_distance = horizontal_clearance + abs(guard_y - endpoint_y)
        if (
            projected_distance <= 5
            and horizontal_clearance
            < MEDIUM_CROSS_ROW_CLIMB_MIN_HORIZONTAL_CLEARANCE
        ):
            return False
    return True


def is_action_guard_safe(
    action: dict[str, Any],
    analysis: dict[str, Any],
    *,
    candidate_kind: str | None = None,
) -> bool:
    return (
        action_guard_safety_rejection_detail(
            action,
            analysis,
            candidate_kind=candidate_kind,
        )
        is None
    )


def limit_horizontal_ticks_under_guard_pressure(
    action: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    if analysis.get("godMode"):
        return action
    risk = _dict(analysis.get("risk"))
    guard = _dict(risk.get("pressureGuard"))
    if guard.get("risk") not in GUARD_PRESSURE_RISKS:
        return action
    if action.get("keyCode") not in {LEFT_KEYCODE, RIGHT_KEYCODE}:
        return action
    return {**action, "ticks": min(4, int(action.get("ticks") or 1))}


def _normalize_action(
    key_code: int,
    ticks: int,
    reason: str,
    *,
    max_ticks: int = AGENT_MAX_TICKS,
) -> dict[str, Any]:
    return {
        "keyCode": key_code,
        "ticks": max(1, min(max_ticks, int(ticks))),
        "reason": str(reason)[:500],
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def terrain_grid_width(snapshot: dict[str, Any]) -> int | None:
    if not isinstance(snapshot, dict):
        return None
    for key in ("grid", "terrainGrid"):
        rows = snapshot.get(key)
        if not isinstance(rows, list):
            continue
        widths = [len(row) for row in rows if isinstance(row, str) and row]
        if widths:
            return max(widths)
    return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
