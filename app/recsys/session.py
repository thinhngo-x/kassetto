"""Short-term intent: what you did in the current listening session.

A session = your plays with no gap longer than 30 min, going back from now (empty if you last played > 30 min
ago). Each play counts by how much you heard (listen_weight: finished +1 ... left in the first seconds -1.2),
the most recent ones most (x0.8 per step back), plus this session's explicit signals (picked from Up next,
from search, jumped past, left autoplay).

profile() turns it into:
  pos / neg   weighted mean CLAP vectors of what you kept / rejected (None without fingerprints)
  artists     {normalised artist: weight}: you skipped two Linkin Park songs in a row -> strongly negative
  n           how many plays the session has (0 = no session: the long-term taste decides alone)
ranking uses it as features "sess" (sound closeness to this session) and "sess_art" (artist mood right now).
"""
import time

import numpy as np

from .core import *  # noqa
from .sound import embeddings

GAP = 30 * 60
DECAY = 0.8
SIG = {"queue_pick": 0.8, "search_click": 0.8, "pass": -0.5, "escape": -0.6, "queue_remove": -0.8, "replay": 1.0}


def session(now=None, max_items=15):
    """-> [(video_id, artist, weight)] newest first."""
    now = now or time.time()
    with db() as c:
        plays = c.execute("""SELECT ts, video_id, artist, played, duration, event FROM plays
                             WHERE user=? AND source='ytm' AND ts > ? ORDER BY ts DESC LIMIT 60""",
                          (me(), int(now - 6 * 3600))).fetchall()
        sigs = c.execute("""SELECT ts, video_id, artist, kind FROM signals WHERE user=? AND ts > ? ORDER BY ts DESC""",
                         (me(), int(now - 6 * 3600))).fetchall()
    out, last = [], now
    for ts, vid, artist, played, dur, ev in plays:
        if last - ts > GAP + (dur or 0):                         # a gap: the session started after this
            break
        out.append((ts, vid, artist, listen_weight(played, dur, ev)))
        last = ts
    if not out:
        return []
    start = out[-1][0] - 60
    out += [(ts, vid, artist, SIG[k]) for ts, vid, artist, k in sigs if ts >= start and k in SIG]
    out.sort(key=lambda x: -x[0])
    return [(vid, artist, w * DECAY ** i) for i, (_, vid, artist, w) in enumerate(out[:max_items])]


def profile(now=None):
    s = session(now)
    E = embeddings()
    pos, neg, pw, nw, arts = None, None, 0.0, 0.0, {}
    for vid, artist, w in s:
        for a in split_artists(artist):
            arts[a] = arts.get(a, 0) + w
        e = E.get(vid) if vid else None
        if e is None:
            continue
        if w > 0:
            pos = e * w if pos is None else pos + e * w; pw += w
        elif w < 0:
            neg = e * -w if neg is None else neg - e * w; nw -= w
    unit = lambda v: v / (np.linalg.norm(v) + 1e-9) if v is not None else None
    return {"pos": unit(pos), "neg": unit(neg), "artists": arts, "n": len(s), "items": s}


def sess_score(p, vec):
    """Sound closeness to what you kept this session minus closeness to what you rejected (about -1..1)."""
    if vec is None or not p["n"]:
        return 0.0
    out = 0.0
    if p["pos"] is not None:
        out += float(vec @ p["pos"])
    if p["neg"] is not None:
        out -= 0.7 * float(vec @ p["neg"])
    return max(-1.0, min(1.0, out))


def sess_artist(p, artists):
    """This session's mood about the candidate's artists: < 0 after skipping them, a little > 0 after finishing."""
    if not p["n"]:
        return 0.0
    v = sum(p["artists"].get(a, 0) for a in artists) / max(1, len(artists))
    return max(-1.5, min(0.6, v))
