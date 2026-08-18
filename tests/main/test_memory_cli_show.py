"""Tests for ``sase memory show``."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.main.init_memory.config import project_memory_name
from sase.main.parser import create_parser
from sase.memory.cli_read import handle_memory_read_command
from sase.memory.cli_show import handle_memory_show_command
from sase.memory.read_log import memory_read_log_path

from .memory_handler_helpers import write

_HUB_MARKDOWN = (
    "# Hub\n\n"
    "## Children\n\n"
    "The below files contain detailed reference material. When working in their "
    "domain, you\n"
    "MUST use your `/sase_memory_read` skill to review their contents. Do not "
    "read canonical\n"
    "memory files directly.\n\n"
    "**`sase/memory/child_a.md`**  \n"
    "Alpha child.\n\n"
    "**`sase/memory/child_b.md`**  \n"
    "Beta child.\n"
)


def _long_note(body: str, *, description: str = "Memory note.") -> str:
    return (
        f"---\ntype: long\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"
    )


def _write_hub_fixture(root: Path) -> None:
    write(
        root / "sase" / "memory" / "hub.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: Hub memory.\n---\n# Hub\n\n",
    )
    write(
        root / "sase" / "memory" / "child_b.md",
        "---\n"
        "type: long\n"
        "parent: sase/memory/hub.md\n"
        "description: Beta child.\n"
        "---\n"
        "# Child B\n",
    )
    write(
        root / "sase" / "memory" / "child_a.md",
        "---\n"
        "type: long\n"
        "parent: sase/memory/hub.md\n"
        "description: Alpha child.\n"
        "---\n"
        "# Child A\n",
    )


def test_show_prints_body_and_children_without_audit_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _write_hub_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    args = create_parser().parse_args(["memory", "show", "hub.md"])
    handle_memory_show_command(args)

    captured = capsys.readouterr()
    assert captured.out == _HUB_MARKDOWN
    assert captured.err == ""
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_show_succeeds_without_agent_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(tmp_path / "sase" / "memory" / "foo.md", _long_note("# Body\n\n"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    args = create_parser().parse_args(["memory", "show", "foo.md"])
    handle_memory_show_command(args)

    captured = capsys.readouterr()
    assert captured.out == "# Body\n\n"
    assert captured.err == ""
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_show_stdout_matches_read_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _write_hub_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    handle_memory_show_command(create_parser().parse_args(["memory", "show", "hub.md"]))
    show_markdown = capsys.readouterr().out

    handle_memory_read_command(
        create_parser().parse_args(["memory", "read", "hub.md", "-r", "Need hub"])
    )
    read_markdown = capsys.readouterr().out

    assert show_markdown == read_markdown == _HUB_MARKDOWN

    handle_memory_show_command(
        create_parser().parse_args(["memory", "show", "hub.md", "-f", "json"])
    )
    show_json = capsys.readouterr().out

    handle_memory_read_command(
        create_parser().parse_args(
            ["memory", "read", "hub.md", "-r", "Need hub", "-f", "json"]
        )
    )
    read_json = capsys.readouterr().out

    assert show_json == read_json


def test_show_json_payload_includes_note_and_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    _write_hub_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    args = create_parser().parse_args(["memory", "show", "hub.md", "-f", "json"])
    handle_memory_show_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["project"] == project_memory_name(tmp_path)
    assert payload["origin"] == "project"
    assert payload["note"]["canonical_path"] == "hub.md"
    assert payload["note"]["type"] == "long"
    assert payload["note"]["description"] == "Hub memory."
    assert payload["note"]["body"] == "# Hub\n\n"
    assert payload["note"]["frontmatter_stripped"] is True
    assert payload["children"] == [
        {"path": "sase/memory/child_a.md", "description": "Alpha child."},
        {"path": "sase/memory/child_b.md", "description": "Beta child."},
    ]


def test_show_rich_format_renders_path_type_and_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    _write_hub_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    args = create_parser().parse_args(["memory", "show", "hub.md", "-f", "rich"])

    handle_memory_show_command(args, console=console)

    text = output.getvalue()
    assert "sase/memory/hub.md" in text
    assert "long" in text
    assert "Hub memory." in text
    assert "sase/memory/child_a.md" in text
    assert "sase/memory/child_b.md" in text


def test_show_json_origin_is_home_on_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    write(home / "sase" / "memory" / "foo.md", _long_note("# Home Body\n\n"))
    monkeypatch.chdir(project)
    monkeypatch.setattr(Path, "home", lambda: home)

    args = create_parser().parse_args(["memory", "show", "foo.md", "-f", "json"])
    handle_memory_show_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["origin"] == "home"


def test_show_missing_note_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    args = create_parser().parse_args(["memory", "show", "does_not_exist.md"])

    with pytest.raises(SystemExit) as exc:
        handle_memory_show_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "sase memory show:" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_show_nested_path_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(tmp_path / "sase" / "memory" / "short" / "foo.md", "# Short\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    args = create_parser().parse_args(["memory", "show", "short/foo.md"])

    with pytest.raises(SystemExit) as exc:
        handle_memory_show_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "sase memory show:" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_show_type_short_note_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(
        tmp_path / "sase" / "memory" / "foo.md",
        "---\ntype: short\nparent: AGENTS.md\n---\n# Short\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)

    args = create_parser().parse_args(["memory", "show", "foo.md"])

    with pytest.raises(SystemExit) as exc:
        handle_memory_show_command(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "sase memory show:" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()
