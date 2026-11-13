"""ORM models.

Every model module is imported here so that ``Base.metadata`` is complete when
Alembic compares it with the database (``app/migrations/env.py`` imports this package).
"""

from app.models.api_key import ApiKey
from app.models.app_setting import AppSetting
from app.models.communication_entry import CommunicationEntry
from app.models.event import Event
from app.models.event_delivery import EventDelivery
from app.models.provider_instance import ProviderInstance
from app.models.ui_session import UiSession
from app.models.user import User
from app.models.user_identity import UserIdentity

__all__ = [
    "ApiKey",
    "AppSetting",
    "CommunicationEntry",
    "Event",
    "EventDelivery",
    "ProviderInstance",
    "UiSession",
    "User",
    "UserIdentity",
]
