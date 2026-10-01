"""Offline boundary checks, with an opt-in paid model decision check."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.prompt import format_candidate
from agent.service import preferred_guard_policy_candidate, validate_or_fallback_candidate

CASES = json.loads((Path(__file__).parent / "fixtures/guard-selection-boundary.json").read_text())["cases"]
ROOT = Path(__file__).resolve().parent.parent
ONLINE_CASES = (
    ("original-dig", "fixture", "c9e7f719-a0b2-4687-9cdd-04e0921b244e", 145, "highest-safety"),
    ("nearer-ladder", "trace", "670319e6-8522-4992-92d1-f161bc101fb3", 8, "highest-ladder"),
    ("dig-versus-descent", "trace", "670319e6-8522-4992-92d1-f161bc101fb3", 30, "highest-safety"),
)


def _online_case(source, trace_id, step_index):
    if source == "fixture":
        return next(case for case in CASES if case["traceId"] == trace_id and case["stepIndex"] == step_index)
    runs = json.loads((ROOT / "__data1" / "agent-traces.json").read_text())["runs"]
    run = runs[trace_id]
    step = next(item for item in run["steps"] if item["stepIndex"] == step_index)
    return {"traceId": trace_id, "stepIndex": step_index, "state": step["state"], "candidates": step["candidates"]}


def _prompt_inputs(case):
    state = case["state"]
    snapshot = {
        "playData": 1,
        "level": 1,
        "gameStateName": state.get("gameState", "running"),
        "godMode": bool(state.get("godMode")),
    }
    analysis = {
        "runner": state.get("runner") or {},
        "gold": state.get("gold") or {},
        "primaryProgressTarget": state.get("primaryProgressTarget") or {},
        "risk": state.get("guardRisk") or {},
        "movement": state.get("movement") or {},
        "ladder": state.get("ladder") or {},
        "routeAccess": state.get("routeAccess") or {},
        "loopReport": {},
    }
    return snapshot, analysis


def _expected_ids(candidates, rule):
    if rule == "highest-safety":
        eligible = [item for item in candidates if item.get("lane") == "safety"]
    else:
        eligible = [item for item in candidates if item.get("kind") == "align_ladder" and item.get("firstAction", {}).get("keyCode") in (37, 39)]
    top_score = max(int(item["score"]) for item in eligible)
    return [item["id"] for item in eligible if int(item["score"]) == top_score]


def online_decision_check(output_path):
    from agent.config import load_public_agent_config, reload_dotenv_files
    from agent.prompt import build_agent_prompt
    from agent.service import get_aisuite_agent_client, run_model_turn

    reload_dotenv_files()
    config = load_public_agent_config()
    client = get_aisuite_agent_client()
    model = client.resolve_model_profile("openai", source="request")
    results = []
    report = {
        "recordedSourceRevision": "95781f45dc60a9a2cb5dee6ad04b858ffcc3fd45",
        "model": model.model,
        "temperature": config["backend"]["temperature"],
        "limitations": "Recorded trace summaries omit merged candidate metadata, full loop state, and engine checkpoints; reconstructed prompts are not byte-identical to the original live prompts. No game action is executed.",
        "results": results,
    }
    for name, source, trace_id, step_index, rule in ONLINE_CASES:
        case = _online_case(source, trace_id, step_index)
        snapshot, analysis = _prompt_inputs(case)
        candidates = case["candidates"]
        expected = _expected_ids(candidates, rule)
        prompt = build_agent_prompt(snapshot, candidates=candidates, analysis=analysis, include_reasoning=True)
        result = run_model_turn(client, model, snapshot, candidates, analysis, {}, config)
        choice = result.get("choice") or {}
        selected_id = choice.get("candidateId")
        row = {
            "case": name,
            "traceId": trace_id,
            "displayStep": step_index + 1,
            "rule": rule,
            "candidateScores": {item["id"]: item["score"] for item in candidates},
            "expectedCandidateIds": expected,
            "requestedCandidateId": selected_id,
            "knownCandidate": selected_id in {item["id"] for item in candidates},
            "ruleSatisfied": selected_id in expected,
            "parseError": result.get("parseError"),
            "promptSha256": hashlib.sha256(prompt.encode()).hexdigest(),
        }
        results.append(row)
        output_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{name}: {selected_id or 'no valid ID'}; expected {', '.join(expected)}; {'pass' if row['ruleSatisfied'] else 'fail'}", flush=True)
        if not row["ruleSatisfied"]:
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="send at most three recorded decisions to the configured OpenAI model")
    parser.add_argument("--output", type=Path, help="write a compact report after each paid decision")
    args = parser.parse_args()
    if args.online:
        if args.output is None:
            parser.error("--online requires --output")
        online_decision_check(args.output)
    else:
        unittest.main(argv=[sys.argv[0]])


class SelectionBoundaryTests(unittest.TestCase):
    def test_scoped_policy_corrects_recorded_score_misses(self):
        dig_case, cross_case = CASES[:2]
        dig_candidates = dig_case["candidates"]
        dig_analysis = {
            "risk": dig_case["state"]["guardRisk"],
            "movement": dig_case["state"]["movement"],
            "runner": dig_case["state"]["runner"],
            "dig": {"canDigRight": True},
        }
        selected, validation = validate_or_fallback_candidate(
            {"choice": {"candidateId": dig_candidates[1]["id"]}},
            dig_candidates, dig_analysis,
        )
        self.assertEqual(selected["id"], dig_candidates[0]["id"])
        self.assertTrue(validation["fallbackUsed"])
        self.assertTrue(validation["knownCandidate"])

        descent = {
            "id": "retreat_from_guard_down", "kind": "retreat_from_guard",
            "lane": "safety", "score": 118,
            "firstAction": {"keyCode": 40, "ticks": 6},
        }
        with_descent = [descent, *dig_candidates]
        dig_analysis["movement"] = {**dig_analysis["movement"], "canMoveDown": True}
        preferred, _ = preferred_guard_policy_candidate(dig_candidates[0], with_descent, dig_analysis)
        self.assertEqual(preferred["id"], descent["id"])
        high_progress = deepcopy(dig_candidates[2])
        high_progress["score"] = 140
        preferred, _ = preferred_guard_policy_candidate(high_progress, [high_progress, *dig_candidates], dig_analysis)
        self.assertEqual(preferred["id"], dig_candidates[0]["id"])

        cross_candidates = cross_case["candidates"]
        cross_analysis = {
            "risk": cross_case["state"]["guardRisk"],
            "movement": cross_case["state"]["movement"],
            "runner": cross_case["state"]["runner"],
            "dig": {},
        }
        selected, validation = validate_or_fallback_candidate(
            {"choice": {"candidateId": cross_candidates[1]["id"]}},
            cross_candidates, cross_analysis,
        )
        self.assertEqual(selected["id"], cross_candidates[0]["id"])
        self.assertTrue(validation["fallbackUsed"])
        self.assertTrue(validation["knownCandidate"])

    def test_scoped_policy_preserves_gates_and_other_risks(self):
        case = CASES[0]
        dig, retreat, _progress = case["candidates"]
        base = {"risk": case["state"]["guardRisk"]}
        controls = (
            {"godMode": True},
            {"activeDig": {"active": True}},
            {"risk": {**base["risk"], "risk": "high"}},
            {"risk": {**base["risk"], "pressureGuard": {**base["risk"]["pressureGuard"], "closing": False}}},
        )
        for update in controls:
            with self.subTest(control=update):
                preferred, _ = preferred_guard_policy_candidate(retreat, [dig, retreat], {**base, **update})
                self.assertIsNone(preferred)
        wait = {"id": "wait_for_trap_resolution", "kind": "wait_for_trap_resolution", "lane": "safety", "score": 120}
        preferred, _ = preferred_guard_policy_candidate(retreat, [wait, dig, retreat], base)
        self.assertIsNone(preferred)
        tied = deepcopy(retreat)
        tied["score"] = dig["score"]
        preferred, _ = preferred_guard_policy_candidate(tied, [dig, tied], base)
        self.assertIsNone(preferred)

        cross = CASES[1]
        left, right = cross["candidates"]
        cross_risk = cross["state"]["guardRisk"]
        cross_controls = (
            {"risk": {**cross_risk, "risk": "low"}},
            {"risk": {**cross_risk, "nearbyGuards": [
                *cross_risk["nearbyGuards"],
                {"relativeY": "same", "risk": "medium"},
            ]}},
            {"activeDig": {"active": True}},
            {"godMode": True},
        )
        for update in cross_controls:
            with self.subTest(cross_control=update):
                preferred, _ = preferred_guard_policy_candidate(
                    right, [left, right], {"risk": cross_risk, **update}
                )
                self.assertIsNone(preferred)
        safety = {"id": "retreat_from_guard_left", "kind": "retreat_from_guard", "lane": "safety", "score": 108}
        preferred, _ = preferred_guard_policy_candidate(right, [safety, left, right], {"risk": cross_risk})
        self.assertIsNone(preferred)

    def test_online_cases_are_bounded_and_use_recorded_scores(self):
        self.assertEqual(len(ONLINE_CASES), 3)
        _, source, trace_id, step_index, rule = ONLINE_CASES[0]
        case = _online_case(source, trace_id, step_index)
        self.assertEqual(_expected_ids(case["candidates"], rule), ["defensive_dig_dig_right"])
        snapshot, analysis = _prompt_inputs(case)
        self.assertEqual((snapshot["playData"], snapshot["level"]), (1, 1))
        self.assertEqual(analysis["risk"]["risk"], "medium")

    def test_historical_lower_score_choices_outside_new_rule_still_survive(self):
        for case in CASES[2:]:
            with self.subTest(trace=case["traceId"], index=case["stepIndex"]):
                state = case["state"]
                # Only selected horizontal actions are revalidated. Missing dig
                # affordances must not be invented to claim full generation replay.
                analysis = {**state, "risk": state["guardRisk"], "dig": {}}
                selected, validation = validate_or_fallback_candidate(
                    {"choice": {"candidateId": case["selectedCandidateId"]}},
                    case["candidates"], analysis,
                )
                self.assertEqual(validation, case["validation"])
                self.assertFalse(validation["fallbackUsed"])
                self.assertEqual(selected["firstAction"], case["action"])
                self.assertLess(selected["score"], case["candidates"][0]["score"])

    def test_new_reason_reaches_prompt_formatter(self):
        case = CASES[0]
        dig, retreat, progress = map(format_candidate, case["candidates"])
        self.assertEqual([dig["score"], retreat["score"], progress["score"]], [112, 108, 90])
        self.assertIn("closing same-row guard can fall", dig["reasons"][0])
        self.assertEqual(dig["intents"], ["defensive_dig"])
        self.assertEqual(dig["lane"], retreat["lane"])
        self.assertEqual(retreat["action"], progress["action"])
        for old in CASES[2:]:
            self.assertEqual(old["state"]["guardRisk"]["pressureGuard"]["distance"], 4)
            self.assertEqual(old["candidates"][0]["score"], 112)
            self.assertNotIn("can fall", format_candidate(old["candidates"][0])["reasons"][0])

    def test_cross_row_control_keeps_backend_ranking(self):
        left, right = CASES[1]["candidates"]
        self.assertEqual([left["score"], right["score"]], [90, 87])
        self.assertEqual(CASES[1]["selectedCandidateId"], right["id"])
        self.assertEqual(left["lane"], right["lane"])


if __name__ == "__main__":
    main()
