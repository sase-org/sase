"""Card blocks beta flag access for deck widgets."""

from __future__ import annotations

from sase.feature_flags import FeatureFlag, current_flags


def card_blocks_enabled() -> bool:
    """Return whether the card blocks beta flag is on."""
    return bool(current_flags().enabled(FeatureFlag.card_blocks))


__all__ = ["card_blocks_enabled"]
