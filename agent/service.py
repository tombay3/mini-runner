from __future__ import annotations

import json
from typing import Any

from aisuite.provider import LLMError

from .aisuite_client import get_aisuite_agent_client
from .config import (
    AGENT_TEMPERATURE,
    AGENT_TOOL_MAX_TURNS,
    get_benchmark_models,
    get_default_agent_model,
)
from .errors import AgentConfigError, AgentExecutionError
from .prompt import build_agent_prompt
from .reasoning_tools import (
    DIG_LEFT_KEYCODE,
    DIG_RIGHT_KEYCODE,
    LEFT_KEYCODE,
    DOWN_KEYCODE,
    RIGHT_KEYCODE,
    STOP_KEYCODE,
    UP_KEYCODE,
    assess_guard_risk,
    assess_safe_progress_options,
    build_reasoning_tools,
    detect_progress_stall,
    find_nearest_gold_candidates,
    find_row_ladders,
    get_dig_affordance,
    get_escape_affordance,
    get_ladder_affordance,
    get_movement_affordance,
    get_route_access_affordance,
)
from .traces import serialize_step_trace
from .validation import normalize_agent_action

PROGRESS_RETRY_NOTE = (
    "The previous candidate repeated a stalled retreat pattern. Choose a progress action instead: "
    "collect nearby safe gold, climb a reachable visible ladder, or otherwise change row or route. "
    "Do not repeat the same retreat direction or stop unless danger is immediate."
)
LADDER_RETRY_NOTE = (
    "The previous candidate reached an active ladder but did not climb it. The runner is on a ladder now; "
    "choose a vertical climb action, preferably up for Classic level 1 row 14, unless doing so causes immediate death."
)
SAFETY_RETRY_NOTE = (
    "The previous candidate moved toward same-row guard danger or chose an invalid escape. Choose a physically valid "
    "safety action: climb only if movementAffordance says up/down is valid now, dig a legal trap if available, "
    "or move away from the nearest same-row guard."
)
FEASIBILITY_RETRY_NOTE = (
    "The previous candidate is not physically valid from the current tile. Use movementAffordance and digAffordance: "
    "do not choose up/down unless currently climbable, and do not choose a dig action unless its canDig flag is true."
)
GOD_MODE_PROGRESS_RETRY_NOTE = (
    "God mode is active, so guard contact is non-lethal. Do not waste the move on survival-only retreat. "
    "Choose a physically valid progress action: collect gold, line up a ladder, climb if valid now, or change route."
)
ROUTE_ACCESS_RETRY_NOTE = (
    "Gold remains and no same-row ladder or same-row gold is available. A legal route-access dig is available. "
    "Use the exact recommended dig action and matching keyCode to open a descent/access route instead of moving "
    "horizontally to create space."
)
ROUTE_ACCESS_EXIT_RETRY_NOTE = (
    "The route-access dig has already been repeated from the same tile without row or gold progress. "
    "Do not dig again. Move into the opened access path toward the remaining lower gold."
)
ROUTE_DESCENT_RETRY_NOTE = (
    "The remaining gold is below on the current x-column and movementAffordance says down is valid. "
    "Do not dig; descend now."
)
LADDER_DESCENT_RETRY_NOTE = (
    "The runner is on a ladder and remaining gold is below on the current x-column. "
    "Do not climb up; continue down toward the lower gold."
)
ROUTE_ACCESS_MIN_TICKS = 8
PROGRESS_APPROACH_MIN_TICKS = 8

ACTION_NAMES = {
    STOP_KEYCODE: "stop",
    LEFT_KEYCODE: "left",
    RIGHT_KEYCODE: "right",
    UP_KEYCODE: "up",
    DOWN_KEYCODE: "down",
    DIG_LEFT_KEYCODE: "dig_left",
    DIG_RIGHT_KEYCODE: "dig_right",
}

DIG_ACTION_KEYCODES = {
    "dig_left": DIG_LEFT_KEYCODE,
    "dig_right": DIG_RIGHT_KEYCODE,
}

ACTION_KEYCODES = {
    "stop": STOP_KEYCODE,
    "left": LEFT_KEYCODE,
    "right": RIGHT_KEYCODE,
    "up": UP_KEYCODE,
    "down": DOWN_KEYCODE,
    **DIG_ACTION_KEYCODES,
}


def plan_next_action(
    snapshot: dict[str, Any], history: list[dict[str, Any]], options: dict[str, Any]
) -> dict[str, Any]:
    client = get_aisuite_agent_client()
    requested_model = resolve_requested_model(client, options)
    run_mode = options.get("runMode", "single")

    if run_mode == "benchmark":
        return run_benchmark(snapshot, history, options, requested_model, client)
    return run_single(snapshot, history, run_mode, requested_model, client)


def resolve_requested_model(client, options: dict[str, Any]) -> str:
    requested = options.get("model")
    if requested:
        return client.resolve_model_name(requested, source="request")

    default_model = get_default_agent_model()
    if not default_model:
        raise AgentConfigError("AGENT_DEFAULT_MODEL or OPENAI_MODEL must be configured")
    return client.resolve_model_name(default_model, source="config")


def run_single(snapshot, history, run_mode, requested_model, client) -> dict[str, Any]:
    result = select_action_with_guardrails(client, requested_model, snapshot, history)
    result["trace"] = serialize_step_trace(
        snapshot=snapshot,
        history=history,
        run_mode=run_mode,
        requested_model=requested_model,
        selected_model=requested_model,
        action=result["action"],
        planner=result["planner"],
        response=result["response"],
        benchmark=None,
        guardrail=result.get("guardrail"),
    )
    return result


def run_benchmark(snapshot, history, options, requested_model, client) -> dict[str, Any]:
    candidate_models = [requested_model]
    candidate_models.extend(
        dedupe_models(options.get("benchmarkModels", []), source="request", include_existing=candidate_models)
    )
    candidate_models.extend(
        dedupe_models(get_benchmark_models(), source="config", include_existing=candidate_models)
    )
    candidates = []
    candidate_results = {}
    selected = None

    for model in candidate_models:
        try:
            candidate = run_model_turn(client, model, snapshot, history)
            candidate_results[model] = candidate
            summary = {
                "model": model,
                "valid": True,
                "action": candidate["action"],
                "planner": candidate["planner"],
            }
            candidates.append(summary)
            if model == requested_model:
                selected = candidate
        except Exception as exc:  # noqa: BLE001
            candidates.append({"model": model, "valid": False, "error": str(exc)})

    if selected is None:
        for candidate in candidates:
            if candidate.get("valid"):
                selected = candidate_results[candidate["model"]]
                break

    if selected is None:
        raise AgentExecutionError("benchmark run did not produce a valid action")

    benchmark = {
        "mode": "benchmark",
        "primaryModel": requested_model,
        "chosenModel": selected["planner"]["model"],
        "candidates": candidates,
    }
    selected["benchmark"] = benchmark
    selected = apply_guardrail_retry(client, selected, snapshot, history)
    selected["benchmark"] = benchmark
    selected["trace"] = serialize_step_trace(
        snapshot=snapshot,
        history=history,
        run_mode="benchmark",
        requested_model=requested_model,
        selected_model=selected["planner"]["model"],
        action=selected["action"],
        planner=selected["planner"],
        response=selected["response"],
        benchmark=benchmark,
        guardrail=selected.get("guardrail"),
    )
    return selected


def run_model_turn(
    client,
    model: str,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    retry_note: str | None = None,
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a Lode Runner planning agent with a forward-thinking mindset. "
                "Use the helper tools when useful to achieve subgoals. "
                "Your final answer must be JSON only."
            ),
        },
        {"role": "user", "content": build_agent_prompt(snapshot, history, retry_note=retry_note)},
    ]
    tools = build_reasoning_tools(snapshot, history)

    try:
        response = client.create_completion(
            model,
            messages,
            tools=tools,
            max_turns=AGENT_TOOL_MAX_TURNS,
            temperature=AGENT_TEMPERATURE,
        )
    except ValueError as exc:
        raise AgentConfigError(str(exc)) from exc
    except LLMError as exc:
        message = str(exc)
        if "API key" in message or "Provider" in message:
            raise AgentConfigError(message) from exc
        raise AgentExecutionError(message) from exc
    except Exception as exc:  # noqa: BLE001
        raise AgentExecutionError(str(exc)) from exc

    action = parse_action_response(response)
    provider, _model_name = model.split(":", 1)
    planner = {
        "provider": provider,
        "model": model,
        "generatedAt": response.created if hasattr(response, "created") else None,
        "responseId": getattr(response, "id", None),
        "intermediateMessageCount": len(
            getattr(response.choices[0], "intermediate_messages", []) or []
        )
        if getattr(response, "choices", None)
        else 0,
        "reasoningContent": getattr(
            getattr(response.choices[0], "message", None), "reasoning_content", None
        )
        if getattr(response, "choices", None)
        else None,
    }
    return {"action": action, "planner": planner, "response": response}


def select_action_with_guardrails(client, model: str, snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    initial = run_model_turn(client, model, snapshot, history)
    return apply_guardrail_retry(client, initial, snapshot, history)


def apply_guardrail_retry(
    client,
    result: dict[str, Any],
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    model = result["planner"]["model"]
    first_evaluation = evaluate_action_guardrail(snapshot, history, result["action"])
    guardrail = {
        "stallDetected": first_evaluation["stallDetected"],
        "stallSummary": first_evaluation["stallSummary"],
        "progressOptions": first_evaluation["progressOptions"],
        "ladderAffordance": first_evaluation["ladderAffordance"],
        "movementAffordance": first_evaluation["movementAffordance"],
        "digAffordance": first_evaluation["digAffordance"],
        "routeAccessAffordance": first_evaluation["routeAccessAffordance"],
        "escapeAffordance": first_evaluation["escapeAffordance"],
        "risk": first_evaluation["risk"],
        "godMode": first_evaluation["godMode"],
        "progressOriented": first_evaluation["progressOriented"],
        "actionName": first_evaluation["actionName"],
        "routeAccessRecommendedAction": first_evaluation["routeAccessRecommendedAction"],
        "routeAccessActionMatched": first_evaluation["routeAccessActionMatched"],
        "reasonActionMismatch": first_evaluation["reasonActionMismatch"],
        "firstAction": result["action"],
        "firstActionVetoed": first_evaluation["vetoed"],
        "firstVetoReason": first_evaluation["reason"],
        "firstVetoSeverity": first_evaluation["severity"],
        "retryAttempted": False,
        "retryAccepted": False,
        "acceptedActionSource": "initial",
    }
    if not first_evaluation["vetoed"]:
        maybe_normalize_action_ticks(result["action"], first_evaluation)
        result["guardrail"] = guardrail
        return result

    repaired_action = get_guardrail_repair(first_evaluation, result["action"])
    if repaired_action:
        result["action"] = repaired_action
        guardrail["repairedAction"] = repaired_action
        guardrail["repairReason"] = guardrail_repair_reason(first_evaluation)
        guardrail["acceptedActionSource"] = "guardrail_repair"
        guardrail["retryAccepted"] = True
        result["guardrail"] = guardrail
        return result

    retry_result = run_model_turn(
        client,
        model,
        snapshot,
        history,
        retry_note=first_evaluation["retryNote"] or PROGRESS_RETRY_NOTE,
    )
    retry_evaluation = evaluate_action_guardrail(snapshot, history, retry_result["action"])
    guardrail["retryAttempted"] = True
    guardrail["retryAction"] = retry_result["action"]
    guardrail["retryAccepted"] = not retry_evaluation["vetoed"]
    guardrail["retryVetoReason"] = retry_evaluation["reason"]
    guardrail["retryVetoSeverity"] = retry_evaluation["severity"]
    guardrail["retryEvaluation"] = {
        "stallDetected": retry_evaluation["stallDetected"],
        "risk": retry_evaluation["risk"],
        "ladderAffordance": retry_evaluation["ladderAffordance"],
        "movementAffordance": retry_evaluation["movementAffordance"],
        "digAffordance": retry_evaluation["digAffordance"],
        "routeAccessAffordance": retry_evaluation["routeAccessAffordance"],
        "escapeAffordance": retry_evaluation["escapeAffordance"],
        "godMode": retry_evaluation["godMode"],
        "progressOriented": retry_evaluation["progressOriented"],
        "actionName": retry_evaluation["actionName"],
        "routeAccessRecommendedAction": retry_evaluation["routeAccessRecommendedAction"],
        "routeAccessActionMatched": retry_evaluation["routeAccessActionMatched"],
        "reasonActionMismatch": retry_evaluation["reasonActionMismatch"],
    }
    repaired_retry_action = get_guardrail_repair(retry_evaluation, retry_result["action"])
    if repaired_retry_action:
        retry_result["action"] = repaired_retry_action
        guardrail["repairedAction"] = repaired_retry_action
        guardrail["repairReason"] = guardrail_repair_reason(retry_evaluation)
        guardrail["acceptedActionSource"] = "guardrail_repair_after_retry"
        guardrail["retryAccepted"] = True
        retry_result["guardrail"] = guardrail
        return retry_result

    if retry_evaluation["vetoed"] and retry_evaluation["severity"] == "hard":
        retry_result["guardrail"] = guardrail
        raise AgentExecutionError(f"guardrail rejected retry: {retry_evaluation['reason']}")
    if retry_evaluation["vetoed"] and retry_evaluation["retryNote"] == ROUTE_ACCESS_RETRY_NOTE:
        retry_result["guardrail"] = guardrail
        raise AgentExecutionError(f"route-access guardrail rejected retry: {retry_evaluation['reason']}")

    guardrail["acceptedActionSource"] = "retry"
    maybe_normalize_action_ticks(retry_result["action"], retry_evaluation)
    retry_result["guardrail"] = guardrail
    return retry_result


def evaluate_action_guardrail(
    snapshot: dict[str, Any], history: list[dict[str, Any]], action: dict[str, Any]
) -> dict[str, Any]:
    stall = detect_progress_stall(snapshot, history, window=8)
    progress = assess_safe_progress_options(snapshot, history, limit=4)
    risk = assess_guard_risk(snapshot)
    ladder_affordance = get_ladder_affordance(snapshot)
    movement_affordance = get_movement_affordance(snapshot)
    dig_affordance = get_dig_affordance(snapshot)
    route_access_affordance = get_route_access_affordance(snapshot)
    escape_affordance = get_escape_affordance(snapshot)
    same_row_gold = [item for item in find_nearest_gold_candidates(snapshot, limit=3) if item["sameRow"]]
    row_ladders = [item for item in find_row_ladders(snapshot, limit=3) if item["visible"]]
    god_mode = bool(snapshot.get("godMode"))

    key_code = action.get("keyCode")
    action_name = ACTION_NAMES.get(key_code, f"keyCode:{key_code}")
    action_direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(key_code)
    route_access_recommended_action = route_access_affordance.get("recommendedAction")
    route_access_action_matched = route_access_action_matches(action, route_access_affordance)
    reason_action_mismatch = detect_reason_action_mismatch(action)
    feasibility_reason = action_feasibility_reason(action, movement_affordance, dig_affordance)
    progress_oriented = is_progress_oriented_action(
        action, progress, ladder_affordance, dig_affordance, same_row_gold, row_ladders
    )
    veto_reason = None
    severity = None
    retry_note = None

    if feasibility_reason:
        veto_reason = feasibility_reason
        severity = "hard"
        retry_note = FEASIBILITY_RETRY_NOTE
    elif reason_action_mismatch:
        veto_reason = reason_action_mismatch
        severity = "soft"
        retry_note = ROUTE_ACCESS_RETRY_NOTE
    elif route_access_action_mismatch(action, route_access_affordance):
        veto_reason = (
            "route-access dig side mismatch: use "
            f"{route_access_recommended_action} with keyCode {DIG_ACTION_KEYCODES.get(route_access_recommended_action)}"
        )
        severity = "soft"
        retry_note = ROUTE_ACCESS_RETRY_NOTE
    elif (
        stall.get("repeatedDigLoop")
        and route_access_affordance.get("available")
        and key_code in {DIG_LEFT_KEYCODE, DIG_RIGHT_KEYCODE}
    ):
        veto_reason = "route-access dig loop detected; stop digging and move into the opened access route"
        severity = "soft"
        retry_note = ROUTE_ACCESS_EXIT_RETRY_NOTE
    elif route_descent_available(action, route_access_affordance, movement_affordance):
        veto_reason = "aligned descent is available toward lower gold; choose down instead of digging"
        severity = "soft"
        retry_note = ROUTE_DESCENT_RETRY_NOTE
    elif ladder_descent_available(snapshot, action, movement_affordance):
        veto_reason = "aligned lower gold is below this ladder; choose down instead of up"
        severity = "soft"
        retry_note = LADDER_DESCENT_RETRY_NOTE
    elif (
        ladder_affordance["onLadder"]
        and risk["risk"] != "critical"
        and key_code not in {UP_KEYCODE, DOWN_KEYCODE}
    ):
        veto_reason = "runner is standing on an active ladder; choose a vertical climb action before leaving it"
        severity = "hard"
        retry_note = LADDER_RETRY_NOTE
    elif moves_toward_dangerous_guard(action, risk, god_mode=god_mode, progress_oriented=progress_oriented):
        veto_reason = "action moves toward high-or-critical same-row guard pressure"
        severity = "hard"
        retry_note = GOD_MODE_PROGRESS_RETRY_NOTE if god_mode else SAFETY_RETRY_NOTE
    elif (
        stall["stalled"]
        and ladder_affordance["onLadder"]
        and risk["risk"] != "critical"
        and key_code not in {UP_KEYCODE, DOWN_KEYCODE}
    ):
        veto_reason = "stall detected while standing on an active ladder; choose a vertical climb action"
        severity = "hard"
        retry_note = LADDER_RETRY_NOTE
    elif (
        god_mode
        and route_access_affordance.get("available")
        and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE, STOP_KEYCODE}
        and not snapshot.get("goldComplete")
    ):
        veto_reason = "god-mode route-access dig is available; horizontal spacing or stopping delays remaining-gold progress"
        severity = "soft"
        retry_note = ROUTE_ACCESS_RETRY_NOTE
    elif not stall["stalled"]:
        return {
            "stallDetected": False,
            "stallSummary": stall,
            "progressOptions": progress,
            "ladderAffordance": ladder_affordance,
            "movementAffordance": movement_affordance,
            "digAffordance": dig_affordance,
            "routeAccessAffordance": route_access_affordance,
            "escapeAffordance": escape_affordance,
            "risk": risk,
            "godMode": god_mode,
            "progressOriented": progress_oriented,
            "actionName": action_name,
            "routeAccessRecommendedAction": route_access_recommended_action,
            "routeAccessActionMatched": route_access_action_matched,
            "reasonActionMismatch": reason_action_mismatch,
            "vetoed": False,
            "reason": None,
            "severity": None,
            "retryNote": None,
        }
    elif key_code == STOP_KEYCODE and risk["risk"] not in {"critical", "high"}:
        veto_reason = "stall detected and stop would preserve the same non-progress state"
        severity = "soft"
        retry_note = PROGRESS_RETRY_NOTE
    elif (
        god_mode
        and stall.get("boundedHorizontalLoop")
        and action_direction is not None
        and stall.get("targetDirection") in {"left", "right"}
        and action_direction != stall.get("targetDirection")
    ):
        veto_reason = (
            "god-mode bounded horizontal loop detected; action moves away from the current "
            f"route target at x={stall.get('targetX')}"
        )
        severity = "soft"
        retry_note = GOD_MODE_PROGRESS_RETRY_NOTE
    elif action_direction is not None and not allow_short_escape(action, risk):
        if stall.get("edgePressure") and action_direction == stall.get("edgeDirection"):
            veto_reason = f"stall detected and action keeps pressing into the {stall['edgeDirection']} edge"
            severity = "soft"
            retry_note = PROGRESS_RETRY_NOTE
        elif stall.get("dominantDirection") and action_direction == stall["dominantDirection"]:
            if same_row_gold or row_ladders:
                veto_reason = (
                    "stall detected and action repeats the dominant retreat direction instead of taking "
                    "nearby gold or ladder progress"
                )
            else:
                veto_reason = "stall detected and action repeats the dominant retreat direction"
            severity = "soft"
            retry_note = PROGRESS_RETRY_NOTE

    return {
        "stallDetected": stall["stalled"],
        "stallSummary": stall,
        "progressOptions": progress,
        "ladderAffordance": ladder_affordance,
        "movementAffordance": movement_affordance,
        "digAffordance": dig_affordance,
        "routeAccessAffordance": route_access_affordance,
        "escapeAffordance": escape_affordance,
        "risk": risk,
        "godMode": god_mode,
        "progressOriented": progress_oriented,
        "actionName": action_name,
        "routeAccessRecommendedAction": route_access_recommended_action,
        "routeAccessActionMatched": route_access_action_matched,
        "reasonActionMismatch": reason_action_mismatch,
        "vetoed": veto_reason is not None,
        "reason": veto_reason,
        "severity": severity,
        "retryNote": retry_note,
    }


def route_access_action_mismatch(action: dict[str, Any], route_access: dict[str, Any]) -> bool:
    if not route_access.get("available"):
        return False
    recommended = route_access.get("recommendedAction")
    if recommended not in DIG_ACTION_KEYCODES:
        return False
    key_code = action.get("keyCode")
    if key_code not in {DIG_LEFT_KEYCODE, DIG_RIGHT_KEYCODE}:
        return False
    return key_code != DIG_ACTION_KEYCODES[recommended]


def route_access_action_matches(action: dict[str, Any], route_access: dict[str, Any]) -> bool | None:
    if not route_access.get("available"):
        return None
    recommended = route_access.get("recommendedAction")
    if recommended not in DIG_ACTION_KEYCODES:
        return None
    key_code = action.get("keyCode")
    if key_code not in {DIG_LEFT_KEYCODE, DIG_RIGHT_KEYCODE}:
        return False
    return key_code == DIG_ACTION_KEYCODES[recommended]


def detect_reason_action_mismatch(action: dict[str, Any]) -> str | None:
    reason = str(action.get("reason") or "").lower()
    key_code = action.get("keyCode")
    mentions_left = "dig_left" in reason or "dig left" in reason
    mentions_right = "dig_right" in reason or "dig right" in reason
    if mentions_left and key_code == DIG_RIGHT_KEYCODE and not mentions_right:
        return "action reason says dig_left but keyCode is dig_right"
    if mentions_right and key_code == DIG_LEFT_KEYCODE and not mentions_left:
        return "action reason says dig_right but keyCode is dig_left"
    return None


def route_descent_available(
    action: dict[str, Any],
    route_access: dict[str, Any],
    movement: dict[str, Any],
) -> bool:
    if action.get("keyCode") not in {DIG_LEFT_KEYCODE, DIG_RIGHT_KEYCODE}:
        return False
    if not route_access.get("available"):
        return False
    target = route_access.get("offRowGoldTarget")
    if not isinstance(target, dict):
        return False
    return (
        target.get("direction") == "same"
        and target.get("verticalDirection") == "below"
        and bool(movement.get("canMoveDown"))
    )


def ladder_descent_available(
    snapshot: dict[str, Any],
    action: dict[str, Any],
    movement: dict[str, Any],
) -> bool:
    if action.get("keyCode") != UP_KEYCODE:
        return False
    if not movement.get("canMoveDown"):
        return False
    runner = snapshot.get("runner") or {}
    runner_x = runner.get("x")
    runner_y = runner.get("y")
    if not isinstance(runner_x, int) or not isinstance(runner_y, int):
        return False
    gold = snapshot.get("gold") or {}
    visible_positions = gold.get("visiblePositions") or []
    return any(
        isinstance(item, dict)
        and item.get("x") == runner_x
        and isinstance(item.get("y"), int)
        and item["y"] > runner_y
        for item in visible_positions
    )


def get_guardrail_repair(evaluation: dict[str, Any], action: dict[str, Any]) -> dict[str, Any] | None:
    ladder_descent_repair = get_ladder_descent_repair(evaluation)
    if ladder_descent_repair:
        return ladder_descent_repair

    descent_repair = get_route_descent_repair(evaluation)
    if descent_repair:
        return descent_repair

    route_repair = get_route_access_exit_repair(evaluation)
    if route_repair:
        return route_repair

    if not evaluation.get("vetoed"):
        return None
    ladder = evaluation.get("ladderAffordance") or {}
    if not ladder.get("onLadder"):
        return None
    recommended = ladder.get("recommendedAction")
    if recommended not in {"up", "down"}:
        return None
    key_code = ACTION_KEYCODES[recommended]
    if action.get("keyCode") == key_code:
        return None
    return {
        "keyCode": key_code,
        "ticks": PROGRESS_APPROACH_MIN_TICKS,
        "reason": (
            "Guardrail repair: runner is already on an active ladder, so climb "
            f"{recommended} instead of leaving the ladder."
        ),
    }


def get_route_access_exit_repair(evaluation: dict[str, Any]) -> dict[str, Any] | None:
    if not evaluation.get("vetoed"):
        return None
    if evaluation.get("retryNote") != ROUTE_ACCESS_EXIT_RETRY_NOTE:
        return None

    route_access = evaluation.get("routeAccessAffordance") or {}
    target = route_access.get("offRowGoldTarget") if isinstance(route_access, dict) else None
    movement = evaluation.get("movementAffordance") or {}
    if not isinstance(target, dict):
        return None

    direction = target.get("direction")
    if direction == "right" and movement.get("canMoveRight"):
        return {
            "keyCode": RIGHT_KEYCODE,
            "ticks": PROGRESS_APPROACH_MIN_TICKS,
            "reason": "Guardrail repair: route-access dig loop detected, so move right into the opened access route.",
        }
    if direction == "left" and movement.get("canMoveLeft"):
        return {
            "keyCode": LEFT_KEYCODE,
            "ticks": PROGRESS_APPROACH_MIN_TICKS,
            "reason": "Guardrail repair: route-access dig loop detected, so move left into the opened access route.",
        }
    if movement.get("canMoveDown"):
        return {
            "keyCode": DOWN_KEYCODE,
            "ticks": PROGRESS_APPROACH_MIN_TICKS,
            "reason": "Guardrail repair: route-access dig loop detected, so descend through the opened access route.",
        }
    return None


def get_route_descent_repair(evaluation: dict[str, Any]) -> dict[str, Any] | None:
    if not evaluation.get("vetoed"):
        return None
    if evaluation.get("retryNote") != ROUTE_DESCENT_RETRY_NOTE:
        return None
    movement = evaluation.get("movementAffordance") or {}
    if not movement.get("canMoveDown"):
        return None
    return {
        "keyCode": DOWN_KEYCODE,
        "ticks": PROGRESS_APPROACH_MIN_TICKS,
        "reason": "Guardrail repair: lower gold is aligned below and down is valid, so descend instead of digging.",
    }


def get_ladder_descent_repair(evaluation: dict[str, Any]) -> dict[str, Any] | None:
    if not evaluation.get("vetoed"):
        return None
    if evaluation.get("retryNote") != LADDER_DESCENT_RETRY_NOTE:
        return None
    movement = evaluation.get("movementAffordance") or {}
    if not movement.get("canMoveDown"):
        return None
    return {
        "keyCode": DOWN_KEYCODE,
        "ticks": PROGRESS_APPROACH_MIN_TICKS,
        "reason": "Guardrail repair: lower gold is aligned below this ladder, so continue down instead of climbing up.",
    }


def guardrail_repair_reason(evaluation: dict[str, Any]) -> str:
    if evaluation.get("retryNote") == LADDER_DESCENT_RETRY_NOTE:
        return "aligned lower-gold ladder route requires descending instead of climbing up"
    if evaluation.get("retryNote") == ROUTE_DESCENT_RETRY_NOTE:
        return "aligned lower-gold route requires descending instead of digging"
    if evaluation.get("retryNote") == ROUTE_ACCESS_EXIT_RETRY_NOTE:
        return "route-access dig loop requires moving into the opened path"
    return "current-tile ladder affordance requires vertical movement"


def maybe_normalize_action_ticks(action: dict[str, Any], evaluation: dict[str, Any]) -> None:
    maybe_normalize_route_access_ticks(action, evaluation)
    maybe_normalize_progress_approach_ticks(action, evaluation)


def maybe_normalize_route_access_ticks(action: dict[str, Any], evaluation: dict[str, Any]) -> None:
    if evaluation.get("routeAccessActionMatched") is not True:
        return
    current_ticks = action.get("ticks")
    if not isinstance(current_ticks, int):
        return
    if current_ticks < ROUTE_ACCESS_MIN_TICKS:
        action["ticks"] = ROUTE_ACCESS_MIN_TICKS


def maybe_normalize_progress_approach_ticks(action: dict[str, Any], evaluation: dict[str, Any]) -> None:
    key_code = action.get("keyCode")
    action_direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(key_code)
    if action_direction is None:
        return
    if (evaluation.get("risk") or {}).get("risk") in {"high", "critical"}:
        return

    ladder = evaluation.get("ladderAffordance") or {}
    nearest = ladder.get("nearestRowLadder") if isinstance(ladder, dict) else None
    if isinstance(nearest, dict) and nearest.get("direction") == action_direction:
        distance = nearest.get("distance")
        if isinstance(distance, int) and distance > 2:
            action["ticks"] = max(int(action.get("ticks") or 1), PROGRESS_APPROACH_MIN_TICKS)
            return

    for option in (evaluation.get("progressOptions") or {}).get("options", []):
        detail = str(option.get("detail") or "").lower()
        if action_direction in detail and "on the runner row" in detail:
            action["ticks"] = max(int(action.get("ticks") or 1), PROGRESS_APPROACH_MIN_TICKS)
            return


def action_feasibility_reason(
    action: dict[str, Any],
    movement: dict[str, Any],
    dig: dict[str, Any],
) -> str | None:
    key_code = action.get("keyCode")
    if key_code == LEFT_KEYCODE and not movement.get("canMoveLeft"):
        return "left is not physically valid from the current tile"
    if key_code == RIGHT_KEYCODE and not movement.get("canMoveRight"):
        return "right is not physically valid from the current tile"
    if key_code == UP_KEYCODE and not movement.get("canMoveUp"):
        return "up is not physically valid because the runner is not on a climbable ladder tile"
    if key_code == DOWN_KEYCODE and not movement.get("canMoveDown"):
        return "down is not physically valid because no ladder descent is available"
    if key_code == DIG_LEFT_KEYCODE and not dig.get("canDigLeft"):
        return "dig_left is not physically valid because the side cell or lower brick target is invalid"
    if key_code == DIG_RIGHT_KEYCODE and not dig.get("canDigRight"):
        return "dig_right is not physically valid because the side cell or lower brick target is invalid"
    return None


def moves_toward_dangerous_guard(
    action: dict[str, Any],
    risk: dict[str, Any],
    *,
    god_mode: bool,
    progress_oriented: bool,
) -> bool:
    action_direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(action.get("keyCode"))
    if action_direction is None or risk.get("risk") not in {"high", "critical"}:
        return False
    if god_mode and progress_oriented:
        return False
    nearest_same_row = risk.get("nearestSameRowGuard") or {}
    return nearest_same_row.get("direction") == action_direction


def is_progress_oriented_action(
    action: dict[str, Any],
    progress: dict[str, Any],
    ladder_affordance: dict[str, Any],
    dig_affordance: dict[str, Any],
    same_row_gold: list[dict[str, Any]],
    row_ladders: list[dict[str, Any]],
) -> bool:
    key_code = action.get("keyCode")
    if key_code in {UP_KEYCODE, DOWN_KEYCODE}:
        return True
    if key_code == DIG_LEFT_KEYCODE:
        return bool(dig_affordance.get("left", {}).get("canDig"))
    if key_code == DIG_RIGHT_KEYCODE:
        return bool(dig_affordance.get("right", {}).get("canDig"))

    action_direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(key_code)
    if action_direction is None:
        return False
    if ladder_affordance.get("adjacentToLadder") and ladder_affordance.get("recommendedAction") == action_direction:
        return True
    for gold in same_row_gold:
        if gold.get("direction") == action_direction:
            return True
    for ladder in row_ladders:
        if ladder.get("direction") == action_direction:
            return True
    for option in progress.get("options", []):
        detail = str(option.get("detail", "")).lower()
        if action_direction in detail:
            return True
    return False


def allow_short_escape(action: dict[str, Any], risk: dict[str, Any]) -> bool:
    action_direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(action.get("keyCode"))
    if action_direction is None:
        return False
    nearest_same_row = risk.get("nearestSameRowGuard") or {}
    guard_direction = nearest_same_row.get("direction")
    if risk["risk"] == "critical":
        return guard_direction in {"left", "right"} and action_direction != guard_direction
    if risk["risk"] == "high" and action.get("ticks", 0) <= 4:
        return guard_direction in {"left", "right"} and action_direction != guard_direction
    return False


def parse_action_response(response: Any) -> dict[str, Any]:
    if not getattr(response, "choices", None):
        raise AgentExecutionError("model returned no choices")
    content = getattr(response.choices[0].message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise AgentExecutionError("model returned no text content")

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        lines = text.splitlines()
        if lines and lines[0].lower().startswith("json"):
            lines = lines[1:]
        text = "\n".join(lines).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentExecutionError(f"model returned non-JSON action: {exc}") from exc
    try:
        return normalize_agent_action(payload)
    except ValueError as exc:
        raise AgentExecutionError(str(exc)) from exc


def dedupe_models(models: list[str], *, source: str, include_existing: list[str] | None = None) -> list[str]:
    seen = set(include_existing or [])
    deduped = []
    client = get_aisuite_agent_client()
    for model in models:
        normalized = client.resolve_model_name(model, source=source)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
