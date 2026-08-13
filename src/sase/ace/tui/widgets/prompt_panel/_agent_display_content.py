"""General content render helpers for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from rich.text import Text

from sase.agent.artifact_files_cache import get_global_cache
from sase.core.time import get_timezone, to_local
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    agent_family_role_for_suffix,
    agent_family_suffix_token,
    canonical_plan_chain_suffix,
    plan_chain_feedback_round,
)

from ...models.agent import Agent, AttemptRecord
from ...util.lazy_syntax import lazy_renderable


_PHASE_LABELS = {
    PLAN_CHAIN_PLAN_SUFFIX: "PLANNER",
    PLAN_CHAIN_CODER_SUFFIX: "CODER",
    PLAN_CHAIN_QUESTION_SUFFIX: "QUESTIONS",
    PLAN_CHAIN_EPIC_SUFFIX: "EPIC",
    PLAN_CHAIN_COMMIT_SUFFIX: "COMMIT",
}


def render_timestamp_divider(iso_timestamp: str) -> Text:
    """Create a styled timestamp divider: ``--- HH:MM:SS ---...---``."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        local_dt = dt.astimezone(get_timezone())
        time_str = local_dt.strftime("%H:%M:%S")
    except (ValueError, OSError):
        time_str = "??:??:??"
    prefix = f"\u2500\u2500\u2500 {time_str} "
    suffix_len = 50 - len(prefix)
    divider = Text()
    divider.append(prefix + "\u2500" * suffix_len + "\n", style="dim #D7D7FF")
    return divider


def get_phase_label(agent: Agent) -> str:
    """Map role_suffix to human-readable phase label."""
    suffix = canonical_plan_chain_suffix(agent.role_suffix)
    role = agent_family_role_for_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )
    is_promoted_root = agent.agent_family_role == "root" and not agent.plan_chain_root
    if role == "q" and not is_promoted_root:
        return "QUESTIONS"
    if role == "code":
        return "CODER"
    if role == "epic":
        return "EPIC"
    if role == "commit":
        return "COMMIT"
    if role == "monitor":
        return "MONITOR"
    if role == "plan":
        return "PLANNER"
    if suffix in _PHASE_LABELS:
        return _PHASE_LABELS[suffix]
    feedback_round = plan_chain_feedback_round(
        suffix,
        agent_family_role=agent.agent_family_role,
    )
    if feedback_round is not None:
        return f"PLANNER (round {feedback_round})"
    token = agent_family_suffix_token(agent.role_suffix)
    if token is not None:
        return f"AGENT ({token})"
    return "AGENT"


def render_attempt_divider(
    attempt: AttemptRecord | None,
    *,
    is_current: bool,
    fallback_model: str | None = None,
) -> Text:
    """Create a styled attempt divider.

    ``attempt=None`` with ``is_current=True`` produces the CURRENT/FINAL
    divider for the root live_reply. A record with ``status="raised"`` is
    the terminal failure — rendered with the current-attempt color since
    its content lives at the root.
    """
    divider = Text()
    if attempt is None:
        label = "ATTEMPT (current)"
        time_str = "??:??:??"
        color = "#AF87FF"
    else:
        label = f"ATTEMPT {attempt.attempt_number}"
        if attempt.used_fallback and attempt.model:
            label += f" via fallback → {attempt.model}"
        elif is_current and fallback_model:
            label += f" via fallback → {fallback_model}"
        try:
            time_str = attempt.start_hhmmss
        except (ValueError, OSError):
            time_str = "??:??:??"
        if is_current:
            color = "#AF87FF"
        else:
            color = "#FF8700"

    divider.append("─── ", style=f"dim {color}")
    divider.append(label, style=f"bold {color}")
    divider.append(f" ─── {time_str} ", style=f"dim {color}")
    used = 4 + len(label) + 5 + len(time_str) + 1
    remaining = max(50 - used, 3)
    divider.append("─" * remaining + "\n", style=f"dim {color}")
    if attempt is not None and attempt.status == "failed" and attempt.error_snippet:
        divider.append(f"  ✗ {attempt.error_snippet}\n", style="dim italic #FF5F5F")
    elif attempt is not None and attempt.status == "raised" and attempt.error_snippet:
        divider.append(f"  ✗ {attempt.error_snippet}\n", style="dim italic #FF5F5F")
    return divider


def render_phase_divider(label: str, start_time: datetime | None) -> Text:
    """Create a styled phase divider: ``--- LABEL --- HH:MM:SS ---...---``."""
    if start_time:
        try:
            # ``start_time`` is a naive configured-tz model datetime (run/start
            # time); ``to_local`` displays it verbatim (and converts if an aware
            # value is ever passed) instead of misreading naive as system tz.
            time_str = to_local(start_time).strftime("%H:%M:%S")
        except (ValueError, OSError):
            time_str = "??:??:??"
    else:
        time_str = "??:??:??"
    divider = Text()
    divider.append("\u2500\u2500\u2500 ", style="dim #AF87FF")
    divider.append(label, style="bold #AF87FF")
    divider.append(f" \u2500\u2500\u2500 {time_str} ", style="dim #AF87FF")
    used = 4 + len(label) + 5 + len(time_str) + 1
    remaining = max(50 - used, 3)
    divider.append("\u2500" * remaining + "\n", style="dim #AF87FF")
    return divider


def render_agent_reply_content(
    agent: Agent,
    render_markdown: Callable[[str], object] | None = None,
) -> list[object]:
    """Render one agent's reply (chunks, live reply, or response)."""
    render_markdown = render_markdown or (
        lambda content: lazy_renderable(content, "markdown")
    )
    renderables: list[object] = []
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            renderables.append(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
                renderables.append(render_markdown(content))
        return renderables
    live_reply = agent.get_live_reply_content()
    if live_reply:
        renderables.append(render_markdown(live_reply))
        return renderables
    response_content = agent.get_response_content()
    if response_content:
        renderables.append(render_markdown(response_content))
        return renderables
    chat_response = agent.get_chat_response_content()
    if chat_response:
        renderables.append(render_markdown(chat_response))
        return renderables
    return renderables


def get_prompt_content(agent: Agent) -> str | None:
    """Get the prompt content for the agent.

    Returns:
        Prompt content, or None if not found.
    """
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return None

    cache = get_global_cache()
    selected = cache.select_prompt_file(
        artifacts_dir,
        is_workflow_child=agent.is_workflow_child,
        step_name=agent.step_name,
    )
    if selected is None:
        return None
    return cache.read_text(selected)
