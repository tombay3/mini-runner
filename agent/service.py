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
        "escapeAffordance": first_evaluation["escapeAffordance"],
        "risk": first_evaluation["risk"],
        "firstAction": result["action"],
        "firstActionVetoed": first_evaluation["vetoed"],
        "firstVetoReason": first_evaluation["reason"],
        "firstVetoSeverity": first_evaluation["severity"],
        "retryAttempted": False,
        "retryAccepted": False,
        "acceptedActionSource": "initial",
    }
    if not first_evaluation["vetoed"]:
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
        "escapeAffordance": retry_evaluation["escapeAffordance"],
    }
    if retry_evaluation["vetoed"] and retry_evaluation["severity"] == "hard":
        retry_result["guardrail"] = guardrail
        raise AgentExecutionError(f"guardrail rejected retry: {retry_evaluation['reason']}")

    guardrail["acceptedActionSource"] = "retry"
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
    escape_affordance = get_escape_affordance(snapshot)
    same_row_gold = [item for item in find_nearest_gold_candidates(snapshot, limit=3) if item["sameRow"]]
    row_ladders = [item for item in find_row_ladders(snapshot, limit=3) if item["visible"]]

    key_code = action.get("keyCode")
    action_direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(key_code)
    feasibility_reason = action_feasibility_reason(action, movement_affordance, dig_affordance)
    veto_reason = None
    severity = None
    retry_note = None

    if feasibility_reason:
        veto_reason = feasibility_reason
        severity = "hard"
        retry_note = FEASIBILITY_RETRY_NOTE
    elif moves_toward_dangerous_guard(action, risk):
        veto_reason = "action moves toward high-or-critical same-row guard pressure"
        severity = "hard"
        retry_note = SAFETY_RETRY_NOTE
    elif (
        stall["stalled"]
        and ladder_affordance["onLadder"]
        and risk["risk"] != "critical"
        and key_code not in {UP_KEYCODE, DOWN_KEYCODE}
    ):
        veto_reason = "stall detected while standing on an active ladder; choose a vertical climb action"
        severity = "hard"
        retry_note = LADDER_RETRY_NOTE
    elif not stall["stalled"]:
        return {
            "stallDetected": False,
            "stallSummary": stall,
            "progressOptions": progress,
            "ladderAffordance": ladder_affordance,
            "movementAffordance": movement_affordance,
            "digAffordance": dig_affordance,
            "escapeAffordance": escape_affordance,
            "risk": risk,
            "vetoed": False,
            "reason": None,
            "severity": None,
            "retryNote": None,
        }
    elif key_code == STOP_KEYCODE and risk["risk"] not in {"critical", "high"}:
        veto_reason = "stall detected and stop would preserve the same non-progress state"
        severity = "soft"
        retry_note = PROGRESS_RETRY_NOTE
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
        "escapeAffordance": escape_affordance,
        "risk": risk,
        "vetoed": veto_reason is not None,
        "reason": veto_reason,
        "severity": severity,
        "retryNote": retry_note,
    }


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
        return "dig_left is not physically valid because ok2Dig-left conditions are not met"
    if key_code == DIG_RIGHT_KEYCODE and not dig.get("canDigRight"):
        return "dig_right is not physically valid because ok2Dig-right conditions are not met"
    return None


def moves_toward_dangerous_guard(action: dict[str, Any], risk: dict[str, Any]) -> bool:
    action_direction = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}.get(action.get("keyCode"))
    if action_direction is None or risk.get("risk") not in {"high", "critical"}:
        return False
    nearest_same_row = risk.get("nearestSameRowGuard") or {}
    return nearest_same_row.get("direction") == action_direction


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
