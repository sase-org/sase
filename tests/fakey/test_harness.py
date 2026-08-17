from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from tests.fakey.harness import FakeyRetryHarness


def test_normalize_visual_timestamps_refreshes_artifact_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        expose_to_agent_loader=True,
        is_home_mode=True,
    )
    harness.seed_running_agent(started_at=datetime(2026, 7, 6, 11, 58, 0))
    calls: list[Path] = []

    def _capture(artifact_dir: Path | str | None, **_kwargs: object) -> bool:
        assert artifact_dir is not None
        calls.append(Path(artifact_dir))
        return True

    monkeypatch.setattr(
        "tests.fakey.harness.update_agent_artifact_index_for_marker_mutation",
        _capture,
    )

    harness.normalize_visual_timestamps(
        datetime(2026, 7, 6, 12, 0, 0),
        countdown_seconds=9,
    )

    assert calls == [harness.artifacts]
