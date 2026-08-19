"""Tests for deferred ``sase glossary read`` Markdown reports."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sase.glossary import read_report as read_report_mod
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.read_log import GLOSSARY_READ_LOG_SCHEMA_VERSION, GlossaryReadEvent
from sase.glossary.read_report import (
    GlossaryReadReportSpec,
    glossary_read_report_path,
    write_glossary_read_report,
)
from tests.main.glossary_cli_helpers import (
    diamond_resolved_glossary_project,
    glossary_entry,
    resolved_glossary_project,
)


def _event(**overrides: object) -> GlossaryReadEvent:
    kwargs: dict[str, object] = {
        "schema_version": GLOSSARY_READ_LOG_SCHEMA_VERSION,
        "id": "read-alpha",
        "timestamp": "2026-08-01T12:00:00+00:00",
        "project": "gh_sase-org__sase",
        "cwd": "/tmp/sase",
        "agent_name": "athena",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": "/tmp/artifacts",
        "reason": "needed the hood/agent distinction",
        "terms": ("Alpha",),
        "related_terms": ("Beta", "Gamma", "Delta"),
        "depth_limit": None,
        "definition_bytes": 64,
        "source_path": "/tmp/sase/sase/sase.yml",
    }
    kwargs.update(overrides)
    return GlossaryReadEvent(**kwargs)  # type: ignore[arg-type]


def _spec(
    event: GlossaryReadEvent | None = None,
    *,
    report_path: str = "/tmp/glossary-read.md",
    agent_label: str | None = "coder",
) -> GlossaryReadReportSpec:
    return GlossaryReadReportSpec(
        event=event or _event(),
        agent_label=agent_label,
        report_path=report_path,
    )


def _patch_resolved(
    monkeypatch: pytest.MonkeyPatch, resolved: object | None = None
) -> None:
    project = resolved if resolved is not None else diamond_resolved_glossary_project()
    monkeypatch.setattr(
        read_report_mod,
        "resolve_glossary_cli_project",
        lambda *_a, **_kw: project,
    )


def test_report_path_is_deterministic_and_io_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    event = _event()

    first = glossary_read_report_path(event)
    second = glossary_read_report_path(event)

    assert first == second
    assert not Path(first).exists()
    assert Path(first).parent == tmp_path / ".sase" / "glossary_read_reports"
    assert Path(first).name.startswith("alpha-")
    assert Path(first).name.endswith(".md")
    digest = hashlib.sha256(event.id.encode("utf-8")).hexdigest()[:8]
    assert digest in Path(first).name


def test_report_contains_command_metadata_and_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch)
    report = read_report_mod._build_glossary_read_report(_spec())

    assert "# Glossary read: Alpha" in report
    assert "sase glossary read Alpha -r 'needed the hood/agent distinction'" in report
    assert "**Agent**: athena (coder)" in report
    assert "**Reason**: needed the hood/agent distinction" in report
    assert "**Time**:" in report
    assert "Mentions Beta then Gamma." in report
    assert "# Alpha" in report
    assert "## Beta" in report
    assert "Mentions Delta." in report
    assert "gh_sase-org__sase" not in report
    assert "GLOSSARY: sase" in report
    assert "**Project**: sase" in report
    assert "**Source**: /tmp/sase/sase/sase.yml" in report


def test_report_header_uses_project_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch)
    report = read_report_mod._build_glossary_read_report(_spec())

    assert "GLOSSARY: sase" in report
    assert "**Project**: sase" in report
    assert "gh_sase-org__sase" not in report


def test_unresolvable_project_degrades_to_metadata_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        read_report_mod,
        "resolve_glossary_cli_project",
        lambda *_a, **_kw: (_ for _ in ()).throw(GlossaryCliError("no such project")),
    )
    monkeypatch.setattr(
        read_report_mod,
        "resolve_glossary_cli_project_name",
        lambda *_a, **_kw: (_ for _ in ()).throw(GlossaryCliError("no such project")),
    )

    report = read_report_mod._build_glossary_read_report(_spec())

    assert "## Recorded" in report
    assert "Could not resolve this project's glossary: no such project" in report
    assert "Recorded terms: Alpha" in report
    assert "## Output" not in report
    assert "gh_sase-org__sase" not in report


def test_unknown_term_degrades_to_metadata_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch)
    report = read_report_mod._build_glossary_read_report(
        _spec(_event(terms=("Zzz",), related_terms=()))
    )

    assert "Could not re-resolve the glossary closure:" in report
    assert "unknown glossary term: Zzz" in report
    assert "Recorded terms: Zzz" in report
    assert "## Output" not in report


def test_deleted_term_degrades_to_metadata_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remaining = resolved_glossary_project(
        project_name="sase",
        entries=(glossary_entry(0, "Delta", "A leaf."),),
    )
    _patch_resolved(monkeypatch, remaining)
    report = read_report_mod._build_glossary_read_report(_spec())

    assert "Could not re-resolve the glossary closure:" in report
    assert "unknown glossary term: Alpha" in report
    assert "Recorded terms: Alpha" in report
    assert "## Output" not in report


def test_related_term_count_drift_appends_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_resolved(monkeypatch)
    report = read_report_mod._build_glossary_read_report(
        _spec(_event(related_terms=("Beta",)))
    )

    assert "Mentions Beta then Gamma." in report
    assert (
        "Note: this read recorded 1 related term; the current glossary has 3 "
        "related terms."
    ) in report


def test_write_overwrites_and_prunes_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _patch_resolved(monkeypatch)
    event = _event()
    path = glossary_read_report_path(event)

    assert write_glossary_read_report(_spec(event, report_path=path)) == path
    assert "needed the hood/agent distinction" in Path(path).read_text(encoding="utf-8")

    updated = _event(reason="confirming stitch vs commit")
    assert write_glossary_read_report(_spec(updated, report_path=path)) == path
    rewritten = Path(path).read_text(encoding="utf-8")
    assert "confirming stitch vs commit" in rewritten
    assert "needed the hood/agent distinction" not in rewritten

    for index in range(55):
        extra = _event(id=f"extra-{index}", terms=("Alpha",))
        extra_path = glossary_read_report_path(extra)
        assert write_glossary_read_report(_spec(extra, report_path=extra_path)) == (
            extra_path
        )

    report_dir = tmp_path / ".sase" / "glossary_read_reports"
    assert len(list(report_dir.glob("*.md"))) == 50


def test_write_is_atomic_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _patch_resolved(monkeypatch)
    event = _event()
    path = glossary_read_report_path(event)
    assert write_glossary_read_report(_spec(event, report_path=path)) == path
    original = Path(path).read_text(encoding="utf-8")

    monkeypatch.setattr(
        read_report_mod.os,
        "replace",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("replace failed")),
    )

    assert write_glossary_read_report(_spec(event, report_path=path)) is None
    assert Path(path).read_text(encoding="utf-8") == original
