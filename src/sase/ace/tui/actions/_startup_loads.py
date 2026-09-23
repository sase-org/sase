"""Post-mount startup background-load helpers.

``StartupLoadsMixin`` is the public mixin imported by ``startup.py``. Its
implementation is split across focused private mixins so this module stays
as a small composition point.
"""

from __future__ import annotations

import time as time  # Re-export: tests patch ``startup_loads.time``.

from ._startup_loads_core import StartupLoadsCoreMixin
from ._startup_loads_index import StartupLoadsIndexMixin
from ._startup_loads_maintenance import StartupLoadsMaintenanceMixin
from ._startup_loads_tags import StartupLoadsTagsMixin


class StartupLoadsMixin(
    StartupLoadsCoreMixin,
    StartupLoadsTagsMixin,
    StartupLoadsMaintenanceMixin,
    StartupLoadsIndexMixin,
):
    """Mixin for startup data loading and deferred index maintenance."""
