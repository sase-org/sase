"""Public notification API for automatic agent restart handling.

The implementation is split across private modules while this module keeps
its established import path for callers and tests.
"""

from __future__ import annotations

from sase.agent.auto_restart._notifications import (
    publish_escalation,
    publish_relaunch,
    refresh_episode_rows,
    resurface_failure,
)
from sase.agent.auto_restart._notify_report import (
    COLOR,
    EPISODES_DIRNAME,
    ICON,
    REPORT_SUFFIX,
    SENDER,
    refresh_episode_report,
)

__all__ = [
    "COLOR",
    "EPISODES_DIRNAME",
    "ICON",
    "REPORT_SUFFIX",
    "SENDER",
    "publish_escalation",
    "publish_relaunch",
    "refresh_episode_report",
    "refresh_episode_rows",
    "resurface_failure",
]
