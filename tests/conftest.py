"""Shared pytest fixtures and acceptance-test gating.

Unit tests run everywhere and never touch the network — they monkeypatch
``client.get_client`` with a real :class:`BrewfatherClient` wired to an
``httpx.MockTransport``, so auth, pagination and error handling are exercised too.

Acceptance tests hit the live Brewfather API and are skipped unless you opt in with
``--run-acceptance`` *and* the required credentials are present in the environment.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest


# --------------------------------------------------------------------------- #
# Acceptance-test gating
# --------------------------------------------------------------------------- #
def pytest_addoption(parser):
    parser.addoption(
        "--run-acceptance",
        action="store_true",
        default=False,
        help="run acceptance tests against the live Brewfather API",
    )


_REQUIRED_ACCEPTANCE_ENV = ("BREWFATHER_USER_ID", "BREWFATHER_API_KEY")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-acceptance"):
        missing = [v for v in _REQUIRED_ACCEPTANCE_ENV if not os.environ.get(v)]
        if missing:
            skip = pytest.mark.skip(reason=f"acceptance env not set: {', '.join(missing)}")
            for item in items:
                if "acceptance" in item.keywords:
                    item.add_marker(skip)
        return
    skip = pytest.mark.skip(reason="need --run-acceptance to run live Brewfather tests")
    for item in items:
        if "acceptance" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------- #
# Mock Brewfather API for unit tests
# --------------------------------------------------------------------------- #
class FakeAPI:
    """Routes ``(method, path)`` to canned responses and records every request.

    A route's value is a response body, or a list of bodies served in order (for
    pagination), or an ``httpx.Response`` for status/header control.
    """

    def __init__(self, routes: dict):
        self.routes = {
            k: (list(v) if isinstance(v, list) and _is_pages(v) else v) for k, v in routes.items()
        }
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/v2/")
        route = self.routes.get((request.method, path))
        if route is None:
            return httpx.Response(404, text="Not Found")
        if isinstance(route, httpx.Response):
            return route
        if isinstance(route, list) and _is_pages(route):
            route = route.pop(0) if route else []
        if isinstance(route, str):
            return httpx.Response(200, text=route)
        return httpx.Response(200, json=route)

    def bodies(self, method: str = "PATCH") -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == method]


def _is_pages(value: list) -> bool:
    """A list of lists is a sequence of pages; a flat list is a single body."""
    return bool(value) and all(isinstance(p, list) for p in value)


@pytest.fixture
def fake_api(monkeypatch):
    """Patch ``client.get_client`` to a client backed by a :class:`FakeAPI`.

    Returns a factory taking the routes dict; the factory returns the FakeAPI so
    tests can inspect ``requests``.
    """
    from mcp_server_brewfather import client

    def _install(routes: dict) -> FakeAPI:
        api = FakeAPI(routes)
        bf = client.BrewfatherClient("uid", "key", transport=httpx.MockTransport(api))
        monkeypatch.setattr(client, "get_client", lambda: bf)
        return api

    return _install
