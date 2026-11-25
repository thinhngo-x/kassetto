import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa

# ---------- taste model ----------

def daypart(hour):
    return 0 if 5 <= hour < 12 else 1 if 12 <= hour < 18 else 2 if 18 <= hour < 23 else 3   # morning/afternoon/evening/night


def taste(hour=None):
    """-> (artist affinity {norm artist: score}, per-video stats {vid: {...}}, anchors [video ids]).
    Listens are weighted by how much was heard; implicit signals (replays, queue adds/removals, searches, lyrics,
    rewinds, volume) add to tracks and artists; with `hour`, plays from the same part of the day count 50 % more."""
    now = time.time()
    dp = daypart(hour) if hour is not None else None
    aff, vids, title_keys = {}, {}, {}
    with db() as c:
        rows = c.execute("SELECT ts, video_id, title, artist, event, source, played, duration, user FROM plays WHERE ts > ?",
                         (int(now - 365 * 86400),)).fetchall()
        likes = c.execute("SELECT video_id, artist, pref, user FROM prefs").fetchall()
        sigs = c.execute("SELECT ts, video_id, artist, kind, value, hour, user FROM signals WHERE ts > ?",
                         (int(now - 365 * 86400),)).fetchall()
    rows, likes, sigs = mine_or_peers(rows, 8), mine_or_peers(likes, 3), mine_or_peers(sigs, 6)
    for ts, vid, artist, kind, value, hr, u in sigs:
        decay = 0.5 ** ((now - ts) / 86400 / HALF_LIFE_DAYS) * uw(u)
        ctx = 1.5 if dp is not None and hr is not None and daypart(hr) == dp else 1.0
        arts = split_artists(artist)
        share = 0.5 if kind == "search_artist" else 0.4            # signals move artists less than tracks
        for a in arts:
            aff[a] = aff.get(a, 0) + value * decay * ctx * (1 if kind == "search_artist" else share) / len(arts)
        if vid:
            v = vids.setdefault(vid, {"recent": 0, "skips": 0.0, "score": 0.0})
            v["score"] += value * decay
    for ts, vid, title, artist, event, source, played, duration, u in rows:
        decay = 0.5 ** ((now - ts) / 86400 / HALF_LIFE_DAYS) * uw(u)
        if dp is not None and daypart(time.localtime(ts).tm_hour) == dp:
            decay *= 1.5
        w = W["lb"] if source == "lb" else listen_weight(played, duration, event)
        arts = split_artists(artist)
        for a in arts:
            aff[a] = aff.get(a, 0) + w * decay / len(arts)
        if vid:
            v = vids.setdefault(vid, {"recent": 0, "skips": 0.0, "score": 0.0})
            if now - ts < 3 * 86400 and event != "skip":
                v["recent"] += 1
            if w < -0.5:                                         # a real rejection (not "listened to most of it")
                v["skips"] += decay
            if w <= -1.2 and now - ts < 90 * 86400:              # left within the first seconds
                v["rej"] = v.get("rej", 0) + 1
            v["score"] += w * decay
        if source == "lb":
            k = (norm(title), arts[0] if arts else "")
            title_keys[k] = title_keys.get(k, 0) + decay
    for vid, artist, pref, u in likes:
        for a in split_artists(artist):
            if pref > 0:                                         # ❤️ = love: the strongest signal; hidden = that song only
                aff[a] = aff.get(a, 0) + 4.0 * uw(u) / max(1, len(split_artists(artist)))
    try:                                                     # old Spotify hours: small boost, known artists only
        import spotify
        aff = spotify.prior(aff, me())
    except Exception:
        pass
    # anchors: tracks finished/liked most (decayed), your own likes first, then circle-mates' (blend > 0)
    liked = [v for v, a, p, u in likes if p > 0 and (u or OWNER) == me()] + [v for v, a, p, u in likes if p > 0 and (u or OWNER) != me()]
    ranked = sorted((v for v in vids if vids[v]["score"] > 0.5), key=lambda v: -vids[v]["score"])
    anchors = list(dict.fromkeys(liked + ranked))[:20]
    return aff, vids, anchors
