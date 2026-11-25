"""First-run taste quiz: ~10 rounds of 3 songs, ❤️ the ones you like, so a new person doesn't start from nothing.

Rounds 1-4 spread wide: three songs from three different genres each. Later rounds adapt: two songs from radios of
what you liked (does the taste hold?) and one from a genre not shown yet (anything missed?). Every song shown goes
through recsys.rank() (ctx "quiz"), so it is logged as an impression with its features; a ❤️ is a real like (prefs,
taste, a learning step), a song shown but not picked is a weak "passed over" outcome for the ranker only (it doesn't
count against the artist: in a quiz you pick one of three).
"""
import random
import re
import time

import recommend as rec
from aiohttp import web

from .catalogue import radio
from .common import YT, clean, item, log, off

ROUNDS = 10
WIDE = 4                                                         # rounds that only explore
GENRES = ["pop hits", "indie rock", "hip hop", "r&b soul", "electronic dance", "house music", "techno", "jazz",
          "classical piano", "lofi beats", "metal", "punk rock", "folk acoustic", "country", "latin pop", "reggaeton",
          "afrobeats", "k-pop", "j-pop", "bossa nova", "reggae", "blues", "ambient", "singer-songwriter",
          "french chanson", "bollywood", "funk disco", "trap", "orchestral film score", "synthwave"]
QUIZ = {}                                                        # user -> {"genres", "liked", "shown", "artists", "ts"}
# a quiz needs songs, not hour-long mixes or compilations
NOT_A_SONG = re.compile(r"\bmix\b|mixtape|compilation|playlist|\bhours?\b|\bbest of\b|\btop \d+|\d+ (songs|hits)|"
                        r"\bvol\.? ?\d|relaxing|sleep|study music|\bfull album\b|nonstop|medley", re.I)


def songlike(s):
    d = s.get("duration") or 0
    return 90 <= d <= 480 and not NOT_A_SONG.search(f"{s.get('title', '')} {s.get('artist', '')}")


def _artist(s):
    return (rec.split_artists(s.get("artist")) or [""])[0]


def _state():
    u = rec.me()
    st = QUIZ.get(u)
    if not st or time.time() - st["ts"] > 3 * 3600:              # a quiz left half-way restarts later
        st = QUIZ[u] = {"genres": random.sample(GENRES, len(GENRES)), "liked": [], "shown": set(), "artists": set(),
                        "ts": time.time()}
    st["ts"] = time.time()
    return st


async def _genre_songs(genre):
    res = await off(YT.search, genre, filter="songs", limit=20)
    songs = [x for x in clean(item(r) for r in res) if x.get("type") == "song" and songlike(x)]
    await off(rec.track_meta_put, songs)
    return songs


async def _pick(st, sources, ctx="quiz"):
    """One song through the real ranker (features + impression logged): not shown before, by an artist not shown
    before, and a song rather than a mix."""
    lists = [[s for s in lst if s["videoId"] not in st["shown"] and _artist(s) not in st["artists"] and songlike(s)]
             for lst in sources]
    lists = [lst for lst in lists if lst]
    if not lists:
        return None
    picks = await off(rec.rank, [], [], [], set(st["shown"]), 1, [(lst, 0.8, "discovery") for lst in lists],
                      time.localtime().tm_hour, False, ctx)
    if not picks:
        return None
    st["shown"].add(picks[0]["videoId"]); st["artists"].add(_artist(picks[0]))
    return {**picks[0], "auto": False}


async def api_quiz(req):
    """GET ?round=N -> {round, total, songs: [3]}. POST {shown: [ids], liked: [ids]}: the answers of a round."""
    st = _state()
    if req.method == "POST":
        b = await req.json()
        liked = [v for v in b.get("liked", []) if v in st["shown"]]
        meta = {}
        with rec.db() as c:
            for v in liked:
                r = c.execute("SELECT title, artist, duration FROM tracks WHERE video_id=?", (v,)).fetchone()
                meta[v] = {"title": r[0], "artist": r[1], "duration": r[2]} if r else {}
        for v in liked:
            await off(rec.record, {"videoId": v, **meta[v], "event": "like", "why": None})
        for v in b.get("shown", []):
            if v in st["shown"] and v not in liked:
                await off(rec.learn.outcome, v, "pass")          # the ranker only: no penalty on the artist
        st["liked"] += liked
        return web.json_response({"liked": len(st["liked"])})
    n = max(1, min(ROUNDS, int(req.query.get("round", 1))))
    songs = []
    try:
        if n <= WIDE or not st["liked"]:
            for _ in range(3):                                   # three genres, one song each
                while st["genres"] and len(songs) < 3:
                    s = await _pick(st, [await _genre_songs(st["genres"].pop())])
                    if s:
                        songs.append(s); break
        else:
            seeds = random.sample(st["liked"], min(2, len(st["liked"])))
            radios = [r for r in [await radio(v, 25) for v in seeds] if r]
            for _ in range(2):
                s = await _pick(st, [r[1:] for r in radios])     # a radio starts with its seed
                if s:
                    songs.append(s)
            while st["genres"] and len(songs) < 3:
                s = await _pick(st, [await _genre_songs(st["genres"].pop())])
                if s:
                    songs.append(s)
    except Exception as e:
        log("quiz round failed:", repr(e)[:150])
    return web.json_response({"round": n, "total": ROUNDS, "songs": songs[:3]})


async def api_quiz_needed(req):
    """Does this person still start from nothing? (the Home page offers the quiz then)"""
    with rec.db() as c:
        plays = c.execute("SELECT COUNT(*) FROM plays WHERE user=?", (rec.me(),)).fetchone()[0]
        likes = c.execute("SELECT COUNT(*) FROM prefs WHERE user=? AND pref > 0", (rec.me(),)).fetchone()[0]
    return web.json_response({"needed": plays < 5 and likes < 3, "plays": plays, "likes": likes})
