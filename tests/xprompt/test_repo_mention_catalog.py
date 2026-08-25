"""Tests for the project-scoped repo-mention catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.repo_inventory import RepoInventory, RepoKind, RepoRecord
from sase.xprompt import glossary_catalog
from sase.xprompt import repo_mention_catalog as catalog


def _record(
    project_name: str,
    workspace: Path,
    *,
    aliases: list[str] | None = None,
    display_name: str | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def _repo_record(
    name: str,
    kind: RepoKind,
    path: str = "/tmp/repo",
    *,
    slug: str | None = None,
    description: str | None = None,
) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,
        project="sase",
        project_key="sase",
        path=path,
        exists=True,
        auto_clone=False,
        description=description,
        source="test",
        env_name=None,
        slug=slug,
    )


def _write_config(workspace: Path, body: str) -> Path:
    config_path = workspace / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(body, encoding="utf-8")
    return config_path


def _write_glossary_web(workspace: Path, *, term: str, slug: str) -> Path:
    """Write a minimal ``glossary`` memory web claiming *term* and return it."""
    descriptor = workspace / "sase" / "memory" / "glossary.md"
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "web: true\n"
        "roster: inline\n"
        "roster_label: GLOSSARY TERMS\n"
        "---\n\n"
        "Glossary descriptor.\n",
        encoding="utf-8",
    )
    strand_path = descriptor.parent / "glossary" / f"{slug}.md"
    strand_path.parent.mkdir(parents=True, exist_ok=True)
    strand_path.write_text(
        f"---\nkeyword: {term}\n---\n\nThe core crate.\n",
        encoding="utf-8",
    )
    return strand_path


def _write_marker(
    checkout: Path,
    *,
    primary_workspace_dir: str | Path,
    project_name: str = "sase",
    project_key: str = "sase-org/sase",
) -> Path:
    marker_dir = checkout / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / "checkout.json"
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": project_name,
                "project_key": project_key,
                "workspace_num": 7,
                "primary_workspace_dir": str(primary_workspace_dir),
                "registry_path": str(checkout / "registry.json"),
            }
        ),
        encoding="utf-8",
    )
    return marker_path


def _setup_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config_body: str = "",
    glossary_term: str | None = None,
) -> Path:
    workspace = tmp_path / "sase-workspace"
    workspace.mkdir()
    if config_body:
        _write_config(workspace, config_body)
    if glossary_term:
        _write_glossary_web(
            workspace, term=glossary_term, slug=glossary_term.casefold()
        )
    record = _record("sase", workspace)
    monkeypatch.setattr(
        glossary_catalog, "list_project_records", lambda *_a, **_kw: [record]
    )
    return workspace


def _load_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    records: tuple[RepoRecord, ...],
    *,
    config_body: str = "",
    glossary_term: str | None = None,
) -> catalog.EditorRepoMentionCatalogResult:
    _setup_project(
        tmp_path, monkeypatch, config_body=config_body, glossary_term=glossary_term
    )
    monkeypatch.setattr(
        catalog,
        "collect_repo_inventory",
        lambda *_a, **_kw: RepoInventory(records),
    )
    return catalog.editor_repo_mention_catalog_for_project("sase")


def test_sidecar_slug_admitted_bare_role_not_and_primary_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (
        _repo_record("sase", "primary"),
        _repo_record("beads", "sidecar", slug="sase--beads"),
        _repo_record("sase-core", "linked"),
        _repo_record("gh:bbugyi200/bugyi-chops", "external"),
    )

    result = _load_catalog(tmp_path, monkeypatch, records)

    assert result.ok
    assert result.catalog is not None
    identifiers = {mention.identifier for mention in result.catalog.mentions}
    assert identifiers == {"sase--beads", "sase-core", "gh:bbugyi200/bugyi-chops"}
    kinds = {mention.identifier: mention.kind for mention in result.catalog.mentions}
    assert kinds["sase--beads"] == "sidecar"
    assert kinds["sase-core"] == "linked"
    assert kinds["gh:bbugyi200/bugyi-chops"] == "external"

    assert catalog.scan_repo_mentions(result.catalog, "beads alone") == ()
    matches = catalog.scan_repo_mentions(result.catalog, "clone sase--beads today")
    assert [span.matched_text for span in matches] == ["sase--beads"]


def test_catalog_resolves_numbered_workspace_via_checkout_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    launch = tmp_path / "state" / "sase_7"
    launch.mkdir(parents=True)
    _write_marker(launch, primary_workspace_dir=primary)
    record = _record("sase", primary)
    monkeypatch.setattr(
        glossary_catalog, "list_project_records", lambda *_a, **_kw: [record]
    )
    monkeypatch.setattr(
        catalog,
        "collect_repo_inventory",
        lambda *_a, **_kw: RepoInventory((_repo_record("sase-core", "linked"),)),
    )

    result = catalog.editor_repo_mention_catalog_for_project(
        None,
        launch_workspace=launch,
    )

    assert result.ok
    assert result.project is not None
    assert result.project.key == "sase"
    assert result.catalog is not None
    assert {mention.identifier for mention in result.catalog.mentions} == {"sase-core"}


def test_no_admitted_records_returns_no_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (_repo_record("sase", "primary"),)

    result = _load_catalog(tmp_path, monkeypatch, records)

    assert result.catalog is None
    assert result.diagnostics == ()


def test_glossary_claimed_name_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (
        _repo_record("sase-core", "linked"),
        _repo_record("other-repo", "linked"),
    )

    result = _load_catalog(tmp_path, monkeypatch, records, glossary_term="sase-core")

    assert result.ok
    assert result.catalog is not None
    identifiers = {mention.identifier for mention in result.catalog.mentions}
    assert identifiers == {"other-repo"}


def test_no_description_gets_synthesized_definition() -> None:
    record = _repo_record(
        "sase-core", "linked", path="/repos/sase-core", description=None
    )
    assert (
        catalog.synthesized_repo_description(record)
        == "Linked repository at /repos/sase-core."
    )

    described = _repo_record(
        "sase-core", "linked", path="/repos/sase-core", description="The core crate."
    )
    assert catalog.synthesized_repo_description(described) == "The core crate."


def test_load_succeeds_without_description(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (_repo_record("sase-core", "linked", description=None),)

    result = _load_catalog(tmp_path, monkeypatch, records)

    assert result.ok


def test_word_boundary_and_case_insensitive_matching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (
        _repo_record("sase-core", "linked"),
        _repo_record("chezmoi", "linked"),
    )

    result = _load_catalog(tmp_path, monkeypatch, records)
    assert result.catalog is not None
    compiled = result.catalog

    assert catalog.scan_repo_mentions(compiled, "Rebuild sase-core-extras today.") == ()
    hits = catalog.scan_repo_mentions(compiled, "Rebuild sase-core.")
    assert [span.matched_text for span in hits] == ["sase-core"]
    hits = catalog.scan_repo_mentions(compiled, "Sase-Core matched case-insensitively")
    assert [span.matched_text for span in hits] == ["Sase-Core"]


def test_derived_plural_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (_repo_record("chezmoi", "linked"),)

    result = _load_catalog(tmp_path, monkeypatch, records)
    assert result.catalog is not None

    assert catalog.scan_repo_mentions(result.catalog, "chezmois plural") == ()
    hits = catalog.scan_repo_mentions(result.catalog, "chezmoi singular")
    assert [span.matched_text for span in hits] == ["chezmoi"]


def test_path_adjacency_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (_repo_record("sase-core", "linked"),)

    result = _load_catalog(tmp_path, monkeypatch, records)
    assert result.catalog is not None
    compiled = result.catalog

    assert catalog.scan_repo_mentions(compiled, "../sase-core is a path") == ()
    assert catalog.scan_repo_mentions(compiled, "sase/repos/linked/sase-core") == ()
    assert catalog.scan_repo_mentions(compiled, "sase-core/crates has stuff") == ()
    hits = catalog.scan_repo_mentions(compiled, "Rebuild sase-core.")
    assert [span.matched_text for span in hits] == ["sase-core"]


def test_fenced_and_inline_code_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (_repo_record("sase-core", "linked"),)

    result = _load_catalog(tmp_path, monkeypatch, records)
    assert result.catalog is not None

    text = (
        "Use `sase-core` inline.\n\n```\nsase-core fenced\n```\n\nRebuild sase-core.\n"
    )
    hits = catalog.scan_repo_mentions(result.catalog, text)
    assert len(hits) == 1
    assert hits[0].matched_text == "sase-core"


def test_declaration_line_col_resolved_for_linked_and_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_body = """repos:
  linked:
    - name: sase-core
      path: ../sase-core
  sidecar:
    custom:
      research:
        description: Research repo.
"""
    records = (
        _repo_record("sase-core", "linked"),
        _repo_record("research", "sidecar", slug="sase--research"),
        _repo_record("gh:bbugyi200/bugyi-chops", "external"),
    )

    result = _load_catalog(tmp_path, monkeypatch, records, config_body=config_body)
    assert result.catalog is not None

    by_identifier = {mention.identifier: mention for mention in result.catalog.mentions}
    linked_mention = by_identifier["sase-core"]
    assert linked_mention.config_path is not None
    assert linked_mention.config_path.endswith("sase/sase.yml")
    assert (linked_mention.config_line, linked_mention.config_col) == (3, 7)

    sidecar_mention = by_identifier["sase--research"]
    assert sidecar_mention.config_path is not None
    assert (sidecar_mention.config_line, sidecar_mention.config_col) == (7, 7)

    external_mention = by_identifier["gh:bbugyi200/bugyi-chops"]
    assert external_mention.config_path is None
    assert external_mention.config_line is None
    assert external_mention.config_col is None


def test_inventory_failure_degrades_to_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_project(tmp_path, monkeypatch)

    def _raise(*_a: object, **_kw: object) -> RepoInventory:
        raise RuntimeError("boom")

    monkeypatch.setattr(catalog, "collect_repo_inventory", _raise)

    result = catalog.editor_repo_mention_catalog_for_project("sase")

    assert result.catalog is None
    assert result.diagnostics
    assert "boom" in result.diagnostics[0]


def test_glossary_load_failure_degrades_to_diagnostic_not_hard_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (_repo_record("sase-core", "linked"),)
    _setup_project(tmp_path, monkeypatch)
    monkeypatch.setattr(
        catalog,
        "collect_repo_inventory",
        lambda *_a, **_kw: RepoInventory(records),
    )
    monkeypatch.setattr(
        catalog,
        "editor_glossary_catalog_for_project",
        lambda *_a, **_kw: _FailedGlossaryResult(),
    )

    result = catalog.editor_repo_mention_catalog_for_project("sase")

    assert result.catalog is not None
    identifiers = {mention.identifier for mention in result.catalog.mentions}
    assert identifiers == {"sase-core"}
    assert result.diagnostics
    assert "glossary catalog unavailable" in result.diagnostics[0]


class _FailedGlossaryResult:
    catalog = None
    diagnostics = ("boom: glossary parse failed",)
