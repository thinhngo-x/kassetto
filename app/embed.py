#!/usr/bin/env python3
"""ytm-embed: sound fingerprints for ytm's recommender (CLAP, laion/larger_clap_music, CPU).

Each track -> 3 x 10 s clips (25 / 50 / 75 % of the song) -> CLAP audio embedding (512-d, L2-normalised, mean of
the clips) -> table emb in /data/ytm.db. Sources, in priority order:
  1. tracks in ytm's audio cache (/data/cache) that have no embedding yet (no download needed)
  2. emb_queue: candidates ytm saw without an embedding (radio items etc.) -> downloaded with yt-dlp into a temp
     file, embedded, deleted. Rate-limited (QUEUE_GAP s apart, QUEUE_PER_DAY) so YouTube isn't hammered.
Also measures every cached track for the player (table audio, no model needed, ~1-2 s per song): EBU R128
integrated loudness + true peak (volume levelling) and where the sound starts / ends (silence trimming,
crossfades). ytm asks for it right after a download (POST /analyze); the main loop backfills the rest.
Runs niced with 2 torch threads so the TTS / other services stay responsive.
"""
import os, sqlite3, subprocess, sys, tempfile, threading, time

LOCK = threading.Lock()                # one torch call at a time (audio loop vs text requests)

import numpy as np

DB = os.environ.get("YTM_DB", "/data/ytm.db")
CACHE = os.environ.get("YTM_CACHE", "/data/cache")
# laion/clap-htsat-unfused: larger_clap_music was tried first, but its text tower is collapsed (every description
# -> the same vector, cosine 0.999), so text<->audio search could not work and its audio side was weaker too.
MODEL = os.environ.get("CLAP_MODEL", "laion/clap-htsat-unfused")
REVISION = os.environ.get("CLAP_REVISION", "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a")
THREADS = int(os.environ.get("EMBED_THREADS", "2"))
QUEUE_GAP = int(os.environ.get("QUEUE_GAP", "60"))
QUEUE_PER_DAY = int(os.environ.get("QUEUE_PER_DAY", "200"))
SR = 48000


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS emb(video_id TEXT PRIMARY KEY, vec BLOB, model TEXT, ts INTEGER);
        CREATE TABLE IF NOT EXISTS emb_queue(video_id TEXT PRIMARY KEY, prio REAL, ts INTEGER, tries INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS audio(video_id TEXT PRIMARY KEY, lufs REAL, peak REAL, start REAL, "end" REAL,
                                         dur REAL, ts INTEGER);
        """)
        # model changed: vectors from another model live in a different space -> drop them, re-fingerprint
        old = [r[0] for r in c.execute("SELECT video_id FROM emb WHERE model NOT IN (?, 'error')", (MODEL,))]
        if old:
            c.executemany("INSERT OR REPLACE INTO emb_queue(video_id, prio, ts, tries) VALUES(?, 5, ?, 0)",
                          [(v, int(time.time())) for v in old])
            c.execute("DELETE FROM emb WHERE model NOT IN (?, 'error')", (MODEL,))
            log(f"model is now {MODEL}: {len(old)} old fingerprints dropped and re-queued")


def analyze(path):
    """One ffmpeg pass: integrated loudness (LUFS), true peak (dBFS), first/last audible second.
    Silence = below -55 dBFS for >= 0.4 s; only silence touching the start / the end of the file is trimmed
    (a hidden track after a long pause in the middle stays), and the lead-in trim is capped at 15 s."""
    import re
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                          "ebur128=peak=true:framelog=quiet,silencedetect=n=-55dB:d=0.4", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=300).stderr
    num = lambda pat: (lambda m: float(m[-1]) if m else None)(re.findall(pat, err))
    lufs, peak = num(r"I:\s+(-?[\d.]+) LUFS"), num(r"Peak:\s+(-?[\d.]+) dBFS")
    t = re.findall(r"time=(\d+):(\d+):([\d.]+)", err)
    dur = int(t[-1][0]) * 3600 + int(t[-1][1]) * 60 + float(t[-1][2]) if t else None
    if lufs is None or not dur:
        raise RuntimeError("ffmpeg gave no loudness/duration")
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    start, end = 0.0, dur
    if starts and starts[0] <= 0.05 and ends:
        start = min(ends[0], 15.0)
    if starts and starts[-1] > start and (len(ends) < len(starts) or ends[-1] >= dur - 0.25):
        end = starts[-1]
    if end - start < 0.5 * dur:                    # implausible (mostly silent?): don't trim
        start, end = 0.0, dur
    return {"lufs": lufs, "peak": peak, "start": round(start, 2), "end": round(end, 2), "dur": round(dur, 2)}


def store_audio(vid, a):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO audio VALUES(?,?,?,?,?,?,?)',
                  (vid, a["lufs"], a["peak"], a["start"], a["end"], a["dur"], int(time.time())))


def cache_file(vid):
    for ext in (".webm", ".m4a", ".mp4"):
        if os.path.exists(os.path.join(CACHE, vid + ext)):
            return os.path.join(CACHE, vid + ext)


def analyze_vid(vid):
    path = cache_file(vid)
    if not path:
        return None
    t = time.time(); a = analyze(path); store_audio(vid, a)
    log(f"analysed {vid}: {a['lufs']} LUFS, sound {a['start']}-{a['end']} of {a['dur']} s ({time.time() - t:.1f}s)")
    return a


SPK_ACTIVE = [0]                     # speaker versions being rendered: fingerprinting waits (someone is listening)


def speaker_version(vid, p):
    """A copy of a cached track tuned for a small mono speaker (the Nest Mini), cached as <id>.spk-<hash>.webm:
    levelled to p["lufs"] measured after the processing (2 fast passes, limiter at -1.5 dBFS), sub-bass the speaker can't play removed
    (high-pass 70 Hz: less distortion when loud), a little warmth (150 Hz) and less harshness (3.5 kHz),
    the user's bass / treble, gentle compression, proper mono downmix (stereo-wide parts don't vanish)."""
    import hashlib, json as _j
    src = cache_file(vid)
    if not src:
        return None
    key = hashlib.sha1(_j.dumps(p, sort_keys=True).encode()).hexdigest()[:8]
    out = os.path.join(CACHE, f"{vid}.spk-{key}.webm")
    if os.path.exists(out):
        os.utime(out); return out
    import re as _re
    chain = ",".join([
        "pan=mono|c0=0.5*c0+0.5*c1",
        "highpass=f=70:poles=2",
        f"equalizer=f=150:t=o:w=1.2:g={1.5 + p.get('bass', 0):.1f}",
        "equalizer=f=3500:t=o:w=1.5:g=-2",
        f"treble=g={p.get('treble', 0):.1f}:f=6000",
        "acompressor=threshold=-18dB:ratio=2.5:attack=15:release=250",
    ])
    t = time.time()
    SPK_ACTIVE[0] += 1
    try:
        _render(src, out, chain, p)
    finally:
        SPK_ACTIVE[0] -= 1
    log(f"speaker version {vid}: bass {p.get('bass', 0)}, treble {p.get('treble', 0)} ({time.time() - t:.1f}s)")
    return out


def _render(src, out, chain, p):
    import re as _re
    # pass 1: loudness of the tuned sound (mono + EQ change it); pass 2: that exact gain + a peak limiter
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-af", chain + ",ebur128=framelog=quiet",
                          "-f", "null", "-"], capture_output=True, text=True, timeout=300).stderr
    m = _re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    gain = max(-15.0, min(9.0, p.get("lufs", -14) - float(m[-1]))) if m else 0.0
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", f"{chain},volume={gain:.2f}dB,alimiter=limit=0.84:level=false",
                    "-ac", "1", "-c:a", "libopus", "-b:a", "96k", "-f", "webm", out + ".tmp"], check=True, timeout=300)
    os.replace(out + ".tmp", out)


def pending_audio():
    with db() as c:
        have = {r[0] for r in c.execute("SELECT video_id FROM audio")}
    vids = {f.rsplit(".", 1)[0] for f in os.listdir(CACHE) if f.endswith((".webm", ".m4a", ".mp4"))}
    return [v for v in vids if len(v) == 11 and v not in have]


def decode_clips(path, n=3, secs=10):
    """ffmpeg -> mono float32 @48 kHz; n clips of `secs` seconds spread over the track."""
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(pcm, dtype=np.float32)
    L = SR * secs
    if len(y) < L:
        return [np.pad(y, (0, L - len(y)))]
    starts = [int((len(y) - L) * f) for f in np.linspace(0.25, 0.75, n)]
    return [y[s:s + L] for s in starts]


IDLE_UNLOAD = int(os.environ.get("IDLE_UNLOAD", "600"))   # free the model after this many idle seconds (reload ~1 s)


class Clap:
    def __init__(self):
        import torch
        torch.set_num_threads(THREADS)
        self.torch = torch
        self.model = self.proc = None
        self.last = 0.0

    def ensure(self):
        """Load on demand (callers hold LOCK)."""
        self.last = time.time()
        if self.model is None:
            from transformers import ClapModel, ClapProcessor
            t = time.time()
            self.proc = ClapProcessor.from_pretrained(MODEL, revision=REVISION)
            self.model = ClapModel.from_pretrained(MODEL, revision=REVISION).eval()
            log(f"CLAP {MODEL}@{REVISION[:8]} loaded in {time.time() - t:.1f}s ({THREADS} threads)")

    def unload_if_idle(self):
        if self.model is not None and time.time() - self.last > IDLE_UNLOAD and LOCK.acquire(blocking=False):
            try:
                import ctypes, gc
                self.model = self.proc = None
                gc.collect()
                try:
                    ctypes.CDLL("libc.so.6").malloc_trim(0)
                except OSError:
                    pass
                log(f"model unloaded after {IDLE_UNLOAD // 60} min idle")
            finally:
                LOCK.release()

    def text(self, q):
        """CLAP text embedding (same joint space as the audio vectors): 'sad rainy piano' -> 512-d unit vector."""
        with LOCK, self.torch.inference_mode():
            self.ensure()
            x = self.proc(text=[q], return_tensors="pt", padding=True)
            m = self.model                                     # explicit encoder -> projection (stable across versions)
            v = m.text_projection(m.text_model(input_ids=x["input_ids"], attention_mask=x["attention_mask"]).pooler_output)[0].numpy()
        return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)

    def embed(self, clips):
        with LOCK, self.torch.inference_mode():
            self.ensure()
            x = self.proc(audio=clips, sampling_rate=SR, return_tensors="pt")
            m = self.model
            f = m.audio_projection(m.audio_model(input_features=x["input_features"], is_longer=x.get("is_longer")).pooler_output)
            f = f / f.norm(dim=-1, keepdim=True)
            v = f.mean(0).numpy()
        return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float16)


def store(vid, vec):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO emb VALUES(?,?,?,?)", (vid, vec.tobytes(), MODEL, int(time.time())))
        c.execute("DELETE FROM emb_queue WHERE video_id=?", (vid,))


def pending_cache():
    with db() as c:
        have = {r[0] for r in c.execute("SELECT video_id FROM emb WHERE model IN (?, 'error')", (MODEL,))}
    out = []
    for f in sorted(os.listdir(CACHE), key=lambda f: -os.path.getmtime(os.path.join(CACHE, f))):
        vid, ext = os.path.splitext(f)
        if ext in (".m4a", ".webm", ".mp4") and len(vid) == 11 and vid not in have:
            out.append((vid, os.path.join(CACHE, f)))
    return out


def next_queued():
    with db() as c:
        return c.execute("SELECT video_id FROM emb_queue WHERE tries < 3 AND video_id NOT IN (SELECT video_id FROM emb WHERE model = ?)"
                         " ORDER BY prio DESC, ts DESC LIMIT 1", (MODEL,)).fetchone()


def download(vid, d):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": {"default": f"{d}/{vid}.%(ext)s"}, "http_chunk_size": 2 << 20}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
    return info["requested_downloads"][0]["filepath"]


def serve_text(clap, port=8099):
    """Internal HTTP endpoint for ytm (network music_ytm only): POST /text {"q": "..."} -> {"vec": [...]}."""
    import http.server, json

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_POST(self):
            if self.path == "/speaker":                      # {"vid", "p": {lufs, bass, treble}} -> {"file": name}
                try:
                    b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                    f = speaker_version(b["vid"], b.get("p") or {}) if len(b.get("vid", "")) == 11 else None
                    body = json.dumps({"file": os.path.basename(f) if f else None}).encode(); self.send_response(200)
                except Exception as e:
                    body = json.dumps({"error": str(e)[:200]}).encode(); self.send_response(500)
                self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            if self.path == "/analyze":                      # {"vid": "..."}: measure a freshly cached track now
                try:
                    vid = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("vid", "")
                    body = json.dumps({"audio": analyze_vid(vid) if len(vid) == 11 else None}).encode(); self.send_response(200)
                except Exception as e:
                    body = json.dumps({"error": str(e)[:200]}).encode(); self.send_response(500)
                self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            try:
                q = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("q", "")[:200]
                body = json.dumps({"vec": clap.text(q).round(5).tolist()}).encode() if q else b'{"vec": null}'
                self.send_response(200)
            except Exception as e:
                body = json.dumps({"error": str(e)[:200]}).encode(); self.send_response(500)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

    threading.Thread(target=http.server.ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever, daemon=True).start()
    log(f"text endpoint on :{port}")


def main():
    os.nice(10)
    init()
    clap = Clap()
    serve_text(clap)
    day, done_today, last_dl = time.strftime("%F"), 0, 0.0
    while True:
        work = False
        for vid in pending_audio()[:50]:                    # cheap (no model): before fingerprints
            try:
                analyze_vid(vid); work = True
            except Exception as e:
                log("analysis failed", vid, repr(e)[:150])
                store_audio(vid, {"lufs": None, "peak": None, "start": 0, "end": None, "dur": None})
        for vid, path in pending_cache()[:20]:
            while SPK_ACTIVE[0]:                            # a Nest listener is waiting for a speaker version
                time.sleep(0.5)
            try:
                t = time.time(); store(vid, clap.embed(decode_clips(path))); work = True
                log(f"embedded {vid} (cache) in {time.time() - t:.1f}s")
            except Exception as e:
                log("embed failed", vid, repr(e)[:150])
                with db() as c:                                   # don't retry a broken file forever
                    c.execute("INSERT OR REPLACE INTO emb VALUES(?,?,?,?)", (vid, None, "error", int(time.time())))
        if time.strftime("%F") != day:
            day, done_today = time.strftime("%F"), 0
        row = next_queued()
        if row and done_today < QUEUE_PER_DAY and time.time() - last_dl >= QUEUE_GAP and not SPK_ACTIVE[0]:
            vid = row[0]; last_dl = time.time(); work = True
            with tempfile.TemporaryDirectory() as d:
                try:
                    t = time.time(); store(vid, clap.embed(decode_clips(download(vid, d)))); done_today += 1
                    log(f"embedded {vid} (queue, {done_today}/{QUEUE_PER_DAY} today) in {time.time() - t:.1f}s")
                except Exception as e:
                    log("queue item failed", vid, repr(e)[:150])
                    with db() as c:
                        c.execute("UPDATE emb_queue SET tries = tries + 1 WHERE video_id=?", (vid,))
        if not work:
            clap.unload_if_idle()
            time.sleep(10)


if __name__ == "__main__":
    main()
