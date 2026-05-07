"""Cross-provider integration coverage for Qwen and OpenCode."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.text import Text

from sase.ace.tui.modals.model_picker_modal import _build_model_options
from sase.ace.tui.modals.plan_approval_modal import _provider_badge_markup
from sase.ace.tui.widgets.prompt_panel._helpers import append_model_field
from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.llm_provider.registry import (
    model_short_alias_map,
    model_to_provider_map,
    provider_cli_status_color_map,
    provider_short_name_map,
    resolve_model_provider,
)
from sase.llm_provider.temporary_override import (
    set_temporary_override,
)
from sase.main import init_skills_handler


def test_provider_metadata_aggregation_includes_qwen_and_opencode() -> None:
    models = model_to_provider_map()
    provider_shorts = provider_short_name_map()
    model_aliases = model_short_alias_map()

    assert models["qwen3-coder-plus"] == "qwen"
    assert models["anthropic/claude-sonnet-4-5"] == "opencode"
    assert provider_shorts["qwen"] == "qwn"
    assert provider_shorts["opencode"] == "opc"
    assert model_aliases["qwen3-coder-plus"] == "qwen3cp"
    assert model_aliases["anthropic/claude-sonnet-4-5"] == "sonnet45"
    assert provider_cli_status_color_map()["qwen"] == "#7CFF6B"
    assert provider_cli_status_color_map()["opencode"] == "#FFB454"


def test_nested_opencode_model_resolution_preserves_provider_local_model() -> None:
    assert resolve_model_provider("opencode/anthropic/claude-sonnet-4-5") == (
        "opencode",
        "anthropic/claude-sonnet-4-5",
    )


def test_model_picker_includes_qwen_and_opencode_models() -> None:
    option_ids = {option.id for option in _build_model_options() if option is not None}

    assert "qwen3-coder-plus" in option_ids
    assert "anthropic/claude-sonnet-4-5" in option_ids


def test_prompt_panel_model_field_infers_qwen_provider() -> None:
    text = Text()

    append_model_field(text, "qwen3-coder-plus", None)

    assert text.plain == "Model: QWEN(qwen3-coder-plus)\n"


def test_prompt_panel_model_field_renders_opencode_provider() -> None:
    text = Text()

    append_model_field(text, "anthropic/claude-sonnet-4-5", "opencode")

    assert text.plain == "Model: OPENCODE(anthropic/claude-sonnet-4-5)\n"


def test_plan_approval_badge_renders_new_provider_colors() -> None:
    qwen = _provider_badge_markup("qwen", "qwen3-coder-plus")
    opencode = _provider_badge_markup("opencode", "anthropic/claude-sonnet-4-5")

    assert "QWEN" in qwen
    assert "#7CFF6B" in qwen
    assert "OPENCODE" in opencode
    assert "#FFB454" in opencode


def test_temporary_override_accepts_nested_opencode_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    override = set_temporary_override(
        "opencode/anthropic/claude-sonnet-4-5",
        60.0,
        source="test",
    )

    assert override.provider == "opencode"
    assert override.model == "anthropic/claude-sonnet-4-5"
    assert override.raw_model == "opencode/anthropic/claude-sonnet-4-5"


def test_agent_metadata_records_qwen_model_directive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260507120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.ace.agent_tags.update_agent_tag"),
    ):
        info = extract_directives_and_write_meta(
            "%model:qwen/qwen3-coder-plus\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert info.llm_provider == "qwen"
    assert info.model == "qwen3-coder-plus"
    assert meta["llm_provider"] == "qwen"
    assert meta["model"] == "qwen3-coder-plus"


def test_agent_metadata_records_nested_opencode_model_directive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260507120100"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.ace.agent_tags.update_agent_tag"),
    ):
        info = extract_directives_and_write_meta(
            "%model:opencode/anthropic/claude-sonnet-4-5\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert info.llm_provider == "opencode"
    assert info.model == "anthropic/claude-sonnet-4-5"
    assert meta["llm_provider"] == "opencode"
    assert meta["model"] == "anthropic/claude-sonnet-4-5"


@pytest.mark.parametrize("provider", ["qwen", "opencode"])
def test_init_skills_provider_filter_accepts_new_providers(
    provider: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
        provider=provider,
    )

    with pytest.raises(SystemExit) as exc_info:
        init_skills_handler.handle_init_skills_command(args)

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert f".{provider}" in captured.out or "opencode" in captured.out
