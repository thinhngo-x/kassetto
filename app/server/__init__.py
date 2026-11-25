"""Kassetto: a self-hosted music player with a personal recommender (search + play in one page, no ads).

Meant to run behind a sign-in proxy (e.g. Authelia, Authentik) that sets Remote-User. Catalogue / search / radio / home feed via ytmusicapi
(unauthenticated); audio = the plain m4a stream found by yt-dlp, proxied by this server (Range/seek supported),
so the browser never loads YouTube's player or ads. Plays are scrobbled to ListenBrainz (LISTENBRAINZ_USER_TOKEN)
and feed the weekly Explo recommendations. "Play on Nest" hands the queue to castplayer.py (Chromecast / Nest).
"""
