"""Sign-in modes (server/auth.py) and the audio port's token."""
from unittest import mock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import config
from server import auth


def req(headers=None, peer="10.0.0.5", path="/api/me", match=None, query=""):
    t = mock.Mock()
    t.get_extra_info.side_effect = lambda k, d=None: (peer, 40000) if k == "peername" else d
    r = make_mocked_request("GET", path + (f"?{query}" if query else ""), headers=headers or {}, transport=t,
                            match_info=match or {})
    return r


@pytest.fixture
def mode(monkeypatch, rs):
    def set_(m, trusted=""):
        monkeypatch.setattr(auth, "MODE", m)
        monkeypatch.setattr(auth, "TRUSTED", [__import__("ipaddress").ip_network(x) for x in trusted.split(",") if x])
    return set_


def test_none_mode_is_always_the_owner_and_ignores_the_header(mode):
    mode("none")
    assert auth.identify(req()) == ("tester", None)
    assert auth.identify(req({"Remote-User": "mallory"})) == ("tester", None)


def test_proxy_mode_trusts_the_header_only_from_the_proxy(mode):
    mode("proxy", "10.0.0.0/24")
    assert auth.identify(req({"Remote-User": "Alice", "Remote-Name": "Alice A."})) == ("alice", "Alice A.")
    with pytest.raises(web.HTTPForbidden):
        auth.identify(req({"Remote-User": "alice"}, peer="192.0.2.9"))
    with pytest.raises(web.HTTPUnauthorized):
        auth.identify(req())                                    # from the proxy but without a user


def test_proxy_mode_rejects_odd_user_names(mode):
    mode("proxy", "10.0.0.5/32")
    with pytest.raises(web.HTTPBadRequest):
        auth.identify(req({"Remote-User": "a:b/c"}))


def test_proxy_mode_needs_trusted_networks(mode):
    mode("proxy")
    with pytest.raises(SystemExit):
        auth.check_config()
    mode("proxy", "172.16.0.0/12")
    assert auth.check_config() is None


def test_dev_mode_warns_and_keeps_the_old_behaviour(mode):
    mode("dev")
    assert "development" in auth.check_config()
    assert auth.identify(req(peer="192.0.2.9"))[0] == "tester"
    assert auth.identify(req({"Remote-User": "bob"}, peer="192.0.2.9"))[0] == "bob"


def test_unknown_mode_refuses_to_start(mode):
    mode("open")
    with pytest.raises(SystemExit):
        auth.check_config()


def test_stream_token(rs, monkeypatch):
    monkeypatch.setattr(auth, "_KEY", {})
    k = auth.stream_key()
    assert k == auth.stream_key() and len(k) == 32              # made once, kept
    vid = "abcdefghijk"
    good = config.stream_token(k, vid)
    auth.check_stream_token(req(path=f"/stream/{vid}", match={"vid": vid}, query=f"t={good}"))
    for q in ("", "t=nope", "t=" + config.stream_token(k, "otherVideo1")):
        with pytest.raises(web.HTTPForbidden):
            auth.check_stream_token(req(path=f"/stream/{vid}", match={"vid": vid}, query=q))
