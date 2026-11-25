# Minimal and full setups

Kassetto runs on its own; everything else is optional and it carries on without it.

| | Minimal | Full |
|---|---|---|
| Containers | `kassetto` | `kassetto` + `kassetto-embed` |
| RAM | ~150 MB (measured: 130 MB after searching, streaming and autoplay) + the page cache for audio | + ~2 GB while the sound model is loaded (it unloads after 10 idle minutes) |
| Disk | the audio cache (`KASSETTO_CACHE_MB`, default 3,000 MB) | + ~800 MB for the CLAP model |
| CPU | light | fingerprinting a song takes a few seconds on 2 cores; it works through a queue at low priority |

What each optional part adds, and what happens without it:

| Optional part | Adds | Without it |
|---|---|---|
| `kassetto-embed` (CLAP sound fingerprints) | "sounds like you", sound-based taste clusters, vibe search ("rainy day piano"), Daily Mixes by sound, even loudness, silence trimming, speaker tuning | recommendations use artists, radios and your listening only; Daily Mixes are grouped by artist; vibe search and speaker tuning are off |
| ListenBrainz account | your listens from other players, collaborative filtering ("listeners with your taste"), ListenBrainz playlists, scrobbling | Kassetto learns from what you play in Kassetto |
| A Cast speaker | play on the speaker, sleep timer, wake-up music | no cast button |
| `KASSETTO_REGION` | that country's charts and local-language shelves | YouTube Music's own home feed |
| Spotify history import (CLI) | a small, capped head start for artists you already play | nothing missing |

Everything above was checked running without it (`tests/smoke`).
