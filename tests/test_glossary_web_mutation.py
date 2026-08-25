"""Tests for the strand-file glossary add/delete engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.mutation import GlossaryMutationError, GlossaryValidationError
from sase.glossary.resolution import GlossaryLookupError
from sase.glossary.web_mutation import add_glossary_strand, delete_glossary_strand
from sase.memory.web.catalog import find_memory_web
from sase.xprompt import glossary_catalog as catalog_mod

_DESCRIPTOR = (
    "---\n"
    "type: core\n"
    "parent: AGENTS.md\n"
    "web: true\n"
    "roster: inline\n"
    "roster_label: GLOSSARY TERMS\n"
    "---\n\n"
    "Glossary descriptor.\n"
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _strand(
    *, keyword: str = "Alpha", aliases: tuple[str, ...] = (), body: str = "First term."
) -> str:
    alias_line = ""
    if aliases:
        alias_items = "\n".join(f"  - {alias}" for alias in aliases)
        alias_line = f"aliases:\n{alias_items}\n"
    return f"---\nkeyword: {keyword}\n{alias_line}---\n\n{body}\n"


def _install_web_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    strands: dict[str, str] | None = None,
    display_name: str = "demo",
) -> Path:
    workspace = tmp_path / "workspace"
    _write(workspace / "sase" / "memory" / "glossary.md", _DESCRIPTOR)
    for filename, content in (strands or {}).items():
        _write(workspace / "sase" / "memory" / "glossary" / filename, content)
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="gh_demo__app",
        project_dir="/tmp/projects/gh_demo__app",
        project_file="/tmp/projects/gh_demo__app/gh_demo__app.sase",
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )
    monkeypatch.setattr(
        catalog_mod, "list_project_records", lambda *_a, **_kw: [record]
    )
    return workspace


def test_add_writes_strand_file_with_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(
        tmp_path, monkeypatch, strands={"alpha.md": _strand()}
    )
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    outcome = add_glossary_strand(
        "demo", web, "Widget Box", "A container for widgets.", aliases=("box",)
    )

    assert outcome.project_name == "demo"
    assert outcome.term == "Widget Box"
    assert outcome.aliases == ("box",)
    assert outcome.created_section is False
    strand_path = workspace / "sase" / "memory" / "glossary" / "widget-box.md"
    assert outcome.config_path == str(strand_path)
    text = strand_path.read_text(encoding="utf-8")
    assert "keyword: Widget Box" in text
    assert "- box" in text
    assert text.endswith("A container for widgets.\n")


def test_add_omits_aliases_key_when_none_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(tmp_path, monkeypatch)

    web = find_memory_web(workspace, "glossary")
    assert web is not None
    add_glossary_strand("demo", web, "Solo Term", "Stands alone.")

    text = (workspace / "sase" / "memory" / "glossary" / "solo-term.md").read_text(
        encoding="utf-8"
    )
    assert "aliases" not in text


def test_add_rejects_slug_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(
        tmp_path, monkeypatch, strands={"alpha.md": _strand()}
    )
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    with pytest.raises(GlossaryMutationError, match="already exists"):
        add_glossary_strand("demo", web, "Alpha", "A colliding definition.")


def test_add_rejects_alias_collision_via_rust_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(
        tmp_path, monkeypatch, strands={"alpha.md": _strand()}
    )
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    with pytest.raises(GlossaryValidationError):
        add_glossary_strand("demo", web, "Other", "Collides.", aliases=("Alpha",))
    assert not (workspace / "sase" / "memory" / "glossary" / "other.md").exists()


def test_add_rejects_blank_and_malformed_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(tmp_path, monkeypatch)
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    with pytest.raises(GlossaryMutationError, match="nonblank"):
        add_glossary_strand("demo", web, "   ", "A definition.")
    with pytest.raises(GlossaryMutationError, match="single-line"):
        add_glossary_strand("demo", web, "Bad\nTerm", "A definition.")


def test_delete_by_term_removes_strand_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(
        tmp_path,
        monkeypatch,
        strands={
            "alpha.md": _strand(keyword="Alpha", body="Mentions Beta."),
            "beta.md": _strand(keyword="Beta", body="A leaf."),
        },
    )
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    outcome = delete_glossary_strand("demo", web, "Beta")

    assert outcome.term == "Beta"
    assert outcome.referenced_by == ("Alpha",)
    assert "sase glossary add" in outcome.restore_command
    assert not (workspace / "sase" / "memory" / "glossary" / "beta.md").exists()


def test_delete_dry_run_leaves_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(
        tmp_path, monkeypatch, strands={"alpha.md": _strand()}
    )
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    outcome = delete_glossary_strand("demo", web, "Alpha", dry_run=True)

    assert outcome.term == "Alpha"
    assert (workspace / "sase" / "memory" / "glossary" / "alpha.md").exists()


def test_delete_unknown_term_raises_lookup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(
        tmp_path, monkeypatch, strands={"alpha.md": _strand()}
    )
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    with pytest.raises(GlossaryLookupError, match="unknown glossary term: xyzzy"):
        delete_glossary_strand("demo", web, "xyzzy")


def test_add_unknown_project_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _install_web_project(
        tmp_path, monkeypatch, strands={"alpha.md": _strand()}
    )
    web = find_memory_web(workspace, "glossary")
    assert web is not None

    with pytest.raises(GlossaryCliError, match="did not resolve"):
        add_glossary_strand("missing", web, "Term", "A definition.")
