"""The synthetic listener runs the whole loop: rank -> react -> record -> learn."""
from recsys import learn, synth


def test_simulation_runs_and_learns(tmp_path):
    r = synth.simulate(seed=0, sessions=8, history_days=5, db_path=str(tmp_path / "s.db"))
    assert len(r["finished"]) == 8 and all(0 <= x <= 1 for x in r["finished"])
    assert r["served"] > 0 and 0 < r["labelled"] <= r["served"]
    assert r["auc_start"] is not None and r["auc_learned"] is not None
    assert r["weights"] != learn.PRIOR
    assert all(-learn.CLIP <= x <= learn.CLIP for x in r["weights"].values())


def test_learning_off_keeps_the_prior(tmp_path):
    r = synth.simulate(seed=0, sessions=4, history_days=3, learning=False, db_path=str(tmp_path / "s.db"))
    assert r["weights"] == learn.PRIOR
