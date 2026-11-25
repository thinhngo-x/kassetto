"""How well does the ranker predict what you actually finish? Offline check on your labelled picks.

  docker compose exec kassetto python -m recsys.evaluate [user]

For every pick Kassetto served that later got an outcome (impressions.label), compares the score the pick would get
from the starting (hand-tuned) weights, from your learned weights, and from each feature alone, against what
happened: AUC = the chance that a pick you kept (label >= 0.5) scored higher than one you didn't (0.5 = coin flip,
1 = perfect). Also: how the learned weights moved, and keep rate per source.
"""
import json, sys

from .core import *  # noqa
from . import learn


def auc(scores, ys):
    pos = [s for s, y in zip(scores, ys) if y >= 0.5]
    neg = [s for s, y in zip(scores, ys) if y < 0.5]
    if not pos or not neg:
        return None
    wins = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def main(user=None):
    if user:
        USER.set(user)
    with db() as c:
        rows = c.execute("SELECT feats, label, why, event FROM impressions WHERE user=? AND label IS NOT NULL", (me(),)).fetchall()
        served = c.execute("SELECT COUNT(*) FROM impressions WHERE user=?", (me(),)).fetchone()[0]
    print(f"{me()}: {served} picks served, {len(rows)} with an outcome")
    if len(rows) < 10:
        print("not enough outcomes yet to measure (needs ~10+; they accumulate as you listen)")
    F = [json.loads(r[0]) for r in rows]; Y = [r[1] for r in rows]
    w, n = learn.weights()
    fmt = lambda a: "n/a" if a is None else f"{a:.2f}"
    if rows:
        print(f"AUC  start weights {fmt(auc([learn.score(f, learn.PRIOR) for f in F], Y))}   "
              f"learned weights {fmt(auc([learn.score(f, w) for f in F], Y))}  ({n} updates)")
        print("AUC by feature alone (sign: higher = keep):")
        for k in learn.FEATURES[1:]:
            a = auc([f.get(k, 0) for f in F], Y)
            print(f"  {k:11s} {fmt(a)}")
        by = {}
        for r in rows:
            by.setdefault(r[2] or "?", []).append(r[1])
        print("keep rate by source:", {k: f"{sum(v) / len(v):.0%} of {len(v)}" for k, v in by.items()})
    print("weights (start -> now):", {k: f"{learn.PRIOR[k]:+.2f}->{w[k]:+.2f}" for k in learn.FEATURES})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
