"""Optional regional content: KASSETTO_REGION=<country code> (off by default).

With a region, the home page adds that country's charts ("Top in …"). Regions listed in REGIONS also know their
language, which adds: the local-language sections of that country's home feed, a "<Language> for you" shelf of
playlists around your favourite artists who sing in it, and Daily Mix groups split by that language when there
are no sound fingerprints yet. Other country codes get the charts only (name them with KASSETTO_REGION_NAME).
"""
import re

from config import env

REGIONS = {
    "VN": {"name": "Vietnam", "language": "Vietnamese",
           "script": re.compile("[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.I),
           "queries": ["Indie Việt", "Nhạc Indie Việt chill", "Nhạc Việt buồn tâm trạng"]},
}

CODE = (env("REGION", "") or "").upper() or None
INFO = {**REGIONS.get(CODE, {}), **({"name": env("REGION_NAME")} if env("REGION_NAME") else {})} if CODE else {}
NAME = INFO.get("name") or CODE
LANGUAGE = INFO.get("language")            # None: no language heuristics


def local(text):
    """Is this text in the region's language? (False without a region language.)"""
    s = INFO.get("script")
    return bool(s and s.search(text or ""))
