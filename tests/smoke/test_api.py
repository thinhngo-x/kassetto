"""The API answers, without YouTube unless marked `network`. Writes go to throwaway people ("smoke-*")."""
import time, uuid

import pytest

from conftest import AUDIO

VID = "smokeTest01"


def person():
    return f"smoke-{uuid.uuid4().hex[:8]}"


def test_health(api):
    assert api("GET", "/healthz").json() == {"ok": True}


def test_page_and_pwa_files(api):
    r = api("GET", "/")
    assert r.status == 200 and b"<title>" in r.body
    assert api("GET", "/manifest.webmanifest").status == 200
    assert api("GET", "/sw.js").status == 200


def test_me_is_the_owner_without_a_proxy(api):
    me = api("GET", "/api/me").json()
    assert me["owner"] is True and me["user"]
    assert me["listenbrainz"] == "off"                          # no account configured in dev


def test_new_person_is_registered_on_first_visit(api):
    u = person()
    me = api("GET", "/api/me", user=u).json()
    assert me == {**me, "user": u, "owner": False}
    assert u in api("GET", "/api/people").json()["people"]


def test_only_the_owner_manages_people(api):
    assert api("GET", "/api/people", user=person()).status == 403


@pytest.mark.parametrize("path", ["/api/prefs", "/api/likes", "/api/taste", "/api/myplaylists", "/api/stats",
                                  "/api/weekly", "/api/spotify"])
def test_read_endpoints_answer_json(api, path):
    r = api("GET", path, user=person())
    assert r.status == 200, r.body[:300]
    r.json()


def test_like_then_unlike(api):
    u = person()
    s = {"videoId": VID, "title": "Smoke test", "artist": "Nobody", "duration": 100}
    assert api("POST", "/api/event", {**s, "event": "like"}, user=u).status == 200
    assert api("GET", "/api/prefs", user=u).json() == {VID: 1}
    assert [x["videoId"] for x in api("GET", "/api/likes", user=u).json()] == [VID]
    api("POST", "/api/event", {**s, "event": "unlike"}, user=u)
    assert api("GET", "/api/prefs", user=u).json() == {}


def test_bad_event_is_rejected(api):
    assert api("POST", "/api/event", {"videoId": VID, "event": "nonsense"}, user=person()).status == 400
    assert api("POST", "/api/event", {"event": "like"}, user=person()).status == 400


def test_listens_reach_the_taste_report(api):
    u = person()
    s = {"videoId": VID, "title": "Smoke test", "artist": "Nobody", "duration": 100}
    api("POST", "/api/event", {**s, "event": "complete", "played": 100}, user=u)
    t = api("GET", "/api/taste", user=u).json()
    assert t["ytm_plays"] >= 1


def test_routines_off_without_the_service(api):
    assert api("GET", "/api/routines").json()["available"] is False


@pytest.mark.xfail(reason="milestone item 6: /api/nest/status waits ~8 s when no speaker is configured", strict=True)
def test_nest_status_is_quick_without_a_speaker(api):
    t = time.time()
    api("GET", "/api/nest/status")
    assert time.time() - t < 2


def test_audio_port_needs_the_speaker_token(api):
    """Nobody on the LAN can make the server download through the speaker's port."""
    for path in (f"/stream/{VID}", f"/prefetch/{VID}", f"/stream/{VID}?t=0123456789abcdef01234567"):
        assert api("GET", path, base=AUDIO).status == 403, path


def test_health_is_open(api):
    assert api("GET", "/healthz").status == 200


@pytest.fixture(scope="module")
def a_song():
    """A song from a real search (needs YouTube)."""
    from conftest import call
    r = call("GET", "/api/search?q=beethoven%20moonlight%20sonata", timeout=40)
    assert r.status == 200
    songs = [x for x in r.json() if x.get("type") == "song" and x.get("videoId")]
    assert songs, r.json()[:3]
    return songs[0]


@pytest.mark.network
def test_search(a_song):
    assert a_song["title"] and a_song["artist"]


@pytest.mark.network
@pytest.mark.parametrize("path", ["/api/home", "/api/foryou", "/api/suggest?q=beeth", "/api/search2?q=beethoven",
                                  "/api/eq/search?q=sennheiser"])
def test_feeds(api, path):
    r = api("GET", path, timeout=60)
    assert r.status == 200, r.body[:300]
    r.json()


@pytest.mark.network
def test_song_pages(api, a_song):
    v = a_song["videoId"]
    for path in (f"/api/radio?videoId={v}", f"/api/versions?id={v}",
                 f"/api/lyrics?videoId={v}&title=Moonlight%20Sonata&artist=Beethoven&duration=300"):
        r = api("GET", path, timeout=60)
        assert r.status == 200, (path, r.body[:300])


@pytest.mark.network
def test_autoplay_explains_its_picks(api, a_song):
    picks = api("GET", f"/api/autoplay?seed={a_song['videoId']}", user=person(), timeout=90).json()
    assert picks and all(p.get("why") for p in picks)


@pytest.mark.network
def test_artist_and_album(api, a_song):
    art = api("GET", "/api/search?q=daft%20punk&filter=artists", timeout=40).json()[0]
    a = api("GET", f"/api/artist?id={art['id']}", timeout=40)
    assert a.status == 200, a.body[:200]
    alb = api("GET", "/api/search?q=discovery%20daft%20punk&filter=albums", timeout=40).json()[0]
    assert api("GET", f"/api/album?id={alb['id']}", timeout=40).status == 200


@pytest.mark.network
def test_audio_streams(api, a_song):
    """Download through yt-dlp and serve the first bytes (Range)."""
    import urllib.request
    from conftest import BASE
    req = urllib.request.Request(f"{BASE}/stream/{a_song['videoId']}", headers={"Range": "bytes=0-1023"})
    with urllib.request.urlopen(req, timeout=120) as r:
        assert r.status in (200, 206) and len(r.read()) > 0
