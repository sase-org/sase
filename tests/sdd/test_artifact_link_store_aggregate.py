"""Aggregate rebuild behavior for the artifact link store."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import itertools
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _plan_index, _row, _store

_OLD_SOURCE_DATE = "2026-08-01T00:00:00+00:00"
_ROW_CREATED_DATE = "2026-08-18T00:00:00Z"
_NEWER_MTIME_DATE = "2026-08-25T00:00:00+00:00"


def _git(repo: Path, *args: str, env: Mapping[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "SASE Test")
    _git(repo, "config", "user.email", "sase-test@example.com")


def _commit_all(repo: Path, message: str, *, when: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        message,
        env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when},
    )


def _touch(path: Path, when: str) -> None:
    timestamp = datetime.fromisoformat(when).astimezone(UTC).timestamp()
    os.utime(path, (timestamp, timestamp))


def _touch_tree(root: Path, when: str) -> None:
    _touch(root, when)
    for path in root.rglob("*"):
        _touch(path, when)


def test_rebuild_carries_forward_rows_from_invisible_sidecar_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans_a = tmp_path / "clone-a" / "plans"
    plans_b = tmp_path / "clone-b" / "plans"
    plans_a.mkdir(parents=True)
    plans_b.mkdir(parents=True)
    store_a = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_a},
    )
    store_b = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_b},
    )
    store_a.upsert_row(_row())

    rebuilt = store_b.rebuild_aggregate()

    assert len(rebuilt["rows"]) == 1
    assert rebuilt["rows"][0]["source_ref"] == "plan:202608/a.md"


def test_rebuild_drops_rows_deleted_from_visible_sidecar_companion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row())
    for path in (_plan_index(tmp_path, "a.md"), _plan_index(tmp_path, "b.md")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["rows"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")

    rebuilt = store.rebuild_aggregate()

    assert rebuilt["rows"] == []
    assert store.load_aggregate()["rows"] == []


def test_rebuild_carries_forward_row_when_sidecar_commit_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans_a = tmp_path / "clone-a" / "plans"
    plans_b = tmp_path / "clone-b" / "plans"
    plans_a.mkdir(parents=True)
    _init_git_repo(plans_b)
    stale_index = plans_b / "links" / "202608" / "a.md.json"
    stale_index.parent.mkdir(parents=True)
    stale_index.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_ref": "plan:202608/a.md",
                "rows": [],
            }
        ),
        encoding="utf-8",
    )
    _commit_all(plans_b, "seed stale companion index", when=_OLD_SOURCE_DATE)
    _touch(stale_index, _NEWER_MTIME_DATE)
    store_a = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_a},
    )
    store_b = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_b},
    )
    store_a.upsert_row(_row(created_at=_ROW_CREATED_DATE))

    rebuilt = store_b.rebuild_aggregate()

    assert [(row["source_ref"], row["target_ref"]) for row in rebuilt["rows"]] == [
        ("plan:202608/a.md", "plan:202608/b.md")
    ]


def test_rebuild_carries_forward_bead_row_when_bead_store_commit_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    ahead_root = tmp_path / "ahead"
    behind_root = tmp_path / "behind"
    _init_git_repo(behind_root)
    with BeadProject.init(ahead_root) as ahead_project:
        issue = ahead_project.create("Target", IssueType.PLAN)
        store_a = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={},
            beads_dir=ahead_project.beads_dir,
        )
        store_a.upsert_row(
            _row(
                source="agent:alice.athena.worker",
                relation="cites",
                target=f"bead:{issue.id}",
                origin="prompt_ref",
                created_at=_ROW_CREATED_DATE,
            )
        )
    with BeadProject.init(behind_root) as behind_project:
        behind_beads_dir = behind_project.beads_dir
    _commit_all(behind_root, "seed stale bead store", when=_OLD_SOURCE_DATE)
    _touch_tree(behind_beads_dir, _NEWER_MTIME_DATE)
    store_b = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={},
        beads_dir=behind_beads_dir,
    )

    rebuilt = store_b.rebuild_aggregate()

    assert [(row["source_ref"], row["target_ref"]) for row in rebuilt["rows"]] == [
        ("agent:alice.athena.worker", f"bead:{issue.id}")
    ]


def test_rebuild_drops_bead_row_deleted_from_fresh_bead_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.project import BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={},
            beads_dir=project.beads_dir,
        )
        store._upsert_aggregate_row(  # noqa: SLF001 - seed a prior aggregate row.
            _row(
                source="agent:alice.athena.worker",
                relation="cites",
                target="bead:sase-missing",
                origin="prompt_ref",
                created_at="1970-01-01T00:00:00Z",
            )
        )

        rebuilt = store.rebuild_aggregate()

    assert rebuilt["rows"] == []


def test_remove_rows_prunes_aggregate_even_when_sidecar_is_invisible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans_a = tmp_path / "clone-a" / "plans"
    plans_b = tmp_path / "clone-b" / "plans"
    plans_a.mkdir(parents=True)
    plans_b.mkdir(parents=True)
    store_a = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_a},
    )
    store_b = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_b},
    )
    store_a.upsert_row(_row())

    removed = store_b.remove_rows("plan:202608/a.md", "plan:202608/b.md")

    assert [row["relation"] for row in removed] == ["implements"]
    assert store_b.load_aggregate()["rows"] == []


def test_every_aggregate_writer_converges_regardless_of_publish_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`rebuild_aggregate` and `reconcile_aggregate` must agree on kept rows.

    Regression test for the defect diagnosed in
    plan:202608/link_rail_every_tab.md: with an unresolvable `agent:`
    endpoint (the housekeeping chop's primary-checkout cwd, reproduced here
    by stubbing `resolve_cli_reference` to always miss),
    `reconcile_aggregate` used to drop `cites`/`read` rows that
    `rebuild_aggregate` kept, so whichever writer ran last decided whether
    those relation classes existed at all. Both writers, in both orders,
    must now land on the same row set.
    """

    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context",
        lambda *, is_home_mode: object(),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference",
        lambda _ref, **_kwargs: SimpleNamespace(
            resolution=SimpleNamespace(status="missing")
        ),
    )
    expected = {
        ("agent:pending.athena.worker", "cites", "plan:202608/a.md"),
        ("agent:pending.athena.worker", "read", "plan:202608/a.md"),
    }

    def row_set(document: Mapping[str, Any]) -> set[tuple[str, str, str]]:
        return {
            (row["source_ref"], row["relation"], row["target_ref"])
            for row in document["rows"]
        }

    writers = {
        "rebuild": lambda store: store.rebuild_aggregate(),
        "reconcile": lambda store: store.reconcile_aggregate(),
    }
    for order in itertools.permutations(writers):
        store = _store(tmp_path / "-".join(order), monkeypatch)
        store.upsert_row(
            _row(
                source="agent:pending.athena.worker",
                relation="cites",
                target="plan:202608/a.md",
                origin="prompt_ref",
                description="cites the plan while drafting",
            )
        )
        store.upsert_row(
            _row(
                source="agent:pending.athena.worker",
                relation="read",
                target="plan:202608/a.md",
                origin="read",
                description="read while drafting",
            )
        )

        last: dict[str, object] = {}
        for name in order:
            last = writers[name](store)

        assert row_set(last) == expected, order
        assert row_set(store.load_aggregate()) == expected, order
        # The publication-facing view still holds back the unpublished row.
        assert store.durable_sidecar_rows() == ()


def test_stale_preview_is_rejected_and_retried_rather_than_clobbering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuild derived from a stale generation must merge, not clobber.

    `preview_aggregate` reads the on-disk generation as its merge base.
    Simulate a concurrent writer (a chop, a sibling clone) advancing the
    aggregate past that base before the write lands: the CAS write must
    refuse the stale write, and `rebuild_aggregate`'s retry loop must
    recompute against the new base so the concurrent writer's row survives.
    """

    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row(source="plan:202608/a.md", target="plan:202608/b.md"))
    stale_preview = store.preview_aggregate()

    # A concurrent writer advances the generation past the preview's base.
    store._upsert_aggregate_row(  # noqa: SLF001 - simulate a racing writer
        _row(source="plan:202608/e.md", target="plan:202608/f.md")
    )

    rejected = store._write_aggregate_if_current(stale_preview)  # noqa: SLF001
    assert rejected is None

    rebuilt = store.rebuild_aggregate()

    assert {(r["source_ref"], r["target_ref"]) for r in rebuilt["rows"]} == {
        ("plan:202608/a.md", "plan:202608/b.md"),
        ("plan:202608/e.md", "plan:202608/f.md"),
    }
    assert {
        (r["source_ref"], r["target_ref"]) for r in store.load_aggregate()["rows"]
    } == {
        ("plan:202608/a.md", "plan:202608/b.md"),
        ("plan:202608/e.md", "plan:202608/f.md"),
    }
