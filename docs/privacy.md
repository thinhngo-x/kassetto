# Privacy: what leaves your server

Kassetto keeps your listening history, likes, taste model and people on your server (`data/`). Nothing is sent to
the Kassetto project. What does go out:

**From the server**
- **YouTube / YouTube Music** (`music.youtube.com`, `www.youtube.com`, Google's video servers): searches, catalogue
  and home-feed requests, radios, lyrics, and the audio downloads. They come from your server's IP address, without
  a Google account. YouTube sees what is searched and played from your address, not who in your home did it.
- **LRCLIB** (`lrclib.net`): title, artist and duration of a song, when YouTube Music has no lyrics for it.
- **Cover images** for the colour behind the player, fetched through the server (`/img`).
- **ListenBrainz** (optional, only with an account set up): your plays are scrobbled, and your listens and
  recommendations fetched.
- **AutoEq** (optional, only when you open the headphone picker): its public index and the profile you choose, from
  GitHub.
- **Hugging Face** (only with the embed service): the sound model is downloaded once on first start.
- **PyPI** (only with `KASSETTO_YTDLP_UPDATE=1`): the newest yt-dlp, at most twice a day.

**From your browser**
- **Cover images** are loaded straight from Google's image servers (`i.ytimg.com`, `lh3.googleusercontent.com`,
  `yt3.ggpht.com`): like any page showing those images, your browser's IP address and the image addresses reach
  Google.
- Everything else (the page, search, audio, lyrics) goes through your server.

**Cast speakers** talk to your server directly (port 8091) and to Google as any Cast device does.
