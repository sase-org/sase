from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

from sase.core.rust import require_rust_binding
from sase.doctor.checks_artifact_links import (
    _check_artifact_links_aggregate,
    _check_artifact_link_cutover,
    _check_primary_sidecar_link_dirt,
    _collect_primary_sidecar_link_dirt,
    apply_primary_sidecar_link_dirt_repairs,
    artifact_links_check_specs,
)
from sase.sdd._artifact_link_cutover_state import (
    ArtifactLinkBaselineEventIdentity,
    ArtifactLinkCutoverImportIdentity,
    ArtifactLinkCutoverRole,
    artifact_link_cutover_marker_path,
    build_artifact_link_cutover_marker_payload,
    parse_artifact_link_cutover_marker_payload,
)
from sase.sdd.artifact_link_import_indexes import (
    artifact_link_legacy_links_tree_identity,
)
from sase.doctor.runner import DoctorContext
from sase.sdd.store import SddStore
from tests._conftest_environment import redirect_sase_home


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project="gh_sase-org__sase",
        sase_home=tmp_path / ".sase",
    )


def test_artifact_links_check_specs_register_the_aggregate_check(
    tmp_path: Path,
) -> None:
    specs = artifact_links_check_specs(_context(tmp_path))
    assert [spec.id for spec in specs] == [
        "project.artifact_links_aggregate",
        "project.primary_sidecar_link_dirt",
        "project.artifact_link_cutover",
    ]


def test_artifact_links_check_skips_without_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: None,
    )
    check = _check_artifact_links_aggregate(_context(tmp_path))
    assert check.status == "SKIP"
    assert "no SDD store" in check.summary


def test_artifact_links_check_errors_without_project_key(
    monkeypatch, tmp_path: Path
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: None,
    )
    check = _check_artifact_links_aggregate(_context(tmp_path))
    assert check.status == "ERROR"
    assert "canonical project key" in check.summary


def test_artifact_links_check_ok_when_empty(monkeypatch, tmp_path: Path) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: "gh_sase-org__sase",
    )
    check = _check_artifact_links_aggregate(_context(tmp_path))
    assert check.status == "OK"
    assert check.data["rows"] == 0


def test_artifact_link_cutover_check_ok_without_marker(
    monkeypatch, tmp_path: Path
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: "gh_sase-org__sase",
    )

    check = _check_artifact_link_cutover(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["state"] == "none"


def test_artifact_link_cutover_check_flags_imported_links_tree_stragglers(
    monkeypatch, tmp_path: Path
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    frozen_links_tree = artifact_link_legacy_links_tree_identity(plans)
    digest = "a" * 64
    payload = build_artifact_link_cutover_marker_payload(
        state="imported",
        project_key="gh_sase-org__sase",
        event_store_schema_version=1,
        event_store_minimum_event_schema_version=int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        import_identity=ArtifactLinkCutoverImportIdentity(
            import_id="legacy-v2-links-test",
            operation_id="b" * 32,
            source_head="sha256:" + "c" * 64,
            created_at="2026-09-10T00:00:00Z",
        ),
        roles=(
            ArtifactLinkCutoverRole(
                role="plans",
                kind="plan",
                head="d" * 40,
                links_tree=frozen_links_tree,
                remote_url="<none>",
            ),
        ),
        baseline_event=ArtifactLinkBaselineEventIdentity(
            digest=digest,
            path=f"link-events/v1/{digest[:2]}/{digest}.json",
        ),
    )
    marker_path = artifact_link_cutover_marker_path(plans)
    marker_path.parent.mkdir(parents=True)
    marker_path.write_bytes(
        parse_artifact_link_cutover_marker_payload(payload).canonical_bytes
    )
    link_path = plans / "links" / "doc.md.json"
    link_path.parent.mkdir(parents=True)
    link_path.write_text("{}\n", encoding="utf-8")
    store = SddStore("sidecar_repos", plans, plans)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: "gh_sase-org__sase",
    )

    check = _check_artifact_link_cutover(_context(tmp_path))

    assert check.status == "ERROR"
    assert check.data["state"] == "imported"
    assert check.data["stragglers"]


def test_artifact_links_check_reports_row_level_and_projected_drift(
    monkeypatch, tmp_path: Path
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    expected_rows = [
        {
            "schema_version": 2,
            "source_ref": "agent:pending.athena.worker",
            "relation": "cites",
            "target_ref": "plan:202608/a.md",
            "description": "prompt citation",
            "origin": "prompt_ref",
            "created_by": "agent",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        },
        {
            "schema_version": 2,
            "source_ref": "chop:hooks/build",
            "relation": "launched",
            "target_ref": "agent:alice.athena.9w",
            "description": "chop launch metadata",
            "origin": "projected",
            "created_by": "projection:chop-agent",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        },
    ]
    adapter = SimpleNamespace(
        load_aggregate=lambda: {"schema_version": 2, "generation": 1, "rows": []},
        preview_aggregate=lambda: {
            "schema_version": 2,
            "generation": 1,
            "rows": expected_rows,
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: "gh_sase-org__sase",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links.ArtifactLinkStore.from_sdd_store",
        lambda _store, _project_key: adapter,
    )

    check = _check_artifact_links_aggregate(_context(tmp_path))

    assert check.status == "ERROR"
    assert check.data["missing_rows"] == 2
    assert check.data["projected_rows"] == 1
    assert check.data["missing_by_relation"] == {"cites": 1, "launched": 1}
    assert "missing 2 row(s)" in str(check.next_steps)
    assert "cites: 1" in str(check.next_steps)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_sidecar_clone(repo: Path, *, relpath: str = "202609/example.md") -> Path:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "sase-test@example.com")
    _git(repo, "config", "user.name", "SASE Test")
    _git(repo, "config", "commit.gpgsign", "false")
    index = repo / "links" / f"{relpath}.json"
    index.parent.mkdir(parents=True)
    index.write_text("{}\n", encoding="utf-8")
    (repo / "README.md").write_text("# research\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed link index")
    return index


def _primary_store(primary: Path, research: Path) -> SddStore:
    plans = primary / "sase" / "repos" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    return SddStore(
        "sidecar_repos",
        plans,
        plans,
        sidecar_dirs={"research": research},
    )


def test_primary_sidecar_link_dirt_skips_without_store(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_primary_sidecar_store",
        lambda _context: None,
    )
    check = _check_primary_sidecar_link_dirt(_context(tmp_path))
    assert check.status == "SKIP"
    assert "no primary sidecar store" in check.summary


def test_primary_sidecar_link_dirt_ok_when_clean(monkeypatch, tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    research = primary / "sase" / "repos" / "research"
    _init_sidecar_clone(research)
    store = _primary_store(primary, research)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_primary_sidecar_store",
        lambda _context: (primary, store),
    )

    check = _check_primary_sidecar_link_dirt(_context(tmp_path))

    assert _collect_primary_sidecar_link_dirt(primary, store) == ()
    assert check.status == "OK"
    assert check.data["dirty_clones"] == 0


def test_primary_sidecar_link_dirt_errors_on_stranded_deletions(
    monkeypatch, tmp_path: Path
) -> None:
    primary = tmp_path / "primary"
    research = primary / "sase" / "repos" / "research"
    index = _init_sidecar_clone(research)
    index.unlink()
    store = _primary_store(primary, research)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_primary_sidecar_store",
        lambda _context: (primary, store),
    )

    check = _check_primary_sidecar_link_dirt(_context(tmp_path))

    assert check.status == "ERROR"
    assert check.data["restorable_deletions"] == 1
    assert "blocks auto-sync" in check.summary
    assert any("sase doctor -R" in step for step in check.next_steps)
    assert any("git -C" in step and "restore" in step for step in check.next_steps)
    assert any("links/202609/example.md.json" in detail for detail in check.details)


def test_primary_sidecar_link_dirt_ignores_non_links_changes(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    research = primary / "sase" / "repos" / "research"
    _init_sidecar_clone(research)
    (research / "README.md").write_text("# dirty\n", encoding="utf-8")
    store = _primary_store(primary, research)

    assert _collect_primary_sidecar_link_dirt(primary, store) == ()


def test_primary_sidecar_link_dirt_ignores_clones_outside_primary(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    hidden = tmp_path / "hidden" / "research"
    index = _init_sidecar_clone(hidden)
    index.unlink()
    store = _primary_store(primary, hidden)

    assert _collect_primary_sidecar_link_dirt(primary, store) == ()


def test_primary_sidecar_link_dirt_flags_untracked_links_but_does_not_restore(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    research = primary / "sase" / "repos" / "research"
    _init_sidecar_clone(research)
    extra = research / "links" / "202609" / "extra.md.json"
    extra.write_text("{}\n", encoding="utf-8")
    store = _primary_store(primary, research)

    dirt = _collect_primary_sidecar_link_dirt(primary, store)

    assert len(dirt) == 1
    assert dirt[0].path == "links/202609/extra.md.json"
    assert dirt[0].restorable is False
    results = apply_primary_sidecar_link_dirt_repairs(dirt)
    assert results == ()
    assert extra.is_file()


def test_primary_sidecar_link_dirt_restore_replays_deletions_without_commit(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    research = primary / "sase" / "repos" / "research"
    index = _init_sidecar_clone(research)
    index.unlink()
    store = _primary_store(primary, research)
    dirt = _collect_primary_sidecar_link_dirt(primary, store)
    assert len(dirt) == 1
    assert dirt[0].restorable is True
    head_before = _git(research, "rev-parse", "HEAD").stdout.strip()

    results = apply_primary_sidecar_link_dirt_repairs(dirt)

    assert results[0].error is None
    assert results[0].restored == ("links/202609/example.md.json",)
    assert index.is_file()
    status = _git(research, "status", "--porcelain")
    assert status.stdout.strip() == ""
    head_after = _git(research, "rev-parse", "HEAD").stdout.strip()
    assert head_after == head_before
