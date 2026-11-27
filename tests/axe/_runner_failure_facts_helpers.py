"""Shared fixtures for runner failure facts tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.axe import runner_lifecycle_phase as lifecycle_mod


@pytest.fixture(autouse=True)
def clean_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle_mod, "_current_phase", None)
    # Lifecycle breadcrumb writes resolve the index updater lazily, so this
    # keeps breadcrumb tests off the real artifact index.
    patcher = patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation",
        MagicMock(),
    )
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()
        monkeypatch.setattr(lifecycle_mod, "_current_phase", None)
