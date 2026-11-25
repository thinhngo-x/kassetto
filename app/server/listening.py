"""What you do and what Kassetto knows about you: events (plays, likes, signals -> recsys), ListenBrainz
scrobbles and sync, /api/me, likes, prefs, taste report, Spotify history setting."""
import asyncio
import time

import library as lib
import people
import recommend as rec
import spotify as sp
from aiohttp import web

from .common import log, off


async def api_spotify(req):
    if req.method == "POST":
        d = await req.json()
        await off(lib.set_setting, "spotify_prior", bool(d.get("prior")))
    return web.json_response({"has": await off(sp.has, rec.me()), "prior": await off(lib.setting, "spotify_prior", True)})


async def api_event(req):
    b = await req.json()
    ev = b.get("event")
    if ev == "search_artist" and b.get("q"):
        pass                                                      # a search that named an artist (no track)
    elif ev not in ("complete", "partial", "skip", "like", "unlike", "hide", "unhide", "dislike", *rec.SIGNALS) or not b.get("videoId"):
        raise web.HTTPBadRequest(text="bad event")
    await off(rec.record, b)
    return web.json_response({"ok": True})


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


# ---------- ListenBrainz ----------

async def api_listen(req):
    b = await req.json()
    _, token, _ = await off(people.lb_account, rec.me())          # own account / the one you scrobble as / none
    if not token or not b.get("artist") or not b.get("title"):
        return web.json_response({"ok": False, "reason": "no token or metadata"})
    meta = {"artist_name": b["artist"], "track_name": b["title"],
            "additional_info": {"media_player": "Kassetto", "submission_client": "kassetto",
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
