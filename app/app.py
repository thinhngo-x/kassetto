#!/usr/bin/env python3
"""Kassetto server entry point (the code is in server/, overview in server/__init__.py)."""
import ytdlp_update  # noqa: F401  (KASSETTO_YTDLP_UPDATE: must come before yt_dlp is imported)
from server.main import main

if __name__ == "__main__":
    main()
