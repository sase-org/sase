"""Lifecycle and query integration for configured ProjectSpec names."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.changespec import cache as cache_mod
from sase.ace.changespec import (
    find_all_changespecs as find_all_patches,  # legacy compatibility alias
)
from sase.ace.changespec.cache import (
    ChangeSpecSnapshotCache as PatchSnapshotCache,  # legacy compatibility alias
)
from sase.ace.changespec.models import Patch
from sase.ace.query import parse_query
from sase.core.query_facade import evaluate_query, evaluate_query_many
from sase.main.search_handler import handle_search_command


def _write_project(
    projects_root: Path,
    directory_key: str,
    *,
    project_name: str | None,
) -> tuple[Path, Path]:
    project_dir = projects_root / directory_key
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{directory_key}.sase"
    archive_file = project_dir / f"{directory_key}-archive.sase"
    metadata = "" if project_name is None else f"PROJECT_NAME: {project_name}\n"
    project_file.write_text(
        metadata
        + "PROJECT_ALIASES: legacy-alias\n"
        + "NAME: active_change\nDESCRIPTION:\n  active\nSTATUS: Ready\n",
        encoding="utf-8",
    )
    archive_file.write_text(
        "NAME: archived_change\nDESCRIPTION:\n  archived\nSTATUS: Submitted\n",
        encoding="utf-8",
    )
    return project_file, archive_file


def _names(query: str, patches: list[Patch]) -> list[str]:
    mask = evaluate_query_many(query, patches)
    return [cs.name for cs, keep in zip(patches, mask, strict=True) if keep]


def _reference_names(query: str, patches: list[Patch]) -> list[str]:
    expr = parse_query(query)
    return [cs.name for cs in patches if evaluate_query(expr, cs, patches)]


def test_lifecycle_discovery_attaches_project_name_to_active_and_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    _write_project(
        sase_home / "projects",
        "gh_acme__widgets",
        project_name="Widgets",
    )

    patches = find_all_patches()
    assert {cs.name for cs in patches} == {
        "active_change",
        "archived_change",
    }
    assert {cs.project_name for cs in patches} == {"gh_acme__widgets"}
    assert {cs.project_basename for cs in patches} == {"gh_acme__widgets"}
    assert {cs.project_query_name for cs in patches} == {"Widgets"}

    for query in ("project:widgets", "project:WIDGETS", "+Widgets"):
        assert _names(query, patches) == [
            "active_change",
            "archived_change",
        ]
        assert _reference_names(query, patches) == _names(query, patches)

    for query in ("project:gh_acme__widgets", "+gh_acme__widgets", "+legacy-alias"):
        assert _names(query, patches) == []
        assert _reference_names(query, patches) == []


def test_project_query_falls_back_to_directory_key_without_project_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    _write_project(sase_home / "projects", "plain-project", project_name=None)

    patches = find_all_patches()
    assert _names("project:PLAIN-PROJECT", patches) == [
        "active_change",
        "archived_change",
    ]
    assert _names("+plain-project", patches) == [
        "active_change",
        "archived_change",
    ]


def test_snapshot_cache_refreshes_archive_query_name_when_metadata_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    project_file, archive_file = _write_project(
        sase_home / "projects",
        "gh_acme__widgets",
        project_name="widgets",
    )
    archive_stat = archive_file.stat()

    cache = PatchSnapshotCache()
    first = cache.find_all_patches_cached()
    assert _names("+widgets", first) == ["active_change", "archived_change"]

    project_file.write_text(
        project_file.read_text(encoding="utf-8").replace(
            "PROJECT_NAME: widgets", "PROJECT_NAME: gadgets"
        ),
        encoding="utf-8",
    )
    fresh_ns = max(project_file.stat().st_mtime_ns, archive_stat.st_mtime_ns) + 1
    os.utime(project_file, ns=(fresh_ns, fresh_ns))

    real_parse = cache_mod.parse_project_file
    with patch.object(
        cache_mod, "parse_project_file", side_effect=real_parse
    ) as parse_spy:
        second = cache.find_all_patches_cached()

    assert archive_file.stat().st_mtime_ns == archive_stat.st_mtime_ns
    assert any(
        call.args[0] == os.fspath(archive_file) for call in parse_spy.call_args_list
    )
    assert _names("+widgets", second) == []
    assert _names("+gadgets", second) == ["active_change", "archived_change"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("project:widgets", {"active_change", "archived_change"}),
        ("+WIDGETS", {"active_change", "archived_change"}),
        ("project:gh_acme__widgets", set()),
    ],
)
def test_patch_search_cli_uses_effective_project_name(
    query: str,
    expected: set[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    _write_project(
        sase_home / "projects",
        "gh_acme__widgets",
        project_name="widgets",
    )

    args = argparse.Namespace(query=query, format="plain")
    with pytest.raises(SystemExit, match="0"):
        handle_search_command(args)

    output = capsys.readouterr().out
    for name in expected:
        assert f"NAME: {name}" in output
    if not expected:
        assert "No Patches match the query." in output
