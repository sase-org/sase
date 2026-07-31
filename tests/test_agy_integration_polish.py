"""Cross-provider integration coverage for the Antigravity (agy) provider.

Phase 3 wires ``agy`` into SASE's provider ecosystem (registry metadata,
doctor, retry defaults, and TUI surfaces) the same way Claude, Codex, Qwen,
and OpenCode are. These tests exercise the provider-neutral seams with exact
``agy`` model slugs matching the current Antigravity CLI catalog.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.text import Text

from sase.ace.tui.modals.model_picker_options import build_model_options
from sase.ace.tui.modals.plan_approval_modal import _provider_badge_markup
from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field
from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.commit_instructions import _resolve_commit_skill_name
from sase.llm_provider.registry import (
    model_short_alias_map,
    model_to_provider_map,
    provider_cli_status_color_map,
    provider_short_name_map,
    resolve_model_provider,
)
from sase.llm_provider.retry_config import get_retry_config, is_retryable_error
from sase.llm_provider.temporary_override import set_temporary_override
from sase.main import init_skills_handler
from sase.main.init_skills_handler import _get_target_path
from sase.main.parser import create_parser

_AGY_LARGE = "gemini-3.6-flash-high"
_AGY_SMALL = "gemini-3.6-flash-low"
_AGY_FLASH35_HIGH = "gemini-3.5-flash-high"


def test_provider_metadata_aggregation_includes_agy() -> None:
    models = model_to_provider_map()
    provider_shorts = provider_short_name_map()
    model_aliases = model_short_alias_map()

    assert models[_AGY_LARGE] == "agy"
    assert models[_AGY_SMALL] == "agy"
    assert provider_shorts["agy"] == "agy"
    assert model_aliases[_AGY_LARGE] == "flash36h"
    assert model_aliases[_AGY_SMALL] == "flash36l"
    # A distinct Antigravity indigo, deliberately not the old Gemini-CLI blue.
    color = provider_cli_status_color_map()["agy"]
    assert color == "#6E5DE7"


def test_agy_autodetect_occupies_late_fallback_slot() -> None:
    """agy inherits the late fallback slot (priority 30) the Gemini CLI used."""
    from sase.llm_provider.registry import get_llm_metadata_payload

    candidates = get_llm_metadata_payload()["autodetect_candidates"]
    by_provider = {c["provider"]: c for c in candidates}

    assert by_provider["agy"]["priority"] == 30
    assert by_provider["agy"]["cli_name"] == "agy"

    # The retired Gemini CLI no longer participates in autodetect.
    assert "gemini" not in by_provider


def test_nested_agy_model_resolution_preserves_slug() -> None:
    assert resolve_model_provider(f"agy/{_AGY_LARGE}") == ("agy", _AGY_LARGE)


def test_model_picker_includes_agy_model_slugs() -> None:
    option_ids = {option.id for option in build_model_options() if option is not None}

    assert _AGY_LARGE in option_ids
    assert _AGY_SMALL in option_ids


def test_prompt_panel_model_field_renders_agy_provider() -> None:
    text = Text()

    append_model_field(text, _AGY_LARGE, "agy")

    assert text.plain == f"Model: AGY({_AGY_LARGE})\n"


def test_prompt_panel_model_field_infers_agy_from_model_name() -> None:
    text = Text()

    append_model_field(text, _AGY_LARGE, None)

    assert text.plain == f"Model: AGY({_AGY_LARGE})\n"


def test_plan_approval_badge_renders_agy_provider_color() -> None:
    badge = _provider_badge_markup("agy", _AGY_LARGE)

    assert "AGY" in badge
    assert "#6E5DE7" in badge
    # The exact model slug survives intact in the badge markup.
    assert _AGY_LARGE in badge


def test_agy_provider_has_emoji_badge() -> None:
    assert provider_emoji_badge("agy") == "🪐"


def test_temporary_override_accepts_agy_model_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    override = set_temporary_override(
        f"agy/{_AGY_LARGE}",
        60.0,
        source="test",
    )

    assert override.provider == "agy"
    assert override.model == _AGY_LARGE
    assert override.raw_model == f"agy/{_AGY_LARGE}"


def test_agent_metadata_records_agy_provider_directive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider half of an ``%model:agy/...`` directive is recorded."""
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260619120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.ace.agent_tribes.update_agent_tribe"),
    ):
        info = extract_directives_and_write_meta(
            "%model:agy/gemini-3.6-flash-high\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert info.llm_provider == "agy"
    assert meta["llm_provider"] == "agy"


def test_agent_metadata_routes_model_xprompt_alias_to_agy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``%model:@#agy_flash`` records agy + the exact model slug, not the default.

    This pins the full readable surface end to end: the ``#agy_flash`` xprompt
    expands to the ``agy_flash`` token, the configured custom alias rewrites
    that token to ``agy/gemini-3.5-flash-high``, and the recorded metadata
    routes to the Antigravity provider even though the configured default
    provider is Codex. It is the regression guard for the bug where the removed
    alias silently degraded these presets to the default provider.
    """
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260628120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    config = {
        "provider": "codex",
        "model_aliases": {
            "custom": {
                "agy_flash": {
                    "model": f"agy/{_AGY_FLASH35_HIGH}",
                    "description": "Antigravity flash preset.",
                }
            }
        },
    }
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    # The `#agy_flash` preset expands to the `agy_flash` alias token; inject just
    # that xprompt so the test does not depend on the live user config.
    from sase.xprompt.models import XPrompt

    monkeypatch.setattr(
        "sase.xprompt.processor.get_all_xprompts",
        lambda *_args, **_kwargs: {
            "agy_flash": XPrompt(name="agy_flash", content="agy_flash"),
        },
    )

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.ace.agent_tribes.update_agent_tribe"),
    ):
        info = extract_directives_and_write_meta(
            "%model:@#agy_flash\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert info.llm_provider == "agy"
    assert info.model == _AGY_FLASH35_HIGH
    assert meta["llm_provider"] == "agy"
    assert meta["model"] == _AGY_FLASH35_HIGH


def test_agy_default_retry_config_matches_transient_failures() -> None:
    config = get_retry_config("agy")

    assert config is not None
    assert config.max_retries == 3
    assert config.preserve_workspace is True
    # Representative Google-stack transport/rate-limit/timeout failures retry.
    assert is_retryable_error("RESOURCE_EXHAUSTED: quota exceeded", config)
    assert is_retryable_error("rpc error: DEADLINE_EXCEEDED", config)
    assert is_retryable_error("HTTP 503 UNAVAILABLE", config)
    assert is_retryable_error("hit the model rate limit", config)
    # A genuine logic error is not retried.
    assert not is_retryable_error("unknown model name", config)


# --- Phase 4: skills and runtime instruction support ---


@pytest.mark.parametrize("argv", [["skill", "init"], ["init", "skills"]])
def test_skill_init_parser_accepts_agy_provider(argv: list[str]) -> None:
    """``sase skill init -p agy`` (and the ``init skills`` alias) parse cleanly."""
    parser = create_parser()

    args = parser.parse_args([*argv, "-p", "agy"])

    assert args.provider == "agy"


def test_skill_init_unknown_provider_is_rejected_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Provider validation happens in the handler, not at parser build time."""
    parser = create_parser()

    args = parser.parse_args(["skill", "init", "-p", "not-a-provider"])

    assert args.provider == "not-a-provider"
    monkeypatch.setattr(init_skills_handler, "_all_providers", lambda: ["agy"])
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    assert init_skills_handler.run_init_skills(args) == 2
    assert (
        "unknown provider 'not-a-provider'; registered providers: agy"
        in capsys.readouterr().err
    )


def test_init_skills_provider_filter_accepts_agy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--provider agy`` routes generated skills to the Antigravity subpath."""
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        init_skills_handler.shutil,
        "which",
        lambda command: None if command == "prettier" else f"/usr/bin/{command}",
    )

    args = Namespace(
        dry_run=True,
        force=False,
        no_apply=False,
        no_commit=False,
        no_push=False,
        provider="agy",
    )

    with pytest.raises(SystemExit) as exc_info:
        init_skills_handler.handle_init_skills_command(args)

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    # Antigravity skills land under the documented ~/.gemini/antigravity-cli tree.
    assert ".gemini/antigravity-cli/skills/" in captured.out


def test_core_skills_generated_for_agy_under_antigravity_subpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real generation pass gives ``agy`` the core SASE skills, not hg_commit.

    This is the Phase 4 smoke check: after ``sase skill init`` the Antigravity
    runtime can see ``/sase_git_commit`` and the other provider-neutral core
    skills under ``~/.gemini/antigravity-cli/skills/``. ``sase_hg_commit`` stays
    Gemini-only (``skill: [gemini]``), so it must NOT be deployed for ``agy``.
    """
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _command: None)

    args = Namespace(
        dry_run=False,
        force=True,
        no_apply=False,
        no_commit=False,
        no_push=False,
        provider="agy",
    )

    with pytest.raises(SystemExit) as exc_info:
        init_skills_handler.handle_init_skills_command(args)
    assert exc_info.value.code == 0

    for skill_name in (
        "sase_git_commit",
        "sase_plan",
        "sase_questions",
        "sase_memory_read",
    ):
        target = _get_target_path("agy", skill_name, use_chezmoi=False)
        assert target.exists(), f"{skill_name} not generated for agy: {target}"
        assert ".gemini/antigravity-cli/skills/" in str(target)

    hg_target = _get_target_path("agy", "sase_hg_commit", use_chezmoi=False)
    assert not hg_target.exists(), "sase_hg_commit must stay Gemini-only"


def test_commit_finalizer_skill_is_vcs_resolved_for_agy_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The commit finalizer stays provider-neutral; ``agy`` needs no stop hook.

    The commit skill is resolved from the detected VCS provider, never from the
    LLM runtime, so an Antigravity agent in a git repo is told to use
    ``/sase_git_commit`` exactly like Claude and Codex.
    """
    monkeypatch.delenv("SASE_COMMIT_SKILL", raising=False)
    monkeypatch.setenv("SASE_VCS_PROVIDER", "auto")
    monkeypatch.setenv("SASE_LLM_PROVIDER", "agy")

    with patch("sase.commit_instructions.detect_vcs", return_value="git") as detect:
        assert _resolve_commit_skill_name(str(tmp_path)) == "/sase_git_commit"

    # Resolution keys off the VCS provider, not the agy LLM runtime.
    detect.assert_called_once_with(str(tmp_path))
