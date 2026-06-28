"""Tests for BR-5 (lazy-init via lifespan) and BR-1 (X-API-Key auth)."""
import os

import yaml
from fastapi.testclient import TestClient

CONFIG_PATH = os.environ["BRIDGE_CONFIG"]


def write_config(api_key: str = "") -> None:
    cfg: dict = {"printers": [], "spoolman": {"base_url": "http://localhost:7912"}}
    if api_key:
        cfg["security"] = {"api_key": api_key}
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh)


# ---- BR-5: lazy init -----------------------------------------------------
def test_import_does_not_require_config():
    """Importing the app must not instantiate Bridge or read config.yaml."""
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)
    import app.main as m

    assert m.bridge is None  # created only inside the lifespan handler


def test_lifespan_creates_and_clears_bridge():
    write_config()
    import app.main as m

    with TestClient(m.app):
        assert m.bridge is not None
    assert m.bridge is None  # cleared on shutdown


def test_api_returns_503_when_bridge_not_ready():
    """Without the lifespan having run, bridge is None -> API calls get a clean 503."""
    import app.main as m

    m.bridge = None  # simulate the startup window
    client = TestClient(m.app)  # no `with` -> lifespan not started
    r = client.get("/api/printers")
    assert r.status_code == 503
    assert r.json() == {"detail": "bridge not ready", "error_code": "service_unavailable"}


# ---- BR-1: auth ----------------------------------------------------------
def test_read_route_needs_no_key():
    write_config(api_key="secret")
    import app.main as m

    with TestClient(m.app) as c:
        r = c.get("/api/printers")
        assert r.status_code == 200
        assert r.json() == []


def test_mutating_route_rejects_missing_key():
    write_config(api_key="secret")
    import app.main as m

    with TestClient(m.app) as c:
        r = c.post("/api/slot/stage", json={"serial": "x", "ams_id": 0, "tray_id": 0})
        assert r.status_code == 401
        assert r.json() == {"detail": "unauthorized", "error_code": "unauthorized"}


def test_mutating_route_rejects_wrong_key():
    write_config(api_key="secret")
    import app.main as m

    with TestClient(m.app) as c:
        r = c.post(
            "/api/slot/stage",
            headers={"X-API-Key": "nope"},
            json={"serial": "x", "ams_id": 0, "tray_id": 0},
        )
        assert r.status_code == 401


def test_mutating_route_accepts_valid_key():
    write_config(api_key="secret")
    import app.main as m

    with TestClient(m.app) as c:
        r = c.post(
            "/api/slot/stage",
            headers={"X-API-Key": "secret"},
            json={"serial": "x", "ams_id": 0, "tray_id": 0},
        )
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_homelab_profile_disables_auth():
    """No key configured -> mutating routes are allowed (HomeLab profile)."""
    write_config(api_key="")
    import app.main as m

    with TestClient(m.app) as c:
        r = c.post("/api/slot/stage", json={"serial": "x", "ams_id": 0, "tray_id": 0})
        assert r.status_code == 200


def test_api_key_via_env(monkeypatch):
    write_config(api_key="")  # no key in file ...
    monkeypatch.setenv("BRIDGE_API_KEY", "fromenv")  # ... but in env
    import app.main as m

    with TestClient(m.app) as c:
        assert c.post("/api/slot/stage", json={"serial": "x", "ams_id": 0, "tray_id": 0}).status_code == 401
        ok = c.post(
            "/api/slot/stage",
            headers={"X-API-Key": "fromenv"},
            json={"serial": "x", "ams_id": 0, "tray_id": 0},
        )
        assert ok.status_code == 200
