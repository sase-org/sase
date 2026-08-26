"""Feature-flag gate for the link-traversing pager surface."""

from __future__ import annotations

from sase.feature_flags.registry import FeatureFlag
from sase.feature_flags.snapshot import current_flags


def link_pager_enabled() -> bool:
    """Return the process-local `link_pager` flag decision."""
    return current_flags().enabled(FeatureFlag.link_pager)
