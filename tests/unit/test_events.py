from recsys import core, events

S = {"videoId": "vid00000001", "title": "Song", "artist": "Artist", "duration": 200}


def plays():
    with core.db() as c:
        return c.execute("SELECT video_id, event, played, user FROM plays ORDER BY id").fetchall()


def signals():
    with core.db() as c:
        return [r[0] for r in c.execute("SELECT kind FROM signals ORDER BY id")]


def test_listen_is_stored_for_the_listener(rs, clock):
    events.record({**S, "event": "skip", "played": 5})
    assert plays() == [("vid00000001", "skip", 5, "tester")]


def test_like_unlike_and_hide(rs, clock):
    events.record({**S, "event": "like"})
    assert events.prefs() == {"vid00000001": 1}
    events.record({**S, "event": "unlike"})
    assert events.prefs() == {}
    events.record({**S, "event": "dislike"})                   # old clients: a dislike is a hide
    assert events.prefs() == {"vid00000001": -1}
    events.record({**S, "event": "unhide"})
    assert events.prefs() == {}
    assert plays() == []                                       # preferences aren't listens


def test_finishing_again_within_two_weeks_is_a_replay(rs, clock):
    events.record({**S, "event": "complete", "played": 200})
    clock.advance(3 * 86400)
    events.record({**S, "event": "complete", "played": 200})
    clock.advance(20 * 86400)
    other = {**S, "videoId": "vid00000002"}
    events.record({**other, "event": "complete", "played": 200})
    clock.advance(15 * 86400)
    events.record({**other, "event": "complete", "played": 200})
    assert signals() == ["replay"]


def test_implicit_signals_are_signals_not_plays(rs, clock):
    events.record({**S, "event": "queue_add"})
    events.record({**S, "event": "pass", "auto": True})
    assert signals() == ["queue_add", "pass"] and plays() == []


def test_boredom_rises_when_you_leave_autoplay_and_fades(rs, clock):
    assert events.boredom() == 0.0
    events.record({**S, "event": "escape", "auto": True})
    events.record({**S, "event": "escape", "auto": True})
    b = events.boredom()
    assert b > 0.5
    clock.advance(events.BORED_HALF_LIFE)
    assert abs(events.boredom() - b / 2) < 1e-6


def test_only_autoplay_finishes_lower_boredom(rs, clock):
    for _ in range(2):
        events.record({**S, "event": "escape", "auto": True})
    b = events.boredom()
    events.record({**S, "event": "complete", "played": 200})   # a song you chose yourself
    assert events.boredom() == b
    events.record({**S, "event": "complete", "played": 200, "auto": True})
    assert events.boredom() < b


def test_bandit_learns_from_picks_with_a_source(rs, clock):
    from recsys.bandit import bandit
    a0, b0 = bandit()["similar"]
    events.record({**S, "event": "complete", "played": 200, "why": "similar"})
    a1, b1 = bandit()["similar"]
    assert a1 > a0 * 0.99 and b1 <= b0
    events.record({**S, "event": "complete", "played": 200, "why": "not a source"})
    assert bandit()["similar"] == [a1, b1]
