"""Brewfather API v2 client.

A thin wrapper over httpx: HTTP Basic auth from the environment
(``BREWFATHER_USER_ID`` / ``BREWFATHER_API_KEY``), JSON in and out, and
``start_after`` pagination. What the server may touch is decided by the API
key's scopes, set when you generate it in Brewfather — and the server never
calls a delete endpoint regardless.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

BASE_URL = "https://api.brewfather.app/v2/"
PAGE_SIZE = 50  # API max for list endpoints.

_client: BrewfatherClient | None = None


class BrewfatherError(ToolError):
    """An API call failed; the message is meant to be read by the model.

    A ToolError so mcp passes the message through instead of a generic error.
    """


class BrewfatherClient:
    def __init__(
        self, user_id: str, api_key: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._http = httpx.Client(
            base_url=BASE_URL, auth=(user_id, api_key), timeout=30.0, transport=transport
        )

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def patch(self, path: str, body: dict) -> Any:
        return self._request("PATCH", path, json=body)

    def post(self, path: str, body: dict) -> Any:
        return self._request("POST", path, json=body)

    def paginate(self, path: str, params: dict | None = None) -> list[dict]:
        """GET every page of a list endpoint, following ``start_after`` by ``_id``."""
        params = {**(params or {}), "limit": PAGE_SIZE}
        out: list[dict] = []
        while True:
            page = self.get(path, params)
            out.extend(page)
            if len(page) < PAGE_SIZE:
                return out
            params["start_after"] = page[-1]["_id"]

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise BrewfatherError(f"{method} {path} failed: {type(e).__name__}: {e}") from e
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "?")
            raise BrewfatherError(
                f"rate limited (500 calls/hour per API key); retry after {retry}s"
            )
        if resp.is_error:
            raise BrewfatherError(
                f"{method} {path} failed: HTTP {resp.status_code} {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError:
            return resp.text  # PATCH endpoints answer with plain text, e.g. "Updated".


def get_client() -> BrewfatherClient:
    """Return a cached client built from the environment (creates it on first call)."""
    global _client
    if _client is None:
        user_id = os.environ.get("BREWFATHER_USER_ID")
        api_key = os.environ.get("BREWFATHER_API_KEY")
        if not user_id or not api_key:
            raise BrewfatherError("BREWFATHER_USER_ID and BREWFATHER_API_KEY must be set")
        _client = BrewfatherClient(user_id, api_key)
    return _client
