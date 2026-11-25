import importlib

import pytest

import config


@pytest.fixture
def fresh(monkeypatch):
    for k in ("KASSETTO_DB", "YTM_DB", "KASSETTO_OWNER", "YTM_OWNER", "KASSETTO_REGION", "YTM_REGION"):
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch
    importlib.reload(config)


def test_new_name_wins_old_name_is_the_fallback(fresh):
    assert config.env("OWNER", "admin") == "admin"
    fresh.setenv("YTM_OWNER", "old")
    assert config.env("OWNER", "admin") == "old"
    fresh.setenv("KASSETTO_OWNER", "new")
    assert config.env("OWNER", "admin") == "new"
    fresh.setenv("KASSETTO_OWNER", "")                         # empty = unset
    assert config.env("OWNER", "admin") == "old"


def test_region_is_off_by_default(fresh):
    import region
    importlib.reload(region)
    assert region.CODE is None and region.LANGUAGE is None and not region.local("Sơn Tùng")


def test_known_region_brings_its_language(fresh):
    fresh.setenv("KASSETTO_REGION", "vn")
    import region
    importlib.reload(region)
    try:
        assert region.CODE == "VN" and region.NAME == "Vietnam" and region.LANGUAGE == "Vietnamese"
        assert region.local("Sơn Tùng") and not region.local("Daft Punk")
    finally:
        fresh.delenv("KASSETTO_REGION")
        importlib.reload(region)


def test_unknown_region_is_charts_only(fresh):
    fresh.setenv("KASSETTO_REGION", "BR")
    fresh.setenv("KASSETTO_REGION_NAME", "Brazil")
    import region
    importlib.reload(region)
    try:
        assert region.NAME == "Brazil" and region.LANGUAGE is None
    finally:
        fresh.delenv("KASSETTO_REGION")
        importlib.reload(region)
