"""Focused backend regressions; no model calls or production data writes."""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.candidates import generate_candidates, action_guard_safety_rejection_detail, choose_ladder_direction, add_ladder_alignment_candidates
from agent.loop_tools import build_loop_report, candidate_suppression_reason
from agent.reasoning_tools import get_dig_affordance
from agent.prompt import build_state_context, build_recent_progress, format_candidate, format_guard, format_ladder, format_route_access
from agent.traces import serialize_step_trace, summarize_state
from agent.candidates import add_descent_candidates


from sanity_backend import candidate_snapshot


def check_model_context():
    state = candidate_snapshot(guarded=True)
    for counter, expected in ((-1, False), (0, False), (12, True)):
        state["guards"][0]["hasGold"] = counter
        _, analysis = generate_candidates(state, [])
        context = build_state_context(state, analysis)
        assert context["threat"]["guardAssessments"][0]["carryingGold"] is expected
        assert context["threat"]["primaryThreat"]["approachingOnSameRow"] is True
        assert summarize_state(state, analysis)["guards"][0]["carryingGold"] is expected
        assert summarize_state(state)["guards"][0]["carryingGold"] is expected
    assert "carryingGold" not in format_guard({})
    context = build_state_context(state, {"movement": dict.fromkeys(
        ("canMoveLeft", "canMoveRight", "canMoveUp", "canMoveDown"), False)})
    assert context["movement"]["physicalDirections"] == []
    assert context["gold"]["visible"] == []
    assert "physicalDirections" not in build_state_context(state, {}).get("movement", {})
    access = format_route_access({"available": False, "followAvailable": True,
                                  "followAction": "right"})
    assert access["digAvailable"] is False and access["entryAvailable"] is True
    assert access["entryAction"] == "right"
    history = [{"candidateId": "align_ladder_4_1_right", "keyCode": 39, "ticks": 4,
                "before": {"runner": runner_pose(2, 1), "goldCount": 2},
                "after": {"runner": runner_pose(3, 1), "goldCount": 1}}]
    original = copy.deepcopy(history)
    recent = build_recent_progress(history)
    entry = recent["entries"][0]
    assert entry["issuedAction"] == {"name": "right", "ticks": 4}
    assert entry["tileChanged"] is True and entry["offsetChanged"] is False
    assert entry["remainingGoldDelta"] == -1
    repeated = recent["repeatedCandidate"]
    assert repeated["target"] == {"x": 4, "y": 1}
    assert repeated["targetDistanceReduced"] is True and repeated["targetTileReached"] is False
    assert history == original
    missing = build_recent_progress([{}])
    assert missing["entries"][0]["tileChanged"] is None
    assert missing["repeatedCandidate"]["targetDistanceReduced"] is None

def check_floor_separated_horizontal_pressure():
    for mirrored in (False, True):
        state = candidate_snapshot(exit_state=True)
        state["terrainGrid"] = state["grid"] = [
            "                  H         ", "                  H         ",
            "############################", "                            ",
            "############################",
        ]
        state["runner"].update(x=10, y=1, xOffset=8, actionName="right")
        state["guards"] = [{"id": 0, "x": 11, "y": 3, "xOffset": -16,
                            "yOffset": 0, "actionName": "left", "hasGold": 0}]
        key = 39
        if mirrored:
            key = 37
            state["terrainGrid"] = state["grid"] = [row[::-1] for row in state["grid"]]
            state["runner"].update(x=17, xOffset=-8, actionName="left")
            state["guards"][0].update(x=16, xOffset=16, actionName="right")
        original = copy.deepcopy(state)
        pool, analysis = generate_candidates(state, [])
        exit_action = next(c["action"] for c in pool if c["kind"] == "exit_ladder_route")
        assert exit_action == {"keyCode": key, "ticks": 4}
        assert action_guard_safety_rejection_detail(exit_action, analysis, snapshot=state) is None
        from agent.service import validate_or_fallback_candidate
        exit_candidate = next(c for c in pool if c["kind"] == "exit_ladder_route")
        selected, validation = validate_or_fallback_candidate(
            {"choice": {"candidateId": exit_candidate["id"]}}, pool, analysis, snapshot=state)
        assert selected == exit_candidate and not validation["fallbackUsed"]
        assert action_guard_safety_rejection_detail(exit_action, analysis) is not None
        assert action_guard_safety_rejection_detail({**exit_action, "ticks": 8}, analysis, snapshot=state)
        controls = []
        floor_x = state["runner"]["x"]
        for tile in (" ", "H", "-"):
            changed = copy.deepcopy(state)
            row = changed["grid"][2]
            changed["grid"][2] = row[:floor_x] + tile + row[floor_x + 1:]
            controls.append(changed)
        for field, value in (("openHoles", [{"x": floor_x, "y": 2}]),
                             ("openHoles", None), ("openHoles", [{}]),
                             ("terrainGrid", None), ("grid", None),
                             ("activeDig", {"active": True})):
            controls.append({**copy.deepcopy(state), field: value})
        for changes in ({"actionName": "up"}, {"actionName": "climb_out"},
                        {"y": 1}, {"y": 2}, {"yOffset": -9}, {"xOffset": None}):
            changed = copy.deepcopy(state)
            changed["guards"][0].update(changes)
            controls.append(changed)
        changed = copy.deepcopy(state)
        changed["runner"]["yOffset"] = 4
        controls.append(changed)
        for changed in controls:
            # Reuse the observed high-risk assessment to isolate the exception's
            # fail-closed evidence checks, including missing snapshot fields.
            altered = copy.deepcopy(analysis)
            altered["runner"].update({k: changed["runner"][k] for k in ("xOffset", "yOffset")})
            altered["risk"]["primaryThreat"].update({
                "motion": changed["guards"][0]["actionName"],
                **{k: changed["guards"][0][k] for k in ("y", "xOffset", "yOffset")}})
            assert action_guard_safety_rejection_detail(exit_action, altered, snapshot=changed)
        secondary = copy.deepcopy(analysis)
        secondary["risk"]["guards"].append({"risk": "high", "relativeY": "same",
            "relativeX": "right" if key == 39 else "left", "distance": 2})
        assert action_guard_safety_rejection_detail(exit_action, secondary, snapshot=state)
        secondary = copy.deepcopy(analysis)
        secondary["risk"]["guards"].append({
            **secondary["risk"]["primaryThreat"], "id": 1, "motion": "up"})
        assert action_guard_safety_rejection_detail(exit_action, secondary, snapshot=state)
        god_analysis = copy.deepcopy(analysis)
        god_analysis["godMode"] = True
        assert action_guard_safety_rejection_detail(exit_action, god_analysis, snapshot=state) is None
        assert state == original


def check_open_hole_escape():
    state = candidate_snapshot(guarded=True)
    state["terrainGrid"] = ["       ", "       ", "#######", "       ", "#######"]
    state["grid"] = ["       ", "       ", "### ###", "       ", "#######"]
    state["guards"][0].update(x=1, y=2, yOffset=-9, actionName="climb_out")
    hole = {"x": 3, "y": 2, "frameIndex": 0, "frameTime": 0}
    state["openHoles"] = [hole]
    pool, _ = generate_candidates(state, [])
    assert any(c["kind"] == "escape_through_open_hole" for c in pool)
    hole["frameIndex"] = 2
    closing, _ = generate_candidates(state, [])
    del hole["frameIndex"]
    unknown, _ = generate_candidates(state, [])
    for pool in (closing, unknown):
        assert pool and all(c["kind"] != "escape_through_open_hole" for c in pool)

def check_exit_context():
    state = candidate_snapshot(exit_state=True)
    pool, original = generate_candidates(state, [])
    state["exitTarget"] = {"x": 2, "y": 1, "tile": "S"}
    updated, analysis = generate_candidates(state, [])
    assert updated == pool and analysis["goldTarget"] == original["goldTarget"]
    assert build_state_context(state, analysis)["exitTarget"] == state["exitTarget"]
    trace = serialize_step_trace(
        snapshot=state, action=pool[0]["action"], candidates=pool,
        selected_candidate=pool[0], analysis=analysis,
        validation={"requestedCandidateId": pool[0]["id"], "fallbackUsed": False},
    )
    assert trace["state"]["exitTarget"] == state["exitTarget"]
    state["gold"]["complete"] = state["goldComplete"] = False
    _, analysis = generate_candidates(state, [])
    assert "exitTarget" not in build_state_context(state, analysis)

def check_recent_ladder_return():
    state = candidate_snapshot(exit_state=True)
    state["terrainGrid"] = state["grid"] = ["       ", "       ", "##H#H##", "  H H  ", "#######"]
    state["tick"] = 20
    before = {"runner": {"x": 2, "y": 3, "xOffset": 0, "yOffset": 0}, "goldCount": 0}
    arrived = {"runner": runner_pose(2, 1), "goldCount": 0}
    history = [{"candidateId": "exit_ladder_route_2_3_up", "keyCode": 38,
                "ticks": 20, "tick": 0, "afterTick": 20, "before": before, "after": arrived}]
    original = copy.deepcopy((state, history))
    control, _ = generate_candidates(state, [])
    changed, analysis = generate_candidates(state, history)
    action_keys = lambda pool: {c["id"]: (c["action"]["keyCode"], c["action"]["ticks"]) for c in pool}
    assert any(c["kind"] == "descend_route" for c in control)
    assert not any(c["kind"] == "descend_route" for c in changed)
    assert action_keys(changed) == action_keys([c for c in control if c["kind"] != "descend_route"])
    assert control[0]["kind"] == "descend_route" and changed[0]["kind"] == "align_ladder"
    assert analysis["ladder"]["recommendedAction"] is None
    assert (state, history) == original
    stationary_state, stationary_history = copy.deepcopy(original)
    for i, (kind, key) in enumerate((("defensive_dig_dig_left", 90),
                                    ("wait_for_dig_completion_1", 32),
                                    ("wait_for_trap_resolution_1", 32))):
        stationary_history.append({"candidateId": kind, "keyCode": key, "ticks": 2,
                                   "tick": 20 + 2 * i, "afterTick": 22 + 2 * i,
                                   "before": copy.deepcopy(arrived), "after": copy.deepcopy(arrived)})
    stationary_state["tick"] = 26
    remembered, _ = generate_candidates(stationary_state, stationary_history)
    assert remembered[0]["kind"] == "align_ladder"
    stationary_history[-1]["before"]["runner"]["xOffset"] = 1
    forgotten, _ = generate_candidates(stationary_state, stationary_history)
    assert forgotten[0]["kind"] == "descend_route"
    state["runner"]["x"] = 3
    state["tick"] = 24
    history.append({"candidateId": "align_ladder_4_1_right", "keyCode": 39, "ticks": 4,
                    "tick": 20, "afterTick": 24, "before": arrived,
                    "after": {"runner": runner_pose(3, 1), "goldCount": 0}})
    changed, _ = generate_candidates(state, history)
    assert changed[0]["target"]["x"] == 4
    state["tick"] = 25  # Stale history cannot establish a return.
    stale, _ = generate_candidates(state, history)
    assert all(not any(p["name"] == "recent_ladder_return_penalty" for p in c["scoreBreakdown"]["components"]) for c in stale)
    state, history = copy.deepcopy(original)
    state["terrainGrid"] = state["grid"] = ["       ", "## ####", "##H####", "  H    ", "#######"]
    sole, analysis = generate_candidates(state, history)
    assert len(sole) == 1 and sole[0]["kind"] == "wait_and_recheck"
    assert analysis["ladder"]["recommendedAction"] is None
    assert generate_candidates(state, [None])[0]

def check_vertical_secondary_safety():
    analysis = {
        "godMode": False, "runner": {"action": "stop"},
        "risk": {
            "primaryThreat": {"id": 0, "risk": "high", "relativeX": "right",
                              "relativeY": "same", "distance": 2, "motion": "left"},
            "guards": [{"id": 1, "risk": "high", "relativeX": "same",
                              "relativeY": "below", "motion": "up"}],
        },
    }
    original = copy.deepcopy(analysis)
    for key, side, approaching, departing in ((40, "below", "up", "down"),
                                             (38, "above", "down", "up")):
        threat = analysis["risk"]["guards"][0]
        threat.update(relativeY=side, motion=approaching)
        action = {"keyCode": key, "ticks": 6}
        for kind in ("retreat_from_guard", "descend_route", "climb_ladder"):
            assert action_guard_safety_rejection_detail(action, analysis, candidate_kind=kind)
        threat["motion"] = departing
        assert action_guard_safety_rejection_detail(action, analysis, candidate_kind="climb_ladder") is None
        threat.update(motion=approaching, relativeX="left")
        assert action_guard_safety_rejection_detail(action, analysis, candidate_kind="descend_route") is None
        threat["relativeX"] = "same"
        analysis["godMode"] = True
        assert action_guard_safety_rejection_detail(action, analysis, candidate_kind="descend_route") is None
        analysis["godMode"] = False
    # Safety validation must not modify its inputs.
    unchanged = copy.deepcopy(original)
    action_guard_safety_rejection_detail({"keyCode": 40, "ticks": 6}, unchanged)
    assert unchanged == original

def check_short_medium_clearance():
    # The same bounded movement must be safe in either direction and at any
    # column. Two-sided pressure is checked before granting the exception.
    for direction in (-1, 1):
        analysis = {
            "runner": {"x": 12, "xOffset": 0},
            "risk": {"risk": "medium", "primaryThreat": {
                "id": 0, "x": 12 + 4 * direction, "xOffset": 0,
                "risk": "medium", "relativeX": "left" if direction < 0 else "right",
                "relativeY": "same", "distance": 4,
            }, "guards": []},
        }
        threat = analysis["risk"]["primaryThreat"]
        analysis["risk"]["guards"] = [threat]
        action = {"keyCode": 37 if direction < 0 else 39, "ticks": 4}
        original = copy.deepcopy(analysis)
        assert action_guard_safety_rejection_detail(action, analysis) is None
        assert analysis == original
        assert action_guard_safety_rejection_detail({**action, "ticks": 6}, analysis)
        # Offsets can consume the apparent tile-level clearance.
        threat["xOffset"] = -17 * direction
        assert action_guard_safety_rejection_detail(action, analysis)
        threat["xOffset"] = 0
        threat["risk"] = "high"
        assert action_guard_safety_rejection_detail(action, analysis)
        threat["risk"] = "medium"
        del threat["xOffset"]
        assert action_guard_safety_rejection_detail(action, analysis)
        threat["xOffset"] = 0
        analysis["risk"]["guards"].append({
            "id": 1, "x": 12 - 2 * direction, "xOffset": 0,
            "risk": "medium", "relativeY": "same",
            "relativeX": "right" if direction < 0 else "left",
        })
        assert action_guard_safety_rejection_detail(action, analysis)
        analysis["godMode"] = True
        assert action_guard_safety_rejection_detail(action, analysis) is None

def check_shorter_medium_candidates():
    for direction in (-1, 1):
        state = candidate_snapshot(guarded=True)
        state["runner"]["x"] = 2 if direction == 1 else 4
        state["gold"]["visiblePositions"][0]["x"] = 4 if direction == 1 else 2
        guard = state["guards"][0]
        guard.update(x=6 if direction == 1 else 0, xOffset=-17 * direction,
                     actionName="left" if direction == 1 else "right")
        original = copy.deepcopy(state)
        pool, analysis = generate_candidates(state, [])
        progress = next(c for c in pool if c["kind"] == "collect_same_row_gold")
        assert progress["action"]["ticks"] == 3
        assert progress["action"]["keyCode"] == (39 if direction == 1 else 37)
        assert action_guard_safety_rejection_detail(progress["action"], analysis,
                                                  candidate_kind=progress["kind"]) is None
        assert action_guard_safety_rejection_detail({**progress["action"], "ticks": 4},
                                                  analysis, candidate_kind=progress["kind"])
        assert state == original
        guard["xOffset"] = 0
        unchanged, _ = generate_candidates(state, [])
        control = next(c for c in unchanged if c["id"] == progress["id"])
        assert control["action"]["ticks"] == 4
        assert control["score"] == progress["score"]
        # Near high-risk pressure must still exclude progress, at any duration.
        guard["x"] = state["runner"]["x"] + 2 * direction
        blocked, _ = generate_candidates(state, [])
        assert not any(c["kind"] == "collect_same_row_gold" for c in blocked)
        state["godMode"] = True
        god, _ = generate_candidates(state, [])
        assert next(c for c in god if c["kind"] == "collect_same_row_gold")["action"]["ticks"] == 8

def check_defensive_dig_threat_priority():
    state = candidate_snapshot()
    state["gold"]["visiblePositions"] = []
    descending = {"relativeX": "right", "relativeY": "above", "motion": "down", "distance": 2}
    same_row = {"relativeX": "left", "relativeY": "same", "distance": 4}
    risk = {"primaryThreat": descending, "guards": [descending, same_row]}
    assert get_dig_affordance(state, risk=risk)["right"]["guardCouldFall"]
    same_row["distance"] = 1
    dig = get_dig_affordance(state, risk=risk)
    assert dig["left"]["guardCouldFall"] and not dig["right"]["guardCouldFall"]

def check_defensive_dig_below_pressure():
    state = candidate_snapshot()
    state["gold"]["visiblePositions"] = []
    state["terrainGrid"] = ["       ", "       ", "#######", "       ", "#######"]
    state["grid"] = state["terrainGrid"]
    state["runner"]["x"] = 3
    for side in (-1, 1):
        guard = {"id": 0, "x": 3 + side, "y": 3, "xOffset": 0, "yOffset": 0,
                 "actionName": "right" if side < 0 else "left", "hasGold": 0}
        state["guards"] = [guard]
        original = copy.deepcopy(state)
        pool, analysis = generate_candidates(state, [])
        assert analysis["risk"]["risk"] == "high"
        assert not any(c["kind"] == "defensive_dig" for c in pool)
        assert state == original
        # Preserve preparation for a guard actually climbing toward this row.
        guard["actionName"] = "up"
        pool, _ = generate_candidates(state, [])
        assert any(c["kind"] == "defensive_dig" for c in pool)
        state["godMode"] = True
        pool, _ = generate_candidates(state, [])
        assert not any(c["kind"] == "defensive_dig" for c in pool)
        state["godMode"] = False

def check_ladder_direction_context():
    state = candidate_snapshot()
    state["terrainGrid"] = ["       ", "  H    ", "  H    ", "  H    ", "#######"]
    state["grid"] = state["terrainGrid"]
    state["runner"]["y"] = 2
    for god_mode in (False, True):
        state["godMode"] = god_mode
        for target_y, direction, key in ((1, "up", 38), (3, "down", 40)):
            state["gold"]["visiblePositions"] = [{"x": 4, "y": target_y}]
            original = copy.deepcopy(state)
            pool, analysis = generate_candidates(state, [])
            candidate = next(c for c in pool if c["kind"] == "climb_ladder")
            assert candidate["action"]["keyCode"] == key
            assert format_ladder(analysis["ladder"])["preferredDirection"] == direction
            # Check semantic directional consistency, not an exact prose template.
            reasons = format_candidate(candidate)["reasons"]
            assert set(re.findall(r"\b(up|down)\b", " ".join(reasons))) == {direction}
            assert state == original

def check_targetless_ladder_continuation():
    state = candidate_snapshot()
    state.update(terrainGrid=["     ", "  H  ", "  H  ", "  H  ", "#####"], tick=6)
    state["grid"] = state["terrainGrid"]
    state["runner"].update(y=1, yOffset=10, actionName="down")
    state["gold"]["visiblePositions"] = []
    history = [{"candidateId": "descend_route_2_1_down", "keyCode": 40, "ticks": 6,
                "tick": 0, "afterTick": 6,
                "before": {"runner": {"x": 2, "y": 0, "xOffset": 0, "yOffset": 0}, "goldCount": 1},
                "after": {"runner": copy.deepcopy(state["runner"]), "goldCount": 1}}]
    original = copy.deepcopy((state, history))
    for god_mode in (False, True):
        state["godMode"] = god_mode
        pool, analysis = generate_candidates(state, history)
        assert any(c["kind"] == "climb_ladder" and c["action"]["keyCode"] == 40 for c in pool)
        assert not any(c["kind"] == "climb_ladder" and c["action"]["keyCode"] == 38 for c in pool)
        assert analysis["ladder"]["recommendedAction"] == "down"
        # A visible target or exit priority must still override continuation.
        analysis["goldTarget"] = {"x": 2, "y": 0}
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["goldTarget"] = {}
        analysis["goldComplete"] = True
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["goldComplete"] = False
        # Guard pressure, blocked movement and stale/non-progress history do not
        # qualify for the no-target direction tie-break.
        analysis["risk"]["risk"] = "medium"
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["risk"]["risk"] = "low"
        analysis["movement"]["canMoveDown"] = False
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["movement"]["canMoveDown"] = True
        for edit in ({"candidateId": "retreat_from_guard_down"}, {"afterTick": 5},
                     {"before": history[0]["after"]}):
            assert choose_ladder_direction(state, analysis, [{**history[0], **edit}]) == "up"
        assert choose_ladder_direction(state, analysis, []) == "up"
        upward = copy.deepcopy(history)
        upward[0].update(candidateId="climb_ladder_2_2_up", keyCode=38)
        upward[0]["before"]["runner"].update(y=2, yOffset=0)
        assert choose_ladder_direction(state, analysis, upward) == "up"
    state["godMode"] = False
    assert (state, history) == original
    # A real approaching guard still determines the safe vertical candidates.
    state["guards"] = [{"id": 0, "x": 2, "y": 2, "xOffset": 0, "yOffset": 0,
                        "actionName": "up", "hasGold": 0}]
    pool, analysis = generate_candidates(state, history)
    assert analysis["risk"]["risk"] in {"high", "critical"}
    assert any(c["action"]["keyCode"] == 38 for c in pool)
    assert not any(c["action"]["keyCode"] == 40 for c in pool)
    assert analysis["ladder"]["recommendedAction"] == "up"

def check_off_center_pinch_dig():
    state = candidate_snapshot()
    state["runner"].update(x=5, xOffset=8)
    state["terrainGrid"] = state["grid"] = ["           ", "           ",
                                            "###########", "@@@@@@@@@@@"]
    state["gold"]["visiblePositions"] = [{"x": 1, "y": 1}]
    state["guards"] = [
        {"id": 0, "x": 0, "y": 1, "xOffset": 8, "yOffset": 0,
         "actionName": "right", "hasGold": 0},
        {"id": 1, "x": 9, "y": 1, "xOffset": 0, "yOffset": 17,
         "actionName": "climb_out", "hasGold": 0},
    ]
    original = copy.deepcopy(state)
    pool, _ = generate_candidates(state, [])
    assert any(c["kind"] == "retreat_from_guard" for c in pool)
    assert any(c["kind"] == "defensive_dig" and c["action"]["keyCode"] == 88
               for c in pool)
    assert state == original
    state["guards"] = state["guards"][1:]
    _, analysis = generate_candidates(state, [])
    assert not analysis["dig"]["right"]["canDefensiveDig"]
    state = copy.deepcopy(original)
    state["godMode"] = True
    _, analysis = generate_candidates(state, [])
    assert not analysis["dig"]["right"]["canDefensiveDig"]

def check_loop_evidence_boundaries():
    history = [
        {"candidateId": f"align_ladder_{5 if i % 2 == 0 else 1}_2_right",
         "keyCode": 39 if i % 2 == 0 else 37,
         "after": {"runner": {"x": 2 + i % 2, "y": 2}, "goldCount": 1}}
        for i in range(6)
    ]
    analysis = {"rowLadders": [{"x": 2, "y": 2}], "nearestGold": []}
    report = build_loop_report(analysis, history)
    assert report["type"] == "horizontal_cycle"
    candidate = {"id": "collect_same_row_gold_2_2_right",
                 "kind": "collect_same_row_gold", "action": {"keyCode": 39}}
    assert candidate_suppression_reason(candidate, report) is not None
    assert candidate_suppression_reason({"kind": "emergency_hold"}, report) is None
    progressing = copy.deepcopy(report)
    progressing["evidence"].update(repeatedCandidateId=candidate["id"],
                                   targetProgress=True, targetReached=False)
    assert candidate_suppression_reason(candidate, progressing) is None
    broken = copy.deepcopy(history)
    broken[0].pop("candidateId")
    broken[1].pop("keyCode")
    assert build_loop_report(analysis, broken) == build_loop_report(analysis, history[2:])
    broken[-1].pop("after")
    assert not build_loop_report(analysis, broken)["active"]

def check_recent_horizontal_cycle_after_row_change():
    # Historical step 109: the older descent/ascent must not veto a complete
    # six-position horizontal cycle on the new row.
    positions = [(25, 4), (25, 3), (23, 3), (24, 3),
                 (25, 3), (24, 3), (25, 3), (24, 3)]
    keys = [40, 38, 37, 39, 39, 37, 39, 37]
    history = [
        {"candidateId": f"align_ladder_{14 if key == 37 else 25}_3_left",
         "keyCode": key,
         "after": {"runner": {"x": x, "y": y}, "goldCount": 2}}
        for (x, y), key in zip(positions, keys)
    ]
    original = copy.deepcopy(history)
    assert build_loop_report({}, history)["type"] == "horizontal_cycle"
    assert not build_loop_report({}, history)["evidence"]["noRowChange"]
    controls = []
    row_change = copy.deepcopy(history)
    row_change[-3]["after"]["runner"]["y"] = 4
    controls.append(row_change)
    progress = copy.deepcopy(history)
    progress[0]["after"]["goldCount"] = 3
    controls.append(progress)
    backtrack = copy.deepcopy(history)
    for item, key in zip(backtrack[-6:], [37, 37, 37, 39, 39, 39]):
        item["keyCode"] = key
    controls.append(backtrack)
    waiting = copy.deepcopy(history)
    waiting[-1]["candidateId"] = "wait_for_trap_resolution"
    controls.append(waiting)
    retreats = copy.deepcopy(history)
    for item in retreats:
        item["candidateId"] = "retreat_from_guard_left"
    controls.append(retreats)
    for control in controls:
        assert not build_loop_report({}, control)["active"]
    assert not build_loop_report({"activeDig": {"active": True}}, history)["active"]
    assert history == original


def check_loop_target_alignment_score():
    for god_mode in (False, True):
        for distance in (1, 5):
            analysis = {
                "runner": {"x": 24, "y": 3}, "goldTarget": {},
                "risk": {"risk": "low"},
                "movement": {"canMoveRight": True},
                "rowLadders": [{"x": 24 + distance, "y": 3, "tile": "H",
                                "distance": distance, "direction": "right"}],
                "loopReport": {"active": False, "target": None},
            }
            ordinary = []
            add_ladder_alignment_candidates(lambda **item: ordinary.append(item), analysis, god_mode, [])
            analysis["loopReport"] = {"active": True, "type": "horizontal_cycle",
                "target": {"x": 24 + distance, "y": 3, "kind": "ladder"}}
            original = copy.deepcopy(analysis)
            recovering = []
            add_ladder_alignment_candidates(lambda **item: recovering.append(item), analysis, god_mode, [])
            assert recovering == ordinary
            assert recovering[0]["score"].total == (104 if distance == 1 else 97 + 4 * god_mode)
            assert analysis == original


def runner_pose(x, y, **changes):
    return {"x": x, "y": y, "xOffset": 0, "yOffset": 0, **changes}


def check_horizontal_offset_progress():
    for key, target, start, end in ((39, 5, -16, 16), (37, 1, 16, -16)):
        candidate_id = f"align_ladder_{target}_2_{'right' if key == 39 else 'left'}"
        history = [
            {"candidateId": f"align_ladder_{5 if i % 2 == 0 else 1}_2_{'right' if i % 2 == 0 else 'left'}",
             "keyCode": 39 if i % 2 == 0 else 37,
             "before": {"runner": runner_pose(3, 2), "goldCount": 1},
             "after": {"runner": runner_pose(3, 2), "goldCount": 1}}
            for i in range(6)
        ]
        history.append({"candidateId": candidate_id, "keyCode": key,
                        "before": {"runner": runner_pose(3, 2, xOffset=start), "goldCount": 1},
                        "after": {"runner": runner_pose(3, 2, xOffset=end), "goldCount": 1}})
        candidate = {"id": candidate_id, "kind": "align_ladder", "action": {"keyCode": key}}
        report = build_loop_report({}, history)
        assert report["type"] == "horizontal_cycle"
        assert not report["evidence"]["targetProgress"]  # Still tile distance.
        assert candidate_suppression_reason(candidate, report) is None
        assert build_recent_progress(history)["repeatedCandidate"]["targetDistanceReduced"] is False
        for variation in ("missing_offset", "moving_away", "stationary", "vertical_change", "target_reached"):
            control = copy.deepcopy(history)
            after = control[-1]["after"]["runner"]
            if variation == "missing_offset":
                after.pop("xOffset")
            elif variation == "moving_away":
                control[-1]["before"]["runner"]["xOffset"], after["xOffset"] = end, start
            elif variation == "stationary":
                after["xOffset"] = start
            elif variation == "vertical_change":
                after["yOffset"] = 8
            else:
                after["x"] = target
            assert candidate_suppression_reason(candidate, build_loop_report({}, control)) is not None


def check_provider_and_response_contracts():
    import os
    from types import SimpleNamespace
    from unittest.mock import patch
    from agent.config import resolve_model_profile, get_explicit_provider_configs
    from agent.service import parse_candidate_response, _extract_openai_declared_reasoning
    for profile in ("openai", "minimax", "gemini"):
        prefix = profile.upper()
        with patch.dict(os.environ, {prefix + "_MODEL": "test", prefix + "_API_KEY": "dummy"}, clear=True):
            resolved = resolve_model_profile(profile, source="request")
            assert resolved.profile == profile
            assert resolved.aisuite_provider == ("openai" if profile == "gemini" else profile)
            if profile != "gemini":
                assert get_explicit_provider_configs(profile) == resolved.provider_configs
        with patch.dict(os.environ, {}, clear=True):
            try:
                resolve_model_profile(profile, source="config")
            except ValueError:
                pass
            else:
                raise AssertionError("Missing model accepted")
    for content in ('{"candidateId":"test"}', '```json\n{"candidateId":"test"}\n```'):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        choice, error = parse_candidate_response(response)
        assert choice == {"candidateId": "test"} and error is None
    assert _extract_openai_declared_reasoning('```json\n{"reasoning":"brief"}\n```') == "brief"
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))])
    assert parse_candidate_response(response)[0] is None


def check_immediate_descent_after_climb():
    runner = {"x": 4, "y": 12}
    entry = {"x": 4, "y": 12, "ladderY": 13, "tile": "H"}
    analysis = {"runner": runner, "ladder": {"onDownEntry": True,
                "nearestRowLadder": entry}, "goldTarget": {}, "goldComplete": True}

    def proposals(before_y, *, key=38, column=4, kind="exit_ladder_route"):
        history = [{"candidateId": f"{kind}_{column}_{before_y}_up",
                    "keyCode": key, "ticks": 20,
                    "before": {"runner": {"x": column, "y": before_y}},
                    "after": {"runner": runner}}]
        choices = []
        add_descent_candidates(lambda **choice: choices.append(choice),
                               analysis, {"canMoveDown": True}, history)
        return choices

    assert not proposals(13), "suppress reversal after a one-row ascent"
    assert not proposals(14), "suppress reversal after a multi-row ascent"
    assert proposals(12), "an action that did not cross the entry must not block descent"
    assert proposals(14, key=40), "a downward action is not an ascent"
    assert proposals(14, column=9), "an ascent elsewhere must not block descent"
    assert proposals(14, kind="retreat_from_guard"), "retain existing candidate-kind scope"
    assert proposals(None), "unknown history does not prove an ascent"


def check_logging_levels():
    import os
    from unittest.mock import patch
    from agent.logging_utils import effective_app_log_level, debug_log_enabled
    for name, expected in (("WARN", 30), ("DEBUG", 10), ("invalid", 20)):
        with patch.dict(os.environ, {"APP_LOG_LEVEL": name}, clear=True):
            assert effective_app_log_level() == expected
    with patch.dict(os.environ, {"APP_LOG_LEVEL": "ERROR", "AGENT_DEBUG_LOG": "yes"}, clear=True):
        assert debug_log_enabled() and effective_app_log_level() == 10


if __name__ == "__main__":
    check_model_context()
    check_floor_separated_horizontal_pressure()
    check_open_hole_escape()
    check_exit_context()
    check_recent_ladder_return()
    check_vertical_secondary_safety()
    check_short_medium_clearance()
    check_shorter_medium_candidates()
    check_defensive_dig_threat_priority()
    check_defensive_dig_below_pressure()
    check_ladder_direction_context()
    check_targetless_ladder_continuation()
    check_off_center_pinch_dig()
    check_loop_evidence_boundaries()
    check_recent_horizontal_cycle_after_row_change()
    check_loop_target_alignment_score()
    check_horizontal_offset_progress()
    check_provider_and_response_contracts()
    check_logging_levels()
    check_immediate_descent_after_climb()
    print("backend regressions ok")
