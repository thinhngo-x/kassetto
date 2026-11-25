"""People and circles: who uses ytm and what they share.

Anyone Authelia lets into ytm (group `music`) is a *person*, auto-registered on first visit with their own,
separate taste. *Circles* (a household, a couple, friends…) group people; each circle has:

  blend    0..1: how much the other members' listening counts in each member's taste (0 = taste stays personal;
           shared playlists / stats still work). A person in several circles gets the highest blend per peer.
  speaker  true for the circle that owns the Cast speaker (Nest): only its members can cast to it, and its
           wake-up music setting belongs to the circle.
  concerts true for the circle whose artists "Concerts near you" looks up (one circle).

ListenBrainz per person: `"listenbrainz": {"user_env": "...", "token_env": "..."}` = own account (names of
variables in the .env file), or `"scrobble_as": "<person>"` = scrobble into that person's account (merged taste,
e.g. a partner without an account), or nothing = not scrobbled.

Stored in /data/people.json (it holds names: keep it out of git). Edited in ytm (owner only:
Settings → People & circles) or by hand; reloaded when the file changes.
"""
import json, os, threading, time

PATH = os.environ.get("YTM_PEOPLE", "/data/people.json")
OWNER_ENV = os.environ.get("YTM_OWNER", "admin")
_LOCK = threading.Lock()
_C = {"mtime": None, "cfg": None}


def _default():
    """First start: reproduce the original two-person setup (owner + one partner, blend 0.6, merged LB)."""
    partner = os.environ.get("YTM_PARTNER", "")
    people = {OWNER_ENV: {"name": os.environ.get("YTM_OWNER_NAME", OWNER_ENV),
                          "listenbrainz": {"user_env": "LISTENBRAINZ_USER", "token_env": "LISTENBRAINZ_USER_TOKEN"}}}
    circles = {}
    if partner:
        people[partner] = {"name": os.environ.get("YTM_PARTNER_NAME", partner), "scrobble_as": OWNER_ENV}
        circles["home"] = {"name": "Home", "members": [OWNER_ENV, partner],
                           "blend": float(os.environ.get("YTM_PARTNER_WEIGHT", "0.6")), "speaker": True, "concerts": True}
    else:
        circles["home"] = {"name": "Home", "members": [OWNER_ENV], "blend": 0.6, "speaker": True, "concerts": True}
    return {"owner": OWNER_ENV, "people": people, "circles": circles,
            "concerts": {"city": "", "lat": None, "lon": None, "radius_km": 150}}   # set your area to enable concerts


def cfg():
    with _LOCK:
        try:
            m = os.path.getmtime(PATH)
        except OSError:
            m = None
        if m is None:
            c = _default(); _save(c); m = os.path.getmtime(PATH)
            _C.update(mtime=m, cfg=c)
        elif m != _C["mtime"]:
            try:
                _C.update(mtime=m, cfg=json.load(open(PATH)))
            except ValueError:                     # half-written by hand: keep the last good one
                pass
        return _C["cfg"]


def _save(c):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH + ".tmp", "w") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    os.replace(PATH + ".tmp", PATH)


def save(c):
    with _LOCK:
        _save(c)
        _C.update(mtime=os.path.getmtime(PATH), cfg=c)


def owner():
    return cfg().get("owner") or OWNER_ENV


def name(u):
    return (cfg()["people"].get(u) or {}).get("name") or u


def register(u, display=None):
    """First visit of someone Authelia let in: a person with their own taste, in no circle yet."""
    c = cfg()
    if u in c["people"]:
        if display and c["people"][u].get("name") in (None, u):
            c["people"][u]["name"] = display; save(c)
        return
    c["people"][u] = {"name": display or u, "joined": int(time.time())}
    save(c)


def circles_of(u):
    return {k: v for k, v in cfg()["circles"].items() if u in v.get("members", [])}


def peers(u):
    """{person: weight} whose data shapes u's taste: u itself 1.0, circle-mates at the circle's blend (max)."""
    out = {u: 1.0}
    for ci in circles_of(u).values():
        b = float(ci.get("blend") or 0)
        if b > 0:
            for m in ci["members"]:
                if m != u:
                    out[m] = max(out.get(m, 0), b)
    return out


def mates(u):
    """Everyone u shares at least one circle with (any blend): who sees u's shared playlists / circle stats."""
    return {m for ci in circles_of(u).values() for m in ci["members"]} - {u}


def lb_account(u, _seen=None):
    """-> (ListenBrainz user, token, owning person) for u: own account, or the one u scrobbles as; else Nones."""
    p = cfg()["people"].get(u) or {}
    lb = p.get("listenbrainz") or {}
    if lb.get("user_env") or lb.get("token_env"):
        return os.environ.get(lb.get("user_env", ""), ""), os.environ.get(lb.get("token_env", ""), ""), u
    t = p.get("scrobble_as")
    if t and t != u and t not in (_seen or set()):
        return lb_account(t, (_seen or set()) | {u})
    return "", "", None


def lb_accounts():
    """Every own ListenBrainz account: [(person, lb user, token)] (for pulling listens)."""
    out = []
    for u, p in cfg()["people"].items():
        lb = p.get("listenbrainz") or {}
        user = os.environ.get(lb.get("user_env", ""), "")
        if user:
            out.append((u, user, os.environ.get(lb.get("token_env", ""), "")))
    return out


def speaker_circle():
    return next((k for k, v in cfg()["circles"].items() if v.get("speaker")), None)


def can_cast(u):
    sc = speaker_circle()
    return sc is None or u in cfg()["circles"][sc].get("members", []) or u == owner()


def concerts_circle():
    return next((k for k, v in cfg()["circles"].items() if v.get("concerts")), None)


def public(u):
    """What the page needs to know about the viewer."""
    own, _, via = lb_account(u)
    return {"user": u, "name": name(u), "owner": u == owner(), "can_cast": can_cast(u),
            "listenbrainz": ("own" if via == u else f"as {name(via)}") if own else "off",   # no LB user set = off
            "blend": [{"user": m, "name": name(m), "weight": w} for m, w in peers(u).items() if m != u],
            "circles": [{"id": k, "name": v.get("name", k), "blend": v.get("blend", 0), "speaker": bool(v.get("speaker")),
                         "members": [{"user": m, "name": name(m)} for m in v.get("members", [])]}
                        for k, v in circles_of(u).items()]}
