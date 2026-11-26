# Backlog

Issues to file on GitHub (each section is one issue, ready to paste).

## Recommender: better candidates, and check the ranker on real listening

*Labels: recommender. Follows the ranker rework of 2026-11-26 (Bayesian pairwise ranking, Thompson sampling, the
source as a feature; `docs/recommender.md`).*

Where it stands on the synthetic listener (`python -m recsys.synth`, 900 songs, 16 seeds × 60 sessions): learning
now helps, +2.1 ± 1.0 points of autoplay picks finished (the first version's online logistic regression lost
2.4 ± 1.0), and as Kassetto runs it is +2.5 ± 1.4 over the first version. Two things learned on the way:

- **The ceiling is in the candidates, not the weights.** Ranking the same candidates by the listener's true hidden
  taste (an oracle) finishes only ~4–5 points more than the hand-tuned weights, whatever the radio noise or the
  listener's decisiveness. With the old 240-song catalogue the listener tired of every good song and nothing could
  help (that is why the first numbers looked like noise: they were). Next gains come from what gets *into* the
  pool: more and better sources, deeper radios, a retrieval step on the sound embeddings (two-tower style: your
  taste vector vs every fingerprinted song), co-listening from ListenBrainz.
- **Sources taking turns had value of its own.** With learning off, the old per-slot source draw finished 2.0 ±
  1.3 points more than best-score-first; a hybrid (draw among sources with a song near the best) had the best
  control (53.8 %) but then learning hurt it (−2.3 ± 1.2: the draw overrides what the model learned). Worth
  another look: diversity as an explicit objective (MMR / DPP on the sound vectors) instead of source turns.

To do:
- run `python -m recsys.evaluate` on a real install for a few weeks: "AUC as served" before vs after the rework,
  the fitted weights and their uncertainty;
- `KASSETTO_EXPLORE` (Thompson draw scale, default 0.3): full-scale draws (1.0) cost ~3 points on the synthetic
  listener; check on real data;
- a CI check on `recsys.synth` (a short run that fails if learning stops helping), once it is fast enough.
