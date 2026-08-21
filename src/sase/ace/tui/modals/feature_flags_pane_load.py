"""Thread-worker payload for the Config Flags pane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import sase
from sase.core import time as core_time
from sase.feature_flags.cli_views import FlagView, flag_views
from sase.feature_flags.models import FeatureFlagDiagnostic
from sase.feature_flags.snapshot import current_flags
from sase.feature_flags.state import feature_flag_state_path


@dataclass(frozen=True)
class FeatureFlagsPaneLoad:
    """One Flags-pane snapshot assembled off the Textual event loop."""

    views: tuple[FlagView, ...]
    state_path: str
    diagnostics: tuple[FeatureFlagDiagnostic, ...]
    today: date
    release: str
    error: str | None = None


def load_feature_flags_pane_state() -> FeatureFlagsPaneLoad:
    """Join registry views, saved-state details, and bead metadata.

    Intended to run in a thread worker. Must not be called from compose,
    render, key, message, timer, or serial ``call_after_refresh`` paths.
    """
    today = core_time.local_now().date()
    release = sase.__version__
    try:
        snapshot = current_flags()
        views = flag_views(
            definitions=None,
            snapshot=snapshot,
            beads=None,
            today=today,
            release=release,
        )
        return FeatureFlagsPaneLoad(
            views=views,
            state_path=snapshot.state_path or feature_flag_state_path(),
            diagnostics=snapshot.diagnostics,
            today=today,
            release=release,
        )
    except Exception as exc:
        return FeatureFlagsPaneLoad(
            views=(),
            state_path=feature_flag_state_path(),
            diagnostics=(),
            today=today,
            release=release,
            error=str(exc) or type(exc).__name__,
        )


__all__ = [
    "FeatureFlagsPaneLoad",
    "load_feature_flags_pane_state",
]
