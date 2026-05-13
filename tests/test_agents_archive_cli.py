"""CLI coverage for dismissed-agent archive search/show/stats/revive."""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.dismissed_bundle_index import rebuild_index
from sase.ace.tui.models.agent import AgentType
from sase.agents.cli_archive import handle_agents_archive


def _archive_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "archive_subcommand": "search",
        "query": "",
        "limit": 50,
        "json": True,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _write_bundle(root: Path, **overrides: object) -> Path:
    raw_suffix = str(overrides.get("raw_suffix", "20260512120000"))
    bundle: dict[str, object] = {
        "raw_suffix": raw_suffix,
        "agent_type": "run",
        "cl_name": "default_cl",
        "agent_name": "default_agent",
        "project_file": "/tmp/projects/sase/sase.sase",
        "status": "DONE",
        "start_time": "2026-05-12T12:00:00",
        "dismissed_at": "2026-05-12T12:30:00",
        "model": "gpt-5.5",
        "llm_provider": "codex",
        "runtime": "codex",
        "archive_search_text": "default transcript",
    }
    bundle.update(overrides)
    shard = root / raw_suffix[:6]
    shard.mkdir(parents=True, exist_ok=True)
    path = shard / f"{raw_suffix}.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def test_archive_search_json_uses_query_planner(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_bundle(tmp_path, cl_name="failed_cl", status="FAILED")
    _write_bundle(tmp_path, raw_suffix="20260512130000", cl_name="done_cl")
    rebuild_index(tmp_path)

    args = _archive_args(archive_subcommand="search", query="status:failed", limit=10)
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert [row["cl_name"] for row in data["results"]] == ["failed_cl"]
    assert data["next_cursor"] is None


def test_archive_show_json_hydrates_selected_bundle_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_bundle(tmp_path, cl_name="show_cl", agent_name="show_agent")
    rebuild_index(tmp_path)

    args = _archive_args(
        archive_subcommand="show",
        suffix="20260512120000",
        agent_id=None,
        name=None,
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["cl_name"] == "show_cl"
    assert data["summary"]["bundle_path"] == str(path)
    assert data["bundle"]["agent_name"] == "show_agent"


def test_archive_stats_json_reports_requested_facets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_bundle(tmp_path, status="FAILED", runtime="codex")
    _write_bundle(
        tmp_path,
        raw_suffix="20260512130000",
        status="DONE",
        runtime="codex",
    )
    rebuild_index(tmp_path)

    args = _archive_args(
        archive_subcommand="stats",
        query="runtime:codex",
        by="status,runtime",
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["facets"]["runtime"] == {"codex": 2}
    assert data["facets"]["status"] == {"DONE": 1, "FAILED": 1}


def test_archive_revive_requires_unambiguous_query(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_bundle(tmp_path)
    _write_bundle(tmp_path, raw_suffix="20260512130000")
    rebuild_index(tmp_path)

    args = _archive_args(archive_subcommand="revive", query="", all=False)
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 2
    assert "matched multiple agents" in capsys.readouterr().err


def test_archive_revive_preserves_bundle_marks_revived_and_restores_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundles_dir = tmp_path / "bundles"
    dismissed_file = tmp_path / "dismissed_agents.json"
    home = tmp_path / "home"
    project_file = str(home / ".sase" / "projects" / "sase" / "sase.sase")
    bundle_path = _write_bundle(
        bundles_dir,
        cl_name="revive_cl",
        agent_name="revive_agent",
        project_file=project_file,
    )
    rebuild_index(bundles_dir)
    dismissed_file.write_text(
        json.dumps([[AgentType.RUNNING.value, "revive_cl", "20260512120000"]]),
        encoding="utf-8",
    )

    def _home() -> Path:
        return home

    args = _archive_args(
        archive_subcommand="revive",
        query="name:revive_cl",
        all=False,
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", dismissed_file),
        patch.object(Path, "home", _home),
        patch.dict("os.environ", {"HOME": str(home)}),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["restored_agents"] == 1
    assert data["marked_bundles"] == 1
    assert bundle_path.exists()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["times_revived"] == 1
    assert bundle["revived_at"]
    done_json = (
        home
        / ".sase"
        / "projects"
        / "sase"
        / "artifacts"
        / "ace-run"
        / "20260512120000"
        / "done.json"
    )
    assert done_json.exists()
    assert json.loads(dismissed_file.read_text(encoding="utf-8")) == []


def test_archive_purge_dry_run_reports_without_deleting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_bundle(tmp_path, dismissed_at="2026-05-01T00:00:00")
    _write_bundle(
        tmp_path,
        raw_suffix="20260512130000",
        dismissed_at="2026-05-12T00:00:00",
    )
    rebuild_index(tmp_path)

    args = _archive_args(
        archive_subcommand="purge",
        before="2026-05-10",
        agent_id=None,
        query=None,
        dry_run=True,
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is True
    assert data["matched"] == 1
    assert data["purged"] == 0
    assert path.exists()


def test_archive_purge_removes_payload_and_index_rows(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_bundle(tmp_path, cl_name="purge_cl")
    rebuild_index(tmp_path)

    args = _archive_args(
        archive_subcommand="purge",
        before=None,
        agent_id=None,
        query="cl:purge_cl",
        dry_run=False,
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["purged"] == 1
    assert not path.exists()
    assert rebuild_index(tmp_path).indexed_rows == 0


def test_archive_scrub_is_idempotent_and_records_version(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_bundle(tmp_path, archive_search_scrubber_version=1)
    rebuild_index(tmp_path)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["archive_search_text"] = "api_key=sk-1234567890abcdefghijkl"
    bundle["archive_search_scrubber_version"] = 0
    path.write_text(json.dumps(bundle), encoding="utf-8")

    args = _archive_args(
        archive_subcommand="scrub",
        before=None,
        query=None,
        since_scrubber_version=1,
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    first = json.loads(capsys.readouterr().out)
    assert first["scrubbed"] == 1
    scrubbed_bundle = json.loads(path.read_text(encoding="utf-8"))
    assert scrubbed_bundle["archive_search_scrubber_version"] == 1
    assert "sk-1234567890abcdefghijkl" not in scrubbed_bundle["archive_search_text"]

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    second = json.loads(capsys.readouterr().out)
    assert second["scrubbed"] == 0


def test_archive_export_writes_restorable_tar_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "archive-export.tar.gz"
    _write_bundle(tmp_path, cl_name="export_cl")
    rebuild_index(tmp_path)

    args = _archive_args(
        archive_subcommand="export",
        query="cl:export_cl",
        out=str(out),
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["exported"] == 1
    assert out.exists()
    with tarfile.open(out, "r:gz") as archive:
        names = archive.getnames()
        assert "manifest.json" in names
        assert any(name.startswith("bundles/") for name in names)


def test_archive_export_keeps_revisions_at_distinct_tar_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "archive-export.tar.gz"
    raw_suffix = "20260512120000"
    for revision, status in ((1, "FAILED"), (2, "DONE")):
        bundle_path = tmp_path / "202605" / f"same-agent.{revision}" / "bundle.json"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            json.dumps(
                {
                    "raw_suffix": raw_suffix,
                    "agent_type": "run",
                    "cl_name": "export_cl",
                    "agent_name": "export_agent",
                    "project_file": "/tmp/projects/sase/sase.sase",
                    "status": status,
                    "start_time": "2026-05-12T12:00:00",
                    "dismissed_at": f"2026-05-12T12:3{revision}:00",
                    "model": "gpt-5.5",
                    "llm_provider": "codex",
                    "runtime": "codex",
                    "archive_revision": revision,
                }
            ),
            encoding="utf-8",
        )
    rebuild_index(tmp_path)

    args = _archive_args(
        archive_subcommand="export",
        query="cl:export_cl",
        out=str(out),
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_archive(args)

    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["exported"] == 2
    export_paths = [row["export_path"] for row in data["rows"]]
    assert len(export_paths) == len(set(export_paths)) == 2
    with tarfile.open(out, "r:gz") as archive:
        bundle_names = [
            name for name in archive.getnames() if name.startswith("bundles/")
        ]
    assert sorted(bundle_names) == sorted(export_paths)
