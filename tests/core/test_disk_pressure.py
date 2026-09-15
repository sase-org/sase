"""Tests for disk-pressure filesystem observation helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.core.disk_pressure import collect_filesystem_observations


def test_collect_filesystem_observations_deduplicates_before_sampling(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    sampled: list[str] = []

    def disk_usage(path: str) -> SimpleNamespace:
        sampled.append(path)
        return SimpleNamespace(total=100, used=60, free=40)

    observations = collect_filesystem_observations(
        (
            {"label": "left", "role": "owner", "path": str(left)},
            {"label": "right", "role": "owner", "path": str(right)},
        ),
        disk_usage_fn=disk_usage,
        filesystem_identity_fn=lambda _path: "same-fs",
    )

    assert len(observations) == 1
    assert observations[0]["label"] == "left"
    assert sampled == [str(left)]
