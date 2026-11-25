"""recsys: ytm's personal recommender (package). Modules:
  core          database, who is listening (people / circles), normalisation, listen_weight
  events        what you do -> plays / prefs / signals, boredom
  taste         long-term taste: artist affinity, per-track scores, anchors (decayed, time of day)
  sound         CLAP audio embeddings: clusters, "sounds like you", taste groups
  bandit        Thompson sampling over recommendation sources
  ranking       candidates -> scored -> picked (diversity, familiarity cap, boredom)
  listenbrainz  listens sync, collaborative filtering, LB playlists
  search        library search, search re-ranking, vibe (text -> audio) search
  store         small tables: track metadata map, liked songs, lyrics cache
  session       short-term intent: this listening session (plays < 30 min apart) -> sound + artist mood
  learn         the ranker learns you: features logged per pick (impressions), online logistic regression
                on outcomes, pulled towards the hand-tuned starting weights
  evaluate      `python -m recsys.evaluate [user]`: AUC of start vs learned weights and each feature
  report        /api/taste
Pipeline (ranking.rank): candidates (seed radio, favourites' radios, ListenBrainz CF, sound neighbours) ->
features (similarity, artist affinity, sound vs taste, session sound / artist mood, novelty, repeats, skips,
liked) -> learned score, reshaped by boredom -> Thompson-sampled sources with diversity rules -> flow order
(each next song the closest in sound within a few places) -> a specific "because …" per pick.

Original overview:

Signals (SQLite /data/ytm.db):
  plays    every track ytm played: complete / partial / skip (+ seconds played), and ListenBrainz listens
           (Spotify, Navidrome, imports) pulled by sync_listenbrainz()  -> source 'ytm' | 'lb'
  prefs    ❤️ liked (+1) / hidden from recommendations (-1, that song only) per video id
  cf_map   ListenBrainz CF recommendation (recording MBID) -> YouTube Music video id
Candidates: radio of the seed track (rank-weighted), radio of 1-2 "anchor" favourites from the history,
ListenBrainz collaborative-filtering recommendations (when the account has enough history).
Score = similarity to seed + artist affinity (decayed, skips negative) - recent repeats - skipped + jitter.
No dislike button: negatives come from behaviour (early skips, queue removals); a song rejected in its first
seconds twice in 90 days is dropped like a hidden one.
Selection: no same artist twice in a row, <= 3 per artist per batch, ~25 % of slots for artists without history.
"""
from .core import *          # noqa: F401,F403
from .events import *        # noqa
from .taste import *         # noqa
from .sound import *         # noqa
from .bandit import *        # noqa
from .ranking import *       # noqa
from .listenbrainz import *  # noqa
from .search import *        # noqa
from .store import *         # noqa
from .report import *        # noqa
from .search import _tokens  # noqa: F401  (used by spotify.py)
from .listenbrainz import _lb  # noqa: F401
from .bandit import _bandit_key  # noqa: F401
from . import learn, session  # noqa: F401
