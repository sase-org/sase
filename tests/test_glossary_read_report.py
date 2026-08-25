"""Tests for deferred legacy glossary-read Markdown reports."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.memory.legacy_glossary_read_log import (
    GLOSSARY_READ_LOG_SCHEMA_VERSION,
    GlossaryReadEvent,
)
from sase.memory.legacy_glossary_read_report import (
    GlossaryReadReportSpec,
    _build_glossary_read_report,
    glossary_read_report_path,
    write_glossary_read_report,
)
from sase.xprompt._glossary_catalog_projects import EditorGlossaryProject
from sase.xprompt.glossary_catalog import (
    EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION,
    EditorGlossaryCatalog,
    EditorGlossaryCatalogResult,
)


class _Signature:
    def to_wire(self) -> dict[str, object]:
        return {}


def _event(**overrides: object) -> GlossaryReadEvent:
    payload: dict[str, object] = {
        "schema_version": GLOSSARY_READ_LOG_SCHEMA_VERSION,
        "id": "abc123",
        "timestamp": "2026-05-23T12:00:00+00:00",
        "project": "demo",
        "cwd": "/repo",
        "agent_name": "agent-a",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": "/tmp/artifacts",
        "reason": "needed the hood/agent distinction",
        "terms": ("Alpha",),
        "related_terms": (),
        "depth_limit": None,
        "definition_bytes": 42,
        "source_path": "/repo/sase/memory/glossary/alpha.md",
    }
    payload.update(overrides)
    return GlossaryReadEvent(**payload)  # type: ignore[arg-type]


def _spec(
    event: GlossaryReadEvent | None = None, report_path: str = "/tmp/r.md"
) -> GlossaryReadReportSpec:
    return GlossaryReadReportSpec(
        event=event or _event(),
        agent_label=None,
        report_path=report_path,
    )


def _catalog_result(*terms: str) -> EditorGlossaryCatalogResult:
    entries = tuple(
        GlossaryEntry(
            index=index,
            term=term,
            normalized_term=term.casefold(),
            definition=f"{term} definition.",
            configured_aliases=(),
            display_aliases=(),
            effective_aliases=(term,),
            source=None,
        )
        for index, term in enumerate(terms)
    )
    project = EditorGlossaryProject(
        key="demo",
        name="Demo",
        aliases=(),
        workspace_dir=Path("/repo"),
    )
    return EditorGlossaryCatalogResult(
        project=project,
        catalog=EditorGlossaryCatalog(
            schema_version=EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION,
            project=project,
            config_path=Path("/repo/sase/memory/glossary"),
            config_signature=_Signature(),  # type: ignore[arg-type]
            catalog=GlossaryCatalog(schema_version=1, entries=entries),
            compiled=None,  # type: ignore[arg-type]
        ),
    )


def test_report_path_is_deterministic_and_project_state_scoped(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    first = glossary_read_report_path(_event())
    second = glossary_read_report_path(_event())

    assert first == second
    assert Path(first).parent == tmp_path / ".sase" / "glossary_read_reports"


def test_build_report_uses_memory_read_reproduction(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project",
        lambda _project: _catalog_result("Alpha"),
    )

    report = _build_glossary_read_report(_spec())

    assert (
        "sase memory read glossary:Alpha -r 'needed the hood/agent distinction'"
        in report
    )
    assert "## Output" in report
    assert "# Alpha" in report


def test_build_report_records_catalog_resolution_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project",
        lambda _project: EditorGlossaryCatalogResult(
            project=None,
            catalog=None,
            diagnostics=("no such project",),
        ),
    )

    report = _build_glossary_read_report(_spec())

    assert "Could not resolve this project's glossary: no such project" in report


def test_build_report_records_unknown_current_term(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project",
        lambda _project: _catalog_result("Delta"),
    )

    report = _build_glossary_read_report(_spec())

    assert "Could not re-resolve the glossary closure:" in report
    assert "unknown glossary term: Alpha" in report


def test_write_report_prunes_old_reports(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project",
        lambda _project: _catalog_result("Alpha"),
    )
    event = _event()
    path = glossary_read_report_path(event)

    assert write_glossary_read_report(_spec(event, report_path=path)) == path

    for index in range(55):
        extra = replace(
            event,
            id=f"extra-{index}",
            timestamp=f"2026-05-23T12:{index:02d}:00+00:00",
        )
        extra_path = glossary_read_report_path(extra)
        assert (
            write_glossary_read_report(_spec(extra, report_path=extra_path))
            == extra_path
        )

    report_dir = tmp_path / ".sase" / "glossary_read_reports"
    assert len(list(report_dir.glob("*.md"))) == 50
