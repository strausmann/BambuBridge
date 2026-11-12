"""Alembic migrations, shipped inside the ``app`` package.

The scripts live here (not next to ``alembic.ini``) so that an installed wheel is
self-contained: the container entrypoint can migrate without the source tree.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

SCRIPT_LOCATION = Path(__file__).resolve().parent
# Keep in sync with ``file_template`` in backend/alembic.ini (developer CLI).
FILE_TEMPLATE = "%%(year)d_%%(month).2d_%%(day).2d_%%(rev)s_%%(slug)s"


def make_alembic_config(url: str | None = None) -> Config:
    """Build the Alembic config in code, without any file from the source tree.

    Without ``url``, ``env.py`` reads ``BAMBUBRIDGE_DATABASE_URL``.
    """
    config = Config()
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    config.set_main_option("file_template", FILE_TEMPLATE)
    config.attributes["configure_logger"] = False
    if url is not None:
        # ConfigParser interpolation: a literal percent sign must be doubled.
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config
