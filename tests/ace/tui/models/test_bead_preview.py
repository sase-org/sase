"""Tests for bead-store directory routing and preview loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models.bead_preview import (
    BeadRouteAmbiguous,
    BeadRouteFound,
    BeadRouteMissing,
    BeadRouteNotBead,
    BeadRouteUnavailable,
    BeadStoreDirectory,
    BeadStoreRef,
    load_bead_preview,
    route_bead_mention,
)
from sase.bead.cross_project import (
    BeadStoreOrigin,
    BeadStoreSnapshot,
    bead_id_prefix,
)
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.core.bead_target_routing_facade import (
    BeadTargetRoute,
    _BeadTargetRouteError,
    _BeadTargetStoreRoute,
)


def _snapshot(
    tmp_path: Path,
    *,
    project_key: str = "sase",
    project_label: str = "sase",
    issue_prefix: str | None = "sase",
    issue_ids: frozenset[str] = frozenset(),
    project_refs: frozenset[str] | None = None,
    beads_dir: Path | None | object = ...,
    unavailable_reason: str | None = None,
) -> BeadStoreSnapshot:
    resolved_dir: Path | None
    if beads_dir is ...:
        resolved_dir = tmp_path / "beads"
    else:
        resolved_dir = beads_dir  # type: ignore[assignment]
    origin = BeadStoreOrigin(
        project_key=project_key,
        project_label=project_label,
        primary_workspace=tmp_path,
        beads_dir=resolved_dir,
    )
    return BeadStoreSnapshot(
        origin=origin,
        store_key=project_key,
        issue_ids=issue_ids,
        issue_prefix=issue_prefix,
        project_refs=project_refs
        if project_refs is not None
        else frozenset({project_key}),
        unavailable_reason=unavailable_reason,
    )


def _directory(tmp_path: Path, **kwargs: object) -> BeadStoreDirectory:
    return BeadStoreDirectory(snapshots=(_snapshot(tmp_path, **kwargs),))


def test_unowned_prefix_is_not_a_bead(tmp_path: Path) -> None:
    directory = _directory(tmp_path, issue_prefix="sase")
    route = route_bead_mention("other-1aa", directory)
    assert isinstance(route, BeadRouteNotBead)
    assert route.bead_id == "other-1aa"


def test_route_found_and_missing_from_real_store(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        issue = project.create("Epic", IssueType.PLAN, description="Body")
        prefix = bead_id_prefix(issue.id)
        assert prefix is not None
        directory = _directory(
            tmp_path,
            issue_prefix=prefix,
            issue_ids=frozenset({issue.id}),
            beads_dir=tmp_path / "beads",
        )
        found = route_bead_mention(issue.id, directory)
        assert isinstance(found, BeadRouteFound)
        assert found.store.beads_dir == tmp_path / "beads"
        missing = route_bead_mention(f"{prefix}-zzzz", directory)
        assert isinstance(missing, BeadRouteMissing)
        assert missing.project_labels == ("sase",) or prefix in missing.bead_id


def test_route_ambiguous_without_and_with_project_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "a" / "beads"
    second = tmp_path / "b" / "beads"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    directory = BeadStoreDirectory(
        snapshots=(
            _snapshot(
                tmp_path / "a",
                project_key="sase",
                issue_prefix="sase",
                beads_dir=first,
            ),
            _snapshot(
                tmp_path / "b",
                project_key="bob-cli",
                project_label="bob-cli",
                issue_prefix="sase",
                beads_dir=second,
                project_refs=frozenset({"bob-cli"}),
            ),
        )
    )
    candidates = (
        _BeadTargetStoreRoute(
            store_key="sase",
            project_key="sase",
            project_label="sase",
            beads_dir=first,
        ),
        _BeadTargetStoreRoute(
            store_key="bob-cli",
            project_key="bob-cli",
            project_label="bob-cli",
            beads_dir=second,
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.bead_preview.route_full_id_with_snapshots",
        lambda *_a, **_k: BeadTargetRoute(
            requested_id="sase-1aa",
            error=_BeadTargetRouteError(
                kind="ambiguous",
                message="ambiguous",
                candidates=candidates,
            ),
        ),
    )
    route = route_bead_mention("sase-1aa", directory)
    assert isinstance(route, BeadRouteAmbiguous)
    assert "sase" in route.project_labels
    assert "bob-cli" in route.project_labels

    monkeypatch.setattr(
        "sase.ace.tui.models.bead_preview.probe_bead_target_owner",
        lambda beads_dir, _bead_id: (
            ("hit", None) if Path(beads_dir) == first else ("miss", None)
        ),
    )
    pinned = route_bead_mention("sase-1aa", directory, project_ref="sase")
    assert isinstance(pinned, BeadRouteFound)
    assert pinned.store.project_key == "sase"


def test_route_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = BeadStoreDirectory(
        snapshots=(
            _snapshot(
                tmp_path,
                beads_dir=None,
                unavailable_reason="locked",
            ),
        )
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.bead_preview.route_full_id_with_snapshots",
        lambda *_a, **_k: BeadTargetRoute(
            requested_id="sase-1aa",
            error=_BeadTargetRouteError(kind="unavailable", message="locked"),
        ),
    )
    route = route_bead_mention("sase-1aa", directory)
    assert isinstance(route, BeadRouteUnavailable)
    assert route.reason == "locked"


def test_load_bead_preview_epic_phase_inheritance_and_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("record_bead_reads must not run for a human peek")

    monkeypatch.setattr("sase.bead.bead_reads.record_bead_reads", boom)
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        epic = project.create(
            "Epic title",
            IssueType.PLAN,
            description="Epic body",
            design="gmail_archive.md",
            tier=BeadTier.EPIC,
        )
        phase = project.create(
            "Phase title",
            IssueType.PHASE,
            parent_id=epic.id,
            description="Phase body",
            size="small",
        )
        task = project.create(
            "Task title", IssueType.TASK, task_type="bug", size="small"
        )
        project.add_dependency(epic.id, task.id)
        store = BeadStoreRef(
            project_key="sase",
            project_label="sase",
            beads_dir=tmp_path / "beads",
            primary_workspace=tmp_path,
        )
        preview = load_bead_preview(epic.id, store)
        assert preview.issue.title == "Epic title"
        assert preview.issue.description == "Epic body"
        assert any(child.id == phase.id for child in preview.children)
        assert preview.plan_reference == "gmail_archive.md"
        assert preview.plan_source == "self"

        inherited = load_bead_preview(phase.id, store)
        assert inherited.plan_reference == "gmail_archive.md"
        assert inherited.plan_source == "parent"
        assert inherited.ancestors[0] is not None
        assert inherited.ancestors[0].id == epic.id

        prefix = bead_id_prefix(epic.id)
        assert prefix is not None
        with pytest.raises(KeyError):
            load_bead_preview(f"{prefix}-zzzz", store)
