from __future__ import annotations

import json
from typing import Any

from .config import LLM_GAME_RULES_PATH


def read_agent_rules() -> str:
    try:
        return LLM_GAME_RULES_PATH.read_text(encoding="utf-8")[:3000]
    except FileNotFoundError:
        return (
            "Classic level 1 focus: collect all gold, use ladders and route digs to change rows, "
            "and avoid non-progress loops. In god mode, guard contact is non-lethal."
        )


def build_agent_prompt(
    snapshot: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> str:
    return "\n\n".join(
        [
            "You are choosing one backend-generated candidate for the next short Lode Runner input burst.",
            "The backend has already checked legality and safety. Choose the candidate that best advances Classic level 1.",
            "Return JSON only: {\"candidateId\":\"candidate_id_here\"}.",
            "Agent rules:\n" + read_agent_rules(),
            format_state_summary(snapshot, analysis),
            format_candidates(candidates),
        ]
    )


def format_state_summary(snapshot: dict[str, Any], analysis: dict[str, Any]) -> str:
    runner = _dict(analysis.get("runner"))
    gold = _dict(analysis.get("gold"))
    risk = _dict(analysis.get("risk"))
    loop_report = _dict(analysis.get("loopReport"))
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
            f"- guardRisk={risk.get('risk')}",
            (
                f"- loop={{active:{bool(loop_report.get('active'))}, "
                f"type:{loop_report.get('type')}, "
                f"suppressed:{len(loop_report.get('suppressedCandidates', []))}}}"
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
                    f"- id={candidate.get('id')} kind={candidate.get('kind')} "
                    f"score={candidate.get('score')}{target_text}"
                ),
                f"  reason={action.get('reason')}",
            ]
        )
    return "\n".join(lines)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
