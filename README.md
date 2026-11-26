# Kassetto

A self-hosted music player with a recommender that learns *you*. It plays YouTube Music's catalogue through your
own server (no ads, no Google account), works out what you like from what you finish, skip and pass over, and
tells you why it picked each song.

**Status:** v0.1, the first public release. It works day to day; expect rough edges (see
[docs/backlog.md](docs/backlog.md) for what's known).

> [!WARNING]
> **Personal use only.** Kassetto plays music from YouTube Music's public catalogue by downloading it to your
> server. Downloading from YouTube is against YouTube's terms of service. Kassetto is meant for personal,
> self-hosted use: run it for yourself and the people you live with, never as a service for others. You are
> responsible for how you use it. Kassetto is not affiliated with Google or YouTube.

## What it does

- **Search and play** YouTube Music's catalogue in a fast web app (installable as a PWA): albums, artists,
  playlists, radios, lyrics (time-synced when available, with romanisation for Korean, Japanese, Chinese and more),
  versions of a song (live, acoustic, remix).
- **No ads, no waiting:** audio is fetched by the server (Opus) and served while it downloads; likely next songs are
  looked up ahead of time.
- **A personal recommender** behind autoplay, *Your mix*, Daily Mixes and weekly lists, explained below.
- **Several people:** each person has their own taste; *circles* (a household, friends) can blend tastes and share
  playlists.
- **Cast speakers** (Chromecast, Google Home / Nest): hand the queue over, with a sleep timer and a tuning profile
  for small speakers.
- **Even loudness and clean transitions** (with the optional sound service): volume levelling, silence trimming,
  crossfades.

## The recommender

Most players either have no recommender (they play your files) or a closed one you can't see into. Kassetto's
runs on your server, on your data, and shows its reasoning.

- **It learns from what you actually do.** A finished song counts; a song you skip in its first seconds counts
  against it, a song you gave a chance and then left counts a little; a song you jump past in *Up next*, or that
  was waiting when you left autoplay for something you chose yourself, says autoplay wasn't holding you. Errors,
  songs that never started and switching to something else don't count: only real choices do. There is no dislike
  button.
- **Long-term taste and this session.** Artist affinity and per-song scores with a 45-day half-life (and a
  time-of-day boost), plus the current session: if you've skipped two songs by the same artist in a row, they're
  out for now.
- **It hears the music** (optional sound service): CLAP audio fingerprints cluster your favourites by sound, find
  "sounds like you" songs, order a mix so each song flows into the next, and power vibe search ("rainy day piano").
- **It adapts its own weights to you.** Every pick is logged with the features it was scored on; outcomes train a
  per-person model: Bayesian pairwise ranking (it learns which of two picks you'd rather keep), starting from the
  hand-tuned weights so a few odd evenings don't undo them, with Thompson sampling to try what it's unsure of. The
  source of each song (similar songs, your favourites' radios, collaborative filtering, sound, new artists) is part
  of the model, and a boredom signal leans away from the familiar when autoplay keeps losing you.
- **Every pick says why:** "Because you like …", "Sounds like …", "New artist for you · close to …", "Listeners with
  your taste play this".
- **It's measured.** `python -m recsys.evaluate` reports how well the learned weights predict what you finish, and
  `python -m recsys.synth` runs the whole loop against a simulated listener. See
  [docs/recommender.md](docs/recommender.md).
- **New here?** A 2-minute taste quiz (10 rounds of 3 songs) gives it a start.

## How it compares

| | Kassetto | Navidrome / Jellyfin / Funkwhale | Spotify / YouTube Music |
|---|---|---|---|
| Music | YouTube Music's catalogue (see the warning above) | your own files | their catalogue |
| Runs on | your server | your server | their servers |
| Learned, per-person recommendations | yes, from skips / finishes / passes, per session | rule-based mixes / radios (similar artists, genres, tags) | yes |
| Explains each pick | yes | no | rarely |
| Your listening data | stays on your server (optionally ListenBrainz) | stays on your server | theirs |
| Ads | none | none | on free plans |

If you have your own music library, Navidrome, Jellyfin and Funkwhale are the right tools; Kassetto is for
discovering and playing music you don't own.

## Quick start

Requirements: Docker with Compose, a 64-bit Linux machine (amd64 or arm64), ~150 MB RAM for the app (~2 GB more for
the optional sound service), a few GB of disk for the audio cache.

```sh
git clone https://github.com/thinhngo-x/kassetto && cd kassetto
cp .env.example .env                         # edit: PUID / PGID, TZ, sign-in
mkdir -p data models && sudo chown "$(id -u):$(id -g)" data models
docker compose up -d                         # or: docker compose --profile embed up -d   (+ sound fingerprints)
```

Open `http://<your server>:8090`. Out of the box it's a single-person install (everyone who reaches the port is
you); for several people put it behind a sign-in proxy ([docs/sign-in.md](docs/sign-in.md)).

## Documentation

- [Setups](docs/setups.md): minimal vs full, what each optional part adds, RAM / disk
- [Configuration](docs/configuration.md): every setting
- [Sign-in](docs/sign-in.md): single person, or behind Authelia / Authentik / oauth2-proxy
- [Cast speakers](docs/cast.md)
- [The recommender](docs/recommender.md)
- [Privacy](docs/privacy.md): what leaves your server
- [FAQ](docs/faq.md)
- [Upgrading from "ytm"](docs/upgrading-from-ytm.md) (the name before Kassetto)

## Development

`docker compose -f docker-compose.dev.yml up -d --build`, then `http://127.0.0.1:18090`. Tests: `pytest`
(recommender, sign-in, schema), `pytest tests/smoke` (the API against the dev stack), `cd app/web && npm test`.

## Licence

[AGPL-3.0](LICENSE). If you run a modified Kassetto for other people, you must offer them its source.
