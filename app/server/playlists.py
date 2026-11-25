"""Your playlists (library.py): list, create, edit, share with a circle."""
import re

import library as lib
import people
import recommend as rec
from aiohttp import web

from .common import off

# ---------- your playlists (library.py) ----------

def _pl_detail(p):
    sub = ("Made by Kassetto, new every Monday" if p["kind"] == "weekly" else
           "Made by Kassetto, new every day · " + ((lib.setting("daily_subs", {}) or {}).get(p["id"]) or "your taste") if p["kind"] == "daily" else
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
