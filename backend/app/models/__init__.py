"""ORM models.

Every model module is imported here so that ``Base.metadata`` is complete when
Alembic compares it with the database (``app/migrations/env.py`` imports this package).
"""

from app.models.app_setting import AppSetting

__all__ = ["AppSetting"]
