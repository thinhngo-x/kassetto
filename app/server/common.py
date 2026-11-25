"""Shared by every part of the server: the YouTube Music clients, logging, running blocking code off the event
loop, the HTTP client, and turning ytmusicapi results into the page's song / item dicts."""
import asyncio
import contextvars
import os
import re
import time

import region
from config import env
from ytmusicapi import YTMusic

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/ (static/ is next to app.py)
YT = YTMusic(language=env("LANGUAGE", "en"), location=env("LOCATION", ""))    # "" = YouTube Music's default
YT_REGION = YTMusic(language="en", location=region.CODE) if region.CODE else None   # KASSETTO_REGION (region.py)


def norm_title(t):
    return re.sub(r"\W+", "", (t or "").lower())


def local_language(text):
    return region.local(text)


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


_APP = {}


def app_http():
    return _APP["http"]
