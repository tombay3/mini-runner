"""Candidate output smoke checks; no services, models or stored-data writes."""
import copy
import json
import math
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Keep the existing isolated import: no production provider service is needed.
package = types.ModuleType("_scoring_agent")
package.__path__ = [str(ROOT / "agent")]
sys.modules[package.__name__] = package
from _scoring_agent.candidates import generate_candidates
from _scoring_agent.traces import serialize_step_trace


def snapshot(*, guarded=False, exit_state=False):
    grid = ["  H    ", "  H    ", "#######"] if exit_state else ["       ", "       ", "#######"]
    gold = {"remainingCount": 0 if exit_state else 1, "complete": exit_state,
            "visiblePositions": [] if exit_state else [{"x": 4, "y": 1}], "carriedByGuards": []}
    return {
        "playData": 1, "level": 1, "tick": 0, "gameStateName": "running", "godMode": False,
        "runner": {"x": 2, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [{"id": 0, "x": 5, "y": 1, "xOffset": 0, "yOffset": 0,
                    "actionName": "left", "hasGold": 0}] if guarded else [],
        "gold": gold, "goldCount": gold["remainingCount"], "goldComplete": exit_state,
        "terrainGrid": grid, "grid": grid, "openHoles": [], "activeDig": None,
    }


class CandidateSmokeTests(unittest.TestCase):
    def test_candidate_output(self):
        for name, options in (("progress", {}), ("guarded", {"guarded": True}),
                              ("exit", {"exit_state": True})):
            with self.subTest(scenario=name):
                state = snapshot(**options)
                original = copy.deepcopy(state)
                pool, analysis = generate_candidates(state, [], limit=7, max_action_ticks=20)
                self.assertEqual(state, original)
                self.assertTrue(0 < len(pool) <= 7)
                self.assertEqual(len({c["id"] for c in pool}), len(pool))
                for candidate in pool:
                    self.assertIsInstance(candidate["id"], str)
                    self.assertIn(candidate["lane"], {"safety", "progress", "environment"})
                    self.assertIn(type(candidate["score"]), {int, float})
                    self.assertTrue(math.isfinite(candidate["score"]))
                    action = candidate["firstAction"]
                    self.assertIn(action["keyCode"], {32, 37, 38, 39, 40, 88, 90})
                    self.assertIs(type(action["ticks"]), int)
                    self.assertTrue(1 <= action["ticks"] <= 20)
                selected = pool[0]
                trace = serialize_step_trace(
                    snapshot=state, action=selected["firstAction"], candidates=pool,
                    selected_candidate=selected, analysis=analysis,
                    validation={"requestedCandidateId": selected["id"], "fallbackUsed": False},
                )
                self.assertEqual(trace["decision"]["selectedId"], selected["id"])
                self.assertEqual(trace["action"], {k: selected["firstAction"][k] for k in ("keyCode", "ticks")})
                json.dumps(trace, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
