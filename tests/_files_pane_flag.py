"""Test helper for exercising the opt-in Artifacts Files pane."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sase.feature_flags import override_flags


@contextmanager
def files_pane_enabled_context() -> Iterator[None]:
    """Temporarily enable Files and clear the descriptor cache around it."""

    from sase.ace.tui import artifact_tabs

    artifact_tabs.reset_artifacts_subtabs_cache()
    try:
        with override_flags(artifacts_files_pane=True):
            yield
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()
