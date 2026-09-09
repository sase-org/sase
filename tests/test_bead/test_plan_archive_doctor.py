"""Plan archive diagnosis and repair coverage for ``sase bead doctor``."""

from __future__ import annotations

import json
from pathlib import Path

from sase.bead.model import BeadTier, IssueType
from sase.bead.plan_archive_doctor import (
    inspect_plan_archive_health,
    repair_plan_archive,
)
from sase.bead.project import BeadProject
from sase.bead._sync_publication import head_is_published
from sase.sdd._artifact_link_store_support import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore
from tests.plan_validation_helpers import VALID_TALE_PLAN
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


MONTH = "202607"


def test_plan_archive_doctor_reports_missing_categories(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    local = tmp_path / "local-plans"
    plans.mkdir()
    store = SddStore("sidecar_repos", plans, plans)
    linked_source = _write_local_plan(local, "linked")
    draft_source = _write_local_plan(local, "draft")
    orphan_index = _write_link_index(plans, f"plan:{MONTH}/orphan.md")

    with BeadProject.init(tmp_path / "project") as project:
        issue = project.create(
            "Linked plan",
            IssueType.PLAN,
            design=f"plan:{MONTH}/{linked_source.name}",
            tier=BeadTier.PLAN,
            created_by="bbugyi200.apollo.abc",
        )
        issues = project.list_issues()

    report = inspect_plan_archive_health(
        issues,
        store,
        plan_roots=(plans, local),
    )

    assert [finding.plan_ref for finding in report.bead_linked_missing] == [
        f"plan:{MONTH}/linked.md"
    ]
    assert report.bead_linked_missing[0].bead_id == issue.id
    assert report.bead_linked_missing[0].source_path == linked_source
    assert report.bead_linked_missing[0].source_machine == "apollo"
    assert [finding.plan_ref for finding in report.orphaned_link_indexes] == [
        f"plan:{MONTH}/orphan.md"
    ]
    assert report.orphaned_link_indexes[0].sidecar_path == plans / MONTH / "orphan.md"
    assert orphan_index.is_file()
    assert [finding.plan_ref for finding in report.local_only_canonical] == [
        f"plan:{MONTH}/draft.md"
    ]
    assert report.local_only_canonical[0].source_path == draft_source


def test_plan_archive_repair_restores_bead_id_and_publishes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    origin = _seed_plans_origin(tmp_path)
    plans = tmp_path / "plans"
    clone(origin, plans)
    local = tmp_path / "local-plans"
    source = _write_local_plan(local, "missing")
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url=str(origin),
        sidecar_role="plans",
    )
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )

    with BeadProject.init(tmp_path / "project") as project:
        issue = project.create(
            "Missing archive",
            IssueType.PLAN,
            design=f"plan:{MONTH}/missing.md",
            tier=BeadTier.PLAN,
        )
        report = inspect_plan_archive_health(
            project.list_issues(),
            store,
            plan_roots=(plans, local),
        )

    result = repair_plan_archive(report, store, primary_root=tmp_path)

    assert result.repaired == (f"plan:{MONTH}/missing.md",)
    assert result.committed
    archived = plans / MONTH / "missing.md"
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        archived.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == issue.id
    assert (
        parse_frontmatter(source.read_text(encoding="utf-8"))[0]["bead_id"] == issue.id
    )
    assert head_is_published(plans)

    verifier = tmp_path / "verifier"
    clone(origin, verifier)
    assert (verifier / MONTH / "missing.md").is_file()


def _seed_plans_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "plans.git"
    init_bare_repo(origin)
    seed = tmp_path / "seed"
    clone(origin, seed)
    (seed / "README.md").write_text("plans\n", encoding="utf-8")
    commit_all(seed, "init plans")
    git(["push", "-u", "origin", "main"], seed)
    return origin


def _write_local_plan(root: Path, stem: str) -> Path:
    path = root / MONTH / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(VALID_TALE_PLAN, encoding="utf-8")
    return path


def _write_link_index(root: Path, plan_ref: str) -> Path:
    _kind, _separator, relpath = plan_ref.partition(":")
    path = root / "links" / f"{relpath}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "artifact_ref": plan_ref,
                "rows": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path
