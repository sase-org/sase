from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.artifact_cli.prune import handle_prune
from sase.artifact_cli.trash import handle_trash
from sase.core.artifact_file_explicit import (
    read_artifact_file_index,
    write_artifact_file_index_unlocked,
)
from sase.core.artifact_file_protection import ProtectedArtifactIds
from sase.core.artifact_file_trash import list_trashed_artifact_files
from sase.core.artifact_file_types import ArtifactFile
from sase.project_display_names import ProjectRefDisplaySnapshot


def _prune_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "apply": False,
        "before": None,
        "keep_generations": 1,
        "json": False,
        "kind": None,
        "limit": None,
        "min_size": None,
        "project": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _row(
    artifact_id: str,
    path: Path,
    *,
    created_at: str,
    explicit: bool = False,
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_id,
        label="report",
        kind="file",
        path=str(path),
        created_at=created_at,
        project="proj",
        explicit=explicit,
        sha256=artifact_id[-24:],
        size_bytes=path.stat().st_size,
    )


def _seed_prune_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, ArtifactFile, ArtifactFile, ArtifactFile]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    root = tmp_path / "artifacts"
    root.mkdir()
    old_path = root / "old.txt"
    new_path = root / "new.txt"
    explicit_path = root / "explicit.txt"
    old_path.write_text("old", encoding="utf-8")
    new_path.write_text("new", encoding="utf-8")
    explicit_path.write_text("declared", encoding="utf-8")
    old = _row(
        "default:111111111111111111111111",
        old_path,
        created_at="2026-07-01T00:00:00Z",
    )
    new = _row(
        "default:222222222222222222222222",
        new_path,
        created_at="2026-07-02T00:00:00Z",
    )
    explicit = _row(
        "explicit:333333333333333333333333",
        explicit_path,
        created_at="2026-07-01T00:00:00Z",
        explicit=True,
    )
    index = root / "index.jsonl"
    write_artifact_file_index_unlocked(index, [old, new, explicit])
    monkeypatch.setattr(
        "sase.artifact_cli.prune.load_project_ref_display_snapshot",
        ProjectRefDisplaySnapshot,
    )
    return index, old, new, explicit


def test_prune_dry_run_writes_nothing_and_apply_trashes_only_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index, old, new, explicit = _seed_prune_store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.artifact_cli.prune.collect_protected_artifact_ids",
        lambda: ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=("projects",),
            sources_unavailable=(),
        ),
    )
    before = index.read_bytes()
    store_before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    assert handle_prune(_prune_args()) == 0

    assert index.read_bytes() == before
    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == store_before
    assert "Dry run only" in capsys.readouterr().out

    assert handle_prune(_prune_args(apply=True)) == 0

    assert {row.id for row in read_artifact_file_index(index)} == {
        new.id,
        explicit.id,
    }
    assert [entry.artifact_id for entry in list_trashed_artifact_files().entries] == [
        old.id
    ]
    assert "Trashed 1 rows" in capsys.readouterr().out


def test_unavailable_protection_source_blocks_apply_but_not_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index, old, new, explicit = _seed_prune_store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.artifact_cli.prune.collect_protected_artifact_ids",
        lambda: ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=("projects",),
            sources_unavailable=("proj:plans",),
        ),
    )
    before = index.read_bytes()

    assert handle_prune(_prune_args()) == 0
    assert index.read_bytes() == before
    assert "Protection source unavailable" in capsys.readouterr().out

    assert handle_prune(_prune_args(apply=True)) == 1
    assert index.read_bytes() == before
    assert {row.id for row in read_artifact_file_index(index)} == {
        old.id,
        new.id,
        explicit.id,
    }
    assert "Apply refused" in capsys.readouterr().out


def test_prune_json_contains_plan_and_apply_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_prune_store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.artifact_cli.prune.collect_protected_artifact_ids",
        lambda: ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=("projects",),
            sources_unavailable=(),
        ),
    )

    assert handle_prune(_prune_args(apply=True, json=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["mode"] == "apply"
    assert payload["plan"]["counts"]["selected"] == 1
    assert payload["execution"]["rows_trashed"] == 1


def test_trash_cli_lists_and_restores_by_artifact_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _index, old, _new, _explicit = _seed_prune_store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.artifact_cli.prune.collect_protected_artifact_ids",
        lambda: ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=("projects",),
            sources_unavailable=(),
        ),
    )
    assert handle_prune(_prune_args(apply=True)) == 0
    capsys.readouterr()

    assert (
        handle_trash(
            argparse.Namespace(
                trash_subcommand="list",
                json=True,
                limit=50,
            )
        )
        == 0
    )
    listing = json.loads(capsys.readouterr().out)
    assert listing["entries"][0]["artifact_id"] == old.id
    assert listing["entries"][0]["past_grace_period"] is False

    assert (
        handle_trash(
            argparse.Namespace(
                trash_subcommand="restore",
                json=True,
                reference=f"file:{old.id}",
            )
        )
        == 0
    )
    restored = json.loads(capsys.readouterr().out)
    assert restored["artifact_id"] == old.id
    assert Path(restored["restored_path"]).read_text(encoding="utf-8") == "old"


def test_prune_dry_run_and_apply_exclude_consumed_only_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index, old, new, explicit = _seed_prune_store(tmp_path, monkeypatch)
    protections = ProtectedArtifactIds(
        referenced_ids=frozenset(),
        consumed_ids=frozenset({old.id}),
        sources_scanned=(str(tmp_path / "artifacts" / "consumption.jsonl"),),
        sources_unavailable=(),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.prune.collect_protected_artifact_ids",
        lambda: protections,
    )
    before = index.read_bytes()

    assert handle_prune(_prune_args(json=True)) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["plan"]["counts"]["selected"] == 0
    assert dry_run["policy"]["protected_ids"] == [old.id]
    assert index.read_bytes() == before

    assert handle_prune(_prune_args(apply=True, json=True)) == 0
    apply = json.loads(capsys.readouterr().out)
    assert apply["plan"]["counts"]["selected"] == 0
    assert apply["execution"]["rows_trashed"] == 0
    assert index.read_bytes() == before
    assert {row.id for row in read_artifact_file_index(index)} == {
        old.id,
        new.id,
        explicit.id,
    }
