# Guard safety experiment

## Introduction

This project sought a guard-aware candidate policy that keeps the runner moving toward
gold while preserving enough distance and a usable escape. Distance alone is
insufficient: guard motion, terrain, other guards, and action duration can turn
an apparently safe move into a trap.

The investigation used the 150-level Classic extraction to find where useful
clearance or escape options disappeared before pressure became critical. It
retained focused corrections, but did not establish a general safety policy or
reliable completion. Classic 1:1 remains the only supported agent context.

## What the audit showed

The audit screened 16,296 sampled decisions from 11,853 input events. It looked
for progress toward a guard despite a safer route, retreat toward another guard,
actions long enough for interception, lost row-changing options, and repeated
safe movement without progress.

Recorded states identified decision windows; engine replay checked whether
apparent problems were real. Terrain, guard motion, action duration, candidate
availability, rejection, scoring, and subsequent states had to be considered
together. Historical demonstrations identified cases to investigate, not proof
that a different action would improve autonomous play.

## Retained improvements

- Candidate generation better matches legal engine actions and preserves useful
  defensive and row-changing options in narrowly defined conditions.
- Ranking and selection can favor guard clearance without discarding progress.
- Action timing allows earlier reassessment of a demonstrated interception risk.
- Loop recovery better preserves escape, defensive, and exit progress.

These changes retain the candidate-selection architecture and existing close-
contact and high-pressure protections. A correction being used in a live run
does not by itself establish better survival.

## Conclusions and limits

Guard distance alone is not a safety measure. Retreat can approach another guard;
waiting can allow guards to converge; a long action can lose an escape that was
available at its start. Safety therefore requires useful progress and escape
options, not simply greater separation or more rejected actions.

Secondary threats, repeated waits, and compound movement loops remain important
limits. The evidence does not justify blanket distance rules, generic wait
limits, or broad score tuning. Long-range escape planning and other policy
expansion remain deferred until supported by stronger evidence.

Keep justified trap waits and emergency holds. A move may safely reduce distance
if it preserves progress and an escape; relaxing existing protections requires
separate evidence.
