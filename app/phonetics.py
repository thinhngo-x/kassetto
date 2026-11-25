"""Phonetic (romanized) lyrics for scripts you may not read: Korean (korean-romanizer, Revised Romanization with
pronunciation rules), Japanese (pykakasi, Hepburn; GPL-3.0), Chinese (pypinyin, with tone marks), anything else
non-Latin (anyascii: Cyrillic, Greek, Thai, Arabic, Hebrew, Devanagari ...). Latin lines (English, Vietnamese,
French ...) get none. Mixed lines keep their Latin words and romanize the rest.
"""
import functools, re

HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
KANA = re.compile(r"[぀-ヿㇰ-ㇿ]")
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATINISH = re.compile(r"^[\s\x00-ɏḀ-ỿ -⁯←-⯿︀-️\U0001f000-\U0001faff♪♫]*$")
RUN = re.compile(r"[\x00-ɏḀ-ỿ -⁯]+")      # Latin / punctuation runs kept as they are


@functools.lru_cache(1)
def _ko():
    from korean_romanizer.romanizer import Romanizer
    return lambda s: Romanizer(s).romanize()


@functools.lru_cache(1)
def _ja():
    import pykakasi
    k = pykakasi.kakasi()
    return lambda s: " ".join(x["hepburn"] for x in k.convert(s) if x["hepburn"].strip())


@functools.lru_cache(1)
def _zh():
    from pypinyin import lazy_pinyin, Style
    return lambda s: " ".join(lazy_pinyin(s, style=Style.TONE))


@functools.lru_cache(1)
def _any():
    from anyascii import anyascii
    return anyascii


def _segment(text, conv):
    """Romanize the non-Latin runs of a line, keep the Latin ones (English words inside K-pop lines)."""
    out, pos = [], 0
    for m in RUN.finditer(text):
        if m.start() > pos:
            out.append(conv(text[pos:m.start()]).strip())
        out.append(m.group())
        pos = m.end()
    if pos < len(text):
        out.append(conv(text[pos:]).strip())
    s = re.sub(r"\s+", " ", "".join(out)).strip()          # Latin runs keep their own spacing / punctuation
    return re.sub(r"([(\[]) | ([)\]])", lambda m: m.group(1) or m.group(2), s)


def romanize(lines):
    """lines = [text] -> [romanized or None], or None if nothing needs it (all Latin)."""
    if all(LATINISH.match(t or "") for t in lines):
        return None
    whole = "".join(lines)
    japanese = bool(KANA.search(whole))                      # kanji in a song with kana = Japanese, else Chinese
    out = []
    for t in lines:
        if not t or LATINISH.match(t):
            out.append(None); continue
        if HANGUL.search(t):
            conv = _ko()
        elif japanese and (KANA.search(t) or HAN.search(t)):
            conv = _ja()
        elif HAN.search(t):
            conv = _zh()
        else:
            conv = _any()
        try:
            r = _segment(t, conv)
        except Exception:
            r = None
        out.append(r if r and r != t else None)
    return out if any(out) else None
