"""Shared state for the recommender: database, who is listening, text normalisation."""
import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

DB = os.environ.get("YTM_DB", "/data/ytm.db")
OWNER = os.environ.get("YTM_OWNER", "admin")
import contextvars
import people
USER = contextvars.ContextVar("user", default=OWNER)


def me():
    return USER.get()


def uw(row_user):
    """Your own data counts fully, circle-mates' at their circle's blend, everyone else's not at all (people.py)."""
    return people.peers(me()).get(row_user or OWNER, 0.0)


def mine_or_peers(rows, ucol):
    """Keep only rows from people whose data shapes my taste (weight > 0)."""
    P = people.peers(me())
    return [r for r in rows if (r[ucol] or OWNER) in P]
HALF_LIFE_DAYS = 45
W = {"complete": 1.0, "partial": 0.4, "skip": -1.0, "lb": 0.7}
LOCK = threading.Lock()


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def migrate_users(c):
    cols = lambda t: {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
    for t in ("plays", "signals"):
        if t in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")} and "user" not in cols(t):
            c.execute(f"ALTER TABLE {t} ADD COLUMN user TEXT DEFAULT '{OWNER}'")
    if "user" not in cols("prefs"):
        c.executescript(f"""
        CREATE TABLE prefs_u(user TEXT, video_id TEXT, title TEXT, artist TEXT, pref INTEGER, ts INTEGER,
                             PRIMARY KEY(user, video_id));
        INSERT INTO prefs_u SELECT '{OWNER}', video_id, title, artist, pref, ts FROM prefs;
        DROP TABLE prefs; ALTER TABLE prefs_u RENAME TO prefs;""")


def init():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS plays(id INTEGER PRIMARY KEY, ts INTEGER, video_id TEXT, title TEXT, artist TEXT,
            album TEXT, duration INTEGER, played INTEGER, event TEXT, source TEXT, UNIQUE(source, ts, title, artist));
        CREATE INDEX IF NOT EXISTS plays_ts ON plays(ts);
        CREATE INDEX IF NOT EXISTS plays_vid ON plays(video_id);
        CREATE TABLE IF NOT EXISTS prefs(video_id TEXT PRIMARY KEY, title TEXT, artist TEXT, pref INTEGER, ts INTEGER);
        CREATE TABLE IF NOT EXISTS cf_map(mbid TEXT PRIMARY KEY, video_id TEXT, title TEXT, artist TEXT, ts INTEGER);
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS lyrics(video_id TEXT PRIMARY KEY, data TEXT, ts INTEGER);
        CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, ts INTEGER, video_id TEXT, artist TEXT, kind TEXT,
            value REAL, hour INTEGER);
        CREATE INDEX IF NOT EXISTS signals_ts ON signals(ts);
        CREATE TABLE IF NOT EXISTS tracks(video_id TEXT PRIMARY KEY, title TEXT, artist TEXT, album TEXT, thumb TEXT, duration INTEGER);
        CREATE TABLE IF NOT EXISTS emb(video_id TEXT PRIMARY KEY, vec BLOB, model TEXT, ts INTEGER);
        CREATE TABLE IF NOT EXISTS emb_queue(video_id TEXT PRIMARY KEY, prio REAL, ts INTEGER, tries INTEGER DEFAULT 0);
        INSERT OR IGNORE INTO tracks(video_id, title, artist) SELECT video_id, title, artist FROM prefs WHERE title IS NOT NULL;
        INSERT OR IGNORE INTO tracks(video_id, title, artist, album, duration)
            SELECT video_id, title, artist, album, duration FROM plays WHERE video_id IS NOT NULL AND title IS NOT NULL;
        """)
        migrate_users(c)
    from . import learn                                          # impressions (the learning ranker)
    learn.init()


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("đ", "d")
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", s)).strip()


def split_artists(a):
    parts = re.split(r",| & | x | feat\.? | ft\.? | và | and ", a or "", flags=re.I)   # "Soap&Skin" stays one artist
    return [p for p in (norm(x) for x in parts) if p]

def listen_weight(played, duration, event):
    """How much a listen says, from the share actually heard (not just complete/partial/skip)."""
    if not duration:
        return {"complete": 1.0, "partial": 0.3, "skip": -1.0}.get(event, 0)
    r = max(0.0, min(1.0, (played or 0) / duration))
    if r >= 0.8:
        return 1.0
    if (played or 0) < 10:
        return -1.2                                           # rejected in the first seconds
    if r < 0.3:
        return -0.6 + r                                       # gave it a chance, then left
    return 0.2 + (r - 0.3)                                    # most of it: mildly positive
