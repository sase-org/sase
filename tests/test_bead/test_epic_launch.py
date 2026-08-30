"""Argv building, origin mapping, and project resolution tests for epic launch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead.epic_launch import (
    build_epic_launch_argv,
    epic_launch_origin_from_gate_source,
    resolve_epic_launch_project,
)
from sase.xprompt.directive_edit import PromptWaitDirective


def test_build_epic_launch_argv_carries_approval_linking_options() -> None:
    assert build_epic_launch_argv(
        "/tmp/epic plan.md",
        artifacts_dir="/tmp/artifacts",
        cl_name="demo",
    ) == [
        "sase",
        "bead",
        "work",
        "/tmp/epic plan.md",
        "--yes-to-all",
        "--artifacts-dir",
        "/tmp/artifacts",
        "--cl-name",
        "demo",
        "--expect-prompt-snapshot",
    ]


def test_build_epic_launch_argv_defaults_to_expecting_prompt_snapshot() -> None:
    argv = build_epic_launch_argv("/tmp/epic plan.md")

    assert "--expect-prompt-snapshot" in argv


def test_build_epic_launch_argv_omits_expect_prompt_snapshot_when_disabled() -> None:
    argv = build_epic_launch_argv(
        "/tmp/epic plan.md",
        expect_prompt_snapshot=False,
    )

    assert "--expect-prompt-snapshot" not in argv


def test_build_epic_launch_argv_omits_wait_by_default() -> None:
    argv = build_epic_launch_argv("/tmp/epic plan.md")

    assert "--wait" not in argv


def test_build_epic_launch_argv_omits_wait_for_an_empty_spec() -> None:
    argv = build_epic_launch_argv(
        "/tmp/epic plan.md",
        wait_spec=PromptWaitDirective(),
    )

    assert "--wait" not in argv


def test_build_epic_launch_argv_appends_formatted_wait_spec() -> None:
    argv = build_epic_launch_argv(
        "/tmp/epic plan.md",
        wait_spec=PromptWaitDirective(agents=("sase-s7.2",), beads=("sase-64.3",)),
    )

    assert argv[-2:] == ["--wait", "sase-s7.2,bead=sase-64.3"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("tui", "ace"),
        ("telegram", "telegram"),
        ("auto_resolution", "axe"),
        ("host", "api"),
        ("unknown", "api"),
        (None, "api"),
    ],
)
def test_epic_launch_origin_maps_gate_response_sources(
    source: str | None,
    expected: str,
) -> None:
    assert epic_launch_origin_from_gate_source(source) == expected


def test_resolve_epic_launch_project_prefers_canonical_project_file(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sase_10"
    project_dir.mkdir()
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )

    with patch("sase.workspace_provider.get_workspace_name") as get_workspace_name:
        resolved = resolve_epic_launch_project(
            project_dir,
            agent_project_file=project_file,
        )

    assert resolved == "gh_sase-org__sase"
    get_workspace_name.assert_not_called()


def test_resolve_epic_launch_project_accepts_project_file_without_project_dir(
    tmp_path: Path,
) -> None:
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )

    with patch("sase.workspace_provider.get_workspace_name") as get_workspace_name:
        resolved = resolve_epic_launch_project(
            None,
            agent_project_file=project_file,
        )

    assert resolved == "gh_sase-org__sase"
    get_workspace_name.assert_not_called()


def test_resolve_epic_launch_project_requires_a_project_signal() -> None:
    with pytest.raises(ValueError, match="project_dir or agent_project_file"):
        resolve_epic_launch_project(None)


@pytest.mark.parametrize("provider_name", ["sase", None])
def test_resolve_epic_launch_project_canonicalizes_compatibility_fallback(
    tmp_path: Path,
    provider_name: str | None,
) -> None:
    project_dir = tmp_path / "sase_10"

    with (
        patch(
            "sase.workspace_provider.get_workspace_name",
            return_value=provider_name,
        ),
        patch(
            "sase.project_aliases.resolve_project_alias_ref",
            return_value="gh_sase-org__sase",
        ) as resolve_alias,
    ):
        resolved = resolve_epic_launch_project(project_dir)

    assert resolved == "gh_sase-org__sase"
    resolve_alias.assert_called_once_with("sase")


def test_resolve_epic_launch_project_rejects_invalid_project_file_identity(
    tmp_path: Path,
) -> None:
    with (
        patch("sase.workspace_provider.get_workspace_name") as get_workspace_name,
        pytest.raises(ValueError, match="does not identify a valid SASE project"),
    ):
        resolve_epic_launch_project(
            tmp_path / "sase_10",
            agent_project_file="project.sase",
        )

    get_workspace_name.assert_not_called()
