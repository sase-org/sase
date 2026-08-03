from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent_clis import history


@pytest.fixture(autouse=True)
def redirect_agent_cli_update_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep execution tests from writing update history to the user's home."""
    monkeypatch.setattr(
        history,
        "AGENT_CLI_UPDATE_JOURNAL",
        str(tmp_path / "agent_cli_updates.jsonl"),
    )
