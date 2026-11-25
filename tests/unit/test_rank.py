"""Invariants of rank(): whatever the candidates, these must hold for every batch of picks."""
import random

import numpy as np
import pytest

from recsys import core, events, ranking, synth
from recsys.bandit import ARMS

N = 20


@pytest.fixture
def history(rs, cat, clock):
    """Some weeks of listening: genre 0 finished and liked, genre 5 skipped."""
    random.seed(1)
    for i, v in enumerate(cat):
        g = cat[v]["genre"]
        if g == 0:
            events.record({**synth.song(v, cat), "event": "complete", "played": cat[v]["duration"]})
            if i % 4 == 0:
                events.record({**synth.song(v, cat), "event": "like"})
        elif g == 5:
            events.record({**synth.song(v, cat), "event": "skip", "played": 4})
        clock.advance(4 * 3600)
    return cat


def batch(cat, exclude=frozenset(), n=N, seed=0):
    rng = np.random.default_rng(seed)
    random.seed(seed)
    vids = list(cat)
    s = vids[3]
    return ranking.rank(synth.radio(s, cat, 40, rng), [synth.radio(vids[50], cat, 25, rng)],
                        [synth.song(v, cat) for v in random.sample(vids, 15)], set(exclude) | {s}, n=n,
                        hour=12, ctx="test", flow_from=s)


@pytest.mark.parametrize("seed", range(5))
def test_batch_invariants(history, seed):
    cat = history
    picks = batch(cat, seed=seed)
    assert 0 < len(picks) <= N
    vids = [p["videoId"] for p in picks]
    assert len(set(vids)) == len(vids)                         # no duplicates
    arts = [p["artist"] for p in picks]
    assert all(a != b for a, b in zip(arts, arts[1:]))         # never the same artist twice in a row
    assert max(arts.count(a) for a in arts) <= 3               # <= 3 per artist per batch
    assert all(p["why"] in ARMS.values() for p in picks)
    assert all("_f" not in p and "_score" not in p for p in picks)
    assert all(p["auto"] for p in picks)
    fam = sum(p["why"] == ARMS["familiar"] for p in picks)
    assert fam <= max(1, 0.35 * len(picks))                    # familiarity cap


def test_excluded_hidden_and_twice_rejected_are_never_picked(history, clock):
    cat = history
    vids = list(cat)
    first = batch(cat)
    hidden, excluded = first[0]["videoId"], first[1]["videoId"]
    events.record({**synth.song(hidden, cat), "event": "hide"})
    rejected = first[2]["videoId"]
    for _ in range(2):
        events.record({**synth.song(rejected, cat), "event": "skip", "played": 3, "duration": 200})
        clock.advance(3600)
    for seed in range(5):
        got = {p["videoId"] for p in batch(cat, exclude={excluded}, seed=seed)}
        assert not got & {hidden, excluded, rejected, vids[3]}


def test_every_pick_is_logged_with_its_features(history):
    picks = batch(history)
    with core.db() as c:
        rows = c.execute("SELECT video_id, ctx, feats FROM impressions").fetchall()
    assert [r[0] for r in rows] == [p["videoId"] for p in picks]
    assert all(r[1] == "test" for r in rows)
    import json
    from recsys import learn
    assert all(set(json.loads(r[2])) == set(learn.FEATURES) for r in rows)


def test_taste_shows_in_the_picks(history):
    """Loved genre 0 should be served far more than skipped genre 5."""
    got = [history[p["videoId"]]["genre"] for s in range(3) for p in batch(history, seed=s)]
    assert got.count(0) > got.count(5)


def test_empty_candidates(rs):
    assert ranking.rank([], [], [], set(), n=10) == []



def test_flow_never_puts_an_artist_twice_in_a_row():
    rng = np.random.default_rng(0)
    for trial in range(200):
        xs = [{"v": k, "art": rng.choice(["a", "b", "c"], p=[0.6, 0.2, 0.2]), "vec": None if rng.random() < 0.2 else
               (lambda v: v / np.linalg.norm(v))(rng.normal(size=8))} for k in range(int(rng.integers(3, 12)))]
        out = ranking.flow(list(xs), xs[0]["vec"])
        assert sorted(map(id, out)) == sorted(map(id, xs))     # a reordering, nothing lost
        arts = [x["art"] for x in xs]
        if max(arts.count(a) for a in arts) <= (len(xs) + 1) // 2:   # possible at all
            assert all(p["art"] != q["art"] for p, q in zip(out, out[1:])), [x["art"] for x in out]
