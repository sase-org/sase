"""Spawn-on-retry machinery: hand a failing agent's state off to a fresh
detached child agent, as if `sase run -d` had been invoked.

Used by :mod:`sase.axe.run_agent_exec_retry` when the active provider's
``ProviderRetryConfig.spawn_new_agent`` flag is set. The failing parent
process snapshots its retry handoff to disk, transfers its workspace claim
to the child, marks itself ``FAILED`` with a forward pointer, and exits.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState
    from sase.axe.run_agent_exec_retry import RetryTracker

RETRY_HANDOFF_FILENAME = "retry_handoff.json"

# Env vars consumed by the spawned child runner to switch into "retry mode".
ENV_RETRY_HANDOFF = "SASE_AGENT_RETRY_HANDOFF"
ENV_RETRY_OF_TIMESTAMP = "SASE_AGENT_RETRY_OF_TIMESTAMP"
ENV_RETRY_ATTEMPT = "SASE_AGENT_RETRY_ATTEMPT"
ENV_RETRY_CHAIN_ROOT_TIMESTAMP = "SASE_AGENT_RETRY_CHAIN_ROOT_TIMESTAMP"


@dataclass
class RetryHandoff:
    """Handoff manifest written by a failing parent and read by its retry child.

    The child runner consumes this at startup to seed its initial LoopState
    so file edits, plan paths, and in-flight Q&A are preserved across the
    process boundary.
    """

    parent_timestamp: str
    retry_attempt: int
    chain_root_timestamp: str
    error_snippet: str
    error_category: str
    continuation_prompt: str | None
    original_prompt: str
    chat_path: str | None
    plan_path: str | None
    role_suffix: str | None
    workspace_num: int
    workspace_dir: str
    vcs_ref: list[str] | None
    cl_name: str
    project_file: str
    project_name: str
    update_target: str
    is_home_mode: bool
    agent_name: str | None
    agent_model: str | None
    agent_llm_provider: str | None
    agent_vcs_provider: str | None
    fallback_model: str | None
    use_fallback: bool
    qa_sections: list[str] = field(default_factory=list)
    feedback_bullets: list[str] = field(default_factory=list)

    def write_to(self, artifacts_dir: str) -> str:
        """Write the handoff to ``artifacts_dir/retry_handoff.json``.

        Returns the path written.
        """
        path = Path(artifacts_dir) / RETRY_HANDOFF_FILENAME
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return str(path)

    @classmethod
    def read_from_path(cls, handoff_path: str) -> RetryHandoff | None:
        try:
            with open(handoff_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        try:
            return cls(**data)
        except TypeError:
            return None


def _classify_error(snippet: str) -> str:
    """Classify the error so the TUI can label retry rows."""
    text = snippet.lower()
    # Context overflow: matches Anthropic's "Prompt is too long" and any
    # variant mentioning context/overflow/limit.
    if (
        "prompt is too long" in text
        or "context length" in text
        or "context window" in text
        or ("context" in text and ("overflow" in text or "limit" in text))
        or ("too long" in text and ("prompt" in text or "context" in text))
    ):
        return "context_overflow"
    if "rate limit" in text or "429" in text or "quota" in text:
        return "rate_limit"
    if (
        "transient" in text
        or "temporarily" in text
        or "overloaded" in text
        or "503" in text
        or "502" in text
    ):
        return "transient"
    return "other"


def _read_plan_path(artifacts_dir: str) -> str | None:
    plan_path_file = Path(artifacts_dir) / "plan_path.json"
    try:
        with open(plan_path_file, encoding="utf-8") as f:
            return json.load(f).get("plan_path")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _read_existing_handoff(artifacts_dir: str) -> RetryHandoff | None:
    """If parent itself was already a retry, walk back to find the chain root."""
    handoff_path = Path(artifacts_dir) / RETRY_HANDOFF_FILENAME
    if not handoff_path.exists():
        return None
    return RetryHandoff.read_from_path(str(handoff_path))


def _vcs_ref_from_tag(vcs_tag: str | None) -> list[str] | None:
    """Resolve a vcs_tag like ``"#gh:sase"`` to ``["gh", "sase"]``.

    Iterates the registered workflow ref patterns to find the workflow name
    that produced the tag, returning ``None`` when the tag doesn't match any
    registered workflow.
    """
    if not vcs_tag:
        return None
    try:
        from sase.workspace_provider import get_ref_patterns
    except Exception:
        return None
    for wf_name, pattern in get_ref_patterns().items():
        m = pattern.search(vcs_tag)
        if m is None:
            continue
        ref_value = m.group(1) or m.group(2)
        if ref_value:
            return [wf_name, ref_value]
    return None


def _build_handoff(
    *,
    ctx: AgentExecContext,
    state: LoopState,
    tracker: RetryTracker,
    error_snippet: str,
    continuation_prompt: str | None,
) -> RetryHandoff:
    """Construct a :class:`RetryHandoff` from the failing parent's state."""
    saved_chat_path = os.environ.get("SASE_AGENT_CHAT_PATH")
    plan_path = _read_plan_path(state.current_artifacts_dir or ctx.artifacts_dir)

    # Walk back through prior handoffs to find the chain root.
    parent_handoff = _read_existing_handoff(ctx.artifacts_dir)
    if parent_handoff is not None:
        chain_root = parent_handoff.chain_root_timestamp
        retry_attempt = parent_handoff.retry_attempt + 1
    else:
        chain_root = ctx.artifacts_timestamp
        retry_attempt = 1

    vcs_ref = _vcs_ref_from_tag(ctx.vcs_tag)

    return RetryHandoff(
        parent_timestamp=ctx.artifacts_timestamp,
        retry_attempt=retry_attempt,
        chain_root_timestamp=chain_root,
        error_snippet=error_snippet,
        error_category=_classify_error(error_snippet),
        continuation_prompt=continuation_prompt,
        original_prompt=state.original_prompt,
        chat_path=saved_chat_path,
        plan_path=plan_path,
        role_suffix=state.current_role_suffix or None,
        workspace_num=ctx.workspace_num,
        workspace_dir=ctx.workspace_dir,
        vcs_ref=vcs_ref,
        cl_name=ctx.cl_name,
        project_file=ctx.project_file,
        project_name=ctx.project_name,
        update_target=ctx.update_target,
        is_home_mode=ctx.is_home_mode,
        agent_name=ctx.agent_name,
        agent_model=ctx.agent_model,
        agent_llm_provider=ctx.agent_llm_provider,
        agent_vcs_provider=ctx.agent_vcs_provider,
        fallback_model=tracker.retry_cfg.fallback_model if tracker.retry_cfg else None,
        use_fallback=tracker.using_fallback,
    )


def _build_resume_prompt(handoff: RetryHandoff) -> str:
    """Construct the prompt the child agent will receive.

    Format::

        #resume:<parent_agent_name>      (only if name was set)
        <continuation_prompt>            (e.g. context-overflow nudge)
        <original_prompt>                (the prompt the parent ran with)
    """
    parts: list[str] = []
    if handoff.agent_name:
        parts.append(f"#resume:{handoff.agent_name}")
    elif handoff.chat_path:
        # No stable name — fall back to a chat-path resume directive
        parts.append(f"#resume_chat:{handoff.chat_path}")
    if handoff.continuation_prompt:
        parts.append(handoff.continuation_prompt)
    parts.append(handoff.original_prompt)
    return "\n\n".join(p for p in parts if p)


def spawn_retry_agent(
    *,
    ctx: AgentExecContext,
    state: LoopState,
    tracker: RetryTracker,
    error_snippet: str,
    continuation_prompt: str | None,
) -> dict[str, Any] | None:
    """Spawn a fresh detached child agent to retry the failing parent.

    Returns a dict with the child's metadata (timestamp, pid, retry_attempt,
    chain_root_timestamp, handoff_path) on success.  Returns ``None`` if
    spawn-side failure occurred and the caller should fall back to in-process
    retry.
    """
    from sase.agent.launcher import spawn_agent_subprocess
    from sase.core.agent_launch_facade import reserve_launch_timestamp_batch
    from sase.telemetry.metrics import RETRY_SPAWNS_TOTAL

    handoff = _build_handoff(
        ctx=ctx,
        state=state,
        tracker=tracker,
        error_snippet=error_snippet,
        continuation_prompt=continuation_prompt,
    )

    # Write handoff into the parent's artifacts dir so diagnostic tooling
    # and the loader can read it from the parent side.
    handoff_path = handoff.write_to(ctx.artifacts_dir)

    child_timestamp = reserve_launch_timestamp_batch(1)[0]
    child_workflow_name = f"ace(run)-{child_timestamp}"
    child_prompt = _build_resume_prompt(handoff)

    extra_env: dict[str, str] = {
        ENV_RETRY_HANDOFF: handoff_path,
        ENV_RETRY_OF_TIMESTAMP: handoff.parent_timestamp,
        ENV_RETRY_ATTEMPT: str(handoff.retry_attempt),
        ENV_RETRY_CHAIN_ROOT_TIMESTAMP: handoff.chain_root_timestamp,
    }
    # Carry the fallback model selection forward to the child process.
    if handoff.use_fallback and handoff.fallback_model:
        extra_env["SASE_MODEL_OVERRIDE"] = handoff.fallback_model

    vcs_ref_tuple: tuple[str, str] | None = (
        (handoff.vcs_ref[0], handoff.vcs_ref[1]) if handoff.vcs_ref else None
    )

    try:
        result = spawn_agent_subprocess(
            cl_name=ctx.cl_name,
            project_file=ctx.project_file,
            workspace_dir=ctx.workspace_dir,
            workspace_num=ctx.workspace_num,
            workflow_name=child_workflow_name,
            prompt=child_prompt,
            timestamp=child_timestamp,
            update_target=ctx.update_target,
            project_name=ctx.project_name,
            history_sort_key="",
            is_home_mode=ctx.is_home_mode,
            vcs_ref=vcs_ref_tuple,
            extra_env=extra_env,
            retry_transfer_from_pid=os.getpid(),
        )
    except RuntimeError as exc:
        # Couldn't claim/transfer workspace.  Caller falls back to in-process.
        print(f"[retry-spawn] Failed to spawn retry agent: {exc}")
        try:
            RETRY_SPAWNS_TOTAL.labels(outcome="failed").inc()
        except Exception:
            pass
        return None
    except Exception as exc:
        print(f"[retry-spawn] Unexpected error spawning retry agent: {exc}")
        try:
            RETRY_SPAWNS_TOTAL.labels(outcome="failed").inc()
        except Exception:
            pass
        return None

    try:
        RETRY_SPAWNS_TOTAL.labels(outcome="ok").inc()
    except Exception:
        pass

    from sase.artifacts import convert_timestamp_to_artifacts_format

    child_artifacts_timestamp = convert_timestamp_to_artifacts_format(child_timestamp)
    return {
        "pid": result.pid,
        "child_timestamp": child_timestamp,
        "child_artifacts_timestamp": child_artifacts_timestamp,
        "retry_attempt": handoff.retry_attempt,
        "chain_root_timestamp": handoff.chain_root_timestamp,
        "handoff_path": handoff_path,
        "error_category": handoff.error_category,
    }


def mark_parent_retried(
    *,
    artifacts_dir: str,
    child_artifacts_timestamp: str,
    chain_root_timestamp: str,
    handoff_path: str,
    error_category: str,
) -> None:
    """Update the parent's ``agent_meta.json`` with retry-chain forward pointers.

    Idempotent — safe to call even if agent_meta.json doesn't exist yet
    (it will be created with just these fields).
    """
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    data["retried_as_timestamp"] = child_artifacts_timestamp
    data["retry_terminal"] = True
    data["retry_handoff_path"] = handoff_path
    data["retry_chain_root_timestamp"] = chain_root_timestamp
    data["retry_error_category"] = error_category

    try:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass
