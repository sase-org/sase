"""Finish regressions for the research commit guard (tale sase-1tj)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from sase._repo_inventory_models import RepoCloneRecord, RepoRecord


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(path: Path, tracked_name: str = "tracked.txt") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    (path / tracked_name).write_text("base\n", encoding="utf-8")
    _git("add", tracked_name, cwd=path)
    _git("commit", "-m", "init", cwd=path)
    return path


def _fake_record(
    name: str,
    project: str = "sase",
    project_key: str = "gh_sase-org__sase",
    own: Path | None = None,
    other: Path | None = None,
    remote_url: str | None = None,
    kind: str = "sidecar",
) -> RepoRecord:
    clones: list[RepoCloneRecord] = []
    if own is not None:
        clones.append(RepoCloneRecord(workspace_num=1, path=str(own), exists=True))
    if other is not None:
        clones.append(RepoCloneRecord(workspace_num=0, path=str(other), exists=True))
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project=project,
        project_key=project_key,
        path=str(other or own or ""),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=tuple(clones),
        remote_url=remote_url,
    )


def _primary_record(path: Path, project: str, project_key: str) -> RepoRecord:
    return RepoRecord(
        name=project,
        kind="primary",
        project=project,
        project_key=project_key,
        path=str(path),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=(),
    )


def test_duplicate_name_dirty_shadowed_reports_b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both A and B dirty: B is shadowed, so its write must warn."""

    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    repo_a = _init_repo(tmp_path / "a")
    repo_b = _init_repo(tmp_path / "b")
    stray_a = repo_a / "report.md"
    stray_a.write_text("# a\n", encoding="utf-8")
    stray_b = repo_b / "202611" / "report.md"
    stray_b.parent.mkdir(parents=True, exist_ok=True)
    stray_b.write_text("# b\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv(
        "SASE_LINKED_REPOS_JSON",
        json.dumps([{"name": "research", "workspace_dir": str(repo_b)}]),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "1")

    from sase._linked_repo_markers import record_opened_linked_repo

    record_opened_linked_repo("research", str(repo_a), reason="test", opened_at="now")

    from sase import repo_inventory as inventory_module

    record = _fake_record("research", own=tmp_path / "opened", other=repo_b)

    class _Inventory:
        records = (record,)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(stray_b),), include_run_paths=False
    )
    assert len(entries) == 1
    assert entries[0]["checkout"] == str(repo_b.resolve(strict=False))


def test_duplicate_name_clean_fallback_covers_b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean leaves the configured fallback eligible, so B stays covered."""

    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    repo_a = _init_repo(tmp_path / "a")
    repo_b = _init_repo(tmp_path / "b")
    stray_b = repo_b / "report.md"
    stray_b.write_text("# b\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv(
        "SASE_LINKED_REPOS_JSON",
        json.dumps([{"name": "research", "workspace_dir": str(repo_b)}]),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "1")

    from sase._linked_repo_markers import record_opened_linked_repo

    record_opened_linked_repo("research", str(repo_a), reason="test", opened_at="now")

    from sase import repo_inventory as inventory_module

    record = _fake_record("research", own=tmp_path / "opened", other=repo_b)

    class _Inventory:
        records = (record,)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(stray_b),), include_run_paths=False
    )
    assert entries == ()


def test_name_only_open_resolves_through_configured_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name-only open resolves through the sibling target and stays covered."""

    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    repo_b = _init_repo(tmp_path / "b")
    stray = repo_b / "report.md"
    stray.write_text("# b\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv(
        "SASE_LINKED_REPOS_JSON",
        json.dumps([{"name": "research", "workspace_dir": str(repo_b)}]),
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    # Name-only open: the recorded workspace dir is empty, so the configured
    # target resolves it. (Installed directly because the marker helper
    # resolves "" to the cwd.)
    import sase.llm_provider.commit_finalizer_state._repository_candidates as candidates_mod

    monkeypatch.setattr(
        candidates_mod, "opened_linked_repo_names", lambda _root: {"research"}
    )
    monkeypatch.setattr(
        candidates_mod,
        "opened_linked_repo_workspace_dirs",
        lambda _root: {"research": ""},
    )

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(stray),), include_run_paths=False
    )
    # The write sits in the resolved configured checkout, which the finalizer
    # scans, so no warning is expected. If the name-only open failed to
    # resolve, the checkout would be uncovered and this would be flagged.
    assert entries == ()


def test_normalized_duplicate_paths_dedupe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Symlinked ancestors canonicalize to one checkout, not two."""

    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    real = _init_repo(tmp_path / "real")
    stray = real / "report.md"
    stray.write_text("# x\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    # Pass the same checkout through a non-canonical spelling; the guard must
    # not treat it as a second checkout.
    redundant = f"{real}/./report.md"
    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(redundant,), include_run_paths=False
    )
    # The checkout is unopened, so it is flagged once, not twice.
    assert len(entries) == 1
    assert entries[0]["checkout"] == str(real.resolve(strict=False))


def test_cross_project_research_uses_external_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same-named research in another project never uses a bare open."""

    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    bob_research = _init_repo(tmp_path / "bob-research")
    stray = bob_research / "202611" / "report.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("# bob\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT_WORKSPACE_NUM", "0")

    sase_primary = _primary_record(main, "sase", "gh_sase-org__sase")
    sase_research = _fake_record(
        "research",
        project="sase",
        project_key="gh_sase-org__sase",
        own=tmp_path / "sase-ws1-research",
        other=tmp_path / "sase-primary-research",
        remote_url="git@github.com:sase-org/sase--research.git",
    )
    bob_research_record = RepoRecord(
        name="research",
        kind="sidecar",
        project="bob-cli",
        project_key="gh_bobs-org__bob-cli",
        path=str(bob_research),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=(RepoCloneRecord(workspace_num=0, path=str(bob_research), exists=True),),
        remote_url="git@github.com:bobs-org/bob-cli--research.git",
    )

    from sase import repo_inventory as inventory_module

    class _Inventory:
        records = (sase_primary, sase_research, bob_research_record)
        issues = ()

    monkeypatch.setattr(
        inventory_module, "collect_repo_inventory", lambda *a, **k: _Inventory()
    )

    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(stray),), include_run_paths=False
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry["repo_name"] == "research"
    assert entry["action"] == "open_and_move"
    assert "gh:bobs-org/bob-cli--research" in str(entry["instruction"])
    assert "sase repo open research`" not in str(entry["instruction"])
    assert entry.get("target") == "gh:bobs-org/bob-cli--research"


def test_existing_non_git_path_drops_without_raising(
    tmp_path: Path,
) -> None:
    """An existing file outside any work tree exercises real git failure."""

    from sase.llm_provider.commit_finalizer_state._unscanned_writes import (
        find_unscanned_writes,
    )

    main = _init_repo(tmp_path / "main")
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    entries = find_unscanned_writes(
        str(main), artifacts, extra_paths=(str(outside),), include_run_paths=False
    )
    assert entries == ()


def test_rust_binding_round_trip() -> None:
    """The shared Rust policy is reachable through its Python binding."""

    from sase.core.unscanned_writes_facade import (
        UNSCANNED_WIRE_SCHEMA_VERSION,
        select_unscanned_coverage,
        suggest_unscanned_repair,
        unscanned_wire_schema_version,
    )

    assert unscanned_wire_schema_version() == UNSCANNED_WIRE_SCHEMA_VERSION
    coverage = select_unscanned_coverage(
        {
            "schema_version": 1,
            "candidates": [
                {"name": "research", "path": "/a", "kind": "sibling"},
                {"name": "research", "path": "/b", "kind": "sibling"},
            ],
            "dirty_paths": ["/a", "/b"],
            "known_sdd_paths": [],
        }
    )
    assert coverage["covered_paths"] == ["/a"]
    repair = suggest_unscanned_repair(
        {
            "schema_version": 1,
            "toplevel": "/bob",
            "relpath": "202611/report.md",
            "current_project": "sase",
            "current_project_key": "gh_sase-org__sase",
            "workspace_num": 0,
            "records": [
                {
                    "name": "research",
                    "project": "bob-cli",
                    "project_key": "gh_bobs-org__bob-cli",
                    "path": "/bob",
                    "clones": [{"workspace_num": 0, "path": "/bob"}],
                    "remote_url": "git@github.com:bobs-org/bob-cli--research.git",
                }
            ],
        }
    )
    assert repair["action"] == "open_and_move"
    assert "gh:bobs-org/bob-cli--research" in repair["instruction"]
