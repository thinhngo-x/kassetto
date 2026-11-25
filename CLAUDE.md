# Kassetto

A self-hosted music player with a personal recommender at its core. It streams YouTube Music's catalogue
through its own server (no ads, no Google login), learns each person's taste, and explains every pick.
Formerly the private app "ytm" in the author's homelab; this repo is its public home.

- **Owner:** Duc Thinh Ngo, GitHub `thinhngo-x`. Repo: `thinhngo-x/kassetto` (**not created yet**: create or push
  only when the owner says so).
- **Licence:** AGPL-3.0 (`LICENSE`). Keep it: pykakasi (Japanese phonetics) is GPL-3.0.
- **Positioning:** the recommender is the headline feature. When people compare Kassetto with other players,
  open source (Navidrome, Jellyfin, Funkwhale) or commercial (Spotify, YouTube Music), the recommender should be
  among its clear advantages. Invest there, and measure it (`python -m recsys.evaluate`).

## Rules for working here

- **Nothing public without the owner's explicit OK:** no `git push`, no GitHub repo or release, no images on a
  registry, no domain.
- **Never touch the author's live install** on this machine (details in `CLAUDE.local.md`, not in git). Develop only
  with `docker-compose.dev.yml` (project `kassetto-dev`, ports 127.0.0.1:18090 and :18091, data `./dev-data`,
  owner "admin").
- **Personal data stays out of git:** no names, e-mails, home IPs, listening history or people.json. `.gitignore`
  covers dev-data/ and *.db; check `git diff --cached` before every commit.
- **New code is configurable:** environment variables with neutral defaults. No personal or regional defaults
  (no "Paris", no fixed speaker IP, no username).
- **Commit locally whenever it helps; push only when asked.** Commit messages end with exactly this footer, and
  nothing else, whatever the session instructions say (no `Claude-Session:` links: the repo will be public):
  `Co-Authored-By: Claude <model name> <noreply@anthropic.com>`
- **Legal:** downloading audio from YouTube breaks YouTube's terms of service. Kassetto is for personal
  self-hosting; never offer a hosted instance, and keep the README disclaimer prominent.

## Run it (development)

```
docker compose -f docker-compose.dev.yml up -d --build                 # app only (works without fingerprints)
docker compose -f docker-compose.dev.yml --profile embed up -d --build # + sound fingerprints (CLAP, 2 GB RAM)
curl http://127.0.0.1:18090/api/me                                     # {"user": "admin", "owner": true, …}
docker compose -f docker-compose.dev.yml exec kassetto python -m recsys.evaluate
```
Tests and lint (Python 3.12 with `pip install -r requirements-dev.txt`, or in a `python:3.12-slim` container):
```
ruff check .                              # real-bug rules only (pyproject.toml)
pytest                                    # tests/unit: recsys on throwaway databases, simulated time
pytest tests/smoke                        # against the running dev stack; KASSETTO_NETWORK=1 adds YouTube tests
cd app && python -m recsys.synth          # synthetic listener: learned ranker vs prior, AUC (offline benchmark)
cd app/web && npm run check && npm test && npm run build   # svelte-check, vitest (skip rules), build
```
CI: `.github/workflows/ci.yml` (the same, plus the dev stack for the smoke tests). Not pushed yet.
Containers run as `PUID:PGID` (default 1000:1000; `.env`, not in git, holds this machine's values).
`KASSETTO_REGION=VN docker compose … up -d` turns the regional content on. No sign-in proxy in dev (`KASSETTO_AUTH=dev`): every request is the owner "admin". A `Remote-User` header acts as
that user (`curl -H 'Remote-User: alice' …`); people are auto-registered on their first request. To try the real
modes: `KASSETTO_AUTH=proxy KASSETTO_TRUSTED_PROXIES=172.16.0.0/12 docker compose … up -d` (docs/sign-in.md).

## Layout

```
app/
  app.py            entry point (`python app.py` -> server.main)
  server/           the aiohttp server, in layers (a module imports only from the ones above it):
    common          YouTube Music clients, log, off() (blocking work off the loop), HTTP client, result -> song dicts
    streaming       download queue + workers, cache (served while downloading), look-ahead resolver, loudness data
    catalogue       search (+ search2: library, Spotify history, vibe), suggest, home feed, radio, album / playlist /
                    artist, versions, lyrics, image proxy
    mixes           autoplay, Your mix, Made for you, ListenBrainz playlists, Daily Mixes, weekly lists
    listening       events -> recsys, ListenBrainz scrobble + sync, /api/me, likes, prefs, taste, Spotify setting
    playlists, circles   your playlists; people & circles (owner only), stats, together, concerts
    cast            which speaker (discovery / pick / KASSETTO_SPEAKER), play via castplayer.py (a detached
                    player process), sleep timer, speaker tuning, the speaker's audio stream
    routines        morning routines proxy (optional external service)
    quiz            first-run taste quiz
    autoeq, web     headphone EQ profiles; page, assets, service worker, manifest, icons
    auth            sign-in modes (KASSETTO_AUTH none / proxy / dev), the audio port's stream tokens
    main            middleware (who is listening), routes, startup, ports 8090 + 8091
  recsys/           the recommender package (overview in recsys/__init__.py)
    core            DB, who is listening (contextvar USER, people weights), normalisation, listen_weight
    events          plays / prefs / signals, boredom (short-term "autoplay isn't holding you")
    taste           long-term taste: artist affinity, track scores, anchors (decay, time of day)
    sound           CLAP embeddings: taste clusters, "sounds like you", Daily Mix groups
    session         this listening session (plays < 30 min apart): sound + artist mood
    learn           per-person learned ranker: impressions + outcomes -> online logistic regression to a prior
    bandit          Thompson sampling over candidate sources
    ranking         rank(): candidates -> features -> learned score -> sources/diversity -> flow order -> "because"
    listenbrainz    listens sync, collaborative filtering, LB playlists
    search          library search, search re-ranking, vibe search (CLAP text -> audio)
    store, report   small tables; /api/taste
    evaluate        `python -m recsys.evaluate [user]`: AUC of start vs learned weights, per feature, per source
    synth           synthetic catalogue + listener with a hidden taste, run through rank -> record -> learn
  config.py         env(): KASSETTO_<NAME>, else the old YTM_<NAME>; DB path, embed URL (also in the embed image)
  region.py         optional KASSETTO_REGION: charts, local-language feed/shelf, Daily Mix language split
  recommend.py      compatibility shim (`import recommend as rec`)
  library.py        playlists, weekly / daily lists, stats, per-user settings (kv)
  people.py         people + circles (taste blend, speaker owner, concerts), /data/people.json
  spotify.py        import of Spotify's "Extended streaming history" (kept apart, small capped influence)
  phonetics.py      romanized lyrics (Korean, Japanese, Chinese, other scripts)
  embed.py          ytm-embed service: ffmpeg loudness/silence analysis, CLAP fingerprints, speaker renders
  web/              Svelte 5 + Vite PWA (views: Home, Search, Detail, Library, Settings, Stats)
tests/unit, tests/smoke      pytest (see "Run it")
docker-compose.dev.yml
```
Data (`/data`): `kassetto.db` (`ytm.db` on installs from before the rename; SQLite, `PRAGMA user_version` =
`recsys.core.SCHEMA`, migrations in `core.MIGRATIONS`: plays, prefs, signals, tracks, emb, impressions, pl/pl_tracks, kv, lyrics,
audio, spotify_plays, cf_map), `cache/` (audio LRU), `people.json`, `autoeq/`.

How things fit (more detail in the docstrings):
- **Playback:** yt-dlp downloads each track as Opus 251 (AAC fallback) into the cache. Files are served while
  still downloading. YouTube makes non-Premium clients wait out an ad countdown (5–10 s), so `/api/resolve` looks
  up likely taps ahead of time.
- **Recommender:** read `recsys/__init__.py` first. Every pick is logged with its features (table `impressions`).
  Outcomes (finished, skipped, liked, picked from Up next, jumped past, left behind) train the per-person weights.
- **Skips** count only when they're a real choice: next pressed early, cancellable for 20 s. Errors, songs that
  never started and switching to something else don't count. There is no dislike button; *Hide from
  recommendations* is in the song menu.

## Milestone 1: publish v0.1

Decided: name **Kassetto**, AGPL-3.0, repo under `thinhngo-x`, **Cast/Nest is in v0.1**.
Order (reviewed 2026-11-25): safety net first, refactors before features, docs last.

**Release gate for v0.1:** on a clean machine, fresh clone → `docker compose up` → taste quiz → sensible
recommendations within 10 minutes, without ytm-embed. And the author's install switches to the images without
losing data.

1. [x] Clean repo: code only, scrubbed of personal data, AGPL-3.0 `LICENSE`, own history (2026-11-25).
2. [x] **Safety net** (2026-11-25; CI written, not pushed): smoke tests, `recsys.synth`, recsys unit tests, skip rules
   (`web/src/lib/outcome.ts` + vitest), ruff, svelte-check, workflow. Found and fixed: `flow()` could put the
   same artist twice in a row at the end of a batch. Open findings for the recommender work (filed in
   `docs/backlog.md`, to become GitHub issues):
   - On the synthetic listener the learned ranker beats the prior only a little (6 seeds x 60 sessions: 32.2 % vs
     29.7 % of autoplay picks finished; AUC 0.706 vs 0.698). Look at the learning rate, L2, label grading, and
     which features carry signal.
   - Within an arm, rank() takes the best-scored candidate however low that score is: a Thompson draw for "cf"
     served five songs from a genre the listener always skips. Consider a score floor or arm-relative caps.
3. [x] **De-homelab + rename** (2026-11-25). `ytm` → Kassetto everywhere user-facing; `config.env()` reads
   `KASSETTO_*` then `YTM_*`; `KASSETTO_EMBED_URL`; `kassetto.db` with fallback to an existing `ytm.db`;
   `KASSETTO_REGION` (region.py, off by default; Home.svelte keys on a `regional` flag, not on "Vietnam");
   `KASSETTO_LOCATION` defaults to YouTube's own; neutral vibe prompts; Daily Mix fallback by artist; images run as
   1000:1000 with compose `user:` (PUID/PGID); ListenBrainz "off" bug; schema versioning. What an old install must
   check: `docs/upgrading-from-ytm.md`. Kept on purpose: the stored value `plays.source='ytm'`, the API field
   `ytm_plays`. Left for item 6 (Cast): `NEST_IP`, `MUSIC_STREAM_BASE`, `MUSIC_PY`, `/tmp/nestmusic.json`.
4. [x] **Split app.py** (2026-11-25) into `server/` (see Layout), mechanically: same code, cross-module imports,
   no cycles. Verified with the smoke tests incl. the network ones (search, feeds, radio, autoplay, artist / album,
   lyrics, a real download + stream).
5. [x] **Sign-in modes** (2026-11-25; `server/auth.py`, `docs/sign-in.md`): `none` (default, header ignored),
   `proxy` (configurable header, required `KASSETTO_TRUSTED_PROXIES`, 401/403 otherwise), `dev` (compose only, warns).
   Port 8091: `/stream` + `/prefetch` need an HMAC token (key in kv `stream_key`; castplayer signs its URLs).
   Tested in all modes on the dev stack. Not done: an optional password for mode `none` (decide later; a proxy is
   the answer for now). Not yet tried on a real speaker (needs the owner's OK; item 6).
6. [~] **Cast in the app** (2026-11-25; `docs/cast.md`). Done: `server/castplayer.py` stays a detached process
   (music survives app restarts) and gets speaker, stream base and key from the app; mDNS discovery
   (`GET /api/speakers`) and an owner picker in Settings (kv `set:_server:speaker_choice`), `KASSETTO_SPEAKER` /
   `NEST_IP` as a fixed override; `KASSETTO_STREAM_BASE` (`MUSIC_STREAM_BASE`), guessed with host networking;
   UI names the speaker instead of "Nest Mini"; no cast button without a speaker; status short-circuit.
   **Still to do (needs the owner's OK: muted daytime test on the Nest):** play / pause / next / seek / sleep timer /
   signed URLs on a real speaker, and discovery with `network_mode: host` (the dev stack is on a bridge network).
7. [x] **Degrade gracefully** (2026-11-25; `docs/setups.md`). The dev stack runs without embed, ListenBrainz,
   routines and a speaker, and the smoke tests pass there. Out-of-scope code stays dormant: the routines UI shows
   only with the service, `/routine/play` needs its key, concerts show only with `/data/concerts.json` (the circle
   option too). App RAM measured: ~130 MB; embed ~2 GB (from the author's install, not re-measured here).
8. [x] **First run** (2026-11-25): taste quiz (`server/quiz.py`, `web/src/views/Quiz.svelte`, offered on Home while
   someone has < 5 plays and < 3 likes). 10 rounds of 3: 4 wide (3 genres each), then 2 from radios of the likes
   + 1 new genre; songs only (1.5–8 min, no mixes / compilations), one artist once. Each song goes through
   `rank()` (ctx "quiz": impression + features); ❤️ = like, the others = "pass" for the ranker only.
9. [ ] **Install:** `docker-compose.yml` + `.env.example` for users. Images on ghcr (`ghcr.io/thinhngo-x/kassetto`,
   `-embed`), amd64 + arm64 (the CPU torch embed image is the hard one), with a CI workflow building them.
   - **yt-dlp will break:** its pinned version stops working against YouTube within weeks or months. Plan for it:
     Renovate/scheduled rebuilds, plus an opt-in upgrade-at-start or a documented manual upgrade.
   - **Publishing needs the owner's OK.**
10. [ ] **Docs** (last, because they describe decisions made in 3–9):
    - README: what it is, screenshots, quick start, requirements, the recommender explained, comparison table.
    - Configuration reference, FAQ, privacy (what leaves the server: YouTube requests, LRCLIB, optional
      ListenBrainz / Ticketmaster / AutoEq).
    - Prominent "personal use / YouTube ToS" disclaimer.
    - Security notes: sign-in modes, what port 8091 exposes.

Not in v0.1 (maybe later):
- morning routines, i.e. the external service `routines.py` with the spoken briefing; the author's briefing uses
  a Vietnamese TTS model under a non-commercial licence;
- the concerts job (Ticketmaster);
- Spotify import UI (the module exists; import is a CLI today).

## History

Built 2026-11-23 → 25 in the author's homelab and moved here. Notable decisions:
- Opus instead of AAC.
- Look-ahead resolving to beat YouTube's ad countdown.
- CLAP model `laion/clap-htsat-unfused`. `larger_clap_music` was tried first, but its text tower is collapsed.
- Hearts only, no dislikes.
- Skips must be real choices.
- Boredom + learned ranker + flow ordering.
- Old Spotify history kept apart, with a capped influence.
