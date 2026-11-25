# Sign-in

Kassetto has no passwords of its own. Pick one mode with `KASSETTO_AUTH`:

## `none` (default): one person, no sign-in

Every request is the owner (`KASSETTO_OWNER`, default `admin`). Any user header is ignored. **Anyone who can reach
port 8090 is you**: keep it on your home network or behind a VPN, never open to the internet.

## `proxy`: several people, behind a sign-in proxy

Put Kassetto behind a proxy that signs people in and passes the user name in a header:

```env
KASSETTO_AUTH=proxy
KASSETTO_TRUSTED_PROXIES=172.18.0.0/16      # the proxy's address or network (comma-separated); required
KASSETTO_AUTH_HEADER=Remote-User           # default
KASSETTO_AUTH_NAME_HEADER=Remote-Name      # display name, optional; default
```

- The header is only accepted from `KASSETTO_TRUSTED_PROXIES`. A request from anywhere else gets 403, and one
  without the header 401. Kassetto refuses to start in this mode without trusted networks.
- Your proxy must **set** the header on every request it forwards (overwriting anything the browser sent). Forward-auth
  setups do this.
- Each new user name becomes a *person* with their own taste on their first visit. The owner manages people and
  circles in Settings.
- Only `/healthz` is open without a user (for container health checks).

Header names for common proxies:

| Proxy | `KASSETTO_AUTH_HEADER` | `KASSETTO_AUTH_NAME_HEADER` |
|---|---|---|
| Authelia (forward auth) | `Remote-User` | `Remote-Name` |
| Authentik (proxy provider / forward auth) | `X-authentik-username` | `X-authentik-name` |
| oauth2-proxy (`--pass-user-headers`) | `X-Forwarded-Preferred-Username` or `X-Forwarded-User` | — |
| oauth2-proxy with nginx `auth_request` (`--set-xauthrequest`) | `X-Auth-Request-User` | — |

## `dev`: development only

Used by `docker-compose.dev.yml`: the header is trusted from anywhere, and no header means the owner. Never use it
for a real install; Kassetto logs a warning when it runs this way.

## The audio port (8091)

Speakers (Chromecast / Nest) can't sign in, so they fetch audio from a second port. Everything there is locked to
the speaker: stream and prefetch URLs carry a token that only Kassetto's own speaker player gets (a random key kept
in the database), so other devices on the network can't use the port to make your server download. The port has to
be reachable from the speakers, so keep it on your local network.
