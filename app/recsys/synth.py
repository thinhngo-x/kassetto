"""A synthetic listener: an offline test bench for the recommender, no YouTube and no real people needed.

  python -m recsys.synth [--sessions 60] [--seeds 3]

It builds a small fake catalogue (genres -> artists -> tracks, each with a CLAP-like sound vector), a listener
with a hidden taste (loved / liked / disliked genres, per-artist and per-track quirks, a mood per session,
fatigue on repeats), seeds a few weeks of history, then runs listening sessions through the real code path:
rank() serves autoplay picks, the listener reacts (finishes, half-hears, skips, likes, leaves), record() logs
the events, so impressions get labels and learn / bandit / boredom / session all do their work.

Each scenario runs twice with the same random seed: with the learned ranker, and with learning switched off
(weights reset to the prior after every event). The report compares how many autoplay picks the listener
finished, in the later sessions, and the evaluate-style AUC of the start vs learned weights on the labelled picks.
It is a sanity check of the pipeline, not proof of quality on real people: the listener is a model we wrote.
"""
import argparse, json, math, os, random, tempfile, time

import numpy as np

import people
from . import core, learn, sound
from .evaluate import auc
from .events import record
from .ranking import rank
from .taste import taste

USER = "synth"
DIM = 32


class Clock:
    """Simulated time: the recommender reads time.time(), and plays need to spread over days."""

    def __init__(self, t0):
        self.t = float(t0)

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def catalogue(rng, genres=6, artists=5, tracks=8):
    """-> {vid: {title, artist, genre, duration, vec}}: genre centres, artists around them, tracks around artists."""
    cat = {}
    G = rng.normal(size=(genres, DIM))
    for g in range(genres):
        for a in range(artists):
            ac = G[g] + 0.6 * rng.normal(size=DIM)
            for t in range(tracks):
                v = ac + 0.5 * rng.normal(size=DIM)
                vid = f"g{g}a{a}t{t}".ljust(11, "_")[:11]
                cat[vid] = {"title": f"Song {t} of artist {g}-{a}", "artist": f"Artist {g}-{a}", "genre": g,
                            "duration": int(rng.integers(150, 300)), "vec": (v / np.linalg.norm(v)).astype(np.float32)}
    return cat


class Listener:
    """Hidden taste: utility(track) = genre + artist + track quirks + this session's mood - fatigue."""

    def __init__(self, rng, cat, genres=6):
        order = rng.permutation(genres)
        self.genre = {int(order[0]): 1.6, int(order[1]): 1.2, int(order[2]): 0.3}
        for g in order[3:]:
            self.genre[int(g)] = -1.2
        self.artist = {t["artist"]: rng.normal(0, 0.7) for t in cat.values()}
        self.track = {v: rng.normal(0, 0.5) for v in cat}
        self.rng, self.cat = rng, cat
        self.mood = None
        self.heard = {}                                            # vid -> [ts]

    def utility(self, vid, now):
        t = self.cat[vid]
        u = self.genre[t["genre"]] + self.artist[t["artist"]] + self.track[vid]
        if self.mood is not None and t["genre"] == self.mood:
            u += 0.8
        recent = sum(1 for ts in self.heard.get(vid, []) if now - ts < 3 * 86400)
        return u - 0.9 * recent

    def react(self, vid, now):
        """-> (event, seconds played, liked?)"""
        u, dur = self.utility(vid, now), self.cat[vid]["duration"]
        self.heard.setdefault(vid, []).append(now)
        if self.rng.random() < 1 / (1 + math.exp(-(1.3 * u - 0.4))):
            return "complete", dur, u > 1.8 and self.rng.random() < 0.2
        if self.rng.random() < 0.4:
            return "partial", int(dur * self.rng.uniform(0.35, 0.75)), False
        return "skip", int(self.rng.uniform(3, 25)), False


def song(vid, cat):
    t = cat[vid]
    return {"type": "song", "videoId": vid, "title": t["title"], "artist": t["artist"], "album": "", "thumb": None,
            "duration": t["duration"]}


def radio(vid, cat, n, rng):
    """Like a YouTube radio: the seed, then sound neighbours in roughly (not exactly) similarity order."""
    v = cat[vid]["vec"]
    ids = [x for x in cat if x != vid]
    sims = np.array([cat[x]["vec"] @ v for x in ids]) + rng.normal(0, 0.15, len(ids))
    return [song(vid, cat)] + [song(ids[i], cat) for i in np.argsort(-sims)[: n - 1]]


def _setup(db_path):
    """Point the recommender at a fresh database + people file (one person, no circles)."""
    core.DB = db_path
    people.PATH = os.path.join(os.path.dirname(db_path), "people.json")
    people.save({"owner": USER, "people": {USER: {"name": "Synthetic listener"}}, "circles": {}, "concerts": {}})
    core.init()
    sound.EMB["ts"] = 0


def simulate(seed=0, sessions=60, learning=True, db_path=None, history_days=21, picks_per_session=12):
    """One scenario. -> {"finished": [per-session share of autoplay picks finished], "auc_start", "auc_learned",
    "weights", "served", "labelled"}."""
    rng = np.random.default_rng(seed)
    random.seed(seed)
    cat = catalogue(rng)
    listener = Listener(rng, cat)
    tmp = None
    if db_path is None:
        tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(tmp.name, "synth.db")
    clock = Clock(1_700_000_000)
    real_time = time.time
    time.time = clock                                             # every recsys module calls time.time()
    token = core.USER.set(USER)
    try:
        _setup(db_path)
        with core.db() as c:
            c.executemany("INSERT INTO tracks VALUES(?,?,?,?,?,?)",
                          [(v, t["title"], t["artist"], "", None, t["duration"]) for v, t in cat.items()])
            c.executemany("INSERT INTO emb(video_id, vec, model, ts) VALUES(?,?,?,?)",
                          [(v, t["vec"].astype(np.float16).tobytes(), "synth", 0) for v, t in cat.items()])
        vids = list(cat)
        good = [v for v in vids if listener.genre[cat[v]["genre"]] > 1]
        for _ in range(history_days * 2):                         # history: two sessions a day, the listener's choice
            for _ in range(10):
                v = random.choice(good) if rng.random() < 0.7 else random.choice(vids)
                ev, played, liked = listener.react(v, clock())
                record({**song(v, cat), "event": ev, "played": played})
                if liked:
                    record({**song(v, cat), "event": "like"})
                clock.advance(played + 5)
            clock.advance(12 * 3600)
        finished = []
        loved = [g for g, w in listener.genre.items() if w > 0]
        for _ in range(sessions):
            listener.mood = int(rng.choice(loved))
            seed_vid = max(random.sample([v for v in vids if cat[v]["genre"] == listener.mood], 6),
                           key=lambda v: listener.utility(v, clock()))
            ev, played, _ = listener.react(seed_vid, clock())     # the song you chose yourself
            record({**song(seed_vid, cat), "event": ev, "played": played})
            clock.advance(played + 5)
            _, _, anchors = taste()
            anch = [radio(a, cat, 20, rng) for a in random.sample(anchors[:10], min(2, len(anchors[:10])))]
            picks = rank(radio(seed_vid, cat, 30, rng), anch, [song(v, cat) for v in random.sample(vids, 10)],
                         {seed_vid}, n=picks_per_session, hour=time.localtime(clock()).tm_hour, ctx="autoplay",
                         flow_from=seed_vid)
            done, skips_in_row = 0, 0
            for i, p in enumerate(picks):
                ev, played, liked = listener.react(p["videoId"], clock())
                record({**p, "event": ev, "played": played, "duration": p["duration"]})
                if liked:
                    record({**p, "event": "like"})
                done += ev == "complete"
                clock.advance(played + 2)
                skips_in_row = skips_in_row + 1 if ev == "skip" else 0
                if skips_in_row >= 3:                             # had enough: leave autoplay
                    for q in picks[i + 1: i + 3]:
                        record({**q, "event": "escape", "auto": True})
                    break
                if not learning:
                    with core.db() as c:
                        c.execute("DELETE FROM kv WHERE k=?", (f"ranker:{USER}",))
            finished.append(done / max(1, len(picks)))
            clock.advance(rng.uniform(5, 14) * 3600)
        with core.db() as c:
            rows = c.execute("SELECT feats, label FROM impressions WHERE user=? AND label IS NOT NULL", (USER,)).fetchall()
            served = c.execute("SELECT COUNT(*) FROM impressions WHERE user=?", (USER,)).fetchone()[0]
        F, Y = [json.loads(r[0]) for r in rows], [r[1] for r in rows]
        w, _ = learn.weights()
        return {"finished": finished, "served": served, "labelled": len(rows), "weights": w,
                "auc_start": auc([learn.score(f, learn.PRIOR) for f in F], Y),
                "auc_learned": auc([learn.score(f, w) for f in F], Y)}
    finally:
        time.time = real_time
        core.USER.reset(token)
        sound.EMB["ts"] = 0
        if tmp:
            tmp.cleanup()


def benchmark(seeds=3, sessions=60):
    """Learning on vs off over several seeds. -> summary dict (finished share in the last third of sessions)."""
    out = {"learned": [], "prior": [], "auc_start": [], "auc_learned": []}
    for s in range(seeds):
        on, off = simulate(s, sessions, learning=True), simulate(s, sessions, learning=False)
        tail = sessions // 3
        out["learned"].append(float(np.mean(on["finished"][-tail:])))
        out["prior"].append(float(np.mean(off["finished"][-tail:])))
        out["auc_start"].append(on["auc_start"])
        out["auc_learned"].append(on["auc_learned"])
    return {k: float(np.mean([x for x in v if x is not None])) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sessions", type=int, default=60)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    r = benchmark(a.seeds, a.sessions)
    print(f"synthetic listener, {a.seeds} seeds x {a.sessions} sessions (last third):")
    print(f"  autoplay picks finished   learned ranker {r['learned']:.1%}   prior weights only {r['prior']:.1%}")
    print(f"  AUC on labelled picks     start weights {r['auc_start']:.3f}   learned weights {r['auc_learned']:.3f}")


if __name__ == "__main__":
    main()
