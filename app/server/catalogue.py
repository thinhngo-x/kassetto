"""YouTube Music's catalogue: search (+ the smarter /api/search2 with library, Spotify history and vibe search),
suggestions, the home feed, radios, albums / playlists / artists, versions of a song, lyrics, image proxy."""
import asyncio
import json
import re
import time
import urllib.parse
import urllib.request

import phonetics
import recommend as rec
import region
import spotify as sp
from aiohttp import ClientTimeout, web
from config import EMBED_URL, USER_AGENT

from .common import YT, YT_REGION, app_http, artists, clean, item, local_language, log, off, song, thumb

RADIO = {}                        # videoId -> (ts, [songs])  (1 h cache)


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
        async with app_http().post(f"{EMBED_URL}/text", json={"q": q}, timeout=ClientTimeout(total=4)) as r:
            return (await r.json()).get("vec")
    except Exception as e:
        log("text embedding unavailable:", repr(e)[:80]); return None
# reference descriptions spanning moods / genres / instruments: their mean = the "text side" of CLAP's space
REF_PROMPTS = ["sad piano ballad", "happy upbeat pop song", "heavy metal with screaming vocals", "calm acoustic guitar",
               "energetic electronic dance music", "slow jazz with saxophone", "epic orchestral film score",
               "lo-fi hip hop beat", "rap with heavy bass", "romantic love song", "dark ambient drone",
               "folk song with banjo", "classical string quartet", "punk rock", "soul music with gospel choir",
               "reggae", "country music", "rainy day melancholic indie", "party anthem", "soft lullaby",
               "aggressive rock with distorted guitars", "dreamy synth pop", "traditional east asian folk music",
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
    """With KASSETTO_REGION: that country's charts and the local-language parts of its home feed first; then the
    regular feed."""
    if time.time() - HOME["ts"] < 1800 and HOME["data"]:
        return web.json_response(HOME["data"])

    async def get(fn, *a, **k):
        try:
            return await off(fn, *a, **k)
        except Exception as e:
            log("home source failed:", repr(e)[:120]); return None

    nothing = asyncio.sleep(0, None)
    home, home_reg, charts = await asyncio.gather(
        get(YT.get_home, limit=8),
        get(YT_REGION.get_home, limit=8) if YT_REGION and region.LANGUAGE else nothing,
        get(YT_REGION.get_charts, country=region.CODE) if YT_REGION else nothing)
    out = []
    if charts:
        top = clean(item({**x, "resultType": "playlist"}) for x in charts.get("videos") or [])
        top += clean(item({**x, "resultType": "artist"}) for x in (charts.get("artists") or [])[:20])
        if top:
            out.append({"title": f"Top in {region.NAME}", "items": top, "regional": True})
    for sec in home_reg or []:
        items = clean(item(x) for x in sec.get("contents") or [])
        if items and sum(local_language(i.get("title")) or local_language(i.get("artist") or i.get("sub")) for i in items) >= 0.4 * len(items):
            out.append({"title": f"{sec.get('title')} · {region.NAME}", "items": items[:20], "regional": True})
    for sec in home or []:
        items = clean(item(x) for x in sec.get("contents") or [])
        if items:
            out.append({"title": sec.get("title"), "items": items[:20]})
    HOME.update(ts=time.time(), data=out)
    return web.json_response(out)


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
    """For radio seeds picked by Kassetto (autoplay, Your mix): YouTube Music's radio follows the seed's type (a music
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
    req = urllib.request.Request(f"https://lrclib.net/api/search?{q}", headers={"User-Agent": USER_AGENT})
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
