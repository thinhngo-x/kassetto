"""Who is listening. Sign-in modes (KASSETTO_AUTH):

  none   (default) one person, no sign-in: every request is the owner (KASSETTO_OWNER), the user header is ignored.
         Anyone who can reach port 8090 is the owner: keep it on a private network.
  proxy  behind a sign-in proxy (Authelia, Authentik, oauth2-proxy, …) that sets a user header
         (KASSETTO_AUTH_HEADER, default Remote-User; display name: KASSETTO_AUTH_NAME_HEADER, default Remote-Name).
         The header is accepted only from KASSETTO_TRUSTED_PROXIES (comma-separated addresses / networks, required);
         requests from anywhere else are refused, and requests without the header too. New people are registered
         on their first visit.
  dev    development only (docker-compose.dev.yml): the header is trusted from anywhere, no header = the owner.

The audio-only port (8091) is for the speaker, which can't sign in: /stream and /prefetch there need a token
(config.stream_token) under a key kept in the database, which castplayer.py gets from the app.
"""
import hmac, ipaddress, re, secrets, sqlite3

from aiohttp import web

import people
import recommend as rec
from config import env, stream_token

MODES = ("none", "proxy", "dev")
MODE = (env("AUTH", "none") or "none").lower()
HEADER = env("AUTH_HEADER", "Remote-User")
NAME_HEADER = env("AUTH_NAME_HEADER", "Remote-Name")
TRUSTED = [ipaddress.ip_network(x.strip(), strict=False) for x in (env("TRUSTED_PROXIES", "") or "").split(",") if x.strip()]
USER_RE = re.compile(r"[\w.@+-]{1,64}")
OPEN_PATHS = {"/healthz"}


def check_config():
    """-> a warning to log, or raises SystemExit for a setup that would be unsafe."""
    if MODE not in MODES:
        raise SystemExit(f"KASSETTO_AUTH={MODE!r}: use one of {', '.join(MODES)}")
    if MODE == "proxy" and not TRUSTED:
        raise SystemExit("KASSETTO_AUTH=proxy needs KASSETTO_TRUSTED_PROXIES (the sign-in proxy's address or network)")
    if MODE == "dev":
        return "KASSETTO_AUTH=dev: the user header is trusted from anywhere. For development only."
    return None


def _trusted(addr):
    try:
        ip = ipaddress.ip_address((addr or "").split("%")[0])
    except ValueError:
        return False
    return any(ip in n for n in TRUSTED)


def identify(req):
    """-> (user, display name or None) for this request, or raises 401 / 403."""
    if MODE == "none":
        return people.owner(), None
    raw = req.headers.get(HEADER, "")
    if MODE == "proxy":
        if not _trusted(req.remote):
            raise web.HTTPForbidden(text="sign in through the sign-in proxy")
        if not raw:
            raise web.HTTPUnauthorized(text=f"no {HEADER} header from the sign-in proxy")
    user = (raw or people.owner()).strip().lower()
    if not USER_RE.fullmatch(user):
        raise web.HTTPBadRequest(text="unusable user name")
    return user, req.headers.get(NAME_HEADER) or None


# ---------- the audio-only port ----------

_KEY = {}


def stream_key():
    """A random key made once and kept in the database (it survives restarts: a running speaker queue keeps working)."""
    if "k" not in _KEY:
        with rec.db() as c:
            r = c.execute("SELECT v FROM kv WHERE k='stream_key'").fetchone()
            if not r:
                k = secrets.token_hex(16)
                try:
                    c.execute("INSERT INTO kv VALUES('stream_key', ?)", (k,))
                except sqlite3.IntegrityError:
                    pass
                r = c.execute("SELECT v FROM kv WHERE k='stream_key'").fetchone()
        _KEY["k"] = r[0]
    return _KEY["k"]


def check_stream_token(req):
    vid = req.match_info.get("vid", "")
    if not hmac.compare_digest(req.query.get("t", ""), stream_token(stream_key(), vid)):
        raise web.HTTPForbidden(text="the audio port serves the speaker only")
