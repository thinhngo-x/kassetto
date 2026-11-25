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
Tests and lint (Python 3.12 with `pip install -r requirements-dev.txt`, or in a `python:3.12-slim` container):
```
ruff check .                              # real-bug rules only (pyproject.toml)
pytest                                    # tests/unit: recsys on throwaway databases, simulated time
pytest tests/smoke                        # against the running dev stack; KASSETTO_NETWORK=1 adds YouTube tests
cd app && python -m recsys.synth          # synthetic listener: learned ranker vs prior, AUC (offline benchmark)
cd app/web && npm run check && npm test && npm run build   # svelte-check, vitest (skip rules), build
```
CI: `.github/workflows/ci.yml` (the same, plus the dev stack for the smoke tests). Not pushed yet.
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
    synth           synthetic catalogue + listener with a hidden taste, run through rank -> record -> learn
  recommend.py      compatibility shim (`import recommend as rec`)
  library.py        playlists, weekly / daily lists, stats, per-user settings (kv)
  people.py         people + circles (taste blend, speaker owner, concerts), /data/people.json
  spotify.py        import of Spotify's "Extended streaming history" (kept apart, small capped influence)
  phonetics.py      romanized lyrics (Korean, Japanese, Chinese, other scripts)
  castplayer.py     detached Chromecast/Nest player (copied from the homelab "nestspeak/music.py")
  embed.py          ytm-embed service: ffmpeg loudness/silence analysis, CLAP fingerprints, speaker renders
  web/              Svelte 5 + Vite PWA (views: Home, Search, Detail, Library, Settings, Stats)
tests/unit, tests/smoke      pytest (see "Run it")
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
Order (reviewed 2026-11-25): safety net first, refactors before features, docs last.

**Release gate for v0.1:** on a clean machine, fresh clone → `docker compose up` → taste quiz → sensible
recommendations within 10 minutes, without ytm-embed. And the author's install switches to the images without
losing data.

1. [x] Clean repo: code only, scrubbed of personal data, AGPL-3.0 `LICENSE`, own history (2026-11-25).
2. [x] **Safety net** (2026-11-25; CI written, not pushed): smoke tests, `recsys.synth`, recsys unit tests, skip rules
   (`web/src/lib/outcome.ts` + vitest), ruff, svelte-check, workflow. Found and fixed: `flow()` could put the
   same artist twice in a row at the end of a batch. Open findings for the recommender work:
   - On the synthetic listener the learned ranker only ties the prior (6 seeds x 60 sessions: 33.5 % vs 33.0 %
     of autoplay picks finished; AUC 0.721 vs 0.710). Learning isn't paying off yet: look at the learning rate,
     L2, label grading, and which features carry signal.
   - Within an arm, rank() takes the best-scored candidate however low that score is: a Thompson draw for "cf"
     served five songs from a genre the listener always skips. Consider a score floor or arm-relative caps.
3. [ ] **De-homelab + rename.**
   - `ytm` → `kassetto` in the UI title, manifest, service-worker cache names, container/service names, docs, log
     lines and UI copy (`PeopleEditor.svelte` names Authelia). Keep reading the old `YTM_*` variables as fallbacks
     for the author's install.
   - Hardcoded `http://ytm-embed:8099` (3× in app.py) → `KASSETTO_EMBED_URL`.
   - Decide on `ytm.db` and `/tmp/nestmusic.json`: keep the names or rename them with a migration.
   - Regional content: the Vietnam feed (`YT_VN`, `location="VN"`), *Top in Vietnam*, *Vietnamese for you* and
     the Vietnamese-language heuristics become an optional `KASSETTO_REGION` (e.g. `VN`), off by default. The
     home page curation (`web/src/views/Home.svelte`) must work without it. Also:
     - `YTM_LOCATION` defaults to `"FR"` (app.py:23): needs a neutral default;
     - the vibe examples include "traditional Vietnamese music";
     - the Daily Mix fallback without fingerprints splits Vietnamese vs the rest (recsys/sound.py, app.py
       `daily_groups`). It needs a neutral fallback (e.g. artist clusters), not just "off".
   - Container user: `USER 1004:1004` → configurable (PUID/PGID) or a fixed non-root user with documented
     volume ownership.
   - [x] Bug: `/api/me` said ListenBrainz "as admin" with no account configured; now "off" (2026-11-25).
   - Schema versioning (`PRAGMA user_version` + migrations) before anyone else installs it.
4. [ ] **Split app.py** into modules (streaming, catalogue, mixes, cast, people, settings), as was done for recsys.
   Before Cast, so `castplayer.py` folds into a `cast` module and not into app.py.
5. [ ] **Sign-in modes**, documented:
   - (a) single user, no proxy: ignore `Remote-User` entirely. Say plainly that anyone who reaches the port is the
     owner (optional password?);
   - (b) behind an auth proxy (Authelia, Authentik, oauth2-proxy). Configurable header name, and **required**
     trusted proxy networks; reject the header from anywhere else. Both ports bind 0.0.0.0 today.
   - Today the header is trusted blindly, and no header = owner.
   - **Audio-only port 8091 has no sign-in at all**: anyone on the LAN can hit `/stream/{vid}` and `/prefetch/{vid}`
     and make the server download from YouTube. At a minimum, serve only tracks already cached or queued for the
     speaker; better, a per-session token in the stream URL.
6. [ ] **Cast in the app.**
   - `castplayer.py` → the `cast` module (see 4).
   - Discover speakers with mDNS (pychromecast discovery) and let the user pick one. mDNS doesn't cross Docker's
     bridge network: document `network_mode: host`, and keep `NEST_IP` as a manual fallback.
   - `MUSIC_STREAM_BASE` must be a LAN address the speaker can reach; it can't be auto-detected reliably inside a
     container. Document it, and the audio-only port (8091).
   - `/api/nest/status` takes 8 s when no speaker is configured: short-circuit it.
   - Speaker tuning (embed `/speaker`) and the Nest sleep timer already exist.
7. [ ] **Degrade gracefully:** verified 2026-11-25 that the app works without ytm-embed. Still to check:
   - without ListenBrainz;
   - without the routines service (fine: `available: false`);
   - without a speaker.
   - Out-of-scope features still have live code: hide the routines UI, `/routine/play` on 8091, `/api/concerts`
     and `"concerts": True` in `people._default()` (or remove them).
   - Document "minimal" vs "full" setups and their RAM needs (app ~250 MB, embed ~2 GB while loaded).
8. [ ] **First run:** an in-app taste quiz (≈10 rounds of 3 songs, ❤️ what you like), so a new person doesn't
   start empty. Log the quiz's picks as impressions with outcomes so they train `learn`, not just hearts.
   The author's taste was seeded by hand in chat.
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
