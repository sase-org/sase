"""Foreground per-machine service host runtime.

The host's behavior lives in focused sibling modules; this module only
composes them. ``_ServiceHost`` combines one mixin per responsibility:

- :mod:`sase.service.host_state` — runtime records and the reconcile tick.
- :mod:`sase.service.host_exits` — exit settlement and crash notifications.
- :mod:`sase.service.host_reconcile` — desired-state convergence and requests.
- :mod:`sase.service.host_spawn` — child launch and shutdown.
"""

from __future__ import annotations

import sys

from sase.service.host_exits import ServiceHostExitsMixin
from sase.service.host_reconcile import ServiceHostReconcileMixin
from sase.service.host_spawn import ServiceHostSpawnMixin
from sase.service.host_state import ServiceHostStateMixin
from sase.service.platform_models import SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE
from sase.service.platform_runner import service_lifecycle_blocked_in_tests


class _ServiceHost(
    ServiceHostStateMixin,
    ServiceHostExitsMixin,
    ServiceHostReconcileMixin,
    ServiceHostSpawnMixin,
):
    """Reconcile configured daemon service procs as direct children."""


def run_service_host() -> int:
    """Entry point used by ``sase service run``."""
    if service_lifecycle_blocked_in_tests():
        print(SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE, file=sys.stderr)
        return 125
    return _ServiceHost().run()


__all__ = ["_ServiceHost", "run_service_host"]
