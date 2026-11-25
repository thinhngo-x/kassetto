"""Audio: yt-dlp downloads into the cache (Opus 251, AAC fallback) served while still downloading, the download
queue and workers, the look-ahead resolver (beats YouTube's ad countdown), cache pruning, loudness data."""
import asyncio
import collections
import heapq
import itertools
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

import recommend as rec
import yt_dlp
from aiohttp import web
from config import CACHE as _CACHE
from config import EMBED_URL, env

from .common import log, off

# ---------- streams ----------

YDL = {"quiet": True, "no_warnings": True, "noprogress": True}
# Opus 251 (~130 kbps VBR, WebM) sounds clearly better than AAC 140 at the same size; the Nest plays it
# (tested 2026-11-24). Browsers that can't play Opus (some Safari versions) ask for ?aac=1 -> AAC copy.
FMT_OPUS = "251/bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio"
FMT_AAC = "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio"


CACHE = _CACHE
CACHE_MAX = int(env("CACHE_MB", "3000")) << 20
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
    """The embed service measures loudness + silent edges of a freshly cached track (~1-2 s) -> table audio."""
    try:
        urllib.request.urlopen(urllib.request.Request(f"{EMBED_URL}/analyze", data=json.dumps({"vid": vid}).encode(),
                                                      headers={"Content-Type": "application/json"}), timeout=60).read()
    except Exception as e:
        log("analysis request failed", vid, str(e)[:100])


# Volume levelling: like YouTube / Spotify, loud masters are turned down to TARGET_LUFS; quieter ones play
# as they are (attenuation only, so no clipping and no Web Audio needed: the player just scales el.volume).
TARGET_LUFS = float(env("TARGET_LUFS", "-14"))


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
    except sqlite3.OperationalError:                             # the embed service hasn't created the table yet
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
