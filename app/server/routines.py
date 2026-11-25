"""Morning routines: an optional external routines service schedules them; Kassetto plays the music step."""
import asyncio
import hmac
import random
import time

import library as lib
import people
import recommend as rec
from aiohttp import ClientSession, ClientTimeout, web
from config import env

from .cast import _cast_ok, _nest_playing, _nest_status, _wake_runner, music, nest_cc, nest_sleep
from .common import log, off
from .mixes import make_mix
from .streaming import cached, start_download

# ---------- morning routines (an optional external routines service) ----------
# The schedule (briefing + music) lives in a separate routines service (KASSETTO_ROUTINES_URL); Kassetto only plays
# the music step (POST :8091/routine/play, key-checked) and shows the routines in Settings when the URL is set.
ROUTINES_URL = env("ROUTINES_URL", "")
ROUTINES_KEY_FILE = env("ROUTINES_KEY", "/run/routines.key")


def _routines_key():
    try:
        return open(ROUTINES_KEY_FILE).read().strip()
    except OSError:
        return ""


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
    if not k or not hmac.compare_digest(req.headers.get("X-Routines-Key", ""), k):
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
