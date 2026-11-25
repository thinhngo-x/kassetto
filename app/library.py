"""Library features (same SQLite file as the recommender):

  playlists   your own playlists (pl, pl_tracks): private or shared with one of your circles (people.py; every
              member may add / remove / reorder, only the owner renames / re-shares / deletes);
              the weekly generated lists live here too (kind 'weekly', rebuilt once per ISO week by app.py)
  weekly      queries behind "On repeat" and "Forgotten favourites" (Discover weekly needs radios: app.py)
  stats       listening stats per month / year / all time, and what a circle's members love
  settings    small per-user JSON settings in kv (wake-up music)
"""
import json, secrets, time

import people
import recommend as rec


def init():
    with rec.db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS pl(id TEXT PRIMARY KEY, owner TEXT, name TEXT, shared INTEGER DEFAULT 0,
                                      kind TEXT DEFAULT 'user', ts INTEGER, updated INTEGER);
        CREATE TABLE IF NOT EXISTS pl_tracks(pl TEXT, pos REAL, video_id TEXT, title TEXT, artist TEXT, album TEXT,
                                             duration INTEGER, thumb TEXT, added_by TEXT, ts INTEGER,
                                             PRIMARY KEY(pl, video_id));
        """)
        if "circle" not in {r[1] for r in c.execute("PRAGMA table_info(pl)")}:   # shared flag -> shared with a circle
            c.execute("ALTER TABLE pl ADD COLUMN circle TEXT")
            for pid, owner in c.execute("SELECT id, owner FROM pl WHERE shared=1").fetchall():
                c.execute("UPDATE pl SET circle=? WHERE id=?", (next(iter(people.circles_of(owner)), None), pid))


# ---------- playlists ----------

class Denied(Exception):
    pass


def _circle_name(cid):
    return (people.cfg()["circles"].get(cid) or {}).get("name", cid) if cid else None


def _row(c, pid):
    r = c.execute("SELECT id, owner, name, circle, kind, ts, updated FROM pl WHERE id=?", (pid,)).fetchone()
    if not r or not (r[1] == rec.me() or (r[3] and r[3] in people.circles_of(rec.me()))):
        raise Denied("no such playlist")
    return {"id": r[0], "owner": r[1], "name": r[2], "shared": bool(r[3]), "circle": r[3], "circle_name": _circle_name(r[3]),
            "kind": r[4], "ts": r[5], "updated": r[6], "mine": r[1] == rec.me()}


def pl_list(kind="user"):
    with rec.db() as c:
        mine = list(people.circles_of(rec.me())) or ["\0"]
        rows = c.execute(f"""SELECT p.id, p.owner, p.name, p.circle, p.kind, p.updated, COUNT(t.video_id),
                                   (SELECT thumb FROM pl_tracks WHERE pl=p.id ORDER BY pos LIMIT 1)
                            FROM pl p LEFT JOIN pl_tracks t ON t.pl = p.id
                            WHERE p.kind=? AND (p.owner=? OR p.circle IN ({",".join("?" * len(mine))}))
                            GROUP BY p.id ORDER BY p.updated DESC""", (kind, rec.me(), *mine)).fetchall()
    return [{"id": r[0], "owner": r[1], "owner_name": people.name(r[1]), "name": r[2], "shared": bool(r[3]), "circle": r[3],
             "circle_name": _circle_name(r[3]), "kind": r[4], "updated": r[5], "count": r[6], "thumb": r[7],
             "mine": r[1] == rec.me()} for r in rows]


def _my_circle(cid):
    if cid and cid not in people.circles_of(rec.me()):
        raise Denied("you can only share with a circle you are in")
    return cid or None


def pl_create(name, circle=None, kind="user", pid=None):
    pid = pid or "pl" + secrets.token_urlsafe(6)
    now, circle = int(time.time()), _my_circle(circle)
    with rec.db() as c:
        c.execute("INSERT OR REPLACE INTO pl(id, owner, name, shared, kind, ts, updated, circle) VALUES(?,?,?,?,?,?,?,?)",
                  (pid, rec.me(), (name or "New playlist").strip()[:80], int(bool(circle)), kind, now, now, circle))
    return pid


def pl_get(pid):
    with rec.db() as c:
        p = _row(c, pid)
        p["tracks"] = [{"type": "song", "videoId": r[0], "title": r[1], "artist": r[2], "album": r[3] or "",
                        "duration": r[4], "thumb": r[5], "added_by": r[6]}
                       for r in c.execute("SELECT video_id, title, artist, album, duration, thumb, added_by FROM pl_tracks "
                                          "WHERE pl=? ORDER BY pos", (pid,))]
    return p


def pl_update(pid, name=None, circle=False):
    """circle: a circle id to share with, None = private, False = unchanged."""
    with rec.db() as c:
        p = _row(c, pid)
        if not p["mine"]:
            raise Denied("only the owner can rename or share it")
        if name is not None:
            c.execute("UPDATE pl SET name=?, updated=? WHERE id=?", (name.strip()[:80] or p["name"], int(time.time()), pid))
        if circle is not False:
            cid = _my_circle(circle)
            c.execute("UPDATE pl SET circle=?, shared=?, updated=? WHERE id=?", (cid, int(bool(cid)), int(time.time()), pid))


def pl_delete(pid):
    with rec.db() as c:
        p = _row(c, pid)
        if not p["mine"] or p["kind"] != "user":
            raise Denied("only the owner can delete it")
        c.execute("DELETE FROM pl_tracks WHERE pl=?", (pid,))
        c.execute("DELETE FROM pl WHERE id=?", (pid,))


def pl_add(pid, songs):
    """Append songs (skips ones already in it). -> number added."""
    now, added = int(time.time()), 0
    with rec.db() as c:
        p = _row(c, pid)
        if p["kind"] != "user":
            raise Denied("generated playlists can't be edited")
        pos = (c.execute("SELECT MAX(pos) FROM pl_tracks WHERE pl=?", (pid,)).fetchone()[0] or 0) + 1
        for s in songs:
            cur = c.execute("INSERT OR IGNORE INTO pl_tracks VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (pid, pos, s["videoId"], s.get("title"), s.get("artist"), s.get("album"), s.get("duration"),
                             s.get("thumb"), rec.me(), now))
            added += cur.rowcount; pos += 1
        c.execute("UPDATE pl SET updated=? WHERE id=?", (now, pid))
    return added


def pl_remove(pid, vid):
    with rec.db() as c:
        if _row(c, pid)["kind"] != "user":
            raise Denied("generated playlists can't be edited")
        c.execute("DELETE FROM pl_tracks WHERE pl=? AND video_id=?", (pid, vid))
        c.execute("UPDATE pl SET updated=? WHERE id=?", (int(time.time()), pid))


def pl_move(pid, vid, to):
    with rec.db() as c:
        if _row(c, pid)["kind"] != "user":
            raise Denied("generated playlists can't be edited")
        order = [r[0] for r in c.execute("SELECT video_id FROM pl_tracks WHERE pl=? ORDER BY pos", (pid,))]
        if vid not in order:
            return
        order.remove(vid)
        order.insert(max(0, min(int(to), len(order))), vid)
        c.executemany("UPDATE pl_tracks SET pos=? WHERE pl=? AND video_id=?", [(i, pid, v) for i, v in enumerate(order)])


def pl_replace(pid, name, songs, kind="weekly"):
    """Generated playlists (kind 'weekly' / 'daily'): overwrite name + tracks."""
    now = int(time.time())
    with rec.db() as c:
        c.execute("INSERT OR REPLACE INTO pl(id, owner, name, shared, kind, ts, updated, circle) VALUES(?,?,?,?,?,?,?,NULL)",
                  (pid, rec.me(), name, 0, kind, now, now))
        c.execute("DELETE FROM pl_tracks WHERE pl=?", (pid,))
        c.executemany("INSERT OR IGNORE INTO pl_tracks VALUES(?,?,?,?,?,?,?,?,?,?)",
                      [(pid, i, s["videoId"], s.get("title"), s.get("artist"), s.get("album"), s.get("duration"),
                        s.get("thumb"), "ytm", now) for i, s in enumerate(songs)])


def pl_drop(pid):
    """Remove a generated playlist (a Daily Mix whose taste group is gone)."""
    with rec.db() as c:
        c.execute("DELETE FROM pl_tracks WHERE pl=?", (pid,)); c.execute("DELETE FROM pl WHERE id=? AND kind!='user'", (pid,))


def pl_containing(vid):
    """Which of my (editable) playlists already hold this song (for the 'Add to playlist' sheet)."""
    ids = {p["id"] for p in pl_list()}
    with rec.db() as c:
        return [r[0] for r in c.execute("SELECT pl FROM pl_tracks WHERE video_id=?", (vid,)) if r[0] in ids]


# ---------- weekly lists (queries) ----------

def _meta(c, vid):
    r = c.execute("SELECT title, artist, album, thumb, duration FROM tracks WHERE video_id=?", (vid,)).fetchone()
    return r


def _song(c, vid, title, artist, album=None, duration=None):
    m = _meta(c, vid) or (None,) * 5
    return {"type": "song", "videoId": vid, "title": title or m[0] or "?", "artist": artist or m[1] or "",
            "album": album or m[2] or "", "thumb": m[3] or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "duration": duration or m[4]}


def on_repeat(n=30, days=30):
    """Your most-played songs of the last 30 days (finished = 1, half-heard = 0.5, replays and likes on top)."""
    since = int(time.time()) - days * 86400
    with rec.db() as c:
        rows = c.execute("""SELECT video_id, MAX(title), MAX(artist), MAX(album), MAX(duration),
                                   SUM(CASE event WHEN 'complete' THEN 1.0 WHEN 'partial' THEN 0.5 ELSE 0 END) s
                            FROM plays WHERE ts>=? AND user=? AND video_id IS NOT NULL GROUP BY video_id
                            HAVING s >= 1 ORDER BY s DESC, MAX(ts) DESC LIMIT ?""", (since, rec.me(), n)).fetchall()
        return [_song(c, *r[:5]) for r in rows]


def forgotten(n=30, quiet_days=60):
    """Songs you loved (liked, or finished at least twice) that you haven't played for 2+ months."""
    cut = int(time.time()) - quiet_days * 86400
    with rec.db() as c:
        rows = c.execute("""SELECT p.video_id, MAX(p.title), MAX(p.artist), MAX(p.album), MAX(p.duration),
                                   SUM(p.event='complete') fin, MAX(p.ts) last
                            FROM plays p WHERE p.user=? AND p.video_id IS NOT NULL GROUP BY p.video_id
                            HAVING last < ? AND (fin >= 2 OR p.video_id IN
                                   (SELECT video_id FROM prefs WHERE user=? AND pref=1))
                            ORDER BY fin DESC, last DESC LIMIT ?""", (rec.me(), cut, rec.me(), n)).fetchall()
        out = [_song(c, *r[:5]) for r in rows]
        played = {r[0] for r in c.execute("SELECT DISTINCT video_id FROM plays WHERE user=? AND ts>=?", (rec.me(), cut))}
        for v, t, a in c.execute("SELECT video_id, title, artist FROM prefs WHERE user=? AND pref=1 AND ts < ?",
                                 (rec.me(), cut)):
            if len(out) < n and v not in played and v not in {s["videoId"] for s in out}:
                out.append(_song(c, v, t, a))                    # liked long ago, never played since
        return out


def played_ids():
    """Songs you (and the circle-mates whose taste blends into yours) already know: played or rated
    (❤️ / hidden, incl. the taste quiz). Not 'new to you'."""
    P = list(people.peers(rec.me()))
    ph = ",".join("?" * len(P))
    with rec.db() as c:
        return ({r[0] for r in c.execute(f"SELECT DISTINCT video_id FROM plays WHERE video_id IS NOT NULL AND user IN ({ph})", P)}
                | {r[0] for r in c.execute(f"SELECT video_id FROM prefs WHERE user IN ({ph})", P)})


# ---------- stats ----------

def _first_artist(a):
    import re
    return re.split(r",| feat\.? | ft\.? ", a or "")[0].strip()       # YouTube Music joins artists with ", "; "Minh Tốc & Lam" is one band


def stats(period="month", user=None):
    """period: 'YYYY-MM' / 'YYYY' / 'month' (this month) / 'year' / 'all'."""
    user = user or rec.me()
    lt = time.localtime()
    if period == "month":
        period = time.strftime("%Y-%m", lt)
    elif period == "year":
        period = time.strftime("%Y", lt)
    fmt = "%Y-%m" if len(period) == 7 else "%Y" if len(period) == 4 else None
    with rec.db() as c:
        rows = c.execute("SELECT ts, video_id, title, artist, played, duration, event, source FROM plays WHERE user=?",
                         (user,)).fetchall()
    rows = [r for r in rows if r[6] in ("complete", "partial") or r[7] == "lb"]
    months = sorted({time.strftime("%Y-%m", time.localtime(r[0])) for r in rows}, reverse=True)
    sel = [r for r in rows if not fmt or time.strftime(fmt, time.localtime(r[0])) == period]
    secs = sum((r[4] if r[4] is not None else (r[5] or 210)) for r in sel)
    arts, songs, hours, days = {}, {}, [0] * 24, {}
    for ts, vid, title, artist, played, dur, ev, src in sel:
        w = 1                                                    # every listen counts as one play (skips aren't here)
        a = _first_artist(artist)
        arts[a] = arts.get(a, 0) + w
        k = vid or f"{rec.norm(title)}|{rec.norm(a)}"
        s = songs.setdefault(k, {"videoId": vid, "title": title, "artist": artist, "plays": 0})
        s["plays"] += w
        hours[time.localtime(ts).tm_hour] += (played or dur or 210) / 60
        d = time.strftime("%F", time.localtime(ts)); days[d] = days.get(d, 0) + 1
    timeline = []
    for m in sorted(months)[-12:]:
        mr = [r for r in rows if time.strftime("%Y-%m", time.localtime(r[0])) == m]
        ma = {}
        for r in mr:
            ma[_first_artist(r[3])] = ma.get(_first_artist(r[3]), 0) + 1
        timeline.append({"month": m, "minutes": round(sum((r[4] if r[4] is not None else (r[5] or 210)) for r in mr) / 60),
                         "top_artist": max(ma, key=ma.get) if ma else None})
    top_songs = sorted(songs.values(), key=lambda s: -s["plays"])[:15]
    with rec.db() as c:
        for s in top_songs:
            if s["videoId"]:
                m = _meta(c, s["videoId"])
                s["thumb"] = (m and m[3]) or f"https://i.ytimg.com/vi/{s['videoId']}/hqdefault.jpg"
    return {"period": period, "months": months, "minutes": round(secs / 60), "plays": len(sel),
            "artists_count": len(arts), "songs_count": len(songs), "days_listened": len(days),
            "top_artists": [{"name": a, "plays": int(v)} for a, v in sorted(arts.items(), key=lambda x: -x[1])[:15]],
            "top_songs": top_songs, "hours": [round(h) for h in hours], "timeline": timeline}


def together(circle=None):
    """What a circle's members love: artists at least two of them play (ranked by how many, then by the smallest
    share among them) and songs at least two of them liked / finished. Default circle: your first with 2+ people."""
    mine = people.circles_of(rec.me())
    cid = circle if circle in mine else next((k for k, v in mine.items() if len(v.get("members", [])) > 1), None)
    if not cid:
        return {"circle": None, "members": [], "artists": [], "songs": []}
    members = mine[cid]["members"]
    with rec.db() as c:
        def arts(u):
            d = {}
            for a, ev in c.execute("SELECT artist, event FROM plays WHERE user=? AND event IN ('complete','partial')", (u,)):
                k = _first_artist(a); d[k] = d.get(k, 0) + (1 if ev == "complete" else 0.5)
            for (a,) in c.execute("SELECT artist FROM prefs WHERE user=? AND pref=1", (u,)):
                k = _first_artist(a); d[k] = d.get(k, 0) + 2
            tot = sum(d.values()) or 1
            return {k: v / tot for k, v in d.items()}

        def loved(u):
            s = {r[0] for r in c.execute("SELECT video_id FROM prefs WHERE user=? AND pref=1", (u,))}
            return s | {r[0] for r in c.execute("SELECT video_id FROM plays WHERE user=? AND event='complete' "
                                                "AND video_id IS NOT NULL", (u,))}
        A = {u: arts(u) for u in members}
        L = {u: loved(u) for u in members}
        names = set().union(*A.values()) if A else set()
        shared = []
        for k in names:
            who = [u for u in members if k in A[u]]
            if len(who) >= 2:
                shared.append((len(who), min(A[u][k] for u in who), k, who))
        shared.sort(key=lambda x: (-x[0], -x[1]))
        counts = {}
        for u in members:
            for v in L[u]:
                counts[v] = counts.get(v, 0) + 1
        songs = []
        for v, n in sorted(counts.items(), key=lambda x: -x[1]):
            if n < 2 or len(songs) >= 30:
                continue
            m = _meta(c, v)
            if m:
                songs.append({**_song(c, v, m[0], m[1]), "album": f"loved by {n} of {len(members)}"})
    return {"circle": cid, "circle_name": mine[cid].get("name", cid),
            "circles": [{"id": k, "name": v.get("name", k)} for k, v in mine.items() if len(v.get("members", [])) > 1],
            "members": [{"user": u, "name": people.name(u)} for u in members],
            "artists": [{"name": k, "people": [people.name(u) for u in who], "share": round(m * 100)} for _, m, k, who in shared[:15]],
            "songs": songs}


# ---------- settings ----------

def setting(key, default=None, user=None):
    with rec.db() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (f"set:{user or rec.me()}:{key}",)).fetchone()
    return json.loads(r[0]) if r else default


def set_setting(key, value, user=None):
    with rec.db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (f"set:{user or rec.me()}:{key}", json.dumps(value)))
