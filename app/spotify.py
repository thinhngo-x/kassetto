"""Old Spotify listening history (Spotify's "Extended streaming history" export), kept apart from ytm's plays.

It is old (mostly 2019-2022), so it never drives today's taste on its own:
  * search: songs played >= 2x show up under "From your library" (matched to YouTube Music on demand);
  * taste: a small, capped boost (<= one recent finished play) ONLY for artists you already play in ytm,
    never a new artist (switch: setting `spotify_prior`, Stats -> Spotify years);
  * Forgotten favourites: <= 3 songs played >= 30x, rotating weekly;
  * stats: "Spotify years".
Import: `docker compose exec -T ytm python spotify.py import <user> < rows.json` (podcasts, incognito plays and
plays < 30 s are dropped before; only ts/title/artist/album/ms are stored, no IPs or devices).
Matches to YouTube Music are cached in cf_map under `sp:<title>|<artist>` (video id NULL = no confident match).
"""
import difflib, json, math, random, re, sys, time

import recommend as rec

MIN_MS = 30_000
_C = {"ts": 0, "user": None, "hours": {}}


def init():
    with rec.db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS spotify_plays(user TEXT, ts INTEGER, title TEXT, artist TEXT, album TEXT, ms INTEGER,
            PRIMARY KEY(user, ts, title));
        CREATE INDEX IF NOT EXISTS spotify_plays_k ON spotify_plays(user, artist, title);
        """)


def key(title, artist):
    return f"sp:{rec.norm(title)}|{rec.norm(artist)}"


def import_rows(rows, user):
    """rows = Spotify's JSON entries. -> (kept, dropped)."""
    init()
    keep = []
    for r in rows:
        t, a = r.get("master_metadata_track_name"), r.get("master_metadata_album_artist_name")
        if not t or not a or r.get("incognito_mode") or (r.get("ms_played") or 0) < MIN_MS:
            continue
        ts = int(time.mktime(time.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone)
        keep.append((user, ts, t, a, r.get("master_metadata_album_album_name"), int(r["ms_played"])))
    with rec.db() as c:
        c.executemany("INSERT OR IGNORE INTO spotify_plays VALUES(?,?,?,?,?,?)", keep)
    return len(keep), len(rows) - len(keep)


def has(user):
    try:
        with rec.db() as c:
            return bool(c.execute("SELECT 1 FROM spotify_plays WHERE user=? LIMIT 1", (user,)).fetchone())
    except Exception:
        return False


def artist_hours(user):
    """{normalised artist: hours} (cached 10 min)."""
    if _C["user"] == user and time.time() - _C["ts"] < 600:
        return _C["hours"]
    h = {}
    try:
        with rec.db() as c:
            for a, ms in c.execute("SELECT artist, SUM(ms) FROM spotify_plays WHERE user=? GROUP BY artist", (user,)):
                for x in rec.split_artists(a):
                    h[x] = h.get(x, 0) + ms / 3.6e6
    except Exception:
        pass
    _C.update(ts=time.time(), user=user, hours=h)
    return h


def prior(aff, user):
    """Boost artists you ALREADY like in ytm by your old Spotify hours: +0.25·ln(1+h), capped at 1.0
    (about one recent finished play). Artists ytm hasn't seen you play get nothing."""
    import library
    if not library.setting("spotify_prior", True, user=user):
        return aff
    hours = artist_hours(user)
    for a in [a for a, v in aff.items() if v > 0 and a in hours]:
        aff[a] += min(1.0, 0.25 * math.log1p(hours[a]))
    return aff


def _songs(user, min_plays):
    with rec.db() as c:
        rows = c.execute("""SELECT title, artist, MAX(album), COUNT(*) n, SUM(ms), MAX(ts) FROM spotify_plays
                            WHERE user=? GROUP BY lower(title), lower(artist) HAVING n >= ? ORDER BY n DESC""",
                         (user, min_plays)).fetchall()
        maps = {k: v for k, v in c.execute("SELECT mbid, video_id FROM cf_map WHERE mbid LIKE 'sp:%'")}
    return [{"title": t, "artist": a, "album": al or "", "plays": n, "hours": ms / 3.6e6, "last": last,
             "key": key(t, a), "videoId": maps.get(key(t, a)), "tried": key(t, a) in maps} for t, a, al, n, ms, last in rows]


def search(q, user, n=4):
    """Accent/typo-tolerant match on old Spotify songs played >= 2x -> [(score, song)] (videoId may be None)."""
    qt = rec._tokens(q)
    if not qt:
        return []
    out = []
    for s in _songs(user, 2):
        if s["tried"] and not s["videoId"]:
            continue                                               # no confident YouTube match
        hay = rec._tokens(f"{s['title']} {s['artist']}")
        hit = 0.0
        for t in qt:
            best = max((1.0 if h == t else 0.85 if h.startswith(t) and len(t) >= 2 else
                        difflib.SequenceMatcher(None, t, h).ratio() for h in hay), default=0)
            hit += best if best >= 0.85 else 0                   # stricter than ytm's own library: 5,000 old songs
        if hit / len(qt) >= 0.8:
            out.append((hit / len(qt) + 0.01 * min(5, s["plays"] / 10), s))
    return sorted(out, key=lambda x: -x[0])[:n]


def forgotten(user, exclude, k=3, pool=12):
    """Up to `pool` candidates (played >= 30x on Spotify), shuffled per ISO week; caller matches and keeps k."""
    cands = [s for s in _songs(user, 30) if not (s["tried"] and not s["videoId"]) and s["videoId"] not in exclude]
    random.Random(time.strftime("%G-W%V") + user).shuffle(cands)
    return cands[:pool]


def _base(s):
    return rec.norm(re.sub(r"\s*[\(\[].*?[\)\]]|\s+-\s+.*$", "", s or ""))


def match(s, results):
    """Pick the YouTube Music song that is clearly this one (title >= 0.75 similar, same artist), else None."""
    want_t, want_a = _base(s["title"]), rec.norm(s["artist"])
    for r in results:
        if r.get("type") != "song" or not r.get("videoId"):
            continue
        ts = max(difflib.SequenceMatcher(None, want_t, _base(r.get("title"))).ratio(),
                 difflib.SequenceMatcher(None, rec.norm(s["title"]), rec.norm(r.get("title"))).ratio())
        arts = rec.norm(r.get("artist"))
        if ts >= 0.75 and want_a and (want_a in arts or difflib.SequenceMatcher(None, want_a, arts).ratio() >= 0.8):
            return r
    return None


def remember(s, r):
    rec.map_put(s["key"], r["videoId"] if r else None, s["title"], s["artist"])


def stats(user):
    with rec.db() as c:
        rows = c.execute("SELECT ts, title, artist, ms FROM spotify_plays WHERE user=?", (user,)).fetchall()
    if not rows:
        return None
    years, arts = {}, {}
    for ts, t, a, ms in rows:
        y = time.strftime("%Y", time.localtime(ts))
        Y = years.setdefault(y, {"year": y, "plays": 0, "ms": 0, "a": {}})
        Y["plays"] += 1; Y["ms"] += ms; Y["a"][a] = Y["a"].get(a, 0) + ms
        arts[a] = arts.get(a, 0) + ms
    songs = _songs(user, 1)[:15]
    return {"from": min(years), "to": max(years), "plays": len(rows), "hours": round(sum(arts.values()) / 3.6e6),
            "artists_count": len(arts), "songs_count": len(_songs(user, 1)),
            "years": [{"year": y["year"], "plays": y["plays"], "hours": round(y["ms"] / 3.6e6, 1),
                       "top_artist": max(y["a"], key=y["a"].get)} for y in sorted(years.values(), key=lambda y: y["year"])],
            "top_artists": [{"name": a, "hours": round(ms / 3.6e6, 1)} for a, ms in sorted(arts.items(), key=lambda x: -x[1])[:15]],
            "top_songs": [{k: s[k] for k in ("title", "artist", "album", "plays", "videoId")} for s in songs]}


if __name__ == "__main__" and sys.argv[1:2] == ["import"]:
    rec.init()
    kept, dropped = import_rows(json.load(sys.stdin), sys.argv[2])
    print(f"imported {kept} plays for {sys.argv[2]} ({dropped} dropped)")
