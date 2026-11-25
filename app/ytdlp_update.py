"""Optional: the newest yt-dlp at startup (KASSETTO_YTDLP_UPDATE=1).

YouTube changes often and an old yt-dlp stops working; the images are rebuilt weekly with the newest one, but
between rebuilds this keeps a running install going. The container's filesystem is read-only, so the update goes
to /data/.yt-dlp (KASSETTO_YTDLP_DIR) and is put first on the import path, for this process and the ones it starts
(the speaker player). Import this module before yt_dlp. A failed update is logged and the built-in version used.
"""
import os, subprocess, sys, time

from config import env

if env("YTDLP_UPDATE", "") in ("1", "true", "yes"):
    target = env("YTDLP_DIR", "/data/.yt-dlp")
    stamp = os.path.join(target, ".updated")
    try:
        fresh = time.time() - os.path.getmtime(stamp) < 12 * 3600   # at most twice a day (restarts don't hammer PyPI)
    except OSError:
        fresh = False
    if not fresh:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                            "--no-cache-dir", "--upgrade", "--target", target, "yt-dlp[default]"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            open(stamp, "w").close()
        else:
            print("yt-dlp update failed, using the built-in version:", (r.stderr or r.stdout)[-300:], flush=True)
    if os.path.isdir(os.path.join(target, "yt_dlp")):
        sys.path.insert(0, target)
        os.environ["PYTHONPATH"] = target + os.pathsep + os.environ.get("PYTHONPATH", "")
