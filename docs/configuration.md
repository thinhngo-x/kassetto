# Configuration

Everything is set with environment variables, in `.env` (start from [`.env.example`](../.env.example), which lists
them all with comments). All are optional. Older installs: each `KASSETTO_X` also reads `YTM_X`.

| Setting | Default | What it does |
|---|---|---|
| `PUID`, `PGID` | `1000` | user / group the containers run as (own `./data`, `./models`) |
| `TZ` | `UTC` | time zone: weekly / daily lists, time-of-day taste |
| `KASSETTO_OWNER` | `admin` | the owner's user name |
| `KASSETTO_AUTH` | `none` | `none` (one person) or `proxy` ([sign-in.md](sign-in.md)) |
| `KASSETTO_TRUSTED_PROXIES` | — | with `proxy`, required: the proxy's addresses / networks, comma-separated |
| `KASSETTO_AUTH_HEADER` | `Remote-User` | header with the user name (proxy mode) |
| `KASSETTO_AUTH_NAME_HEADER` | `Remote-Name` | header with the display name (proxy mode) |
| `KASSETTO_LANGUAGE` | `en` | YouTube Music's language |
| `KASSETTO_LOCATION` | YouTube Music's default | country code for the catalogue and home feed |
| `KASSETTO_REGION` | off | extra regional content: charts; for known regions (`VN`) also local-language shelves |
| `KASSETTO_REGION_NAME` | — | display name for a region Kassetto doesn't know |
| `KASSETTO_CACHE_MB` | `3000` | audio cache size |
| `KASSETTO_TARGET_LUFS` | `-14` | loudness levelling target (with the embed service) |
| `KASSETTO_YTDLP_UPDATE` | off | `1`: the newest yt-dlp at start, into `data/.yt-dlp` |
| `KASSETTO_EXPLORE` | `0.3` | how much the recommender tries what it's unsure of (Thompson draw scale; `0` = never) |
| `KASSETTO_SPEAKER` | — | a fixed Cast speaker address ([cast.md](cast.md)) |
| `KASSETTO_SPEAKER_NAME` | `Speaker` | its display name |
| `KASSETTO_STREAM_BASE` | guessed with host networking | how the speaker reaches port 8091, e.g. `http://192.168.1.10:8091` |
| `LISTENBRAINZ_USER`, `LISTENBRAINZ_USER_TOKEN` | — | the owner's ListenBrainz account |
| `KASSETTO_EMBED_URL` | `http://kassetto-embed:8099` | where the embed service is |
| `EMBED_THREADS` | `2` | embed service: CPU threads |
| `IDLE_UNLOAD` | `600` | embed service: free the model after this many idle seconds |
| `KASSETTO_DB`, `KASSETTO_CACHE`, `KASSETTO_PEOPLE` | under `/data` | file locations inside the container |

People and circles (names, taste blend, who owns the speaker, ListenBrainz per person) are edited by the owner in
Settings → People, and stored in `data/people.json`.
