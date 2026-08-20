"""Tests for the project-aware snippet catalog loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.content_layout import resolve_project_config_write_path
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.snippet.catalog import load_snippet_catalog
from sase.snippet.lookup import SnippetLookupError, lookup_snippet
from sase.xprompt import glossary_catalog as catalog_mod
from sase.xprompt.models import XPrompt


def _record(
    project_name: str, workspace: Path, *, display_name: str
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
        aliases=["demo"],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def _install_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    snippets: str,
    key: str = "gh_demo__app",
    display_name: str = "demo",
) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    config_path = resolve_project_config_write_path(workspace)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"ace:\n  snippets:\n{snippets}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        catalog_mod,
        "list_project_records",
        lambda *_a, **_k: [_record(key, workspace, display_name=display_name)],
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return config_path


def test_catalog_loads_named_project_without_changing_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(
        tmp_path,
        monkeypatch,
        snippets="    todo: |-\n      TODO($1)$0\n",
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )

    catalog = load_snippet_catalog("demo")

    assert Path.cwd() == tmp_path / "elsewhere"
    assert catalog.context.name == "demo"
    assert catalog.entries[0].trigger == "todo"
    assert catalog.entries[0].origin.kind == "project"
    assert catalog.entries[0].origin.path == str(config_path)
    assert catalog.composed_templates["todo"].startswith("TODO")
    assert catalog.composed.alias_provenance["Todo"] == "todo"


def test_config_overrides_xprompt_and_keeps_shadowed_contribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(
        tmp_path,
        monkeypatch,
        snippets="    shared: |-\n      from config$0\n",
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {
            "shared": XPrompt(
                name="shared",
                content="from xprompt",
                snippet=True,
                source_path="xprompts/shared.md",
            )
        },
    )

    catalog = load_snippet_catalog("demo")
    entry = catalog.entry_for("shared")

    assert entry is not None
    assert entry.raw_template == "from config$0"
    assert entry.origin.kind == "project"
    assert entry.contributions[0].kind == "xprompt"
    assert entry.contributions[0].shadowed_by == str(entry.origin.path)
    assert entry.contributions[-1].shadowed_by is None


def test_invalid_layer_is_diagnostic_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = resolve_project_config_write_path(workspace)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("ace: [not, a, mapping]\n", encoding="utf-8")
    monkeypatch.setattr(
        catalog_mod,
        "list_project_records",
        lambda *_a, **_k: [_record("gh_demo__app", workspace, display_name="demo")],
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )

    catalog = load_snippet_catalog("demo")

    assert catalog.entries == ()
    assert any(
        "ace must be a YAML mapping" in item.message
        for item in catalog.layer_diagnostics
    )


def test_lookup_exact_alias_and_unique_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(
        tmp_path,
        monkeypatch,
        snippets=("    helper: |\n      help$0\n    wrap: |\n      #[helper]$0\n"),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )
    catalog = load_snippet_catalog("demo")

    assert lookup_snippet(catalog, "helper").trigger == "helper"
    assert lookup_snippet(catalog, "Helper").trigger == "helper"
    assert lookup_snippet(catalog, "wr").trigger == "wrap"
    with pytest.raises(SnippetLookupError, match="unknown snippet trigger"):
        lookup_snippet(catalog, "missing")


def test_lookup_ambiguous_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(
        tmp_path,
        monkeypatch,
        snippets="    foo: |\n      F$0\n    food: |\n      D$0\n",
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )
    catalog = load_snippet_catalog("demo")

    with pytest.raises(SnippetLookupError, match="did you mean"):
        lookup_snippet(catalog, "fo")


def test_relations_and_cycle_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(
        tmp_path,
        monkeypatch,
        snippets=(
            "    outer: |\n      #[missing]$0\n    selfish: |\n      #[selfish]$0\n"
        ),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )
    catalog = load_snippet_catalog("demo")
    outer = catalog.entry_for("outer")
    selfish = catalog.entry_for("selfish")

    assert outer is not None
    assert outer.relations.calls[0].status == "missing"
    assert selfish is not None
    assert selfish.relations.calls[0].status == "cycle"
    codes = {item.code for item in catalog.composed.diagnostics}
    assert "missing_target" in codes
    assert "direct_cycle" in codes
