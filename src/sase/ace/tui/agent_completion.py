"""Shared visible-agent completion candidates for the ACE TUI."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from sase.agent.status_buckets import status_bucket_for_values

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent


@dataclass(frozen=True, slots=True)
class AgentVcsWorkflow:
    """Display metadata for the VCS workflow tag used by an agent prompt."""

    tag: str
    workflow_type: str | None
    project: str | None
    provider_display: str | None
    style: str

    @property
    def display(self) -> str:
        return self.tag or "local"


@dataclass(frozen=True, slots=True)
class AgentCompletionCandidate:
    """A named visible agent that can be inserted into prompt syntax."""

    name: str
    label: str
    status: str
    runtime: str | None = None
    model: str | None = None
    start_time: str | None = None
    duration: str | None = None
    role: str | None = None
    tag: str | None = None
    vcs_workflow: AgentVcsWorkflow | None = None
    prompt_snippet: str = ""
    search_aliases: tuple[str, ...] = ()

    @property
    def wait_name(self) -> str:
        """Compatibility label used by the wait modal."""
        return self.name

    @property
    def search_text(self) -> str:
        return " ".join(
            (self.name, self.label, self.prompt_snippet, *self.search_aliases)
        ).lower()


_WORKFLOW_STYLES = (
    "#5FD7FF",
    "#00D7AF",
    "#D7AF87",
    "#AF87FF",
    "#FFD75F",
    "#FF87AF",
)
_FRONTMATTER_RE = re.compile(r"\A---[^\n]*\n.*?\n---\s*", re.DOTALL)
_DIRECTIVE_NAME_RE = re.compile(r"%[a-zA-Z_][a-zA-Z0-9_]*")
# When a family wait resolves to multiple agents, active work takes precedence
# over terminal states, and a successful terminal attempt satisfies the family.
_WAIT_DEPENDENCY_BUCKET_PRECEDENCE: tuple[str, ...] = (
    "Running",
    "Starting",
    "Waiting",
    "Done",
    "Stopped",
    "Failed",
)
_WAIT_DEPENDENCY_BUCKET_RANK = {
    bucket: index for index, bucket in enumerate(_WAIT_DEPENDENCY_BUCKET_PRECEDENCE)
}


def agent_prompt_name(agent: Agent) -> str | None:
    """Return the prompt-referenceable name for an agent row."""
    if _is_agent_family_root(agent):
        return agent.family_reference_name()
    return agent.agent_name


def _preferred_wait_dependency_bucket(current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    current_rank = _WAIT_DEPENDENCY_BUCKET_RANK.get(
        current,
        len(_WAIT_DEPENDENCY_BUCKET_RANK),
    )
    candidate_rank = _WAIT_DEPENDENCY_BUCKET_RANK.get(
        candidate,
        len(_WAIT_DEPENDENCY_BUCKET_RANK),
    )
    return candidate if candidate_rank < current_rank else current


def _collect_agent_status_buckets(agents: Iterable[Agent]) -> dict[str, str]:
    """Return prompt-referenceable agent names mapped to status buckets."""
    buckets: dict[str, str] = {}
    for agent in agents:
        bucket = status_bucket_for_values(agent.status)
        for name in (agent_prompt_name(agent), agent.agent_name):
            if not name or not name.strip():
                continue
            buckets[name] = _preferred_wait_dependency_bucket(
                buckets.get(name),
                bucket,
            )
    return buckets


def collect_agent_status_buckets(agents: Iterable[Agent]) -> dict[str, str]:
    """Return prompt-referenceable agent names mapped to status buckets."""
    return _collect_agent_status_buckets(agents)


def agent_status_buckets_for_app(app: object | None) -> dict[str, str] | None:
    """Return known prompt-referenceable agent status buckets for a TUI app."""
    if app is None:
        return None

    for attr_name in ("_agents_with_children", "_agents"):
        try:
            agents = getattr(app, attr_name, None)
        except Exception:
            continue
        if agents:
            return _collect_agent_status_buckets(agents)
    return None


def wait_dependencies_satisfied(
    agent: Agent, status_buckets: Mapping[str, str] | None
) -> bool:
    """Return whether every waited-for agent is known done."""
    from sase.ace.tui.models.agent_time import wait_display_agent

    wait_agent = wait_display_agent(agent)
    if not wait_agent.waiting_for:
        return True
    if status_buckets is None:
        return False
    return all(status_buckets.get(name) == "Done" for name in wait_agent.waiting_for)


def build_agent_completion_candidates(
    visible_agents: Iterable[Agent],
    *,
    exclude_identity: object | None = None,
) -> list[AgentCompletionCandidate]:
    """Build de-duplicated completion candidates from visible agent rows."""
    candidates: list[AgentCompletionCandidate] = []
    seen_names: set[str] = set()
    all_agents = list(visible_agents)
    for agent in all_agents:
        if exclude_identity is not None and agent.identity == exclude_identity:
            continue
        name = agent_prompt_name(agent)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        candidates.append(_candidate_from_agent(agent, name, all_agents))
    return candidates


def filter_agent_completion_candidates(
    candidates: Sequence[AgentCompletionCandidate] | None,
    partial: str,
) -> list[AgentCompletionCandidate]:
    """Return visible-agent candidates matching *partial* by name prefix."""
    if not candidates:
        return []
    partial_lower = partial.lower()
    return [
        candidate
        for candidate in candidates
        if candidate.name.lower().startswith(partial_lower)
    ]


def status_style(status: str) -> str:
    """Return the Rich style used for a status indicator."""
    status_upper = status.upper()
    if status_upper in {"RUNNING", "STARTING"}:
        return "bold #00D7AF"
    if status_upper == "WAITING":
        return "bold #AF87FF"
    if "DONE" in status_upper:
        return "bold #5FD7FF"
    if "FAILED" in status_upper:
        return "bold #FF5F5F"
    return "dim"


def neutral_vcs_workflow() -> AgentVcsWorkflow:
    """Return the neutral local workflow marker for rows without a VCS tag."""
    return AgentVcsWorkflow(
        tag="local",
        workflow_type=None,
        project=None,
        provider_display=None,
        style="dim",
    )


def _candidate_from_agent(
    agent: Agent,
    name: str,
    all_agents: Sequence[Agent],
) -> AgentCompletionCandidate:
    role = agent.agent_family_role or agent.role_suffix
    raw_prompt = _raw_prompt_for_agent(agent, all_agents)
    canonical_snippet = _prompt_snippet(raw_prompt, humanize=False)
    return AgentCompletionCandidate(
        name=name,
        label=agent.agent_name or agent.display_name or agent.cl_name or name,
        status=agent.status,
        runtime=agent.duration_display,
        model=_model_label(agent),
        start_time=agent.start_time_short,
        duration=agent.duration_display,
        role=role,
        tag=f"@{agent.tag}" if agent.tag else None,
        vcs_workflow=_vcs_workflow_from_prompt(raw_prompt),
        prompt_snippet=_prompt_snippet(raw_prompt),
        search_aliases=tuple(
            alias
            for alias in (
                canonical_snippet,
                _raw_vcs_tag_for_prompt(raw_prompt),
            )
            if alias
        ),
    )


def _is_agent_family_root(agent: Agent) -> bool:
    return agent.is_family_root_entry


def _model_label(agent: Agent) -> str | None:
    bits: list[str] = []
    if agent.llm_provider:
        bits.append(agent.llm_provider)
    if agent.model:
        bits.append(agent.model)
    label = " / ".join(bits) if bits else None
    if agent.reasoning_effort:
        return f"{label or ''}@{agent.reasoning_effort}".lstrip("@")
    return label


def _raw_prompt_for_agent(agent: Agent, all_agents: Sequence[Agent]) -> str:
    raw_content = agent.get_raw_xprompt_content() or ""
    if raw_content or not agent.parent_timestamp:
        return raw_content
    for parent in all_agents:
        if parent.raw_suffix == agent.parent_timestamp:
            return parent.get_raw_xprompt_content() or ""
    return ""


def _vcs_workflow_from_prompt(raw_prompt: str) -> AgentVcsWorkflow | None:
    if not raw_prompt:
        return None

    from sase.xprompt import extract_project_from_vcs_tag, extract_vcs_workflow_tag
    from sase.project_display_names import (
        humanize_vcs_refs_in_text,
        project_display_name_for,
    )

    body = _strip_leading_prompt_directives(_strip_frontmatter(raw_prompt))
    tag = extract_vcs_workflow_tag(body)
    if not tag:
        return None

    raw_tag = tag.strip()
    display_tag = humanize_vcs_refs_in_text(raw_tag)
    workflow_type = _workflow_type_from_vcs_tag(display_tag)
    provider_display = _provider_display(workflow_type)
    project = extract_project_from_vcs_tag(raw_tag)
    return AgentVcsWorkflow(
        tag=display_tag,
        workflow_type=workflow_type,
        project=project_display_name_for(project) if project else None,
        provider_display=provider_display,
        style=_workflow_style(workflow_type),
    )


def _raw_vcs_tag_for_prompt(raw_prompt: str) -> str:
    if not raw_prompt:
        return ""
    from sase.xprompt import extract_vcs_workflow_tag, find_vcs_workflow_tag

    body = _strip_leading_prompt_directives(_strip_frontmatter(raw_prompt))
    tag = extract_vcs_workflow_tag(body) or find_vcs_workflow_tag(body)
    return tag.strip() if tag else ""


def _workflow_type_from_vcs_tag(tag: str) -> str | None:
    if not tag.startswith("#"):
        return None
    body = tag[1:]
    for suffix in ("!!", "??"):
        body = body.replace(suffix, "", 1)
    separators = [
        idx for idx in (body.find(":"), body.find("_"), body.find("(")) if idx >= 0
    ]
    if separators:
        body = body[: min(separators)]
    if body.endswith("+"):
        body = body[:-1]
    return body or None


def _provider_display(workflow_type: str | None) -> str | None:
    if not workflow_type:
        return None
    try:
        from sase.workspace_provider import get_display_name

        return get_display_name(workflow_type) or workflow_type
    except Exception:
        return workflow_type


def _workflow_style(workflow_type: str | None) -> str:
    if not workflow_type:
        return "dim"
    index = sum(ord(char) for char in workflow_type) % len(_WORKFLOW_STYLES)
    return f"bold {_WORKFLOW_STYLES[index]}"


def _prompt_snippet(
    raw_prompt: str, *, max_len: int = 96, humanize: bool = True
) -> str:
    cleaned = _strip_frontmatter(raw_prompt)
    cleaned = _strip_leading_prompt_directives(cleaned)
    cleaned = _strip_leading_vcs_tag(cleaned)
    cleaned = _strip_leading_prompt_directives(cleaned)
    snippet = " ".join(cleaned.split())
    if humanize:
        from sase.project_display_names import humanize_vcs_refs_in_text

        snippet = humanize_vcs_refs_in_text(snippet)
    if len(snippet) <= max_len:
        return snippet
    if max_len <= 3:
        return snippet[:max_len]
    return snippet[: max_len - 3].rstrip() + "..."


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1).lstrip()


def _strip_leading_prompt_directives(text: str) -> str:
    from sase.xprompt._parsing import find_matching_paren_for_args

    current = text.lstrip()
    while current.startswith("%"):
        match = _DIRECTIVE_NAME_RE.match(current)
        if match is None:
            return current
        end = match.end()
        marker = current[end : end + 1]
        if marker == "(":
            close = find_matching_paren_for_args(current, end)
            if close is None:
                return current
            end = close + 1
        elif marker == ":":
            end += 1
            while end < len(current) and not current[end].isspace():
                end += 1
        elif marker == "+":
            end += 1

        next_text = current[end:].lstrip()
        if next_text == current:
            return current
        current = next_text
    return current


def _strip_leading_vcs_tag(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.startswith("#"):
        return stripped
    try:
        from sase.xprompt import strip_vcs_workflow_tag

        return strip_vcs_workflow_tag(stripped).lstrip()
    except Exception:
        return stripped


def visible_agent_completion_agents(app: object) -> list[Agent]:
    """Return agents currently visible across all Agents-tab panels."""
    from textual.css.query import NoMatches

    from sase.ace.tui.actions.agents._display_helpers import panel_widget_id
    from sase.ace.tui.models.agent_panels import agent_is_rendered_in_agents_panel
    from sase.ace.tui.widgets import AgentList

    panel_group = getattr(app, "_panel_group", None)
    panel_keys = getattr(panel_group, "panel_keys", [])
    panel_count = len(panel_keys)
    query_one = getattr(app, "query_one", None)
    if callable(query_one):
        visible: list[Agent] = []
        seen_identities: set[object] = set()
        queried_widget = False
        for panel_idx in range(panel_count):
            try:
                widget = query_one(f"#{panel_widget_id(panel_idx)}", AgentList)
            except NoMatches:
                continue
            queried_widget = True
            for agent in widget.visible_agents():
                if agent.identity in seen_identities:
                    continue
                seen_identities.add(agent.identity)
                visible.append(agent)
        if queried_widget:
            return visible

    agents = list(getattr(app, "_agents", []))
    order_fn = getattr(app, "_agents_visible_order", None)
    if callable(order_fn):
        try:
            return [agents[idx] for idx in order_fn() if 0 <= idx < len(agents)]
        except Exception:
            pass

    return [
        candidate
        for candidate in agents
        if agent_is_rendered_in_agents_panel(candidate)
    ]
