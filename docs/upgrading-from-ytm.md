# Upgrading from "ytm" (the app's name before Kassetto)

An install from before the rename keeps working with its data. Check these when you switch to the Kassetto images:

| What | Before | Now | To keep the old behaviour |
|---|---|---|---|
| Settings | `YTM_*` variables | `KASSETTO_*` | nothing: `YTM_*` is still read when the `KASSETTO_*` one is unset |
| Database | `/data/ytm.db` | `/data/kassetto.db` | nothing: an existing `ytm.db` is used as long as there is no `kassetto.db` |
| Embed service | host `ytm-embed` | `kassetto-embed` | rename the service, or set `KASSETTO_EMBED_URL=http://ytm-embed:8099` |
| Container user | `1004:1004` | `1000:1000` | set `user: "<uid>:<gid>"` (the owner of your data volume) on both services |
| Catalogue location | `FR` by default | YouTube Music's default | `KASSETTO_LOCATION=FR` (any country code) |
| Vietnam home content | always on | off | `KASSETTO_REGION=VN` |
| ListenBrainz client name | `ytm` | `kassetto` | nothing: listens sent under either name are recognised as Kassetto's own |

The web app's offline cache is renamed, so browsers fetch the page once more after the upgrade. Plays stored
before and after the rename look the same in the database (`plays.source = 'ytm'` still means "played here").
