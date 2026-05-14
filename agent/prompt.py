from __future__ import annotations

import json
from typing import Any

from .config import AGENT_RULES_PATH


def read_agent_rules() -> str:
    try:
        return AGENT_RULES_PATH.read_text(encoding="utf-8")[:3000]
    except FileNotFoundError:
        return (
            "Classic level 1 focus: collect all gold, use ladders and route digs to change rows, "
            "and avoid non-progress loops. In god mode, guard contact is non-lethal."
        )


def build_agent_prompt(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
    retry_note: str | None = None,
) -> str:
    sections = [
        "You are choosing one backend-generated candidate for the next short Lode Runner input burst.",
        "The backend has already checked candidate legality. Do not invent keyCodes or actions.",
        "Choose the candidate that best advances Classic level 1: collect remaining gold, change rows through ladders/routes, then exit after goldComplete.",
        "Return JSON only with this exact shape: {\"candidateId\":\"candidate_id_here\",\"reason\":\"brief explanation\"}.",
        "Agent rules:\n" + read_agent_rules(),
        format_state_summary(snapshot, analysis),
        format_candidates(candidates),
    ]
    behavior = format_recent_behavior(history)
    if behavior:
        sections.append(behavior)
    if retry_note:
        sections.append("Retry instruction:\n" + retry_note)
    return "\n\n".join(sections)


def format_state_summary(snapshot: dict[str, Any], analysis: dict[str, Any]) -> str:
    runner = _dict(analysis.get("runner"))
    gold = _dict(analysis.get("gold"))
    risk = _dict(analysis.get("risk"))
    ladder = _dict(analysis.get("ladder"))
    route_access = _dict(analysis.get("routeAccess"))
    movement = _dict(analysis.get("movement"))
    return "\n".join(
        [
            "Current state:",
            (
                f"- playData={snapshot.get('playData')} level={snapshot.get('level')} "
                f"gameState={snapshot.get('gameStateName')} godMode={bool(snapshot.get('godMode'))}"
            ),
            (
                f"- runner=({runner.get('x')},{runner.get('y')}) action={runner.get('action')} "
                f"offset=({runner.get('xOffset')},{runner.get('yOffset')})"
            ),
            (
                f"- goldComplete={bool(gold.get('complete', snapshot.get('goldComplete')))} "
                f"remainingGold={gold.get('remainingCount', snapshot.get('goldCount'))} "
                f"visibleGold={json.dumps(gold.get('visiblePositions', []), sort_keys=True)}"
            ),
            (
                f"- guardRisk={risk.get('risk')} nearestSameRowGuard="
                f"{json.dumps(risk.get('nearestSameRowGuard'), sort_keys=True)}"
            ),
            (
                f"- movement={{left:{movement.get('canMoveLeft')}, right:{movement.get('canMoveRight')}, "
                f"up:{movement.get('canMoveUp')}, down:{movement.get('canMoveDown')}}}"
            ),
            f"- ladder={ladder.get('detail')}",
            (
                f"- routeAccess={{available:{route_access.get('available')}, "
                f"recommended:{route_access.get('recommendedAction')}, reason:{route_access.get('reason')}}}"
            ),
        ]
    )


def format_candidates(candidates: list[dict[str, Any]]) -> str:
    lines = ["Candidate choices:"]
    for candidate in candidates:
        action = _dict(candidate.get("firstAction"))
        target = candidate.get("target")
        target_text = f" target={json.dumps(target, sort_keys=True)}" if target else ""
        lines.extend(
            [
                (
                    f"- id={candidate.get('id')} kind={candidate.get('kind')} score={candidate.get('score')} "
                    f"risk={candidate.get('risk')} keyCode={action.get('keyCode')} ticks={action.get('ticks')}"
                    f"{target_text}"
                ),
                f"  goal={candidate.get('goal')}",
                f"  reason={candidate.get('reason')}",
            ]
        )
    return "\n".join(lines)


def format_recent_behavior(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    lines = ["Recent behavior:"]
    for item in history[-4:]:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- keyCode={item.get('keyCode')} state={item.get('state')} "
            f"before={json.dumps(item.get('before'), sort_keys=True)} "
            f"after={json.dumps(item.get('after'), sort_keys=True)}"
        )
    return "\n".join(lines)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
