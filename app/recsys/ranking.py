import json, math, os, random, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request

import numpy as np

from .core import *  # noqa
from .bandit import ARMS, bandit
from .events import boredom, prefs
from .sound import embeddings, enqueue, sound_model, sound_score, sounds_like, track_meta_put
from .taste import taste
from . import learn, session as sess

# ---------- ranking ----------

FLOW_WINDOW = 4          # flow ordering may pull a pick at most this many places forward


def _title_map(vids):
    vids = [v for v in vids if v]
    if not vids:
        return {}
    with db() as c:
        return {v: t for v, t in c.execute(
            f"SELECT video_id, title FROM tracks WHERE video_id IN ({','.join('?' * len(vids))})", vids)}


def _key_title(t):
    return norm(_clean_title(t))


def _clean_title(t):
    return re.sub(r"\s*[\(\[].*?[\)\]]|\s+-\s+.*$", "", t or "").strip() or (t or "")


def rank(seed_radio, anchor_radios, cf_songs, exclude, n=25, extra=None, hour=None, sound=True, ctx="rank", flow_from=None):
    """Candidates from several sources -> features -> learned score -> each slot goes to the source (arm) that wins a
    Thompson draw (diversity, familiarity cap, boredom) -> ordered for flow. Each pick says why ("because …")."""
    aff, vids, _ = taste(hour)
    pref = prefs()
    E = embeddings()
    model = sound_model()
    b = boredom()                                                # 0..1: lean away from the familiar when high
    sp = sess.profile()                                          # this listening session
    w, _ = learn.weights()
    cand = {}

    def add(lst, weight, source):
        L = max(1, len(lst))
        origin = lst[0]["videoId"] if lst and source in ("similar", "taste") else None   # a radio starts with its seed
        for i, t in enumerate(lst):
            v = t["videoId"]
            if v in exclude or pref.get(v, 0) < 0 or vids.get(v, {}).get("rej", 0) >= 2:
                continue
            sim = weight * (1 - i / L) + 0.05
            if v not in cand or cand[v]["sim"] < sim:
                cand[v] = {"t": t, "sim": sim, "src": source, "origin": origin if origin != v else None}

    add(seed_radio, 1.0, "similar")
    for r in anchor_radios:
        add(r, 0.55, "taste")
    add(cf_songs, 0.7, "cf")
    if model and sound:                                          # off for Daily Mixes: global, the same in every mix
        add(sounds_like(model, exclude | set(cand)), 0.6, "sound")
    for lst, wgt, src in extra or []:
        add(lst, wgt, src)
    track_meta_put([c["t"] for c in cand.values()])
    members = [m for _, _, ms in model["clusters"] for m in ms] if model else []
    M = np.stack([E[m] for m in members]) if members else None
    members_t = {m: _key_title(x) for m, x in _title_map(members).items()}
    missing, scored = [], []
    for v, c in cand.items():
        t = c["t"]
        arts = split_artists(t.get("artist"))
        a = sum(aff.get(x, 0) for x in arts) / max(1, len(arts))
        known_artist = any(x in aff for x in arts)
        s = vids.get(v, {})
        vec = E.get(v)
        snd = sound_score(model, vec) if model and vec is not None else 0.0
        if vec is None:
            missing.append((v, c["sim"]))
        f = {"bias": 1.0, "sim": c["sim"], "aff": math.tanh(a / 3), "snd": snd, "sess": sess.sess_score(sp, vec),
             "sess_art": sess.sess_artist(sp, arts), "new_artist": 0.0 if known_artist else 1.0,
             "recent": min(3, s.get("recent", 0)), "skips": min(2.0, s.get("skips", 0)), "liked": 1.0 if pref.get(v) == 1 else 0.0}
        base = learn.score(f, w)
        # boredom reshapes the learned score for now (less similarity / familiarity, more new artists, more chance)
        score = (base - b * (0.4 * w["sim"] * f["sim"] + 0.5 * w["aff"] * f["aff"]) + 0.5 * b * f["new_artist"]
                 + random.uniform(0, 0.1 + 0.4 * b))
        familiar = pref.get(v) == 1 or s.get("score", 0) > 0.5
        arm = "familiar" if familiar else ("discovery" if not known_artist else c["src"])
        near = None
        if c["src"] == "sound" and M is not None and vec is not None:
            for j in np.argsort(-(M @ vec))[:4]:                 # nearest favourite that isn't this song (any version)
                if members[j] != v and members_t.get(members[j]) != _key_title(t.get("title")):
                    near = members[j]; break
        scored.append({"score": score, "base": base, "v": v, "t": t, "art": arts[0] if arts else "", "arm": arm, "f": f,
                       "vec": vec, "origin": c["origin"], "near": near, "liked": pref.get(v) == 1})
    enqueue(sorted(missing, key=lambda x: -x[1])[:30])          # the embed service fingerprints these over time
    scored.sort(key=lambda x: -x["score"])
    seen_keys, uniq = set(), []                                  # same song uploaded twice -> keep the best-scored one
    for x in scored:
        k = (norm(re.sub(r"\(.*?\)|\[.*?\]| - .*$", "", x["t"].get("title") or "")), x["art"])
        if k not in seen_keys:
            seen_keys.add(k); uniq.append(x)
    scored = uniq
    B = bandit()
    chosen, per_artist, last_artist, fam = [], {}, None, 0
    pool = scored[:]
    while pool and len(chosen) < n:
        def ok(x):
            if x["art"] and (x["art"] == last_artist or per_artist.get(x["art"], 0) >= (2 if b > 0.5 else 3)):
                return False
            return not (x["arm"] == "familiar" and fam + 1 > max(1, (0.35 - 0.25 * b) * (len(chosen) + 1)))
        avail = {x["arm"] for x in pool if ok(x)}
        if not avail:
            break
        arm = max(avail, key=lambda a: random.betavariate(*B[a]))
        x = next(x for x in pool if x["arm"] == arm and ok(x))
        pool.remove(x)
        chosen.append(x)
        per_artist[x["art"]] = per_artist.get(x["art"], 0) + 1
        last_artist = x["art"]
        fam += x["arm"] == "familiar"
    chosen = flow(chosen, E.get(flow_from) if flow_from else None)
    titles = _title_map([x["origin"] for x in chosen] + [x["near"] for x in chosen])
    picks = []
    for x in chosen:
        picks.append({**x["t"], "auto": True, "why": ARMS[x["arm"]], "because": because(x, titles, vids.get(x["v"], {})),
                      "_f": x["f"], "_score": round(x["base"], 4)})
    learn.log_impressions(picks, ctx)
    for p in picks:
        p.pop("_f", None); p.pop("_score", None)
    return picks


def because(x, titles, st):
    """A specific reason for a pick, shown in the song menu / tooltip."""
    o = _clean_title(titles.get(x["origin"])) if x["origin"] else None
    near = _clean_title(titles.get(x["near"])) if x["near"] else None
    if x["arm"] == "familiar":
        return "One of your favourites" if x["liked"] else "You finished this before"
    if x["f"]["sess"] > 0.35 and x["f"]["sess_art"] >= 0:
        return "Fits what you're listening to now"
    if x["arm"] == "discovery":
        return f"New artist for you · close to {o or near}" if (o or near) else "New artist for you"
    if x["arm"] == "cf":
        return "Listeners with your taste play this"
    if near:
        return f"Sounds like {near}"
    if o:
        return f"Because you like {o}" if x["arm"] == "taste" else f"Similar to {o}"
    return None


def flow(chosen, start=None):
    """DJ-like order: each next song is the one (within a few places) that sounds closest to the previous one, so
    the mix moves smoothly instead of jumping between moods. Picks without a fingerprint keep their place;
    never the same artist twice in a row."""
    if len(chosen) < 3:
        return chosen
    rest, out = chosen[:], []
    prev = start
    while rest:
        win = rest[:FLOW_WINDOW]
        last_art = out[-1]["art"] if out else None
        cands = [x for x in win if not (x["art"] and x["art"] == last_art)] or win
        if prev is None or rest[0]["vec"] is None:
            x = cands[0]
        else:
            withv = [y for y in cands if y["vec"] is not None]
            x = max(withv, key=lambda y: float(y["vec"] @ prev)) if withv else cands[0]
        rest.remove(x); out.append(x)
        if x["vec"] is not None:
            prev = x["vec"]
    return _no_repeat(out)


def _no_repeat(out):
    """The greedy pass can run out of other artists near the end: move a same-artist neighbour to a place where it
    sits between two other artists."""
    art = lambda i: out[i]["art"] if 0 <= i < len(out) else None
    for i in range(1, len(out)):
        if not out[i]["art"] or out[i]["art"] != art(i - 1):
            continue
        x = out.pop(i)
        j = next((j for j in range(len(out) + 1) if x["art"] not in (art(j - 1), art(j))), None)
        out.insert(i if j is None else j, x)
    return out
