"""Tests for tree-wide plan provenance reconciliation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType

import pytest

from sase.sdd.associations import (
    PlanAgentAssociation,
    PlanAssociationIndex,
    PlanAssociations,
    PlanCommitAssociation,
)
from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.plan_links_refresh import refresh_plan_links
from sase.sdd.store import SddStore


def _store(root: Path) -> SddStore:
    root.mkdir()
    return SddStore("sidecar_repos", root, root)


def _write_plan(
    root: Path,
    name: str,
    *,
    tier: str = "tale",
    parent: str | None = None,
) -> Path:
    path = root / "202607" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_line = f"parent: {parent}\n" if parent else ""
    path.write_text(
        f"---\ntier: {tier}\ntitle: {name}\ngoal: Test\n{parent_line}---\n# {name}\n",
        encoding="utf-8",
    )
    return path


@contextmanager
def _acquired_lock(*_args: object, **_kwargs: object):
    yield True


def test_refresh_dry_run_write_and_second_write_are_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    _write_plan(root, "epic", tier="epic")
    child = _write_plan(
        root,
        "child",
        parent="plans:202607/epic.md",
    )
    associations = PlanAssociations(
        agents=(PlanAgentAssociation("owner.host.agent", None, "owner.host.agent"),),
        commits=(
            PlanCommitAssociation(
                "abcdef0",
                None,
                "feat: child",
                (1, "abcdef012345"),
                "abcdef012345",
            ),
        ),
    )
    index = PlanAssociationIndex(
        MappingProxyType({"plans:202607/child.md": associations})
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )
    committed: list[tuple[Path, ...]] = []

    def commit(*_args: object, **kwargs: object) -> bool:
        committed.append(tuple(Path(path) for path in kwargs["paths"]))
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)
    before = child.read_text(encoding="utf-8")

    dry = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
    )

    assert dry.ok
    assert dry.scanned == 2
    assert [action.path for action in dry.actions] == ["202607/child.md"]
    assert dry.actions[0].parent_migrated
    assert dry.changed_files == ()
    assert child.read_text(encoding="utf-8") == before

    written = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
        write=True,
    )

    assert written.ok and written.committed
    assert written.changed_files == ("202607/child.md",)
    assert committed == [(child,)]
    content = child.read_text(encoding="utf-8")
    assert "\nparent:" not in content
    assert "— feat: child" in content
    assert "— —" not in content
    parsed = parse_plan_header_block(content)
    assert [section.kind for section in parsed.sections] == [
        PlanHeaderSectionKind.PARENT,
        PlanHeaderSectionKind.AGENTS,
        PlanHeaderSectionKind.COMMITS,
    ]

    second = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
        write=True,
    )

    assert second.ok
    assert second.actions == ()
    assert second.changed_files == ()
    assert not second.committed
    assert committed == [(child,)]


def test_refresh_reports_unresolved_legacy_parent_without_dropping_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    child = _write_plan(root, "child", parent="plans:202607/missing.md")
    before = child.read_text(encoding="utf-8")
    index = PlanAssociationIndex(MappingProxyType({}))

    report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        association_index=index,
    )

    assert not report.ok
    assert report.errors[0].code == "parent-unresolved"
    assert report.actions == ()
    assert child.read_text(encoding="utf-8") == before


def test_refresh_plan_scope_rejects_missing_reference(tmp_path: Path) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    _write_plan(root, "child")

    report = refresh_plan_links(
        store,
        primary_root=tmp_path,
        plan_ref="plans:202607/missing.md",
        association_index=PlanAssociationIndex(MappingProxyType({})),
    )

    assert not report.ok
    assert report.scanned == 0
    assert report.errors[0].code == "plan-unresolved"
