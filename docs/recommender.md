# The recommender

The code is in `app/recsys/`; `recsys/__init__.py` has the overview. In short:

## Signals

- **Listens**, weighted by how much you heard: finished (≥ 80 %) +1; left in the first 10 seconds −1.2; left before
  30 % somewhat negative; most of it mildly positive. Only real choices count: pressing *next* early is a skip
  (undone if you go back within 20 s); errors, songs that never started, and switching to something else are not.
- **Likes** (❤️) are the strongest signal; *Hide from recommendations* removes that one song. There is no dislike.
- **Implicit signals:** replays, adding to / removing from the queue, picking a song from *Up next*, jumping past
  one, leaving autoplay for something you chose, searching, opening lyrics, rewinding, turning it up.
- Optional: **ListenBrainz** listens from your other players, and old **Spotify** history (a small, capped boost
  for artists you already play).

## Taste

- **Long-term:** artist affinity and per-song scores, decayed with a 45-day half-life; listens from the same part
  of the day count 50 % more. In circles, people's data counts at the circle's blend.
- **This session** (plays less than 30 minutes apart): the sound of what you kept vs rejected, and your mood about
  each artist right now.
- **Sound** (with the embed service): CLAP fingerprints of your favourites, clustered into taste groups.
- **Boredom:** passing over and leaving autoplay raises it, finishing autoplay picks lowers it (3-hour half-life).
  While high, picks lean away from the familiar.

## Picking songs (`ranking.rank`)

1. **Candidates** from several sources: the seed song's radio, radios of your favourites, ListenBrainz
   collaborative filtering, sound neighbours of your taste clusters.
2. **Features** per candidate: similarity to the seed, artist affinity, sound vs your taste, sound vs this session,
   artist mood this session, new artist, recent repeats, past skips, liked, your own history with the song, and
   which source it came from.
3. **Score** = features × weights *drawn* from your learned model (Thompson sampling: where the model is unsure,
   the draw varies, so uncertain options get tried now and then), reshaped by boredom.
4. **Selection:** best score first, with rules: never the same artist twice in a row, at most 3 per artist, a cap
   on familiar songs. A source only gets a slot with a song that scores well (sources used to take turns, which let
   one win with a poor song).
5. **Flow:** the picks are reordered so each song is the one closest in sound to the previous (within a few places).
6. **Because:** each pick gets a specific reason.

## Learning

Every pick is logged with its features (table `impressions`). When its outcome arrives (finished, half-heard,
skipped, liked, picked from *Up next*, jumped past, left behind), the pick gets a label from 0 to 1 and the
person's model is refitted (`recsys/learn.py`):

- **Pairwise:** each outcome is compared with the ones just before it; when you kept one pick and not another, the
  model learns that the kept one should have scored higher (as in RankNet / BPR). It learns the *order*, which is
  all ranking needs.
- **Bayesian:** the prior is the hand-tuned weights (times a scale fitted to the data), the fit is the most likely
  weights given your outcomes (Newton's method), with an uncertainty per weight (Laplace approximation, as in
  Chapelle & Li, "An Empirical Evaluation of Thompson Sampling"). With little data the ranker behaves as it
  started; recent outcomes count more than old ones (~300-outcome memory).
- Your last 2,000 labelled picks are refitted after every outcome; it takes milliseconds.

Why not online logistic regression (the first version): it predicted the *probability* of finishing, and the
hand-tuned weights were never calibrated probabilities, so its steps went into shrinking every weight rather than
reordering them. On the synthetic listener it made picks worse (below).

## Measuring it

- `python -m recsys.evaluate [user]`: on your labelled picks, the AUC (how often a song you kept scored above one
  you didn't) of each pick's score *as it was served*, before its outcome was learned (the honest number); the
  starting vs current weights re-scoring the same picks (in-sample, flatters the current ones); each feature
  alone; the weights with their uncertainty; the keep rate per source.
- `python -m recsys.synth [--seeds 8]`: a synthetic listener with a hidden taste (900 songs), run through the real
  loop with learning on and off, paired by seed. Results (16 seeds × 60 sessions, share of autoplay picks
  finished in the last third):

  | | learning on | learning off |
  |---|---|---|
  | first version (online logistic regression, sources take turns) | 50.3 % | 52.6 % |
  | now (Bayesian pairwise, Thompson sampling, source as a feature) | 52.7 % | 50.6 % |

  Learning now helps (+2.1 ± 1.0 points) where it used to hurt (−2.4 ± 1.0); as Kassetto runs (learning on),
  +2.5 ± 1.4 over the first version. The ceiling is low on this listener: ranking the same candidates by its true
  hidden taste (an oracle) finishes only ~4–5 points more than the hand-tuned weights, so better candidates matter
  more than better weights from here. Real listening data will tell more than the synthetic listener.
