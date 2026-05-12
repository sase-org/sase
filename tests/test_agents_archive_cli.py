"""CLI coverage for dismissed-agent archive search/show/stats/revive."""

from __future__ import annotations

import argparse
import json
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
