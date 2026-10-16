"""Pick-time resolution and archived-prompt repair for file hints."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.hints._link_context_capture import CapturedLinkContext
from sase.ace.tui.actions.hints._view_materialize import (
    materialize_selected_view_files,
)
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.sdd.store import AGENTS_SIDECAR_ROLE


def test_materializes_logical_plan_target_through_ordered_anchors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    primary = tmp_path / "primary"
    workspace.mkdir()
    primary.mkdir()
    plan_path = tmp_path / "plans" / "202610" / "x.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("plan\n", encoding="utf-8")
    context = LinkResolutionContext(
        anchors=(
            LinkAnchor(workspace, workspace_num=7),
            LinkAnchor(primary, workspace_num=1),
        )
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_materialize.link_context_from_capture",
        lambda _captured: context,
    )
    calls: list[tuple[str, str, int]] = []

    def resolve(
        ref: str,
        *,
        workspace_dir: str | Path,
        workspace_num: int,
    ) -> SimpleNamespace:
        calls.append((ref, str(workspace_dir), workspace_num))
        path = plan_path if workspace_dir == primary else None
        return SimpleNamespace(resolved_path=path)

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_target_repair.resolve_plan_reference",
        resolve,
    )

    result = materialize_selected_view_files(
        ("plan:202610/x.md", "plan:202610/x.md"),
        (),
        (),
        CapturedLinkContext(source="default"),
    )

    assert result.files == (str(plan_path),)
    assert result.unresolved_plan_refs == ()
    assert calls == [
        ("plan:202610/x.md", str(workspace), 7),
        ("plan:202610/x.md", str(primary), 1),
    ]


def test_unresolved_plan_target_is_not_statd_as_a_cwd_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = LinkResolutionContext(anchors=(LinkAnchor(Path("/anchor"), 1),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_materialize.link_context_from_capture",
        lambda _captured: context,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_target_repair.resolve_plan_reference",
        lambda *_args, **_kwargs: SimpleNamespace(resolved_path=None),
    )
    real_exists = os.path.exists

    def check_exists(path: str | os.PathLike[str]) -> bool:
        if os.fspath(path).startswith("plan:"):
            raise AssertionError("logical plan identity was stat'd as a path")
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", check_exists)

    result = materialize_selected_view_files(
        ("plan:202610/missing.md",),
        (),
        (),
        CapturedLinkContext(source="default"),
    )

    assert result.files == ()
    assert result.missing_paths == ()
    assert result.unresolved_plan_refs == ("plan:202610/missing.md",)


def test_missing_archived_prompt_repairs_to_agents_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    project_key = "gh_acme__demo"
    project_file = tmp_path / "project" / project_key / f"{project_key}.sase"
    prompt_target = (
        sase_home
        / "projects"
        / project_key
        / "repos"
        / AGENTS_SIDECAR_ROLE
        / "prompts"
        / "202610"
        / "x.md"
    )
    prompt_target.parent.mkdir(parents=True)
    prompt_target.write_text("archived prompt\n", encoding="utf-8")
    missing_workspace_target = tmp_path / "workspace" / "prompts" / "202610" / "x.md"
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_materialize.link_context_from_capture",
        lambda _captured: LinkResolutionContext(),
    )

    result = materialize_selected_view_files(
        (str(missing_workspace_target),),
        (),
        (),
        CapturedLinkContext(source="agent", project_file=str(project_file)),
    )

    assert result.files == (str(prompt_target),)
    assert result.missing_paths == ()


def test_missing_archived_prompt_stays_missing_without_sidecar_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    project_key = "gh_acme__demo"
    project_file = tmp_path / "project" / project_key / f"{project_key}.sase"
    missing = tmp_path / "workspace" / "prompts" / "202610" / "x.md"
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_materialize.link_context_from_capture",
        lambda _captured: LinkResolutionContext(),
    )

    result = materialize_selected_view_files(
        (str(missing),),
        (),
        (),
        CapturedLinkContext(source="agent", project_file=str(project_file)),
    )

    assert result.files == ()
    assert result.missing_paths == (str(missing),)
