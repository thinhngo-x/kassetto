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


def test_audio_port_rejects_bad_ids(api):
    assert api("GET", "/stream/not-a-video-id-at-all", base=AUDIO).status in (400, 404)


@pytest.mark.network
def test_search(api):
    r = api("GET", "/api/search?q=beethoven", timeout=40)
    assert r.status == 200 and r.json()
