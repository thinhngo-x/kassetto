"""The aiohttp application: who is listening (middleware), routes, startup, the two ports (8090 app, 8091 audio)."""
import asyncio
import os
import re

import library as lib
import people
import recommend as rec
import spotify as sp
from aiohttp import ClientSession, ClientTimeout, web

from . import auth
from .autoeq import api_eq_profile, api_eq_search
from .cast import api_nest, api_nest_sleep, api_nest_status, api_speaker, api_speakers, nest_stream, speaker_cfg, speaker_version
from .catalogue import (
    api_album,
    api_artist,
    api_home,
    api_lyrics,
    api_playlist,
    api_radio,
    api_search,
    api_search2,
    api_suggest,
    api_suggest2,
    api_versions,
    img,
)
from .circles import api_concerts, api_people, api_stats, api_together
from .common import _APP, log, off
from .listening import api_event, api_likes, api_listen, api_me, api_prefs, api_spotify, api_taste, lb_sync_loop
from .mixes import api_autoplay, api_foryou, api_lbplaylist, api_mix, api_weekly
from .playlists import api_myplaylist, api_myplaylists
from .quiz import api_quiz, api_quiz_needed
from .routines import api_routines, routine_play
from .streaming import CACHE, api_audio, api_prefetch, api_resolve, cached, start_download, stream
from .web import asset, icon, index, manifest, sw


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
    if req.path in auth.OPEN_PATHS:
        return await handler(req)
    user, display = auth.identify(req)                         # sign-in mode: server/auth.py
    if user not in people.cfg()["people"]:                     # first visit: a person with their own taste
        await off(people.register, user, display)
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


@web.middleware
async def speaker_only(req, handler):
    """The audio-only port: /stream and /prefetch need the speaker's token (auth.check_stream_token)."""
    if req.path.startswith(("/stream/", "/prefetch/")):
        auth.check_stream_token(req)
    return await handler(req)


def main():
    warn = auth.check_config()
    if warn:
        log("WARNING", warn)
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
        web.get("/api/speakers", api_speakers), web.post("/api/speakers", api_speakers),
        web.get("/api/quiz", api_quiz), web.post("/api/quiz", api_quiz), web.get("/api/quiz/needed", api_quiz_needed),
    ])
    log(f"kassetto listening on :8090 (sign-in: {auth.MODE}, {len(people.lb_accounts())} ListenBrainz account(s)), audio-only for the Nest on :8091")

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
        audio = web.Application(middlewares=[speaker_only])
        audio.add_routes([web.get(r"/stream/{vid}", nest_stream), web.get(r"/prefetch/{vid}", prefetch_plain),
                          web.post("/routine/play", routine_play)])
        r1, r2 = web.AppRunner(app, access_log=None), web.AppRunner(audio, access_log=None)
        await r1.setup(); await r2.setup()
        await web.TCPSite(r1, "0.0.0.0", 8090).start(); await web.TCPSite(r2, "0.0.0.0", 8091).start()
        await asyncio.Event().wait()
    asyncio.run(both())
