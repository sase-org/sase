"""Tests for the audited ``roster:<web>`` read and the bare-web guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.identity import AgentIdentity
from sase.main.parser import create_parser
from sase.memory._read_log_query_facade import query_memory_audit
from sase.memory.cli_read import (
    build_memory_read_event_for_view,
    handle_memory_read_command,
)
from sase.memory.cli_show import handle_memory_show_command
from sase.memory.memory_read_report import (
    MemoryReadReportSpec,
    _build_memory_read_report,
)
from sase.memory.read_log import (
    READ_LOG_SCHEMA_VERSION,
    MemoryReadEvent,
    append_memory_read_event,
    memory_read_log_path,
    read_memory_read_events,
)
from sase.memory.selector import (
    MemorySelectorError,
    resolve_memory_selector_batch,
)
from sase.memory.selector_models import (
    NoteSelector,
    RosterSelector,
    StrandSelector,
    WebSelector,
    classify_selector,
)
from sase.memory.selector_render import memory_selector_batch_markdown
from sase.memory.web.roster import render_strand_roster
from sase.sdd._plan_decisions_shared import resolve_memory_records


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _descriptor(
    *,
    slug: str = "runbooks",
    roster: str = "list",
    loading: str | None = None,
    triggers: tuple[str, ...] = ("before writing a plan",),
    description: str = "Runbook catalog.",
) -> str:
    extra = ""
    if loading is not None:
        extra += f"roster_loading: {loading}\n"
    if triggers:
        extra += "roster_read_when:\n" + "".join(f"  - {item}\n" for item in triggers)
    return (
        "---\ntype: core\nweb: true\n"
        f"roster: {roster}\n"
        "roster_label: RECORDS\n"
        "strand_noun: record\n"
        f"description: {description}\n"
        f"{extra}"
        "---\n\nAuthored preamble.\n"
    )


def _strand(keyword: str, summary: str, body: str) -> str:
    return f"---\nkeyword: {keyword}\nsummary: {summary}\n---\n{body}"


def _seed_runbooks(
    root: Path,
    *,
    slug: str = "runbooks",
    loading: str | None = "on_demand",
    strands: tuple[tuple[str, str, str, str], ...] = (
        ("record-0", "Record 0", "Summary 0.", "Body of record 0.\n"),
        ("record-1", "Record 1", "Summary 1.", "Body of record 1.\n"),
    ),
) -> None:
    _write(root / "sase" / "memory" / f"{slug}.md", _descriptor(loading=loading))
    strand_dir = root / "sase" / "memory" / slug
    strand_dir.mkdir(parents=True, exist_ok=True)
    for strand_slug, keyword, summary, body in strands:
        _write(strand_dir / f"{strand_slug}.md", _strand(keyword, summary, body))


def _seed_note(root: Path) -> None:
    _write(
        root / "sase" / "memory" / "foo.md",
        "---\ntype: reference\nparent: AGENTS.md\ndescription: A note.\n---\n# Foo\n",
    )


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    return home


# --- classification ------------------------------------------------------


def test_classify_roster_selector_shapes() -> None:
    assert classify_selector("roster:decisions") == RosterSelector(
        raw="roster:decisions", web_slug="decisions"
    )
    assert isinstance(classify_selector("glossary:stitch"), StrandSelector)
    assert isinstance(classify_selector("glossary"), WebSelector)
    assert isinstance(classify_selector("foo.md"), NoteSelector)

    with pytest.raises(MemorySelectorError, match="invalid memory selector"):
        classify_selector("roster:")
    with pytest.raises(MemorySelectorError, match="invalid memory selector"):
        classify_selector("roster:  ")


def test_unknown_roster_web_fails_whole_batch_closed(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path)

    with pytest.raises(MemorySelectorError, match="unknown memory web: bogus"):
        resolve_memory_selector_batch(
            ["roster:bogus"], project_root=tmp_path, home_root=tmp_path / "home"
        )


# --- markdown rendering ---------------------------------------------------


def test_roster_markdown_is_header_intro_roster_footer(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path)

    batch = resolve_memory_selector_batch(
        ["roster:runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    assert batch.kind == "web"
    assert batch.has_roster_selector
    (section,) = batch.rosters
    roster = render_strand_roster(section.web)
    assert roster  # the fixture roster body itself is non-empty
    expected = (
        "\n---------- MEMORY ROSTER: runbooks\n"
        "\n*2 records — Runbook catalog.*\n"
        f"\n{roster}\n"
        '\nRead one record with `sase memory read runbooks:<keyword> -r "<why>"`.\n'
    )
    assert memory_selector_batch_markdown(batch) == expected


def test_roster_markdown_hides_bodies_and_references(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path)

    output = memory_selector_batch_markdown(
        resolve_memory_selector_batch(
            ["roster:runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
        )
    )

    assert "Body of record 0" not in output
    assert "Body of record 1" not in output
    assert "# Record 0" not in output
    assert "## Linked References" not in output


def test_empty_web_gives_labeled_empty_roster(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path, strands=())

    output = memory_selector_batch_markdown(
        resolve_memory_selector_batch(
            ["roster:runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
        )
    )

    assert "---------- MEMORY ROSTER: runbooks" in output
    assert "*0 records — Runbook catalog.*" in output
    assert output.rstrip().endswith(
        'Read one record with `sase memory read runbooks:<keyword> -r "<why>"`.'
    )


def test_duplicate_roster_selectors_collapse_to_one_section(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path)

    batch = resolve_memory_selector_batch(
        ["roster:runbooks", "roster:runbooks"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )

    assert len(batch.rosters) == 1
    output = memory_selector_batch_markdown(batch)
    assert output.count("---------- MEMORY ROSTER: runbooks") == 1


def test_roster_scope_merging_matches_strand_reads(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _seed_runbooks(tmp_path)
    _seed_runbooks(
        home,
        strands=(
            ("record-1", "Record 1", "Home summary 1.", "Home body 1.\n"),
            ("record-9", "Record 9", "Home summary 9.", "Home body 9.\n"),
        ),
    )

    roster_batch = resolve_memory_selector_batch(
        ["roster:runbooks"], project_root=tmp_path, home_root=home
    )
    strand_batch = resolve_memory_selector_batch(
        ["runbooks"], project_root=tmp_path, home_root=home
    )

    (section,) = roster_batch.rosters
    roster_slugs = {strand.slug for strand in section.web.strands}
    strand_slugs = {
        node.strand.slug for part in strand_batch.web_sections for node in part.nodes
    }
    assert roster_slugs == strand_slugs == {"record-0", "record-1", "record-9"}
    # The shared slug resolves to the project strand in both views.
    merged = {strand.slug: strand for strand in section.web.strands}
    assert merged["record-1"].summary == "Summary 1."


def test_mixed_roster_strand_note_batch_keeps_selector_order(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path, loading=None)
    _seed_note(tmp_path)

    batch = resolve_memory_selector_batch(
        ["foo.md", "roster:runbooks", "runbooks:record-0"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )

    assert batch.kind == "web"
    assert [unit.key for unit in batch.render_units] == [
        "foo.md",
        "runbooks",
        "runbooks",
    ]
    assert [unit.kind for unit in batch.render_units] == ["note", "roster", "web"]
    output = memory_selector_batch_markdown(batch)
    assert output.index("---------- MEMORY FILE: foo.md") < output.index(
        "---------- MEMORY ROSTER: runbooks"
    )
    assert output.index("---------- MEMORY ROSTER: runbooks") < output.index(
        "---------- MEMORY WEB: runbooks"
    )


# --- audit event ----------------------------------------------------------


def test_roster_read_event_shape(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path)
    batch = resolve_memory_selector_batch(
        ["roster:runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    event = build_memory_read_event_for_view(
        batch,
        reason="need the catalog",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        cwd=tmp_path,
    )

    assert event.kind == "web"
    assert event.selectors == ("roster:runbooks",)
    assert event.resolved_targets == ("roster:runbooks",)
    assert event.included_targets == ()
    assert event.canonical_path == "roster:runbooks"
    (section,) = batch.rosters
    assert event.byte_count == len(render_strand_roster(section.web).encode("utf-8"))
    assert len(event.included_blob_oids) == 1
    target, oid = event.included_blob_oids[0]
    assert target == "runbooks.md"
    assert len(oid) == 40


def test_mixed_batch_audit_event_counts_roster_bytes_and_blobs(
    tmp_path: Path,
) -> None:
    _seed_runbooks(tmp_path, loading=None)
    _seed_note(tmp_path)
    batch = resolve_memory_selector_batch(
        ["foo.md", "roster:runbooks", "runbooks:record-0"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )

    event = build_memory_read_event_for_view(
        batch,
        reason="need everything",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        cwd=tmp_path,
    )

    assert event.selectors == ("foo.md", "roster:runbooks", "runbooks:record-0")
    assert event.resolved_targets == (
        "foo.md",
        "runbooks:record-0",
        "roster:runbooks",
    )
    assert event.included_targets == ()
    targets = [target for target, _ in event.included_blob_oids]
    assert "foo.md" in targets
    assert "runbooks.md" in targets
    assert "runbooks:record-0" in targets


def test_roster_event_round_trips_through_rust_audit_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _seed_runbooks(tmp_path)
    batch = resolve_memory_selector_batch(
        ["roster:runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
    )
    event = build_memory_read_event_for_view(
        batch,
        reason="need the catalog",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        cwd=tmp_path,
    )
    log_path = tmp_path / "audit.jsonl"
    append_memory_read_event(event, log_path=log_path)

    rows, _ = query_memory_audit(
        log_path,
        members=[{"artifacts_dir": None, "agent_name": "agent-a"}],
    )

    assert len(rows) == 1
    replayed = rows[0].event
    assert replayed.kind == "web"
    assert replayed.selectors == ("roster:runbooks",)
    assert replayed.resolved_targets == ("roster:runbooks",)
    assert replayed.included_blob_oids == event.included_blob_oids


# --- the bare-web guard ----------------------------------------------------


def test_guard_fires_only_for_on_demand_webs(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path)
    _seed_runbooks(tmp_path, slug="glossary", loading=None)

    with pytest.raises(MemorySelectorError) as exc:
        resolve_memory_selector_batch(
            ["runbooks"],
            project_root=tmp_path,
            home_root=tmp_path / "home",
            refuse_on_demand_bare_webs=True,
        )
    assert getattr(exc.value, "reason", None) == "on_demand_web"

    permissive = resolve_memory_selector_batch(
        ["runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
    )
    assert permissive.kind == "web"
    always_batch = resolve_memory_selector_batch(
        ["glossary"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
        refuse_on_demand_bare_webs=True,
    )
    assert always_batch.kind == "web"


def test_read_guard_names_roster_strand_and_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_runbooks(tmp_path)

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            create_parser().parse_args(["memory", "read", "runbooks", "-r", "need it"])
        )

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "runbooks loads its roster on demand" in captured.err
    assert "sase memory read roster:runbooks" in captured.err
    assert "sase memory read runbooks:<keyword>" in captured.err
    assert "-a/--all-strands" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_show_guard_names_show_hints_without_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_runbooks(tmp_path)

    with pytest.raises(SystemExit) as exc:
        handle_memory_show_command(
            create_parser().parse_args(["memory", "show", "runbooks"])
        )

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sase memory show roster:runbooks" in captured.err
    assert "sase memory show runbooks:<keyword>" in captured.err
    assert '"<why>"' not in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_all_strands_bypasses_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_runbooks(tmp_path)

    handle_memory_read_command(
        create_parser().parse_args(
            ["memory", "read", "runbooks", "-a", "-r", "need every body"]
        )
    )

    captured = capsys.readouterr()
    assert "Body of record 0" in captured.out
    assert "Body of record 1" in captured.out
    assert captured.err == ""
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].kind == "web"


def test_show_logs_nothing_for_roster_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_runbooks(tmp_path)

    handle_memory_show_command(
        create_parser().parse_args(["memory", "show", "roster:runbooks"])
    )

    captured = capsys.readouterr()
    assert "MEMORY ROSTER: runbooks" in captured.out
    assert captured.err == ""
    assert not memory_read_log_path(cwd=tmp_path).exists()


# --- report and plan-decision callers stay permissive ----------------------


def test_plan_memory_decision_naming_bare_on_demand_web_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    _seed_runbooks(tmp_path)

    records, _ = resolve_memory_records(["runbooks"])

    assert records
    assert records[0]["kind"] == "web"


def test_report_reresolves_historical_bare_on_demand_read(tmp_path: Path) -> None:
    _seed_runbooks(tmp_path)
    event = MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id="roster-report",
        timestamp="2026-08-01T12:00:00+00:00",
        project="demo-roster-report",
        cwd=str(tmp_path),
        canonical_path="runbooks:record-0",
        resolved_path="",
        agent_name="agent-a",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason="needed bodies",
        byte_count=8,
        frontmatter_stripped=False,
        kind="web",
        selectors=("runbooks",),
        resolved_targets=("runbooks:record-0", "runbooks:record-1"),
        included_targets=(),
    )

    report = _build_memory_read_report(
        MemoryReadReportSpec(event=event, agent_label=None, report_path="/tmp/x.md")
    )

    assert (
        "sase memory show -p demo-roster-report runbooks -a --format markdown" in report
    )
    assert "Body of record 0" in report
    assert "Body of record 1" in report


def test_report_reproduced_command_adds_all_strands_for_bare_web(
    tmp_path: Path,
) -> None:
    _seed_runbooks(tmp_path, loading=None)
    view = resolve_memory_selector_batch(
        ["runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
    )
    event = build_memory_read_event_for_view(
        view,
        reason="needed bodies",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        cwd=tmp_path,
    )

    report = _build_memory_read_report(
        MemoryReadReportSpec(event=event, agent_label=None, report_path="/tmp/x.md")
    )

    assert "runbooks -a --format markdown" in report


# --- json shape -------------------------------------------------------------


def test_roster_json_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    _prepare(tmp_path, monkeypatch)
    _seed_runbooks(tmp_path)

    handle_memory_show_command(
        create_parser().parse_args(["memory", "show", "roster:runbooks", "-f", "json"])
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["selectors"] == ["roster:runbooks"]
    assert payload["notes"] == []
    assert payload["webs"] == []
    (entry,) = payload["rosters"]
    assert entry["web"] == "runbooks"
    assert entry["label"] == "RECORDS"
    assert entry["strand_noun"] == "record"
    assert entry["count"] == 2
    assert entry["roster"] == "list"
    assert entry["roster_loading"] == "on_demand"
    assert entry["read_when"] == ["before writing a plan"]
    assert [item["number"] for item in entry["entries"]] == [1, 2]
    assert [item["keyword"] for item in entry["entries"]] == ["Record 0", "Record 1"]
    assert [item["slug"] for item in entry["entries"]] == ["record-0", "record-1"]
    assert [item["summary"] for item in entry["entries"]] == [
        "Summary 0.",
        "Summary 1.",
    ]
    assert all(item["supersession"] is None for item in entry["entries"])
    batch = resolve_memory_selector_batch(
        ["roster:runbooks"], project_root=tmp_path, home_root=tmp_path / "home"
    )
    assert entry["markdown"] == render_strand_roster(batch.rosters[0].web)


def test_roster_rich_render_mentions_on_demand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_runbooks(tmp_path)

    handle_memory_show_command(
        create_parser().parse_args(["memory", "show", "roster:runbooks", "-f", "rich"])
    )

    out = capsys.readouterr().out
    assert "MEMORY ROSTER" in out
    assert "runbooks" in out
    assert "2 records · on demand" in out
