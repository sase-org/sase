"""Chat persistence and transcript metadata helpers for agent finalization."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from collections.abc import Callable

from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    canonical_plan_chain_suffix,
    plan_chain_agent_name,
)

XpromptLinker = Callable[..., str]


def final_done_agent_name(ctx: AgentExecContext, state: LoopState) -> str | None:
    if state.agent_step <= 1 or not ctx.agent_name:
        return ctx.agent_name
    plan_chain_suffix = canonical_plan_chain_suffix(state.current_role_suffix)
    if plan_chain_suffix is not None:
        return plan_chain_agent_name(ctx.agent_name, plan_chain_suffix)
    return f"{ctx.agent_name}.{state.agent_step}"


def link_saved_chats(state: LoopState, saved_path: str) -> None:
    state.saved_chat_paths.append(
        (state.current_role_suffix or PLAN_CHAIN_CODER_SUFFIX, saved_path)
    )
    if len(state.saved_chat_paths) <= 1:
        return
    from sase.history.chat_links import append_links_to_chat, build_linked_chats_section

    for role, path in state.saved_chat_paths:
        links_section = build_linked_chats_section(
            state.saved_chat_paths, current_role=role
        )
        append_links_to_chat(os.path.expanduser(path), links_section)


def read_plan_path(artifacts_dir: str) -> str | None:
    plan_path_file = os.path.join(artifacts_dir, "plan_path.json")
    try:
        with open(plan_path_file, encoding="utf-8") as f:
            return json.load(f).get("plan_path")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def load_prompt_renderings(
    ctx: AgentExecContext,
    state: LoopState,
    *,
    link_xprompt_prompt: XpromptLinker | None = None,
) -> tuple[str | None, str | None]:
    """Load the panel's XPrompt and rendered prompt for chat persistence."""

    if link_xprompt_prompt is None:
        link_xprompt_prompt = rewrite_xprompt_links

    current_dir = Path(state.current_artifacts_dir or ctx.artifacts_dir)
    fallback_dir = Path(ctx.artifacts_dir)
    candidates = (
        (current_dir,)
        if current_dir == fallback_dir
        else (
            current_dir,
            fallback_dir,
        )
    )

    xprompt_prompt: str | None = None
    xprompt_dir = current_dir
    for directory in candidates:
        content = _read_text(directory / "raw_xprompt.md")
        if content is not None:
            xprompt_prompt = content
            xprompt_dir = directory
            break

    from sase.agent.artifact_files_cache import ArtifactFileCache

    cache = ArtifactFileCache()
    rendered_prompt: str | None = None
    for directory in candidates:
        selected = cache.select_prompt_file(
            str(directory),
            is_workflow_child=False,
            step_name=None,
        )
        if selected is not None:
            rendered_prompt = cache.read_text(selected)
            break

    if xprompt_prompt is not None:
        xprompt_prompt = link_xprompt_prompt(
            xprompt_prompt,
            artifacts_dir=xprompt_dir,
            workspace_dir=Path(ctx.workspace_dir),
            project_name=ctx.project_name,
        )
    return xprompt_prompt, rendered_prompt


def rewrite_xprompt_links(
    prompt: str,
    *,
    artifacts_dir: Path,
    workspace_dir: Path,
    project_name: str,
) -> str:
    """Best-effort hosted link rewriting for one stored XPrompt prompt."""

    try:
        from sase.agents_sync.git import run_git
        from sase.agents_sync.prompt_archive.preparation import repository_roots
        from sase.sdd.hosted_links import HostedLinkResolver
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store
        from sase.xprompt_links import (
            XpromptTargetResolver,
            load_xprompt_source_records,
            rewrite_xprompt_source_links,
        )

        records = load_xprompt_source_records(artifacts_dir)
        if not records:
            return prompt
        primary_root, workspace_num = workspace_context_for_plan_resolution(
            workspace_dir
        )
        revision_result = run_git(
            primary_root,
            ["rev-parse", "HEAD"],
            op="chat_history.xprompt_revision",
        )
        primary_revision = revision_result.stdout.strip()
        if revision_result.returncode != 0 or not primary_revision:
            return prompt
        store = resolve_sdd_store(primary_root, workspace_num)
        hosted = HostedLinkResolver(
            store,
            project=project_name,
            primary_root=primary_root,
            git_runner=run_git,
        )
        resolver = XpromptTargetResolver(
            primary_root=primary_root,
            primary_revision=primary_revision,
            hosted=hosted,
            git_runner=run_git,
            repository_roots=repository_roots(),
        )
        return rewrite_xprompt_source_links(prompt, records, resolver)
    except Exception:
        return prompt


def read_retry_handoff_meta(
    ctx: AgentExecContext,
) -> tuple[str | None, str | None, str | None]:
    try:
        meta_path = os.path.join(ctx.artifacts_dir, "agent_meta.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, None, None
    if not isinstance(meta, dict):
        return None, None, None
    return (
        meta.get("retried_as_timestamp"),
        meta.get("retry_chain_root_timestamp"),
        meta.get("retry_error_category"),
    )


def read_transcript_agent_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def metadata_str(meta: dict[str, Any], key: str) -> str | None:
    value = meta.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def final_transcript_model_provider(
    ctx: AgentExecContext,
    state: LoopState,
    tracker: RetryTracker,
    fallback_model_override: str | None,
) -> tuple[str | None, str | None]:
    latest_meta = read_transcript_agent_meta(state.current_artifacts_dir)
    model = metadata_str(latest_meta, "model") or ctx.agent_model
    llm_provider = metadata_str(latest_meta, "llm_provider") or ctx.agent_llm_provider

    fallback_model = fallback_model_override
    if fallback_model is None and tracker.using_fallback and tracker.retry_cfg:
        fallback_model = tracker.retry_cfg.fallback_model
    if fallback_model:
        try:
            from sase.llm_provider.registry import resolve_model_provider

            resolved_provider, resolved_model = resolve_model_provider(fallback_model)
        except Exception:
            resolved_provider, resolved_model = None, fallback_model
        model = resolved_model
        if resolved_provider:
            llm_provider = resolved_provider

    return model, llm_provider


def final_execution_provider(state: LoopState) -> str | None:
    latest_meta = read_transcript_agent_meta(state.current_artifacts_dir)
    return metadata_str(latest_meta, "exec_llm_provider")
