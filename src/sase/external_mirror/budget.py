"""Shared per-pass work-budget derivation for external mirror chops.

Both mirror chops previously hand-copied their internal work-budget seconds
from the ``timeout: "2m"`` each carried in ``default_config.yml``'s
``checks`` lane. Deriving both from this one constant means a future change
to the ``external_mirror`` lane's configured timeout cannot leave either
budget stale.
"""

from __future__ import annotations

#: Matches the ``external_mirror`` lumberjack's ``chop_timeout: "5m"`` in
#: ``default_config.yml``.
LANE_CHOP_TIMEOUT_SECONDS = 300.0

__all__ = ["LANE_CHOP_TIMEOUT_SECONDS"]
