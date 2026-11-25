import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa
from .bandit import ARMS, bandit
from .events import boredom
from .sound import sound_model
from .taste import taste
from . import learn, session

def stats():
    with db() as c:
        n = dict(c.execute("SELECT source, COUNT(*) FROM plays WHERE user=? AND event != 'skip' GROUP BY source",   # = Stats
                           (me(),)).fetchall())
        p = dict(c.execute("SELECT pref, COUNT(*) FROM prefs WHERE user=? GROUP BY pref", (me(),)).fetchall())
        P = list(people.peers(me()))                             # only people whose data shapes your taste
        per_user = {people.name(u): k for u, k in c.execute(
            f"SELECT user, COUNT(*) FROM plays WHERE source='ytm' AND user IN ({','.join('?' * len(P))}) GROUP BY user", P)}
    aff, _, anchors = taste()
    top = sorted(aff.items(), key=lambda x: -x[1])[:10]
    m = sound_model()
    with db() as c:
        meta = dict(c.execute("SELECT video_id, artist || ' – ' || title FROM tracks").fetchall())
        n_emb = c.execute("SELECT COUNT(*) FROM emb WHERE vec IS NOT NULL").fetchone()[0]
        n_q = c.execute("SELECT COUNT(*) FROM emb_queue WHERE video_id NOT IN (SELECT video_id FROM emb)").fetchone()[0]
    clusters = [{"weight": round(w, 1), "songs": [meta.get(v, v) for v in vs][:6]} for _, w, vs in (m or {}).get("clusters", [])]
    B = bandit()
    return {"ytm_plays": n.get("ytm", 0), "listenbrainz_listens": n.get("lb", 0), "likes": p.get(1, 0),
            "hidden": p.get(-1, 0), "boredom": round(boredom(), 2), "top_artists": [[a, round(s, 2)] for a, s in top], "anchors": len(anchors),
            "embedded": n_emb, "embed_queue": n_q, "taste_clusters": clusters, "signals": sig_counts(),
            "ranker": learn.report(), "session": {"plays": session.profile()["n"]},
            "user": me(), "plays_by_user": per_user, "blend": people.peers(me()),
            "sources": {ARMS[a]: round(x / (x + y), 2) for a, (x, y) in B.items()}}



def sig_counts():
    with db() as c:
        return dict(c.execute("SELECT kind, COUNT(*) FROM signals WHERE user=? GROUP BY kind", (me(),)).fetchall())
