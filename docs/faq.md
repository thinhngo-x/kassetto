# FAQ

**Is this legal?** Kassetto downloads audio from YouTube, which YouTube's terms of service don't allow. It's meant
for personal, self-hosted use. Don't offer it to the public, and decide for yourself whether to run it.

**Do I need a Google account or YouTube Premium?** No. Kassetto uses YouTube Music's public catalogue without
signing in.

**A song doesn't play / everything stopped playing.** YouTube changes things now and then and yt-dlp, the
downloader, needs an update. Pull the newest image (`docker compose pull && docker compose up -d`; it's rebuilt weekly
with the newest yt-dlp) or set `KASSETTO_YTDLP_UPDATE=1`.

**Why is there no dislike button?** Kassetto learns from what you do: skipping a song early counts against it,
finishing it counts for it. If you never want to hear a song again, use *Hide from recommendations* in its menu.

**Why did it pick this song?** Open the song's menu: every pick has its reason ("Because you like …", "Sounds like …",
"New artist for you"). *Your stats* shows what it has learned about you.

**It doesn't know me yet.** Take the taste quiz on the home page (2 minutes), or just play: after a few dozen songs
autoplay gets noticeably better. If you use ListenBrainz, connect it to start from your history.

**Can several people use it?** Yes: put it behind a sign-in proxy ([sign-in.md](sign-in.md)). Each person gets
their own taste; circles share playlists and can blend tastes.

**Do I need the embed service?** No. It adds sound-based recommendations, vibe search, even loudness and speaker
tuning, and needs ~2 GB of RAM while loaded ([setups.md](setups.md)).

**Can it play my own music files?** No: use Navidrome, Jellyfin or Funkwhale for that.

**Does it work on a Raspberry Pi?** It should: the images are built for arm64 too, and the app needs ~150 MB of RAM
(not tested on a Pi yet). The embed service needs ~2 GB of RAM and is slow on small CPUs.
