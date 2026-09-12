"""Repository target resolution tests for ``sase repo open``."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.repo_handler import RepoOpenResolutionError, _match_repo_record
from sase.main.repo_open_external import ExternalRepoOpenError, open_external_repo
from sase.repo_inventory import RepoInventory
from tests.main.repo_handler_helpers import (
    project_context,
    repo_record,
    set_git_origin,
)


def test_repo_open_parser_requires_reason_and_accepts_context_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "repo",
            "open",
            "core",
            "--project",
            "demo",
            "--reason",
            "fix bindings",
            "--workspace",
            "12",
        ]
    )

    assert args.repo_subcommand == "open"
    assert args.repo == "core"
    assert args.project == "demo"
    assert args.reason == "fix bindings"
    assert args.workspace == 12

    with pytest.raises(SystemExit) as help_exit:
        create_parser().parse_args(["repo", "open", "--help"])

    assert help_exit.value.code == 0
    assert "without cleaning" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        create_parser().parse_args(["repo", "open", "core"])


def test_repo_name_resolution_prefers_linked_over_primary_alias(
    tmp_path: Path,
) -> None:
    host_ctx = project_context(tmp_path)
    primary = repo_record(tmp_path, name="demo", kind="primary")
    linked = repo_record(tmp_path, name="demo", kind="linked")

    resolved = _match_repo_record(
        "demo",
        host_ctx=host_ctx,
        inventory=RepoInventory((primary, linked)),
    )

    assert resolved is linked


def test_repo_name_resolution_accepts_sidecar_slug(tmp_path: Path) -> None:
    host_ctx = project_context(tmp_path)
    sidecar = repo_record(
        tmp_path,
        name="research",
        slug="shared-research",
        kind="sidecar",
    )

    resolved = _match_repo_record(
        "shared-research",
        host_ctx=host_ctx,
        inventory=RepoInventory((sidecar,)),
    )

    assert resolved is sidecar


def test_repo_name_resolution_raises_ambiguous_error_with_selectable_paths(
    tmp_path: Path,
) -> None:
    host_ctx = project_context(tmp_path)
    first = repo_record(tmp_path, name="agents", slug="sase--agents", kind="sidecar")
    second = replace(
        repo_record(tmp_path, name="agents", slug="sase--agents", kind="sidecar"),
        path=str(tmp_path / "other-agents-path"),
    )

    with pytest.raises(RepoOpenResolutionError) as exc_info:
        _match_repo_record(
            "agents",
            host_ctx=host_ctx,
            inventory=RepoInventory((first, second)),
        )

    message = str(exc_info.value)
    assert first.path in message
    assert second.path in message
    assert "Pass one of the listed paths" in message


def test_repo_name_resolution_disambiguates_by_path(tmp_path: Path) -> None:
    host_ctx = project_context(tmp_path)
    first = repo_record(tmp_path, name="agents", slug="sase--agents", kind="sidecar")
    second = replace(
        repo_record(tmp_path, name="agents", slug="sase--agents", kind="sidecar"),
        path=str(tmp_path / "other-agents-path"),
    )

    resolved = _match_repo_record(
        second.path,
        host_ctx=host_ctx,
        inventory=RepoInventory((first, second)),
    )

    assert resolved is second


def test_repo_name_resolution_matches_github_alias_from_linked_origin(
    tmp_path: Path,
) -> None:
    host_ctx = project_context(tmp_path)
    linked = repo_record(tmp_path, name="sase-core", kind="linked")
    set_git_origin(Path(linked.path), "git@github.com:sase-org/sase-core.git")

    inventory = RepoInventory((linked,))

    assert (
        _match_repo_record(
            "gh:SASE-Org/SASE-Core",
            host_ctx=host_ctx,
            inventory=inventory,
        )
        is linked
    )
    assert (
        _match_repo_record(
            "sase-org/sase-core",
            host_ctx=host_ctx,
            inventory=inventory,
        )
        is linked
    )


def test_repo_name_resolution_does_not_match_basename_only(
    tmp_path: Path,
) -> None:
    host_ctx = project_context(tmp_path)
    linked = repo_record(tmp_path, name="sase-core", kind="linked")
    set_git_origin(Path(linked.path), "git@github.com:other/sase-core.git")

    assert (
        _match_repo_record(
            "gh:sase-org/sase-core",
            host_ctx=host_ctx,
            inventory=RepoInventory((linked,)),
        )
        is None
    )


def test_unknown_repo_lists_valid_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = project_context(tmp_path)
    inventory = RepoInventory(
        (
            repo_record(tmp_path, name="demo", kind="primary"),
            repo_record(tmp_path, name="core", kind="linked"),
        )
    )

    monkeypatch.setattr(
        "sase.main.repo_open_external.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    with pytest.raises(ExternalRepoOpenError) as exc_info:
        open_external_repo(
            "missing",
            host_ctx=host_ctx,
            workspace_num=0,
            inventory=inventory,
            reason="test",
            resolve_checkout=lambda *_args, **_kwargs: host_ctx.primary_workspace_dir,
        )

    assert "Valid repos: core, demo" in str(exc_info.value)
    assert "gh:owner/repo" in str(exc_info.value)


def test_materialized_external_is_not_a_tier_one_cleaning_target(
    tmp_path: Path,
) -> None:
    host_ctx = project_context(tmp_path)
    external = repo_record(tmp_path, name="gh:acme/widget", kind="external")

    assert (
        _match_repo_record(
            "gh:acme/widget",
            host_ctx=host_ctx,
            inventory=RepoInventory((external,)),
        )
        is None
    )
