"""Feature-flag helper for the ⊛ FINAL deck beta (epic sase-1b2)."""

from __future__ import annotations


def final_deck_enabled() -> bool:
    """Return True while the ``ace_final_deck`` beta flag is on."""
    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.ace_final_deck)


__all__ = ["final_deck_enabled"]
