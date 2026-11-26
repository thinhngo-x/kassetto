import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa

# ---------- sources: keep rate per source ----------
# A Beta(kept, not kept) count per source, slowly forgetting, shown in /api/taste ("sources"). It used to choose
# the source of each slot (Thompson sampling), which let a source win with its best song however poor that was;
# the source is now a feature of the learned ranker (learn.py), which decides per song.

ARMS = {"similar": "similar", "taste": "your taste", "cf": "recommended for you", "sound": "sounds like you",
        "familiar": "you liked this", "discovery": "new for you"}
LABEL_ARM = {v: k for k, v in ARMS.items()}
REWARD = {"complete": (1, 0), "partial": (0.5, 0.5), "skip": (0, 1), "like": (2, 0), "hide": (0, 2), "pass": (0, 0.5), "escape": (0, 0.7)}


PRIOR = {"similar": [3, 2], "taste": [3, 2], "familiar": [3, 2], "sound": [2, 2], "cf": [2, 2], "discovery": [2, 3]}


def _bandit_key():
    """Each person learns which sources work for them (the owner keeps the original key)."""
    return "bandit" if me() == people.owner() else f"bandit:{me()}"


def bandit():
    with db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (_bandit_key(),)).fetchone()
    st = json.loads(r[0]) if r else {}
    return {a: st.get(a, list(PRIOR[a])) for a in ARMS}


def bandit_update(label, event, played=None, duration=None):
    arm = LABEL_ARM.get(label)
    if not arm or event not in REWARD:
        return
    st = bandit()
    for a in st:                                   # slow forgetting (~last 100 outcomes), stays adaptive
        st[a] = [max(1.0, x * 0.99) for x in st[a]]
    ra, rb = REWARD[event]
    if event in ("complete", "partial", "skip") and duration:   # graded: the share of the pick you actually heard
        w = listen_weight(played, duration, event)
        ra, rb = (max(0.0, (w + 1.2) / 2.2), max(0.0, 1 - (w + 1.2) / 2.2))
    st[arm] = [st[arm][0] + ra, st[arm][1] + rb]
    with LOCK, db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", (_bandit_key(), json.dumps(st)))
