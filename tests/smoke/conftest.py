"""Smoke tests run against a running dev stack (docker-compose.dev.yml), never against a real install.

  docker compose -f docker-compose.dev.yml up -d --build
  pytest tests/smoke                       # KASSETTO_URL / KASSETTO_AUDIO_URL to point elsewhere
  KASSETTO_NETWORK=1 pytest tests/smoke    # + the tests that need YouTube
"""
import json, os, urllib.error, urllib.request

import pytest

BASE = os.environ.get("KASSETTO_URL", "http://127.0.0.1:18090").rstrip("/")
AUDIO = os.environ.get("KASSETTO_AUDIO_URL", "http://127.0.0.1:18091").rstrip("/")


class Resp:
    def __init__(self, status, body, headers):
        self.status, self.body, self.headers = status, body, headers

    def json(self):
        return json.loads(self.body)


def call(method, path, body=None, user=None, base=BASE, timeout=20):
    h = {"Content-Type": "application/json"}
    if user:
        h["Remote-User"] = user
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.status, r.read(), r.headers)
    except urllib.error.HTTPError as e:
        return Resp(e.code, e.read(), e.headers)


def pytest_collection_modifyitems(config, items):
    try:
        ok = call("GET", "/healthz", timeout=3).status == 200
    except OSError:
        ok = False
    skip_all = pytest.mark.skip(reason=f"no dev stack at {BASE}")
    skip_net = pytest.mark.skip(reason="needs the internet: KASSETTO_NETWORK=1")
    for it in items:
        if not ok:
            it.add_marker(skip_all)
        elif "network" in it.keywords and os.environ.get("KASSETTO_NETWORK") != "1":
            it.add_marker(skip_net)


@pytest.fixture
def api():
    return call
