import { readFileSync } from "node:fs";

const laneMap = JSON.parse(
  readFileSync(new URL("../agent/candidate_lanes.json", import.meta.url), "utf8"),
);

export const CANDIDATE_LANES = Object.freeze(laneMap);
export const KNOWN_LANES = Object.freeze(["safety", "progress", "environment", "fallback"]);

const EXECUTION_GATE_KINDS = new Set([
  "wait_for_dig_completion",
  "wait_for_trap_resolution",
  "wait_for_floor_refill",
]);

const ACTION_NAMES = Object.freeze({ 37: "left", 38: "up", 39: "right", 40: "down" });

export function candidateLane(candidateOrKind) {
  const kind = typeof candidateOrKind === "string" ? candidateOrKind : candidateOrKind?.kind;
  return CANDIDATE_LANES[kind] || "fallback";
}

export function candidateLaneSet(candidates) {
  return [...new Set((candidates || []).map(candidateLane))].sort();
}

export function isProgressOnlyLowRiskStep(step) {
  const candidates = Array.isArray(step?.candidates) ? step.candidates : [];
  const lanes = candidateLaneSet(candidates);
  return (
    candidates.length > 0 &&
    lanes.length === 1 &&
    lanes[0] === "progress" &&
    step?.state?.guardRisk?.risk === "low" &&
    !step?.state?.activeDig?.active &&
    !step?.loopMonitor?.active
  );
}

export function decisionClass(step) {
  const candidates = Array.isArray(step?.candidates) ? step.candidates : [];
  if (!candidates.length) return "no_candidates";
  if (isProgressOnlyLowRiskStep(step)) return "progress_only_low_risk";
  const lanes = candidateLaneSet(candidates);
  if (lanes.length === 1) return `${lanes[0]}_only`;
  return `mixed_${lanes.join("_")}`;
}

export function classifySingletonStep(step) {
  const candidates = Array.isArray(step?.candidates) ? step.candidates : [];
  if (candidates.length !== 1) return null;
  const candidate = candidates[0];
  const kind = candidate?.kind || "unknown";
  const lane = candidateLane(candidate);
  if (kind === "emergency_hold") {
    return { classification: "emergency_hold_singleton", evidence: [] };
  }
  if (EXECUTION_GATE_KINDS.has(kind)) {
    return { classification: "legitimate_execution_gate", evidence: [] };
  }
  if (lane === "safety") {
    return { classification: "legitimate_forced_safety", evidence: [] };
  }
  if (lane === "progress") {
    const evidence = progressAlternativeEvidence(step, candidate);
    return {
      classification: evidence.length
        ? "suspicious_progress_singleton"
        : "legitimate_forced_progress",
      evidence,
    };
  }
  return {
    classification: "suspicious_fallback_singleton",
    evidence: [`${kind} is not a known progress, safety, or execution-gate candidate`],
  };
}

function progressAlternativeEvidence(step, selected) {
  if (!isProgressOnlyLowRiskStep(step)) return [];
  const state = step?.state || {};
  const movement = state.movement || {};
  const runner = state.runner || {};
  const selectedAction = ACTION_NAMES[selected?.firstAction?.keyCode] || null;
  const evidence = [];
  const addAlternative = (action, reason) => {
    const field = `canMove${action[0].toUpperCase()}${action.slice(1)}`;
    if (action && action !== selectedAction && movement[field] && !evidence.includes(reason)) {
      evidence.push(reason);
    }
  };

  const target = state.primaryProgressTarget || {};
  if (target.sameRow && ["left", "right"].includes(target.direction)) {
    addAlternative(target.direction, `primary same-row target supports ${target.direction}`);
  } else if (Number.isFinite(Number(target.y)) && Number.isFinite(Number(runner.y))) {
    const vertical = Number(target.y) < Number(runner.y) ? "up" : "down";
    addAlternative(vertical, `primary target row supports ${vertical}`);
  }

  for (const gold of state?.gold?.visiblePositions || []) {
    if (Number(gold?.y) !== Number(runner?.y) || Number(gold?.x) === Number(runner?.x)) continue;
    const direction = Number(gold.x) < Number(runner.x) ? "left" : "right";
    addAlternative(direction, `visible same-row gold supports ${direction}`);
  }

  const route = state.routeAccess || {};
  if (route.available && route.recommendedAction) {
    addAlternative(route.recommendedAction, `route access supports ${route.recommendedAction}`);
  }
  if (route.followAvailable && route.followAction) {
    addAlternative(route.followAction, `open route supports ${route.followAction}`);
  }

  const ladderDetail = String(state?.ladder?.detail || "");
  for (const action of ["left", "right", "up", "down"]) {
    if (new RegExp(`(?:use|move) ${action}\\b`, "i").test(ladderDetail)) {
      addAlternative(action, `ladder affordance supports ${action}`);
    }
  }
  return evidence;
}
