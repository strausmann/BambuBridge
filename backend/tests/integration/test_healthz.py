from __future__ import annotations

import httpx


async def test_healthz_no_auth_returns_ok(client: httpx.AsyncClient):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
