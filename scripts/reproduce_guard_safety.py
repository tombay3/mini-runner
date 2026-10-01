"""Offline characterization of retained guard holds; no gameplay changes or API calls.

Uses recorded movement affordances, not reconstructed terrain. This reproduces
the candidate validation boundary, not a full engine replay or safe escape proof.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.candidates import (
    CandidateBuilder, action_guard_safety_rejection_detail,
    add_descent_candidates,
    add_trap_resolution_wait_candidate,
    find_primary_progress_target,
    is_action_physically_valid,
    just_climbed_from_entry_ladder,
    ladder_alignment_score,
    low_risk_guard_clearance_score_bonus,
)
from agent.reasoning_tools import assess_guard_risk
from agent.loop_tools import build_loop_report
from agent.service import validate_or_fallback_candidate

FIXTURE = json.loads((Path(__file__).parent / "fixtures/guard-safety-holds.json").read_text())
CASES = FIXTURE["cases"]
DISTANCE_CASES = FIXTURE["distanceCases"]
CONVERGENCE_SEQUENCE = FIXTURE["convergenceSequence"]
PINCH_ENTRY_CASES = FIXTURE["pinchEntryCases"]
LATEST_PINCH_BOUNDARY = FIXTURE["latestPinchBoundary"]
POST_GOLD_REVERSAL_BOUNDARY = FIXTURE["postGoldReversalBoundary"]
COMPOUND_LADDER_CYCLE_BOUNDARY = FIXTURE["compoundLadderCycleBoundary"]
SECONDARY_LADDER_BOUNDARY = FIXTURE["secondaryLadderGuardBoundary"]

ACTION_TICKS_PER_CELL = 8
ACTION_VECTORS = {
    37: (-1, 0),
    38: (0, -1),
    39: (1, 0),
    40: (0, 1),
    32: (0, 0),
}
MOTION_VECTORS = {
    "left": (-1, 0),
    "right": (1, 0),
    "up": (0, -1),
    "down": (0, 1),
    "fall": (0, 1),
    "stop": (0, 0),
    "in_hole": (0, 0),
}
TRAPPED_MOTIONS = {"in_hole"}


def _scaled_grid_position(entity):
    # Risk bands use grid coordinates. Offsets are legacy pixels, while action
    # ticks are decision duration, so mixing both would invent a false scale.
    return (
        int(entity.get("x", 0)) * ACTION_TICKS_PER_CELL,
        int(entity.get("y", 0)) * ACTION_TICKS_PER_CELL,
    )


def _distance(a, b):
    return round(
        (abs(a[0] - b[0]) + abs(a[1] - b[1])) / ACTION_TICKS_PER_CELL,
        3,
    )


def _relation(origin, other, axis):
    index = 0 if axis == "x" else 1
    if other[index] == origin[index]:
        return "same"
    if axis == "x":
        return "left" if other[index] < origin[index] else "right"
    return "above" if other[index] < origin[index] else "below"


def measure_guard_clearance(runner, guards, action):
    """Measure a bounded action without simulating terrain or legacy physics."""
    ticks = max(1, int(action.get("ticks", 1) or 1))
    runner_start = _scaled_grid_position(runner)
    runner_vector = ACTION_VECTORS.get(action.get("keyCode"), (0, 0))
    measurements = []
    for guard in guards:
        guard_start = _scaled_grid_position(guard)
        motion = str(guard.get("motion") or guard.get("actionName") or "stop")
        trapped = motion in TRAPPED_MOTIONS
        guard_vector = (0, 0) if trapped else MOTION_VECTORS.get(motion, (0, 0))
        distances = []
        runner_end = runner_start
        guard_end = guard_start
        for tick in range(ticks + 1):
            runner_end = (
                runner_start[0] + runner_vector[0] * tick,
                runner_start[1] + runner_vector[1] * tick,
            )
            guard_end = (
                guard_start[0] + guard_vector[0] * tick,
                guard_start[1] + guard_vector[1] * tick,
            )
            distances.append(_distance(runner_end, guard_end))
        before = distances[0]
        after = distances[-1]
        minimum = min(distances)
        active = not trapped
        measurements.append({
            "guardId": guard.get("id"),
            "risk": guard.get("risk"),
            "motion": motion,
            "closing": bool(guard.get("closing")),
            "trapped": trapped,
            "active": active,
            "rowBefore": _relation(runner_start, guard_start, "y"),
            "rowAfter": _relation(runner_end, guard_end, "y"),
            "distanceBefore": before,
            "minimumDistance": minimum,
            "distanceAfter": after,
            "distanceDelta": round(after - before, 3),
            "approach": active and minimum < before,
            "projectedIntercept": active and minimum <= 1,
            "projectedCollision": active and minimum == 0,
            "safetyBoundaryCrossed": active and before > 1 and minimum <= 1,
        })
    return measurements


def measure_candidate(case, candidate):
    action = candidate.get("action") or candidate.get("proposedAction") or {}
    guards = case.get("guards") or case.get("state", {}).get(
        "guardRisk", {}
    ).get("nearbyGuards", [])
    runner = case.get("runner") or case.get("state", {}).get("runner", {})
    target = case.get("target") or case.get("state", {}).get("primaryProgressTarget") or {}
    route_threat = (
        candidate.get("routeThreat")
        or case.get("state", {}).get("routeAccess", {}).get("dropThreat")
    )
    guard_metrics = measure_guard_clearance(runner, guards, action)
    active_metrics = [item for item in guard_metrics if item["active"]]
    endpoint = _scaled_grid_position(runner)
    vector = ACTION_VECTORS.get(action.get("keyCode"), (0, 0))
    ticks = max(1, int(action.get("ticks", 1) or 1))
    endpoint = (endpoint[0] + vector[0] * ticks, endpoint[1] + vector[1] * ticks)
    progress_before = progress_after = None
    if target.get("x") is not None and target.get("y") is not None:
        target_position = (
            int(target["x"]) * ACTION_TICKS_PER_CELL,
            int(target["y"]) * ACTION_TICKS_PER_CELL,
        )
        progress_before = _distance(_scaled_grid_position(runner), target_position)
        progress_after = _distance(endpoint, target_position)
    progress_gain = (
        round(progress_before - progress_after, 3)
        if progress_before is not None and progress_after is not None
        else None
    )
    minimum_before = min((item["distanceBefore"] for item in active_metrics), default=None)
    minimum_during = min((item["minimumDistance"] for item in active_metrics), default=None)
    minimum_after = min((item["distanceAfter"] for item in active_metrics), default=None)
    projected_intercept = bool(route_threat) or any(
        item["projectedIntercept"] for item in active_metrics
    )
    return {
        "candidateId": candidate.get("id") or candidate.get("candidateId"),
        "kind": candidate.get("kind"),
        "lane": candidate.get("lane"),
        "score": candidate.get("score"),
        "baselineDisposition": candidate.get("baselineDisposition"),
        "disposition": candidate.get("currentDisposition") or candidate.get(
            "disposition", "exposed"
        ),
        "actionTicks": ticks,
        "minimumDistanceBefore": minimum_before,
        "minimumDistanceDuring": minimum_during,
        "minimumDistanceAfter": minimum_after,
        "distanceReduced": bool(
            minimum_before is not None
            and minimum_after is not None
            and minimum_after < minimum_before
        ),
        "approach": any(item["approach"] for item in active_metrics),
        "routeThreat": route_threat,
        "projectedIntercept": projected_intercept,
        "projectedCollision": any(item["projectedCollision"] for item in active_metrics),
        "safetyBoundaryCrossed": any(item["safetyBoundaryCrossed"] for item in active_metrics),
        "progressGain": progress_gain,
        "progressWhilePreservingDistance": bool(
            progress_gain is not None
            and progress_gain > 0
            and not projected_intercept
            and (
                minimum_before is None
                or (minimum_during is not None and minimum_during >= minimum_before)
            )
        ),
        "guards": guard_metrics,
    }


def summarize_distance_case(case):
    measured = [measure_candidate(case, candidate) for candidate in case["candidates"]]
    rejected = {
        "safety_rejection", "physical_rejection", "loop_suppressed", "truncated",
    }
    safe_progress = [
        item["candidateId"] for item in measured
        if item["lane"] == "progress"
        and item["disposition"] not in rejected
        and not item["projectedIntercept"]
    ]
    selected_id = case.get("selectedCandidateId")
    selected = next((item for item in measured if item["candidateId"] == selected_id), None)
    selected_is_safety = bool(selected and selected["lane"] in {"safety", "environment"})
    return {
        "id": case["id"],
        "candidates": measured,
        "safeProgressIds": safe_progress,
        "guardDistanceRejectionCount": sum(
            item["lane"] == "progress" and item["disposition"] == "safety_rejection"
            for item in measured
        ),
        "candidateLimitDisplacementCount": sum(
            item["lane"] == "progress"
            and item["disposition"] == "truncated"
            and not item["projectedIntercept"]
            for item in measured
        ),
        "unnecessarySafetySelection": selected_is_safety and bool(safe_progress),
        "selectedDistanceReduced": bool(selected and selected["distanceReduced"]),
        "selectedApproach": bool(selected and selected["approach"]),
        "selectedProjectedIntercept": bool(selected and selected["projectedIntercept"]),
        "selectedProjectedCollision": bool(selected and selected["projectedCollision"]),
        "repeatedNoProgressCount": int(case.get("repeatedNoProgressCount", 0)),
    }


def assert_expected(actual, expected, context):
    for key, value in expected.items():
        if isinstance(value, dict):
            assert_expected(actual[key], value, f"{context}.{key}")
        else:
            if actual.get(key) != value:
                raise AssertionError(
                    f"{context}.{key}: expected {value!r}, got {actual.get(key)!r}"
                )


def retained_distance_case(case):
    analysis = analysis_for(case)
    builder = CandidateBuilder(snapshot={}, analysis=analysis, max_action_ticks=20, limit=7)
    for proposal in case["proposals"]:
        action = proposal["proposedAction"]
        builder.add(
            kind=proposal["kind"],
            key_code=action["keyCode"],
            ticks=action["ticks"],
            score=100 if proposal["lane"] == "progress" else 0,
            target=proposal.get("target"),
            reason="retained guard-distance comparison",
            candidate_id=proposal["candidateId"],
        )
    builder.finalize()
    current = {item["candidateId"]: item["disposition"] for item in builder.audit}
    candidates = []
    selected_id = None
    for proposal in case["proposals"]:
        candidate = {
            **proposal,
            "baselineDisposition": proposal["disposition"],
            "currentDisposition": current[proposal["candidateId"]],
        }
        candidates.append(candidate)
        if proposal["kind"] == case.get("selectedKind") and selected_id is None:
            selected_id = proposal["candidateId"]
    return {
        "id": f"{case['traceId'][:8]}-step-{case['displayStep']}",
        "state": case["state"],
        "candidates": candidates,
        "selectedCandidateId": selected_id,
        "repeatedNoProgressCount": 136 if case["traceId"].startswith("3dcb7b7d") else 0,
    }


def print_distance_summary(summaries):
    print("\nGuard-distance experiment (bounded diagnostic; no terrain simulation)")
    print(
        "case                         candidate                 "
        "main->candidate       progress  distance b/min/a  flags"
    )
    for summary in summaries:
        for item in summary["candidates"]:
            flags = []
            if item["distanceReduced"]:
                flags.append("reduce")
            if item["progressWhilePreservingDistance"]:
                flags.append("safe-progress")
            if item["projectedIntercept"]:
                flags.append("intercept")
            if item["projectedCollision"]:
                flags.append("collision")
            distances = "/".join(
                "-" if value is None else str(value)
                for value in (
                    item["minimumDistanceBefore"],
                    item["minimumDistanceDuring"],
                    item["minimumDistanceAfter"],
                )
            )
            print(
                f"{summary['id'][:28]:28} {str(item['candidateId'])[:25]:25} "
                f"{str(item['baselineDisposition'] or '-')[:8]:8}->{item['disposition'][:9]:9} "
                f"{str(item['progressGain']):>8}  "
                f"{distances:17} {','.join(flags) or '-'}"
            )


def analysis_for(case):
    state = deepcopy(case["state"])
    movement = state["movement"]
    movement["details"] = {
        side: {"openHole": movement.get(f"{side}OpenHole")}
        for side in ("left", "right")
    }
    return {
        "godMode": state["godMode"], "runner": state["runner"],
        "risk": state["guardRisk"], "movement": movement,
        "dig": {}, "activeDig": state["activeDig"],
        "loopReport": {"active": False},
    }


class GuardHoldCharacterization(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        print_distance_summary(
            [summarize_distance_case(case) for case in DISTANCE_CASES]
            + [summarize_distance_case(retained_distance_case(case)) for case in CASES]
        )

    def test_bounded_guard_distance_matrix(self):
        summaries = {
            case["id"]: summarize_distance_case(case) for case in DISTANCE_CASES
        }

        convergence = summaries["403-step-135-convergence-choice"]
        right, left = convergence["candidates"]
        self.assertEqual(convergence["safeProgressIds"], [
            "align_ladder_27_14_right", "align_ladder_4_14_left",
        ])
        assert_expected(right, {
            "score": 99,
            "minimumDistanceBefore": 4.0,
            "minimumDistanceDuring": 3.0,
            "minimumDistanceAfter": 3.0,
            "distanceReduced": True,
            "progressGain": -0.5,
        }, "403 step 135 right choice")
        assert_expected(left, {
            "score": 90,
            "minimumDistanceBefore": 4.0,
            "minimumDistanceDuring": 4.0,
            "minimumDistanceAfter": 4.0,
            "distanceReduced": False,
            "progressGain": 0.5,
            "progressWhilePreservingDistance": True,
        }, "403 step 135 left alternative")
        self.assertTrue(convergence["selectedDistanceReduced"])

    def test_retained_convergence_sequence_loses_choices_after_reversal(self):
        summaries = {
            case["id"]: summarize_distance_case(case) for case in DISTANCE_CASES
        }
        by_step = {item["displayStep"]: item for item in CONVERGENCE_SEQUENCE}
        self.assertEqual(
            by_step[135]["exposedCandidateIds"],
            ["align_ladder_27_14_right", "align_ladder_4_14_left"],
        )
        self.assertEqual(
            by_step[135]["selectedCandidateId"], "align_ladder_27_14_right"
        )
        self.assertEqual(by_step[136]["selectedCandidateId"], "retreat_from_guard_left")
        self.assertEqual(by_step[137]["exposedCandidateIds"], [
            "emergency_hold_0_26_14_16_0_left",
        ])
        self.assertEqual(
            [by_step[step]["runnerX"] for step in (134, 135, 136, 137)],
            [25, 24, 25, 24],
        )

        two_routes = summaries["low-ahead-two-safe-routes"]
        self.assertEqual(
            two_routes["safeProgressIds"],
            ["progress_toward_guard", "progress_preserve_clearance"],
        )
        toward, preserving = two_routes["candidates"]
        assert_expected(toward, {
            "minimumDistanceBefore": 7.0,
            "minimumDistanceDuring": 6.0,
            "minimumDistanceAfter": 6.0,
            "distanceReduced": True,
            "projectedIntercept": False,
            "progressGain": 0.5,
            "progressWhilePreservingDistance": False,
        }, "low-ahead toward candidate")
        assert_expected(preserving, {
            "minimumDistanceBefore": 7.0,
            "minimumDistanceDuring": 7.0,
            "minimumDistanceAfter": 7.0,
            "distanceReduced": False,
            "progressGain": 0.5,
            "progressWhilePreservingDistance": True,
        }, "low-ahead preserving candidate")

        moving_away = summaries["low-behind-moving-away"]["candidates"][0]
        assert_expected(moving_away, {
            "minimumDistanceBefore": 6.0,
            "minimumDistanceAfter": 7.0,
            "progressWhilePreservingDistance": True,
        }, "guard behind moving away")

        trapped = summaries["trapped-guard-is-inactive"]["candidates"][0]
        self.assertFalse(trapped["guards"][0]["active"])
        self.assertTrue(trapped["guards"][0]["trapped"])
        self.assertTrue(trapped["progressWhilePreservingDistance"])
        self.assertFalse(trapped["projectedIntercept"])

        safe_reduction = summaries["safe-distance-reduction"]["candidates"][0]
        assert_expected(safe_reduction, {
            "distanceReduced": True,
            "minimumDistanceAfter": 6.5,
            "projectedIntercept": False,
            "safetyBoundaryCrossed": False,
        }, "safe distance reduction")

        interception = summaries["projected-interception"]
        self.assertEqual(interception["guardDistanceRejectionCount"], 1)
        self.assertEqual(interception["safeProgressIds"], [])
        assert_expected(interception["candidates"][0], {
            "minimumDistanceBefore": 3.0,
            "minimumDistanceDuring": 1.0,
            "projectedIntercept": True,
            "projectedCollision": False,
            "safetyBoundaryCrossed": True,
        }, "projected interception")
        self.assertFalse(interception["unnecessarySafetySelection"])

        collision = summaries["projected-collision"]["candidates"][0]
        self.assertTrue(collision["projectedIntercept"])
        self.assertTrue(collision["projectedCollision"])
        self.assertEqual(collision["minimumDistanceDuring"], 0.0)

        route_threat = summaries["route-access-threat"]
        self.assertEqual(route_threat["safeProgressIds"], [])
        self.assertTrue(route_threat["candidates"][0]["projectedIntercept"])
        self.assertEqual(
            route_threat["candidates"][0]["routeThreat"]["guardId"], 1
        )

        hold = summaries["historical-hold-with-safe-progress"]
        self.assertEqual(hold["safeProgressIds"], ["climb_ladder"])
        self.assertTrue(hold["unnecessarySafetySelection"])
        self.assertEqual(hold["repeatedNoProgressCount"], 136)

        displacement = summaries["candidate-limit-displacement"]
        self.assertEqual(displacement["safeProgressIds"], ["exposed_progress"])
        self.assertEqual(displacement["candidateLimitDisplacementCount"], 1)

    def test_three_failed_runs_share_medium_dig_selection_miss(self):
        for case in PINCH_ENTRY_CASES:
            with self.subTest(trace=case["traceId"], step=case["displayStep"]):
                pressure = case["pressureGuard"]
                self.assertEqual(pressure["risk"], "medium")
                self.assertTrue(pressure["sameRow"])
                self.assertTrue(pressure["closing"])
                self.assertEqual(pressure["distance"], 4)

                candidates = {item["kind"]: item for item in case["candidates"]}
                self.assertEqual(
                    {kind: candidates[kind]["score"] for kind in candidates},
                    {
                        "defensive_dig": 112,
                        "retreat_from_guard": 108,
                        "align_ladder": 90,
                    },
                )
                self.assertEqual(case["selectedCandidateKind"], "align_ladder")
                self.assertEqual(
                    candidates["align_ladder"]["id"], case["selectedCandidateId"]
                )
                self.assertNotIn(
                    "guard-safe", candidates["align_ladder"]["reason"].lower()
                )
                self.assertNotIn("safe", candidates["align_ladder"]["reason"].lower())
                self.assertIn("guard pressure", candidates["defensive_dig"]["reason"])
                self.assertLessEqual(
                    case["pinch"]["displayStep"] - case["displayStep"], 20
                )
                self.assertEqual(case["pinch"]["exposedCandidateKinds"], [
                    "emergency_hold",
                ])
                self.assertEqual(len(case["pinch"]["sameRowClosingGuards"]), 2)

    def test_latest_pinch_entry_restores_one_bounded_climb(self):
        case = LATEST_PINCH_BOUNDARY
        self.assertEqual((case["traceId"][:8], case["rawStepIndex"]), ("2a15066a", 39))
        prior = case["priorSelection"]
        self.assertEqual(prior["rawStepIndex"], 37)
        self.assertEqual(prior["requestedCandidateId"], "defensive_dig_dig_right")
        self.assertEqual(prior["selectedCandidateId"], "retreat_from_guard_down")
        self.assertTrue(prior["fallbackUsed"])
        self.assertEqual(prior["exposedSafetyScores"], {
            "retreat_from_guard_down": 118,
            "defensive_dig_dig_right": 112,
            "retreat_from_guard_left": 108,
        })
        self.assertEqual(case["priorLoopExit"], {
            "rawStepIndex": 38,
            "suppressedCandidateId": "climb_ladder_4_13_up",
            "selectedCandidateId": "climb_ladder_4_13_down",
        })
        self.assertEqual(len(case["recentCandidateIds"]), 8)

        state = case["state"]
        guards = [{**guard, "actionName": guard["motion"]}
                  for guard in state["guardRisk"]["nearbyGuards"]]
        recomputed = assess_guard_risk({"runner": state["runner"], "guards": guards})
        self.assertEqual(recomputed["pressureGuard"], state["guardRisk"]["pressureGuard"])
        self.assertEqual((recomputed["risk"], len(guards)), ("low", 3))
        pressure = recomputed["pressureGuard"]
        self.assertEqual(
            (pressure["id"], pressure["relativeY"], pressure["closing"], pressure["distance"]),
            (1, "same", True, 6),
        )
        self.assertTrue(state["movement"]["canMoveUp"])
        self.assertTrue(state["movement"]["canMoveLeft"])
        audit = {item["candidateId"]: item for item in case["recordedAudit"]}
        up_id = "climb_ladder_4_14_up"
        right_id = "align_ladder_27_14_right"
        self.assertEqual(set(audit), {up_id, right_id})
        self.assertEqual(audit[up_id]["disposition"], "loop_suppressed")
        self.assertEqual(audit[right_id]["disposition"], "exposed")
        self.assertEqual(case["selectedCandidateId"], right_id)
        self.assertEqual(case["modelRequestedCandidateId"], right_id)
        self.assertFalse(case["fallbackUsed"])
        self.assertEqual(case["selectedAction"], {"keyCode": 39, "ticks": 8})

        analysis = analysis_for(case)
        up = audit[up_id]["proposedAction"]
        self.assertTrue(is_action_physically_valid(up, analysis["movement"], analysis["dig"]))
        self.assertIsNone(action_guard_safety_rejection_detail(
            up, analysis, candidate_kind="climb_ladder"))
        # Reapply the current validator to the recorded proposals. The fixture
        # retains the historical suppression, while the Candidate restores one
        # climb after it sees that the sole exposed route approaches the guard.
        for suppress_up in (False, True):
            with self.subTest(suppress_up=suppress_up):
                analysis = analysis_for(case)
                if suppress_up:
                    analysis["loopReport"] = {
                        "active": True,
                        "type": "vertical_cycle",
                        "suppress": {"directions": ["up"]},
                        "evidence": {"candidateIds": case["recentCandidateIds"]},
                        "suppressedCandidates": [],
                    }
                builder = CandidateBuilder(
                    snapshot={}, analysis=analysis, max_action_ticks=20, limit=7)
                builder.add(kind="climb_ladder", key_code=38, ticks=6,
                            score=108, target={"x": 4, "y": 14, "tile": "H"},
                            reason="recorded upward ladder proposal", candidate_id=up_id)
                builder.add(kind="align_ladder", key_code=39, ticks=8,
                            score=90, target={"x": 27, "y": 14, "tile": "H"},
                            reason="recorded right ladder proposal", candidate_id=right_id)
                exposed, _ = builder.finalize()
                dispositions = {item["candidateId"]: item["disposition"]
                                for item in builder.audit}
                self.assertEqual(dispositions[up_id],
                                 "exposed")
                self.assertEqual(dispositions[right_id], "exposed")
                self.assertEqual([item["id"] for item in exposed], [up_id, right_id])
                if suppress_up:
                    self.assertIn("row-changing option", exposed[0]["reasons"][-1])
                    self.assertEqual(analysis["loopReport"]["suppressedCandidates"], [])

        def replay_control(*, guard_changes=None, recent_ids=None, extra_route=False):
            analysis = analysis_for(case)
            guard = analysis["risk"]["pressureGuard"]
            guard.update(guard_changes or {})
            analysis["risk"]["risk"] = guard["risk"]
            analysis["loopReport"] = {
                "active": True,
                "type": "vertical_cycle",
                "suppress": {"directions": ["up"]},
                "evidence": {"candidateIds": (
                    recent_ids if recent_ids is not None
                    else case["recentCandidateIds"]
                )},
                "suppressedCandidates": [],
            }
            builder = CandidateBuilder(
                snapshot={}, analysis=analysis, max_action_ticks=20, limit=7)
            builder.add(kind="climb_ladder", key_code=38, ticks=6,
                        score=108, target={"x": 4, "y": 14, "tile": "H"},
                        reason="recorded upward ladder proposal", candidate_id=up_id)
            builder.add(kind="align_ladder", key_code=39, ticks=8,
                        score=90, target={"x": 27, "y": 14, "tile": "H"},
                        reason="recorded right ladder proposal", candidate_id=right_id)
            if extra_route:
                builder.add(kind="align_ladder", key_code=37, ticks=4,
                            score=90, target={"x": 1, "y": 14, "tile": "H"},
                            reason="additional safe route", candidate_id="align_ladder_1_14_left")
            exposed, _ = builder.finalize()
            return {item["candidateId"]: item["disposition"] for item in builder.audit}, exposed

        for changes, recent_ids, extra_route in (
            ({"closing": False, "motion": "right"}, None, False),
            ({"distance": 8}, None, False),
            ({"relativeY": "above"}, None, False),
            ({}, case["recentCandidateIds"][:-1] + [up_id], False),
            ({}, [], False),
            ({}, None, True),
        ):
            with self.subTest(changes=changes, recent_ids=recent_ids,
                              extra_route=extra_route):
                dispositions, _ = replay_control(
                    guard_changes=changes, recent_ids=recent_ids,
                    extra_route=extra_route)
                self.assertEqual(dispositions[up_id], "loop_suppressed")

        high, exposed = replay_control(guard_changes={"risk": "high", "distance": 3})
        self.assertEqual(high[up_id], "loop_suppressed")
        self.assertEqual(high[right_id], "safety_rejection")
        self.assertEqual(exposed, [])

        self.assertEqual(case["observedNext"], {
            "rawStepIndex": 40,
            "runner": {"x": 6, "y": 14},
            "pressureGuardId": 1,
            "pressureRisk": "high",
            "pressureDistance": 3,
        })
        terminal = case["terminal"]
        self.assertEqual(terminal["rawStepIndices"], [59, 60, 61, 62, 63])
        self.assertEqual(terminal["risk"], ["critical"] * 5)
        self.assertEqual(terminal["selectedKinds"], ["emergency_hold"] * 5)
        self.assertEqual(terminal["candidateCounts"], [1] * 5)

    def test_post_gold_exit_route_reexposes_immediate_descent(self):
        case = POST_GOLD_REVERSAL_BOUNDARY
        self.assertEqual((case["traceId"][:8], case["rawStepIndices"]),
                         ("9e099955", [225, 226, 227, 228, 229, 230]))
        self.assertTrue(case["goldComplete"])
        self.assertEqual(case["upwardCandidate"], {
            "candidateId": "exit_ladder_route_7_2_up",
            "keyCode": 38,
            "ticks": 20,
            "score": 119,
        })
        self.assertEqual(case["nextCandidates"], {
            "descend_route_7_2_down": 108,
            "align_ladder_18_1_right": 91,
        })
        self.assertEqual(case["selectedCandidateId"], "descend_route_7_2_down")
        self.assertFalse(case["fallbackUsed"])

        history = [deepcopy(case["historyEntry"])]
        runner = deepcopy(case["runnerAfterClimb"])
        entry = deepcopy(case["ladderEntry"])

        # Candidate behavior: both IDs preserve the same upward ladder
        # movement, so neither can expose an immediate reversing descent.
        self.assertTrue(just_climbed_from_entry_ladder(history, runner, entry))
        normal_climb = deepcopy(history)
        normal_climb[-1]["candidateId"] = "climb_ladder_7_2_up"
        self.assertTrue(just_climbed_from_entry_ladder(normal_climb, runner, entry))

        def generated_descent(candidate_history):
            generated = []

            def add(**candidate):
                generated.append(candidate)

            add_descent_candidates(
                add,
                {
                    "runner": runner,
                    "ladder": {"onDownEntry": True, "nearestRowLadder": entry},
                    "primaryProgressTarget": {},
                    "goldComplete": True,
                    "nearestGold": [],
                },
                {"canMoveDown": True},
                candidate_history,
            )
            return generated

        self.assertEqual(generated_descent(history), [])
        self.assertEqual(generated_descent(normal_climb), [])

        # A horizontal arrival above the ladder must keep descent available.
        horizontal_arrival = deepcopy(history)
        horizontal_arrival[-1]["candidateId"] = "align_ladder_7_1_right"
        horizontal_arrival[-1]["keyCode"] = 39
        self.assertFalse(
            just_climbed_from_entry_ladder(horizontal_arrival, runner, entry)
        )
        self.assertEqual(len(generated_descent(horizontal_arrival)), 1)

        self.assertEqual(case["guardContext"], {
            "risk": "low",
            "sameRowClosing": False,
        })

    def test_compound_ladder_cycle_evades_pure_axis_detectors(self):
        case = COMPOUND_LADDER_CYCLE_BOUNDARY
        self.assertEqual((case["traceId"][:8], case["stepCount"]),
                         ("9de4cb06", 300))
        self.assertEqual(case["outcome"], "agent safety step limit reached")

        departed = case["departedLadder"]
        self.assertEqual(departed["selectedCandidateId"],
                         "align_ladder_20_6_left")
        self.assertEqual(departed["observedNextRunner"], {"x": 23, "y": 6})
        down = departed["downCandidate"]
        self.assertEqual(down["disposition"], "physical_rejection")
        self.assertFalse(is_action_physically_valid(
            {"keyCode": down["keyCode"], "ticks": down["ticks"]},
            {"canMoveDown": False}, {}, candidate_kind="climb_ladder",
        ))

        reversal = case["firstReversal"]
        candidates = {item["id"]: item for item in reversal["candidates"]}
        right = candidates["align_ladder_25_6_right"]
        left = candidates["align_ladder_20_6_left"]
        self.assertEqual((right["score"], left["score"]), (104, 99))
        self.assertEqual(reversal["requestedCandidateId"], right["id"])
        self.assertEqual(reversal["selectedCandidateId"], right["id"])
        self.assertFalse(reversal["fallbackUsed"])

        analysis = {
            "godMode": False,
            "runner": reversal["runner"],
            "risk": reversal["guardRisk"],
        }
        self.assertIsNone(action_guard_safety_rejection_detail(
            right["firstAction"], analysis, candidate_kind="align_ladder"))
        self.assertIsNone(action_guard_safety_rejection_detail(
            left["firstAction"], analysis, candidate_kind="align_ladder"))
        self.assertEqual(
            ladder_alignment_score(2, god_mode=False, fine_align=False,
                                   loop_target=False),
            100,
        )
        self.assertEqual(
            low_risk_guard_clearance_score_bonus(
                right["firstAction"], analysis, candidate_kind="align_ladder"),
            4,
        )
        self.assertEqual(
            low_risk_guard_clearance_score_bonus(
                left["firstAction"], analysis, candidate_kind="align_ladder"),
            0,
        )

        early = build_loop_report(
            {
                "activeDig": {},
                "primaryProgressTarget": case["primaryProgressTarget"],
                "movement": {"canMoveLeft": True, "canMoveRight": True,
                             "canMoveUp": False, "canMoveDown": False},
            },
            case["earlyHistory"],
        )
        self.assertEqual(
            {
                "active": early["active"],
                "type": early["type"],
                "noGoldChange": early["evidence"]["noGoldChange"],
                "noRowChange": early["evidence"]["noRowChange"],
                "directionChanges": early["evidence"]["directionChanges"],
            },
            case["recordedStep141Loop"],
        )
        self.assertFalse(early["active"])

        later = build_loop_report(
            {
                "activeDig": {},
                "primaryProgressTarget": {},
                "movement": {"canMoveLeft": True, "canMoveRight": True,
                             "canMoveUp": True, "canMoveDown": True},
            },
            case["laterVerticalHistory"],
        )
        activation = case["firstRecordedLoopActivation"]
        self.assertTrue(later["active"])
        self.assertEqual(later["type"], activation["type"])
        self.assertIn("up", later["suppress"]["directions"])
        self.assertEqual(activation["rawStepIndex"] - reversal["rawStepIndex"], 48)

    def test_retained_main_expectations_against_candidate(self):
        for case in CASES[:3]:
            measured_case = retained_distance_case(case)
            climb = next(
                item for item in measured_case["candidates"]
                if item["kind"] == "climb_ladder"
            )
            self.assertEqual(climb["baselineDisposition"], "safety_rejection")
            self.assertEqual(climb["currentDisposition"], "exposed")
            metrics = measure_candidate(measured_case, climb)
            self.assertEqual(
                len(metrics["guards"]),
                len(case["state"]["guardRisk"]["nearbyGuards"]),
            )
            self.assertFalse(metrics["projectedIntercept"])

    def test_guard_owned_gold_is_not_a_progress_target(self):
        guard_gold = {
            "x": 5, "y": 2, "source": "guard", "distance": 1,
            "sameRow": True, "direction": "right",
        }
        visible_gold = {
            "x": 9, "y": 2, "source": "visible", "distance": 5,
            "sameRow": True, "direction": "right",
        }
        self.assertIsNone(find_primary_progress_target([guard_gold]))
        self.assertEqual(
            find_primary_progress_target([guard_gold, visible_gold])["x"], 9
        )

    def test_recorded_risk_recomputes(self):
        for case in CASES:
            state = case["state"]
            guards = [{**g, "actionName": g["motion"]}
                      for g in state["guardRisk"]["nearbyGuards"]]
            risk = assess_guard_risk({"runner": state["runner"], "guards": guards})
            self.assertEqual(risk["pressureGuard"], state["guardRisk"]["pressureGuard"])

    def test_medium_cross_row_climb_correction_precedes_ranking(self):
        for case in CASES[:3]:
            for score, limit in ((108, 7), (10000, 20)):
                with self.subTest(trace=case["traceId"], step=case["displayStep"], score=score):
                    analysis = analysis_for(case)
                    guard = analysis["risk"]["pressureGuard"]
                    self.assertEqual(guard["risk"], "medium")
                    self.assertFalse(guard["closing"])
                    climb = next(p for p in case["proposals"] if p["kind"] == "climb_ladder")
                    self.assertTrue(is_action_physically_valid(
                        climb["proposedAction"], analysis["movement"], {}, candidate_kind="climb_ladder"))
                    builder = CandidateBuilder(snapshot={}, analysis=analysis,
                                               max_action_ticks=20, limit=limit)
                    builder.add(kind="climb_ladder", key_code=38, ticks=6, score=score,
                                target=climb["target"], reason="recorded ladder proposal")
                    self.assertEqual(climb["disposition"], "safety_rejection")
                    self.assertEqual(builder.audit[0]["disposition"], "validated")
                    candidates, _ = builder.finalize()
                    self.assertEqual([c["kind"] for c in candidates], ["climb_ladder"])
                    # A legal downward action exists at this boundary, but was not
                    # proposed. That does not prove it advances the objective.
                    down = {"keyCode": 40, "ticks": 6}
                    self.assertTrue(is_action_physically_valid(down, analysis["movement"], {}))
                    self.assertIsNone(action_guard_safety_rejection_detail(down, analysis))
                    low = deepcopy(analysis)
                    low["risk"]["pressureGuard"]["risk"] = "low"
                    self.assertIsNone(action_guard_safety_rejection_detail(
                        climb["proposedAction"], low, candidate_kind="climb_ladder"))

    def test_nonclosing_critical_trap_wait_is_justified(self):
        analysis = analysis_for(CASES[3])
        guard = analysis["risk"]["pressureGuard"]
        self.assertEqual((guard["risk"], guard["motion"], guard["closing"]),
                         ("critical", "fall", False))
        builder = CandidateBuilder(snapshot={}, analysis=analysis, max_action_ticks=20, limit=7)
        self.assertTrue(add_trap_resolution_wait_candidate(
            builder.add, analysis["movement"], analysis["risk"]))
        self.assertEqual(builder.candidates[0]["kind"], "wait_for_trap_resolution")
        self.assertEqual(builder.candidates[0]["firstAction"]["ticks"], 2)

    def test_secondary_ladder_guard_is_masked_by_primary_pressure(self):
        case = SECONDARY_LADDER_BOUNDARY
        self.assertEqual((case["traceId"][:8], case["rawStepIndex"], case["displayStep"]),
                         ("a9cffb0c", 59, 60))
        analysis = analysis_for(case)
        guards = analysis["risk"]["nearbyGuards"]
        recomputed = assess_guard_risk({
            "runner": analysis["runner"],
            "guards": [{**g, "actionName": g["motion"]} for g in guards],
        })
        self.assertEqual(recomputed["pressureGuard"], analysis["risk"]["pressureGuard"])
        secondary = next(g for g in guards if g["id"] == 1)
        self.assertEqual((secondary["relativeX"], secondary["relativeY"],
                          secondary["motion"], secondary["distance"], secondary["risk"]),
                         ("same", "below", "up", 2, "high"))
        self.assertFalse(secondary["closing"])
        self.assertEqual([c["score"] for c in case["candidates"]], [118, 108])
        down, left = case["candidates"]
        for candidate in (down, left):
            action = candidate["firstAction"]
            self.assertTrue(is_action_physically_valid(
                action, analysis["movement"], analysis["dig"],
                candidate_kind=candidate["kind"]))
            self.assertIsNone(action_guard_safety_rejection_detail(
                action, analysis, candidate_kind=candidate["kind"]))
        selected, validation = validate_or_fallback_candidate(
            {"choice": {"candidateId": case["requestedCandidateId"]}},
            deepcopy(case["candidates"]), analysis)
        self.assertEqual(selected["id"], down["id"])
        self.assertEqual(validation, case["validation"])

        # Isolate the primary-guard dependency; this is not an alternative engine state.
        control = deepcopy(analysis)
        control["risk"]["pressureGuard"] = deepcopy(secondary)
        self.assertEqual(action_guard_safety_rejection_detail(
            down["firstAction"], control, candidate_kind=down["kind"]),
            "down moves toward the high risk pressure guard below")
        self.assertIsNone(action_guard_safety_rejection_detail(
            left["firstAction"], control, candidate_kind=left["kind"]))
        self.assertEqual([d["rawStepIndex"] for d in case["precedingDecisions"]],
                         list(range(53, 59)))
        self.assertEqual([d["action"]["keyCode"] for d in case["precedingDecisions"]],
                         [40, 40, 38, 40, 38, 38])
        terminal = case["terminal"]
        self.assertEqual((terminal["result"], terminal["reason"]), ("failure", "runner dead"))
        self.assertEqual(terminal["finalState"]["runner"], {
            "action": "down", "x": 4, "xOffset": 0, "y": 13, "yOffset": 1})
        # The trace observes death during descent; it does not prove left would survive.

    def test_secondary_ladder_measurements_keep_motion_and_separation_distinct(self):
        case = SECONDARY_LADDER_BOUNDARY
        analysis = analysis_for(case)
        down, left = case["candidates"]
        secondary = next(g for g in analysis["risk"]["nearbyGuards"] if g["id"] == 1)

        def measure(guard, candidate):
            return measure_guard_clearance(
                analysis["runner"], [guard], candidate["firstAction"])[0]

        observed = measure(secondary, down)
        self.assertEqual((observed["distanceBefore"], observed["minimumDistance"],
                          observed["distanceAfter"]), (2.0, 0.5, 0.5))
        self.assertTrue(observed["safetyBoundaryCrossed"])
        self.assertFalse(measure(secondary, left)["projectedIntercept"])
        for changes in ({"motion": "down"}, {"motion": "in_hole"},
                        {"x": 7}, {"y": 16, "distance": 4, "risk": "medium"}):
            with self.subTest(changes=changes):
                control = {**secondary, **changes}
                self.assertFalse(measure(control, down)["projectedIntercept"])
        trapped = measure({**secondary, "motion": "in_hole"}, down)
        self.assertFalse(trapped["active"])
        # These diagnostic projections do not implement a new rejection rule.
        for key in (37, 39):
            rejected = action_guard_safety_rejection_detail(
                {"keyCode": key, "ticks": 4}, analysis,
                candidate_kind="retreat_from_guard")
            self.assertEqual(rejected is not None, key == 39)

    def test_terminal_pinch_keeps_both_horizontal_rejections(self):
        analysis = analysis_for(CASES[4])
        for key in (37, 39):
            self.assertIsNotNone(action_guard_safety_rejection_detail(
                {"keyCode": key, "ticks": 2}, analysis))
        self.assertIsNone(action_guard_safety_rejection_detail(
            {"keyCode": 32, "ticks": 2}, analysis, candidate_kind="emergency_hold"))

    def test_repeated_hold_does_not_activate_loop_recovery(self):
        case = CASES[1]
        analysis = analysis_for(case)
        hold = next(p for p in case["proposals"] if p["kind"] == "emergency_hold")
        history = [{"candidateId": hold["candidateId"], "keyCode": 32,
                    "after": {"runner": case["state"]["runner"], "goldCount": 2}}
                   for _ in range(10)]
        report = build_loop_report(analysis, history)
        self.assertFalse(report["active"])
        self.assertTrue(report["evidence"]["environmentProgressDominated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
