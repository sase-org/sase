"""Shared visible-agent completion candidates for the ACE TUI."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Literal

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
    """A visible prompt target that can be inserted into prompt syntax."""

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
    kind: Literal["agent", "family", "clan", "tribe"] = "agent"
    member_count: int | None = None
    aggregate_status: str | None = None
    member_names: tuple[str, ...] = ()
    agent_count: int | None = None
    clan_count: int | None = None

    @property
    def wait_name(self) -> str:
        """Compatibility label used by the wait modal."""
        return self.name

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.name,
                self.label,
                self.prompt_snippet,
                *self.member_names,
                *self.search_aliases,
            )
        ).lower()


@dataclass(frozen=True, slots=True)
class _ClanCompletionGroup:
    """Newest visible generation of one clan, derived without external reads."""

    name: str
    generation: str | None
    source_index: int
    container: Agent | None
    members: tuple[Agent, ...]
    tags: tuple[str, ...]


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
    """Build kind-aware completion candidates from one visible-row snapshot."""
    all_agents = list(visible_agents)
    clan_groups = _visible_clan_completion_groups(all_agents)
    clans = _build_clan_completion_candidates(
        clan_groups,
        exclude_identity=exclude_identity,
    )
    families = _build_family_completion_candidates(
        all_agents,
        exclude_identity=exclude_identity,
    )
    agents = _build_plain_agent_completion_candidates(
        all_agents,
        exclude_identity=exclude_identity,
    )
    tribes = _build_tribe_completion_candidates(all_agents, clan_groups)
    return _dedupe_completion_candidates([*tribes, *clans, *families, *agents])


def _dedupe_completion_candidates(
    candidates: Iterable[AgentCompletionCandidate],
) -> list[AgentCompletionCandidate]:
    ordered: list[AgentCompletionCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.name in seen:
            continue
        seen.add(candidate.name)
        ordered.append(candidate)
    return ordered


def _build_plain_agent_completion_candidates(
    all_agents: Sequence[Agent],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    """Return real, non-container rows in their existing visible order."""
    candidates: list[AgentCompletionCandidate] = []
    seen_names: set[str] = set()
    for agent in all_agents:
        if (
            agent.is_clan_container
            or agent.is_synthetic_planner
            or agent.is_family_root_entry
            or (exclude_identity is not None and agent.identity == exclude_identity)
        ):
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
    """Return prompt-target candidates matching *partial* by name prefix."""
    if not candidates:
        return []
    partial_lower = partial.lower()
    return [
        candidate
        for candidate in candidates
        if _candidate_matches_prefix(candidate, partial_lower)
    ]


def _candidate_matches_prefix(
    candidate: AgentCompletionCandidate,
    partial_lower: str,
) -> bool:
    if candidate.kind != "tribe" or partial_lower.startswith("@"):
        return candidate.name.lower().startswith(partial_lower)
    return candidate.name.removeprefix("@").lower().startswith(partial_lower)


def _visible_clan_completion_groups(
    all_agents: Sequence[Agent],
) -> list[_ClanCompletionGroup]:
    """Return each clan's newest visible generation in stable display order."""
    rows_by_key: dict[tuple[str, str | None], list[tuple[int, Agent]]] = {}
    for index, agent in enumerate(all_agents):
        if not agent.agent_clan:
            continue
        key = (agent.agent_clan, agent.agent_clan_generation)
        rows_by_key.setdefault(key, []).append((index, agent))

    groups_by_name: dict[str, list[_ClanCompletionGroup]] = {}
    for (name, generation), indexed_rows in rows_by_key.items():
        rows = [row for _index, row in indexed_rows]
        container = next((row for row in rows if row.is_clan_container), None)
        members = _clan_group_members(container, rows)
        if not members:
            continue
        groups_by_name.setdefault(name, []).append(
            _ClanCompletionGroup(
                name=name,
                generation=generation,
                source_index=min(index for index, _row in indexed_rows),
                container=container,
                members=members,
                tags=_clan_group_tags(container, rows),
            )
        )

    newest = [
        max(groups, key=_clan_group_recency_key) for groups in groups_by_name.values()
    ]
    newest.sort(key=lambda group: group.source_index)
    return newest


def _clan_group_recency_key(group: _ClanCompletionGroup) -> tuple[str, str]:
    row_recency = max((_agent_recency_key(row) for row in group.members), default="")
    return (group.generation or row_recency, row_recency)


def _agent_recency_key(agent: Agent) -> str:
    if agent.raw_suffix:
        return agent.raw_suffix
    if agent.start_time is not None:
        return agent.start_time.isoformat()
    return ""


def _clan_group_members(
    container: Agent | None,
    rows: Sequence[Agent],
) -> tuple[Agent, ...]:
    if container is not None:
        from sase.ace.tui.models._agent_clan_sections import clan_section_member_rows

        members = clan_section_member_rows(container)
        if members:
            return _dedupe_real_member_rows(members)
    return _dedupe_real_member_rows(row for row in rows if not row.is_clan_container)


def _clan_group_tags(
    container: Agent | None,
    rows: Sequence[Agent],
) -> tuple[str, ...]:
    tags: list[str] = []
    if container is not None:
        tags.extend(container.clan_tags)
        if container.clan_tribe:
            tags.append(container.clan_tribe)
        if container.tag:
            tags.append(container.tag)
    if not tags:
        tags.extend(row.clan_tribe or row.tag or "" for row in rows)
    return tuple(dict.fromkeys(tag for tag in tags if tag))


def _build_clan_completion_candidates(
    groups: Sequence[_ClanCompletionGroup],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    candidates: list[AgentCompletionCandidate] = []
    for group in groups:
        if exclude_identity is not None and any(
            member.identity == exclude_identity for member in group.members
        ):
            continue
        status = _aggregate_completion_status(group.members)
        candidates.append(
            AgentCompletionCandidate(
                name=group.name,
                label=group.name,
                status=status,
                kind="clan",
                member_count=len(group.members),
                aggregate_status=status,
                member_names=_member_names(group.members),
            )
        )
    return candidates


def _build_family_completion_candidates(
    all_agents: Sequence[Agent],
    *,
    exclude_identity: object | None,
) -> list[AgentCompletionCandidate]:
    from sase.ace.tui.models.agent_family_members import concrete_family_member_rows

    candidates: list[AgentCompletionCandidate] = []
    seen_names: set[str] = set()
    for agent in all_agents:
        if not agent.is_family_root_entry or agent.is_clan_container:
            continue
        name = agent.family_reference_name()
        if not name or name in seen_names:
            continue
        members = _dedupe_real_member_rows(concrete_family_member_rows(agent))
        if not members or (
            exclude_identity is not None
            and any(member.identity == exclude_identity for member in members)
        ):
            continue
        seen_names.add(name)
        status = _aggregate_completion_status(members)
        candidates.append(
            _candidate_from_agent(
                agent,
                name,
                all_agents,
                kind="family",
                member_count=len(members),
                aggregate_status=status,
                member_names=_member_names(members),
            )
        )
    return candidates


def _build_tribe_completion_candidates(
    all_agents: Sequence[Agent],
    clan_groups: Sequence[_ClanCompletionGroup],
) -> list[AgentCompletionCandidate]:
    """Build canonical ``@tribe`` targets from already-loaded rows and clans."""
    from sase.ace.tui.models.agent_family_members import concrete_family_member_rows

    clan_group_by_key = {(group.name, group.generation): group for group in clan_groups}
    encountered_clans: set[tuple[str, str | None]] = set()
    members_by_tribe: dict[str, list[Agent]] = {}
    agent_carriers_by_tribe: dict[str, set[object]] = {}
    clan_carriers_by_tribe: dict[str, set[tuple[str, str | None]]] = {}
    tribe_order: list[str] = []

    def add(
        tag: str,
        members: Iterable[Agent],
        *,
        agent_carrier: object | None = None,
        clan_carrier: tuple[str, str | None] | None = None,
    ) -> None:
        bare_tag = tag.removeprefix("@")
        if not bare_tag:
            return
        if bare_tag not in members_by_tribe:
            members_by_tribe[bare_tag] = []
            agent_carriers_by_tribe[bare_tag] = set()
            clan_carriers_by_tribe[bare_tag] = set()
            tribe_order.append(bare_tag)
        members_by_tribe[bare_tag].extend(members)
        if agent_carrier is not None:
            agent_carriers_by_tribe[bare_tag].add(agent_carrier)
        if clan_carrier is not None:
            clan_carriers_by_tribe[bare_tag].add(clan_carrier)

    for agent in all_agents:
        if agent.agent_clan:
            key = (agent.agent_clan, agent.agent_clan_generation)
            group = clan_group_by_key.get(key)
            if group is None or key in encountered_clans:
                continue
            encountered_clans.add(key)
            for tag in group.tags:
                add(tag, group.members, clan_carrier=key)
            continue
        if agent.is_clan_container or agent.is_synthetic_planner or not agent.tag:
            continue
        members: Iterable[Agent]
        if agent.is_family_root_entry:
            members = concrete_family_member_rows(agent)
        else:
            members = (agent,)
        add(agent.tag, members, agent_carrier=agent.identity)

    candidates: list[AgentCompletionCandidate] = []
    for tag in tribe_order:
        members = _dedupe_real_member_rows(members_by_tribe[tag])
        if not members:
            continue
        status = _aggregate_completion_status(members)
        candidates.append(
            AgentCompletionCandidate(
                name=f"@{tag}",
                label=tag,
                status=status,
                kind="tribe",
                member_count=len(members),
                aggregate_status=status,
                member_names=_member_names(members),
                agent_count=len(agent_carriers_by_tribe[tag]),
                clan_count=len(clan_carriers_by_tribe[tag]),
                search_aliases=(tag,),
            )
        )
    return candidates


def _dedupe_real_member_rows(rows: Iterable[Agent]) -> tuple[Agent, ...]:
    members: list[Agent] = []
    seen: set[object] = set()
    for row in rows:
        if row.is_clan_container or row.is_synthetic_planner or row.identity in seen:
            continue
        seen.add(row.identity)
        members.append(row)
    return tuple(members)


def _aggregate_completion_status(rows: Sequence[Agent]) -> str:
    from sase.ace.tui.models._agent_clan import aggregate_clan_status

    return aggregate_clan_status(row.status for row in rows) or "RUNNING"


def _member_names(rows: Sequence[Agent]) -> tuple[str, ...]:
    names: list[str] = []
    for row in rows:
        name = row.agent_name or row.presented_agent_name or row.display_name
        if name and name not in names:
            names.append(name)
    return tuple(names)


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
    *,
    kind: Literal["agent", "family", "clan", "tribe"] = "agent",
    member_count: int | None = None,
    aggregate_status: str | None = None,
    member_names: tuple[str, ...] = (),
) -> AgentCompletionCandidate:
    role = agent.agent_family_role or agent.role_suffix
    raw_prompt = _raw_prompt_for_agent(agent, all_agents)
    canonical_snippet = _prompt_snippet(raw_prompt, humanize=False)
    return AgentCompletionCandidate(
        name=name,
        label=agent.agent_name or agent.display_name or agent.cl_name or name,
        status=agent.status,
        kind=kind,
        member_count=member_count,
        aggregate_status=aggregate_status,
        member_names=member_names,
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
