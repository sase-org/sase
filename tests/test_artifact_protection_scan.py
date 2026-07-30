from __future__ import annotations

from pathlib import Path

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.core.artifact_file_protection import collect_protected_artifact_ids


def _record(
    name: str,
    path: Path,
    *,
    kind: str = "sidecar",
    exists: bool = True,
) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="sase",
        project_key="gh_sase-org__sase",
        path=str(path),
        exists=exists,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=f"sase--{name}" if kind == "sidecar" else None,
    )


def test_collects_and_normalizes_project_plan_bead_and_research_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    research = tmp_path / "research"
    projects.mkdir()
    plans.mkdir()
    beads.mkdir()
    research.mkdir()
    (projects / "sase.sase").write_text(
        "CL/PR: file:default:111111111111111111111111\n",
        encoding="utf-8",
    )
    (projects / "sase-archive.sase").write_text(
        "COMMENTS: explicit:222222222222222222222222\n",
        encoding="utf-8",
    )
    (plans / "design.md").write_text(
        "default:333333333333333333333333\n",
        encoding="utf-8",
    )
    (beads / "page.md").write_text(
        "file:explicit:444444444444444444444444\n",
        encoding="utf-8",
    )
    (research / "report.txt").write_text(
        "default:555555555555555555555555\n",
        encoding="utf-8",
    )
    git_dir = plans / ".git"
    git_dir.mkdir()
    (git_dir / "ignored.md").write_text(
        "default:aaaaaaaaaaaaaaaaaaaaaaaa\n",
        encoding="utf-8",
    )
    (plans / "ignored.py").write_text(
        "default:bbbbbbbbbbbbbbbbbbbbbbbb\n",
        encoding="utf-8",
    )

    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", beads),
            _record("research", research),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: tmp_path / "missing-consumption.jsonl",
    )

    result = collect_protected_artifact_ids()

    expected = frozenset(
        {
            "default:111111111111111111111111",
            "explicit:222222222222222222222222",
            "default:333333333333333333333333",
            "explicit:444444444444444444444444",
            "default:555555555555555555555555",
        }
    )
    assert result.referenced_ids == expected
    assert result.consumed_ids == frozenset()
    assert result.overlap_ids == frozenset()
    assert result.ids == expected
    assert result.sources_scanned == tuple(
        sorted(map(str, (projects, plans, beads, research)))
    )
    assert result.sources_unavailable == ()


def test_bead_store_projection_protects_refs_without_a_published_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    stored_id = "default:111111111111111111111111"
    detached_id = "explicit:222222222222222222222222"
    (beads / "issues.jsonl").write_text(
        f'{{"id":"sase-1","refs":["file:{stored_id}"]}}\n',
        encoding="utf-8",
    )
    streams = beads / "events" / "streams"
    streams.mkdir(parents=True)
    (streams / "sase-1.jsonl").write_text(
        f'{{"operation":"ReferenceRemoved","reference":"file:{detached_id}"}}\n',
        encoding="utf-8",
    )
    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: tmp_path / "missing-consumption.jsonl",
    )

    result = collect_protected_artifact_ids()

    assert result.referenced_ids == frozenset({stored_id})
    assert detached_id not in result.ids
    assert result.sources_unavailable == ()


def test_bead_store_projection_is_not_scanned_under_other_sidecar_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    (plans / "issues.jsonl").write_text(
        '{"refs":["file:default:333333333333333333333333"]}\n',
        encoding="utf-8",
    )
    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: tmp_path / "missing-consumption.jsonl",
    )

    result = collect_protected_artifact_ids()

    assert result.referenced_ids == frozenset()


def test_missing_required_sidecar_is_unavailable_but_research_is_optional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    projects.mkdir()
    plans.mkdir()
    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", tmp_path / "missing-beads", exists=False),
            _record("research", tmp_path / "missing-research", exists=False),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: tmp_path / "missing-consumption.jsonl",
    )

    result = collect_protected_artifact_ids()

    assert result.sources_unavailable == ("sase:beads",)
    assert "sase:research" not in result.sources_unavailable


def test_consumption_adds_only_canonical_file_ids_and_retains_overlap_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    ledger = tmp_path / "consumption.jsonl"
    for path in (projects, plans, beads):
        path.mkdir()
    ledger.touch()
    overlap_id = "default:111111111111111111111111"
    consumed_only_id = "explicit:222222222222222222222222"
    (projects / "sase.sase").write_text(
        f"COMMENTS: file:{overlap_id}\n",
        encoding="utf-8",
    )
    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: ledger,
    )
    query_calls: list[Path | str | None] = []

    def summarize(*, log_path: Path | str | None = None):  # type: ignore[no-untyped-def]
        query_calls.append(log_path)
        return {
            f"file:{overlap_id}": object(),
            f"file:{consumed_only_id}": object(),
            "plans:202607/report.md": object(),
            f"file:{consumed_only_id}#L2": object(),
            "file:default:AAAAAAAAAAAAAAAAAAAAAAAA": object(),
        }

    monkeypatch.setattr(
        "sase.core.artifact_file_protection.summarize_artifact_consumption",
        summarize,
    )

    result = collect_protected_artifact_ids()

    assert query_calls == [ledger]
    assert result.referenced_ids == frozenset({overlap_id})
    assert result.consumed_ids == frozenset({overlap_id, consumed_only_id})
    assert result.overlap_ids == frozenset({overlap_id})
    assert result.ids == frozenset({overlap_id, consumed_only_id})
    assert str(ledger) in result.sources_scanned
    assert result.sources_unavailable == ()


def test_missing_consumption_ledger_is_an_empty_optional_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    ledger = tmp_path / "missing-consumption.jsonl"
    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: ledger,
    )

    def unexpected_query(**_kwargs: object) -> object:
        raise AssertionError("missing ledgers must not be queried")

    monkeypatch.setattr(
        "sase.core.artifact_file_protection.summarize_artifact_consumption",
        unexpected_query,
    )

    result = collect_protected_artifact_ids()

    assert result.consumed_ids == frozenset()
    assert str(ledger) not in result.sources_scanned
    assert result.sources_unavailable == ()


def test_query_failure_marks_present_consumption_ledger_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    ledger = tmp_path / "consumption.jsonl"
    for path in (projects, plans, beads):
        path.mkdir()
    ledger.touch()
    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: ledger,
    )

    def failing_query(**_kwargs: object) -> object:
        raise RuntimeError("query failed")

    monkeypatch.setattr(
        "sase.core.artifact_file_protection.summarize_artifact_consumption",
        failing_query,
    )

    result = collect_protected_artifact_ids()

    assert result.consumed_ids == frozenset()
    assert str(ledger) not in result.sources_scanned
    assert result.sources_unavailable == (f"{ledger}: query failed",)
