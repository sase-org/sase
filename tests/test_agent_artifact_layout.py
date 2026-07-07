from __future__ import annotations

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agents.cli_artifacts_layout import handle_agents_artifacts_layout
from sase.artifacts import create_artifacts_directory, launch_artifacts_dir
from sase.core.agent_artifact_paths import (
    DAY_SHARDED_LAYOUT_VERSION,
    LEGACY_LAYOUT_VERSION,
    iter_agent_artifact_dirs,
    parse_agent_artifact_path,
    resolve_agent_artifact_path,
)


def _layout_args(
    subcommand: str,
    *,
    projects_root: Path,
    index_path: Path,
    manifest: Path | None = None,
    dry_run: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        artifacts_subcommand="layout",
        layout_subcommand=subcommand,
        dry_run=dry_run,
        force=False,
        index_path=str(index_path),
        json=True,
        limit=None,
        manifest=str(manifest) if manifest is not None else None,
        project="proj",
        projects_root=str(projects_root),
    )


def _read_json_output(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return json.loads(capsys.readouterr().out)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_create_artifacts_directory_uses_day_shards_for_ace_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    ace_dir = Path(
        create_artifacts_directory(
            "ace-run",
            "proj",
            timestamp="260613_120000",
        )
    )
    assert ace_dir == (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202606"
        / "13"
        / "20260613120000"
    )
    assert ace_dir.is_dir()

    other_dir = Path(
        create_artifacts_directory(
            "crs",
            "proj",
            timestamp="260613_120001",
        )
    )
    assert other_dir == (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "crs"
        / "20260613120001"
    )
    assert other_dir.is_dir()


def test_launch_artifacts_dir_uses_day_shards_for_ace_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    artifacts_dir = Path(launch_artifacts_dir("proj", "260613_120000"))

    assert artifacts_dir == (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202606"
        / "13"
        / "20260613120000"
    )
    assert not artifacts_dir.exists()


def test_create_artifacts_directory_canonicalizes_project_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )

    artifacts_dir = Path(
        create_artifacts_directory(
            "ace-run",
            "bob",
            timestamp="260613_120000",
        )
    )

    assert artifacts_dir == (
        tmp_path
        / ".sase"
        / "projects"
        / "bob-cli"
        / "artifacts"
        / "ace-run"
        / "202606"
        / "13"
        / "20260613120000"
    )
    assert artifacts_dir.is_dir()
    assert not (tmp_path / ".sase" / "projects" / "bob").exists()


def test_artifact_path_helpers_resolve_legacy_to_existing_day_shard(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    legacy_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260613120000"
    sharded_dir = (
        projects_root
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202606"
        / "13"
        / "20260613120000"
    )
    legacy_dir.mkdir(parents=True)
    sharded_dir.mkdir(parents=True)

    legacy_info = parse_agent_artifact_path(legacy_dir, projects_root=projects_root)
    sharded_info = parse_agent_artifact_path(sharded_dir, projects_root=projects_root)

    assert legacy_info is not None
    assert legacy_info.layout_version == LEGACY_LAYOUT_VERSION
    assert sharded_info is not None
    assert sharded_info.layout_version == DAY_SHARDED_LAYOUT_VERSION
    assert (
        resolve_agent_artifact_path(
            legacy_dir,
            projects_root=projects_root,
        )
        == sharded_dir
    )
    assert list(
        iter_agent_artifact_dirs(
            "proj",
            "ace-run",
            projects_root=projects_root,
        )
    ) == [sharded_dir]


def test_artifact_layout_cli_migrates_verifies_and_rolls_back(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "index.sqlite"
    manifest_path = tmp_path / "manifest.json"
    old_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260613120000"
    new_dir = (
        projects_root
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202606"
        / "13"
        / "20260613120000"
    )
    old_dir.mkdir(parents=True)
    _write_json(old_dir / "agent_meta.json", {"name": "agent-one"})
    _write_json(
        old_dir / "workflow_state.json",
        {"artifacts_dir": str(old_dir), "status": "RUNNING"},
    )
    _write_json(
        old_dir / "prompt_step_0.json",
        {"artifacts_dir": str(old_dir), "status": "DONE"},
    )

    handle_agents_artifacts_layout(
        _layout_args(
            "migrate",
            projects_root=projects_root,
            index_path=index_path,
            manifest=manifest_path,
            dry_run=True,
        )
    )
    dry_run_payload = _read_json_output(capsys)
    assert dry_run_payload["entries"][0]["status"] == "planned"
    assert old_dir.is_dir()
    assert not new_dir.exists()

    handle_agents_artifacts_layout(
        _layout_args(
            "migrate",
            projects_root=projects_root,
            index_path=index_path,
            manifest=manifest_path,
        )
    )
    migrate_payload = _read_json_output(capsys)
    assert migrate_payload["moved"] == 1
    assert migrate_payload["marker_files_rewritten"] == 2
    assert not old_dir.exists()
    assert new_dir.is_dir()
    assert json.loads((new_dir / "workflow_state.json").read_text(encoding="utf-8"))[
        "artifacts_dir"
    ] == str(new_dir)

    with closing(sqlite3.connect(index_path)) as conn:
        alias_rows = conn.execute(
            "SELECT alias_path, artifact_dir FROM agent_artifact_aliases"
        ).fetchall()
    assert alias_rows == [(str(old_dir), str(new_dir))]

    handle_agents_artifacts_layout(
        _layout_args(
            "verify",
            projects_root=projects_root,
            index_path=index_path,
            manifest=manifest_path,
        )
    )
    verify_payload = _read_json_output(capsys)
    assert verify_payload["ok"] is True
    assert verify_payload["checked"] == 1

    handle_agents_artifacts_layout(
        _layout_args(
            "status",
            projects_root=projects_root,
            index_path=index_path,
        )
    )
    status_payload = _read_json_output(capsys)
    assert status_payload["flat_dirs"] == 0
    assert status_payload["sharded_dirs"] == 1
    assert status_payload["alias_rows"] == 1

    handle_agents_artifacts_layout(
        _layout_args(
            "rollback",
            projects_root=projects_root,
            index_path=index_path,
            manifest=manifest_path,
        )
    )
    rollback_payload = _read_json_output(capsys)
    assert rollback_payload["rolled_back"] == 1
    assert old_dir.is_dir()
    assert not new_dir.exists()
    assert json.loads((old_dir / "workflow_state.json").read_text(encoding="utf-8"))[
        "artifacts_dir"
    ] == str(old_dir)

    with closing(sqlite3.connect(index_path)) as conn:
        alias_count = conn.execute(
            "SELECT COUNT(*) FROM agent_artifact_aliases"
        ).fetchone()[0]
    assert alias_count == 0


def test_artifact_layout_migrate_persists_manifest_and_records_entry_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "index.sqlite"
    manifest_path = tmp_path / "manifest.json"
    old_one = projects_root / "proj" / "artifacts" / "ace-run" / "20260613120000"
    old_two = projects_root / "proj" / "artifacts" / "ace-run" / "20260613120100"
    new_one = (
        projects_root
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202606"
        / "13"
        / "20260613120000"
    )
    for path, name in ((old_one, "one"), (old_two, "two")):
        path.mkdir(parents=True)
        _write_json(path / "agent_meta.json", {"name": name})

    real_rename = os.rename

    def flaky_rename(src: object, dst: object) -> None:
        if Path(src) == old_two:
            raise OSError("boom")
        real_rename(src, dst)

    with (
        patch("sase.agents.cli_artifacts_layout.os.rename", side_effect=flaky_rename),
        patch("sase.agents.cli_artifacts_layout.rebuild_agent_artifact_index"),
    ):
        handle_agents_artifacts_layout(
            _layout_args(
                "migrate",
                projects_root=projects_root,
                index_path=index_path,
                manifest=manifest_path,
            )
        )

    payload = _read_json_output(capsys)
    assert payload["moved"] == 1
    assert [entry["status"] for entry in payload["entries"]] == [
        "migrated",
        "failed",
    ]
    assert payload["entries"][1]["failure_reason"] == "boom"
    assert (
        json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
        == (payload["entries"])
    )
    assert new_one.is_dir()
    assert old_two.is_dir()

    handle_agents_artifacts_layout(
        _layout_args(
            "rollback",
            projects_root=projects_root,
            index_path=index_path,
            manifest=manifest_path,
        )
    )
    _read_json_output(capsys)
    assert old_one.is_dir()
    assert not new_one.exists()
    assert old_two.is_dir()
