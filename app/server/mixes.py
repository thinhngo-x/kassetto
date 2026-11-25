"""What Kassetto makes for you: autoplay (/api/autoplay -> recsys.rank), Your mix, the 'Made for you' shelf,
ListenBrainz playlists, Daily Mixes and the weekly lists."""
import asyncio
import itertools
import random
import re
import time

import library as lib
import recommend as rec
import region
import spotify as sp
from aiohttp import web

from .catalogue import audio_version, radio, sp_resolve
from .common import YT, item, local_language, log, norm_title, off, song

LOCAL_FORYOU_BY = {}                                          # user -> {"ts", "items"}


async def local_playlists():
    """Playlists around your favourite artists who sing in the region's language (by how much you like them), plus
    the region's own searches (region.py). Empty without a region language."""
    if not region.LANGUAGE:
        return []
    cache = LOCAL_FORYOU_BY.setdefault(rec.me(), {"ts": 0, "items": []})
    if time.time() - cache["ts"] < 6 * 3600 and cache["items"]:
        return cache["items"]
    aff, _, _ = await off(rec.taste)
    names = await off(rec.artist_names)                       # normalised -> original spelling
    fav = [names[a] for a, sc in sorted(aff.items(), key=lambda x: -x[1]) if sc > 0 and a in names and local_language(names[a])][:4]
    queries = [(a, f"based on {a}") for a in fav] + [(q, q) for q in region.INFO.get("queries", [])]
    results = await asyncio.gather(*[off(YT.search, q, filter="playlists", limit=6) for q, _ in queries], return_exceptions=True)
    lists, seen = [], set()
    for (q, why), res in zip(queries, results):
        lst = []
        for x in [] if isinstance(res, Exception) else res:
            it = item({**x, "resultType": "playlist"})
            t = (it or {}).get("title") or ""
            if it and it["id"] not in seen and norm_title(t) not in seen:
                seen.update({it["id"], norm_title(t)}); lst.append({**it, "sub": f"{region.LANGUAGE} · {why}"})
        lists.append(lst[:2] if q in fav else lst[:3])
    items = [x for row in itertools.zip_longest(*lists) for x in row if x]   # round-robin: artists and moods mixed
    cache.update(ts=time.time(), items=items[:16])
    return cache["items"]


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
    """The 'Made for you' shelf: your mix (from Kassetto's own taste model) + ListenBrainz playlists made for you."""
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
    out = [{"shelf": "Made for you", "items": FORYOU["items"]}]
    try:
        local = await local_playlists()
    except Exception as e:
        log("regional playlists failed:", repr(e)[:120]); local = []
    if local:
        out.append({"shelf": f"{region.LANGUAGE} for you", "items": local, "regional": True})
    return web.json_response(out)


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

# ---------- Daily Mixes ----------
# One mix per taste group (rec.daily_groups: the sound model's clusters, else
# by language with a region language, else by artist), rebuilt once a
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
