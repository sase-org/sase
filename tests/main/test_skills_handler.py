"""Tests for the ``sase skills`` parser, handler, inventory, and list output."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import sys

import pytest
from rich.console import Console

from sase.main import init_skills_handler, skills_handler
from sase.main.init_skills_handler import _get_target_path, run_init_skills
from sase.main.parser import create_parser
from sase.skills.cli_list import _render_skills_inventory
from sase.skills.inventory import (
    SkillSourceEntry,
    SkillTargetEntry,
    SkillsInventory,
    build_skills_inventory,
)
from sase.skills.use_log import read_skill_use_events
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import make_args


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _stub_skill_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    source_root = tmp_path / "sources"
    source_paths = {
        "current": source_root / "current.md",
        "missing": source_root / "missing.md",
        "stale": source_root / "stale.md",
    }
    for name, path in source_paths.items():
        _write(
            path,
            f"---\nname: {name}\ndescription: {name} description\n"
            "skill: [claude]\n---\n\nbody\n",
        )

    xprompts = {
        name: XPrompt(
            name=name,
            content=f"{name} body\n",
            source_path=str(path),
            description=f"{name} description",
            skill=["claude"],
        )
        for name, path in source_paths.items()
    }
    monkeypatch.setattr(init_skills_handler, "load_xprompts_from_internal", lambda: {})
    monkeypatch.setattr(
        init_skills_handler, "get_all_xprompts", lambda project="": xprompts
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return source_paths


def _inventory_with_target_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    source_paths = _stub_skill_sources(tmp_path, monkeypatch)

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()

    missing_target = _get_target_path("claude", "missing", use_chezmoi=False)
    missing_target.unlink()
    stale_target = _get_target_path("claude", "stale", use_chezmoi=False)
    stale_target.write_text("stale skill\n", encoding="utf-8")

    return build_skills_inventory(), source_paths


def test_parser_registers_skills_namespace() -> None:
    parser = create_parser()

    init_args = parser.parse_args(
        [
            "skills",
            "init",
            "--no-apply",
            "--no-commit",
            "--force",
            "--dry-run",
            "--no-push",
            "--provider",
            "codex",
        ]
    )
    assert init_args.command == "skills"
    assert init_args.skills_subcommand == "init"
    assert init_args.no_apply is True
    assert init_args.no_commit is True
    assert init_args.force is True
    assert init_args.dry_run is True
    assert init_args.no_push is True
    assert init_args.provider == "codex"

    list_args = parser.parse_args(["skills", "list"])
    assert list_args.command == "skills"
    assert list_args.skills_subcommand == "list"

    use_args = parser.parse_args(["skills", "use", "sase_plan", "-r", "Need plan"])
    assert use_args.command == "skills"
    assert use_args.skills_subcommand == "use"
    assert use_args.name == "sase_plan"
    assert use_args.reason == "Need plan"

    default_args = parser.parse_args(["skills"])
    assert default_args.command == "skills"
    assert default_args.skills_subcommand == "list"


def test_parser_requires_skills_use_reason() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["skills", "use", "sase_plan"])


def test_bare_skills_defaults_to_list(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[argparse.Namespace] = []

    def fake_list(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(skills_handler, "_handle_skills_list_command", fake_list)
    args = create_parser().parse_args(["skills"])

    with pytest.raises(SystemExit) as exc:
        skills_handler.handle_skills_command(args)

    assert exc.value.code == 0
    assert calls == [args]


def test_skills_init_dispatches_to_existing_initializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[argparse.Namespace] = []

    def fake_init(args: argparse.Namespace) -> int:
        calls.append(args)
        return 7

    monkeypatch.setattr(init_skills_handler, "run_init_skills", fake_init)
    args = create_parser().parse_args(
        ["skills", "init", "--dry-run", "--force", "--provider", "codex"]
    )

    with pytest.raises(SystemExit) as exc:
        skills_handler.handle_skills_command(args)

    assert exc.value.code == 7
    assert calls == [args]
    assert calls[0].dry_run is True
    assert calls[0].force is True
    assert calls[0].provider == "codex"


def test_skills_use_dispatches_to_recorder(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[argparse.Namespace] = []

    def fake_use(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(skills_handler, "_handle_skills_use_command", fake_use)
    args = create_parser().parse_args(["skills", "use", "sase_plan", "-r", "Need"])

    with pytest.raises(SystemExit) as exc:
        skills_handler.handle_skills_command(args)

    assert exc.value.code == 0
    assert calls == [args]
    assert calls[0].name == "sase_plan"
    assert calls[0].reason == "Need"


def test_skills_use_command_writes_attributed_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        '{"name": "alpha", "llm_provider": "codex"}',
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT_NAME", "alpha")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    args = create_parser().parse_args(["skills", "use", "sase_plan", "-r", "Need"])
    with pytest.raises(SystemExit) as exc:
        skills_handler.handle_skills_command(args)

    assert exc.value.code == 0
    assert "Logged skill use: sase_plan" in capsys.readouterr().out
    events = read_skill_use_events(project="project")
    assert len(events) == 1
    assert events[0].skill_name == "sase_plan"
    assert events[0].agent_name == "alpha"
    assert events[0].artifacts_dir == str(artifacts_dir)
    assert events[0].reason == "Need"
    assert events[0].runtime == "codex"


def test_skills_use_command_reports_missing_agent_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    args = create_parser().parse_args(["skills", "use", "sase_plan", "-r", "Need"])
    with pytest.raises(SystemExit) as exc:
        skills_handler.handle_skills_command(args)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("sase skills use:")
    assert "agent attribution" in err


def test_init_skills_alias_remains_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.entry import main

    calls: list[argparse.Namespace] = []

    def fake_init(args: argparse.Namespace) -> None:
        calls.append(args)
        sys.exit(0)

    monkeypatch.setattr(sys, "argv", ["sase", "init", "skills", "-n", "-p", "codex"])
    monkeypatch.setattr(
        "sase.main.init_skills_handler.handle_init_skills_command",
        fake_init,
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert len(calls) == 1
    assert calls[0].command == "init"
    assert calls[0].init_subcommand == "skills"
    assert calls[0].dry_run is True
    assert calls[0].provider == "codex"


def test_skills_inventory_classifies_generated_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory, _ = _inventory_with_target_states(tmp_path, monkeypatch, capsys)

    assert inventory.source_count == 3
    assert inventory.provider_count == 1
    assert inventory.target_count == 3
    assert inventory.current_count == 1
    assert inventory.stale_count == 1
    assert inventory.missing_count == 1
    assert inventory.deploy_mode == "home"
    sources = {source.name: source for source in inventory.sources}
    assert sources["current"].current_count == 1
    assert sources["missing"].missing_count == 1
    assert sources["stale"].stale_count == 1


def test_skills_list_dashboard_renders_summary_and_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory, source_paths = _inventory_with_target_states(
        tmp_path, monkeypatch, capsys
    )
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=140,
    )

    _render_skills_inventory(inventory, console=console)

    text = output.getvalue()
    assert "SASE Skills" in text
    assert "Sources" in text
    assert "3" in text
    assert "Providers" in text
    assert "claude" in text
    assert "Generated targets" in text
    assert "1 current" in text
    assert "1 stale" in text
    assert "1 missing" in text
    assert "Deploy mode" in text
    assert "home" in text
    assert "Skill Sources" in text
    assert "/current" in text
    _ = source_paths  # path display is exercised by the long-description test
    assert "current description" in text
    assert "…" not in text
    assert "..." not in text.replace(
        "sase skills init --force refreshes generated skill files.", ""
    ).replace("sase init skills remains an alias-compatible initializer.", "")
    assert "Drift" in text
    assert "claude/missing" in text
    assert "claude/stale" in text
    assert "sase skills init --force refreshes generated skill files" in text
    assert "sase init skills remains an alias-compatible initializer" in text


def test_skills_list_dashboard_does_not_truncate_long_name_or_description() -> None:
    long_name = "a_very_long_skill_name_for_testing"
    long_description = (
        "Sentence one provides background context. "
        "Sentence two adds an additional clarification about usage. "
        "Sentence three explains an edge case that the reader needs to know about. "
        "Sentence four reinforces the guidance with an explicit example. "
        "Sentence five reminds the caller about the dangers of misuse and concludes."
    )
    assert len(long_description) > 200
    assert len(long_name) > 18

    source = SkillSourceEntry(
        name=long_name,
        description=long_description,
        source_path="src/sase/xprompts/skills/a_very_long_skill_name_for_testing.md",
        providers=("claude",),
        targets=(),
    )
    inventory = SkillsInventory(sources=(source,), deploy_mode="home")

    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=120)
    _render_skills_inventory(inventory, console=console)
    text = output.getvalue()

    assert f"/{long_name}" in text
    for word in long_description.split():
        assert word in text
    assert "…" not in text
    # The canonical xprompts/skills/<name>.md path is redundant with the skill
    # name and intentionally omitted from the description footer.


def test_skills_list_table_shows_full_provider_set_and_status_tokens() -> None:
    multi_targets = tuple(
        SkillTargetEntry(
            path=Path(f"/tmp/{provider}/multi.md"),
            provider=provider,
            skill_name="multi",
            status="current",
        )
        for provider in ("claude", "gemini", "codex", "amp", "cursor")
    )
    multi = SkillSourceEntry(
        name="multi",
        description="multi-provider skill",
        source_path="src/sase/xprompts/skills/multi.md",
        providers=("claude", "gemini", "codex", "amp", "cursor"),
        targets=multi_targets,
    )
    single = SkillSourceEntry(
        name="single",
        description="single-provider skill",
        source_path="src/sase/xprompts/skills/single.md",
        providers=("gemini",),
        targets=(),
    )
    inventory = SkillsInventory(sources=(multi, single), deploy_mode="home")

    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    _render_skills_inventory(inventory, console=console)
    text = output.getvalue()

    for provider in ("claude", "gemini", "codex", "amp", "cursor"):
        assert provider in text
    # No `+N` collapse should appear in the providers column.
    assert "+4" not in text
    assert "+3" not in text


def test_skills_list_table_renders_compact_status_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory, _ = _inventory_with_target_states(tmp_path, monkeypatch, capsys)

    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=140)
    _render_skills_inventory(inventory, console=console)
    text = output.getvalue()

    assert "✓ 1" in text
    assert "⚠ 1" in text
    assert "✗ 1" in text
