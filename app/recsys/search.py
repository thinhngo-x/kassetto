import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa
from .events import prefs
from .sound import embeddings
from .taste import taste

# ---------- search intelligence ----------

LOW_QUALITY = re.compile(r"karaoke|tribute|\bcover\b|\b8d\b|nightcore|sped ?up|slowed|reverb|\bremix\b|instrumental|"
                         r"\bbeat\b|1 hour|10 hours|\bloop\b|ringtone|piano version|lyrics? video", re.I)


def _tokens(s):
    return [t for t in norm(s).split() if t]


def library_search(q, n=6):
    """Accent/typo-tolerant match against songs you liked or played (instant, local)."""
    import difflib
    qt = _tokens(q)
    if not qt:
        return []
    P = list(people.peers(me()))
    with db() as c:
        rows = c.execute("""SELECT t.video_id, t.title, t.artist, t.album, t.thumb, t.duration,
                                   COALESCE((SELECT pref FROM prefs p WHERE p.video_id = t.video_id AND p.user = ?), 0) AS pref,
                                   (SELECT COUNT(*) FROM plays p WHERE p.video_id = t.video_id AND p.event != 'skip') AS n
                            FROM tracks t WHERE t.video_id IN (SELECT video_id FROM prefs WHERE pref > 0 AND user IN ({ph})
                                                               UNION SELECT video_id FROM plays WHERE video_id IS NOT NULL
                                                               AND user IN ({ph}))""".format(ph=",".join("?" * len(P))),
                         (me(), *P, *P)).fetchall()
    out = []
    for v, title, artist, album, thumb, dur, pref, n_ in rows:
        if pref < 0 or not title:
            continue
        hay = _tokens(f"{title} {artist}")
        hit = 0.0
        for t in qt:                                             # each query word: exact, prefix, or fuzzy word match
            best = max((1.0 if h == t else 0.85 if h.startswith(t) and len(t) >= 2 else
                        difflib.SequenceMatcher(None, t, h).ratio() for h in hay), default=0)
            hit += best if best >= 0.75 else 0
        score = hit / len(qt)
        if score >= 0.7:
            out.append((score + 0.1 * (pref > 0) + 0.02 * min(5, n_), {
                "type": "song", "videoId": v, "title": title, "artist": artist or "", "album": album or "",
                "thumb": thumb or f"https://i.ytimg.com/vi/{v}/hqdefault.jpg", "duration": dur,
                "why": "liked" if pref > 0 else "played"}))
    return [x for _, x in sorted(out, key=lambda x: -x[0])[:n]]


def rerank_search(songs, q):
    """YouTube's order, nudged by your taste; low-quality uploads (karaoke, covers, sped up…) sink unless asked for;
    duplicates of the same song collapse."""
    aff, vids, _ = taste()
    pref = prefs()
    qlow = bool(LOW_QUALITY.search(q))
    scored, seen = [], set()
    L = max(1, len(songs))
    for i, t in enumerate(songs):
        if pref.get(t["videoId"], 0) < 0:
            continue
        arts = split_artists(t.get("artist"))
        a = sum(aff.get(x, 0) for x in arts) / max(1, len(arts))
        sc = (1 - i / L) + 0.35 * math.tanh(a / 3) + (0.3 if pref.get(t["videoId"]) == 1 else 0) \
             + (0.15 if vids.get(t["videoId"], {}).get("score", 0) > 0 else 0)
        if not qlow and LOW_QUALITY.search(f"{t.get('title')} {t.get('album') or ''}"):
            sc -= 0.8
        scored.append((sc, t))
    out = []
    base = lambda t: norm(re.sub(r"\(.*?\)|\[.*?\]| - .*$", "", t.get("title") or ""))
    first = {}
    for sc, t in sorted(scored, key=lambda x: -x[0]):           # the best-ranked artist "owns" a title; other
        first.setdefault(base(t), (split_artists(t.get("artist")) or [""])[0])   # artists' same-title songs = covers
    rescored = []
    for sc, t in scored:
        a0 = (split_artists(t.get("artist")) or [""])[0]
        rescored.append((sc - (0.45 if first.get(base(t)) not in (a0, None) and base(t) else 0), t))
    for sc, t in sorted(rescored, key=lambda x: -x[0]):
        k = (base(t), (split_artists(t.get("artist")) or [""])[0])
        if k in seen:
            continue
        seen.add(k); out.append(t)
    return out


def semantic(vec, n=20, text_mean=None):
    """Fingerprinted songs whose sound matches a CLAP text vector ('sad rainy piano').
    Both modalities are centred (audio on the mean of all fingerprints, text on the mean of reference prompts):
    raw CLAP text<->audio cosines are dominated by the modality offset and rank the same songs for any query."""
    E = embeddings()                                             # already centred + renormalised audio vectors
    if not E or vec is None:
        return []
    t = np.asarray(vec, dtype=np.float32)
    if text_mean is not None:
        t = t - np.asarray(text_mean, dtype=np.float32)
    t /= np.linalg.norm(t) + 1e-9
    ids = list(E); X = np.stack([E[v] for v in ids])
    sims = X @ t
    pref = prefs()
    order = [ids[i] for i in np.argsort(-sims)[: n * 3] if pref.get(ids[i], 0) >= 0]
    with db() as c:
        meta = {r[0]: r for r in c.execute(f"SELECT * FROM tracks WHERE video_id IN ({','.join('?' * len(order))})", order)} if order else {}
    out, seen = [], set()
    for v in order:
        m = meta.get(v)
        if not m or not m[1]:
            continue
        k = (norm(m[1]), (split_artists(m[2]) or [""])[0])
        if k in seen:
            continue
        seen.add(k)
        out.append({"type": "song", "videoId": v, "title": m[1], "artist": m[2] or "", "album": m[3] or "",
                    "thumb": m[4] or f"https://i.ytimg.com/vi/{v}/hqdefault.jpg", "duration": m[5], "why": "matches the vibe"})
        if len(out) >= n:
            break
    return out
