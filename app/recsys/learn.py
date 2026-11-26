"""The ranker learns you: per-person Bayesian pairwise ranking over the pick features, with Thompson sampling.

Every pick Kassetto serves (autoplay, mixes, the quiz) is logged in table `impressions` with the features it was
scored on. When its outcome arrives (finished, half-heard, skipped, jumped past in Up next, left behind when you
went off autoplay, liked, picked from Up next), the pick gets a label 0..1 and the model is refitted.

What is learned is the order, not a probability (pairwise, as in RankNet / BPR): each outcome is compared with the
picks that got one shortly before it, and for each pair whose labels differ the model learns that the kept pick
should have scored above the other. Ranking is all rank() needs, and the hand-tuned starting weights were never
calibrated probabilities (a pointwise model spent its steps shrinking every weight instead of reordering them).

The fit is Bayesian (Laplace approximation, as in Chapelle & Li 2011, "An Empirical Evaluation of Thompson
Sampling"): a Gaussian prior centred on the starting weights (PRIOR) times a scale c fitted to the data (outcomes
are noisy, so the best weights are small; the scale keeps the prior from fighting that), then the MAP weights by
Newton's method and their precision (the Hessian's diagonal). A person has at most a few thousand labelled picks,
so the whole fit takes milliseconds and runs after every outcome; older outcomes count less (FORGET per outcome,
~300-outcome memory), so the ranker follows you when your taste moves.

rank() scores candidates with weights *sampled* from the posterior (Thompson sampling): where the model is sure,
picks follow it; where it isn't (a source or feature it has seen little of), the draw varies and the uncertain
option gets tried now and then, which is how it learns. The source a candidate came from (similar songs, your
favourites' radios, collaborative filtering, sound, familiar, new artist) is a feature too, so the same model
learns which sources work for you, per song rather than per slot.

Weights are kept in the prior's units (divided by c), stored per person in kv `ranker:<user>` ({"m", "sd", "c",
"n"}); /api/taste shows them next to the prior; `python -m recsys.evaluate` measures how well they predict what
you finished.
"""
import json, math, random, time

import numpy as np

from .core import *  # noqa

# feature -> starting weight (the hand-tuned ranking before learning)
PRIOR = {"bias": 0.0, "sim": 1.0, "aff": 0.8, "snd": 0.9, "sess": 0.8, "sess_art": 0.8, "new_artist": 0.0,
         "recent": -0.6, "skips": -1.5, "liked": 0.5,
         "track": 0.4,                                           # your own history with this song (decayed score)
         # where the candidate came from (one-hot; "similar" is the reference, so it has no weight of its own)
         "src_taste": 0.0, "src_cf": 0.0, "src_sound": 0.0, "src_familiar": 0.6, "src_discovery": 0.0}
FEATURES = list(PRIOR)
SOURCES = [k[4:] for k in FEATURES if k.startswith("src_")]
PRIOR_SD = {k: (10.0 if k == "bias" else 0.4 if k.startswith("src_") else 0.3 + 0.3 * abs(PRIOR[k])) for k in FEATURES}   # prior units
FORGET = 0.997                                                   # weight of an outcome per later outcome
EXPLORE = float(config.env("EXPLORE", "0.3"))                    # Thompson draw scale (0 = always the mean)
HISTORY = 2000                                                   # labelled picks used per fit
MIN_PAIRS = 20                                                   # fewer: keep the prior
CLIP = 4.0
LABEL = {"complete": 1.0, "like": 1.0, "queue_pick": 0.9, "partial": 0.55, "skip": 0.0, "pass": 0.2, "escape": 0.15,
         "hide": 0.0}
WINDOW = 12 * 3600                                               # an outcome counts for a pick served < 12 h ago
PAIR_WINDOW = 6 * 3600                                           # compare with other outcomes from the last 6 h
PAIRS = 6                                                        # at most this many comparisons per outcome
PAIR_MIN = 0.25                                                  # labels this close say nothing about the order


def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS impressions(id INTEGER PRIMARY KEY, user TEXT, ts INTEGER, video_id TEXT, ctx TEXT,
            why TEXT, score REAL, feats TEXT, label REAL, label_ts INTEGER, event TEXT);
        CREATE INDEX IF NOT EXISTS impressions_uv ON impressions(user, video_id, ts);
        """)


def _key(u=None):
    return f"ranker:{u or me()}"


def posterior(u=None):
    """-> (weights, their sd, number of fits), in the prior's units."""
    with db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (_key(u),)).fetchone()
    st = json.loads(r[0]) if r else {}
    m = {**PRIOR, **st.get("m", {})}                             # an older state ({"w": ...}) restarts at the prior
    sd = {**PRIOR_SD, **st.get("sd", {})}
    return {k: m[k] for k in FEATURES}, {k: sd[k] for k in FEATURES}, st.get("n", 0)


def weights(u=None):
    """-> (posterior means, number of fits)."""
    m, _, n = posterior(u)
    return m, n


def sample(u=None, scale=None):
    """Weights drawn from the posterior, for one ranking (Thompson sampling)."""
    m, sd, _ = posterior(u)
    s = EXPLORE if scale is None else scale
    return {k: m[k] + s * sd[k] * random.gauss(0, 1) for k in FEATURES}


def score(f, w):
    return sum(w.get(k, 0.0) * f.get(k, 0.0) for k in FEATURES)


def source_features(arm):
    return {f"src_{a}": 1.0 if a == arm else 0.0 for a in SOURCES}


def log_impressions(picks, ctx):
    """picks: [{videoId, why, _score, _f}] -> impressions (features kept for learning / evaluation)."""
    now = int(time.time())
    rows = [(me(), now, p["videoId"], ctx, p.get("why"), p.get("_score"), json.dumps(p["_f"])) for p in picks if p.get("_f")]
    if rows:
        try:
            with LOCK, db() as c:
                c.executemany("INSERT INTO impressions(user, ts, video_id, ctx, why, score, feats) VALUES(?,?,?,?,?,?,?)", rows)
                c.execute("DELETE FROM impressions WHERE ts < ? AND label IS NULL", (now - 30 * 86400,))
        except sqlite3.OperationalError:
            init()


def pairs(rows):
    """rows: [(feats dict, label, label_ts)] in label order -> (D, T, weights): feature differences, targets
    (1 + label_a - label_b) / 2, recency weights. Each outcome is compared with up to PAIRS earlier ones."""
    D, T, W = [], [], []
    X = [[f.get(k, 0.0) for k in FEATURES] for f, _, _ in rows]
    n = len(rows)
    for i in range(n):
        _, y, t = rows[i]
        for j in range(i - 1, max(-1, i - 1 - PAIRS), -1):
            _, yo, to = rows[j]
            if t - to > PAIR_WINDOW:
                break
            if abs(y - yo) >= PAIR_MIN:
                D.append([a - b for a, b in zip(X[i], X[j])]); T.append((1 + y - yo) / 2); W.append(FORGET ** (n - 1 - i))
    return np.array(D, dtype=float).reshape(-1, len(FEATURES)), np.array(T), np.array(W)


def _loss(D, T, W, w):
    z = np.clip(D @ w, -30, 30)
    return float(W @ (np.logaddexp(0, z) - T * z))


def fit(D, T, W, iters=25):
    """Bayesian pairwise logistic regression -> (means, sds, scale c), means / sds in the prior's units."""
    p0 = np.array([PRIOR[k] for k in FEATURES])
    s0 = np.array([PRIOR_SD[k] for k in FEATURES])
    c = min((x for x in np.geomspace(0.03, 3, 25)), key=lambda x: _loss(D, T, W, x * p0))   # the data's scale
    mu, P = c * p0, 1 / (c * s0) ** 2
    w = mu.copy()
    for _ in range(iters):                                       # Newton steps to the MAP
        p = 1 / (1 + np.exp(-np.clip(D @ w, -30, 30)))
        g = D.T @ (W * (p - T)) + P * (w - mu)
        H = (D * (W * p * (1 - p))[:, None]).T @ D + np.diag(P)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-6:
            break
    p = 1 / (1 + np.exp(-np.clip(D @ w, -30, 30)))
    H = (D * (W * p * (1 - p))[:, None]).T @ D + np.diag(P)
    sd = np.sqrt(np.diag(np.linalg.inv(H)))
    return np.clip(w / c, -CLIP, CLIP), sd / c, float(c)


def refit(u=None):
    """Fit the person's ranker on their recent labelled picks; store it. -> the stored state (or None: too few)."""
    u = u or me()
    with db() as c:
        rows = c.execute("""SELECT feats, label, label_ts FROM impressions WHERE user=? AND label IS NOT NULL
                            ORDER BY label_ts DESC, id DESC LIMIT ?""", (u, HISTORY)).fetchall()
        r = c.execute("SELECT v FROM kv WHERE k=?", (_key(u),)).fetchone()
    n = json.loads(r[0]).get("n", 0) if r else 0
    D, T, W = pairs([(json.loads(f), y, t) for f, y, t in reversed(rows)])
    if len(T) < MIN_PAIRS:
        return None
    m, sd, scale = fit(D, T, W)
    st = {"m": dict(zip(FEATURES, map(float, m))), "sd": dict(zip(FEATURES, map(float, sd))), "c": scale, "n": n + 1}
    with LOCK, db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", (_key(u), json.dumps(st)))
    return st


def outcome(vid, event, played=None, duration=None):
    """An event for a song: label its latest unlabelled impression (if any) and take one learning step."""
    if event not in LABEL or not vid:
        return
    y = LABEL[event]
    if event in ("complete", "partial", "skip") and duration:      # graded by the share heard
        y = max(0.0, min(1.0, (listen_weight(played, duration, event) + 1.2) / 2.2))
    now = int(time.time())
    try:
        with db() as c:
            r = c.execute("""SELECT id, feats FROM impressions WHERE user=? AND video_id=? AND ts>? AND label IS NULL
                             ORDER BY ts DESC LIMIT 1""", (me(), vid, now - WINDOW)).fetchone()
    except sqlite3.OperationalError:
        return
    if not r:
        return
    with LOCK, db() as c:
        c.execute("UPDATE impressions SET label=?, label_ts=?, event=? WHERE id=?", (y, now, event, r[0]))
    refit()


def report():
    m, sd, n = posterior()
    with db() as c:
        try:
            served, labelled = c.execute("SELECT COUNT(*), COUNT(label) FROM impressions WHERE user=?", (me(),)).fetchone()
        except sqlite3.OperationalError:
            served, labelled = 0, 0
    return {"updates": n, "served": served, "labelled": labelled,
            "weights": {k: {"now": round(m[k], 3), "start": PRIOR[k], "sd": round(sd[k], 3)}
                        for k in FEATURES}}
