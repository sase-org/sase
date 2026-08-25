"""Tests for project-aware editor glossary catalog loading."""

from __future__ import annotations

import json
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
from sase.memory.web.catalog import glossary_source_from_wire
from sase.xprompt import _glossary_catalog_config as catalog_config
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
    monkeypatch.setattr(
        catalog_config, "validate_glossary_entries", lambda _entries: ()
    )
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


def _write_glossary_web(workspace: Path) -> Path:
    """Write a minimal ``glossary`` memory web with one strand and return it."""
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
    strand_path = descriptor.parent / "glossary" / "agent-clan.md"
    strand_path.parent.mkdir(parents=True, exist_ok=True)
    strand_path.write_text(
        "---\nkeyword: Agent Clan\naliases: [clan]\n---\n\nA named container.\n",
        encoding="utf-8",
    )
    return strand_path


def _write_marker(
    checkout: Path,
    *,
    primary_workspace_dir: str | Path = "",
    project_name: str = "sase",
    project_key: str = "sase-org/sase",
    workspace_num: int = 7,
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
                "workspace_num": workspace_num,
                "primary_workspace_dir": str(primary_workspace_dir),
                "registry_path": str(checkout / "registry.json"),
            }
        ),
        encoding="utf-8",
    )
    return marker_path


_ONE_TERM = "memory:\n  glossary:\n    Stitch:\n      definition: A stitch.\n"
_NO_WORKSPACE_MATCH = (
    "no enabled project matched the active workspace; pass -p/--project"
)


def test_glossary_source_from_wire_accepts_v1_source_mapping() -> None:
    source = glossary_source_from_wire(
        {
            "config_path": "/repo/sase/sase.yml",
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
    )

    assert source is not None
    assert source.source_path == "/repo/sase/sase.yml"
    assert source.key_path == ("memory", "glossary", "Agent Clan")
    assert source.keyword_range == {
        "start": {"line": 2, "character": 4},
        "end": {"line": 2, "character": 14},
    }
    assert source.body_range == {
        "start": {"line": 5, "character": 18},
        "end": {"line": 7, "character": 19},
    }


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
        "source_path": str(config_path),
        "key_path": ["memory", "glossary", "Agent Clan"],
        "keyword_range": {
            "start": {"line": 2, "character": 4},
            "end": {"line": 2, "character": 14},
        },
        "body_range": {
            "start": {"line": 5, "character": 18},
            "end": {"line": 7, "character": 19},
        },
        "aliases_range": {
            "start": {"line": 4, "character": 8},
            "end": {"line": 4, "character": 14},
        },
    }


def test_catalog_for_project_prefers_strand_backed_glossary_web(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "sase-workspace"
    workspace.mkdir()
    strand_path = _write_glossary_web(workspace)
    record = _record("sase", workspace)
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project("sase")

    assert result.ok
    assert result.catalog is not None
    assert result.catalog.config_path == strand_path.parent
    assert result.catalog.config_signature.path == str(strand_path.parent)

    entry = result.catalog.entries[0]
    assert entry.term == "Agent Clan"
    assert entry.display_aliases == ("clan",)
    assert entry.source is not None
    assert entry.source["source_path"] == str(strand_path)
    assert entry.source["key_path"] == []
    assert entry.source["keyword_range"]["start"] == {"line": 1, "character": 9}


def test_catalog_for_project_blocks_dual_glossary_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "sase-workspace"
    workspace.mkdir()
    _write_glossary_web(workspace)
    _write_config(workspace, _ONE_TERM)
    record = _record("sase", workspace)
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project("sase")

    assert result.catalog is None
    assert len(result.diagnostics) == 1
    assert "sase memory web migrate glossary" in result.diagnostics[0]


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
    numbered = tmp_path / "state" / "beta_7"
    numbered.mkdir(parents=True)
    _write_marker(
        numbered,
        primary_workspace_dir=beta,
        project_name="beta",
        project_key="beta",
    )
    missing = catalog.editor_glossary_catalog_for_project(
        "missing",
        launch_workspace=numbered,
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
        catalog_config,
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


def test_catalog_resolves_numbered_workspace_via_checkout_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    _write_config(primary, _ONE_TERM)
    launch = tmp_path / "state" / "proj_7"
    launch.mkdir(parents=True)
    _write_marker(launch, primary_workspace_dir=primary)
    record = _record("gh_sase-org__sase", primary, display_name="sase")
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project(
        None,
        launch_workspace=launch,
    )

    assert result.ok
    assert result.project is not None
    assert result.project.key == "gh_sase-org__sase"
    assert result.catalog is not None
    assert result.catalog.entries[0].term == "Stitch"


def test_catalog_resolves_nested_subdirectory_of_numbered_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    _write_config(primary, _ONE_TERM)
    launch = tmp_path / "state" / "proj_7"
    nested = launch / "src" / "sase"
    nested.mkdir(parents=True)
    _write_marker(launch, primary_workspace_dir=primary)
    record = _record("gh_sase-org__sase", primary, display_name="sase")
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project(
        None,
        launch_workspace=nested,
    )

    assert result.ok
    assert result.project is not None
    assert result.project.key == "gh_sase-org__sase"


def test_catalog_resolves_empty_primary_via_marker_project_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    _write_config(primary, _ONE_TERM)
    launch = tmp_path / "state" / "proj_7"
    launch.mkdir(parents=True)
    _write_marker(
        launch,
        primary_workspace_dir="",
        project_name="sase",
        project_key="",
    )
    record = _record("gh_sase-org__sase", primary, display_name="sase")
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project(
        None,
        launch_workspace=launch,
    )

    assert result.ok
    assert result.project is not None
    assert result.project.key == "gh_sase-org__sase"


def test_catalog_resolves_empty_primary_via_marker_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    primary = tmp_path / "projects" / "github" / "foo-org" / "foo"
    primary.mkdir(parents=True)
    _write_config(primary, _ONE_TERM)
    launch = tmp_path / "state" / "proj_7"
    launch.mkdir(parents=True)
    _write_marker(
        launch,
        primary_workspace_dir="",
        project_name="",
        project_key="foo-org/foo",
    )
    record = _record("gh_foo_org__foo", primary)
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project(
        None,
        launch_workspace=launch,
    )

    assert result.ok
    assert result.project is not None
    assert result.project.key == "gh_foo_org__foo"


def test_catalog_leaves_unlisted_marker_project_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed = tmp_path / "listed"
    listed.mkdir()
    _write_config(listed, _ONE_TERM)
    other_primary = tmp_path / "other-primary"
    other_primary.mkdir()
    launch = tmp_path / "state" / "proj_7"
    launch.mkdir(parents=True)
    _write_marker(
        launch,
        primary_workspace_dir=other_primary,
        project_name="ghost",
        project_key="ghost-org/ghost",
    )
    record = _record("listed", listed)
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project(
        None,
        launch_workspace=launch,
    )

    assert result.project is None
    assert result.catalog is None
    assert result.diagnostics == (_NO_WORKSPACE_MATCH,)


def test_catalog_still_resolves_primary_checkout_without_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    _write_config(primary, _ONE_TERM)
    record = _record("gh_sase-org__sase", primary, display_name="sase")
    monkeypatch.setattr(catalog, "list_project_records", lambda *_a, **_kw: [record])

    result = catalog.editor_glossary_catalog_for_project(
        None,
        launch_workspace=primary / "src",
    )

    assert result.ok
    assert result.project is not None
    assert result.project.key == "gh_sase-org__sase"
