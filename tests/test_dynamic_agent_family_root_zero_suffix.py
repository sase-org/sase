"""Legacy-loader coverage after family promotion moved to persisted metadata."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.agent_completion import agent_prompt_name
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import banner_label, build_agent_tree
from sase.ace.tui.models.agent_loader import _apply_status_overrides

_PROJECT = "/repo/sase.sase"


def _bare_root(
    *,
    name: str = "foo",
    raw_suffix: str = "20260701010101",
    status: str = "RUNNING",
) -> Agent:
    """A plain ``%n:foo`` top-level agent (no family metadata)."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file=_PROJECT,
        status=status,
        start_time=datetime(2026, 7, 1, 1, 1, 1),
        raw_suffix=raw_suffix,
        agent_name=name,
    )


def _attached_member(
    *,
    name: str,
    role_suffix: str,
    role: str,
    parent_timestamp: str = "20260701010101",
    raw_suffix: str = "20260701010202",
    agent_family: str = "foo",
) -> Agent:
    """A ``%n(parent, suffix)`` family-member child row."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature",
        project_file=_PROJECT,
        status="RUNNING",
        start_time=datetime(2026, 7, 1, 1, 2, 2),
        raw_suffix=raw_suffix,
        parent_timestamp=parent_timestamp,
        role_suffix=role_suffix,
        agent_name=name,
        agent_family=agent_family,
        agent_family_role=role,
    )


def test_legacy_bare_root_is_not_renamed_in_memory() -> None:
    """The loader no longer invents a display-only identity for old artifacts."""
    root = _bare_root()
    member = _attached_member(name="foo--bar", role_suffix="--bar", role="bar")

    _apply_status_overrides([root, member])

    assert root.agent_name == "foo"
    assert root.role_suffix is None
    assert root.agent_family is None
    assert root.agent_family_role is None
    assert member.agent_name == "foo--bar"


def test_legacy_bare_root_reference_identity_stays_foo() -> None:
    root = _bare_root()
    member = _attached_member(name="foo--bar", role_suffix="--bar", role="bar")

    _apply_status_overrides([root, member])

    assert agent_prompt_name(root) == "foo"
    assert agent_prompt_name(member) == "foo--bar"


def test_legacy_bare_root_and_member_still_group_under_foo_banner() -> None:
    root = _bare_root()
    member = _attached_member(name="foo--bar", role_suffix="--bar", role="bar")

    _apply_status_overrides([root, member])
    entries = build_agent_tree([root, member])

    foo_banners = [
        entry.group
        for entry in entries
        if entry.kind == "group"
        and entry.group is not None
        and banner_label(entry.group) == "foo"
        and len(entry.group.group_key) >= 2
    ]
    assert len(foo_banners) == 1
    # The name-root banner covers both family rows.
    assert set(foo_banners[0].agent_indices) == {0, 1}
    assert {root.agent_name, member.agent_name} == {"foo", "foo--bar"}


def test_persisted_generic_root_does_not_create_synthetic_planner() -> None:
    root = _bare_root(name="foo--0")
    root.role_suffix = "--0"
    root.agent_family = "foo"
    root.agent_family_role = "root"
    member = _attached_member(name="foo--bar", role_suffix="--bar", role="bar")
    agents = [root, member]

    _apply_status_overrides(agents)

    assert len(agents) == 2
    assert root.agent_name == "foo--0"
    assert root.plan_chain_root is False


def test_single_bare_member_stays_bare() -> None:
    """A lone ``foo`` (no attached member) keeps its bare identity."""
    root = _bare_root()

    _apply_status_overrides([root])

    assert root.agent_name == "foo"
    assert root.role_suffix is None
    assert root.agent_family is None
    assert root.agent_family_role is None


def test_explicit_zero_member_is_not_duplicated() -> None:
    """An explicit ``foo--0`` (``%n(foo, 0)``) suppresses normalization."""
    root = _bare_root()
    explicit_zero = _attached_member(name="foo--0", role_suffix="--0", role="q")

    _apply_status_overrides([root, explicit_zero])

    # The bare root is left alone so there are never two ``foo--0`` rows.
    assert root.agent_name == "foo"
    assert root.role_suffix is None
    assert explicit_zero.agent_name == "foo--0"


def test_plan_chain_family_is_unaffected() -> None:
    """A plan-chain family (``foo--plan`` + ``foo--code``) gets no ``--0``."""
    plan_root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature",
        project_file=_PROJECT,
        status="DONE",
        start_time=datetime(2026, 7, 1, 1, 1, 1),
        raw_suffix="20260701010101",
        role_suffix="--plan",
        agent_name="foo--plan",
        agent_family="foo",
        agent_family_role="root",
        plan_chain_root=True,
    )
    code_child = _attached_member(name="foo--code", role_suffix="--code", role="code")

    _apply_status_overrides([plan_root, code_child])

    assert plan_root.agent_name == "foo--plan"
    assert code_child.agent_name == "foo--code"
    assert all(agent.agent_name != "foo--0" for agent in (plan_root, code_child))
