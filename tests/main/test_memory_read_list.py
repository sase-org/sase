"""Tests for ``sase memory list`` and ``sase memory read`` behavior."""

from __future__ import annotations

import argparse
from io import StringIO
import json
from pathlib import Path

import pytest
from rich.console import Console

from sase.memory.cli_list import _render_memory_inventory
from sase.memory.cli_read import handle_memory_read_command
from sase.memory.inventory import build_memory_inventory
from sase.memory.read_log import memory_read_log_path, read_memory_read_events

from .memory_handler_helpers import write


def _long_note(body: str, *, description: str = "Memory note.") -> str:
    return f"---\ntype: reference\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"


def test_memory_list_dashboard_renders_inventory_statuses(tmp_path: Path) -> None:
    write(tmp_path / "AGENTS.md", "@sase/memory/base.md\nsase/memory/missing.md\n")
    write(
        tmp_path / "sase" / "memory" / "base.md",
        "# Base\nSee sase/memory/index.md\n",
    )
    write(tmp_path / "sase" / "memory" / "index.md", "# Index\n")
    write(tmp_path / "sase" / "memory" / "orphan.md", "# Orphan\n")

    inventory = build_memory_inventory(tmp_path)
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=240,
    )

    _render_memory_inventory(inventory, console=console, project_name="demo")

    text = output.getvalue()
    assert "SASE Memory Context" in text
    assert str(tmp_path) in text
    assert "Project" in text
    assert "demo" in text
    assert "Loaded files" in text
    assert "Referenced-only files" in text
    assert "Available files" in text
    assert "Missing references" in text
    assert "Approx loaded tokens" in text
    assert "AGENTS.md" in text
    assert "loaded" in text
    assert "sase/memory/base.md" in text
    assert "referenced" in text
    assert "sase/memory/index.md" in text
    assert "available" in text
    assert "sase/memory/orphan.md" in text
    assert "missing" in text
    assert "sase/memory/missing.md" in text
    assert "@path loads file contents" in text
    assert "AGENTS.md is counted because it is loaded instruction context." in text
    assert "Plain sase/memory/... paths are visible references only." in text


def test_memory_read_prints_body_and_appends_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    artifacts_dir = tmp_path / "artifacts"
    write(
        tmp_path / "sase" / "memory" / "foo.md",
        _long_note("# Body\n\n"),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    handle_memory_read_command(
        argparse.Namespace(selectors=["foo.md"], reason=" Need foo ")
    )

    captured = capsys.readouterr()
    assert captured.out == "# Body\n\n"
    assert captured.err == ""
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].canonical_path == "foo.md"
    assert events[0].agent_name == "agent-a"
    assert events[0].artifacts_dir == str(artifacts_dir)
    assert events[0].reason == "Need foo"
    assert events[0].frontmatter_stripped is True


def test_memory_read_json_format_still_appends_exactly_one_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(
        tmp_path / "sase" / "memory" / "foo.md",
        _long_note("# Body\n\n"),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    handle_memory_read_command(
        argparse.Namespace(selectors=["foo.md"], reason="Need foo", format="json")
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["note"]["canonical_path"] == "foo.md"
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].canonical_path == "foo.md"


def test_memory_read_accepts_flat_path_and_omits_empty_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(
        tmp_path / "sase" / "memory" / "foo.md",
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Foo memory.\n---\n# Body\n\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    handle_memory_read_command(
        argparse.Namespace(selectors=["foo.md"], reason="Need foo")
    )

    captured = capsys.readouterr()
    assert captured.out == "# Body\n\n"
    assert captured.err == ""
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].canonical_path == "foo.md"


def test_memory_read_appends_children_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(
        tmp_path / "sase" / "memory" / "hub.md",
        "---\ntype: reference\nparent: AGENTS.md\ndescription: Hub memory.\n---\n# Hub\n\n",
    )
    write(
        tmp_path / "sase" / "memory" / "child_b.md",
        "---\n"
        "type: reference\n"
        "parent: sase/memory/hub.md\n"
        "description: Beta child.\n"
        "---\n"
        "# Child B\n",
    )
    write(
        tmp_path / "sase" / "memory" / "child_a.md",
        "---\n"
        "type: reference\n"
        "parent: sase/memory/hub.md\n"
        "description: Alpha child.\n"
        "---\n"
        "# Child A\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    handle_memory_read_command(
        argparse.Namespace(selectors=["sase/memory/hub.md"], reason="Need hub")
    )

    captured = capsys.readouterr()
    assert captured.out == (
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
    assert captured.err == ""
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=tmp_path))
    assert len(events) == 1
    assert events[0].canonical_path == "hub.md"


def test_memory_read_falls_back_to_home_memory_and_logs_resolved_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    home_memory = home / "sase" / "memory" / "foo.md"
    write(home_memory, _long_note("# Home Body\n\n"))
    monkeypatch.chdir(project)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    handle_memory_read_command(
        argparse.Namespace(selectors=["foo.md"], reason="Need home foo")
    )

    captured = capsys.readouterr()
    assert captured.out == "# Home Body\n\n"
    assert captured.err == ""
    events = read_memory_read_events(log_path=memory_read_log_path(cwd=project))
    assert len(events) == 1
    assert events[0].canonical_path == "foo.md"
    assert events[0].resolved_path == str(home_memory.resolve())
    assert events[0].reason == "Need home foo"
    assert events[0].frontmatter_stripped is True


def test_memory_read_rejects_nested_legacy_short_path_without_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(tmp_path / "sase" / "memory" / "short" / "foo.md", "# Short\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            argparse.Namespace(selectors=["short/foo.md"], reason="Need short")
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "flat" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_memory_read_rejects_flat_short_memory_without_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(
        tmp_path / "sase" / "memory" / "foo.md",
        "---\ntype: core\nparent: AGENTS.md\n---\n# Short\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            argparse.Namespace(selectors=["foo.md"], reason="Need short")
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "always-loaded" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_memory_read_rejects_blank_reason_before_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(tmp_path / "sase" / "memory" / "foo.md", _long_note("# Body\n"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            argparse.Namespace(selectors=["foo.md"], reason="   ")
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "reason" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_memory_read_requires_agent_attribution_before_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    write(tmp_path / "sase" / "memory" / "foo.md", _long_note("# Body\n"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        handle_memory_read_command(
            argparse.Namespace(selectors=["foo.md"], reason="Need foo")
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out == ""
    assert "agent attribution" in captured.err
    assert not memory_read_log_path(cwd=tmp_path).exists()


def test_memory_list_dashboard_renders_home_context_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    write(project / "AGENTS.md", "@sase/memory/project.md\n")
    write(project / "sase" / "memory" / "project.md", "# Project\n")
    write(home / "AGENTS.md", "@sase/memory/home.md\n")
    write(home / "sase" / "memory" / "home.md", "# Home\n")

    inventory = build_memory_inventory(project, home_root=home)
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=140,
    )

    _render_memory_inventory(inventory, console=console, project_name="demo")

    text = output.getvalue()
    assert "AGENTS.md" in text
    assert "sase/memory/project.md" in text
    assert "~/AGENTS.md" in text
    assert "~/sase/memory/home.md" in text
    assert "~/AGENTS.md -> @sase/memory/home.md" in text
