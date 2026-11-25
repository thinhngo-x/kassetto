"""Settings from the environment: KASSETTO_<NAME>, else YTM_<NAME> (installs from before the rename), else a
neutral default. Shared by the app and the embed service (copied into both images)."""
import os


def env(name, default=None):
    for k in (f"KASSETTO_{name}", f"YTM_{name}"):
        v = os.environ.get(k)
        if v not in (None, ""):
            return v
    return default


def _db_path():
    """/data/kassetto.db; an install from before the rename keeps its /data/ytm.db."""
    p = env("DB")
    if p:
        return p
    new, old = "/data/kassetto.db", "/data/ytm.db"
    return old if os.path.exists(old) and not os.path.exists(new) else new


DB = _db_path()
CACHE = env("CACHE", "/data/cache")
EMBED_URL = env("EMBED_URL", "http://kassetto-embed:8099").rstrip("/")
USER_AGENT = "Kassetto/0.1 (self-hosted music player)"
