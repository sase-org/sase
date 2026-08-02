"""Tests for run_agent_exec transcript metadata finalization."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import LoopState, _finalize_loop
from sase.axe.run_agent_exec_finalize import _link_xprompt_prompt
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


def test_finalize_loop_stores_selected_prompt_renderings(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "raw_xprompt.md").write_text("#plan implement", encoding="utf-8")
    (artifacts / "codex_prompt.md").write_text("rendered prompt", encoding="utf-8")
    state = LoopState(
        current_prompt="loop prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="loop prompt",
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
            "sase.axe.run_agent_exec_finalize._link_xprompt_prompt",
            return_value="[#plan](https://example.test/plan) implement",
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

    assert captured["xprompt_prompt"] == (
        "[#plan](https://example.test/plan) implement"
    )
    assert captured["rendered_prompt"] == "rendered prompt"


def test_link_xprompt_prompt_uses_captured_provenance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    source = workspace / "sase/xprompts/plan.md"
    source.parent.mkdir(parents=True)
    source.write_text("definition", encoding="utf-8")
    (artifacts / "xprompt_sources.json").write_text(
        json.dumps(
            [
                {
                    "schema_version": 1,
                    "raw_ref": "#plan",
                    "name": "plan",
                    "kind": "xprompt",
                    "source_kind": "markdown",
                    "source_path": str(source),
                    "definition_line": 7,
                    "repo": "sase",
                    "repo_root": str(workspace),
                    "repo_relpath": "sase/xprompts/plan.md",
                    "chezmoi": False,
                    "skipped_reason": None,
                }
            ]
        ),
        encoding="utf-8",
    )

    git_result = subprocess.CompletedProcess(
        ["git", "rev-parse", "HEAD"],
        0,
        "abc123\n",
        "",
    )
    hosted = SimpleNamespace(
        blob_url_for_repository=lambda root, revision, relpath: (
            f"https://example.test/blob/{revision}/{relpath}"
        )
    )
    with (
        patch("sase.agents_sync.git.run_git", return_value=git_result),
        patch(
            "sase.agents_sync.prompt_archive.preparation.repository_roots",
            return_value={"sase": workspace},
        ),
        patch("sase.sdd.hosted_links.HostedLinkResolver", return_value=hosted),
        patch(
            "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
            return_value=(workspace, 1),
        ),
        patch("sase.sdd.store.resolve_sdd_store", return_value=object()),
    ):
        rewritten = _link_xprompt_prompt(
            "Use #plan now",
            artifacts_dir=artifacts,
            workspace_dir=workspace,
            project_name="sase",
        )

    assert rewritten == (
        "Use [#plan](https://example.test/blob/abc123/sase/xprompts/plan.md#L7) now"
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
