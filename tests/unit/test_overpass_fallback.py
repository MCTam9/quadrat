"""Overpass fallback: a busy primary must not fail the report."""

from __future__ import annotations

import pytest
from osmnx._errors import InsufficientResponseError

from sce.providers import _overpass


@pytest.fixture(autouse=True)
def _reset_cooldown():
    _overpass._down_until.clear()
    yield
    _overpass._down_until.clear()


def test_falls_through_to_next_endpoint(monkeypatch):
    monkeypatch.setenv("SCE_OVERPASS_URLS", "https://a.example/api,https://b.example/api")
    seen = []

    def query():
        import osmnx as ox

        seen.append(ox.settings.overpass_url)
        if ox.settings.overpass_url.startswith("https://a."):
            raise ConnectionError("502 at capacity")
        return "ok"

    assert _overpass.with_overpass_fallback(query) == "ok"
    assert seen == ["https://a.example/api", "https://b.example/api"]


def test_empty_result_is_not_retried(monkeypatch):
    monkeypatch.setenv("SCE_OVERPASS_URLS", "https://a.example/api,https://b.example/api")
    calls = []

    def query():
        calls.append(1)
        raise InsufficientResponseError("no data")

    with pytest.raises(InsufficientResponseError):
        _overpass.with_overpass_fallback(query)
    assert len(calls) == 1


def test_all_fail_reports_every_endpoint(monkeypatch):
    monkeypatch.setenv("SCE_OVERPASS_URLS", "https://a.example/api,https://b.example/api")

    def query():
        raise TimeoutError("timed out")

    with pytest.raises(RuntimeError, match=r"a\.example.*b\.example"):
        _overpass.with_overpass_fallback(query)


def test_failed_endpoint_is_tried_last_next_time(monkeypatch):
    monkeypatch.setenv("SCE_OVERPASS_URLS", "https://a.example/api,https://b.example/api")

    def query():
        import osmnx as ox

        if ox.settings.overpass_url.startswith("https://a."):
            raise ConnectionError("down")
        return ox.settings.overpass_url

    _overpass.with_overpass_fallback(query)
    assert _overpass.overpass_urls() == ["https://b.example/api", "https://a.example/api"]
