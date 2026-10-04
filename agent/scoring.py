from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Score adjustments only; admission and geometry thresholds remain in candidates.
LOW_RISK_GUARD_CLEARANCE_BONUS = 4
MEDIUM_CROSS_ROW_CLEARANCE_PENALTY = 12
SAME_BURST_OPPOSITE_LADDER_GOLD_BONUS = 4


# Existing values preserve the historical heuristic policy. New-family defaults
# are explicit engineering choices, not learned weights or optimality claims.
FIXED_SCORES = {
    "climb_ladder.vertical_cycle_toward_target": 122,
    "climb_ladder.toward_target": 108,
    "climb_ladder.loop_active": 112,
    "climb_ladder.gold_remaining": 95,
    "climb_ladder.gold_complete": 105,
    "climb_ladder.vertical_cycle_recovery": 112,
    "exit_ladder_route.finish_climb": 150,
    "exit_ladder_route.on_exit_ladder": 130,
    "exit_ladder_route.align_row": 125,
    "exit_ladder_route.move_up": 115,
    "evade_edge_ladder.base": 124,
    "evade_open_hole.base": 124,
    "escape_through_open_hole.base": 126,
    "retreat_from_guard.up": 120,
    "retreat_from_guard.down": 118,
    "defensive_dig.imminent_landing": 136,
    "defensive_dig.pinch": 134,
    "defensive_dig.edge": 132,
    "defensive_dig.decisive": 138,
    "defensive_dig.default": 112,
    "retreat_from_guard.side": 108,
    "retreat_from_guard.same_column": 110,
    "collect_current_tile_gold.base": 122,
    "collect_same_row_gold.god_mode": 106,
    "collect_same_row_gold.normal": 100,
    "align_ladder.loop_target": 118,
    "align_ladder.fine_alignment": 104,
    "align_ladder.god_mode_base": 94,
    "align_ladder.normal_base": 90,
    "route_access_dig.base": 88,
    "route_access_follow.base": 104,
    "wait_for_guard_clearance.base": 120,
    "wait_for_dig_completion.base": 142,
    "wait_for_trap_resolution.base": 140,
    "wait_for_floor_refill.base": 120,
    "descend_route.ladder_entry": 108,
    "descend_route.already_falling": 116,
    "descend_route.rope": 114,
    "descend_route.same_column": 110,
    "descend_route.other_column": 86,
    "god_mode_progress.loop_active": 72,
    "god_mode_progress.default": 82,
    "low_risk_horizontal_progress.base": 70,
    "wait_and_recheck.base": 1,
    "wait_for_gold_carrier.base": 1,  # Approved selectable alternative, not a preferred action.
    "emergency_hold.base": 0,
}


@dataclass(frozen=True)
class ScoreSpec:
    policy: str
    total: int
    components: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if sum(value for _, value in self.components) != self.total:
            raise ValueError("score components must sum to the total")

    def with_guard_adjustments(
        self, *, bonus: int, penalty: int,
        penalty_component: str = "medium_cross_row_clearance_penalty",
    ) -> ScoreSpec:
        components = self.components
        if bonus:
            components += (("guard_clearance_bonus", bonus),)
        if penalty:
            components += ((penalty_component, -penalty),)
        return ScoreSpec(self.policy, self.total + bonus - penalty, components)

    def with_component(self, name: str, value: int) -> ScoreSpec:
        return ScoreSpec(self.policy, self.total + value, self.components + ((name, value),))

    def breakdown(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "total": self.total,
            "components": [
                {"name": name, "value": value} for name, value in self.components
            ],
        }


def fixed_score(policy: str) -> ScoreSpec:
    value = FIXED_SCORES[policy]
    return ScoreSpec(policy=policy, total=value, components=(("base", value),))


def caller_score(value: int, *, kind: str) -> ScoreSpec:
    """Preserve direct CandidateBuilder callers with an honest fixed breakdown."""
    return ScoreSpec(
        policy=f"{kind}.caller_supplied",
        total=int(value),
        components=(("base", int(value)),),
    )


def ladder_alignment_score(
    distance: int, *, god_mode: bool, fine_align: bool, loop_target: bool
) -> ScoreSpec:
    if loop_target:
        return fixed_score("align_ladder.loop_target")
    if fine_align:
        return fixed_score("align_ladder.fine_alignment")
    base_policy = (
        "align_ladder.god_mode_base" if god_mode else "align_ladder.normal_base"
    )
    base = FIXED_SCORES[base_policy]
    distance_bonus = max(0, 12 - min(max(distance, 0), 12))
    return ScoreSpec(
        policy="align_ladder.distance",
        total=base + distance_bonus,
        components=((base_policy, base), ("distance_bonus", distance_bonus)),
    )
