"""People and circles (people.py; owner only), stats, listening together, concerts."""
import json
import re
import time

import library as lib
import people
import recommend as rec
import spotify as sp
from aiohttp import web

from .common import off


async def api_concerts(req):
    """Written weekly by the concerts job (/data/concerts.json; Ticketmaster, needs TICKETMASTER_API_KEY; the job itself is not in the repo yet)."""
    try:
        d = json.load(open("/data/concerts.json"))
        today = time.strftime("%F")
        return web.json_response({"updated": d.get("updated"), "events": [e for e in d.get("events", []) if e.get("date", "") >= today]})
    except (OSError, ValueError):
        return web.json_response({"updated": None, "events": []})


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
