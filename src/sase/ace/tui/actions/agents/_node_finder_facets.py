"""Per-open facet tables for the Node Finder snapshot.

Split from :mod:`_node_finder_snapshot`: reads every per-agent fact once
so the fold filter and row describer never re-derive it per pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...models.agent import AgentType, project_file_parent_name
from sase.gate_turn.state import is_real_gate_member
from sase.monitor_state import is_monitor_member_role
from sase.project_display_names import humanize_cl_name

if TYPE_CHECKING:
    from ...models import Agent

    AgentIdentity = tuple[AgentType, str, str | None]

#: Position of each :func:`describe_node_finder_row_from_facts` fact inside
#: the per-agent tuple built by :func:`snapshot_all_facets`. The tuple
#: carries every naming/role fact the batched describer needs, so the row
#: loop never re-reads an agent property the facet pass already covered.
_DESCRIBE_FACT_FIELDS = (
    "is_clan",
    "is_proc",
    "is_wf_step",
    "step_type",
    "presented",
    "agent_name",
    "display_name",
    "cl_name",
    "is_session_container",
    "is_agent_entry",
    "agent_clan",
    "proc_label",
    "proc_safe_preview",
    "step_name",
    "is_session_member_child",
    "is_pre_prompt_step",
    "agent_type",
    "is_workflow_child",
    "appears_as_agent",
)


def _describe_plain_row(
    presented: str | None,
    agent_name: str | None,
    display_name: str,
    cl_name: str,
    is_pre_prompt_step: bool,
    styles: dict[str, Any],
) -> tuple[bool, str, str, str, str]:
    """Return ``(jumpable, name, title, kind_label, kind_accent)`` for plain rows.

    Exact fast path through :func:`describe_node_finder_row_from_facts`
    for ordinary running agents (no clan/proc/workflow-step/session shape
    and no monitor/gate/session-child role): the name, title, jumpable,
    and kind branches collapse to these reads, and a running non-shell
    row is always an agent entry. Any other shape uses the full batched
    describer; the differential test pins this against the single-row
    contract.
    """
    name = presented or agent_name or display_name or humanize_cl_name(cl_name)
    raw_title = display_name or None
    title = "" if (not raw_title or raw_title == name) else raw_title
    return (
        not is_pre_prompt_step,
        name,
        title,
        "AGENT SHELL",
        styles["agent_entry"],
    )


def snapshot_all_facets(
    complete: list[Agent],
) -> tuple[
    dict[int, str | None],
    dict[int, str | None],
    dict[int, int],
    dict[int, AgentIdentity],
    set[int],
    dict[int, bool],
    dict[int, bool],
    dict[int, bool],
    dict[int, tuple[Any, ...]],
]:
    """Read every per-open facet once, including role facts.

    Beyond the base tables, each agent pays once for the monitor/gate role
    booleans and child linkage that the fold filter otherwise recomputes
    per pass via repeated plan-chain suffix parses. The child linkage enum
    answers ``is_child_row`` for the filter and the workflow-step, session
    child, and workflow-child flags for the row describer from one read.
    The row loop reuses the same facts plus one shared kind-style binding
    when calling the batched describer, instead of re-parsing suffixes per
    property per row. Every table is local to this snapshot; live owner
    state is still read afresh on every open. The shell/child maps stay
    sparse: ordinary running rows are never shells or child rows, so only
    other shapes populate them, and every consumer falls back to the same
    live read for a missing id.
    """
    from ...models._agent_tree import agent_fold_key
    from ...models.agent import AgentChildLinkage
    from ...models.agent_types import AgentType

    parent_keys: dict[int, str | None] = {}
    fold_keys: dict[int, str | None] = {}
    depths: dict[int, int] = {}
    identity_of: dict[int, AgentIdentity] = {}
    hidden_steps: set[int] = set()
    is_monitor_map: dict[int, bool] = {}
    is_gate_map: dict[int, bool] = {}
    is_child_row_map: dict[int, bool] = {}
    describe_facts: dict[int, tuple[Any, ...]] = {}
    # ``humanize_cl_name`` is module-cached, but the plain branch below
    # still pays a call plus a tuple-keyed lookup per agent for a value
    # that repeats per Patch: one snapshot-local entry per distinct name.
    _plain_display_cache: dict[str, str] = {}
    for agent in complete:
        key = id(agent)
        # ``agent_parent_fold_key`` is the first truthy link (a falsy
        # ``tree_parent_key`` falls through exactly like the ``if`` does);
        # ``agent_fold_key`` is the clan key for clan containers and the
        # raw suffix otherwise. Inlining both skips two calls per agent.
        # Repeated fields are bound once: the loop below re-reads the
        # parent timestamp and Patch name several times per agent.
        parent_timestamp = agent.parent_timestamp
        parent_keys[key] = agent.tree_parent_key or parent_timestamp or None
        is_clan = agent.is_clan_container
        agent_clan = agent.agent_clan if is_clan else None
        raw_suffix = agent.raw_suffix
        cl_name = agent.cl_name
        if agent_clan:
            fold_keys[key] = agent_fold_key(agent)
        else:
            fold_keys[key] = raw_suffix or None
        # ``child_linkage`` is two ``None`` checks; inlining the field
        # reads skips a property call per agent with identical values.
        if agent.parent_workflow is not None:
            linkage = AgentChildLinkage.WORKFLOW_STEP
        elif parent_timestamp is not None:
            linkage = AgentChildLinkage.AGENT_SESSION_MEMBER
        else:
            linkage = AgentChildLinkage.ROOT
        is_child_row = linkage is not AgentChildLinkage.ROOT
        # ``agent_tree_depth`` prefers the stored depth and falls back to
        # child-row detection; the linkage read above already answers it.
        tree_depth = agent.tree_depth
        depths[key] = tree_depth if tree_depth > 0 else (1 if is_child_row else 0)
        # Identity's fallthrough for ordinary rows is exactly
        # ``(agent_type, cl_name, raw_suffix)`` (see ``Agent.identity``):
        # only clan/imported/remote containers take another branch, so
        # only they pay the property call.
        if (
            is_clan
            or agent.is_imported_agent_session_container
            or agent.is_remote_agent_session_container
        ):
            identity_of[key] = agent.identity
        else:
            identity_of[key] = (
                agent.agent_type,
                cl_name,
                raw_suffix,
            )
        if agent.is_hidden_step:
            hidden_steps.add(key)
        # The monitor/gate predicates stay the single implementation in
        # their state modules. A falsy session role can never be a durable
        # gate member (``is_real_turn_member`` needs a non-blank role
        # string, and the gate leg never consults the suffix fallback), so
        # the gate call is skipped outright; the monitor call is skipped
        # when the suffix fallback has nothing to parse either. Rows
        # carrying either field take the exact predicate calls below.
        agent_session_role = agent.agent_session_role
        if agent_session_role:
            role_suffix = agent.role_suffix
            is_monitor = is_monitor_member_role(agent_session_role, role_suffix)
            is_gate = is_real_gate_member(agent_session_role, agent.gate_id)
        elif agent.role_suffix:
            is_monitor = is_monitor_member_role(None, agent.role_suffix)
            is_gate = False
        else:
            is_monitor = False
            is_gate = False
        is_proc = agent.is_proc_shell
        is_wf_step = linkage is AgentChildLinkage.WORKFLOW_STEP
        is_session_child = linkage is AgentChildLinkage.AGENT_SESSION_MEMBER
        # ``is_agent_session_root_entry`` is ``not is_workflow_child``
        # (``is_workflow_child`` is exactly ``linkage is not ROOT``: session
        # members and workflow steps both count as children) plus root
        # metadata; inlining the two attribute reads avoids re-deriving the
        # linkage through the property. The container flag adds the member
        # check from its body.
        is_root_entry = (linkage is AgentChildLinkage.ROOT) and (
            agent.plan_chain_root or agent_session_role == "root"
        )
        if (
            not is_clan
            and not is_proc
            and not is_wf_step
            and not is_monitor
            and not is_gate
            and not is_session_child
            and not (is_root_entry and bool(agent.followup_agents))
            and agent.agent_type is AgentType.RUNNING
        ):
            # Ordinary running row: the plain describer needs only the
            # naming facts plus the pre-prompt flag. All other shapes
            # record the full fact tuple for the batched describer.
            # The display name inlines ``display_name``'s tail: the plain
            # condition already excluded clan/proc/gate shapes and
            # non-RUNNING types, so only the project-agent branch can still
            # apply; anything else humanizes the cl name. The humanized
            # value repeats per Patch, so one snapshot-local entry per
            # distinct cl name replaces a call per agent.
            project_display = agent.project_display_name
            if (
                project_display
                and agent.project_file
                and cl_name == project_file_parent_name(agent.project_file)
            ):
                plain_display = project_display
            else:
                try:
                    plain_display = _plain_display_cache[cl_name]
                except KeyError:
                    plain_display = _plain_display_cache[cl_name] = humanize_cl_name(
                        cl_name
                    )
            # Short 5-tuple for the ``_describe_plain_row`` fast path below
            # (inlined in ``_node_finder_rows``): keep the order in sync
            # with both.
            describe_facts[key] = (
                agent.presented_agent_name,
                agent.agent_name,
                plain_display,
                cl_name,
                agent.is_pre_prompt_step,
            )
            continue
        # Only non-plain rows populate the shell/child maps: the plain
        # branch above already proved its rows are never shells or child
        # rows, and every map consumer (the fold filter, the keep-all fast
        # path, and the row describer) falls back to the same live read
        # for a missing id.
        is_monitor_map[key] = is_monitor
        is_gate_map[key] = is_gate
        is_child_row_map[key] = is_child_row
        describe_facts[key] = (
            is_clan,
            is_proc,
            is_wf_step,
            agent.step_type,
            agent.presented_agent_name,
            agent.agent_name,
            agent.display_name,
            agent.cl_name,
            agent.is_agent_session_container_row,
            agent.is_agent_entry,
            agent.agent_clan,
            agent.proc_label,
            agent.proc_safe_preview,
            agent.step_name,
            is_session_child,
            agent.is_pre_prompt_step,
            agent.agent_type,
            is_child_row,
            agent.appears_as_agent,
        )
    return (
        parent_keys,
        fold_keys,
        depths,
        identity_of,
        hidden_steps,
        is_monitor_map,
        is_gate_map,
        is_child_row_map,
        describe_facts,
    )


__all__ = [
    "snapshot_all_facets",
]
