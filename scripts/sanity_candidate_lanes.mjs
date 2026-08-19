import assert from "node:assert/strict";

import {
  candidateLane,
  candidateLaneSet,
  classifySingletonStep,
  decisionClass,
  isProgressOnlyLowRiskStep,
} from "./candidate-lanes.mjs";

assert.equal(candidateLane("retreat_from_guard"), "safety");
assert.equal(candidateLane("classic_gold_route"), "progress");
assert.equal(candidateLane("wait_for_dig_completion"), "environment");
assert.equal(candidateLane("unknown_kind"), "fallback");

const progressOnly = {
  state: { guardRisk: { risk: "low" }, activeDig: {} },
  loopMonitor: { active: false },
  candidates: [
    { kind: "classic_gold_route" },
    { kind: "low_risk_progress_option" },
  ],
};
assert.deepEqual(candidateLaneSet(progressOnly.candidates), ["progress"]);
assert.equal(isProgressOnlyLowRiskStep(progressOnly), true);
assert.equal(decisionClass(progressOnly), "progress_only_low_risk");
assert.equal(
  isProgressOnlyLowRiskStep({
    ...progressOnly,
    candidates: [...progressOnly.candidates, { kind: "retreat_from_guard" }],
  }),
  false,
);

const forcedProgress = {
  state: {
    guardRisk: { risk: "low" },
    activeDig: {},
    runner: { x: 10, y: 10 },
    movement: { canMoveUp: true },
    primaryProgressTarget: { x: 10, y: 5, sameRow: false },
  },
  loopMonitor: { active: false },
  candidates: [{ kind: "climb_ladder", firstAction: { keyCode: 38, ticks: 6 } }],
};
assert.equal(classifySingletonStep(forcedProgress).classification, "legitimate_forced_progress");
assert.equal(
  classifySingletonStep({
    ...forcedProgress,
    state: {
      ...forcedProgress.state,
      movement: { canMoveUp: true, canMoveLeft: true },
      primaryProgressTarget: { x: 5, y: 10, sameRow: true, direction: "left" },
    },
  }).classification,
  "suspicious_progress_singleton",
);
assert.equal(
  classifySingletonStep({ candidates: [{ kind: "wait_for_dig_completion" }] }).classification,
  "legitimate_execution_gate",
);
assert.equal(
  classifySingletonStep({ candidates: [{ kind: "retreat_from_guard" }] }).classification,
  "legitimate_forced_safety",
);
assert.equal(
  classifySingletonStep({ candidates: [{ kind: "emergency_hold" }] }).classification,
  "emergency_hold_singleton",
);
assert.equal(
  classifySingletonStep({ candidates: [{ kind: "unknown_kind" }] }).classification,
  "suspicious_fallback_singleton",
);
assert.equal(
  isProgressOnlyLowRiskStep({
    ...progressOnly,
    state: { ...progressOnly.state, guardRisk: { risk: "high" } },
  }),
  false,
);
assert.equal(
  isProgressOnlyLowRiskStep({
    ...progressOnly,
    state: { ...progressOnly.state, activeDig: { active: true } },
  }),
  false,
);

process.stdout.write("candidate lane sanity ok\n");
