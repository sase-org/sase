"""Error digest notification chop."""

from datetime import datetime, timedelta

from sase.axe.chop_registry import ChopContext, register_chop
from sase.axe.state import read_errors
from sase.notifications.senders import notify_axe_error_digest
from sase.sase_utils import EASTERN_TZ


@register_chop("error_digest")
def run_error_digest(ctx: ChopContext) -> None:
    """Send a notification if there were axe errors in the last hour."""
    errors = read_errors()
    cutoff = (datetime.now(EASTERN_TZ) - timedelta(hours=1)).isoformat()
    recent = [e for e in errors if e.get("timestamp", "") >= cutoff]
    if recent:
        notify_axe_error_digest(recent)
