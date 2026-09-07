"""Tests for pager link-resolution workspace anchors."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from sase.pager.link_context import (
    LinkAnchor,
    LinkResolutionContext,
    agent_link_context,
    default_link_context,
    inherited_link_context,
    link_anchor_for_directory,
    merge_link_context,
    workspace_link_context,
)


def _write_checkout_marker(
    checkout_dir: Path, primary: Path, workspace_num: int
) -> None:
    marker_dir = checkout_dir / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "primary_workspace_dir": str(primary),
                "project_key": "org/proj",
                "project_name": "proj",
                "registry_path": str(checkout_dir.parent / "registry.json"),
                "schema_version": 1,
                "workspace_num": workspace_num,
            }
        ),
        encoding="utf-8",
    )


def test_default_link_context_anchors_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.pager.link_context.get_primary_workspace_dir",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    context = default_link_context()

    assert context.base_dirs == (tmp_path.resolve(),)
    assert context.anchors[0].workspace_num is None


def test_default_link_context_appends_distinct_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "sase_7"
    primary = tmp_path / "primary"
    checkout.mkdir()
    primary.mkdir()
    _write_checkout_marker(checkout, primary, workspace_num=7)
    monkeypatch.chdir(checkout)

    context = default_link_context()

    assert context.base_dirs == (checkout.resolve(), primary.resolve())
    assert context.anchors[0].workspace_num == 7
    assert context.anchors[1].workspace_num == 1


def test_default_link_context_skips_missing_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.pager.link_context.get_primary_workspace_dir",
        lambda *_args, **_kwargs: str(tmp_path / "missing"),
    )

    assert default_link_context().base_dirs == (tmp_path.resolve(),)


def test_default_link_context_degrades_when_primary_lookup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.pager.link_context.get_primary_workspace_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert default_link_context().base_dirs == (tmp_path.resolve(),)


def test_agent_link_context_orders_agent_then_primary_then_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = tmp_path / "agent"
    primary = tmp_path / "primary"
    cwd = tmp_path / "cwd"
    agent.mkdir()
    primary.mkdir()
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._file_path_hints.resolve_agent_workspace_dir",
        lambda *_args, **_kwargs: str(agent),
    )
    monkeypatch.setattr(
        "sase.pager.link_context.parse_workspace_dir",
        lambda _project_file: str(primary),
    )
    monkeypatch.setattr(
        "sase.pager.link_context.get_primary_workspace_dir",
        lambda *_args, **_kwargs: str(cwd),
    )

    context = agent_link_context(12, str(tmp_path / "proj.sase"), str(agent))

    assert context.base_dirs == (agent.resolve(), primary.resolve(), cwd.resolve())
    assert context.anchors[0].workspace_num == 12
    assert context.anchors[1].workspace_num == 1


def test_agent_link_context_degrades_when_agent_workspace_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._file_path_hints.resolve_agent_workspace_dir",
        lambda *_args, **_kwargs: str(tmp_path / "gone"),
    )
    monkeypatch.setattr(
        "sase.pager.link_context.parse_workspace_dir",
        lambda _project_file: None,
    )
    monkeypatch.setattr(
        "sase.pager.link_context.get_primary_workspace_dir",
        lambda *_args, **_kwargs: str(cwd),
    )

    context = agent_link_context(3, str(tmp_path / "proj.sase"))

    assert context.base_dirs == (cwd.resolve(),)


def test_workspace_link_context_orders_workspace_primary_then_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "sase_8"
    primary = tmp_path / "primary"
    cwd = tmp_path / "cwd"
    workspace.mkdir()
    primary.mkdir()
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(
        "sase.pager.link_context.get_primary_workspace_dir",
        lambda current, *_args, **_kwargs: (
            str(primary) if Path(current).name == "sase_8" else str(cwd)
        ),
    )

    context = workspace_link_context(workspace, workspace_num=8)

    assert context.base_dirs == (workspace.resolve(), primary.resolve(), cwd.resolve())
    assert [anchor.workspace_num for anchor in context.anchors] == [8, 1, None]


def test_workspace_link_context_empty_string_uses_only_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.pager.link_context.get_primary_workspace_dir",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    assert workspace_link_context("").base_dirs == (tmp_path.resolve(),)


def test_inherited_link_context_prepends_landed_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    nested = workspace / "src"
    nested.mkdir(parents=True)
    landed = nested / "foo.py"
    landed.write_text("ok\n", encoding="utf-8")
    parent = LinkResolutionContext(
        anchors=(LinkAnchor(directory=workspace, workspace_num=4),)
    )

    context = inherited_link_context(landed, parent)

    assert context.base_dirs == (nested.resolve(), workspace.resolve())
    assert context.anchors[1].workspace_num == 4


def test_inherited_link_context_dedupes_when_parent_is_already_first(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    parent = LinkResolutionContext(anchors=(LinkAnchor(directory=workspace),))

    context = inherited_link_context(workspace / "foo.py", parent)

    assert context.base_dirs == (workspace.resolve(),)


def test_link_anchor_for_directory_recovers_workspace_num_from_marker(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "sase_9"
    primary = tmp_path / "primary"
    checkout.mkdir()
    primary.mkdir()
    _write_checkout_marker(checkout, primary, workspace_num=9)

    anchor = link_anchor_for_directory(checkout)

    assert anchor == LinkAnchor(directory=checkout.resolve(), workspace_num=9)


def test_merge_link_context_prepends_and_dedupes_section_anchors(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    document_context = LinkResolutionContext(
        anchors=(
            LinkAnchor(directory=second, workspace_num=2),
            LinkAnchor(directory=first, workspace_num=1),
        )
    )

    merged = merge_link_context(
        (LinkAnchor(directory=first, workspace_num=1),),
        document_context,
    )

    assert merged is not None
    assert merged.base_dirs == (first.resolve(), second.resolve())


def test_link_context_module_does_not_call_workspace_cleaner() -> None:
    import sase.pager.link_context as link_context

    tree = ast.parse(Path(link_context.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    assert "get_workspace_directory_for_num" not in names
