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
- **Commit locally whenever it helps; push only when asked.** Commit message footer as in the session instructions.
- **Legal:** downloading audio from YouTube breaks YouTube's terms of service. Kassetto is for personal
  self-hosting; never offer a hosted instance, and keep the README disclaimer prominent.

## Run it (development)

```
docker compose -f docker-compose.dev.yml up -d --build                 # app only (works without fingerprints)
docker compose -f docker-compose.dev.yml --profile embed up -d --build # + sound fingerprints (CLAP, 2 GB RAM)
curl http://127.0.0.1:18090/api/me                                     # {"user": "admin", "owner": true, …}
docker compose -f docker-compose.dev.yml exec ytm python -m recsys.evaluate
```
No sign-in proxy in dev: every request is the owner "admin". A `Remote-User` header acts as that user
(`curl -H 'Remote-User: alice' …`); people are auto-registered on their first request.

## Layout

```
app/
  app.py            aiohttp server (~2,000 lines; splitting it is on the checklist): API, streaming + download
                    queue, look-ahead resolver, lyrics, home feed, mixes, Daily Mixes, weekly lists, Nest/Cast,
                    routines proxy, sound profile + speaker tuning endpoints, people & circles, stats
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
  recommend.py      compatibility shim (`import recommend as rec`)
  library.py        playlists, weekly / daily lists, stats, per-user settings (kv)
  people.py         people + circles (taste blend, speaker owner, concerts), /data/people.json
  spotify.py        import of Spotify's "Extended streaming history" (kept apart, small capped influence)
  phonetics.py      romanized lyrics (Korean, Japanese, Chinese, other scripts)
  castplayer.py     detached Chromecast/Nest player (copied from the homelab "nestspeak/music.py")
  embed.py          ytm-embed service: ffmpeg loudness/silence analysis, CLAP fingerprints, speaker renders
  web/              Svelte 5 + Vite PWA (views: Home, Search, Detail, Library, Settings, Stats)
docker-compose.dev.yml
```
Data (`/data`): `ytm.db` (SQLite: plays, prefs, signals, tracks, emb, impressions, pl/pl_tracks, kv, lyrics,
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

1. [x] Clean repo: code only, scrubbed of personal data, AGPL-3.0 `LICENSE`, own history (2026-11-25).
2. [ ] **De-homelab + rename.**
   - `ytm` → `kassetto` in the UI title, manifest, service-worker cache names, container/service names,
     docs and log lines. Keep reading the old `YTM_*` variables as fallbacks for the author's install.
   - Regional content: the Vietnam feed (`YT_VN`, `location="VN"`), *Top in Vietnam*, *Vietnamese for you* and
     the Vietnamese-language heuristics become an optional `KASSETTO_REGION` (e.g. `VN`), off by default. The
     home page curation (`web/src/views/Home.svelte`) must work without it.
   - Container user: `USER 1004:1004` → configurable (PUID/PGID) or a fixed non-root user with documented
     volume ownership.
   - Bug: `/api/me` says ListenBrainz "as admin" when no account is configured (should say "off").
3. [ ] **Cast in the app.**
   - Fold `castplayer.py` into the app.
   - Discover speakers with mDNS (pychromecast discovery) instead of `NEST_IP`, and let the user pick one.
   - `/api/nest/status` takes 8 s when no speaker is configured: short-circuit it.
   - The audio-only port (8091) must stay reachable by the speakers; document it.
   - Speaker tuning (embed `/speaker`) and the Nest sleep timer already exist.
4. [ ] **Sign-in modes**, documented:
   - (a) single user, no proxy;
   - (b) behind an auth proxy (Authelia, Authentik, oauth2-proxy). Configurable header name and trusted proxy
     networks; reject the `Remote-User` header from anywhere else.
   - Today the header is trusted blindly, and no header = owner.
5. [ ] **Install:** `docker-compose.yml` + `.env.example` for users. Images on ghcr (`ghcr.io/thinhngo-x/kassetto`,
   `-embed`), with a CI workflow building them. **Publishing needs the owner's OK.**
6. [ ] **Degrade gracefully:** verified 2026-11-25 that the app works without ytm-embed. Still to check:
   - without ListenBrainz;
   - without the routines service (fine: `available: false`);
   - without a speaker.
   Document "minimal" vs "full" setups and their RAM needs (app ~250 MB, embed ~2 GB while loaded).
7. [ ] **First run:** an in-app taste quiz (≈10 rounds of 3 songs, ❤️ what you like), so a new person doesn't
   start empty. The author's taste was seeded by hand in chat.
8. [ ] **Docs:**
   - README: what it is, screenshots, quick start, requirements, the recommender explained, comparison table.
   - Configuration reference, FAQ, privacy (what leaves the server: YouTube requests, LRCLIB, optional
     ListenBrainz / Ticketmaster / AutoEq).
   - Prominent "personal use / YouTube ToS" disclaimer.
9. [ ] **Tests + CI:**
   - API smoke tests against the dev stack;
   - unit tests for recsys (rank invariants, learn updates, session, skip rules);
   - lint (ruff), frontend build + svelte-check, in GitHub Actions.
10. [ ] **Split app.py** into modules (streaming, catalogue, mixes, cast, people, settings), as was done for recsys.

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
