import json
import random

import numpy as np

from recsys import core, learn

F = {"bias": 1.0, "sim": 0.8, "aff": 0.5, "snd": 0.2, "sess": 0.0, "sess_art": 0.0, "new_artist": 0.0,
     "recent": 0.0, "skips": 0.0, "liked": 0.0}


def serve(vid="vid00000001", f=F):
    learn.log_impressions([{"videoId": vid, "why": "similar", "_score": 0.0, "_f": f}], "test")


def labels():
    with core.db() as c:
        return c.execute("SELECT video_id, label, event FROM impressions ORDER BY id").fetchall()


def listen(clock, n, rule, seed=0):
    """n picks with random features; rule(f) -> True = finished. One outcome a minute."""
    rng = random.Random(seed)
    for i in range(n):
        f = {**{k: 0.0 for k in learn.FEATURES}, "bias": 1.0,
             **{k: rng.random() for k in ("sim", "aff", "snd", "sess")}}
        vid = f"vid{i:08d}"
        serve(vid, f)
        learn.outcome(vid, "complete" if rule(f) else "skip", 200 if rule(f) else 4, 200)
        clock.advance(60)


def test_starts_at_the_prior(rs):
    w, n = learn.weights()
    assert w == learn.PRIOR and n == 0


def test_outcome_without_impression_changes_nothing(rs, clock):
    learn.outcome("vid00000001", "complete", 200, 200)
    assert learn.weights() == (learn.PRIOR, 0)


def test_finished_pick_is_labelled(rs, clock):
    serve()
    learn.outcome("vid00000001", "complete", 200, 200)
    assert labels() == [("vid00000001", 1.0, "complete")]


def test_partial_is_graded_by_share_heard(rs, clock):
    serve()
    learn.outcome("vid00000001", "partial", 120, 240)          # half heard: listen_weight 0.4
    assert abs(labels()[0][1] - (0.4 + 1.2) / 2.2) < 1e-9


def test_one_outcome_per_impression(rs, clock):
    serve()
    learn.outcome("vid00000001", "complete", 200, 200)
    learn.outcome("vid00000001", "skip", 3, 200)               # no unlabelled impression left
    assert [r[1] for r in labels()] == [1.0]


def test_old_impressions_are_not_labelled(rs, clock):
    serve()
    clock.advance(learn.WINDOW + 60)
    learn.outcome("vid00000001", "complete", 200, 200)
    assert labels()[0][1] is None


def test_unknown_event_is_ignored(rs, clock):
    serve()
    learn.outcome("vid00000001", "lyrics_open")
    assert labels()[0][1] is None


def test_few_outcomes_keep_the_prior(rs, clock):
    listen(clock, 5, lambda f: f["aff"] > 0.5)
    assert learn.weights() == (learn.PRIOR, 0)


def test_pairs_compare_nearby_outcomes_with_different_labels():
    a, b = {"sim": 1.0}, {"sim": 0.0}
    rows = [(a, 1.0, 0), (b, 0.0, 60), (a, 0.9, 120), (b, 0.0, 120 + learn.PAIR_WINDOW + 1)]
    D, T, W = learn.pairs(rows)
    k = learn.FEATURES.index("sim")
    # (b vs a): b lost; (a' vs b): a' won; (a' vs a): labels too close; last row: too long after the others
    assert [round(t, 2) for t in T] == [0.0, 0.95]
    assert list(D[:, k]) == [-1.0, 1.0]
    assert W[0] < W[1] <= 1.0                                   # older outcomes count less


def test_learns_what_matters_to_you(rs, clock):
    """Only artist affinity decides here: its weight grows relative to the others."""
    listen(clock, 300, lambda f: f["aff"] > 0.5)
    w, n = learn.weights()
    assert n > 0
    rel = lambda w: w["aff"] / (abs(w["sim"]) + abs(w["snd"]) + abs(w["sess"]))
    assert rel(w) > 2 * rel(learn.PRIOR)


def test_learned_weights_rank_better_than_the_prior(rs, clock):
    listen(clock, 300, lambda f: f["sess"] > f["sim"])          # against the prior's sim > sess
    w, _ = learn.weights()
    assert w["sess"] > w["sim"]


def test_weights_stay_clipped(rs, clock):
    listen(clock, 300, lambda f: f["aff"] > 0.5)
    w, _ = learn.weights()
    assert all(-learn.CLIP <= x <= learn.CLIP for x in w.values())


def test_posterior_narrows_with_evidence(rs, clock):
    listen(clock, 300, lambda f: f["aff"] > 0.5)
    _, sd, _ = learn.posterior()
    assert sd["aff"] < learn.PRIOR_SD["aff"]
    assert sd["liked"] == learn.PRIOR_SD["liked"] or abs(sd["liked"] - learn.PRIOR_SD["liked"]) < 1e-6   # never seen


def test_thompson_draws_spread_with_the_posterior(rs):
    random.seed(0)
    assert learn.sample(scale=0) == learn.PRIOR
    draws = np.array([learn.sample()["sim"] for _ in range(2000)])
    assert abs(draws.mean() - learn.PRIOR["sim"]) < 0.05
    assert abs(draws.std() - learn.EXPLORE * learn.PRIOR_SD["sim"]) < 0.05


def test_an_old_state_restarts_at_the_prior(rs):
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES(?, ?)", ("ranker:tester", json.dumps({"w": {"sim": 3.0}, "n": 9})))
    assert learn.weights()[0] == learn.PRIOR


def test_weights_are_per_person(rs, clock):
    listen(clock, 100, lambda f: f["aff"] > 0.5)
    token = core.USER.set("someone-else")
    try:
        assert learn.weights() == (learn.PRIOR, 0)
    finally:
        core.USER.reset(token)
