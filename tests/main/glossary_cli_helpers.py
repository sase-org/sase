"""Shared fixtures for ``sase glossary`` CLI handler tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.content_layout import resolve_project_config_write_path
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.glossary.cli_common import ResolvedGlossaryProject
from sase.glossary.mutation import GlossaryMutationOutcome
from sase.xprompt import glossary_catalog as catalog_mod


class FakeCompiledGlossaryCatalog:
    """A fake compiled matcher keyed by exact definition text."""

    def __init__(
        self, spans_by_definition: dict[str, tuple[dict[str, Any], ...]]
    ) -> None:
        self._spans_by_definition = spans_by_definition

    def scan(self, text: str) -> list[dict[str, Any]]:
        return list(self._spans_by_definition.get(text, ()))


def glossary_entry(
    index: int,
    term: str,
    definition: str = "Definition.",
    *,
    aliases: tuple[str, ...] = (),
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=aliases,
        display_aliases=aliases,
        effective_aliases=(term, *aliases),
        source={"config_path": "sase/sase.yml"},
    )


def glossary_span(
    entry_index: int, matched_text: str, *, start: int = 0
) -> dict[str, Any]:
    end = start + len(matched_text)
    return {
        "term": matched_text,
        "entry_index": entry_index,
        "alias_index": 0,
        "alias": matched_text,
        "matched_text": matched_text,
        "byte_start": start,
        "byte_end": end,
        "range": {
            "start": {"line": 0, "character": start},
            "end": {"line": 0, "character": end},
        },
        "segments": [
            {
                "byte_start": start,
                "byte_end": end,
                "range": {
                    "start": {"line": 0, "character": start},
                    "end": {"line": 0, "character": end},
                },
            }
        ],
    }


def resolved_glossary_project(
    *,
    project_name: str = "sase",
    entries: tuple[GlossaryEntry, ...],
    compiled: FakeCompiledGlossaryCatalog | None = None,
) -> ResolvedGlossaryProject:
    return ResolvedGlossaryProject(
        project_name=project_name,
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=compiled or FakeCompiledGlossaryCatalog({}),
        config_path="/tmp/sase/sase/sase.yml",
    )


def diamond_resolved_glossary_project() -> ResolvedGlossaryProject:
    alpha = glossary_entry(0, "Alpha", "Mentions Beta then Gamma.")
    beta = glossary_entry(1, "Beta", "Mentions Delta.", aliases=("B",))
    gamma = glossary_entry(2, "Gamma", "Mentions Delta.")
    delta = glossary_entry(3, "Delta", "A leaf.")
    compiled = FakeCompiledGlossaryCatalog(
        {
            alpha.definition: (
                glossary_span(1, "Beta", start=9),
                glossary_span(2, "Gamma", start=19),
            ),
            beta.definition: (glossary_span(3, "Delta", start=9),),
            gamma.definition: (glossary_span(3, "Delta", start=9),),
        }
    )
    return resolved_glossary_project(
        entries=(alpha, beta, gamma, delta), compiled=compiled
    )


def mutation_outcome(
    *,
    project_name: str = "demo",
    config_path: str = "/tmp/demo/sase/sase.yml",
    workspace_dir: str = "/tmp/demo",
    term: str = "Widget Box",
    aliases: tuple[str, ...] = ("box",),
    definition: str = "A container for widgets.",
    created_section: bool = False,
    restore_command: str = (
        "sase glossary add 'Widget Box' 'A container for widgets.' -a box -p demo"
    ),
    referenced_by: tuple[str, ...] = (),
) -> GlossaryMutationOutcome:
    return GlossaryMutationOutcome(
        project_name=project_name,
        config_path=config_path,
        workspace_dir=workspace_dir,
        term=term,
        aliases=aliases,
        definition=definition,
        created_section=created_section,
        restore_command=restore_command,
        referenced_by=referenced_by,
    )


_SORTED_GLOSSARY = """# keep this comment
timezone: UTC  # tz
memory:
  h1_title: Demo
  glossary:
    Alpha:
      definition: >-
        First term stands alone.
    Gamma:
      aliases:
        - g
      definition: >-
        Third term mentions Alpha.
"""


def install_writable_glossary_project(
    tmp_path: Path,
    monkeypatch: Any,
    body: str | None = _SORTED_GLOSSARY,
    *,
    display_name: str = "demo",
) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    config_path = resolve_project_config_write_path(workspace)
    if body is not None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(body, encoding="utf-8")
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
    return config_path
