"""Unit tests for the HTTP client: auth, pagination, and error surfacing."""

from __future__ import annotations

import base64

import httpx
import pytest

from mcp_server_brewfather import client


def _ids(n: int, start: int = 0) -> list[dict]:
    return [{"_id": f"id{i:03d}", "name": f"Item {i}"} for i in range(start, start + n)]


def test_basic_auth_header(fake_api):
    api = fake_api({("GET", "recipes"): []})
    client.get_client().get("recipes")
    expected = "Basic " + base64.b64encode(b"uid:key").decode()
    assert api.requests[0].headers["authorization"] == expected


def test_paginate_follows_start_after(fake_api):
    api = fake_api({("GET", "batches"): [_ids(50), _ids(50, 50), _ids(3, 100)]})
    out = client.get_client().paginate("batches", {"status": "Fermenting"})
    assert len(out) == 103
    params = [dict(r.url.params) for r in api.requests]
    assert params[0] == {"status": "Fermenting", "limit": "50"}
    assert params[1]["start_after"] == "id049"
    assert params[2]["start_after"] == "id099"


def test_paginate_stops_on_short_first_page(fake_api):
    api = fake_api({("GET", "recipes"): [_ids(2)]})
    assert len(client.get_client().paginate("recipes")) == 2
    assert len(api.requests) == 1


def test_rate_limit_error_mentions_retry_after(fake_api):
    fake_api({("GET", "recipes"): httpx.Response(429, headers={"Retry-After": "120"})})
    with pytest.raises(client.BrewfatherError, match="retry after 120s"):
        client.get_client().get("recipes")


def test_http_error_raises(fake_api):
    fake_api({("GET", "recipes/x"): httpx.Response(403, text="Forbidden")})
    with pytest.raises(client.BrewfatherError, match="HTTP 403"):
        client.get_client().get("recipes/x")


def test_plain_text_response(fake_api):
    fake_api({("PATCH", "batches/b1"): "Updated"})
    assert client.get_client().patch("batches/b1", {"status": "Completed"}) == "Updated"


def test_get_client_requires_env(monkeypatch):
    monkeypatch.setattr(client, "_client", None)
    monkeypatch.delenv("BREWFATHER_USER_ID", raising=False)
    monkeypatch.delenv("BREWFATHER_API_KEY", raising=False)
    with pytest.raises(client.BrewfatherError, match="must be set"):
        client.get_client()
