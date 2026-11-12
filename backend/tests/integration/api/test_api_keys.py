from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.tokens import TOKEN_PREFIX
from app.db.session import make_session_factory
from app.models.api_key import ApiKey
from app.models.user import User
from app.repositories import api_keys as api_keys_repo
from tests.conftest import KEY_HEADER, issue_token

BASE = "/api/v1/admin/api-keys"


def _problem(r: httpx.Response, status: int, error_code: str) -> None:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == status
    assert body["error_code"] == error_code


async def _key_row(engine: AsyncEngine, plaintext: str) -> ApiKey:
    async with make_session_factory(engine)() as session:
        row = await session.scalar(select(ApiKey).where(ApiKey.prefix == plaintext[:16]))
        assert row is not None
        return row


# --- authentication and scopes -------------------------------------------------------------


async def test_missing_token_401(client: httpx.AsyncClient):
    _problem(await client.get(BASE), 401, "not_authenticated")


async def test_wrong_token_401_wrong_scope_403(client: httpx.AsyncClient, read_token: str):
    forged = read_token[:16] + "X" * (len(read_token) - 16)
    _problem(await client.get(BASE, headers={KEY_HEADER: forged}), 401, "invalid_token")
    _problem(await client.get(BASE, headers={KEY_HEADER: "garbage"}), 401, "invalid_token")
    unknown = TOKEN_PREFIX + "Z" * 40
    _problem(await client.get(BASE, headers={KEY_HEADER: unknown}), 401, "invalid_token")
    _problem(await client.get(BASE, headers={KEY_HEADER: read_token}), 403, "insufficient_scope")


async def test_operate_token_is_not_admin(client: httpx.AsyncClient, operate_token: str):
    _problem(await client.get(BASE, headers={KEY_HEADER: operate_token}), 403, "insufficient_scope")


async def test_error_messages_never_echo_the_token(client: httpx.AsyncClient, read_token: str):
    forged = read_token[:16] + "Q" * (len(read_token) - 16)
    for value in (forged, read_token):
        r = await client.get(BASE, headers={KEY_HEADER: value})
        assert value not in r.text
        assert value[16:] not in r.text


async def test_expired_and_disabled_token_401(client: httpx.AsyncClient, engine: AsyncEngine):
    expired = await issue_token(engine, "admin")
    disabled = await issue_token(engine, "admin")
    async with make_session_factory(engine)() as session:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.prefix == expired[:16])
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.execute(
            update(ApiKey).where(ApiKey.prefix == disabled[:16]).values(enabled=False)
        )
        await session.commit()
    _problem(await client.get(BASE, headers={KEY_HEADER: expired}), 401, "token_expired")
    _problem(await client.get(BASE, headers={KEY_HEADER: disabled}), 401, "token_disabled")


async def test_token_scope_capped_by_owner_role(client: httpx.AsyncClient, engine: AsyncEngine):
    async with make_session_factory(engine)() as session:
        reader = User(display_name="reader", role="read")
        session.add(reader)
        await session.flush()
        _, plaintext = await api_keys_repo.create(
            session, owner_user_id=reader.id, name="too strong", scope="admin"
        )
        await session.commit()
    _problem(await client.get(BASE, headers={KEY_HEADER: plaintext}), 403, "insufficient_scope")


async def test_token_of_disabled_owner_401(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_token: str
):
    async with make_session_factory(engine)() as session:
        await session.execute(update(User).values(enabled=False))
        await session.commit()
    _problem(await client.get(BASE, headers={KEY_HEADER: admin_token}), 401, "owner_disabled")


async def test_last_used_at_updated(
    admin_client: httpx.AsyncClient, engine: AsyncEngine, admin_token: str
):
    assert (await _key_row(engine, admin_token)).last_used_at is None
    before = datetime.now(UTC)
    assert (await admin_client.get(BASE)).status_code == 200
    used = (await _key_row(engine, admin_token)).last_used_at
    assert used is not None
    assert used >= before - timedelta(seconds=1)


async def test_rate_limit_429_with_retry_after(client: httpx.AsyncClient, engine: AsyncEngine):
    plaintext = await issue_token(engine, "admin", rate_limit_per_minute=2)
    headers = {KEY_HEADER: plaintext}
    assert (await client.get(BASE, headers=headers)).status_code == 200
    assert (await client.get(BASE, headers=headers)).status_code == 200
    r = await client.get(BASE, headers=headers)
    _problem(r, 429, "rate_limited")
    retry_after = int(r.headers["Retry-After"])
    assert 1 <= retry_after <= 60


async def test_rate_limit_is_per_token(client: httpx.AsyncClient, engine: AsyncEngine):
    first = await issue_token(engine, "admin", rate_limit_per_minute=1)
    second = await issue_token(engine, "admin", rate_limit_per_minute=1)
    assert (await client.get(BASE, headers={KEY_HEADER: first})).status_code == 200
    _problem(await client.get(BASE, headers={KEY_HEADER: first}), 429, "rate_limited")
    assert (await client.get(BASE, headers={KEY_HEADER: second})).status_code == 200


async def test_database_error_during_auth_is_503(
    client: httpx.AsyncClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
):
    async def broken(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(api_keys_repo, "get_by_prefix", broken)
    r = await client.get(BASE, headers={KEY_HEADER: admin_token})
    _problem(r, 503, "database_unavailable")
    assert "SELECT" not in r.text


# --- create / list / patch / delete ----------------------------------------------------------


async def test_token_plaintext_only_in_create_response(admin_client: httpx.AsyncClient):
    r = await admin_client.post(BASE, json={"name": "ci", "scope": "operate", "note": "pipeline"})
    assert r.status_code == 201, r.text
    created = r.json()
    plaintext = created["token"]
    assert plaintext.startswith(TOKEN_PREFIX)
    assert len(plaintext) == len(TOKEN_PREFIX) + 40
    assert created["prefix"] == plaintext[:16]
    assert created["scope"] == "operate"
    assert "hash" not in created

    listed = await admin_client.get(BASE)
    assert listed.status_code == 200
    assert plaintext not in listed.text
    assert plaintext[16:] not in listed.text
    assert "$2b$" not in listed.text
    entries = {e["id"]: e for e in listed.json()}
    entry = entries[created["id"]]
    assert entry["prefix"] == plaintext[:16]
    assert entry["name"] == "ci"
    assert entry["note"] == "pipeline"
    assert entry["enabled"] is True
    assert entry["rate_limit_per_minute"] == 60
    assert "token" not in entry
    assert "hash" not in entry

    # The new token works with its scope.
    assert (
        await admin_client.get(BASE, headers={KEY_HEADER: plaintext})
    ).status_code == 403  # operate is not admin


async def test_created_token_is_owned_by_the_caller(
    admin_client: httpx.AsyncClient, engine: AsyncEngine, admin_token: str
):
    r = await admin_client.post(BASE, json={"name": "child", "scope": "read"})
    assert r.status_code == 201
    caller = await _key_row(engine, admin_token)
    created = await _key_row(engine, r.json()["token"])
    assert created.owner_user_id == caller.owner_user_id


async def test_hash_is_bcrypt_in_database(admin_client: httpx.AsyncClient, engine: AsyncEngine):
    r = await admin_client.post(BASE, json={"name": "x", "scope": "read"})
    row = await _key_row(engine, r.json()["token"])
    assert row.hash.startswith("$2b$12$")
    assert r.json()["token"] not in row.hash
    assert r.json()["token"] not in repr(row)


async def test_create_rejects_past_expiry_and_bad_input(admin_client: httpx.AsyncClient):
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    _problem(
        await admin_client.post(BASE, json={"name": "x", "scope": "read", "expires_at": past}),
        422,
        "invalid_expiry",
    )
    assert (await admin_client.post(BASE, json={"name": "x", "scope": "root"})).status_code == 422
    assert (await admin_client.post(BASE, json={"name": "", "scope": "read"})).status_code == 422
    assert (
        await admin_client.post(BASE, json={"name": "x", "scope": "read", "hash": "h"})
    ).status_code == 422


async def test_create_with_expiry_and_rate_limit(admin_client: httpx.AsyncClient):
    future = datetime.now(UTC) + timedelta(days=1)
    r = await admin_client.post(
        BASE,
        json={
            "name": "short",
            "scope": "read",
            "expires_at": future.isoformat(),
            "rate_limit_per_minute": 5,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["rate_limit_per_minute"] == 5
    assert datetime.fromisoformat(body["expires_at"]) == future


async def test_create_database_error_is_503_and_nothing_stored(
    admin_client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    async def broken(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("INSERT", {}, Exception("connection lost"))

    monkeypatch.setattr(api_keys_repo, "create", broken)
    _problem(
        await admin_client.post(BASE, json={"name": "x", "scope": "read"}),
        503,
        "database_unavailable",
    )
    async with make_session_factory(engine)() as session:
        names = (await session.scalars(select(ApiKey.name))).all()
    assert "x" not in names


async def test_patch_updates_fields(admin_client: httpx.AsyncClient, engine: AsyncEngine):
    created = (await admin_client.post(BASE, json={"name": "a", "scope": "read"})).json()
    future = datetime.now(UTC) + timedelta(days=2)
    r = await admin_client.patch(
        f"{BASE}/{created['id']}",
        json={"name": "b", "note": "renamed", "enabled": False, "expires_at": future.isoformat()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["name"], body["note"], body["enabled"]) == ("b", "renamed", False)
    assert datetime.fromisoformat(body["expires_at"]) == future
    assert "token" not in body
    # The disabled token is rejected.
    _problem(
        await admin_client.get(BASE, headers={KEY_HEADER: created["token"]}), 401, "token_disabled"
    )

    # Explicit null clears expiry and note; omitted fields stay.
    r = await admin_client.patch(f"{BASE}/{created['id']}", json={"expires_at": None, "note": None})
    assert r.status_code == 200
    assert r.json()["expires_at"] is None
    assert r.json()["note"] is None
    assert r.json()["name"] == "b"
    row = await _key_row(engine, created["token"])
    assert row.expires_at is None


async def test_patch_rejects_bad_input(admin_client: httpx.AsyncClient):
    created = (await admin_client.post(BASE, json={"name": "a", "scope": "read"})).json()
    url = f"{BASE}/{created['id']}"
    assert (await admin_client.patch(url, json={"scope": "admin"})).status_code == 422
    assert (await admin_client.patch(url, json={"name": None})).status_code == 422
    assert (await admin_client.patch(url, json={"enabled": None})).status_code == 422
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    _problem(await admin_client.patch(url, json={"expires_at": past}), 422, "invalid_expiry")


async def test_patch_and_delete_unknown_id_404(admin_client: httpx.AsyncClient):
    missing = uuid.uuid4()
    _problem(await admin_client.patch(f"{BASE}/{missing}", json={"name": "x"}), 404, "not_found")
    _problem(await admin_client.delete(f"{BASE}/{missing}"), 404, "not_found")


async def test_patch_database_error_is_503(
    admin_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    created = (await admin_client.post(BASE, json={"name": "a", "scope": "read"})).json()

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("UPDATE", {}, Exception("connection lost"))

    monkeypatch.setattr(api_keys_repo, "get", broken)
    _problem(
        await admin_client.patch(f"{BASE}/{created['id']}", json={"name": "z"}),
        503,
        "database_unavailable",
    )


async def test_delete_removes_token(admin_client: httpx.AsyncClient, engine: AsyncEngine):
    created = (await admin_client.post(BASE, json={"name": "gone", "scope": "read"})).json()
    r = await admin_client.delete(f"{BASE}/{created['id']}")
    assert r.status_code == 204
    assert r.content == b""
    ids = [e["id"] for e in (await admin_client.get(BASE)).json()]
    assert created["id"] not in ids
    _problem(
        await admin_client.get(BASE, headers={KEY_HEADER: created["token"]}), 401, "invalid_token"
    )


async def test_delete_database_error_is_503(
    admin_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    created = (await admin_client.post(BASE, json={"name": "a", "scope": "read"})).json()

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("DELETE", {}, Exception("connection lost"))

    monkeypatch.setattr(api_keys_repo, "delete", broken)
    _problem(await admin_client.delete(f"{BASE}/{created['id']}"), 503, "database_unavailable")


async def test_read_and_operate_cannot_manage_tokens(
    client: httpx.AsyncClient, read_token: str, operate_token: str
):
    for token in (read_token, operate_token):
        h = {KEY_HEADER: token}
        _problem(
            await client.post(BASE, json={"name": "x", "scope": "read"}, headers=h),
            403,
            "insufficient_scope",
        )
        _problem(
            await client.patch(f"{BASE}/{uuid.uuid4()}", json={}, headers=h),
            403,
            "insufficient_scope",
        )
        _problem(
            await client.delete(f"{BASE}/{uuid.uuid4()}", headers=h), 403, "insufficient_scope"
        )


async def test_prefix_collision_is_retried(
    admin_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
):
    first = (await admin_client.post(BASE, json={"name": "one", "scope": "read"})).json()
    fixed = first["token"]
    fresh = iter([(fixed, fixed[:16]), (TOKEN_PREFIX + "N" * 40, (TOKEN_PREFIX + "N" * 40)[:16])])
    monkeypatch.setattr(api_keys_repo, "generate_token", lambda: next(fresh))
    r = await admin_client.post(BASE, json={"name": "two", "scope": "read"})
    assert r.status_code == 201, r.text
    assert r.json()["prefix"] == (TOKEN_PREFIX + "N" * 40)[:16]


# --- failed verifications, timing, last_used_at throttling -----------------------------------


async def test_failed_verifications_limited_per_key_without_touching_real_budget(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    import app.auth.dependencies as deps

    monkeypatch.setattr(deps, "FAILED_VERIFICATIONS_PER_MINUTE", 3)
    real = await issue_token(engine, "admin", rate_limit_per_minute=5)
    wrong = real[:16] + "W" * (len(real) - 16)
    for _ in range(3):
        _problem(await client.get(BASE, headers={KEY_HEADER: wrong}), 401, "invalid_token")
    r = await client.get(BASE, headers={KEY_HEADER: wrong})
    _problem(r, 429, "rate_limited")
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    # The real token keeps its own budget of 5 requests per minute.
    for _ in range(5):
        assert (await client.get(BASE, headers={KEY_HEADER: real})).status_code == 200
    _problem(await client.get(BASE, headers={KEY_HEADER: real}), 429, "rate_limited")


async def test_valid_uncached_token_passes_while_its_prefix_is_over_the_failure_budget(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    # Knowing a prefix must not let anyone lock out its holder: the failure budget only
    # turns failed checks into 429, a correct token is always verified and accepted.
    import app.auth.dependencies as deps
    import app.auth.tokens as tokens

    monkeypatch.setattr(deps, "FAILED_VERIFICATIONS_PER_MINUTE", 2)
    real = await issue_token(engine, "admin")
    wrong = real[:16] + "W" * (len(real) - 16)
    for expected in (401, 401, 429, 429):
        r = await client.get(BASE, headers={KEY_HEADER: wrong})
        assert r.status_code == expected
    tokens.clear_verify_cache()  # e.g. after a restart: the holder's token is not cached
    assert not tokens.is_cached(real, (await _key_row(engine, real)).hash)
    assert (await client.get(BASE, headers={KEY_HEADER: real})).status_code == 200


async def test_unknown_prefix_runs_a_dummy_bcrypt_check(
    client: httpx.AsyncClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
):
    import app.auth.tokens as tokens

    calls: list[bytes] = []
    real_checkpw = tokens.bcrypt.checkpw

    def spy(password: bytes, hashed: bytes) -> bool:
        calls.append(hashed)
        return real_checkpw(password, hashed)

    monkeypatch.setattr(tokens.bcrypt, "checkpw", spy)
    unknown = TOKEN_PREFIX + "U" * 40
    _problem(await client.get(BASE, headers={KEY_HEADER: unknown}), 401, "invalid_token")
    assert len(calls) == 1  # same bcrypt work as for a known prefix with a wrong body
    assert calls[0].startswith(b"$2b$12$")


async def test_last_used_at_written_at_most_once_per_minute(
    admin_client: httpx.AsyncClient,
    engine: AsyncEngine,
    admin_token: str,
    monkeypatch: pytest.MonkeyPatch,
):
    updates: list[bool] = []
    original = api_keys_repo.touch_last_used

    async def recording(*args: object, **kwargs: object) -> bool:
        updated = await original(*args, **kwargs)  # type: ignore[arg-type]
        updates.append(updated)
        return updated

    monkeypatch.setattr(api_keys_repo, "touch_last_used", recording)
    assert (await admin_client.get(BASE)).status_code == 200
    first = (await _key_row(engine, admin_token)).last_used_at
    assert (await admin_client.get(BASE)).status_code == 200
    assert updates == [True, False]
    assert (await _key_row(engine, admin_token)).last_used_at == first


async def test_last_used_at_refreshed_after_a_minute(
    admin_client: httpx.AsyncClient, engine: AsyncEngine, admin_token: str
):
    assert (await admin_client.get(BASE)).status_code == 200
    old = datetime.now(UTC) - timedelta(seconds=61)
    async with make_session_factory(engine)() as session:
        await session.execute(
            update(ApiKey).where(ApiKey.prefix == admin_token[:16]).values(last_used_at=old)
        )
        await session.commit()
    assert (await admin_client.get(BASE)).status_code == 200
    assert (await _key_row(engine, admin_token)).last_used_at > old  # type: ignore[operator]


async def test_failure_limit_does_not_reveal_whether_a_prefix_exists(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    import app.auth.dependencies as deps

    monkeypatch.setattr(deps, "FAILED_VERIFICATIONS_PER_MINUTE", 3)
    real = await issue_token(engine, "admin")
    known_wrong = real[:16] + "W" * (len(real) - 16)
    unknown = TOKEN_PREFIX + "U" * 40

    async def sequence(value: str) -> list[tuple[int, str]]:
        out = []
        for _ in range(5):
            r = await client.get(BASE, headers={KEY_HEADER: value})
            out.append((r.status_code, r.json()["error_code"]))
        return out

    expected = [(401, "invalid_token")] * 3 + [(429, "rate_limited")] * 2
    assert await sequence(known_wrong) == expected
    assert await sequence(unknown) == expected
    # The holder of the attacked prefix is not throttled.
    assert (await client.get(BASE, headers={KEY_HEADER: real})).status_code == 200


async def test_authenticated_request_uses_one_pooled_connection(
    admin_client: httpx.AsyncClient, app: FastAPI
):
    # Authentication shares the request's session: a request never holds two pool
    # connections at once, so concurrent requests cannot exhaust the pool waiting on
    # their own second connection.
    from sqlalchemy import event

    pool = app.state.engine.sync_engine.pool
    current = 0
    peak = 0

    def on_checkout(*_args: object) -> None:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)

    def on_checkin(*_args: object) -> None:
        nonlocal current
        current -= 1

    event.listen(pool, "checkout", on_checkout)
    event.listen(pool, "checkin", on_checkin)
    try:
        for method, url, body in (
            ("GET", BASE, None),
            ("POST", BASE, {"name": "pool", "scope": "read"}),
        ):
            peak = 0
            r = await admin_client.request(method, url, json=body)
            assert r.status_code in (200, 201), r.text
            assert peak == 1, (method, peak)
    finally:
        event.remove(pool, "checkout", on_checkout)
        event.remove(pool, "checkin", on_checkin)


async def test_parallel_failures_cannot_overrun_the_budget(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    # Concurrent wrong attempts: the budget holds when each failure is counted.
    import asyncio

    import app.auth.dependencies as deps

    monkeypatch.setattr(deps, "FAILED_VERIFICATIONS_PER_MINUTE", 1)
    real = await issue_token(engine, "admin")
    wrong = real[:16] + "P" * (len(real) - 16)
    results = await asyncio.gather(
        *(client.get(BASE, headers={KEY_HEADER: wrong}) for _ in range(3))
    )
    assert sorted(r.status_code for r in results) == [401, 429, 429]


# --- per-client failure budget before bcrypt -----------------------------------------------

# A small budget keeps these tests fast: with slow bcrypt, 30 failures could take longer than
# the 60 s window and the budget would drain while the test is still filling it.
BUDGET = 3


@pytest.fixture
def small_client_budget(monkeypatch: pytest.MonkeyPatch) -> int:
    import app.auth.dependencies as dependencies

    monkeypatch.setattr(dependencies, "FAILED_VERIFICATIONS_PER_CLIENT_PER_MINUTE", BUDGET)
    return BUDGET


def _client_at(app: FastAPI, ip: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(ip, 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_client_over_failure_budget_gets_429_without_bcrypt(
    app: FastAPI, admin_token: str, monkeypatch: pytest.MonkeyPatch, small_client_budget: int
):
    import app.auth.tokens as tokens

    async with _client_at(app, "192.0.2.10") as attacker, _client_at(app, "192.0.2.20") as other:
        # Spread over many prefixes, so the per-prefix BUDGET never triggers.
        for i in range(BUDGET):
            guess = TOKEN_PREFIX + f"{i:04d}" + "G" * 36
            r = await attacker.get(BASE, headers={KEY_HEADER: guess})
            assert r.status_code == 401, (i, r.text)
        calls: list[bytes] = []
        real_checkpw = tokens.bcrypt.checkpw

        def spy(password: bytes, hashed: bytes) -> bool:
            calls.append(hashed)
            return real_checkpw(password, hashed)

        monkeypatch.setattr(tokens.bcrypt, "checkpw", spy)
        tokens.clear_verify_cache()
        for presented in (TOKEN_PREFIX + "N" * 40, admin_token[:16] + "W" * 31, admin_token):
            r = await attacker.get(BASE, headers={KEY_HEADER: presented})
            _problem(r, 429, "rate_limited")
            assert int(r.headers["Retry-After"]) >= 1
        assert calls == []  # rejected before any bcrypt work
        # Another client with the valid token is not affected.
        assert (await other.get(BASE, headers={KEY_HEADER: admin_token})).status_code == 200
        assert len(calls) == 1


async def test_correct_token_from_client_under_budget_is_verified(app: FastAPI, admin_token: str):

    async with _client_at(app, "192.0.2.30") as c:
        for i in range(BUDGET - 1):
            guess = TOKEN_PREFIX + f"{i:04d}" + "H" * 36
            assert (await c.get(BASE, headers={KEY_HEADER: guess})).status_code == 401
        assert (await c.get(BASE, headers={KEY_HEADER: admin_token})).status_code == 200


async def test_client_budget_same_answers_for_known_and_unknown_prefixes(
    app: FastAPI, admin_token: str, small_client_budget: int
):

    sequences = []
    for ip, prefix in (("192.0.2.41", admin_token[:16]), ("192.0.2.42", TOKEN_PREFIX + "Z" * 9)):
        statuses = []
        async with _client_at(app, ip) as c:
            for i in range(BUDGET + 2):
                guess = prefix + f"{i:04d}" + "Q" * (40 - 9 - 4)
                statuses.append((await c.get(BASE, headers={KEY_HEADER: guess})).status_code)
        sequences.append(statuses)
    assert sequences[0] == sequences[1]
    assert sequences[0][-1] == 429


async def test_unknown_client_never_gets_the_pre_check_429(
    app: FastAPI, admin_token: str, small_client_budget: int
):
    # A client address that cannot be determined shares no bucket with anyone: one guesser
    # without a usable address must not lock out every other such client.
    async with _client_at(app, "not-an-ip") as guesser, _client_at(app, "") as other:
        for i in range(BUDGET + 3):
            guess = TOKEN_PREFIX + f"{i:04d}" + "U" * 36
            r = await guesser.get(BASE, headers={KEY_HEADER: guess})
            _problem(r, 401, "invalid_token")
        assert (await other.get(BASE, headers={KEY_HEADER: admin_token})).status_code == 200
        assert (await guesser.get(BASE, headers={KEY_HEADER: admin_token})).status_code == 200
    # The per-prefix budget still applies to unknown clients.
    async with _client_at(app, "not-an-ip") as guesser:
        prefix = TOKEN_PREFIX + "Y" * 9
        statuses = [
            (
                await guesser.get(BASE, headers={KEY_HEADER: prefix + f"{i:04d}" + "Y" * 27})
            ).status_code
            for i in range(11)
        ]
    assert statuses[-1] == 429


async def test_cached_valid_token_passes_while_its_client_is_over_budget(
    app: FastAPI, admin_token: str, monkeypatch: pytest.MonkeyPatch, small_client_budget: int
):
    import app.auth.tokens as tokens

    async with _client_at(app, "192.0.2.50") as c:
        tokens.clear_verify_cache()
        assert (await c.get(BASE, headers={KEY_HEADER: admin_token})).status_code == 200
        for i in range(BUDGET):
            guess = TOKEN_PREFIX + f"{i:04d}" + "C" * 36
            assert (await c.get(BASE, headers={KEY_HEADER: guess})).status_code == 401
        calls: list[bytes] = []
        real_checkpw = tokens.bcrypt.checkpw

        def spy(password: bytes, hashed: bytes) -> bool:
            calls.append(hashed)
            return real_checkpw(password, hashed)

        monkeypatch.setattr(tokens.bcrypt, "checkpw", spy)
        # The token verified a moment ago is still let through, without bcrypt work ...
        assert (await c.get(BASE, headers={KEY_HEADER: admin_token})).status_code == 200
        # ... while anything else from this client still gets 429 before bcrypt.
        _problem(
            await c.get(BASE, headers={KEY_HEADER: admin_token[:16] + "W" * 31}),
            429,
            "rate_limited",
        )
        _problem(
            await c.get(BASE, headers={KEY_HEADER: TOKEN_PREFIX + "V" * 40}), 429, "rate_limited"
        )
        _problem(await c.get(BASE, headers={KEY_HEADER: "garbage"}), 429, "rate_limited")
        assert calls == []


@pytest.mark.parametrize(
    ("first", "second", "shared"),
    [
        ("2001:db8:1:2::10", "2001:db8:1:2:ffff:1:2:3", True),
        ("2001:db8:1:2::10", "2001:db8:1:3::10", False),
        ("::ffff:192.0.2.60", "192.0.2.60", True),
        ("192.0.2.61", "192.0.2.62", False),
    ],
)
async def test_ipv6_clients_share_a_budget_per_64(
    app: FastAPI, admin_token: str, small_client_budget: int, first: str, second: str, shared: bool
):
    async with _client_at(app, first) as a, _client_at(app, second) as b:
        for i in range(BUDGET):
            guess = TOKEN_PREFIX + f"{i:04d}" + "S" * 36
            assert (await a.get(BASE, headers={KEY_HEADER: guess})).status_code == 401
        r = await b.get(BASE, headers={KEY_HEADER: TOKEN_PREFIX + "T" * 40})
        if shared:
            _problem(r, 429, "rate_limited")
        else:
            _problem(r, 401, "invalid_token")
