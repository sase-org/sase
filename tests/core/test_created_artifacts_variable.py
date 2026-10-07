"""Tests for the SASE-managed ``artifacts`` output variable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from sase.artifact_cli.create import handle_create
from sase.core.artifact_file_types import ArtifactFile
from sase.core.created_artifacts_variable import (
    CREATED_ARTIFACTS_OUTPUT_VARIABLE,
    CreatedArtifactEntryTooLargeError,
    CreatedArtifactsShapeError,
    _created_artifact_entry,
    _merge_created_artifact_entry,
    record_created_artifact,
)


def _artifact(
    *,
    id: str = "explicit:abc123",
    label: str = "report.md",
    kind: str = "markdown",  # type: ignore[arg-type]
    path: str | None = "/home/user/.sase/artifacts/report-abc.md",
    source_path: str | None = "/work/report.md",
) -> ArtifactFile:
    return ArtifactFile(
        id=id, label=label, kind=kind, path=path, source_path=source_path
    )


def test_entry_includes_retained_source_and_bead() -> None:
    entry = _created_artifact_entry(_artifact(), source_retained=True, bead_id="sase-1")

    assert entry["ref"] == "file:explicit:abc123"
    assert entry["label"] == "report.md"
    assert entry["kind"] == "markdown"
    assert entry["source_path"] == "/work/report.md"
    assert entry["bead"] == "sase-1"


def test_entry_omits_source_path_when_moved() -> None:
    entry = _created_artifact_entry(_artifact(), source_retained=False, bead_id=None)

    assert "source_path" not in entry
    assert "bead" not in entry


def test_merge_appends_and_replaces_same_ref_in_place() -> None:
    first = _created_artifact_entry(_artifact(), source_retained=True, bead_id=None)
    merge = _merge_created_artifact_entry(None, first)

    assert merge.value == [first]
    assert merge.index == 0

    second = dict(first) | {"path": "/home/user/.sase/artifacts/report-def.md"}
    remerge = _merge_created_artifact_entry(merge.value, second)

    assert len(remerge.value) == 1
    assert remerge.value[0]["path"] == second["path"]
    assert remerge.index == 0


def test_merge_replaces_same_label_and_source_with_new_ref() -> None:
    old = _created_artifact_entry(_artifact(), source_retained=True, bead_id=None)
    merge = _merge_created_artifact_entry(None, old)
    new = dict(old) | {"ref": "file:explicit:def456"}
    remerge = _merge_created_artifact_entry(merge.value, new)

    assert len(remerge.value) == 1
    assert remerge.value[0]["ref"] == "file:explicit:def456"


def test_merge_rejects_agent_managed_shape() -> None:
    try:
        _merge_created_artifact_entry(
            "owned",
            _created_artifact_entry(_artifact(), source_retained=True, bead_id=None),  # type: ignore[arg-type]
        )
    except CreatedArtifactsShapeError:
        pass
    else:
        raise AssertionError("expected CreatedArtifactsShapeError")


def test_merge_evicts_oldest_past_cap() -> None:
    current: list = [
        {"ref": f"file:explicit:{i:04d}", "label": f"{i}.md"} for i in range(100)
    ]
    entry = {"ref": "file:explicit:new", "label": "new.md"}
    merge = _merge_created_artifact_entry(current, entry)  # type: ignore[arg-type]

    assert len(merge.value) == 100
    assert merge.evicted == 1
    assert merge.value[-1]["ref"] == "file:explicit:new"
    assert merge.index == 99


def test_oversized_entry_alone_raises() -> None:
    entry = {"ref": "file:explicit:big", "label": "x" * 9000}
    try:
        _merge_created_artifact_entry(None, entry)  # type: ignore[arg-type]
    except CreatedArtifactEntryTooLargeError:
        pass
    else:
        raise AssertionError("expected CreatedArtifactEntryTooLargeError")


def test_record_created_artifact_persists_variable(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text("{}", encoding="utf-8")

    with patch(
        "sase.core.agent_meta_update.update_agent_artifact_index_for_marker_mutation"
    ):
        merge = record_created_artifact(
            artifacts_dir, _artifact(), source_retained=True, bead_id=None
        )

    assert merge.index == 0
    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert meta["output_variables"]["artifacts"][0]["ref"] == "file:explicit:abc123"


def test_handle_create_prints_var_and_stores_variable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "home"
    artifacts_dir = (
        home
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260507120000"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "agent-one"}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")

    args = argparse.Namespace(
        path=str(source), label=None, kind=None, move=False, bead=None
    )
    assert handle_create(args) == 0

    out = capsys.readouterr().out.splitlines()
    assert f"var: {CREATED_ARTIFACTS_OUTPUT_VARIABLE}[0]" in out
    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    stored = meta["output_variables"]["artifacts"][0]
    assert stored["ref"].startswith("file:explicit:")
    assert stored["source_path"] == str(source.resolve())
