import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa

# ---------- ListenBrainz ----------

def _lb(path, params=None, token=None):
    url = "https://api.listenbrainz.org" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Token {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r) if r.status == 200 else None


def sync_listenbrainz(max_pages=20):
    """Pull new listens of every own ListenBrainz account (people.json) into plays (source 'lb', user = that
    person). Listens ytm scrobbled itself are skipped (already in plays). Returns how many were added."""
    added = 0
    for person, lb_user, token in people.lb_accounts():
        added += _sync_lb_account(person, lb_user, token, max_pages)
    return added


def _sync_lb_account(person, lb_user, token, max_pages):
    key = "lb_last" if person == people.owner() else f"lb_last:{lb_user}"   # the owner keeps the original key
    with db() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    last, newest, added, max_ts = int(row[0]) if row else 0, 0, 0, None
    for _ in range(max_pages):
        params = {"count": 1000, **({"max_ts": max_ts} if max_ts else {})}
        d = _lb(f"/1/user/{urllib.parse.quote(lb_user)}/listens", params, token)
        ls = (d or {}).get("payload", {}).get("listens") or []
        ls = [l for l in ls if l["listened_at"] > last]
        if not ls:
            break
        with LOCK, db() as c:
            for l in ls:
                m = l["track_metadata"]
                if (m.get("additional_info") or {}).get("submission_client") == "ytm":
                    continue                                   # our own scrobbles: already in plays
                cur = c.execute("INSERT OR IGNORE INTO plays(ts,video_id,title,artist,album,duration,played,event,source,user)"
                                " VALUES(?,?,?,?,?,?,?,?, 'lb', ?)", (l["listened_at"], None, m.get("track_name"),
                                m.get("artist_name"), m.get("release_name"), None, None, "complete", person))
                added += cur.rowcount
        newest = max(newest, ls[0]["listened_at"])
        max_ts = ls[-1]["listened_at"]
        if len(ls) < 1000:
            break
    if newest:
        with db() as c:
            c.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", (key, str(max(newest, last))))
    return added


def cf_recordings(count=25):
    """ListenBrainz collaborative-filtering recommendations -> [(mbid, score)] (empty until enough history)."""
    lb_user, token, _ = people.lb_account(me())                # own account, or the one you scrobble as
    if not lb_user:
        return []
    try:
        d = _lb(f"/1/cf/recommendation/user/{urllib.parse.quote(lb_user)}/recording", {"count": count}, token)
    except Exception:
        return []
    return [(r["recording_mbid"], r.get("score", 0.5)) for r in ((d or {}).get("payload") or {}).get("mbids") or []]


def cf_resolve(mbids, ytm_search):
    """MBIDs -> YouTube Music songs (cached in cf_map)."""
    out = []
    with db() as c:
        known = {m: (v, t, a) for m, v, t, a in c.execute(
            f"SELECT mbid, video_id, title, artist FROM cf_map WHERE mbid IN ({','.join('?' * len(mbids))})", mbids)} if mbids else {}
    todo = [m for m in mbids if m not in known][:8]                    # limit lookups per call
    if todo:
        try:
            meta = _lb("/1/metadata/recording/", {"recording_mbids": ",".join(todo), "inc": "artist"}) or {}
        except Exception:
            meta = {}
        for m in todo:
            r = meta.get(m) or {}
            title = (r.get("recording") or {}).get("name")
            artist = (r.get("artist") or {}).get("name")
            vid = None
            if title and artist:
                try:
                    res = ytm_search(f"{artist} {title}", filter="songs", limit=3)
                    vid = res[0]["videoId"] if res else None
                except Exception:
                    pass
            known[m] = (vid, title, artist)
            with db() as c:
                c.execute("INSERT OR REPLACE INTO cf_map VALUES(?,?,?,?,?)", (m, vid, title, artist, int(time.time())))
    for m in mbids:
        if m in known and known[m][0]:
            out.append(known[m][0])
    return out



# ---------- ListenBrainz "created for you" playlists (Weekly Exploration, Weekly/Daily Jams …) ----------

def lb_playlists(count=10):
    lb_user, token, _ = people.lb_account(me())
    if not lb_user:
        return []
    try:
        d = _lb(f"/1/user/{urllib.parse.quote(lb_user)}/playlists/createdfor", {"count": count}, token) or {}
    except Exception:
        return []
    out = []
    for p in d.get("playlists") or []:
        p = p.get("playlist") or {}
        mbid = (p.get("identifier") or "").rstrip("/").rsplit("/", 1)[-1]
        if mbid:
            out.append({"id": mbid, "title": p.get("title") or "ListenBrainz playlist", "date": (p.get("date") or "")[:10]})
    return out


def lb_playlist(mbid):
    """-> (title, [(recording_mbid, title, artist)])"""
    d = _lb(f"/1/playlist/{urllib.parse.quote(mbid)}") or {}
    p = d.get("playlist") or {}
    tracks = []
    for t in p.get("track") or []:
        ids = t.get("identifier") or []
        ids = [ids] if isinstance(ids, str) else ids
        rec = next((i.rstrip("/").rsplit("/", 1)[-1] for i in ids if "/recording/" in i), None)
        if t.get("title") and t.get("creator"):
            tracks.append((rec or f"{t['creator']}|{t['title']}", t["title"], t["creator"]))
    return p.get("title") or "ListenBrainz playlist", tracks
