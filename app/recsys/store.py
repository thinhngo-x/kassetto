import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa

def map_get(key):
    with db() as c:
        r = c.execute("SELECT video_id, title, artist FROM cf_map WHERE mbid=?", (key,)).fetchone()
    return r


def map_put(key, vid, title, artist):
    with LOCK, db() as c:
        c.execute("INSERT OR REPLACE INTO cf_map VALUES(?,?,?,?,?)", (key, vid, title, artist, int(time.time())))


def artist_names():
    """normalised artist name -> original spelling (from liked/played tracks)."""
    out = {}
    with db() as c:
        rows = c.execute("SELECT artist FROM prefs WHERE pref > 0 UNION ALL SELECT artist FROM plays").fetchall()
    for (a,) in rows:
        for part in re.split(r",| & | x | feat\.? | ft\.? ", a or ""):
            part = part.strip()
            if part:
                out.setdefault(norm(part), part)
    return out


def liked_tracks():
    """👍 songs, newest first, with whatever metadata ytm has seen."""
    with db() as c:
        rows = c.execute("""SELECT p.video_id, COALESCE(t.title, p.title), COALESCE(t.artist, p.artist), t.album, t.thumb,
                                   t.duration FROM prefs p LEFT JOIN tracks t ON t.video_id = p.video_id
                            WHERE p.pref > 0 AND p.user = ? ORDER BY p.ts DESC""", (me(),)).fetchall()
    return [{"type": "song", "videoId": v, "title": ti or v, "artist": ar or "", "album": al or "",
             "thumb": th or f"https://i.ytimg.com/vi/{v}/hqdefault.jpg", "duration": du} for v, ti, ar, al, th, du in rows]


def lyrics_get(vid, max_age_missing=7 * 86400):
    """Cached lyrics (None = not cached; a cached 'not found' expires after a week, found ones never)."""
    with db() as c:
        r = c.execute("SELECT data, ts FROM lyrics WHERE video_id=?", (vid,)).fetchone()
    if not r:
        return None
    d = json.loads(r[0])
    if not d.get("lines") and time.time() - r[1] > max_age_missing:
        return None
    return d


def lyrics_put(vid, data):
    with LOCK, db() as c:
        c.execute("INSERT OR REPLACE INTO lyrics VALUES(?,?,?)", (vid, json.dumps(data, ensure_ascii=False), int(time.time())))
