"""Bead claim marker-file tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.claims import (
    BEAD_CLAIM_MARKER,
    clear_bead_claim_marker,
    read_bead_claim_marker,
    write_bead_claim_marker,
)


def test_bead_claim_marker_helpers_round_trip(tmp_path: Path) -> None:
    assert write_bead_claim_marker(
        tmp_path,
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )

    marker = read_bead_claim_marker(tmp_path)

    assert marker is not None
    assert marker.project_name == "sase"
    assert marker.bead_id == "sase-1.2"
    assert marker.agent_name == "sase-1.2"
    assert clear_bead_claim_marker(tmp_path)
    assert read_bead_claim_marker(tmp_path) is None


def test_bead_claim_marker_failures_warn_without_raising(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact_file = tmp_path / "not-a-directory"
    artifact_file.write_text("", encoding="utf-8")

    assert not write_bead_claim_marker(
        artifact_file,
        project_name="sase",
        bead_id="sase-1.2",
        agent_name="sase-1.2",
    )

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / BEAD_CLAIM_MARKER).write_text("{", encoding="utf-8")

    assert read_bead_claim_marker(corrupt_dir) is None

    stderr = capsys.readouterr().err
    assert "Warning: Failed to write bead claim marker" in stderr
    assert "Warning: Failed to read bead claim marker" in stderr
