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
    show_candidate_scores: bool = True,
) -> str:
    sections = [
        "You are choosing one backend-generated candidate for the next short Lode Runner input burst.",
        "The backend has already checked candidate legality. Do not invent keyCodes or actions.",
        "Choose the candidate that best advances Classic level 1: collect remaining gold, change rows through ladders/routes, then exit after goldComplete.",
        "Return JSON only with this exact shape: {\"candidateId\":\"candidate_id_here\",\"reason\":\"brief explanation\"}.",
        "Agent rules:\n" + read_agent_rules(),
        format_state_summary(snapshot, analysis),
        format_candidates(candidates, show_scores=show_candidate_scores),
    ]
    stall_report = format_stall_report(analysis)
    if stall_report:
        sections.insert(-1, stall_report)
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
    stall_report = _dict(analysis.get("stallReport") or analysis.get("progressMonitor"))
    primary_target = _dict(analysis.get("primaryProgressTarget"))
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
            f"- primaryProgressTarget={json.dumps(primary_target, sort_keys=True)}",
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
                f"recommended:{route_access.get('recommendedAction')}, "
                f"followAvailable:{route_access.get('followAvailable')}, "
                f"followAction:{route_access.get('followAction')}, "
                f"reason:{route_access.get('reason')}}}"
            ),
            (
                f"- stall={{severity:{stall_report.get('severity')}, "
                f"type:{stall_report.get('type')}, "
                f"blocked:{json.dumps(stall_report.get('blockedCandidateIds', []), sort_keys=True)}, "
                f"preferred:{json.dumps(stall_report.get('preferredCandidateKinds', []), sort_keys=True)}}}"
            ),
        ]
    )


def format_stall_report(analysis: dict[str, Any]) -> str:
    stall_report = _dict(analysis.get("stallReport") or analysis.get("progressMonitor"))
    if stall_report.get("severity") in {None, "none"}:
        return ""
    return "\n".join(
        [
            "Stall report:",
            (
                f"- severity={stall_report.get('severity')} type={stall_report.get('type')} "
                f"reason={stall_report.get('reason')}"
            ),
            f"- recentPositions={json.dumps(stall_report.get('recentPositions', []), sort_keys=True)}",
            f"- recentCandidateIds={json.dumps(stall_report.get('recentCandidateIds', []), sort_keys=True)}",
            (
                f"- blockedCandidateIds={json.dumps(stall_report.get('blockedCandidateIds', []), sort_keys=True)} "
                f"blockedKinds={json.dumps(stall_report.get('blockedCandidateKinds', []), sort_keys=True)}"
            ),
            (
                f"- preferredRecoveryKinds="
                f"{json.dumps(stall_report.get('preferredCandidateKinds', []), sort_keys=True)}"
            ),
            (
                f"- blockedLadderDirections="
                f"{json.dumps(stall_report.get('blockedLadderDirections', []), sort_keys=True)} "
                f"preferredVerticalDirection={stall_report.get('preferredVerticalDirection')} "
                f"ladderExitDirection={stall_report.get('ladderExitDirection')}"
            ),
            f"- recoveryHint={stall_report.get('recoveryHint')}",
            "If severity=stalled, do not choose blocked candidates; prefer a recovery candidate.",
        ]
    )


def format_candidates(candidates: list[dict[str, Any]], *, show_scores: bool = True) -> str:
    lines = ["Candidate choices:"]
    for candidate in candidates:
        action = _dict(candidate.get("firstAction"))
        target = candidate.get("target")
        target_text = f" target={json.dumps(target, sort_keys=True)}" if target else ""
        score_text = f" score={candidate.get('score')}" if show_scores else ""
        stall_text = ""
        if candidate.get("stallBlocked"):
            stall_text = f" stallBlocked={candidate.get('stallBlockReason')}"
        elif candidate.get("stallRecovery"):
            stall_text = " stallRecovery=true"
        lines.extend(
            [
                (
                    f"- id={candidate.get('id')} kind={candidate.get('kind')}{score_text} "
                    f"risk={candidate.get('risk')} keyCode={action.get('keyCode')} ticks={action.get('ticks')}"
                    f"{target_text}{stall_text}"
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
