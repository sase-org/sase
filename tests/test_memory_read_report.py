"""Tests for deferred modern memory-read Markdown reports."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.agent.identity import AgentIdentity
from sase.memory.cli_read import build_memory_read_event_for_view
from sase.memory.memory_read_report import (
    MemoryReadReportSpec,
    _build_memory_read_report,
    memory_read_report_path,
    write_memory_read_report,
)
from sase.memory.read_log import (
    READ_LOG_SCHEMA_VERSION,
    MemoryReadEvent,
    append_memory_read_event,
    memory_read_log_path,
    read_memory_read_events,
)
from sase.memory.selector import resolve_memory_selector_batch
from sase.memory.selector_render import memory_selector_batch_markdown


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _descriptor(*, closure: str = "none") -> str:
    return (
        "---\n"
        "type: core\n"
        "web: true\n"
        "roster: inline\n"
        f"closure: {closure}\n"
        "---\n\nDecision records.\n"
    )


def _note(body: str = "# Note\n") -> str:
    return "---\ntype: reference\nparent: AGENTS.md\n---\n" + body


def _strand(*, summary: str, body: str, keyword: str | None = None) -> str:
    keyword_line = "" if keyword is None else f"keyword: {keyword}\n"
    return f"---\n{keyword_line}summary: {summary}\n---\n{body}"


def _seed_decisions_web(root: Path, *, closure: str = "mentions") -> None:
    _write(root / "sase" / "memory" / "decisions.md", _descriptor(closure=closure))
    _write(
        root / "sase" / "memory" / "decisions" / "corpus-before-mechanism.md",
        _strand(
            keyword="Corpus Before Mechanism",
            summary="Corpus first.",
            body="Choose the corpus before building the retrieval mechanism.\n",
        ),
    )
    _write(
        root / "sase" / "memory" / "decisions" / "memory-webs.md",
        _strand(
            keyword="Memory Webs",
            summary="Flat descriptor plus strands.",
            body="A memory web keeps strands out of the descriptor.\n",
        ),
    )


def _event(
    *,
    cwd: Path,
    selectors: tuple[str, ...] = ("decisions:corpus-before-mechanism",),
    canonical_path: str = "decisions:corpus-before-mechanism",
    resolved_targets: tuple[str, ...] = ("decisions:corpus-before-mechanism",),
    included_targets: tuple[str, ...] = (),
    kind: str = "strand",
    depth: int | None = None,
    read_id: str = "read-modern",
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=read_id,
        timestamp="2026-08-01T12:00:00+00:00",
        project="demo-memory-report",
        cwd=str(cwd),
        canonical_path=canonical_path,
        resolved_path="",
        agent_name="agent-a",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/artifacts",
        reason="needed the decision context",
        byte_count=128,
        frontmatter_stripped=False,
        kind=kind,  # type: ignore[arg-type]
        selectors=selectors,
        resolved_targets=resolved_targets,
        included_targets=included_targets,
        depth=depth,
        scope_origin=tuple((target, "project") for target in resolved_targets),
    )


def _spec(
    event: MemoryReadEvent | None = None,
    *,
    cwd: Path | None = None,
    report_path: str = "/tmp/memory-report.md",
) -> MemoryReadReportSpec:
    return MemoryReadReportSpec(
        event=event or _event(cwd=cwd or Path("/tmp/project")),
        agent_label=None,
        report_path=report_path,
    )


def test_report_path_is_deterministic_and_project_state_scoped(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    event = _event(cwd=tmp_path)

    first = memory_read_report_path(event)
    second = memory_read_report_path(event)

    assert first == second
    assert Path(first).parent == tmp_path / ".sase" / "memory_read_reports"


def test_build_report_uses_memory_show_command_and_current_markdown_output(
    tmp_path: Path,
) -> None:
    _seed_decisions_web(tmp_path, closure="none")
    event = _event(cwd=tmp_path, depth=0)

    report = _build_memory_read_report(_spec(event))

    assert (
        "sase memory show -p demo-memory-report "
        "decisions:corpus-before-mechanism -d 0 --format markdown"
    ) in report
    expected = memory_selector_batch_markdown(
        resolve_memory_selector_batch(
            ["decisions:corpus-before-mechanism"],
            depth=0,
            project_root=tmp_path,
            home_root=tmp_path / "home",
        )
    ).strip()
    assert "## Output" in report
    assert report.partition("## Output")[2].strip() == expected


def test_build_report_renders_bare_web_multi_target_output(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path, closure="none")
    event = _event(
        cwd=tmp_path,
        selectors=("decisions",),
        canonical_path="decisions:corpus-before-mechanism",
        resolved_targets=(
            "decisions:corpus-before-mechanism",
            "decisions:memory-webs",
        ),
        kind="web",
    )

    report = _build_memory_read_report(_spec(event))

    assert (
        "sase memory show -p demo-memory-report decisions --format markdown" in report
    )
    assert "MEMORY WEB: decisions" in report
    assert "# Corpus Before Mechanism" in report
    assert "# Memory Webs" in report


def test_build_report_records_resolution_failure(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)
    event = _event(
        cwd=tmp_path,
        selectors=("decisions:missing",),
        canonical_path="decisions:missing",
        resolved_targets=("decisions:missing",),
    )

    report = _build_memory_read_report(_spec(event))

    assert "## Note" in report
    assert "Could not re-resolve the memory selector batch:" in report
    assert "unknown memory strand" in report
    assert "Recorded selectors: decisions:missing" in report


def test_write_report_records_no_memory_read_event(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _seed_decisions_web(tmp_path)
    view = resolve_memory_selector_batch(
        ["decisions:corpus-before-mechanism"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )
    event = build_memory_read_event_for_view(
        view,
        reason="needed it",
        agent=AgentIdentity("agent-a", "test", None),
        cwd=tmp_path,
    )
    log_path = memory_read_log_path("demo-memory-report")
    append_memory_read_event(event, log_path=log_path)
    report_path = memory_read_report_path(event)

    assert (
        write_memory_read_report(_spec(event, report_path=report_path)) == report_path
    )

    assert read_memory_read_events(log_path=log_path) == (event,)


def test_write_report_uses_atomic_overwrite(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _seed_decisions_web(tmp_path)
    calls: list[tuple[Path, bool, bytes]] = []

    def fake_atomic(path: Path, data: bytes, *, overwrite: bool) -> None:
        calls.append((path, overwrite, data))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    monkeypatch.setattr(
        "sase.memory.memory_read_report.write_bytes_atomically",
        fake_atomic,
    )
    event = _event(cwd=tmp_path)
    report_path = memory_read_report_path(event)

    assert (
        write_memory_read_report(_spec(event, report_path=report_path)) == report_path
    )

    assert calls
    assert calls[0][0] == Path(report_path)
    assert calls[0][1] is True
    assert b"## Output" in calls[0][2]


def test_write_report_prunes_old_reports(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _seed_decisions_web(tmp_path)
    event = _event(cwd=tmp_path)

    assert write_memory_read_report(
        _spec(event, report_path=memory_read_report_path(event))
    )

    for index in range(55):
        extra = replace(
            event,
            id=f"extra-{index}",
            timestamp=f"2026-08-01T12:{index:02d}:00+00:00",
        )
        extra_path = memory_read_report_path(extra)
        assert (
            write_memory_read_report(_spec(extra, report_path=extra_path)) == extra_path
        )

    report_dir = tmp_path / ".sase" / "memory_read_reports"
    assert len(list(report_dir.glob("*.md"))) == 50


def test_mixed_note_and_strand_report_uses_original_selector_batch(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "tui_perf.md", _note("# Perf\n"))
    _seed_decisions_web(tmp_path, closure="none")
    event = _event(
        cwd=tmp_path,
        selectors=("decisions:corpus-before-mechanism", "tui_perf.md"),
        resolved_targets=("decisions:corpus-before-mechanism", "tui_perf.md"),
        kind="strand",
    )

    report = _build_memory_read_report(_spec(event))

    assert "decisions:corpus-before-mechanism tui_perf.md" in report
    output = report.partition("## Output")[2]
    assert "# Perf" in output
    assert "MEMORY WEB: decisions" in output
