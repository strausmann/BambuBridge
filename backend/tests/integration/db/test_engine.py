from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.base import Base
from app.db.session import make_session_factory
from tests.db_support import truncate_all


async def test_engine_does_not_inherit_serializable(engine: AsyncEngine):
    # Guards against copying the reference project's SERIALIZABLE default.
    async with engine.connect() as c:
        assert (await c.scalar(text("show transaction_isolation"))) == "read committed"


async def test_server_is_postgres_18(engine: AsyncEngine):
    async with engine.connect() as c:
        assert (await c.scalar(text("show server_version_num"))).startswith("18")


async def test_pgcrypto_provides_uuid_generation(engine: AsyncEngine):
    async with engine.connect() as c:
        assert (
            await c.scalar(text("select count(*) from pg_extension where extname='pgcrypto'"))
        ) == 1
        assert (await c.scalar(text("select gen_random_uuid()"))) is not None


async def test_session_factory_keeps_attributes_after_commit(engine: AsyncEngine):
    async with make_session_factory(engine)() as session:
        assert (await session.scalar(text("select 1"))) == 1
        assert session.sync_session.expire_on_commit is False


async def test_db_session_fixture_is_usable(db_session: AsyncSession):
    assert (await db_session.scalar(text("select 2"))) == 2


async def test_truncate_all_empties_tables_and_restarts_identity(engine: AsyncEngine):
    async with engine.begin() as c:
        await c.execute(text("create table t5_probe (id serial primary key, v text)"))
    try:
        async with engine.begin() as c:
            await c.execute(text("insert into t5_probe (v) values ('a'), ('b')"))
        await truncate_all(engine)
        async with engine.begin() as c:
            assert (await c.scalar(text("select count(*) from t5_probe"))) == 0
            await c.execute(text("insert into t5_probe (v) values ('c')"))
            assert (await c.scalar(text("select id from t5_probe"))) == 1
    finally:
        async with engine.begin() as c:
            await c.execute(text("drop table t5_probe"))


async def test_truncate_all_keeps_alembic_version(engine: AsyncEngine):
    await truncate_all(engine)
    async with engine.connect() as c:
        assert (await c.scalar(text("select version_num from alembic_version"))) is not None


def test_base_naming_convention_patterns():
    convention = Base.metadata.naming_convention
    assert convention == {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
