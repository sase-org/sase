"""Ownership and copy contracts for session-roster Agent rows."""

from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from dataclasses import replace

import pytest

from sase.ace.tui.models._agent_clan_waves import (
    ClanWaveSlot,
    ClanWaveSummary,
    _ClanWaveMemberView,
    _ClanWaveState,
    _ClanWaveView,
)
from sase.ace.tui.models._agent_graph import (
    copy_agent_graph,
    copy_agent_rows_delta_isolated,
    copy_agent_rows_relinked,
)
from sase.ace.tui.models._loaders._done_common import (
    _LazyInstructionBundleFiles,
    lazy_done_instruction_bundle_files,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_session_members import agent_session_roster_container
from sase.core.agent_scan_wire_markers import (
    FinalizerStatusInstanceWire,
    FinalizerStatusRunnerWire,
    FinalizerStatusSummaryWire,
)
from tests.ace.tui._gc_cycles import AGENT_TYPE, measure_cycle_garbage
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent,
    make_plan_root,
)

_COPYERS: tuple[Callable[[Sequence[Agent]], list[Agent]], ...] = (
    copy_agent_graph,
    copy_agent_rows_relinked,
    copy_agent_rows_delta_isolated,
)


def _session_rows(prefix: str = "ownership") -> tuple[Agent, Agent]:
    root = make_plan_root(name=f"{prefix}--plan")
    member = make_agent(
        f"{prefix}--code",
        role="code",
        parent_timestamp=root.raw_suffix,
    )
    root.followup_agents = [member]
    root.runtime_children = [member]
    member.agent_session_container = root
    return root, member


def _attach_payloads(root: Agent, member: Agent) -> None:
    identity = member.raw_suffix or "ownership-member"
    root.clan_waves = ClanWaveSummary(
        layered=True,
        numbered_wave_count=1,
        has_seal=False,
        waves=(
            _ClanWaveView(
                number=1,
                kind="number",
                member_identities=(identity,),
                ghost_names=(),
                state=_ClanWaveState.IN_FLIGHT,
                predecessor_identities=(),
            ),
        ),
        members=(
            _ClanWaveMemberView(
                identity=identity,
                relative_label=".code",
                wave_index=0,
                predecessors=(),
                ghost_predecessors=(),
                external_wait_count=0,
            ),
        ),
        unresolved_identities=(),
    )
    member.clan_wave_slot = ClanWaveSlot(
        wave_index=0,
        label_kind="number",
        number=1,
        rank=0,
        open=True,
    )
    member.finalizer_status = FinalizerStatusSummaryWire(
        phase="finalize",
        status="done",
        runner=FinalizerStatusRunnerWire(pid=1234, identity="test-runner"),
        instances=[
            FinalizerStatusInstanceWire(
                id="builtin@commit",
                status="done",
                attempt=1,
                max_attempts=1,
            )
        ],
        instance_count=1,
    )
    member.instruction_bundle_files = lazy_done_instruction_bundle_files(
        "/tmp/unopened-agent-bundle"
    )


def _copy_fixture() -> list[Agent]:
    root, member = _session_rows("copy")
    _attach_payloads(root, member)

    clan = make_agent("copy-clan", role="clan", status="RUNNING")
    clan.is_clan_container = True
    clan.runtime_children = [root, member]
    clan.wait_display_source = member
    clan.status_display_source = member

    retry_parent = make_agent("copy-retry-parent", role="code")
    retry_child = make_agent(
        "copy-retry-child",
        role="code",
        parent_timestamp=retry_parent.raw_suffix,
    )
    retry_child.retry_of_timestamp = retry_parent.raw_suffix
    retry_parent.retry_chain_siblings = [retry_child]

    return [root, member, clan, retry_parent, retry_child]


def _drop_realistic_session_graph() -> None:
    root, member = _session_rows()
    _attach_payloads(root, member)
    bundle_files = member.instruction_bundle_files
    assert isinstance(bundle_files, _LazyInstructionBundleFiles)
    assert bundle_files._loaded is False
    del root, member


def test_session_roster_backreference_stays_navigable_without_owning_parent() -> None:
    root, member = _session_rows()
    root_ref = weakref.ref(root)

    assert isinstance(member.agent_session_container, Agent)
    assert agent_session_roster_container(member) is root
    # The generated dataclass constructor still accepts this public field.
    assert replace(member, agent_session_container=root).agent_session_container is root
    assert member == replace(member, agent_session_container=None)
    assert "agent_session_container=Agent(" not in repr(member)

    del root

    assert root_ref() is None
    assert member.agent_session_container is None
    assert agent_session_roster_container(member) is None


def test_session_roster_replacement_releases_old_rows_by_refcount() -> None:
    old_root, old_member = _session_rows("old")
    old_root_ref = weakref.ref(old_root)
    old_member_ref = weakref.ref(old_member)
    old_roster = [old_root, old_member]

    new_root, new_member = _session_rows("new")
    roster = [new_root, new_member]
    old_roster.clear()
    del old_root, old_member

    assert old_root_ref() is None
    assert old_member_ref() is None
    assert roster[1].agent_session_container is roster[0]


@pytest.mark.parametrize("copy_rows", _COPYERS, ids=lambda fn: fn.__name__)
def test_copy_paths_relink_session_parent_and_keep_lazy_payloads_deferred(
    copy_rows: Callable[[Sequence[Agent]], list[Agent]],
) -> None:
    originals = _copy_fixture()
    original_refs = [weakref.ref(row) for row in originals]

    copies = copy_rows(originals)
    root, member, clan, retry_parent, retry_child = copies

    assert root.followup_agents[0] is member
    assert root.runtime_children[0] is member
    assert member.agent_session_container is root
    assert clan.runtime_children == [root, member]
    assert clan.wait_display_source is member
    assert clan.status_display_source is member
    assert retry_parent.retry_chain_siblings == [retry_child]
    assert retry_child.retry_of_timestamp == retry_parent.raw_suffix
    assert isinstance(member.instruction_bundle_files, _LazyInstructionBundleFiles)
    assert member.instruction_bundle_files._loaded is False
    assert originals[1].instruction_bundle_files._loaded is False

    originals.clear()
    del originals

    assert all(ref() is None for ref in original_refs)
    assert member.agent_session_container is root
    assert root.followup_agents[0] is member


@pytest.mark.parametrize(
    "copy_rows",
    (copy_agent_rows_relinked, copy_agent_rows_delta_isolated),
    ids=lambda fn: fn.__name__,
)
def test_shallow_copy_keeps_out_of_batch_parent_weak_and_navigable_while_alive(
    copy_rows: Callable[[Sequence[Agent]], list[Agent]],
) -> None:
    root, member = _session_rows("external")
    root_ref = weakref.ref(root)
    copied_member = copy_rows([member])[0]

    assert copied_member.agent_session_container is root
    del root

    assert root_ref() is None
    assert copied_member.agent_session_container is None


def test_releasing_session_graph_releases_attached_payloads_without_gc_cycles() -> None:
    garbage = measure_cycle_garbage(_drop_realistic_session_graph, repeat=3)

    expected_zero_types = (
        AGENT_TYPE,
        "sase.ace.tui.models._agent_clan_waves.ClanWaveSlot",
        "sase.ace.tui.models._agent_clan_waves.ClanWaveSummary",
        "sase.ace.tui.models._agent_clan_waves._ClanWaveView",
        "sase.ace.tui.models._agent_clan_waves._ClanWaveMemberView",
        "sase.core.agent_scan_wire_markers_finalizer.FinalizerStatusSummaryWire",
        "sase.core.agent_scan_wire_markers_finalizer.FinalizerStatusRunnerWire",
        "sase.core.agent_scan_wire_markers_finalizer.FinalizerStatusInstanceWire",
        "sase.ace.tui.models._loaders._done_common._LazyInstructionBundleFiles",
    )
    for type_name in expected_zero_types:
        assert garbage.count(type_name) == 0, garbage.describe()
