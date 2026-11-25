"""The ranker learns from you: per-person feature weights, updated online from what happens to each pick.

Every pick Kassetto serves (autoplay, mixes) is logged in table `impressions` with the features it was scored on.
When its outcome arrives (finished, half-heard, skipped, jumped past in Up next, left behind when you went off
autoplay, liked, picked from Up next), the pick gets a label 0..1 and the weights take one logistic-regression
step towards predicting it: w += lr * ((y - p) * f - l2 * (w - prior)).

The prior = the hand-tuned weights Kassetto started with, and the L2 pull towards it keeps a few odd evenings from
undoing them: with little data the ranker behaves as before, with more it becomes yours. Weights are clipped,
stored per person in kv `ranker:<user>`; /api/taste shows them next to the prior; `python -m recsys.evaluate`
measures how well they (and each feature alone) predict what you finished.
"""
import json, math, time

from .core import *  # noqa

# feature -> starting weight (the hand-tuned ranking before learning)
PRIOR = {"bias": 0.0, "sim": 1.0, "aff": 0.8, "snd": 0.9, "sess": 0.8, "sess_art": 0.8, "new_artist": 0.0,
         "recent": -0.6, "skips": -1.5, "liked": 0.5}
FEATURES = list(PRIOR)
LR, L2, CLIP = 0.08, 0.03, 4.0
LABEL = {"complete": 1.0, "like": 1.0, "queue_pick": 0.9, "partial": 0.55, "skip": 0.0, "pass": 0.2, "escape": 0.15,
         "hide": 0.0}
WINDOW = 12 * 3600                                               # an outcome counts for a pick served < 12 h ago


def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS impressions(id INTEGER PRIMARY KEY, user TEXT, ts INTEGER, video_id TEXT, ctx TEXT,
            why TEXT, score REAL, feats TEXT, label REAL, label_ts INTEGER, event TEXT);
        CREATE INDEX IF NOT EXISTS impressions_uv ON impressions(user, video_id, ts);
        """)


def _key(u=None):
    return f"ranker:{u or me()}"


def weights(u=None):
    with db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (_key(u),)).fetchone()
    st = json.loads(r[0]) if r else {}
    return {**PRIOR, **st.get("w", {})}, st.get("n", 0)


def score(f, w):
    return sum(w.get(k, 0.0) * f.get(k, 0.0) for k in FEATURES)


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
    f = json.loads(r[1])
    w, n = weights()
    p = 1 / (1 + math.exp(-max(-30, min(30, score(f, w)))))
    for k in FEATURES:
        g = (y - p) * f.get(k, 0.0) - (0 if k == "bias" else L2) * (w[k] - PRIOR[k])   # bias: free (order-neutral)
        w[k] = max(-CLIP, min(CLIP, w[k] + LR * g))
    with LOCK, db() as c:
        c.execute("UPDATE impressions SET label=?, label_ts=?, event=? WHERE id=?", (y, now, event, r[0]))
        c.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", (_key(), json.dumps({"w": w, "n": n + 1})))


def report():
    w, n = weights()
    with db() as c:
        try:
            served, labelled = c.execute("SELECT COUNT(*), COUNT(label) FROM impressions WHERE user=?", (me(),)).fetchone()
        except sqlite3.OperationalError:
            served, labelled = 0, 0
    return {"updates": n, "served": served, "labelled": labelled,
            "weights": {k: {"now": round(w[k], 3), "start": PRIOR[k]} for k in FEATURES}}
