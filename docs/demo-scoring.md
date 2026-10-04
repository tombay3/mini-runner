# Demo scoring roadmap

## Introduction

This experiment began by extracting all 150 Classic demonstrations and asking
whether their actions could improve the agent's heuristic candidate scores or
support a small learned ranker. The audit first measured whether each demonstrated
action existed in the current candidate pool, matched its duration, and survived
filtering.

Initial coverage was too weak for direct training: most samples were missing a
matching candidate or used a different duration. A training-only audit therefore
separated exact matches from conservative action prefixes and preserved the
original labels. It recovered 920 evidence rows, but these rows did not establish
that the demonstrated action was uniquely best.

The focus then narrowed from ranker training to the existing heuristic policy.
Scoring constants were centralized with truthful score breakdowns, and a temporary
top-score evaluator measured how the current ranking compared with the retained
evidence. Classic 1 had only 34 sampled decisions, so its disagreements were too
small to guide reliable score changes; results from other levels did not establish
improvement for the supported Classic 1 context.

The experiment is now closed. The scoring inventory is retained, while the
temporary top-score evaluator was removed. The extracted data and reports remain
available for focused future work, but learned ranking, broad candidate-gap work,
and LLM comparisons require separate evidence and approval. The results do not
establish general completion or safety.

## Why this work is needed

The numeric scores are fixed constants written by Codex. The user did not choose
them, and they were neither learned from data nor mathematically optimized.

Scores determine candidate order, the seven-item shortlist, model context and
fallback selection. The model can choose a lower-ranked candidate. Diagnose
candidate availability, scoring, model selection, validation, execution timing
and loop filtering separately when reviewing an LLM gameplay result.

The Classic demo extraction completed successfully:

| Measurement | Result |
| --- | ---: |
| Levels completed / quarantined | 150 / 0 |
| Retries / validation errors | 0 / 0 |
| Train / validation / test | 90 / 30 / 30 |
| Sampled decisions | 16,296 |
| Exact exposed key-duration matches | 788 |
| Same-key duration mismatches | 7,132 |
| Missing candidates | 8,317 |
| Matching suppressed/rejected proposals | 59 |
| Elapsed time | 6,045.839 seconds (~1h 40m 46s) |

The original 788 exact matches were 4.8% of all samples and included held-out
levels. Reanalysis against the rebuilt branch found 920 unique training evidence
rows: 464 exact matches and 456 conservative action prefixes, with no overlap.
They remain evidence, not adopted ranker labels.

The offline top-score baseline agreed with 314/464 exact rows and 386/456 prefix
rows. Its 220 disagreements are not proven gameplay errors. Classic 1 supplied
only 34 sampled decisions from one demo, including 10 supported rows and two
disagreements. This is too small to establish autonomous completion or safety.

## Conclusions

The scores are hand-written constants, not learned or optimized weights. They
affect candidate order, the seven-item shortlist, model context, and fallback
selection, but the model may choose a lower-ranked candidate.

Candidate availability is the main coverage limit. More than half the original
samples had no eligible candidate with the demonstrated key; scoring cannot rank
an unavailable action. Duration mismatches may contain useful prefixes, but are
not automatically labels. Digging, falling, ladders, and target changes require
specific evidence.

A successful demo shows one workable route. It does not prove that route is
uniquely best or that alternatives are bad. Offline agreement on recorded states
also cannot establish behavior in new autonomous states. Candidate availability,
scoring, model selection, validation, execution timing, and loop filtering must
be diagnosed separately.

The scoring inventory preserved totals, ordering, shortlist membership,
deduplication, filtering, and fallback behavior. Fixed base values are named
without inventing risk or progress components that the code does not calculate.
