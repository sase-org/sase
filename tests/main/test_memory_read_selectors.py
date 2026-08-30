"""CLI-level tests for variadic ``sase memory read``/``show`` selectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.memory.cli_read import handle_memory_read_command
from sase.memory.cli_show import handle_memory_show_command
from sase.memory.read_log import memory_read_log_path, read_memory_read_events

from .memory_handler_helpers import write


def _note(body: str = "# Body\n", *, description: str = "A note.") -> str:
    return f"---\ntype: reference\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"


def _seed_glossary_web(root: Path, *, closure: str = "mentions") -> None:
    write(
        root / "sase" / "memory" / "glossary.md",
        f"---\ntype: core\nweb: true\nroster: inline\nclosure: {closure}\n---\n\nPreamble.\n",
    )
    write(
        root / "sase" / "memory" / "glossary" / "stitch.md",
        "---\naliases: [commit-ish]\nsummary: A change record.\n---\n"
        "A Stitch mentions Patch inside its body.\n",
    )
    write(
        root / "sase" / "memory" / "glossary" / "patch.md",
        "---\nsummary: A proposed change.\n---\nA Patch precedes a Stitch.\n",
    )


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    return home


def test_read_bare_web_selector_prints_every_strand_and_logs_web_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_glossary_web(tmp_path)

    handle_memory_read_command(
        create_parser().parse_args(["memory", "read", "glossary", "-r", "need it"])
    )

    out = capsys.readouterr().out
    assert "Stitch" in out
    assert "Patch" in out
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].kind == "web"
    assert events[0].selectors == ("glossary",)


def test_read_strand_selector_with_mentions_closure_includes_related_strand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_glossary_web(tmp_path, closure="mentions")

    handle_memory_read_command(
        create_parser().parse_args(
            ["memory", "read", "glossary:stitch", "-r", "need it"]
        )
    )

    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert events[0].kind == "strand"
    assert events[0].resolved_targets == ("glossary:stitch",)
    assert events[0].included_targets == ("glossary:patch",)


def test_read_core_web_descriptor_is_refused_but_strand_is_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_glossary_web(tmp_path)

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            create_parser().parse_args(
                ["memory", "read", "glossary.md", "-r", "need it"]
            )
        )
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "always-loaded memory web descriptor" in err
    assert "sase memory read glossary:<keyword>" in err
    assert not memory_read_log_path(cwd=tmp_path).exists()

    handle_memory_read_command(
        create_parser().parse_args(
            ["memory", "read", "glossary:stitch", "-r", "need it"]
        )
    )
    assert (
        len(read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))) == 1
    )


def test_read_mixed_batch_fails_atomically_on_one_bad_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    write(tmp_path / "sase" / "memory" / "foo.md", _note())
    _seed_glossary_web(tmp_path)

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            create_parser().parse_args(
                [
                    "memory",
                    "read",
                    "foo.md",
                    "glossary:bogus",
                    "-r",
                    "need it",
                ]
            )
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_show_mixed_batch_json_includes_notes_and_webs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    write(tmp_path / "sase" / "memory" / "foo.md", _note())
    _seed_glossary_web(tmp_path, closure="none")

    handle_memory_show_command(
        create_parser().parse_args(
            ["memory", "show", "glossary:stitch", "foo.md", "-f", "json"]
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["selectors"] == ["glossary:stitch", "foo.md"]
    assert [note["canonical_path"] for note in payload["notes"]] == ["foo.md"]
    (web,) = payload["webs"]
    assert web["web"] == "glossary"
    assert [node["slug"] for node in web["nodes"]] == ["stitch"]
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_read_multi_note_batch_markdown_labels_each_note_before_its_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    write(
        tmp_path / "sase" / "memory" / "first.md",
        _note("# First body\n", description="First note."),
    )
    write(
        tmp_path / "sase" / "memory" / "second.md",
        _note("# Second body\n", description="Second note."),
    )

    handle_memory_read_command(
        create_parser().parse_args(
            ["memory", "read", "first.md", "second.md", "-r", "need it"]
        )
    )

    out = capsys.readouterr().out
    first_header_line = "---------- MEMORY FILE: first.md"
    second_header_line = "---------- MEMORY FILE: second.md"
    assert out.startswith(f"\n{first_header_line}\n\n")
    assert f"\n\n{second_header_line}\n\n" in out
    first_header = out.index(first_header_line)
    first_body = out.index("# First body")
    second_header = out.index(second_header_line)
    second_body = out.index("# Second body")
    assert first_header < first_body < second_header < second_body


def test_show_records_no_audit_event_for_web_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_glossary_web(tmp_path)

    handle_memory_show_command(
        create_parser().parse_args(["memory", "show", "glossary"])
    )

    assert "Stitch" in capsys.readouterr().out
    assert not memory_read_log_path(cwd=tmp_path).exists()


def _seed_decisions_web(root: Path) -> None:
    write(
        root / "sase" / "memory" / "decisions.md",
        "---\nweb: true\ndescription: Decision records.\nroster: list\n---\n\nPreamble.\n",
    )
    write(
        root / "sase" / "memory" / "decisions" / "gates-never-block.md",
        "---\nkeyword: A Gate Never Blocks\nsummary: Gate summary.\n---\n"
        "See ![[decisions/single-turn-agents]] for more.\n",
    )
    write(
        root / "sase" / "memory" / "decisions" / "single-turn-agents.md",
        "---\nkeyword: Agents Are Single-Turn\nsummary: Turn summary.\n---\n"
        "A run is one turn.\n",
    )


def test_show_inline_link_expands_strand_without_linked_references_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_decisions_web(tmp_path)

    handle_memory_show_command(
        create_parser().parse_args(["memory", "show", "decisions:gates-never-block"])
    )

    out = capsys.readouterr().out
    assert "A Gate Never Blocks" in out
    assert "Agents Are Single-Turn" in out
    assert out.index("A Gate Never Blocks") < out.index("Agents Are Single-Turn")
    assert "Linked References" not in out


def test_show_and_read_match_for_a_note_with_linked_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_decisions_web(tmp_path)
    write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note("# Body\nSee [[decisions:single-turn-agents]].\n"),
    )

    handle_memory_show_command(create_parser().parse_args(["memory", "show", "foo.md"]))
    show_out = capsys.readouterr().out

    handle_memory_read_command(
        create_parser().parse_args(["memory", "read", "foo.md", "-r", "need it"])
    )
    read_out = capsys.readouterr().out

    assert show_out == read_out
    assert "## Linked References" in show_out
    assert "### 1. `decisions:single-turn-agents`" in show_out
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].byte_count == len(
        (tmp_path / "sase" / "memory" / "foo.md")
        .read_text(encoding="utf-8")
        .encode("utf-8")
    )


def test_show_json_includes_linked_references_for_notes_and_webs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(tmp_path, monkeypatch)
    _seed_decisions_web(tmp_path)
    write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note("# Body\nSee [[decisions:single-turn-agents]].\n"),
    )

    handle_memory_show_command(
        create_parser().parse_args(["memory", "show", "foo.md", "-f", "json"])
    )
    note_payload = json.loads(capsys.readouterr().out)
    assert note_payload["linked_references"][0]["address"] == (
        "decisions:single-turn-agents"
    )
    assert note_payload["note"]["links"][0]["kind"] == "reference"

    handle_memory_show_command(
        create_parser().parse_args(
            ["memory", "show", "decisions:gates-never-block", "-f", "json"]
        )
    )
    web_payload = json.loads(capsys.readouterr().out)
    (web,) = web_payload["webs"]
    assert web["linked_references"] == []
    requested = next(
        node for node in web["nodes"] if node["slug"] == "gates-never-block"
    )
    assert requested["links"][0]["kind"] == "inline"
    assert requested["links"][0]["address"] == "decisions:single-turn-agents"
