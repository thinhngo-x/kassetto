"""Shared fixtures: every unit test gets its own empty database and people file, one person "tester"."""
import os, sys, time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import people  # noqa: E402
import recsys  # noqa: E402
from recsys import core, sound, synth  # noqa: E402

USER = "tester"


class Clock:
    def __init__(self, t0=1_700_000_000.0):
        self.t = t0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    """Simulated time for everything in recsys (they all call time.time())."""
    c = Clock()
    monkeypatch.setattr(time, "time", c)
    sound.EMB["ts"] = 0
    return c


@pytest.fixture
def rs(tmp_path, monkeypatch):
    """The recsys package on a fresh database, listening as USER."""
    monkeypatch.setattr(core, "DB", str(tmp_path / "ytm.db"))
    monkeypatch.setattr(people, "PATH", str(tmp_path / "people.json"))
    people.save({"owner": USER, "people": {USER: {"name": "Tester"}}, "circles": {}, "concerts": {}})
    core.init()
    sound.EMB["ts"] = 0
    token = core.USER.set(USER)
    yield recsys
    core.USER.reset(token)
    sound.EMB["ts"] = 0


@pytest.fixture
def cat(rs):
    """A small synthetic catalogue (6 genres x 5 artists x 8 tracks) with sound vectors, stored in the database."""
    c = synth.catalogue(np.random.default_rng(0))
    with core.db() as d:
        d.executemany("INSERT INTO tracks VALUES(?,?,?,?,?,?)",
                      [(v, t["title"], t["artist"], "", None, t["duration"]) for v, t in c.items()])
        d.executemany("INSERT INTO emb(video_id, vec, model, ts) VALUES(?,?,?,?)",
                      [(v, t["vec"].astype(np.float16).tobytes(), "test", 0) for v, t in c.items()])
    sound.EMB["ts"] = 0
    return c


def song(vid, cat):
    return synth.song(vid, cat)
