"""Tests for run_agent_exec transcript metadata finalization."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import LoopState, _finalize_loop
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.llm_provider.retry_config import ProviderRetryConfig

from tests._axe_run_agent_exec_helpers import make_exec_ctx


@pytest.fixture(autouse=True)
def clean_model_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_MODEL_OVERRIDE", raising=False)


def test_finalize_loop_passes_transcript_metadata_to_chat_history(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    ctx.agent_model = "sonnet"
    ctx.agent_llm_provider = "claude"
    ctx.multi_agent_prompt_file = "~/.sase/multi_prompts/202606/main.md"
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    captured: dict = {}

    def capture_save_chat(**kwargs):
        captured.update(kwargs)
        return str(tmp_path / "chat.md")

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            side_effect=capture_save_chat,
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert captured["metadata_agent"] == "agent"
    assert captured["metadata_model"] == "sonnet"
    assert captured["metadata_llm_provider"] == "claude"
    assert captured["metadata_multi_agent_prompt"] == (
        "~/.sase/multi_prompts/202606/main.md"
    )


def test_finalize_loop_prefers_latest_agent_meta_for_transcript_metadata(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    ctx.agent_model = "planner-model"
    ctx.agent_llm_provider = "planner-provider"
    followup = tmp_path / "followup"
    followup.mkdir()
    (followup / "agent_meta.json").write_text(
        json.dumps({"model": "coder-model", "llm_provider": "codex"}),
        encoding="utf-8",
    )
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="-code",
        current_artifacts_dir=str(followup),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
        agent_step=2,
    )
    captured: dict = {}

    def capture_save_chat(**kwargs):
        captured.update(kwargs)
        return str(tmp_path / "chat.md")

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            side_effect=capture_save_chat,
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert captured["metadata_agent"] == "agent--code"
    assert captured["metadata_model"] == "coder-model"
    assert captured["metadata_llm_provider"] == "codex"


def test_finalize_loop_uses_new_phase_question_suffix_for_agent_name(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="--code-0",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
        agent_step=3,
    )
    captured: dict = {}

    def capture_save_chat(**kwargs):
        captured.update(kwargs)
        return str(tmp_path / "chat.md")

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            side_effect=capture_save_chat,
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert captured["metadata_agent"] == "agent--code-0"


def test_finalize_loop_uses_retry_fallback_model_for_transcript_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    ctx.agent_model = "primary-model"
    ctx.agent_llm_provider = "claude"
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    tracker = RetryTracker(
        retry_cfg=ProviderRetryConfig(fallback_model="codex/o3"),
        using_fallback=True,
    )
    captured: dict = {}

    def capture_save_chat(**kwargs):
        captured.update(kwargs)
        return str(tmp_path / "chat.md")

    monkeypatch.setenv("SASE_MODEL_OVERRIDE", "codex/o3")
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            side_effect=capture_save_chat,
        ),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("codex", "o3"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            tracker,
            SimpleNamespace(response_text="done"),
        )

    assert captured["metadata_model"] == "o3"
    assert captured["metadata_llm_provider"] == "codex"
    assert "SASE_MODEL_OVERRIDE" not in os.environ
