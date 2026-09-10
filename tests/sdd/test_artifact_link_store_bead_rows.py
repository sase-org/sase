"""Bead endpoint row behavior for the artifact link store."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import (
    _plan_index,
    _row,
    _store,
    write_imported_cutover_marker,
)


def test_bead_endpoint_is_not_written_to_sidecar_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(source="plan:202608/a.md", relation="related", target="bead:sase-js")
    )

    plan_index = _plan_index(tmp_path, "a.md")
    assert plan_index.is_file()
    assert list((tmp_path / "plans" / "links").rglob("*.json")) == [plan_index]
    rows = store.load_artifact_rows("bead:sase-js")
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "plan:202608/a.md"


def test_bead_bead_row_lives_in_the_event_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        store.upsert_row(
            _row(
                source=f"bead:{left.id}",
                relation="related",
                target=f"bead:{right.id}",
                description="shares the ACE-TUI flake root cause",
            )
        )

        assert list((tmp_path / "plans").rglob("*.json")) == []
        rows = store.load_artifact_rows(f"bead:{left.id}")
        assert len(rows) == 1
        assert rows[0]["relation"] == "related"
        assert project.show(left.id).links[0].target_ref == f"bead:{right.id}"


def test_plan_implements_bead_reaches_the_bead_from_either_direction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Target", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        store.upsert_row(
            _row(
                source="plan:202608/a.md",
                relation="implements",
                target=f"bead:{issue.id}",
                description="lands the approved CLI design",
            )
        )

        # Visible from the bead's own stream (what `sase bead show` reads).
        assert project.show(issue.id).links[0].direction == "in"
        assert project.show(issue.id).links[0].target_ref == "plan:202608/a.md"

        # Visible from the plan's own sidecar (what `sase artifact link
        # list plan:X` reads).
        plan_rows = store.load_artifact_rows("plan:202608/a.md")
        assert len(plan_rows) == 1
        assert plan_rows[0]["target_ref"] == f"bead:{issue.id}"

        # And the aggregate holds exactly one row for it, not two.
        aggregate_rows = [
            row
            for row in store.load_aggregate()["rows"]
            if row["relation"] == "implements"
        ]
        assert len(aggregate_rows) == 1
        assert aggregate_rows[0]["source_ref"] == "plan:202608/a.md"
        assert aggregate_rows[0]["target_ref"] == f"bead:{issue.id}"


def test_backfill_bead_endpoint_links_is_additive_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Target", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)

        # Simulate a one-sided write from before this phase existed: only
        # the plan's sidecar knows about the edge, and the bead has never
        # learned its own inbound endpoint event.
        store._upsert_sidecar(
            "plan:202608/a.md",
            _row(
                source="plan:202608/a.md",
                relation="implements",
                target=f"bead:{issue.id}",
                description="lands the approved CLI design",
            ),
        )
        assert project.show(issue.id).links == []

        result = store.backfill_bead_endpoint_links()
        assert result["written"] == 1
        assert project.show(issue.id).links[0].direction == "in"

        again = store.backfill_bead_endpoint_links()
        assert again["written"] == 0


def test_imported_backfill_projects_from_events_without_sidecar_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Target", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        plans = tmp_path / "plans"
        plans.mkdir(exist_ok=True)
        event = _event_for_row(
            store.project_key,
            _row(
                source="plan:202608/a.md",
                relation="implements",
                target=f"bead:{issue.id}",
                description="lands the approved CLI design",
            ),
        )
        _write_event(plans, event)
        store.rebuild_aggregate()
        write_imported_cutover_marker(store)

        result = store.backfill_bead_endpoint_links()

        assert result["candidates"] == 1
        assert result["written"] == 1
        assert list((plans / "links").rglob("*.json")) == []
        assert project.show(issue.id).links[0].direction == "in"


def test_bead_load_includes_incoming_rows_stored_on_the_target_bead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        store.upsert_row(
            _row(
                source="agent:alice.athena.reviewer",
                relation="cites",
                target=f"bead:{issue.id}",
                origin="prompt_ref",
                description="Prompt citation of the bead.",
                uses=3,
            )
        )

        # The bead itself now stores the inbound endpoint event, so the row
        # is visible from `sase bead show` (not only the machine-global
        # aggregate this workspace happens to hold). Bead-owned rows do not
        # carry `uses`, matching the existing outbound-position behavior.
        rows = store.load_artifact_rows(f"bead:{issue.id}")
        assert len(rows) == 1
        assert rows[0]["source_ref"] == "agent:alice.athena.reviewer"
        assert rows[0]["target_ref"] == f"bead:{issue.id}"
        assert project.show(issue.id).links[0].direction == "in"


def test_bead_owned_rows_skip_a_second_bead_store_reduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        owned = _row(
            source=f"bead:{left.id}",
            relation="implements",
            target="plan:202608/a.md",
            description="lands the approved CLI design",
        )
        calls = {"list": 0}
        real = ArtifactLinkStore._list_bead_issues

        def counting(self: ArtifactLinkStore) -> tuple[object, ...]:
            calls["list"] += 1
            return real(self)

        monkeypatch.setattr(ArtifactLinkStore, "_list_bead_issues", counting)
        rows = store.load_artifact_rows(
            f"bead:{left.id}",
            bead_owned_rows=(owned,),
        )
        assert calls["list"] == 0
        assert rows[0]["target_ref"] == "plan:202608/a.md"
        store.load_artifact_rows(f"bead:{left.id}")
        assert calls["list"] == 1


def test_bead_merge_includes_sidecar_and_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        issue = project.create("Left", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": tmp_path / "plans"},
            beads_dir=project.beads_dir,
        )
        (tmp_path / "plans").mkdir(exist_ok=True)
        sidecar = _row(
            source="plan:202608/a.md",
            relation="related",
            target=f"bead:{issue.id}",
            description="plan sidecar row",
        )
        store.upsert_row(sidecar)
        owned = _row(
            source=f"bead:{issue.id}",
            relation="related",
            target="plan:202608/a.md",
            description="bead owned duplicate",
        )
        rows = store.load_artifact_rows(
            f"bead:{issue.id}",
            bead_owned_rows=(owned,),
        )
        related = [row for row in rows if row["relation"] == "related"]
        assert len(related) == 1
        assert related[0]["description"] == "bead owned duplicate"


def _event_for_row(project_key: str, row: dict[str, object]) -> dict[str, object]:
    edge = {
        "kind": "directed",
        "source_ref": row["source_ref"],
        "relation": row["relation"],
        "target_ref": row["target_ref"],
    }
    event = {
        "schema_version": int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        "project_key": project_key,
        "operation_id": "d" * 32,
        "created_by": row["created_by"],
        "origin": row["origin"],
        "created_at": row["created_at"],
        "kind": {
            "type": "edge-put",
            "edge": edge,
            "description": row["description"],
            "observed_operation_ids": [],
        },
    }
    return dict(require_rust_binding("artifact_link_event_canonicalize")(event))


def _write_event(root: Path, event: dict[str, object]) -> None:
    digest = str(require_rust_binding("artifact_link_event_digest")(event))
    relpath = str(require_rust_binding("artifact_link_event_path_for_digest")(digest))
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        str(require_rust_binding("artifact_link_event_canonical_json")(event)),
        encoding="utf-8",
    )
