import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa
from .taste import taste

# ---------- sound model (CLAP embeddings from ytm-embed) ----------


EMB = {"ts": 0, "vecs": {}}            # video_id -> float32 unit vector (refreshed every 60 s)


def track_meta_put(songs):
    """Remember metadata of songs ytm has seen, so embedded tracks can be offered later."""
    rows = [(t["videoId"], t.get("title"), t.get("artist"), t.get("album"), t.get("thumb"), t.get("duration"))
            for t in songs if t.get("videoId")]
    if rows:
        with LOCK, db() as c:
            c.executemany("INSERT OR REPLACE INTO tracks VALUES(?,?,?,?,?,?)", rows)


def embeddings():
    if time.time() - EMB["ts"] > 60:
        with db() as c:
            try:
                rows = c.execute("SELECT video_id, vec FROM emb WHERE vec IS NOT NULL").fetchall()
            except sqlite3.OperationalError:
                rows = []
        raw = {v: np.frombuffer(b, dtype=np.float16).astype(np.float32) for v, b in rows}
        EMB["raw"] = raw                                         # uncentred: for text<->audio (CLAP joint space)
        if raw:
            # CLAP vectors are anisotropic (any two songs ~0.96 cosine): centre on the mean of everything
            # fingerprinted so far, renormalise -> similarities spread over -1..1 and mean something
            ids = list(raw); V = np.stack([raw[v] for v in ids]); V = V - V.mean(0)
            V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-9
            raw = dict(zip(ids, V))
        EMB.update(ts=time.time(), vecs=raw)
    return EMB["vecs"]


def enqueue(vids_prio):
    if not vids_prio:
        return
    with LOCK, db() as c:
        try:
            c.executemany("INSERT OR IGNORE INTO emb_queue(video_id, prio, ts) VALUES(?,?,?)",
                          [(v, p, int(time.time())) for v, p in vids_prio])
        except sqlite3.OperationalError:
            pass


def kmeans(X, w, k, iters=25, seed=0):
    """Spherical k-means (unit vectors, cosine), weighted."""
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), k, replace=False)]
    for _ in range(iters):
        lab = (X @ C.T).argmax(1)
        newC = np.stack([(X[lab == j] * w[lab == j, None]).sum(0) if (lab == j).any() else C[j] for j in range(k)])
        newC /= np.linalg.norm(newC, axis=1, keepdims=True) + 1e-9
        if np.allclose(newC, C):
            break
        C = newC
    return C, (X @ C.T).argmax(1)


def silhouette(X, lab):
    if len(set(lab)) < 2:
        return -1
    D = 1 - X @ X.T
    s = []
    for i in range(len(X)):
        same = lab == lab[i]
        a = D[i, same].sum() / max(1, same.sum() - 1)
        b = min(D[i, lab == j].mean() for j in set(lab) if j != lab[i])
        s.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(s))


def sound_model():
    """-> {clusters: [(centroid, weight, [vids])], neg: vector|None, mu, sd} or None (not enough data)."""
    E = embeddings()
    now = time.time()
    with db() as c:
        likes = mine_or_peers(c.execute("SELECT video_id, pref, user FROM prefs").fetchall(), 2)
    pos, neg = {}, {}
    _, vids, _ = taste()
    for v, st in vids.items():                                    # graded per-track score (listens + signals)
        if st["score"] > 0.5:
            pos[v] = pos.get(v, 0) + st["score"]
        elif st["score"] < -0.5:
            neg[v] = neg.get(v, 0) - st["score"]
    for v, p, u in likes:
        (pos if p > 0 else neg)[v] = (pos if p > 0 else neg).get(v, 0) + (2.5 if p > 0 else 1.0) * uw(u)
    enqueue([(v, 10.0) for v in pos if v not in E])            # your favourites get fingerprinted first
    P = [v for v in pos if v in E]
    if len(P) < 3:
        return None
    X = np.stack([E[v] for v in P]); w = np.array([pos[v] for v in P])
    best = (None, None, -2)
    for k in range(1, min(4, len(P) // 3) + 1):
        C, lab = kmeans(X, w, k)
        sc = silhouette(X, lab) if k > 1 else 0.05                # k=1 wins unless clusters are clearly separated
        if sc > best[2]:
            best = (C, lab, sc)
    C, lab, _ = best
    clusters = [(C[j], float(w[lab == j].sum()), [P[i] for i in np.where(lab == j)[0]]) for j in range(len(C))]
    N = [v for v in neg if v in E and v not in pos]
    negv = None
    if N:
        negv = np.average(np.stack([E[v] for v in N]), axis=0, weights=[neg[v] for v in N])
        negv /= np.linalg.norm(negv) + 1e-9
    allv = np.stack(list(E.values()))
    raw = (allv @ C.T).max(1) - (0.5 * (allv @ negv) if negv is not None else 0)
    return {"clusters": clusters, "neg": negv, "mu": float(raw.mean()), "sd": float(raw.std() + 1e-6)}


def sound_score(model, vec):
    """Closeness to your nearest taste cluster minus closeness to what you skip, normalised to about -1..1."""
    C = np.stack([c for c, _, _ in model["clusters"]])
    raw = float((C @ vec).max() - (0.5 * float(model["neg"] @ vec) if model["neg"] is not None else 0))
    return math.tanh((raw - model["mu"]) / model["sd"] / 1.5)


def sounds_like(model, exclude, n=15):
    """Nearest embedded tracks to each taste cluster (with known metadata) -> song dicts."""
    E = embeddings()
    vids = [v for v in E if v not in exclude]
    if not vids:
        return []
    X = np.stack([E[v] for v in vids])
    picks = []
    for c, wt, _ in model["clusters"]:
        sims = X @ c
        for i in np.argsort(-sims)[: n]:
            picks.append((float(sims[i]), vids[i]))
    picks = sorted(set(picks), reverse=True)
    with db() as c:
        meta = {r[0]: r for r in c.execute(
            f"SELECT * FROM tracks WHERE video_id IN ({','.join('?' * len(picks))})", [v for _, v in picks])} if picks else {}
    out = []
    for _, v in picks:
        m = meta.get(v)
        if m and m[1]:
            out.append({"type": "song", "videoId": v, "title": m[1], "artist": m[2] or "", "album": m[3] or "",
                        "thumb": m[4], "duration": m[5]})
    return out[: n * 2]


def cluster_seeds(anchors, k_each=1):
    """One or two favourites from each taste cluster (for mixes), else None."""
    m = sound_model()
    if not m:
        return None
    E = embeddings()
    seeds = []
    for c, _, members in m["clusters"]:
        ms = sorted(members, key=lambda v: -float(E[v] @ c))
        seeds += ms[:k_each] + random.sample(ms[k_each:], min(1, len(ms[k_each:])))
    return seeds


VI_CHARS = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)


def daily_groups(max_groups=4, min_size=3):
    """Your favourites split into taste groups for the Daily Mixes: [[video id, ...], ...], biggest first.
    Groups = the sound model's clusters (members nearest the centre first); without a sound model yet, the
    favourites split by language (Vietnamese titles/artists vs the rest)."""
    m = sound_model()
    if m and len(m["clusters"]) >= 2:
        E = embeddings()
        groups = [(w, sorted(ms, key=lambda v: -float(E[v] @ c))) for c, w, ms in m["clusters"]]
        groups = [g for _, g in sorted(groups, key=lambda x: -x[0]) if len(g) >= min_size]
        if len(groups) >= 2:
            return groups[:max_groups]
    _, vids, anchors = taste()
    fav = list(dict.fromkeys(anchors + sorted((v for v in vids if vids[v]["score"] > 0.5), key=lambda v: -vids[v]["score"])))
    with db() as c:
        meta = {v: f"{t} {a}" for v, t, a in c.execute(
            f"SELECT video_id, title, artist FROM tracks WHERE video_id IN ({','.join('?' * len(fav))})", fav)} if fav else {}
    vi = [v for v in fav if VI_CHARS.search(meta.get(v, ""))]
    other = [v for v in fav if v not in set(vi)]
    groups = [g for g in (vi, other) if len(g) >= min_size]
    return sorted(groups, key=len, reverse=True) or ([fav] if len(fav) >= min_size else [])
