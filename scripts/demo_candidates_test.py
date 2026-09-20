"""Offline adapter contracts; no live services or provider dependencies."""
import copy
import importlib.util
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("adapter", Path(__file__).with_name("demo-candidates.py"))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = {"playData": 1, "level": 1, "tick": 0, "gameStateName": "running", "godMode": False,
                      "runner": {"x": 2, "y": 1, "xOffset": 0, "yOffset": 0}, "guards": [],
                      "goldCount": 1, "goldComplete": False,
                      "gold": {"complete": False, "remainingCount": 1, "visiblePositions": [{"x": 4, "y": 1}], "carriedByGuards": []},
                      "terrainGrid": ["      ", " H  $ ", "######"], "grid": ["      ", " H  $ ", "######"]}
        self.config = {"backend": {"candidateLimit": 7, "maxActionTicks": 20}, "agent": {"historyLimit": 24}}

    def test_no_service_import(self):
        self.assertNotIn("agent.service", sys.modules)
        self.assertNotIn("aisuite", sys.modules)
        self.assertNotIn("_demo_agent.service", sys.modules)

    def test_instrumentation_preserves_rank_and_input(self):
        before = copy.deepcopy(self.state)
        expected, _ = adapter.module.generate_candidates(self.state, [])
        with patch.object(adapter.module, "CandidateBuilder", adapter.CaptureBuilder):
            actual, analysis = adapter.module.generate_candidates(self.state, [])
        self.assertEqual(expected, actual)
        self.assertEqual(self.state, before)
        self.assertEqual(actual, analysis["eligiblePool"][:7])
        self.assertTrue(all("score" in row for row in analysis["candidateAudit"]))

    def test_set_labels_and_observed_history(self):
        snapshots = [dict(self.state, tick=t) for t in [0, 10, 20]]
        payload = {"states": snapshots, "config": self.config, "demo": {"action": [0, 39]}}
        original = copy.deepcopy(payload)
        candidate = {"id": "a", "firstAction": {"keyCode": 39, "ticks": 10}}
        alternative = dict(candidate, id="b")
        with patch.object(adapter.module, "generate_candidates", return_value=(
            [candidate], {"eligiblePool": [candidate, alternative], "candidateAudit": []})):
            result = adapter.analyze(payload)
        self.assertEqual(result["decisions"][0]["exactCandidateIds"], ["a", "b"])
        self.assertTrue(result["decisions"][0]["trainingEligible"])
        self.assertNotIn("candidateId", result["decisions"][1]["history"][0])
        self.assertEqual(payload, original)

    def test_socket_prohibition(self):
        # Test the patched entry points without allocating an OS socket. Restricted
        # Linux environments may deny socket creation before connect is reached.
        for method in ("connect", "connect_ex"):
            with self.subTest(method=method), \
                    patch.object(socket.socket, "__init__", side_effect=PermissionError) as constructor, \
                    patch.object(socket.socket, method, adapter.deny_network):
                with self.assertRaisesRegex(RuntimeError, "Network is forbidden"):
                    getattr(socket.socket, method)(object(), ("127.0.0.1", 1))
                constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
