"""Offline demo analysis. No service, provider, Flask, or persistence imports."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import socket
import sys
import types
from unittest.mock import patch

# agent.__init__ imports the provider service. Give the offline files a separate
# package namespace so their relative imports work without executing that initializer.
package = types.ModuleType("_demo_agent")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "agent")]
sys.modules[package.__name__] = package
module = importlib.import_module("_demo_agent.candidates")


def deny_network(*args, **kwargs):
    raise RuntimeError("Network is forbidden in offline candidate analysis")


def summarize(snapshot):
    return {
        "playData": snapshot["playData"], "level": snapshot["level"],
        "tick": snapshot["tick"], "state": snapshot["gameStateName"],
        "goldCount": snapshot["goldCount"], "goldComplete": snapshot["goldComplete"],
        "runner": {**snapshot["runner"], "action": snapshot["runner"].get("actionName")},
    }


class CaptureBuilder(module.CandidateBuilder):
    """Keep instrumentation local to this subprocess, including rejected proposals."""
    def add(self, **kwargs):
        offset = len(self.audit)
        super().add(**kwargs)
        for row in self.audit[offset:]:
            row["score"] = kwargs["score"]
            row["reason"] = kwargs["reason"]

    def finalize(self):
        self.analysis["preFinalizationPool"] = copy.deepcopy(self.candidates)
        exposed, analysis = super().finalize()
        analysis["eligiblePool"] = copy.deepcopy(self.candidates)
        return exposed, analysis


def analyze(payload):
    states, config = payload["states"], payload["config"]
    history, rows = [], []
    actions = payload["demo"]["action"]
    for index, before in enumerate(states[:-1]):
        after = states[index + 1]
        ticks = after["tick"] - before["tick"]
        if ticks <= 0:
            raise ValueError("Decision samples must have increasing demo ticks")
        action_index = max(i for i in range(0, len(actions), 2) if actions[i] <= before["tick"])
        demonstrated = {"keyCode": actions[action_index + 1], "ticks": ticks}
        shortlist, analysis = module.generate_candidates(
            before, history, limit=config["backend"]["candidateLimit"],
            max_action_ticks=config["backend"]["maxActionTicks"],
        )
        pool = analysis["eligiblePool"]
        same_key = lambda c: c["firstAction"]["keyCode"] == demonstrated["keyCode"]
        exact = [c["id"] for c in pool if same_key(c) and c["firstAction"]["ticks"] == ticks]
        exposed = {c["id"] for c in shortlist}
        audit = analysis["candidateAudit"]
        rejected = [a for a in audit if a.get("validatedAction", a["proposedAction"])["keyCode"] == demonstrated["keyCode"]
                    and a.get("validatedAction", a["proposedAction"])["ticks"] == ticks
                    and a["disposition"] in {"loop_suppressed", "physical_rejection", "safety_rejection"}]
        if exact:
            classification = "exact_exposed" if exposed.intersection(exact) else "exact_truncated"
        elif rejected:
            classification = "suppressed_or_rejected"
        elif any(same_key(c) for c in pool):
            classification = "duration_mismatch"
        else:
            classification = "missing_candidate"
        # Multiple semantic candidates with the same executable action are a set label,
        # not evidence identifying one particular intent or target.
        rows.append({
            "tick": before["tick"], "afterTick": after["tick"], "demonstratedAction": demonstrated,
            "history": copy.deepcopy(history), "shortlist": shortlist,
            "analysis": analysis, "classification": classification,
            "exactCandidateIds": exact,
            "ambiguousCandidateIds": [c["id"] for c in pool if same_key(c) and c["id"] not in exact],
            "matchingRejectedProposals": rejected,
            "trainingEligible": bool(exact), "labelMeaning": "executable_action_equivalence",
        })
        # Always observed history; even exact key matches do not establish intent IDs.
        history.append({**demonstrated, "tick": before["tick"], "afterTick": after["tick"],
                        "state": before["gameStateName"], "afterState": after["gameStateName"],
                        "before": summarize(before), "after": summarize(after)})
        history = history[-config["agent"]["historyLimit"]:]
    counts = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {"decisions": rows, "coverage": {"decisions": len(rows), "classes": counts,
            "usableLabels": sum(r["trainingEligible"] for r in rows),
            "historyLimitation": "Observed actions only; candidate-ID-dependent loop detection has no inferred IDs."}}


if __name__ == "__main__":
    with patch.object(socket.socket, "connect", deny_network), patch.object(socket.socket, "connect_ex", deny_network), \
            patch.object(module, "CandidateBuilder", CaptureBuilder):
        print(json.dumps(analyze(json.load(sys.stdin)), allow_nan=False))
