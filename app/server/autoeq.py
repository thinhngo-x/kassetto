"""AutoEq headphone correction (experimental): search the AutoEq index, fetch a profile."""
import json
import os
import re
import time
import urllib.parse
import urllib.request

import recommend as rec
from aiohttp import web
from config import USER_AGENT

from .common import log, off

# ---------- AutoEq headphone correction (experimental) ----------
# AutoEq (github.com/jaakkopasanen/AutoEq, MIT): measured correction curves for ~8,800 headphones, as a preamp +
# 10 parametric filters each. Kassetto fetches only AutoEq's public files (index weekly, a profile when picked), cached
# in /data/autoeq; nothing about the listener is sent. The player applies the filters with Web Audio.
AEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
AEQ_DIR = "/data/autoeq"
AEQ = {"ts": 0, "items": [], "by_id": {}}
_AEQ_LINE = re.compile(r"^- \[(.+?)\]\(\./(.+)\) by (.+?)(?: on (.+))?$")
_AEQ_FILT = re.compile(r"Filter \d+: ON (PK|LSC|HSC|LS|HS) Fc ([\d.]+) Hz Gain (-?[\d.]+) dB Q ([\d.]+)")


def _aeq_fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
