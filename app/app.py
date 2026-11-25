#!/usr/bin/env python3
"""ytm: a small self-hosted YouTube Music client (search + play in one page, no ads).

Meant to run behind a sign-in proxy (e.g. Authelia, Authentik) that sets Remote-User. Catalogue / search / radio / home feed via ytmusicapi
(unauthenticated); audio = the plain m4a stream found by yt-dlp, proxied by this server (Range/seek supported),
so the browser never loads YouTube's player or ads. Plays are scrobbled to ListenBrainz (LISTENBRAINZ_USER_TOKEN)
and feed the weekly Explo recommendations. "Play on Nest" hands the queue to castplayer.py (Chromecast / Nest).
"""
import asyncio, collections, sqlite3, contextvars, heapq, itertools, json, os, random, re, struct, subprocess, sys, threading, time, urllib.parse, urllib.request, zlib

from aiohttp import ClientSession, ClientTimeout, web
import yt_dlp
from ytmusicapi import YTMusic

import recommend as rec
import library as lib
import people
import spotify as sp
import phonetics

HERE = os.path.dirname(os.path.abspath(__file__))
MUSIC_PY = os.environ.get("MUSIC_PY", "/app/castplayer.py")
YT = YTMusic(language=os.environ.get("YTM_LANGUAGE", "en"), location=os.environ.get("YTM_LOCATION", "FR"))
YT_VN = YTMusic(language="en", location="VN")      # Vietnam home feed + charts (ytmusicapi has no 'vi' UI language)
VN_CHARS = re.compile("[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.I)


def norm_title(t):
    return re.sub(r"\W+", "", (t or "").lower())


def vietnamese(text):
    return bool(VN_CHARS.search(text or ""))
RADIO = {}                        # videoId -> (ts, [songs])  (1 h cache)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------- normalisation of ytmusicapi results ----------

def thumb(x, size=None):
    t = (x or {}).get("thumbnails") or (x or {}).get("thumbnail") or []
    if isinstance(t, dict):
        t = t.get("thumbnails") or []
    if not t:
        return None
    u = t[-1]["url"]
    if size and "lh3.googleusercontent.com" in u:              # ask for a square of the wanted size
        u = re.sub(r"=w\d+-h\d+.*$", f"=w{size}-h{size}-l90-rj", u)
    return u


def artists(x):
    a = x.get("artists") or []
    if isinstance(a, list):
        return ", ".join(i.get("name", "") for i in a if i.get("name"))
    return x.get("artist") or ""


def secs(x):
    if x.get("duration_seconds"):
        return int(x["duration_seconds"])
    d = x.get("duration") or x.get("length") or ""
    try:
        p = [int(v) for v in d.split(":")]
        return sum(v * 60 ** i for i, v in enumerate(reversed(p)))
    except ValueError:
        return None


def song(x, album=None, cover=None):
    if not x.get("videoId"):
        return None
    alb = x.get("album")
    return {"type": "song", "videoId": x["videoId"], "title": x.get("title") or "?", "artist": artists(x),
            "album": (alb.get("name") if isinstance(alb, dict) else alb) or album or "",
            "duration": secs(x), "thumb": thumb(x, 226) or cover}


def item(x):
    rt = x.get("resultType")
    if x.get("videoId") and rt in (None, "song", "video"):
        return song(x)
    bid = x.get("browseId") or ""
    if rt == "album" or bid.startswith("MPRE"):
        return {"type": "album", "id": bid, "title": x.get("title"), "sub": " · ".join(
            v for v in (artists(x), str(x.get("year") or "")) if v), "thumb": thumb(x, 226)}
    if rt == "artist" or (bid.startswith("UC") and not x.get("playlistId")):
        return {"type": "artist", "id": bid, "title": x.get("artist") or x.get("title"), "sub": "Artist",
                "thumb": thumb(x, 226)}
    pid = x.get("playlistId") or (bid[2:] if bid.startswith("VL") else None)
    if rt == "playlist" or pid:
        return {"type": "playlist", "id": pid or bid, "title": x.get("title"),
                "sub": x.get("author") if isinstance(x.get("author"), str) else artists(x) or (x.get("description") or "")[:60],
                "thumb": thumb(x, 226)}
    return None


def clean(lst):
    return [i for i in lst if i]


# ---------- API ----------

async def off(fn, *a, **k):
    ctx = contextvars.copy_context()                            # carries the current user into the worker thread
    return await asyncio.get_running_loop().run_in_executor(None, lambda: ctx.run(fn, *a, **k))


async def api_search(req):
    q = req.query.get("q", "").strip()
    f = req.query.get("filter", "songs")
    if not q:
        return web.json_response([])
    res = clean(item(x) for x in await off(YT.search, q, filter=None if f == "top" else f, limit=30))
    await off(rec.track_meta_put, [x for x in res if x.get("type") == "song"])
    if f in ("songs", "videos"):
        res = await off(rec.rerank_search, res, q)                  # taste-aware + covers/karaoke down + dedupe
    return web.json_response(res)


# ---------- search intelligence (/api/search2, /api/suggest2) ----------

SIMILAR_Q = re.compile(r"^(?:songs?|music|nhạc|bài(?: hát)?|chansons?)?\s*(?:like|similar to|giống|kiểu như|như|comme|style)\s+(.+)$", re.I)
MOOD = set("""sad buon chill relax relaxing happy vui love yeu tinh rock piano acoustic guitar study focus sleep ngu workout gym
rain mua dark epic calm soft energetic upbeat dance party romantic melancholic nostalgic morning sang night dem cafe jazz
lofi indie ballad rap edm cinematic orchestral triste douce doux heavy angry emotional dreamy ambient summer winter
nhe nhang tam trang hung phan quay tre sau lang man vibe vibes mood moody haunting""".split())


async def text_vec(q):
    try:
        async with app_http().post("http://ytm-embed:8099/text", json={"q": q}, timeout=ClientTimeout(total=4)) as r:
            return (await r.json()).get("vec")
    except Exception as e:
        log("text embedding unavailable:", repr(e)[:80]); return None


_APP = {}
# reference descriptions spanning moods / genres / instruments: their mean = the "text side" of CLAP's space
REF_PROMPTS = ["sad piano ballad", "happy upbeat pop song", "heavy metal with screaming vocals", "calm acoustic guitar",
               "energetic electronic dance music", "slow jazz with saxophone", "epic orchestral film score",
               "lo-fi hip hop beat", "rap with heavy bass", "romantic love song", "dark ambient drone",
               "folk song with banjo", "classical string quartet", "punk rock", "soul music with gospel choir",
               "reggae", "country music", "rainy day melancholic indie", "party anthem", "soft lullaby",
               "aggressive rock with distorted guitars", "dreamy synth pop", "traditional Vietnamese music",
               "french chanson", "male vocal ballad with piano", "female vocal indie folk", "instrumental hip hop",
               "cinematic trailer music", "acoustic cafe music", "80s synthwave"]
TEXT_MEAN = {}


async def text_mean():
    if "v" not in TEXT_MEAN:
        vecs = [v for v in await asyncio.gather(*[text_vec(p) for p in REF_PROMPTS]) if v]
        if len(vecs) < len(REF_PROMPTS) // 2:
            return None
        import numpy as np
        TEXT_MEAN["v"] = np.mean(np.asarray(vecs, dtype=np.float32), axis=0)
    return TEXT_MEAN["v"]


def app_http():
    return _APP["http"]


def vibe_query(q):
    toks = rec._tokens(q)
    return bool(toks) and sum(t in MOOD for t in toks) >= max(1, len(toks) // 3)


async def api_search2(req):
    """All-in-one search: top result, your library, songs (taste-ranked, cleaned), 'songs like X', vibe matches,
    artists / albums / playlists."""
    q = req.query.get("q", "").strip()[:200]
    if not q:
        return web.json_response({})
    m = SIMILAR_Q.match(q)
    like_of = m.group(1).strip() if m else None
    lex = like_of or q

    async def s(filter_, query):
        try:
            return clean(item(x) for x in await off(YT.search, query, filter=filter_, limit=25))
        except Exception as e:
            log("search failed:", filter_, repr(e)[:100]); return []

    vibe = vibe_query(q) and not like_of
    top, songs, artists, albums, playlists, library, vec = await asyncio.gather(
        s(None, lex), s("songs", lex), s("artists", lex), s("albums", lex), s("playlists", lex),
        library_with_spotify(lex, 6, 3), text_vec(q) if vibe else asyncio.sleep(0, None))
    await off(rec.track_meta_put, [x for x in songs + top if x.get("type") == "song"])   # names for later (vibe, library)
    songs = await off(rec.rerank_search, songs, lex)
    out = {"q": q, "library": library, "songs": songs[:20], "artists": artists[:12], "albums": albums[:12],
           "playlists": playlists[:12]}
    if like_of and songs:                                        # "songs like X": personal similar list
        seed = songs[0]
        sim = await radio(seed["videoId"])
        out["similar"] = {"seed": seed, "songs": await off(rec.rank, sim, [], [], {seed["videoId"]}, 25)}
    if vec:
        out["vibe"] = await off(rec.semantic, vec, 20, await text_mean())
    # top result: your library when it clearly matches > YouTube's own top pick (a song version preferred over
    # its music video) ; vibe queries have none (the vibe list leads)
    ql = rec.norm(lex)
    yt = top[0] if top else None
    if yt and yt.get("type") == "song" and songs and rec.norm(songs[0]["title"]).startswith(rec.norm(yt["title"])[:12]):
        yt = songs[0]
    lib = library[0] if library and rec.norm(library[0]["title"]).startswith(ql[: max(4, len(ql) // 2)]) else None
    named = next((a["title"] for a in artists[:3] if rec.norm(a["title"]) == ql), None)
    if named:                                                    # you searched an artist by name: interest signal
        await off(rec.record, {"event": "search_artist", "artist": named, "q": q})
    out["top"] = None if vibe else (lib or yt)
    out["intent"] = "similar" if like_of else "vibe" if vibe else "lookup"
    return web.json_response(out)


# ---------- old Spotify history (spotify.py) ----------

async def sp_resolve(songs, limit=4):
    """Spotify songs without a YouTube Music id: look up <= limit of them (cached, misses too); -> playable songs."""
    out, looked = [], 0
    for s in songs:
        if not s.get("videoId") and not s.get("tried") and looked < limit:
            looked += 1
            try:
                res = clean(item(x) for x in await off(YT.search, f"{s['artist']} {s['title']}", filter="songs", limit=5))
            except Exception as e:
                log("spotify match failed:", repr(e)[:100]); continue
            r = sp.match(s, res)
            await off(sp.remember, s, r)
            if r:
                await off(rec.track_meta_put, [r]); s["videoId"] = r["videoId"]; s["_r"] = r
        if s.get("videoId") and s["videoId"] not in {x["videoId"] for x in out}:
            m = s.get("_r") or {}
            out.append({"type": "song", "videoId": s["videoId"], "title": m.get("title") or s["title"],
                        "artist": m.get("artist") or s["artist"], "album": m.get("album") or s.get("album") or "",
                        "thumb": m.get("thumb") or f"https://i.ytimg.com/vi/{s['videoId']}/hqdefault.jpg",
                        "duration": m.get("duration"), "why": "from your Spotify years"})
    return out


async def library_with_spotify(q, n, lookups):
    mine = await off(rec.library_search, q, n)
    if len(mine) >= n:
        return mine
    hits = [s for _, s in await off(sp.search, q, rec.me(), n)]
    have = {x["videoId"] for x in mine}
    extra = await sp_resolve([s for s in hits if lookups or s.get("videoId")], lookups)
    return (mine + [x for x in extra if x["videoId"] not in have])[:n]


async def api_spotify(req):
    if req.method == "POST":
        d = await req.json()
        await off(lib.set_setting, "spotify_prior", bool(d.get("prior")))
    return web.json_response({"has": await off(sp.has, rec.me()), "prior": await off(lib.setting, "spotify_prior", True)})


async def api_suggest2(req):
    q = req.query.get("q", "").strip()[:100]
    if not q:
        return web.json_response({"suggestions": [], "library": []})
    sug, lib = await asyncio.gather(off(YT.get_search_suggestions, q), library_with_spotify(q, 3, 0), return_exceptions=True)
    return web.json_response({"suggestions": (sug if isinstance(sug, list) else [])[:7],
                              "library": lib if isinstance(lib, list) else []})


async def api_suggest(req):
    q = req.query.get("q", "").strip()
    if not q:
        return web.json_response([])
    try:
        res = await off(YT.get_search_suggestions, q)
    except Exception:
        res = []
    return web.json_response(res[:8])


HOME = {"ts": 0, "data": []}


async def api_home(req):
    """Vietnam sections first (charts + the Vietnamese parts of the VN home feed), then the regular feed."""
    if time.time() - HOME["ts"] < 1800 and HOME["data"]:
        return web.json_response(HOME["data"])

    async def get(fn, *a, **k):
        try:
            return await off(fn, *a, **k)
        except Exception as e:
            log("home source failed:", repr(e)[:120]); return None

    home, home_vn, charts = await asyncio.gather(get(YT.get_home, limit=8), get(YT_VN.get_home, limit=8),
                                                 get(YT_VN.get_charts, country="VN"))
    out = []
    if charts:
        top = clean(item({**x, "resultType": "playlist"}) for x in charts.get("videos") or [])
        top += clean(item({**x, "resultType": "artist"}) for x in (charts.get("artists") or [])[:20])
        if top:
            out.append({"title": "Top in Vietnam", "items": top})
    seen = set()
    for sec in home_vn or []:
        items = clean(item(x) for x in sec.get("contents") or [])
        if items and sum(vietnamese(i.get("title")) or vietnamese(i.get("artist") or i.get("sub")) for i in items) >= 0.4 * len(items):
            out.append({"title": f"{sec.get('title')} · Vietnam", "items": items[:20]}); seen.add(sec.get("title"))
    for sec in home or []:
        items = clean(item(x) for x in sec.get("contents") or [])
        if items:
            out.append({"title": sec.get("title"), "items": items[:20]})
    HOME.update(ts=time.time(), data=out)
    return web.json_response(out)


VN_FORYOU_BY = {}                                             # user -> {"ts", "items"}
VN_QUERIES = ["Indie Việt", "Nhạc Indie Việt chill", "Nhạc Việt buồn tâm trạng"]


async def vn_playlists():
    """Playlists around your Vietnamese favourites (artists with Vietnamese names, by how much you like them)."""
    VN_FORYOU = VN_FORYOU_BY.setdefault(rec.me(), {"ts": 0, "items": []})
    if time.time() - VN_FORYOU["ts"] < 6 * 3600 and VN_FORYOU["items"]:
        return VN_FORYOU["items"]
    aff, _, _ = await off(rec.taste)
    names = await off(rec.artist_names)                       # normalised -> original spelling
    vn = [names[a] for a, sc in sorted(aff.items(), key=lambda x: -x[1]) if sc > 0 and a in names and vietnamese(names[a])][:4]
    queries = [(a, f"based on {a}") for a in vn] + [(q, q) for q in VN_QUERIES]
    results = await asyncio.gather(*[off(YT.search, q, filter="playlists", limit=6) for q, _ in queries], return_exceptions=True)
    lists, seen = [], set()
    for (q, why), res in zip(queries, results):
        lst = []
        for x in [] if isinstance(res, Exception) else res:
            it = item({**x, "resultType": "playlist"})
            t = (it or {}).get("title") or ""
            if it and it["id"] not in seen and norm_title(t) not in seen:
                seen.update({it["id"], norm_title(t)}); lst.append({**it, "sub": f"Vietnamese · {why}"})
        lists.append(lst[:2] if q in vn else lst[:3])
    items = [x for row in itertools.zip_longest(*lists) for x in row if x]   # round-robin: artists and moods mixed
    VN_FORYOU.update(ts=time.time(), items=items[:16])
    return VN_FORYOU["items"]


async def radio(vid, limit=50):
    hit = RADIO.get(vid)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    r = await off(YT.get_watch_playlist, videoId=vid, radio=True, limit=limit)
    songs = clean(song(t) for t in r.get("tracks") or [])
    RADIO[vid] = (time.time(), songs)
    await off(rec.track_meta_put, songs)
    if len(RADIO) > 300:
        for k in sorted(RADIO, key=lambda k: RADIO[k][0])[:100]:
            RADIO.pop(k, None)
    return songs


async def api_radio(req):
    return web.json_response(await radio(req.query["videoId"]))


# ---------- personal autoplay (recommend.py) ----------

async def api_autoplay(req):
    seed = req.query["seed"]
    exclude = set(filter(None, req.query.get("exclude", "").split(","))) | {seed}
    _, _, anchors = await off(rec.taste)
    top = [a for a in anchors[:10] if a not in exclude]
    picked = random.sample(top, min(2, len(top))) if top else []
    aseed, *picked = await asyncio.gather(*[off(audio_version, v) for v in [seed, *picked]])
    exclude.add(aseed)                                  # its radio starts with the seed's own audio track

    async def safe(coro, default):
        try:
            return await asyncio.wait_for(coro, 12)
        except Exception as e:
            log("autoplay source failed:", repr(e)); return default

    async def cf():
        mbids = [m for m, _ in await off(rec.cf_recordings, 40)]
        if not mbids:
            return []
        random.shuffle(mbids)
        vids = await off(rec.cf_resolve, mbids[:15], YT.search)
        out = []
        for v in vids[:8]:
            r = await radio(v, 10)
            if r:
                out.append(r[0])                       # the recommended track itself (radio's first item)
        return out

    seed_r, cf_r, *anch = await asyncio.gather(safe(radio(aseed), []), safe(cf(), []),
                                               *[safe(radio(a, 25), []) for a in picked])
    picks = await off(rec.rank, seed_r, anch, cf_r, exclude, 25, None, time.localtime().tm_hour, True, "autoplay", aseed)
    if not picks:                                       # nothing left after filtering: plain radio
        picks = [{**t, "auto": True, "why": "similar"} for t in seed_r if t["videoId"] not in exclude][:25]
    return web.json_response(picks)


FORYOU_BY = {}                                                # user -> {"ts", "items"}


async def api_foryou(req):
    """The 'Made for you' shelf: your mix (from ytm's own taste model) + ListenBrainz playlists made for you."""
    FORYOU = FORYOU_BY.setdefault(rec.me(), {"ts": 0, "items": []})
    if time.time() - FORYOU["ts"] > 1800:
        items = []
        _, _, anchors = await off(rec.taste)
        if anchors:
            items.append({"type": "mix", "id": "mix", "title": "Your mix", "sub": "Based on what you play", "thumb": "/icon-512.png"})
        try:
            items += await ensure_daily()
        except Exception as e:
            log("daily mixes failed:", repr(e)[:150])
        try:
            items += [w for w in await ensure_weekly() if w.get("count")]
        except Exception as e:
            log("weekly lists failed:", repr(e)[:150])
        for p in await off(rec.lb_playlists):
            items.append({"type": "lbplaylist", "id": p["id"], "title": p["title"], "sub": "ListenBrainz · " + p["date"],
                          "thumb": "/icon-512.png"})
        FORYOU.update(ts=time.time(), items=items)
    try:
        vn = await vn_playlists()
    except Exception as e:
        log("vietnamese playlists failed:", repr(e)[:120]); vn = []
    return web.json_response([{"shelf": "Made for you", "items": FORYOU["items"]},
                              {"shelf": "Vietnamese for you", "items": vn}])


async def make_mix(n=40, exclude=frozenset(), radio_len=30):
    """Ranked radios of your favourites (1-2 per taste cluster). Used by Your mix, Discover weekly, wake-up music."""
    _, _, anchors = await off(rec.taste)
    seeds = (await off(rec.cluster_seeds, anchors)                  # 1-2 favourites from every taste cluster
             or random.sample(anchors[:16], min(4, len(anchors[:16]))))
    seeds = list(await asyncio.gather(*[off(audio_version, v) for v in seeds[:6]]))
    if not seeds:
        return []
    radios = await asyncio.gather(*[radio(v, radio_len) for v in seeds], return_exceptions=True)
    radios = [r for r in radios if isinstance(r, list)]
    picks = await off(rec.rank, [], radios, [], set(exclude), n, None, time.localtime().tm_hour, True, "mix")   # all seeds equal
    for t in picks:
        t.pop("auto", None)                                      # these are the mix itself, not autoplay extras
    return picks


async def api_mix(req):
    picks = await make_mix()
    if not picks:
        return web.json_response({"title": "Your mix", "sub": "Play and finish a few songs first", "tracks": []})
    return web.json_response({"title": "Your mix", "sub": "Based on what you play · new every time",
                              "thumb": picks[0]["thumb"] if picks else None, "tracks": picks})


SEARCH_SEM = asyncio.Semaphore(6)


async def match_track(key, title, artist):
    hit = await off(rec.map_get, key)
    if hit:
        return hit[0] and {"type": "song", "videoId": hit[0], "title": hit[1], "artist": hit[2]}
    async with SEARCH_SEM:
        try:
            res = await off(YT.search, f"{artist} {title}", filter="songs", limit=3)
        except Exception:
            res = []
    s = song(res[0]) if res else None
    await off(rec.map_put, key, s and s["videoId"], s and s["title"], s and s["artist"])
    return s


async def api_lbplaylist(req):
    title, tracks = await off(rec.lb_playlist, req.query["id"])
    found = await asyncio.gather(*[match_track(*t) for t in tracks])
    songs = []
    for f in found:
        if f and f.get("videoId"):
            songs.append(f if f.get("thumb") else {**f, "thumb": f"https://i.ytimg.com/vi/{f['videoId']}/hqdefault.jpg"})
    return web.json_response({"title": title, "sub": f"ListenBrainz · {len(songs)} of {len(tracks)} tracks found on YouTube Music",
                              "thumb": songs[0]["thumb"] if songs else None, "tracks": songs})


async def api_event(req):
    b = await req.json()
    ev = b.get("event")
    if ev == "search_artist" and b.get("q"):
        pass                                                      # a search that named an artist (no track)
    elif ev not in ("complete", "partial", "skip", "like", "unlike", "hide", "unhide", "dislike", *rec.SIGNALS) or not b.get("videoId"):
        raise web.HTTPBadRequest(text="bad event")
    await off(rec.record, b)
    return web.json_response({"ok": True})


IMG_HOSTS = ("lh3.googleusercontent.com", "i.ytimg.com", "yt3.ggpht.com", "yt3.googleusercontent.com", "i9.ytimg.com")
IMG = {}


async def img(req):
    """Same-origin copy of a cover (Google hosts only) so the page can read its colours (canvas)."""
    u = req.query.get("u", "")
    host = urllib.parse.urlparse(u).hostname or ""
    if not u.startswith("https://") or host not in IMG_HOSTS:
        raise web.HTTPBadRequest(text="host not allowed")
    if u not in IMG:
        async with req.app["http"].get(u) as r:
            if r.status != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
                raise web.HTTPBadGateway()
            body = await r.read()
        if len(body) > 2 << 20:
            raise web.HTTPBadGateway()
        IMG[u] = (r.headers["Content-Type"], body)
        while len(IMG) > 200:
            IMG.pop(next(iter(IMG)))
    ct, body = IMG[u]
    return web.Response(body=body, content_type=ct, headers={"Cache-Control": "private, max-age=604800"})


# ---------- lyrics: YouTube Music (often time-synced) first, LRCLIB (lrclib.net, open, no key) as fallback ----------

LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)")


def _lyrics_ytm(vid):
    w = YT.get_watch_playlist(videoId=vid, limit=1)
    b = w.get("lyrics")
    if not b:
        return None
    l = YT.get_lyrics(b, timestamps=True)
    ls = l.get("lyrics")
    if isinstance(ls, list) and ls:
        lines = [{"t": round(x.start_time / 1000, 2), "text": x.text} for x in ls]
        return {"synced": True, "lines": lines, "source": re.sub(r"^Source:\s*", "", l.get("source") or "") or "YouTube Music"}
    if isinstance(ls, str) and ls.strip():
        return {"synced": False, "lines": [{"t": None, "text": x} for x in ls.splitlines()],
                "source": re.sub(r"^Source:\s*", "", l.get("source") or "") or "YouTube Music"}
    return None


VIDEO_TAGS = re.compile(r"\s*[\(\[【][^\)\]】]*(official|clip|video|vidéo|lyric|audio|mv|m/v|hd|4k|visualizer|visualiser|"
                        r"karaoke|vietsub|engsub|live session|performance)[^\)\]】]*[\)\]】]", re.I)


def _sim(a, b):
    import difflib
    return difflib.SequenceMatcher(None, rec.norm(a), rec.norm(b)).ratio()


def song_title(title, artist):
    """'Clou - Comme au cinéma [clip officiel]' + 'Clou' -> 'Comme au cinéma' (video titles -> the song title)."""
    t = VIDEO_TAGS.sub("", title or "").strip()
    t = re.sub(r"\s*[\(\[](feat|ft)\.?[^\)\]]*[\)\]]", "", t, flags=re.I).strip()
    arts0 = [rec.norm(a) for a in re.split(r",| & | x | feat\.? | ft\.? ", artist or "") if a.strip()]
    if " | " in t or " ｜ " in t:                              # "Artist | Song | Official MV"
        parts = [x.strip() for x in re.split(r" [|｜] ", t)]
        keep = [x for x in parts if x and not re.search(r"official|music video|lyric|audio|\bmv\b|vietsub|clip", x, re.I)
                and not any(a and (a == rec.norm(x) or a in rec.norm(x) and len(rec.norm(x)) - len(a) < 4) for a in arts0)]
        if keep:
            t = keep[0]
    if " - " in t:
        left, right = [x.strip() for x in t.split(" - ", 1)]
        arts = [rec.norm(a) for a in re.split(r",| & | x | feat\.? | ft\.? ", artist or "") if a.strip()]
        if any(a and (a in rec.norm(left) or rec.norm(left) in a) for a in arts):
            t = right                                          # "Artist - Song"
        elif any(a and a in rec.norm(right) for a in arts):
            t = left                                           # "Song - Artist"
        elif re.search(r"remaster|version|mix|edit|live|acoustic", right, re.I):
            t = left                                           # "Song - Remastered 2011"
    return t.strip(" -|") or title


def first_artist(artist):
    return re.split(r",| & | feat\.? | ft\.? ", artist or "")[0].strip()


# Version words: a music video is only exchanged for an audio track of the SAME version (a live / acoustic /
# remix video stays itself unless YouTube Music has that same version as an audio track).
VERSION_WORDS = {"live": "live", "en vivo": "live", "en directo": "live", "en concert": "live", "concert": "live", "in concert": "live", "trực tiếp": "live",
                 "acoustic": "acoustic", "acústico": "acoustic", "acoustique": "acoustic", "unplugged": "acoustic", "mộc": "acoustic",
                 "remix": "remix", "rmx": "remix", "mix": "mix", "edit": "edit", "cover": "cover", "piano": "piano",
                 "instrumental": "instrumental", "beat": "instrumental", "karaoke": "karaoke", "orchestral": "orchestral",
                 "symphonic": "orchestral", "acapella": "acapella", "a cappella": "acapella", "demo": "demo",
                 "session": "session", "sped up": "sped", "slowed": "slowed", "reverb": "slowed", "nightcore": "sped",
                 "8d": "8d", "lofi": "lofi", "lo-fi": "lofi", "mashup": "mashup", "version": "version", "ver.": "version"}
_VW = re.compile(r"(?<![\w])(" + "|".join(sorted(map(re.escape, VERSION_WORDS), key=len, reverse=True)) + r")(?![\w])", re.I)


def version_tags(title):
    t = re.sub(r"official (music )?video|official audio|video oficial|clip officiel|official mv", " ", (title or "").lower())
    return {VERSION_WORDS[m.lower()] for m in _VW.findall(t)}


AUDIO_OF = {}                     # videoId -> the audio-track id of the same song + version (or itself)


def audio_version(vid):
    """For radio seeds picked by ytm (autoplay, Your mix): YouTube Music's radio follows the seed's type (a music
    video seed -> ~all music videos, with intros / skits / video mixes; an audio-track seed -> 48/50 audio tracks,
    measured 2026-11-24). So a music-video seed is swapped for its audio track when one clearly matches: same
    title, artist, duration +-15 s and the same version words. What the user chose to play is never swapped."""
    if vid in AUDIO_OF:
        return AUDIO_OF[vid]
    out = vid
    try:
        w = (YT.get_watch_playlist(videoId=vid, limit=1).get("tracks") or [{}])[0]
        if w.get("videoType") not in (None, "MUSIC_VIDEO_TYPE_ATV") and song(w):
            s0 = song(w)
            t, a, tags = song_title(s0["title"], s0["artist"]), first_artist(s0["artist"]), version_tags(s0["title"])
            for x in YT.search(f"{a} {t}", filter="songs", limit=5)[:5]:
                c = song(x)
                if (c and _sim(song_title(c["title"], c["artist"]), t) >= 0.75
                        and any(_sim(a, p) >= 0.7 for p in re.split(r",| & ", c["artist"]))
                        and (not s0.get("duration") or not c.get("duration")          # videos add intros/outros/skits
                             or -90 <= c["duration"] - s0["duration"] <= 15)
                        and version_tags(c["title"]) == tags):
                    out = c["videoId"]
                    log(f"radio seed {vid} ({s0['title'][:40]}) -> audio track {out}")
                    break
    except Exception as e:
        log("audio_version", vid, str(e)[:100])
    AUDIO_OF[vid] = out
    if len(AUDIO_OF) > 2000:
        AUDIO_OF.clear()
    return out


VERSION_LABEL = {"live": "Live", "acoustic": "Acoustic", "remix": "Remix", "mix": "Mix", "edit": "Edit", "cover": "Cover",
                 "piano": "Piano", "instrumental": "Instrumental", "karaoke": "Karaoke", "orchestral": "Orchestral",
                 "acapella": "A cappella", "demo": "Demo", "session": "Session", "sped": "Sped up", "slowed": "Slowed",
                 "8d": "8D", "lofi": "Lo-fi", "mashup": "Mashup", "version": "Version"}
VERSIONS = {}                     # videoId -> (time, response)


def base_title(title, artist):
    """'In the End (Live In Texas)' -> 'In the End': the song itself, without any version / edition part."""
    return re.sub(r"\s*[\(\[【].*?[\)\]】]|\s+[-–]\s+.*$", "", song_title(title, artist)).strip() or title


def _versions(vid):
    """Every version YouTube Music has of a song: audio tracks + videos of the same base title by the same
    artist (labelled Original / Live / Acoustic / Remix / … / Music video), plus covers by other artists."""
    from concurrent.futures import ThreadPoolExecutor
    w = (YT.get_watch_playlist(videoId=vid, limit=1).get("tracks") or [{}])[0]
    s0 = song(w)
    if not s0:
        return {"title": "Other versions", "sub": "", "tracks": []}
    t, a = base_title(s0["title"], s0["artist"]), first_artist(s0["artist"])
    queries = [(f"{a} {t}", "songs"), (f"{a} {t}", "videos"), (f"{a} {t} live", "songs"),
               (f"{a} {t} acoustic", "songs"), (f"{t} cover", "songs"), (f"{a} {t} live", "videos")]
    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(lambda q: [(x, q[1]) for x in (YT.search(q[0], filter=q[1], limit=20) or [])], queries))
    seen, rows = {vid}, []
    for x, kind in (r for res in results for r in res):
        c = song(x)
        if not c or c["videoId"] in seen or _sim(base_title(c["title"], c["artist"]), t) < 0.8:
            continue
        seen.add(c["videoId"])
        same_artist = any(_sim(a, p) >= 0.7 for p in re.split(r",| & | x | feat\.? ", c["artist"]))
        tags = version_tags(c["title"] + " " + (c.get("album") or "")) - {"version"}
        upload = False
        if not same_artist:
            if "karaoke" in tags:
                continue
            if "cover" not in tags and rec.norm(a) and rec.norm(a) in rec.norm(c["title"]):
                upload = True                                   # "Song - Artist | Live" posted by someone else
            else:
                tags.add("cover")
        extra = [b.strip() for b in re.findall(r"[\(\[]([^\)\]]+)[\)\]]", c["title"])
                 if not re.match(r"(feat|ft|with)\b", b.strip(), re.I) and not VIDEO_TAGS.search(f"({b})")]
        label = (" · ".join(VERSION_LABEL[x] for x in sorted(tags)) if tags else
                 extra[0][:30] if extra and same_artist else "Music video" if kind == "videos" else "Original")
        if "cover" in tags:
            label = f"Cover by {first_artist(c['artist'])}" + (" · " + " · ".join(VERSION_LABEL[x] for x in sorted(tags - {"cover"})) if tags - {"cover"} else "")
        if upload:
            label = " · ".join([VERSION_LABEL[x] for x in sorted(tags)] + [f"uploaded by {first_artist(c['artist'])}"])
        rank = 0 if label == "Original" else 3 if label == "Music video" else 5 if "cover" in tags else 4 if upload else 1
        rows.append((rank, label, c))
    out, dup, extra_n = [], set(), {4: 0, 5: 0}                # ≤ 6 fan uploads, ≤ 6 covers
    for rank, label, c in sorted(rows, key=lambda r: r[0]):    # stable: search relevance within each group
        k = (label, rec.norm(c["artist"]), round((c.get("duration") or 0) / 4))      # same audio on several albums
        if k in dup or (rank >= 4 and extra_n[rank] >= 6):
            continue
        dup.add(k)
        if rank >= 4:
            extra_n[rank] += 1
        alb = c.get("album") or ""
        show_alb = alb and label != "Music video" and _sim(base_title(alb, c["artist"]), t) < 0.8 and rec.norm(alb) not in rec.norm(label)
        out.append({**c, "album": label + (f" · {alb}" if show_alb else "")})
    return {"title": t, "sub": f"Other versions · {s0['artist']}", "thumb": s0.get("thumb"),
            "tracks": out[:40]}


async def api_versions(req):
    vid = req.query.get("id", "")
    if not re.fullmatch(r"[\w-]{11}", vid):
        raise web.HTTPBadRequest()
    hit = VERSIONS.get(vid)
    if not hit or time.time() - hit[0] > 6 * 3600:
        hit = VERSIONS[vid] = (time.time(), await off(_versions, vid))
        if len(VERSIONS) > 200:
            VERSIONS.pop(next(iter(VERSIONS)))
    return web.json_response(hit[1])


def _lyrics_ytm_song(title, artist, duration):
    """Video without lyrics: use the official YouTube Music audio track of the same song, if it clearly matches."""
    t, a = song_title(title, artist), first_artist(artist)
    for x in YT.search(f"{a} {t}", filter="songs", limit=5)[:5]:
        s = song(x)
        if not s:
            continue
        ok_t = _sim(song_title(s["title"], s["artist"]), t) >= 0.75
        ok_a = any(_sim(a, p) >= 0.7 for p in re.split(r",| & ", s["artist"]))
        ok_d = not duration or not s.get("duration") or abs(s["duration"] - duration) <= 15
        if ok_t and ok_a and ok_d:
            r = _lyrics_ytm(s["videoId"])
            if r:
                return r
    return None


def _lyrics_lrclib(title, artist, duration):
    t, a = song_title(title, artist), first_artist(artist)
    q = urllib.parse.urlencode({"track_name": t, "artist_name": a})
    req = urllib.request.Request(f"https://lrclib.net/api/search?{q}", headers={"User-Agent": "ytm-selfhosted/1.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        res = json.load(r)
    good = []
    for x in res or []:                                       # only accept a result that is clearly this song
        st, sa = _sim(x.get("trackName"), t), _sim(x.get("artistName"), a)
        dd = abs((x.get("duration") or 0) - duration) if duration and x.get("duration") else 0
        if st >= 0.75 and sa >= 0.6 and dd <= 15:
            good.append((not x.get("syncedLyrics"), dd, -st - sa, x))
    if not good:
        return None
    best = sorted(good, key=lambda g: g[:3])[0][3]
    if best.get("syncedLyrics"):
        lines = []
        for ln in best["syncedLyrics"].splitlines():
            m = LRC_LINE.match(ln)
            if m:
                lines.append({"t": round(int(m.group(1)) * 60 + float(m.group(2)), 2), "text": m.group(3)})
        if lines:
            return {"synced": True, "lines": lines, "source": "LRCLIB"}
    if best.get("plainLyrics"):
        return {"synced": False, "lines": [{"t": None, "text": x} for x in best["plainLyrics"].splitlines()], "source": "LRCLIB"}
    return None


def _lyrics(vid, title, artist, duration):
    hit = rec.lyrics_get(vid)
    if hit is not None:
        return hit
    out = None
    for fn in (lambda: _lyrics_ytm(vid), lambda: _lyrics_ytm_song(title, artist, duration),
               lambda: _lyrics_lrclib(title, artist, duration)):
        try:
            r = fn()
        except Exception as e:
            log("lyrics source failed:", repr(e)[:120]); r = None
        if r and (r["synced"] or not out):
            out = r
            if r["synced"]:
                break
    out = out or {"synced": False, "lines": [], "source": None}
    rec.lyrics_put(vid, out)
    return out


async def api_lyrics(req):
    vid = req.query["videoId"]
    if not re.fullmatch(r"[\w-]{11}", vid):
        raise web.HTTPBadRequest()
    dur = req.query.get("duration")
    out = await off(_lyrics, vid, req.query.get("title", ""), req.query.get("artist", ""),
                    float(dur) if dur and dur.replace(".", "", 1).isdigit() else None)
    if out and out.get("lines"):
        try:                                                     # phonetics for Korean / Japanese / Chinese / ...
            roman = await off(phonetics.romanize, [ln.get("text") or "" for ln in out["lines"]])
            if roman:
                out = {**out, "lines": [{**ln, "roman": r} if r else ln for ln, r in zip(out["lines"], roman)]}
        except Exception as e:
            log("phonetics:", repr(e)[:100])
    return web.json_response(out)


async def api_me(req):
    return web.json_response(await off(people.public, rec.me()))


async def api_likes(req):
    return web.json_response(await off(rec.liked_tracks))


async def api_prefs(req):
    return web.json_response(await off(rec.prefs))


async def api_taste(req):
    return web.json_response(await off(rec.stats))


async def lb_sync_loop(app):
    while True:
        try:
            n = await off(rec.sync_listenbrainz)
            if n:
                log(f"listenbrainz: +{n} listens")
        except Exception as e:
            log("listenbrainz sync failed:", repr(e))
        await asyncio.sleep(1800)


async def api_album(req):
    a = await off(YT.get_album, req.query["id"])
    cover = thumb(a, 544)
    return web.json_response({"title": a.get("title"), "sub": " · ".join(v for v in (artists(a), str(a.get("year") or "")) if v),
                              "thumb": cover, "tracks": clean(song(t, a.get("title"), thumb(a, 226)) for t in a.get("tracks") or [])})


async def api_playlist(req):
    p = await off(YT.get_playlist, req.query["id"], limit=300)
    au = p.get("author")
    return web.json_response({"title": p.get("title"), "sub": au.get("name") if isinstance(au, dict) else (au or ""),
                              "thumb": thumb(p, 544), "tracks": clean(song(t) for t in p.get("tracks") or [])})


async def api_artist(req):
    a = await off(YT.get_artist, req.query["id"])
    songs = (a.get("songs") or {}).get("results") or []
    tracks = clean(song(t) for t in songs)
    sb = (a.get("songs") or {}).get("browseId")
    if sb:                                                      # the artist's full "Songs" playlist
        try:
            p = await off(YT.get_playlist, sb, limit=100)
            tracks = clean(song(t) for t in p.get("tracks") or []) or tracks
        except Exception:
            pass
    albums = clean(item({**x, "resultType": "album"}) for x in (a.get("albums") or {}).get("results") or [])
    singles = clean(item({**x, "resultType": "album"}) for x in (a.get("singles") or {}).get("results") or [])
    return web.json_response({"title": a.get("name"), "sub": "Artist", "thumb": thumb(a, 544),
                              "tracks": tracks, "albums": albums + singles})


# ---------- streams ----------

YDL = {"quiet": True, "no_warnings": True, "noprogress": True}
# Opus 251 (~130 kbps VBR, WebM) sounds clearly better than AAC 140 at the same size; the Nest plays it
# (tested 2026-11-24). Browsers that can't play Opus (some Safari versions) ask for ?aac=1 -> AAC copy.
FMT_OPUS = "251/bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio"
FMT_AAC = "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio"


CACHE = os.environ.get("YTM_CACHE", "/data/cache")
CACHE_MAX = int(os.environ.get("YTM_CACHE_MB", "3000")) << 20
DLS = {}                          # videoId -> Download (in progress or failed recently)


class Download:
    """yt-dlp downloads the track into the cache (its own downloader copes with YouTube's stream protection);
    the file is served to the browser while it is still being written."""
    def __init__(self, vid, aac=False):
        self.aac = aac
        self.vid, self.total, self.tmp, self.final, self.mime = vid, None, None, None, "audio/mp4"
        self.done = self.error = None
        self.started, self.prio = False, 2
        self.ready = threading.Event()                          # total size + file name known (or failed)
        self.t0 = time.time()

    def hook(self, d):
        if d.get("tmpfilename"):
            self.tmp = d["tmpfilename"]
            self.mime = "audio/webm" if ".webm" in self.tmp else "audio/mp4"     # known before it finishes
        self.total = self.total or d.get("total_bytes") or d.get("total_bytes_estimate")
        if d["status"] == "finished":
            self.final = d.get("filename")
        if self.tmp and self.total and os.path.exists(self.tmp):
            self.ready.set()

    def run(self):
        opts = {**YDL, "format": FMT_AAC if self.aac else FMT_OPUS, "outtmpl": {"default": f"{CACHE}/{self.vid}.%(ext)s"}, "progress_hooks": [self.hook],
                "http_chunk_size": 2 << 20, "retries": 3, "fragment_retries": 3, "continuedl": False}
        try:
            raw = take_resolved(self.vid)
            with yt_dlp.YoutubeDL(opts) as y:
                info = (y.process_ie_result(raw, download=True) if raw else
                        y.extract_info(f"https://www.youtube.com/watch?v={self.vid}", download=True))
            log(f"{'pre-resolved' if raw else 'cold'} {self.vid} audible after {time.time() - self.t0:.1f}s")
            self.mime = "audio/mp4" if info.get("ext") in ("m4a", "mp4") else "audio/webm"
            self.final = self.final or info.get("requested_downloads", [{}])[0].get("filepath")
            self.total = os.path.getsize(self.final)
            self.done = True
            log(f"cached {self.vid} {self.total >> 10} KiB in {time.time() - self.t0:.1f}s")
            threading.Thread(target=request_analysis, args=(self.vid,), daemon=True).start()
            prune_cache()
        except Exception as e:
            self.error = str(e)[:200]
            log("download failed", self.vid, self.error)
        finally:
            self.ready.set()


def request_analysis(vid):
    """ytm-embed measures loudness + silent edges of a freshly cached track (~1-2 s) -> table audio."""
    try:
        urllib.request.urlopen(urllib.request.Request("http://ytm-embed:8099/analyze", data=json.dumps({"vid": vid}).encode(),
                                                      headers={"Content-Type": "application/json"}), timeout=60).read()
    except Exception as e:
        log("analysis request failed", vid, str(e)[:100])


# Volume levelling: like YouTube / Spotify, loud masters are turned down to TARGET_LUFS; quieter ones play
# as they are (attenuation only, so no clipping and no Web Audio needed: the player just scales el.volume).
TARGET_LUFS = float(os.environ.get("YTM_TARGET_LUFS", "-14"))


async def api_audio(req):
    """?ids=a,b -> {vid: {gain, start, end}} for measured tracks + "default": the median gain (used until a
    fresh download has been measured, so the correction when it arrives is small)."""
    ids = [v for v in req.query.get("ids", "").split(",") if re.fullmatch(r"[\w-]{11}", v)][:20]

    def q():
        with rec.db() as c:
            rows = c.execute(f'SELECT video_id, lufs, start, "end" FROM audio WHERE video_id IN ({",".join("?" * len(ids))})',
                             ids).fetchall() if ids else []
            allv = sorted(r[0] for r in c.execute("SELECT lufs FROM audio WHERE lufs IS NOT NULL"))
        g = lambda l: round(max(0.1, min(1.0, 10 ** ((TARGET_LUFS - l) / 20))), 3)
        out = {v: {"gain": g(l) if l is not None else None, "start": st or 0, "end": en} for v, l, st, en in rows}
        out["default"] = g(allv[len(allv) // 2]) if allv else 0.6
        return out
    try:
        return web.json_response(await off(q))
    except sqlite3.OperationalError:                             # ytm-embed hasn't created the table yet
        return web.json_response({"default": 0.6})


def cached(vid, aac=False):
    """Cached file for a track: Opus (.webm) preferred, older AAC files still served; aac=True = AAC only."""
    for ext, mime in ((("m4a", "audio/mp4"), ("mp4", "audio/mp4")) if aac else
                      (("webm", "audio/webm"), ("m4a", "audio/mp4"), ("mp4", "audio/mp4"))):
        f = f"{CACHE}/{vid}.{ext}"
        if os.path.exists(f):
            return f, mime
    return None, None


def prune_cache():
    """LRU: drop the least recently played files until the cache fits CACHE_MAX; also remove leftovers of
    failed/aborted downloads (.part files untouched for an hour; in-progress ones are written to constantly)."""
    if not os.path.isdir(CACHE):
        return
    now = time.time()
    for f in os.listdir(CACHE):
        p = os.path.join(CACHE, f)
        try:
            if f.endswith((".part", ".ytdl")) and now - os.path.getmtime(p) > 3600:
                os.remove(p)
        except OSError:
            pass
    files = [(os.path.getmtime(p), os.path.getsize(p), p) for p in
             (os.path.join(CACHE, f) for f in os.listdir(CACHE)) if not p.endswith((".part", ".ytdl"))]
    size = sum(f[1] for f in files)
    for _, sz, p in sorted(files):
        if size <= CACHE_MAX:
            break
        os.remove(p); size -= sz


# Download scheduling: yt-dlp extraction is CPU-heavy (YouTube's JS challenge), so at most 3 run at once:
# 2 general workers (lowest priority number first) + 1 worker reserved for tracks someone is waiting to hear.
# Priorities: 0 = playing now (a /stream request), 1 = next in a queue, 2 = speculative.
JOBS, JOB_SEQ = [], itertools.count()
JOB_COND = threading.Condition()


def _worker(play_only):
    while True:
        with JOB_COND:
            while not JOBS or (play_only and JOBS[0][0] > 0):
                JOB_COND.wait()
            prio, _, key = heapq.heappop(JOBS)
            d = DLS.get(key)
            if not d or d.started:
                continue                                       # stale entry (already started / re-queued higher)
            d.started = True
            urgent = prio <= 1
            URGENT[0] += urgent
        try:
            d.run()
        finally:
            with JOB_COND:
                URGENT[0] -= urgent


for _i, _po in enumerate((True, False, False)):
    threading.Thread(target=_worker, args=(_po,), daemon=True, name=f"dl{_i}").start()


def start_download(vid, prio=2, aac=False):
    key = vid + "~aac" if aac else vid
    with JOB_COND:
        d = DLS.get(key)
        if d and not (d.error and time.time() - d.t0 > 60):    # reuse running/finished; retry a failure after 60 s
            if not d.started and prio < d.prio:                # someone now waits for it: move it up
                d.prio = prio
                heapq.heappush(JOBS, (prio, next(JOB_SEQ), vid)); JOB_COND.notify_all()
            return d
        d = DLS[key] = Download(vid, aac)
        d.prio = prio
        heapq.heappush(JOBS, (prio, next(JOB_SEQ), key))
        JOB_COND.notify_all()
        if len(DLS) > 200:
            for k in [k for k, v in DLS.items() if v.done][:100]:
                DLS.pop(k, None)
    return d


# Look-ahead resolving. YouTube makes non-Premium clients sit through the pre-roll ad server-side: the audio
# URLs 403 until the ad's (skip) time has passed (5-10 s; measured 2026-11-24), and yt-dlp sleeps that long
# before downloading, so a cold tap took ~9 s (3.3 s extraction + the ad wait + 0.2 s download). The countdown
# starts when the song is looked up, so songs the user is likely to tap (top search results, the first tracks of
# an album, a hovered row) are extracted ahead (process=False: formats + solved URLs, no download) by one
# background thread, newest request first; it yields while a download someone waits for is running.
# A later tap only selects the format and downloads (~0.3 s). URLs live ~6 h; kept 4 h, ≤ 60 entries.
RESOLVED, RESOLVING = {}, {}         # vid -> (time, raw info) / vid -> Event while being looked up
RESOLVE_TTL = 4 * 3600
RQ = collections.deque(maxlen=12)
RQ_COND = threading.Condition()
URGENT = [0]                         # downloads running at priority 0/1


def take_resolved(vid):
    ev = RESOLVING.get(vid)
    if ev:
        ev.wait(8)                   # being looked up right now: finishing it is faster than starting over
    t, raw = RESOLVED.pop(vid, (0, None))
    return raw if raw and time.time() - t < RESOLVE_TTL else None


def _resolver():
    while True:
        with RQ_COND:
            while not RQ:
                RQ_COND.wait()
            vid = RQ.pop()
        if cached(vid)[0] or vid in DLS or vid in RESOLVED:
            continue
        while URGENT[0] > 0:
            time.sleep(0.3)
        RESOLVING[vid] = threading.Event()
        try:
            with yt_dlp.YoutubeDL(YDL) as y:
                raw = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False, process=False)
            RESOLVED[vid] = (time.time(), raw)
            for k in sorted(RESOLVED, key=lambda k: RESOLVED[k][0])[:max(0, len(RESOLVED) - 60)]:
                RESOLVED.pop(k, None)
        except Exception as e:
            log("resolve failed", vid, str(e)[:120])
        finally:
            RESOLVING.pop(vid).set()


threading.Thread(target=_resolver, daemon=True, name="resolver").start()
threading.Thread(target=prune_cache, daemon=True, name="prune").start()   # also at startup


async def api_resolve(req):
    ids = [v for v in req.query.get("ids", "").split(",") if re.fullmatch(r"[\w-]{11}", v)][:6]
    with RQ_COND:
        for v in reversed(ids):      # ids[0] = most likely tap = looked up first
            if not cached(v)[0] and v not in DLS and v not in RESOLVED:
                RQ.append(v)
        RQ_COND.notify()
    return web.json_response({"ok": True})


async def api_prefetch(req):
    vid, aac = req.query["videoId"], req.query.get("aac") == "1"
    if re.fullmatch(r"[\w-]{11}", vid) and not cached(vid, aac)[0]:
        start_download(vid, 1, aac)                             # the client asks for the next track in its queue
    return web.json_response({"ok": True})


async def stream(req):
    vid = req.match_info["vid"]
    if not re.fullmatch(r"[\w-]{11}", vid):
        raise web.HTTPNotFound()
    aac = req.query.get("aac") == "1"
    path, mime = cached(vid, aac)
    if path:                                                    # complete file: aiohttp handles Range itself
        os.utime(path)
        return web.FileResponse(path, headers={"Content-Type": mime, "Cache-Control": "private, max-age=86400"})
    d = start_download(vid, 0, aac)                             # someone is waiting to hear this
    ok = await off(d.ready.wait, 45)
    if not ok or d.error or not (d.tmp or d.final):
        raise web.HTTPBadGateway(text=f"could not load this track: {d.error or 'timeout'}")
    if d.done:
        return await stream(req)
    total = d.total
    m = re.match(r"bytes=(\d*)-(\d*)", req.headers.get("Range", ""))
    start = int(m.group(1)) if m and m.group(1) else 0
    end = min(int(m.group(2)) if m and m.group(2) else total - 1, total - 1)
    resp = web.StreamResponse(status=206 if m else 200, headers={
        "Content-Type": d.mime, "Accept-Ranges": "bytes", "Cache-Control": "no-store",
        "Content-Length": str(end - start + 1), **({"Content-Range": f"bytes {start}-{end}/{total}"} if m else {})})
    pos, idle = start, 0.0
    try:
        await resp.prepare(req)
        with open(d.tmp, "rb") as f:                           # the fd survives yt-dlp's rename .part -> final
            while pos <= end:
                f.seek(pos)
                chunk = f.read(min(256 << 10, end - pos + 1))
                if chunk:
                    await resp.write(chunk); pos += len(chunk); idle = 0.0
                    continue
                if d.error or (d.done and pos >= os.fstat(f.fileno()).st_size):
                    break
                await asyncio.sleep(0.1); idle += 0.1
                if idle > 30:
                    break
    except (ConnectionError, asyncio.CancelledError, RuntimeError):   # the browser hung up (seek / skip): fine
        pass
    return resp


# ---------- ListenBrainz ----------

async def api_listen(req):
    b = await req.json()
    _, token, _ = await off(people.lb_account, rec.me())          # own account / the one you scrobble as / none
    if not token or not b.get("artist") or not b.get("title"):
        return web.json_response({"ok": False, "reason": "no token or metadata"})
    meta = {"artist_name": b["artist"], "track_name": b["title"],
            "additional_info": {"media_player": "ytm (self-hosted)", "submission_client": "ytm",
                                "music_service": "music.youtube.com",
                                "origin_url": f"https://music.youtube.com/watch?v={b.get('videoId', '')}"}}
    if b.get("album"):
        meta["release_name"] = b["album"]
    if b.get("duration"):
        meta["additional_info"]["duration_ms"] = int(b["duration"]) * 1000
    lt = "playing_now" if b.get("type") == "playing_now" else "single"
    listen = {"track_metadata": meta}
    if lt == "single":
        listen["listened_at"] = int(b.get("listened_at") or time.time())
    async with req.app["http"].post("https://api.listenbrainz.org/1/submit-listens",
                                    json={"listen_type": lt, "payload": [listen]},
                                    headers={"Authorization": f"Token {token}"}) as r:
        ok = r.status == 200
        if not ok:
            log("listenbrainz", r.status, (await r.text())[:200])
    return web.json_response({"ok": ok})


# ---------- Nest / Chromecast (via castplayer.py) ----------

def music(*args):
    r = subprocess.run([sys.executable, MUSIC_PY, *args], capture_output=True, text=True, timeout=60)
    return (r.stdout + r.stderr).strip()


NEST = {"cc": None}
NEST_LOCK = threading.Lock()


def fix_stale_status(mc):
    """pychromecast ignores a MEDIA_STATUS with an empty list, which is what the Nest sends when playback is
    stopped on the speaker / in Google Home: the old status (PLAYING) would stay forever. Reset it instead."""
    from pychromecast.controllers.media import MediaStatus
    orig = mc._process_media_status

    def proc(data):
        if not data.get("status"):
            mc.status = MediaStatus()
        orig(data)
    mc._process_media_status = proc
    return mc


def nest_cc():
    """One persistent Cast connection for status/seek (music.py's player keeps its own)."""
    import pychromecast
    with NEST_LOCK:
        cc = NEST["cc"]
        if cc is None or not cc.socket_client.is_connected:
            if cc is not None:
                try:
                    cc.disconnect(timeout=2)
                except Exception:
                    pass
            cc = pychromecast.get_chromecast_from_host((os.environ.get("NEST_IP", ""), 8009, None, None, None),
                                                       tries=2, timeout=8)
            cc.wait(timeout=8)
            fix_stale_status(cc.media_controller)
            NEST["cc"] = cc
        return cc


def _nest_status():
    try:
        st = json.load(open("/tmp/nestmusic.json"))
    except (OSError, ValueError):
        st = {}
    pid = st.get("pid")
    try:
        running = bool(pid) and (os.kill(pid, 0) is None)
    except OSError:
        running = False
    out = {"active": running, "sleep_at": NEST_SLEEP["at"] or None}
    if running and st.get("queue"):
        i = st.get("index", 0)
        out.update(index=i, videoId=st["queue"][i][0], title=st.get("title"))
    try:
        cc = nest_cc(); ms = cc.media_controller.status
        try:
            cc.media_controller.update_status()                  # the answer lands for the next poll
        except Exception:
            pass
        out.update(state=ms.player_state, position=ms.adjusted_current_time or 0, duration=ms.duration,
                   volume=cc.status.volume_level if cc.status else None)
    except Exception as e:
        out["error"] = str(e)[:100]
    return out


def _cast_ok():
    if not people.can_cast(rec.me()):
        raise web.HTTPForbidden(text="the speaker belongs to another circle")


async def api_nest_status(req):
    if not people.can_cast(rec.me()):
        return web.json_response({"active": False, "allowed": False})
    return web.json_response(await off(_nest_status))


def _nest_seek(t):
    cc = nest_cc(); cc.media_controller.seek(max(0.0, float(t)))


async def api_nest(req):
    _cast_ok()
    action = req.match_info["action"]
    b = await req.json() if req.can_read_body else {}
    if action == "play":
        tracks = [t for t in b.get("tracks", []) if re.fullmatch(r"[\w-]{11}", t.get("videoId", ""))][:100]
        if not tracks:
            raise web.HTTPBadRequest(text="tracks required")
        for k, t in enumerate(tracks[:2]):
            if not cached(t["videoId"])[0]:
                start_download(t["videoId"], k)                 # first track: now; second: next
        args = ["\t".join([t["videoId"], *(str(t.get(k) or "").replace("\t", " ") for k in ("title", "artist", "thumb"))])
                for t in tracks]
        out = await off(music, "play-ids", *args)
    elif action in ("next", "pause", "resume", "stop", "now"):
        out = await off(music, action)
    elif action == "seek":
        await off(_nest_seek, b.get("t", 0)); out = "ok"
    elif action == "vol":
        out = await off(music, "vol", str(max(0.0, min(1.0, float(b.get("v", 0.3))))))
    else:
        raise web.HTTPNotFound()
    return web.json_response({"out": out})


# ---------- your playlists (library.py) ----------

def _pl_detail(p):
    sub = ("Made by ytm, new every Monday" if p["kind"] == "weekly" else
           "Made by ytm, new every day · " + ((lib.setting("daily_subs", {}) or {}).get(p["id"]) or "your taste") if p["kind"] == "daily" else
           (f"Shared with {p['circle_name']}" if p["shared"] else "Your playlist") + ("" if p["mine"] else f" · by {people.name(p['owner'])}"))
    return {"title": p["name"], "sub": sub, "thumb": p["tracks"][0]["thumb"] if p["tracks"] else None,
            "tracks": p["tracks"], "meta": {k: p[k] for k in ("id", "owner", "shared", "circle", "circle_name", "kind", "mine")}}


async def api_myplaylists(req):
    if req.method == "POST":
        b = await req.json()
        try:
            pid = await off(lib.pl_create, b.get("name") or "New playlist", b.get("circle"))
        except lib.Denied as e:
            raise web.HTTPForbidden(text=str(e))
        if b.get("songs"):
            await off(lib.pl_add, pid, [x for x in b["songs"] if re.fullmatch(r"[\w-]{11}", x.get("videoId", ""))][:500])
        return web.json_response({"id": pid})
    return web.json_response(await off(lib.pl_list))


async def api_myplaylist(req):
    try:
        if req.method == "GET":
            if req.query.get("containing"):
                return web.json_response(await off(lib.pl_containing, req.query["containing"]))
            return web.json_response(_pl_detail(await off(lib.pl_get, req.query.get("id", ""))))
        action, b = req.match_info["action"], await req.json()
        pid = b.get("id", "")
        if action == "add":
            songs = [x for x in (b.get("songs") or []) if re.fullmatch(r"[\w-]{11}", x.get("videoId", ""))][:500]
            n = await off(lib.pl_add, pid, songs)
            await off(rec.track_meta_put, songs)
            return web.json_response({"added": n})
        if action == "remove":
            await off(lib.pl_remove, pid, b.get("videoId"))
        elif action == "move":
            await off(lib.pl_move, pid, b.get("videoId"), b.get("to", 0))
        elif action == "rename":
            await off(lib.pl_update, pid, b.get("name"))
        elif action == "share":                                    # {"circle": id} or {"circle": null} = private
            await off(lib.pl_update, pid, None, b.get("circle") or None)
        elif action == "delete":
            await off(lib.pl_delete, pid)
        else:
            raise web.HTTPNotFound()
        return web.json_response({"ok": True})
    except lib.Denied as e:
        raise web.HTTPForbidden(text=str(e))



async def api_concerts(req):
    """Written weekly by the concerts job (/data/concerts.json; Ticketmaster, needs TICKETMASTER_API_KEY; the job itself is not in the repo yet)."""
    try:
        d = json.load(open("/data/concerts.json"))
        today = time.strftime("%F")
        return web.json_response({"updated": d.get("updated"), "events": [e for e in d.get("events", []) if e.get("date", "") >= today]})
    except (OSError, ValueError):
        return web.json_response({"updated": None, "events": []})

# ---------- Daily Mixes ----------
# One mix per taste group (rec.daily_groups: the sound model's clusters, else Vietnamese / other), rebuilt once a
# day in the background (the previous day's mixes are served meanwhile): ~1 of 3 songs is one of your favourites
# from that group, the rest are new picks from radios of 3 of them, ranked by your taste. Stored as playlists
# kind 'daily', ids dm-<user>-<n>; the subtitle (its main artists) in setting daily_subs.
DAILY_BUILDING = set()


def _artists_line(songs, n=3):
    seen, keys = [], set()
    for t in songs:
        a = lib._first_artist(t.get("artist") or "")
        if a and rec.norm(a) not in keys:                       # "OSAD" / "Osad" = one artist
            keys.add(rec.norm(a)); seen.append(a)
    return ", ".join(seen[:n]) + (" and more" if len(seen) > n else "")


async def build_daily():
    u = rec.me()
    if u in DAILY_BUILDING:
        return
    DAILY_BUILDING.add(u)
    try:
        groups = (await off(rec.daily_groups))[:4]
        subs, made, used = {}, 0, set()
        everyone = {v for g in groups for v in g}                 # all groups' favourites
        for g in groups:
            seeds = random.sample(g[:8], min(3, len(g[:8])))
            seeds = list(await asyncio.gather(*[off(audio_version, v) for v in seeds]))
            radios = [r for r in await asyncio.gather(*[radio(v, 40) for v in seeds], return_exceptions=True) if isinstance(r, list)]
            # new picks only: not a favourite of any group, not already in an earlier mix; no global sources
            new = await off(rec.rank, [], radios, [], everyone | used, 27, None, time.localtime().tm_hour, False, "daily", seeds[0])
            def fam_songs():
                with rec.db() as c:
                    return [lib._song(c, v, None, None) for v in g[:14]]
            fam = await off(fam_songs)
            random.shuffle(fam)
            songs, seen = [], set()
            for i in range(max(len(new), len(fam) * 3)):        # new, new, one of yours, ...
                t = (fam[i // 3] if i % 3 == 2 and i // 3 < len(fam) else new.pop(0) if new else None)
                k = t and rec.norm(re.sub(r"\(.*?\)|\[.*?\]| - .*$", "", t.get("title") or "")) + "|" + rec.norm(lib._first_artist(t.get("artist") or ""))
                if t and t["videoId"] not in seen and k not in seen:  # one version of a song (video / audio track)
                    seen |= {t["videoId"], k}; t.pop("auto", None); songs.append(t)
            if len(songs) < 10:
                continue
            used |= {t["videoId"] for t in songs}
            made += 1
            pid = f"dm-{u}-{made}"
            await off(lib.pl_replace, pid, f"Daily Mix {made}", songs[:40], "daily")
            subs[pid] = _artists_line(fam + songs)
        for p in await off(lib.pl_list, "daily"):                # fewer groups than before: drop the extra mixes
            if p["owner"] == u and p["id"] not in subs:
                await off(lib.pl_drop, p["id"])
        await off(lib.set_setting, "daily_subs", subs)
        await off(lib.set_setting, "daily_day", time.strftime("%F"))
        FORYOU_BY.pop(u, None)
        log(f"daily mixes for {u}: {made} ({', '.join(subs.values())})")
    except Exception as e:
        log("daily mixes failed:", repr(e)[:150])
    finally:
        DAILY_BUILDING.discard(u)


async def ensure_daily():
    """Today's Daily Mixes for the 'Made for you' shelf; a stale day rebuilds in the background."""
    have = [p for p in await off(lib.pl_list, "daily") if p["owner"] == rec.me()]
    if await off(lib.setting, "daily_day") != time.strftime("%F"):
        task = asyncio.ensure_future(build_daily())
        if not have:                                             # the very first time: wait for it (~10 s)
            await asyncio.wait_for(asyncio.shield(task), 40)
            have = [p for p in await off(lib.pl_list, "daily") if p["owner"] == rec.me()]
    subs = await off(lib.setting, "daily_subs", {}) or {}
    return [{"type": "myplaylist", "id": p["id"], "title": p["name"], "sub": subs.get(p["id"]) or "Your daily mix",
             "thumb": p["thumb"] or "/icon-512.png", "count": p["count"]}
            for p in sorted(have, key=lambda p: p["id"]) if p["count"]]


# ---------- weekly generated playlists ----------
# Rebuilt once per ISO week, on the first visit from Monday on (frozen for the week, like Discover Weekly).
WEEKLY_LOCK = asyncio.Lock()
WEEKLY = (("discover", "Discover weekly", "New to you, picked from your taste"),
          ("repeat", "On repeat", "What you've played most this month"),
          ("forgotten", "Forgotten favourites", "Songs you loved and haven't played lately"))


async def ensure_weekly():
    u, week = rec.me(), time.strftime("%G-W%V")
    async with WEEKLY_LOCK:
        if await off(lib.setting, "weekly_week") != week:
            played = await off(lib.played_ids)
            lists = {"discover": [], "repeat": await off(lib.on_repeat), "forgotten": await off(lib.forgotten)}
            try:
                lists["discover"] = [t for t in await make_mix(30, exclude=played, radio_len=50) if t["videoId"] not in played]
            except Exception as e:
                log("discover weekly failed:", repr(e)[:120])
            try:                                                 # + up to 3 old Spotify favourites, spread out
                old = (await sp_resolve(await off(sp.forgotten, u, played), 6))[:3]
                for j, x in enumerate(old):
                    lists["forgotten"].insert(min(len(lists["forgotten"]), 2 + 5 * j), x)
            except Exception as e:
                log("spotify favourites failed:", repr(e)[:120])
            for key, name, _ in WEEKLY:
                await off(lib.pl_replace, f"wk-{u}-{key}", name, lists[key])
            await off(lib.set_setting, "weekly_week", week)
            log(f"weekly lists for {u} ({week}): " + ", ".join(f"{k} {len(v)}" for k, v in lists.items()))
    have = {p["id"]: p for p in await off(lib.pl_list, "weekly")}
    out = []
    for key, name, sub in WEEKLY:
        p = have.get(f"wk-{u}-{key}")
        if p:
            out.append({"type": "myplaylist", "id": p["id"], "title": name, "sub": sub if p["count"] else "Not enough listening yet",
                        "thumb": p["thumb"] or "/icon-512.png", "count": p["count"]})
    return out


async def api_weekly(req):
    return web.json_response(await ensure_weekly())


# ---------- stats ----------

async def api_stats(req):
    out = await off(lib.stats, req.query.get("period", "month"))
    if req.query.get("period") == "all":
        out["spotify"] = await off(sp.stats, rec.me())
    return web.json_response(out)


async def api_together(req):
    return web.json_response(await off(lib.together, req.query.get("circle")))


# ---------- people & circles (people.py; owner only) ----------

async def api_people(req):
    if rec.me() != people.owner():
        raise web.HTTPForbidden(text="only the owner manages people and circles")
    if req.method == "PUT":
        c = await req.json()
        known = set(people.cfg()["people"])
        circles = {}
        for cid, ci in (c.get("circles") or {}).items():
            cid = re.sub(r"[^a-z0-9_-]", "", cid.lower())[:30]
            if not cid:
                continue
            circles[cid] = {"name": str(ci.get("name") or cid)[:40], "members": [m for m in ci.get("members", []) if m in known],
                            "blend": max(0.0, min(1.0, float(ci.get("blend") or 0))),
                            "speaker": bool(ci.get("speaker")), "concerts": bool(ci.get("concerts"))}
        for flag in ("speaker", "concerts"):                        # at most one circle each
            first = next((k for k, v in circles.items() if v[flag]), None)
            for k in circles:
                circles[k][flag] = k == first
        cfg = people.cfg()
        for u, p in (c.get("people") or {}).items():
            if u in cfg["people"]:
                cfg["people"][u]["name"] = str(p.get("name") or u)[:40]
                sa = p.get("scrobble_as")
                if sa in cfg["people"] and sa != u:
                    cfg["people"][u]["scrobble_as"] = sa
                else:
                    cfg["people"][u].pop("scrobble_as", None)
        cfg["circles"] = circles
        await off(people.save, cfg)
    c = people.cfg()
    return web.json_response({"owner": c["owner"], "circles": c["circles"],
                              "people": {u: {"name": p.get("name"), "scrobble_as": p.get("scrobble_as"),
                                             "own_listenbrainz": bool((p.get("listenbrainz") or {}).get("user_env"))}
                                         for u, p in c["people"].items()}})


# ---------- sleep timer on the Nest (the page may be closed, so the server runs it) ----------
NEST_SLEEP = {"at": 0, "tok": 0}


def _nest_playing(cc):
    try:
        return cc.media_controller.status.player_state in ("PLAYING", "BUFFERING")
    except Exception:
        return False


def _nest_fade_stop(tok, fade=30):
    """Fade the Nest out over `fade` s, stop, put the volume back (so tomorrow isn't silent).
    Nothing playing any more (stopped on the speaker): do nothing; an idle Nest chimes at every volume change."""
    try:
        cc = nest_cc(); v0 = cc.status.volume_level if cc.status else 0.3
        if not _nest_playing(cc):
            log("sleep timer: the Nest had already stopped"); return
        for i in range(1, fade + 1):
            if NEST_SLEEP["tok"] != tok or not _nest_playing(cc):
                cc.set_volume(v0); return
            cc.set_volume(max(0.0, v0 * (1 - i / fade))); time.sleep(1)
        music("stop"); time.sleep(2); cc.set_volume(v0)
        log("sleep timer: Nest stopped")
    except Exception as e:
        log("sleep timer", repr(e)[:120])
    finally:
        if NEST_SLEEP["tok"] == tok:
            NEST_SLEEP["at"] = 0


def nest_sleep(minutes):
    NEST_SLEEP["tok"] += 1
    tok = NEST_SLEEP["tok"]
    if minutes <= 0:
        NEST_SLEEP["at"] = 0; return
    NEST_SLEEP["at"] = time.time() + minutes * 60

    def run():
        quiet = 0
        while NEST_SLEEP["tok"] == tok and time.time() < NEST_SLEEP["at"] - 30:
            time.sleep(1)
            if int(time.time()) % 10 == 0:                       # music stopped on the speaker: drop the timer
                try:
                    alive = nest_cc().media_controller.status.player_state in ("PLAYING", "BUFFERING", "PAUSED")
                    quiet = 0 if alive else quiet + 1
                except Exception:
                    pass
                if quiet >= 6:                                   # ~1 min with nothing playing
                    NEST_SLEEP["at"] = 0; log("sleep timer dropped: the Nest stopped"); return
        if NEST_SLEEP["tok"] == tok:
            _nest_fade_stop(tok)
    threading.Thread(target=run, daemon=True).start()


async def api_nest_sleep(req):
    _cast_ok()
    b = await req.json()
    m = float(b.get("minutes") or 0)
    if b.get("end_of_track"):
        st = await off(_nest_status)
        m = max(0.6, ((st.get("duration") or 0) - (st.get("position") or 0)) / 60 + 0.4)
    nest_sleep(m)
    return web.json_response({"at": NEST_SLEEP["at"]})


# ---------- morning routines (an optional external routines service) ----------
# The schedule (briefing + music) lives in a separate routines service (YTM_ROUTINES_URL); ytm only plays the music
# step (POST :8091/routine/play, key-checked) and shows the routines in Settings when YTM_ROUTINES_URL is set.
ROUTINES_URL = os.environ.get("YTM_ROUTINES_URL", "")
ROUTINES_KEY_FILE = os.environ.get("YTM_ROUTINES_KEY", "/run/routines.key")


def _routines_key():
    try:
        return open(ROUTINES_KEY_FILE).read().strip()
    except OSError:
        return ""


def _wake_key():
    sc = people.speaker_circle()
    return f"circle:{sc}" if sc else people.owner()


def _wake_runner():
    """Default taste for alarms without an owner: the owner if in the speaker's circle, else its first member."""
    sc = people.speaker_circle()
    m = (people.cfg()["circles"].get(sc) or {}).get("members", []) if sc else []
    return people.owner() if not m or people.owner() in m else m[0]


async def _source_tracks(a):
    token = rec.USER.set(a.get("by") or _wake_runner())        # the alarm follows its owner's taste / library
    try:
        k = a["source"]["kind"]
        if k == "liked":
            t = await off(rec.liked_tracks); random.shuffle(t); return t[:60]
        if k == "playlist":
            t = (await off(lib.pl_get, a["source"]["id"]))["tracks"]
            return t[:100]
        return await make_mix(40)
    except Exception as e:
        log("source tracks", repr(e)[:100]); return []
    finally:
        rec.USER.reset(token)


async def play_source(a, reason):
    """Play a source on the Nest: a = {source, by, volume, fade, minutes} (a routine's music step)."""
    st = await off(_nest_status)
    if st.get("active") and st.get("state") in ("PLAYING", "BUFFERING"):   # really playing (paused / stopped on the speaker = free)
        return "skipped: the Nest is already playing music"
    tracks = await _source_tracks(a)
    if not tracks:
        return "skipped: nothing to play"
    target, fade = a["volume"], a["fade"]

    def go():
        try:
            nest_cc().set_volume(0.04 if fade else target)
        except Exception as e:
            log("nest volume", repr(e)[:100])
        for k, t in enumerate(tracks[:2]):
            if not cached(t["videoId"])[0]:
                start_download(t["videoId"], k)
        music("play-ids", *["\t".join([t["videoId"], *(str(t.get(k) or "").replace("\t", " ") for k in ("title", "artist", "thumb"))])
                            for t in tracks])
        if fade:
            time.sleep(8)
            steps, last = max(1, fade), 0.04
            for i in range(1, steps + 1):                        # 4 % -> volume, one step a second
                try:
                    cc = nest_cc()
                    # stopped on the speaker, or the volume changed by hand: stop fading. Volume changes on an
                    # idle Nest each play its chime, so never touch it once the music is gone.
                    if not _nest_playing(cc) or abs((cc.status.volume_level or 0) - last) > 0.03:
                        log(f"fade-in ended early at {i}/{steps}"); break
                    last = 0.04 + (target - 0.04) * i / steps
                    cc.set_volume(last)
                except Exception:
                    pass
                time.sleep(1)
    asyncio.ensure_future(off(go))
    nest_sleep(float(a["minutes"]))
    log(f"nest music started ({reason}): {a['source']['kind']}, {len(tracks)} tracks, volume {target}, "
        f"fade {fade}s, stops after {a['minutes']} min")
    return "started"


async def routine_play(req):                                     # audio-only port, called by routines.py
    k = _routines_key()
    if not k or req.headers.get("X-Routines-Key", "") != k:
        raise web.HTTPForbidden()
    b = await req.json()
    src = b.get("source") or {"kind": "mix"}
    if src.get("kind") not in ("mix", "liked", "playlist") or (src["kind"] == "playlist" and not src.get("id")):
        raise web.HTTPBadRequest(text="bad source")
    a = {"source": src, "by": b.get("by") if b.get("by") in people.cfg()["people"] else _wake_runner(),
         "volume": max(0.05, min(0.8, float(b.get("volume", 0.25)))), "fade": max(0, min(600, int(b.get("fade", 60)))),
         "minutes": max(5, min(180, int(b.get("minutes", 30))))}
    return web.Response(text=await play_source(a, "routine"))


async def _routines(method, path, body=None):
    async with ClientSession(timeout=ClientTimeout(total=10)) as s:
        async with s.request(method, ROUTINES_URL + path, json=body, headers={"X-Routines-Key": _routines_key()}) as r:
            return r.status, await r.json(content_type=None)


async def api_routines(req):
    """Settings -> Routines (speaker circle). {available: false} when the routines service isn't set up / down."""
    if not ROUTINES_URL or not _routines_key():
        return web.json_response({"available": False})
    if req.method != "GET":
        _cast_ok()
    try:
        if req.method == "PUT":
            st, d = await _routines("PUT", "/routines", await req.json())
        elif req.method == "POST":
            st, d = await _routines("POST", f"/run/{req.match_info.get('rid', '')}")
        else:
            st, d = await _routines("GET", "/routines")
    except Exception as e:
        log("routines service:", repr(e)[:100])
        return web.json_response({"available": False, "error": "the routines service isn't answering"})
    if st >= 400:
        return web.json_response(d, status=st)
    sc = people.speaker_circle()
    return web.json_response({**d, "available": True, "allowed": people.can_cast(rec.me()),
                              "circle": (people.cfg()["circles"].get(sc) or {}).get("name") if sc else None,
                              "people": {u: people.name(u) for u in people.cfg()["people"]}})


# ---------- speaker tuning for the Nest (rendered by ytm-embed: ffmpeg) ----------
# The Nest plays files from the audio-only port, so it gets a version tuned for a small mono speaker: levelled
# to SPEAKER["lufs"], sub-bass removed, warmth / less harshness, the circle's bass & treble, gentle compression,
# proper mono mix (embed.py speaker_version, ~3-5 s per song). The next song is prepared while one plays; a song
# not downloaded yet plays as the original (tuned in the background for next time); a version not ready within
# 25 s falls back to the original. Setting belongs to the speaker's circle (like wake-up music).
SPEAKER_DEFAULT = {"on": True, "bass": 0, "treble": 0, "lufs": -14}
SPK_JOBS = {}


def speaker_cfg():
    return {**SPEAKER_DEFAULT, **(lib.setting("speaker", {}, user=_wake_key()) or {})}


async def speaker_version(vid, cfg):
    """-> path of the tuned file, or None (then the original plays)."""
    p = {"lufs": float(cfg["lufs"]), "bass": float(cfg["bass"]), "treble": float(cfg["treble"])}
    key = (vid, json.dumps(p, sort_keys=True))
    if key not in SPK_JOBS:
        async def job():
            t0 = time.time()
            if not cached(vid)[0]:
                d = start_download(vid, 0)
                while not cached(vid)[0] and not d.error and time.time() - t0 < 40:
                    await asyncio.sleep(0.2)
            if not cached(vid)[0]:
                return None
            async with app_http().post("http://ytm-embed:8099/speaker", json={"vid": vid, "p": p},
                                       timeout=ClientTimeout(total=120)) as r:
                f = (await r.json()).get("file")
            return os.path.join(CACHE, f) if f else None
        SPK_JOBS[key] = asyncio.ensure_future(job())
        if len(SPK_JOBS) > 300:
            for k in [k for k, v in SPK_JOBS.items() if v.done()][:150]:
                SPK_JOBS.pop(k, None)
    fut = SPK_JOBS[key]
    try:
        f = await asyncio.wait_for(asyncio.shield(fut), 25)
    except Exception as e:
        if fut.done():
            SPK_JOBS.pop(key, None)                               # failed: try again next time
        log("speaker version", vid, "not ready, playing the original:", repr(e)[:80])
        return None
    if not f or not os.path.exists(f):
        SPK_JOBS.pop(key, None)
        return None
    return f


async def nest_stream(req):
    """/stream/<id> on the audio-only port (= the Nest): the speaker-tuned version when switched on."""
    vid = req.match_info["vid"]
    if re.fullmatch(r"[\w-]{11}", vid):
        cfg = await off(speaker_cfg)
        if cfg["on"] and not cached(vid)[0]:                     # cold: play the original now, tune it for next time
            asyncio.ensure_future(speaker_version(vid, cfg))
        elif cfg["on"]:
            f = await speaker_version(vid, cfg)
            if f:
                os.utime(f)
                return web.FileResponse(f, headers={"Content-Type": "audio/webm", "Cache-Control": "private, max-age=86400"})
    return await stream(req)


async def api_speaker(req):
    if req.method == "POST":
        _cast_ok()
        b = await req.json()
        cur = await off(speaker_cfg)
        cur.update({k: b[k] for k in ("on", "bass", "treble") if k in b})
        cur["bass"] = max(-6.0, min(6.0, float(cur["bass"]))); cur["treble"] = max(-6.0, min(6.0, float(cur["treble"])))
        await off(lib.set_setting, "speaker", cur, _wake_key())
    return web.json_response({**await off(speaker_cfg), "allowed": people.can_cast(rec.me())})


# ---------- static / PWA ----------

def png_icon(n):
    """A plain app icon (accent square + white play triangle), drawn without image libraries."""
    bg, fg = (0xD9, 0x3A, 0x5B), (255, 255, 255)
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            u, v = x / n, y / n
            inside = 0.38 <= u <= 0.74 and abs(v - 0.5) <= 0.22 * (0.74 - u) / 0.36   # play triangle
            row += bytes(fg if inside else bg)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


ICONS = {}


async def icon(req):
    n = int(req.match_info["n"])
    if n not in (192, 512):
        raise web.HTTPNotFound()
    if n not in ICONS:
        ICONS[n] = png_icon(n)
    return web.Response(body=ICONS[n], content_type="image/png", headers={"Cache-Control": "max-age=604800"})


MANIFEST = {"name": "ytm", "short_name": "ytm", "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#0c0c10", "theme_color": "#0c0c10",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}


async def manifest(req):
    return web.json_response(MANIFEST, content_type="application/manifest+json")


# ---------- AutoEq headphone correction (experimental) ----------
# AutoEq (github.com/jaakkopasanen/AutoEq, MIT): measured correction curves for ~8,800 headphones, as a preamp +
# 10 parametric filters each. ytm fetches only AutoEq's public files (index weekly, a profile when picked), cached
# in /data/autoeq; nothing about the listener is sent. The player applies the filters with Web Audio.
AEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
AEQ_DIR = "/data/autoeq"
AEQ = {"ts": 0, "items": [], "by_id": {}}
_AEQ_LINE = re.compile(r"^- \[(.+?)\]\(\./(.+)\) by (.+?)(?: on (.+))?$")
_AEQ_FILT = re.compile(r"Filter \d+: ON (PK|LSC|HSC|LS|HS) Fc ([\d.]+) Hz Gain (-?[\d.]+) dB Q ([\d.]+)")


def _aeq_fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ytm-selfhosted/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode()


def aeq_index():
    if AEQ["items"] and time.time() - AEQ["ts"] < 7 * 86400:
        return AEQ
    os.makedirs(AEQ_DIR, exist_ok=True)
    f = f"{AEQ_DIR}/index.json"
    items = None
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < 7 * 86400:
        items = json.load(open(f))
    else:
        try:
            items = []
            for ln in _aeq_fetch(AEQ_RAW + "INDEX.md").splitlines():
                m = _AEQ_LINE.match(ln.strip())
                if m:
                    path = urllib.parse.unquote(m.group(2))
                    kind = next((k for k in ("in-ear", "over-ear", "earbud") if k in path.lower()), "")
                    items.append({"id": path, "name": m.group(1), "by": m.group(3) + (f" on {m.group(4)}" if m.group(4) else ""),
                                  "kind": kind})
            json.dump(items, open(f + ".tmp", "w")); os.replace(f + ".tmp", f)
        except Exception as e:
            log("autoeq index", str(e)[:120])
            items = json.load(open(f)) if os.path.exists(f) else []
    AEQ.update(ts=time.time(), items=items, by_id={i["id"]: i for i in items})
    return AEQ


async def api_eq_search(req):
    q = rec.norm(req.query.get("q", ""))
    idx = await off(aeq_index)
    if not q:
        return web.json_response({"total": len(idx["items"]), "items": []})
    words = q.split()
    hits = [i for i in idx["items"] if all(w in rec.norm(i["name"]) for w in words)]
    hits.sort(key=lambda i: (not rec.norm(i["name"]).startswith(q), len(i["name"]), i["name"]))
    return web.json_response({"total": len(idx["items"]), "items": hits[:40]})


async def api_eq_profile(req):
    pid = req.query.get("id", "")
    idx = await off(aeq_index)
    it = idx["by_id"].get(pid)
    if not it:
        raise web.HTTPNotFound(text="unknown headphone")
    import hashlib
    f = f"{AEQ_DIR}/{hashlib.sha1(pid.encode()).hexdigest()[:16]}.json"
    if os.path.exists(f):
        return web.json_response(json.load(open(f)))
    name = pid.rsplit("/", 1)[-1]
    url = AEQ_RAW + urllib.parse.quote(pid) + "/" + urllib.parse.quote(f"{name} ParametricEQ.txt")
    try:
        txt = await off(_aeq_fetch, url)
    except Exception as e:
        raise web.HTTPBadGateway(text=f"AutoEq: {str(e)[:80]}")
    pre = re.search(r"Preamp: (-?[\d.]+) dB", txt)
    kinds = {"PK": "peaking", "LSC": "lowshelf", "LS": "lowshelf", "HSC": "highshelf", "HS": "highshelf"}
    filters = [{"type": kinds[t], "f": float(fc), "gain": float(g), "q": float(q)} for t, fc, g, q in _AEQ_FILT.findall(txt)]
    if not filters:
        raise web.HTTPBadGateway(text="AutoEq profile has no parametric filters")
    out = {**it, "preamp": float(pre.group(1)) if pre else 0.0, "filters": filters}
    json.dump(out, open(f, "w"))
    return web.json_response(out)


async def sw(req):
    return web.FileResponse(os.path.join(HERE, "static", "sw.js"),
                            headers={"Content-Type": "application/javascript", "Cache-Control": "no-cache"})


async def asset(req):
    """Vite's hashed build output: immutable, cache forever."""
    name = req.match_info["name"]
    path = os.path.join(HERE, "static", "assets", name)
    if "/" in name or name.startswith(".") or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


async def index(req):
    return web.FileResponse(os.path.join(HERE, "static", "index.html"), headers={"Cache-Control": "no-cache"})


async def on_start(app):
    app["http"] = ClientSession(timeout=ClientTimeout(total=None, sock_connect=15, sock_read=60))
    _APP["http"] = app["http"]
    rec.init()
    lib.init()
    sp.init()
    os.makedirs(CACHE, exist_ok=True)
    for f in os.listdir(CACHE):                                 # leftovers of interrupted downloads
        if f.endswith(".part") or ".part-" in f or f.endswith(".ytdl"):
            os.remove(os.path.join(CACHE, f))
    app["lbsync"] = asyncio.ensure_future(lb_sync_loop(app))


async def on_stop(app):
    await app["http"].close()




@web.middleware
async def errors(req, handler):
    user = (req.headers.get("Remote-User") or people.owner()).strip().lower()
    if user not in people.cfg()["people"]:                     # first visit: a person with their own taste
        await off(people.register, user, req.headers.get("Remote-Name"))
    token = rec.USER.set(user)
    try:
        return await handler(req)
    except web.HTTPException:
        raise
    except ConnectionError:                                    # client went away mid-response: nothing to report
        raise
    except Exception as e:
        log("error", req.path, repr(e))
        return web.json_response({"error": str(e)}, status=500)
    finally:
        rec.USER.reset(token)


def main():
    app = web.Application(middlewares=[errors])
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    app.add_routes([
        web.get("/", index), web.get("/manifest.webmanifest", manifest), web.get("/sw.js", sw),
        web.get(r"/assets/{name}", asset),
        web.get(r"/icon-{n:\d+}.png", icon),
        web.get("/healthz", lambda r: web.json_response({"ok": True})),
        web.get("/api/search", api_search), web.get("/api/suggest", api_suggest),
        web.get("/api/search2", api_search2), web.get("/api/suggest2", api_suggest2), web.get("/api/home", api_home),
        web.get("/api/radio", api_radio), web.get("/api/album", api_album), web.get("/api/versions", api_versions), web.get("/api/eq/search", api_eq_search), web.get("/api/eq/profile", api_eq_profile), web.get("/api/playlist", api_playlist),
        web.get("/api/artist", api_artist), web.get("/api/prefetch", api_prefetch), web.get("/api/resolve", api_resolve), web.get("/api/audio", api_audio),
        web.get(r"/stream/{vid}", stream), web.post("/api/listen", api_listen),
        web.get("/api/nest/status", api_nest_status), web.post("/api/nest/sleep", api_nest_sleep),
        web.post(r"/api/nest/{action}", api_nest),
        web.get("/api/foryou", api_foryou), web.get("/api/mix", api_mix), web.get("/api/lbplaylist", api_lbplaylist),
        web.get("/api/autoplay", api_autoplay), web.post("/api/event", api_event),
        web.get("/api/prefs", api_prefs), web.get("/api/taste", api_taste), web.get("/api/likes", api_likes),
        web.get("/img", img), web.get("/api/lyrics", api_lyrics), web.get("/api/me", api_me),
        web.get("/api/myplaylists", api_myplaylists), web.post("/api/myplaylists", api_myplaylists),
        web.get("/api/myplaylist", api_myplaylist), web.post(r"/api/myplaylist/{action}", api_myplaylist),
        web.get("/api/weekly", api_weekly), web.get("/api/people", api_people), web.put("/api/people", api_people), web.get("/api/concerts", api_concerts), web.get("/api/stats", api_stats), web.get("/api/spotify", api_spotify), web.post("/api/spotify", api_spotify), web.get("/api/together", api_together),
        web.get("/api/routines", api_routines), web.put("/api/routines", api_routines), web.post("/api/routines/{rid}/run", api_routines), web.get("/api/speaker", api_speaker), web.post("/api/speaker", api_speaker),
    ])
    log(f"ytm listening on :8090 ({len(people.lb_accounts())} ListenBrainz account(s)), audio-only for the Nest on :8091")

    async def prefetch_plain(req):
        vid = req.match_info["vid"]
        if re.fullmatch(r"[\w-]{11}", vid):
            if not cached(vid)[0]:
                start_download(vid, 1)
            cfg = await off(speaker_cfg)
            if cfg["on"]:                                          # the Nest's next track: tune it now
                asyncio.ensure_future(speaker_version(vid, cfg))
        return web.Response(text="ok")

    async def both():
        audio = web.Application()
        audio.add_routes([web.get(r"/stream/{vid}", nest_stream), web.get(r"/prefetch/{vid}", prefetch_plain),
                          web.post("/routine/play", routine_play)])
        r1, r2 = web.AppRunner(app, access_log=None), web.AppRunner(audio, access_log=None)
        await r1.setup(); await r2.setup()
        await web.TCPSite(r1, "0.0.0.0", 8090).start(); await web.TCPSite(r2, "0.0.0.0", 8091).start()
        await asyncio.Event().wait()
    asyncio.run(both())


if __name__ == "__main__":
    main()
