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
   artist mood this session, new artist, recent repeats, past skips, liked.
3. **Score** = your learned weights × features, reshaped by boredom, plus a little randomness.
4. **Selection:** each slot goes to the source that wins a Thompson-sampling draw (a bandit learns which sources
   work for you), with rules: never the same artist twice in a row, at most 3 per artist, a cap on familiar songs.
5. **Flow:** the picks are reordered so each song is the one closest in sound to the previous (within a few places).
6. **Because:** each pick gets a specific reason.

## Learning

Every pick is logged with its features (table `impressions`). When its outcome arrives (finished, half-heard,
skipped, liked, picked from *Up next*, jumped past, left behind), the pick gets a label from 0 to 1 and the
person's weights take one step of online logistic regression, pulled towards the hand-tuned starting weights (L2) so
little data changes little.

## Measuring it

- `python -m recsys.evaluate [user]`: on your labelled picks, the AUC of the starting vs your learned weights (how
  often a song you kept scored above one you didn't), per feature, and the keep rate per source.
- `python -m recsys.synth`: a synthetic listener with a hidden taste, run through the real loop with learning on and
  off. Current result (6 seeds × 60 sessions): the learned ranker finishes 32.2 % of autoplay picks vs 29.7 % with
  the starting weights (AUC 0.706 vs 0.698): learning helps, but not much yet. Improving that is open work.
