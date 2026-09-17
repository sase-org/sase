from __future__ import annotations

import json
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


def test_normalize_visual_timestamps_canonicalizes_artifact_file_source_paths(
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
    monkeypatch.setattr(
        "tests.fakey.harness.update_agent_artifact_index_for_marker_mutation",
        lambda *_args, **_kwargs: True,
    )
    index_path = harness.home / "artifacts" / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact": {
                    "agent_artifacts_dir": str(harness.artifacts),
                    "path": str(harness.home / "artifacts/stored.json"),
                    "source_path": str(
                        harness.artifacts / "continuation/records/delta.json"
                    ),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    harness.normalize_visual_timestamps(datetime(2026, 7, 6, 12, 0, 0))

    row = json.loads(index_path.read_text(encoding="utf-8"))
    artifact = row["artifact"]
    assert artifact["agent_artifacts_dir"] == str(harness.artifacts)
    assert artifact["path"] == str(harness.home / "artifacts/stored.json")
    assert artifact["workspace_dir"] == str(tmp_path)
    assert artifact["source_path"] == (
        "/var/tmp/sase-visual/sase-home/projects/home/artifacts/ace-run/"
        "20260710120000/continuation/records/delta.json"
    )
