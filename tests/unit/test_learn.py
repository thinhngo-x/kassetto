import json

from recsys import core, learn

F = {"bias": 1.0, "sim": 0.8, "aff": 0.5, "snd": 0.2, "sess": 0.0, "sess_art": 0.0, "new_artist": 0.0,
     "recent": 0.0, "skips": 0.0, "liked": 0.0}


def serve(vid="vid00000001", f=F):
    learn.log_impressions([{"videoId": vid, "why": "similar", "_score": 0.0, "_f": f}], "test")


def labels():
    with core.db() as c:
        return c.execute("SELECT video_id, label, event FROM impressions ORDER BY id").fetchall()


def test_starts_at_the_prior(rs):
    w, n = learn.weights()
    assert w == learn.PRIOR and n == 0


def test_outcome_without_impression_changes_nothing(rs, clock):
    learn.outcome("vid00000001", "complete", 200, 200)
    assert learn.weights() == (learn.PRIOR, 0)


def test_finished_pick_is_labelled_and_moves_weights_up(rs, clock):
    serve()
    learn.outcome("vid00000001", "complete", 200, 200)
    assert labels() == [("vid00000001", 1.0, "complete")]
    w, n = learn.weights()
    assert n == 1
    assert w["sim"] > learn.PRIOR["sim"] and w["aff"] > learn.PRIOR["aff"]
    assert w["recent"] == learn.PRIOR["recent"]                # feature 0 and at its prior: untouched


def test_early_skip_moves_weights_down(rs, clock):
    serve()
    learn.outcome("vid00000001", "skip", 4, 200)
    assert labels()[0][1] == 0.0
    w, _ = learn.weights()
    assert w["sim"] < learn.PRIOR["sim"]


def test_partial_is_graded_by_share_heard(rs, clock):
    serve()
    learn.outcome("vid00000001", "partial", 120, 240)          # half heard: listen_weight 0.4
    assert abs(labels()[0][1] - (0.4 + 1.2) / 2.2) < 1e-9


def test_one_outcome_per_impression(rs, clock):
    serve()
    learn.outcome("vid00000001", "complete", 200, 200)
    learn.outcome("vid00000001", "skip", 3, 200)               # no unlabelled impression left
    assert [r[1] for r in labels()] == [1.0]
    assert learn.weights()[1] == 1


def test_old_impressions_are_not_labelled(rs, clock):
    serve()
    clock.advance(learn.WINDOW + 60)
    learn.outcome("vid00000001", "complete", 200, 200)
    assert labels()[0][1] is None


def test_unknown_event_is_ignored(rs, clock):
    serve()
    learn.outcome("vid00000001", "lyrics_open")
    assert labels()[0][1] is None


def test_weights_stay_clipped(rs, clock):
    big = {**F, "sim": 50.0}
    for i in range(200):
        vid = f"vid{i:08d}"
        serve(vid, big)
        learn.outcome(vid, "complete", 200, 200)
    w, _ = learn.weights()
    assert all(-learn.CLIP <= x <= learn.CLIP for x in w.values())


def test_l2_pulls_unused_weights_back_to_the_prior(rs, clock):
    w0 = {**learn.PRIOR, "liked": 2.0}
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", ("ranker:tester", json.dumps({"w": w0, "n": 0})))
    serve()                                                    # liked = 0 in F: only the L2 term acts on it
    learn.outcome("vid00000001", "complete", 200, 200)
    w, _ = learn.weights()
    assert learn.PRIOR["liked"] < w["liked"] < 2.0


def test_weights_are_per_person(rs, clock):
    serve()
    learn.outcome("vid00000001", "complete", 200, 200)
    token = core.USER.set("someone-else")
    try:
        assert learn.weights() == (learn.PRIOR, 0)
    finally:
        core.USER.reset(token)
