#!/usr/bin/env python3
"""YouTube (Music) on the Nest Mini without ads: yt-dlp resolves the plain audio stream (m4a), the Nest plays it
with the Default Media Receiver, so the YouTube app and its ads are never involved.

  music.py play "song or artist"     search, play it, then continue with YouTube's radio mix for that song
  music.py play <youtube/ytmusic URL> a video (+ its radio) or a playlist (list=...)
  music.py play --only "…"           just that track, no radio
  music.py play-ids ID ID …          an explicit queue of video ids
  music.py next | pause | resume | stop
  music.py vol 0.4                   volume 0..1
  music.py now                       what's playing + up next
(Copied from the author's home setup; v0.1 folds it into the app with speaker discovery.)
A detached player process (state /tmp/nestmusic.json) feeds the Nest track by track; stream URLs are resolved
just before each track (they expire after a few hours). Anything else casting to the Nest (say.py, the morning
briefing, a phone) takes over and the player exits.
"""
import json, os, signal, subprocess, sys, time, urllib.request

import pychromecast
import yt_dlp

SPEAKER_IP = os.environ.get("NEST_IP", "")
STATE = "/tmp/nestmusic.json"
RADIO_MAX = 40
STREAM_BASE = os.environ.get("MUSIC_STREAM_BASE")   # e.g. http://<this server>:8091 = Kassetto's audio-only port
STREAM_KEY = os.environ.get("KASSETTO_STREAM_KEY", "")   # set by the app (server/auth.py): signs the URLs below


def signed(path, vid):
    import hashlib, hmac
    return f"{STREAM_BASE}/{path}/{vid}?t=" + hmac.new(STREAM_KEY.encode(), vid.encode(), hashlib.sha256).hexdigest()[:24]
class _Log:                          # yt-dlp: errors only (hides the "Python 3.10 deprecated" notice)
    def debug(self, m): pass
    def info(self, m): pass
    def warning(self, m): pass
    def error(self, m): print(m, file=sys.stderr)


YDL = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _Log()}


def cast():
    cc = pychromecast.get_chromecast_from_host((SPEAKER_IP, 8009, None, None, None), tries=2, timeout=10)
    cc.wait(timeout=10)
    return cc


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def save_state(st):
    json.dump(st, open(STATE + ".tmp", "w"), ensure_ascii=False); os.replace(STATE + ".tmp", STATE)


def alive(pid):
    try:
        os.kill(pid, 0); return True
    except (OSError, TypeError):
        return False


def resolve_queue(arg, radio=True):
    """-> [(video_id, title)]"""
    with yt_dlp.YoutubeDL({**YDL, "extract_flat": "in_playlist"}) as y:
        target = arg if arg.startswith("http") else f"ytsearch1:{arg}"
        info = y.extract_info(target, download=False)
        if info.get("_type") == "playlist" and "list=" in arg:            # an explicit playlist
            return [(e["id"], e.get("title") or e["id"]) for e in info["entries"] if e.get("id")]
        first = info["entries"][0] if info.get("_type") == "playlist" else info
        q = [(first["id"], first.get("title") or first["id"])]
        if radio:
            try:
                mix = y.extract_info(f"https://www.youtube.com/watch?v={first['id']}&list=RD{first['id']}", download=False)
                q += [(e["id"], e.get("title") or e["id"]) for e in mix.get("entries") or []
                      if e.get("id") and e["id"] != first["id"]][:RADIO_MAX]
            except Exception as e:
                print("radio mix unavailable:", e, file=sys.stderr)
        return q


def stream(video_id):
    with yt_dlp.YoutubeDL({**YDL, "format": "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio"}) as y:
        i = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    mime = "audio/mp4" if i.get("ext") in ("m4a", "mp4") else "audio/webm"
    return i["url"], mime, i.get("title") or video_id, i.get("uploader") or "", i.get("thumbnail")


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


PAUSE_GIVE_UP = 15 * 60                                       # s paused before the player gives up


def run():
    """The player loop (detached)."""
    skip = {"flag": False}
    signal.signal(signal.SIGUSR1, lambda *a: skip.update(flag=True))
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *a: stop.update(flag=True))
    st = load_state()
    cc = cast(); mc = fix_stale_status(cc.media_controller)
    i = st.get("index", 0)
    while i < len(st["queue"]) and not stop["flag"]:
        vid, title, *meta = st["queue"][i]
        st["index"] = i; save_state(st)
        try:
            if STREAM_BASE:                                       # ytm downloads + serves it (copes with 403s)
                url = signed("stream", vid)
                try:                                              # Opus (.webm) or older AAC file: ask ytm
                    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=45) as r:
                        mime = r.headers.get("Content-Type", "audio/webm").split(";")[0]
                except Exception:
                    mime = "audio/webm"
                artist, thumb = (meta + ["", ""])[:2]
                if i + 1 < len(st["queue"]):
                    try:
                        urllib.request.urlopen(signed("prefetch", st['queue'][i + 1][0]), timeout=3).read()
                    except Exception:
                        pass
            else:
                url, mime, title, artist, thumb = stream(vid)
        except Exception as e:
            print(f"skip {vid}: {e}", file=sys.stderr, flush=True); i += 1; continue
        st["title"] = title; save_state(st)
        mc.play_media(url, mime, title=title, thumb=thumb or None,
                      metadata={"metadataType": 3, "title": title, "artist": artist})
        mc.block_until_active(timeout=20)
        started, t0, gone, paused = False, time.time(), 0, 0
        while not stop["flag"]:
            time.sleep(1)
            if int(time.time() - t0) % 5 == 0:                   # ask: pushes can be missed
                try:
                    mc.update_status()
                except Exception:
                    pass
            s = mc.status
            if skip["flag"]:
                skip["flag"] = False; break
            # stopped on the speaker / in Google Home: the receiver app closes (state UNKNOWN, no IDLE ever comes)
            gone = gone + 1 if started and (s.player_state == "UNKNOWN" or cc.app_id != pychromecast.APP_MEDIA_RECEIVER) else 0
            if gone >= 3:
                stop["flag"] = True; st["taken_over"] = True; break
            if s.content_id and s.content_id != url:                # someone else is casting now
                stop["flag"] = True; st["taken_over"] = True; break
            if s.player_state in ("PLAYING", "BUFFERING", "PAUSED"):
                started = True
            paused = paused + 1 if s.player_state == "PAUSED" else 0
            if paused >= PAUSE_GIVE_UP:                           # the Nest's button pauses; long pause = stopped
                stop["flag"] = True; break
            elif s.player_state == "IDLE" and (started or time.time() - t0 > 30):
                if s.idle_reason == "INTERRUPTED" or (cc.app_id and cc.app_id != pychromecast.APP_MEDIA_RECEIVER):
                    stop["flag"] = True; st["taken_over"] = True
                break
        i += 1
    if not st.get("taken_over"):
        try:
            mc.stop(); cc.quit_app()
        except Exception:
            pass
    st["pid"] = None; save_state(st)
    cc.disconnect(timeout=5)


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 1
    cmd, rest = a[0], a[1:]
    st = load_state()
    running = alive(st.get("pid"))
    if cmd == "_run":
        return run()
    if cmd == "play":
        radio = "--only" not in rest
        query = " ".join(x for x in rest if x != "--only")
        if not query:
            print("play what?"); return 1
        if running:
            os.kill(st["pid"], signal.SIGTERM); time.sleep(1.5)
        q = resolve_queue(query, radio)
        save_state({"queue": q, "index": 0, "query": query, "pid": None})
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_run"], start_new_session=True,
                             stdout=open("/tmp/nestmusic.log", "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        st = load_state(); st["pid"] = p.pid; save_state(st)
        print(f"▶ {q[0][1]}" + (f"  (+{len(q) - 1} in the radio queue)" if len(q) > 1 else ""))
        return 0
    if cmd == "play-ids":                       # an explicit queue of video ids (used by ytm's "play on Nest")
        if not rest:
            print("play-ids ID…"); return 1
        if running:
            os.kill(st["pid"], signal.SIGTERM); time.sleep(1.5)
        q = []
        for a in rest:
            vid, *m = a.split("\t")
            q.append([vid, (m[0] if m and m[0] else vid), *m[1:3]])
        save_state({"queue": q, "index": 0, "query": "ids", "pid": None})
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_run"], start_new_session=True,
                             stdout=open("/tmp/nestmusic.log", "a"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        st = load_state(); st["pid"] = p.pid; save_state(st)
        print(f"▶ {len(rest)} tracks"); return 0
    if cmd == "next":
        if not running:
            print("nothing playing"); return 1
        os.kill(st["pid"], signal.SIGUSR1); print("⏭ next"); return 0
    if cmd == "stop":
        if running:
            os.kill(st["pid"], signal.SIGTERM)
        else:
            cc = cast(); cc.media_controller.stop(); cc.quit_app(); cc.disconnect(timeout=5)
        print("⏹ stopped"); return 0
    if cmd in ("pause", "resume", "vol"):
        cc = cast(); mc = cc.media_controller; mc.update_status(); time.sleep(0.5)
        if cmd == "pause":
            mc.pause()
        elif cmd == "resume":
            mc.play()
        else:
            cc.set_volume(max(0.0, min(1.0, float(rest[0]))))
        time.sleep(0.5); cc.disconnect(timeout=5); print("ok"); return 0
    if cmd == "now":
        if not running:
            print("nothing playing"); return 0
        i, q = st["index"], st["queue"]
        print(f"▶ {st.get('title') or q[i][1]}")
        for _, t in q[i + 1:i + 6]:
            print(f"  next: {t}")
        return 0
    print(__doc__); return 1


if __name__ == "__main__":
    sys.exit(main())
