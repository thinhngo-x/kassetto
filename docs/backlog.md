# Backlog

Issues to file on GitHub once the repo exists (each section is one issue, ready to paste).

## Recommender: learned ranker doesn't beat its prior yet; low-scored picks win through the source bandit

*Labels: recommender, quality. Found 2026-11-25 with the synthetic listener (`python -m recsys.synth`).*

### 1. Learning isn't paying off

On the synthetic listener (6 seeds × 60 sessions, last third of the sessions):

| | learned ranker | learning off (prior weights) |
|---|---|---|
| autoplay picks finished | 33.5 % | 33.0 % |
| AUC on labelled picks | 0.721 (learned weights) | 0.710 (start weights) |

The learned weights barely improve on the hand-tuned start, so learning isn't doing much yet. Things to look at:
- learning rate / L2 pull (`LR, L2` in `recsys/learn.py`): with ~10 picks per session the weights may hardly move;
- label grading (`LABEL`, the graded complete/partial/skip): is the signal too compressed?
- which features carry signal: run `recsys.evaluate` per-feature AUC on the synthetic DB;
- what boredom does to the score (it reshapes the learned score after the fact, so the learned weights aren't
  what decides);
- the listener model itself (`recsys/synth.py`): is it too noisy for any ranker to win? Add an oracle ranker
  (true utility) as an upper bound, to know how much room there is.

**Done when** the learned ranker beats the prior clearly (several points of "finished") on the synthetic listener
across seeds, and a CI check guards it from regressing.

### 2. A source can win with poor songs

`rank()` picks a source (arm) by Thompson sampling, then serves that arm's best-scored candidate, however low that
score is. In a test batch, a draw for "recommended for you" (cf) served five songs in a row from a genre the
listener always skips.

Options: a score floor (relative to the batch's best), arms only competing with candidates above it, or limiting
how often one arm can serve below-median picks. Measure with `recsys.synth` before and after.
