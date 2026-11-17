from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Viewer tests must not inherit the agent's tmux session topology."""

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
