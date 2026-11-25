import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa
from .bandit import bandit_update
from .sound import track_meta_put
from . import learn

# ---------- events ----------

# implicit feedback: kind -> weight on the track (and, shared, on its artists)
SIGNAL_W = {"replay": 1.0, "queue_add": 0.8, "queue_remove": -0.8, "search_click": 0.6, "search_artist": 0.3,
            "lyrics_open": 0.3, "seek_back": 0.4, "seek_fwd": -0.2, "volume_up": 0.2,
            # autoplay that didn't hold you: a pick you jumped past in Up next / the picks waiting when you left
            # autoplay for something you chose yourself; and the song you picked from Up next yourself
            "pass": -0.3, "escape": -0.4, "queue_pick": 0.4}
SIGNALS = set(SIGNAL_W)

# ---------- boredom (short-term: autoplay isn't holding you right now) ----------
# Each pass / escape raises it, finishing autoplay picks lowers it, it fades (half-life 3 h). While it's high,
# rank() leans away from the familiar: fewer "you liked this" picks, more new artists, looser similarity to the
# seed, fewer songs per artist, more randomness.
BORED_HALF_LIFE = 3 * 3600
BORED_STEP = {"escape": 1.0, "pass": 0.35, "complete": -0.6, "like": -0.8}


def _bored_key():
    return f"bored:{me()}"


def boredom():
    """0 (autoplay is fine) .. 1 (you keep leaving it)."""
    with db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (_bored_key(),)).fetchone()
    if not r:
        return 0.0
    v, ts = json.loads(r[0])
    return max(0.0, min(1.0, v * 0.5 ** ((time.time() - ts) / BORED_HALF_LIFE) / 3))


def bored_update(event, auto=True):
    step = BORED_STEP.get(event)
    if step is None or (step < 0 and not auto):
        return
    with LOCK, db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (_bored_key(),)).fetchone()
        v, ts = json.loads(r[0]) if r else (0.0, time.time())
        v = max(0.0, min(3.5, v * 0.5 ** ((time.time() - ts) / BORED_HALF_LIFE) + step))
        c.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", (_bored_key(), json.dumps([v, time.time()])))




def record(ev):
    """ev: {videoId,title,artist,album,duration,played,event}; event = complete|partial|skip|like|dislike|unlike or an
    implicit signal (SIGNALS: replay is detected here, the page sends the others)."""
    now = int(time.time())
    if ev["event"] == "dislike":                                  # old clients
        ev = {**ev, "event": "hide"}
    if ev.get("why") and ev["event"] in ("complete", "partial", "skip", "like", "hide", "pass", "escape"):
        bandit_update(ev["why"], ev["event"], ev.get("played"), ev.get("duration"))
    if ev["event"] in BORED_STEP:
        bored_update(ev["event"], auto=bool(ev.get("auto")))
    learn.outcome(ev.get("videoId"), ev["event"], ev.get("played"), ev.get("duration"))   # the ranker learns
    track_meta_put([ev])
    hour = time.localtime(now).tm_hour
    if ev["event"] in SIGNALS:
        with LOCK, db() as c:
            c.execute("INSERT INTO signals(ts,video_id,artist,kind,value,hour,user) VALUES(?,?,?,?,?,?,?)",
                      (now, ev.get("videoId"), ev.get("artist") or ev.get("q"), ev["event"], SIGNAL_W[ev["event"]], hour, me()))
        return
    if ev["event"] == "complete":                                 # finished again within 14 days = a replay
        with db() as c:
            again = c.execute("SELECT 1 FROM plays WHERE video_id=? AND event='complete' AND ts > ? AND user=? LIMIT 1",
                              (ev.get("videoId"), now - 14 * 86400, me())).fetchone()
        if again:
            with LOCK, db() as c:
                c.execute("INSERT INTO signals(ts,video_id,artist,kind,value,hour,user) VALUES(?,?,?,?,?,?,?)",
                          (now, ev.get("videoId"), ev.get("artist"), "replay", SIGNAL_W["replay"], hour, me()))
    with LOCK, db() as c:
        if ev["event"] in ("like", "unlike", "hide", "unhide"):
            if ev["event"] in ("unlike", "unhide"):
                c.execute("DELETE FROM prefs WHERE video_id=? AND user=? AND pref=?",
                          (ev["videoId"], me(), 1 if ev["event"] == "unlike" else -1))
            else:
                c.execute("INSERT OR REPLACE INTO prefs(user,video_id,title,artist,pref,ts) VALUES(?,?,?,?,?,?)",
                          (me(), ev["videoId"], ev.get("title"), ev.get("artist"), 1 if ev["event"] == "like" else -1, now))
            return
        c.execute("INSERT OR IGNORE INTO plays(ts,video_id,title,artist,album,duration,played,event,source,user)"
                  " VALUES(?,?,?,?,?,?,?,?, 'ytm',?)", (now, ev.get("videoId"), ev.get("title"), ev.get("artist"),
                  ev.get("album"), ev.get("duration"), int(ev.get("played") or 0), ev["event"], me()))


def prefs():
    """Your own ❤️ (+1) / hidden (-1, only for you)."""
    with db() as c:
        return {v: p for v, p in c.execute("SELECT video_id, pref FROM prefs WHERE user=?", (me(),))}
