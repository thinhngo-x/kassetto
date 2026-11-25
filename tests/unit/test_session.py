import numpy as np

from recsys import events, session, sound

S = {"title": "Song", "duration": 200}


def play(clock, vid, artist, ev, played, gap=10):
    events.record({**S, "videoId": vid, "artist": artist, "event": ev, "played": played})
    clock.advance(played + gap)


def test_no_session_after_a_long_break(rs, clock):
    play(clock, "vid00000001", "A", "complete", 200)
    clock.advance(session.GAP + 300)
    assert session.session() == []
    assert session.profile()["n"] == 0


def test_session_starts_after_the_last_gap(rs, clock):
    play(clock, "vid00000001", "Old", "complete", 200)
    clock.advance(2 * 3600)
    play(clock, "vid00000002", "A", "complete", 200)
    play(clock, "vid00000003", "B", "skip", 5)
    s = session.session()
    assert [v for v, _, _ in s] == ["vid00000003", "vid00000002"]   # newest first, the old play left out
    assert s[0][2] == -1.2 and abs(s[1][2] - 1.0 * session.DECAY) < 1e-9


def test_skipping_an_artist_twice_turns_the_mood_against_them(rs, clock):
    play(clock, "vid00000001", "Liked", "complete", 200)
    play(clock, "vid00000002", "Skipped", "skip", 4)
    play(clock, "vid00000003", "Skipped", "skip", 4)
    p = session.profile()
    assert session.sess_artist(p, ["skipped"]) == -1.5               # two early skips: as low as it goes
    assert session.sess_artist(p, ["liked"]) > 0
    assert session.sess_artist(p, ["unknown"]) == 0


def test_sound_closeness_to_what_you_kept(rs, cat, clock):
    vids = list(cat)
    kept, rejected = vids[0], vids[-1]                         # genre 0 vs genre 5
    play(clock, kept, cat[kept]["artist"], "complete", 200)
    play(clock, rejected, cat[rejected]["artist"], "skip", 4)
    p = session.profile()
    E = sound.embeddings()
    assert p["pos"] is not None and p["neg"] is not None
    assert session.sess_score(p, E[kept]) > session.sess_score(p, E[rejected])
    assert session.sess_score(p, None) == 0.0
    assert all(-1 <= session.sess_score(p, E[v]) <= 1 for v in vids)
    assert np.isclose(np.linalg.norm(p["pos"]), 1, atol=1e-3)
