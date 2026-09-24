"""``ace_command_line`` beta flag access for the Command Line panel."""

from __future__ import annotations

from sase.feature_flags import FeatureFlag, current_flags


def command_line_enabled() -> bool:
    """Return whether the Command Line panel beta flag is on."""
    return bool(current_flags().enabled(FeatureFlag.ace_command_line))
