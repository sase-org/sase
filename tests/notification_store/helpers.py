import uuid
from datetime import datetime

from sase.core.time import get_timezone
from sase.notifications.models import Notification


def make_notification(
    *,
    id: str | None = None,
    sender: str = "test-sender",
    notes: list[str] | None = None,
    files: list[str] | None = None,
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
) -> Notification:
    """Factory for creating test notifications with sensible defaults."""
    return Notification(
        id=id or str(uuid.uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        notes=notes or [],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        silent=silent,
    )
