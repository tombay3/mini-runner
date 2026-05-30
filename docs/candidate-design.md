# Candidate Design Notes

## Summary
The V2 agent constrains the model to backend-generated candidate actions. This deliberately trades an open raw-key action space for a smaller, safer set of legal and purposeful choices.

Candidate generation answers: "What legal useful moves exist right now?" Candidate scoring answers: "Which moves look promising by simple rules?" The LLM answers: "Given these choices and the current context, which candidate should we commit to?"

## Scoring
The heuristic scoring acts as the tactical engine, while the LLM acts as the strategic engine.

Scores are useful because they:

- order candidates before the list is truncated for the prompt;
- encode local progress bias and stall recovery knowledge;
- provide deterministic fallback when the model returns invalid JSON or chooses a blocked candidate;
- make traces easier to debug when the model chooses against backend ranking.

Score visibility in the prompt is configurable through `public/agent-config.json` `prompt.showCandidateScores`. Scores always remain available in trace/debug output. Showing score is a pragmatic debugging/default choice: without a numeric priority signal, some models overfit candidate wording and ignore the backend's tactical ranking.

Known heuristic limits:

- Heuristics are greedy and can contribute to oscillation loops.
- Heuristics struggle when risk and reward are both high.
- Heuristics generally penalize doing nothing (`wait_or_stop`).

Scores should not be treated as proof of correctness. If a high-score candidate creates a loop, fix candidate coverage, scoring, or stall handling rather than assuming the model can infer the correction from text alone.

## Necessary And Sufficient Candidates
The candidate set is not provably complete by inspection. It is an empirical interface that should be validated against Classic level 1 failures.

A candidate kind is necessary when a successful route sometimes requires that class of first action and no existing kind expresses it cleanly. For example, `route_access_dig` is necessary because digging can open descent/access routes to lower gold, not only trap guards.

A candidate set is sufficient when every important state has at least one legal candidate that makes real progress or avoids immediate failure. It does not need every possible raw move.

Practical sufficiency checks:

- Inspect failed traces and ask whether the correct first action was available as a candidate.
- Compare against successful human or demo play and confirm each required first action maps to an existing kind.
- Watch for states where only `wait_or_stop` is emitted.
- Watch for repeated fallback, repeated blocked choices, or no progress candidate in traces.
- Compare highest-score behavior against LLM-selected behavior to separate candidate coverage problems from selection problems.

## Failure Classification
Every recurring failure should be classified before adding more prompt text or guardrails:

- `Coverage gap`: the correct action is absent from the candidate list.
- `Selection gap`: the correct candidate exists but the model or ranking chooses another candidate.
- `Execution gap`: the candidate maps to a legal action, but ticks/timing/legacy physics make it ineffective.
- `State gap`: snapshot or analysis omits a fact needed to generate or rank the right candidate.
- `Stall gap`: repeated non-progress is not detected or the recovery candidate is not boosted/selected.

This classification keeps the candidate approach constrained without making it blind.

## Selection Validation
After the LLM returns a `candidateId`, `agent/service.py` validates the choice before sending an action to the browser. This validation is planner-level bookkeeping, not legacy physics execution.

Validation records:

- the candidate id requested by the model;
- the candidate id actually selected by the backend;
- whether the requested id was known;
- whether fallback was used and why;
- whether the translated first action is still physically valid;
- whether the stall supervisor blocked the candidate;
- the model's reason text.

`requestedCandidateId` and `selectedCandidateId` can differ when the model returns invalid JSON, chooses an unknown candidate, chooses a physically invalid action, or repeats a stall-blocked candidate. This makes traces explain whether a bad run came from candidate coverage, model selection, fallback behavior, or stall supervision.

## Design Bias
Prefer adding or refining candidates when the correct first action is missing. Prefer scoring/stall changes when the correct candidate exists but is not selected. Prefer action translation changes when the candidate is right but the legacy runtime does not execute it effectively.

Avoid returning to raw key planning as the default path. The current model role is candidate selection, not physics, pathfinding, or executor control.
