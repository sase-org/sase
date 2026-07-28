"""Bulk reconciliation coverage for generated bead pages."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead_pages.associations import (
    BeadAgentAssociation,
    BeadAssociationIndex,
    BeadAssociations,
    BeadCommitAssociation,
)
from sase.bead_pages.refresh import (
    bead_pages_refresh_to_json,
    refresh_bead_pages,
)
from sase.sdd.store import SddStore


class _View:
    def __init__(self, issues: tuple[Issue, ...]) -> None:
        self._issues = issues

    def __enter__(self) -> _View:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def list_issues(self) -> list[Issue]:
        return list(self._issues)


class _Links:
    def plan_url(self, _plan_ref: str) -> str | None:
        return None


def _store(tmp_path: Path) -> SddStore:
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    plans.mkdir()
    beads.mkdir()
    return SddStore(
        "sidecar_repos",
        plans,
        plans,
        beads_dir=beads,
    )


def _issues() -> tuple[Issue, ...]:
    root = Issue(
        "sase-ai",
        "Published | pages",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    phase = Issue(
        "sase-ai.7",
        "Bulk refresh",
        issue_type=IssueType.PHASE,
        parent_id=root.id,
    )
    other = Issue(
        "sase-other",
        "Other",
        issue_type=IssueType.PLAN,
        tier=BeadTier.PLAN,
    )
    return root, phase, other


def _index() -> BeadAssociationIndex:
    agent = BeadAgentAssociation("agent", None, "sase-ai.7", 1, ("agent", "sase-ai.7"))
    commit = BeadCommitAssociation(
        "abcdef0",
        None,
        "sase-ai.7",
        "feat: refresh",
        1,
        (1, "abcdef012345"),
        "abcdef012345",
    )
    return BeadAssociationIndex(
        MappingProxyType(
            {
                "sase-ai": BeadAssociations((agent,), (commit,)),
                "sase-ai.7": BeadAssociations((agent,), (commit,)),
            }
        )
    )


@contextmanager
def _acquired_lock(
    *_args: object,
    **_kwargs: object,
) -> Iterator[bool]:
    yield True


def _patch_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    issues: tuple[Issue, ...],
) -> list[tuple[Path, ...]]:
    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_project_for_beads_dir",
        lambda _root: _View(issues),
    )
    monkeypatch.setattr(
        "sase.bead_pages.rendering.render_bead_page_detail_bytes",
        lambda detail, _issues, _index, **_kwargs: f"# {detail.issue.id}\n".encode(),
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    committed: list[tuple[Path, ...]] = []

    def commit(*_args: object, **kwargs: object) -> bool:
        paths = cast(tuple[Path, ...], kwargs["paths"])
        committed.append(tuple(Path(path) for path in paths))
        assert kwargs["auto_commit_type"] == "beads"
        assert kwargs["already_locked"] is True
        assert kwargs["push_after_commit"] == "async"
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)
    return committed


def _beads_root(store: SddStore) -> Path:
    assert store.beads_dir is not None
    return store.beads_dir


def test_refresh_dry_run_write_orphan_removal_roster_and_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    issues = _issues()
    committed = _patch_dependencies(monkeypatch, issues)
    orphan = _beads_root(store) / "pages" / "sase-gone" / "README.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("# stale\n", encoding="utf-8")

    dry = refresh_bead_pages(
        store,
        primary_root=tmp_path,
        association_index=_index(),
        link_resolver=_Links(),  # type: ignore[arg-type]
    )

    assert dry.ok
    assert dry.scanned == 3
    assert dry.lineages == 2
    assert [(action.path, action.change) for action in dry.actions] == [
        ("README.md", "create"),
        ("sase-ai/README.md", "create"),
        ("sase-ai/sase-ai.7.md", "create"),
        ("sase-gone/README.md", "remove"),
        ("sase-other/README.md", "create"),
    ]
    assert dry.changed_files == ()
    assert dry.removed_files == ()
    assert orphan.is_file()

    written = refresh_bead_pages(
        store,
        primary_root=tmp_path,
        write=True,
        association_index=_index(),
        link_resolver=_Links(),  # type: ignore[arg-type]
    )

    assert written.ok and written.committed
    assert written.actions == dry.actions
    assert written.removed_files == ("sase-gone/README.md",)
    assert not orphan.exists()
    roster = (_beads_root(store) / "pages" / "README.md").read_text(encoding="utf-8")
    assert "[sase-ai](sase-ai/README.md)" in roster
    assert "Published \\| pages" in roster
    assert "| epic | in_progress | 1 | 1 | 1 |" in roster
    assert len(committed) == 1

    second = refresh_bead_pages(
        store,
        primary_root=tmp_path,
        write=True,
        association_index=_index(),
        link_resolver=_Links(),  # type: ignore[arg-type]
    )

    assert second.ok
    assert second.actions == ()
    assert second.changed_files == ()
    assert second.removed_files == ()
    assert not second.committed
    assert len(committed) == 1
    assert bead_pages_refresh_to_json(second)["would_change"] == 0


def test_bead_scope_touches_only_the_selected_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    issues = _issues()
    _patch_dependencies(monkeypatch, issues)
    pages = _beads_root(store) / "pages"
    roster = pages / "README.md"
    selected = pages / "sase-ai" / "README.md"
    selected_orphan = pages / "sase-ai" / "sase-ai.gone.md"
    unrelated = pages / "sase-other" / "README.md"
    for path, content in (
        (roster, "# keep roster\n"),
        (selected, "# old\n"),
        (selected_orphan, "# remove\n"),
        (unrelated, "# keep unrelated\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    report = refresh_bead_pages(
        store,
        primary_root=tmp_path,
        bead_id="sase-ai.7",
        write=True,
        association_index=_index(),
        link_resolver=_Links(),  # type: ignore[arg-type]
    )

    assert report.ok
    assert report.scanned == 2
    assert report.lineages == 1
    assert [(action.path, action.change) for action in report.actions] == [
        ("sase-ai/README.md", "update"),
        ("sase-ai/sase-ai.7.md", "create"),
        ("sase-ai/sase-ai.gone.md", "remove"),
    ]
    assert roster.read_text(encoding="utf-8") == "# keep roster\n"
    assert unrelated.read_text(encoding="utf-8") == "# keep unrelated\n"
    assert not selected_orphan.exists()


def test_missing_bead_scope_is_an_error_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _patch_dependencies(monkeypatch, _issues())

    report = refresh_bead_pages(
        store,
        primary_root=tmp_path,
        bead_id="sase-missing",
        write=True,
        association_index=_index(),
        link_resolver=_Links(),  # type: ignore[arg-type]
    )

    assert not report.ok
    assert report.errors[0].code == "bead-unresolved"
    assert report.actions == ()
