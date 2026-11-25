"""Chromecast / Nest (via castplayer.py): play, status, seek, sleep timer, speaker tuning, the audio-only stream
the speaker fetches (port 8091), whose taste the speaker follows."""
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time

import library as lib
import people
import recommend as rec
from aiohttp import ClientTimeout, web
from config import EMBED_URL

from .common import app_http, log, off
from .streaming import CACHE, cached, start_download, stream

MUSIC_PY = os.environ.get("MUSIC_PY", "/app/castplayer.py")


# ---------- Nest / Chromecast (via castplayer.py) ----------

def music(*args):
    from .auth import stream_key                                 # castplayer signs its audio-port URLs with it
    r = subprocess.run([sys.executable, MUSIC_PY, *args], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "KASSETTO_STREAM_KEY": stream_key()})
    return (r.stdout + r.stderr).strip()


SPEAKER_IP = os.environ.get("NEST_IP", "")                       # discovery replaces it (milestone item 6)
NEST = {"cc": None}
NEST_LOCK = threading.Lock()


def fix_stale_status(mc):
    """pychromecast ignores a MEDIA_STATUS with an empty list, which is what the Nest sends when playback is
    stopped on the speaker / in Google Home: the old status (PLAYING) would stay forever. Reset it instead."""
    from pychromecast.controllers.media import MediaStatus
    orig = mc._process_media_status

    def proc(data):
        if not data.get("status"):
            mc.status = MediaStatus()
        orig(data)
    mc._process_media_status = proc
    return mc


def nest_cc():
    """One persistent Cast connection for status/seek (music.py's player keeps its own)."""
    import pychromecast
    with NEST_LOCK:
        cc = NEST["cc"]
        if cc is None or not cc.socket_client.is_connected:
            if cc is not None:
                try:
                    cc.disconnect(timeout=2)
                except Exception:
                    pass
            if not SPEAKER_IP:
                raise RuntimeError("no speaker set up")
            cc = pychromecast.get_chromecast_from_host((SPEAKER_IP, 8009, None, None, None),
                                                       tries=2, timeout=8)
            cc.wait(timeout=8)
            fix_stale_status(cc.media_controller)
            NEST["cc"] = cc
        return cc


def _nest_status():
    try:
        st = json.load(open("/tmp/nestmusic.json"))
    except (OSError, ValueError):
        st = {}
    pid = st.get("pid")
    try:
        running = bool(pid) and (os.kill(pid, 0) is None)
    except OSError:
        running = False
    out = {"active": running, "sleep_at": NEST_SLEEP["at"] or None, "configured": bool(SPEAKER_IP)}
    if running and st.get("queue"):
        i = st.get("index", 0)
        out.update(index=i, videoId=st["queue"][i][0], title=st.get("title"))
    if not SPEAKER_IP:                                           # nothing to ask (was an 8 s connect timeout)
        return out
    try:
        cc = nest_cc(); ms = cc.media_controller.status
        try:
            cc.media_controller.update_status()                  # the answer lands for the next poll
        except Exception:
            pass
        out.update(state=ms.player_state, position=ms.adjusted_current_time or 0, duration=ms.duration,
                   volume=cc.status.volume_level if cc.status else None)
    except Exception as e:
        out["error"] = str(e)[:100]
    return out


def _cast_ok():
    if not people.can_cast(rec.me()):
        raise web.HTTPForbidden(text="the speaker belongs to another circle")


async def api_nest_status(req):
    if not people.can_cast(rec.me()):
        return web.json_response({"active": False, "allowed": False})
    return web.json_response(await off(_nest_status))


def _nest_seek(t):
    cc = nest_cc(); cc.media_controller.seek(max(0.0, float(t)))


async def api_nest(req):
    _cast_ok()
    action = req.match_info["action"]
    b = await req.json() if req.can_read_body else {}
    if action == "play":
        tracks = [t for t in b.get("tracks", []) if re.fullmatch(r"[\w-]{11}", t.get("videoId", ""))][:100]
        if not tracks:
            raise web.HTTPBadRequest(text="tracks required")
        for k, t in enumerate(tracks[:2]):
            if not cached(t["videoId"])[0]:
                start_download(t["videoId"], k)                 # first track: now; second: next
        args = ["\t".join([t["videoId"], *(str(t.get(k) or "").replace("\t", " ") for k in ("title", "artist", "thumb"))])
                for t in tracks]
        out = await off(music, "play-ids", *args)
    elif action in ("next", "pause", "resume", "stop", "now"):
        out = await off(music, action)
    elif action == "seek":
        await off(_nest_seek, b.get("t", 0)); out = "ok"
    elif action == "vol":
        out = await off(music, "vol", str(max(0.0, min(1.0, float(b.get("v", 0.3))))))
    else:
        raise web.HTTPNotFound()
    return web.json_response({"out": out})


# ---------- sleep timer on the Nest (the page may be closed, so the server runs it) ----------
NEST_SLEEP = {"at": 0, "tok": 0}


def _nest_playing(cc):
    try:
        return cc.media_controller.status.player_state in ("PLAYING", "BUFFERING")
    except Exception:
        return False


def _nest_fade_stop(tok, fade=30):
    """Fade the Nest out over `fade` s, stop, put the volume back (so tomorrow isn't silent).
    Nothing playing any more (stopped on the speaker): do nothing; an idle Nest chimes at every volume change."""
    try:
        cc = nest_cc(); v0 = cc.status.volume_level if cc.status else 0.3
        if not _nest_playing(cc):
            log("sleep timer: the Nest had already stopped"); return
        for i in range(1, fade + 1):
            if NEST_SLEEP["tok"] != tok or not _nest_playing(cc):
                cc.set_volume(v0); return
            cc.set_volume(max(0.0, v0 * (1 - i / fade))); time.sleep(1)
        music("stop"); time.sleep(2); cc.set_volume(v0)
        log("sleep timer: Nest stopped")
    except Exception as e:
        log("sleep timer", repr(e)[:120])
    finally:
        if NEST_SLEEP["tok"] == tok:
            NEST_SLEEP["at"] = 0


def nest_sleep(minutes):
    NEST_SLEEP["tok"] += 1
    tok = NEST_SLEEP["tok"]
    if minutes <= 0:
        NEST_SLEEP["at"] = 0; return
    NEST_SLEEP["at"] = time.time() + minutes * 60

    def run():
        quiet = 0
        while NEST_SLEEP["tok"] == tok and time.time() < NEST_SLEEP["at"] - 30:
            time.sleep(1)
            if int(time.time()) % 10 == 0:                       # music stopped on the speaker: drop the timer
                try:
                    alive = nest_cc().media_controller.status.player_state in ("PLAYING", "BUFFERING", "PAUSED")
                    quiet = 0 if alive else quiet + 1
                except Exception:
                    pass
                if quiet >= 6:                                   # ~1 min with nothing playing
                    NEST_SLEEP["at"] = 0; log("sleep timer dropped: the Nest stopped"); return
        if NEST_SLEEP["tok"] == tok:
            _nest_fade_stop(tok)
    threading.Thread(target=run, daemon=True).start()


async def api_nest_sleep(req):
    _cast_ok()
    b = await req.json()
    m = float(b.get("minutes") or 0)
    if b.get("end_of_track"):
        st = await off(_nest_status)
        m = max(0.6, ((st.get("duration") or 0) - (st.get("position") or 0)) / 60 + 0.4)
    nest_sleep(m)
    return web.json_response({"at": NEST_SLEEP["at"]})


def _wake_key():
    sc = people.speaker_circle()
    return f"circle:{sc}" if sc else people.owner()


def _wake_runner():
    """Default taste for alarms without an owner: the owner if in the speaker's circle, else its first member."""
    sc = people.speaker_circle()
    m = (people.cfg()["circles"].get(sc) or {}).get("members", []) if sc else []
    return people.owner() if not m or people.owner() in m else m[0]


# ---------- speaker tuning for the Nest (rendered by the embed service: ffmpeg) ----------
# The Nest plays files from the audio-only port, so it gets a version tuned for a small mono speaker: levelled
# to SPEAKER["lufs"], sub-bass removed, warmth / less harshness, the circle's bass & treble, gentle compression,
# proper mono mix (embed.py speaker_version, ~3-5 s per song). The next song is prepared while one plays; a song
# not downloaded yet plays as the original (tuned in the background for next time); a version not ready within
# 25 s falls back to the original. Setting belongs to the speaker's circle (like wake-up music).
SPEAKER_DEFAULT = {"on": True, "bass": 0, "treble": 0, "lufs": -14}
SPK_JOBS = {}


def speaker_cfg():
    return {**SPEAKER_DEFAULT, **(lib.setting("speaker", {}, user=_wake_key()) or {})}


async def speaker_version(vid, cfg):
    """-> path of the tuned file, or None (then the original plays)."""
    p = {"lufs": float(cfg["lufs"]), "bass": float(cfg["bass"]), "treble": float(cfg["treble"])}
    key = (vid, json.dumps(p, sort_keys=True))
    if key not in SPK_JOBS:
        async def job():
            t0 = time.time()
            if not cached(vid)[0]:
                d = start_download(vid, 0)
                while not cached(vid)[0] and not d.error and time.time() - t0 < 40:
                    await asyncio.sleep(0.2)
            if not cached(vid)[0]:
                return None
            async with app_http().post(f"{EMBED_URL}/speaker", json={"vid": vid, "p": p},
                                       timeout=ClientTimeout(total=120)) as r:
                f = (await r.json()).get("file")
            return os.path.join(CACHE, f) if f else None
        SPK_JOBS[key] = asyncio.ensure_future(job())
        if len(SPK_JOBS) > 300:
            for k in [k for k, v in SPK_JOBS.items() if v.done()][:150]:
                SPK_JOBS.pop(k, None)
    fut = SPK_JOBS[key]
    try:
        f = await asyncio.wait_for(asyncio.shield(fut), 25)
    except Exception as e:
        if fut.done():
            SPK_JOBS.pop(key, None)                               # failed: try again next time
        log("speaker version", vid, "not ready, playing the original:", repr(e)[:80])
        return None
    if not f or not os.path.exists(f):
        SPK_JOBS.pop(key, None)
        return None
    return f


async def nest_stream(req):
    """/stream/<id> on the audio-only port (= the Nest): the speaker-tuned version when switched on."""
    vid = req.match_info["vid"]
    if re.fullmatch(r"[\w-]{11}", vid):
        cfg = await off(speaker_cfg)
        if cfg["on"] and not cached(vid)[0]:                     # cold: play the original now, tune it for next time
            asyncio.ensure_future(speaker_version(vid, cfg))
        elif cfg["on"]:
            f = await speaker_version(vid, cfg)
            if f:
                os.utime(f)
                return web.FileResponse(f, headers={"Content-Type": "audio/webm", "Cache-Control": "private, max-age=86400"})
    return await stream(req)


async def api_speaker(req):
    if req.method == "POST":
        _cast_ok()
        b = await req.json()
        cur = await off(speaker_cfg)
        cur.update({k: b[k] for k in ("on", "bass", "treble") if k in b})
        cur["bass"] = max(-6.0, min(6.0, float(cur["bass"]))); cur["treble"] = max(-6.0, min(6.0, float(cur["treble"])))
        await off(lib.set_setting, "speaker", cur, _wake_key())
    return web.json_response({**await off(speaker_cfg), "allowed": people.can_cast(rec.me())})
