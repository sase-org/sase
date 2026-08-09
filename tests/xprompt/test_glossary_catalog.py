"""Tests for project-aware editor glossary catalog loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.glossary_facade import (
    GlossaryCatalog,
    GlossaryDiagnostic,
    GlossaryEntry,
    GlossaryInputEntry,
    GlossarySource,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.xprompt import glossary_catalog as catalog


def _record(
    project_name: str,
    workspace: Path,
    *,
    aliases: list[str] | None = None,
    display_name: str | None = None,
    state: str = "enabled",
    system_managed: bool = False,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=str(workspace),
        state=state,
        state_explicit=False,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=state == "enabled",
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


@pytest.fixture(autouse=True)
def _fake_glossary_rust(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "validate_glossary_entries", lambda _entries: ())
    monkeypatch.setattr(catalog, "build_glossary_catalog", _fake_build_catalog)
    monkeypatch.setattr(catalog, "compile_glossary_catalog", lambda entries: entries)


def _fake_build_catalog(entries: tuple[GlossaryInputEntry, ...]) -> GlossaryCatalog:
    return GlossaryCatalog(
        schema_version=1,
        entries=tuple(
            GlossaryEntry(
                index=index,
                term=entry.term,
                normalized_term=entry.term.casefold(),
                definition=entry.definition,
                configured_aliases=entry.aliases,
                display_aliases=entry.aliases,
                effective_aliases=(entry.term, *entry.aliases),
                source=_source_wire(entry.source),
            )
            for index, entry in enumerate(entries)
        ),
    )


def _source_wire(
    source: GlossarySource | dict[str, Any] | None,
) -> dict[str, Any] | None:
    if isinstance(source, GlossarySource):
        return source.to_wire()
    return source


def _write_config(workspace: Path, body: str) -> Path:
    config_path = workspace / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(body, encoding="utf-8")
    return config_path


def test_catalog_for_project_uses_project_alias_and_source_ranges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "sase-workspace"
    workspace.mkdir()
    config_path = _write_config(
        workspace,
        """memory:
  glossary:
    Agent Clan:
      aliases:
        - clan
      definition: >-
        A named, rootless container
        for agents.
""",
    )
    record = _record(
        "gh_sase-org__sase",
        workspace,
        aliases=["s"],
        display_name="sase",
    )
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project(
        "s",
        launch_workspace=tmp_path / "other",
    )

    assert result.ok
    assert result.project is not None
    assert result.project.key == "gh_sase-org__sase"
    assert result.catalog is not None
    assert result.catalog.config_path == config_path
    assert result.catalog.config_signature.path == str(config_path)

    entry = result.catalog.entries[0]
    assert entry.term == "Agent Clan"
    assert entry.display_aliases == ("clan",)
    assert entry.effective_aliases == ("Agent Clan", "clan")
    assert entry.source == {
        "config_path": str(config_path),
        "config_key_path": ["memory", "glossary", "Agent Clan"],
        "term_range": {
            "start": {"line": 2, "character": 4},
            "end": {"line": 2, "character": 14},
        },
        "definition_range": {
            "start": {"line": 5, "character": 18},
            "end": {"line": 7, "character": 19},
        },
        "aliases_range": {
            "start": {"line": 4, "character": 8},
            "end": {"line": 4, "character": 14},
        },
    }


def test_catalog_without_ref_uses_launch_workspace_and_never_falls_back_from_bad_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    _write_config(
        alpha,
        "memory:\n  glossary:\n    Alpha Term:\n      definition: Alpha definition.\n",
    )
    _write_config(
        beta,
        "memory:\n  glossary:\n    Beta Term:\n      definition: Beta definition.\n",
    )
    records = [
        _record("alpha", alpha),
        _record("beta", beta, aliases=["docs"]),
    ]
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: records)

    fallback = catalog.editor_glossary_catalog_for_project(
        None,
        launch_workspace=beta / "nested",
    )
    missing = catalog.editor_glossary_catalog_for_project(
        "missing",
        launch_workspace=beta,
    )

    assert fallback.catalog is not None
    assert fallback.project is not None
    assert fallback.project.key == "beta"
    assert fallback.catalog.entries[0].term == "Beta Term"
    assert missing.catalog is None
    assert missing.project is None
    assert "did not resolve to an enabled workspace" in missing.diagnostics[0]


def test_catalog_reports_validation_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = _write_config(
        workspace,
        """memory:
  glossary:
    Agent:
      aliases:
        - worker
      definition: A worker.
    Worker:
      aliases:
        - worker
      definition: Another worker.
""",
    )
    record = _record("sase", workspace)
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])
    monkeypatch.setattr(
        catalog,
        "validate_glossary_entries",
        lambda _entries: (
            GlossaryDiagnostic(
                severity="error",
                code="ambiguous_alias",
                message="alias is claimed by more than one term",
                path="glossary.Worker.aliases[0]",
            ),
        ),
    )

    result = catalog.editor_glossary_catalog_for_project("sase")

    assert result.catalog is None
    assert result.diagnostics == (
        f"{config_path}: memory.glossary.Worker.aliases[0]: "
        "alias is claimed by more than one term",
    )


def test_lsp_payload_materializes_enabled_project_catalogs_and_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beta = tmp_path / "beta"
    alpha = tmp_path / "alpha"
    missing = tmp_path / "missing"
    beta.mkdir()
    alpha.mkdir()
    _write_config(
        beta, "memory:\n  glossary:\n    Beta Term:\n      definition: Beta.\n"
    )
    _write_config(
        alpha,
        "memory:\n  glossary:\n    Alpha Term:\n      definition: Alpha.\n",
    )
    records = [
        _record("beta", beta, aliases=["b"], display_name="Beta"),
        _record("alpha", alpha, display_name="Alpha"),
        _record("missing", missing, display_name="Missing"),
    ]
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: records)

    payload = catalog.editor_glossary_lsp_catalog_payload(
        launch_workspace=beta / "subdir",
    )

    assert payload["schema_version"] == catalog.EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION
    assert payload["default_project"] == "beta"
    projects = payload["projects"]
    assert isinstance(projects, list)
    assert [project["project"]["key"] for project in projects] == ["alpha", "beta"]
    assert projects[1]["project"]["aliases"] == ["b"]
    assert projects[1]["entries"][0]["term"] == "Beta Term"
    assert projects[1]["entries"][0]["display_aliases"] == []
