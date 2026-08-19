"""Tests for provider-scoped ``sase init skills`` generation targets."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import (
    _get_target_path,
    _get_target_paths,
    handle_init_skills_command,
)
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import make_args


@pytest.fixture(autouse=True)
def _disable_prettier_for_skill_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """These generation tests assert content, not Prettier integration."""

    monkeypatch.setattr(init_skills_handler, "_prettier_available", lambda: False)


def test_agy_skill_generation_writes_antigravity_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-scoped skill is written to that provider's deployment profile."""
    xprompt = XPrompt(
        name="skill/agy_only",
        content="Antigravity profile body.\n",
        description="Antigravity profile test skill.",
        skill=["agy"],
        skill_name="agy_only",
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"skill/agy_only": xprompt},
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    for target in _get_target_paths("agy", "agy_only", use_chezmoi=False):
        assert target.exists(), f"missing generated skill target: {target}"
        assert "Antigravity profile body." in target.read_text(encoding="utf-8")


def test_grok_skill_generation_writes_native_target_and_renders_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sase skill init -p grok`` writes a Grok-native rendered skill file."""
    xprompt = XPrompt(
        name="skill/grok_only",
        content=(
            "Provider {{ provider_name }} uses {{ provider_tool_name }} "
            "and {{ provider_native_ask_tool }}.\n"
        ),
        description="Grok profile test skill.",
        skill=["grok"],
        skill_name="grok_only",
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"skill/grok_only": xprompt},
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(provider="grok"))

    assert exc.value.code == 0
    target = _get_target_path("grok", "grok_only", use_chezmoi=False)
    assert target.exists()
    rendered = target.read_text(encoding="utf-8")
    assert "Provider Grok uses Grok Build and ask_user_question." in rendered
    assert not _get_target_path("claude", "grok_only", use_chezmoi=False).exists()


def test_config_defined_skill_is_rejected_with_a_migration_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A config entry can never be a skill: it has no file to generate from."""
    from sase.xprompt.loader_parsing import parse_xprompt_entries

    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": parse_xprompt_entries(
            {
                "sase_gmail": {
                    "content": "Use gog for Gmail.\n",
                    "description": "Read-only personal Gmail access through gog.",
                    "skill": True,
                }
            },
            "config_overlay:sase_athena.yml",
        ),
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True, provider="codex"))

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert str(_get_target_path("codex", "sase_gmail", use_chezmoi=False)) not in (
        captured.out
    )
    assert "declares `skill:` outside a canonical skill source" in captured.err
    assert "sase/skills/" in captured.err


def test_skill_provider_list_respects_requested_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``skill: [codex]`` only renders for codex, including with --provider."""
    xprompt = XPrompt(
        name="skill/codex_only",
        content="Only for Codex.\n",
        description="Codex-only skill.",
        skill=["codex"],
        skill_name="codex_only",
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"skill/codex_only": xprompt},
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True))

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(_get_target_path("codex", "codex_only", use_chezmoi=False)) in out
    assert "claude/skills/codex_only" not in out

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True, provider="claude"))

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(_get_target_path("codex", "codex_only", use_chezmoi=False)) not in out
    assert "Dry run: 1 source entries, no files written" in out
