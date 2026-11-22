"""Surface-proof: relation, notification, and catalog payload replacement.

Phase ``tailnet-1e.7.1.3.1.2.1.5``. Uses the landed union of the fix phases
(``tailnet-1e.7.1.3.1.2.1.1`` visitors, ``.1.2`` row-ownership, ``.1.3``
failed-snapshots) and the shared ``tests/ace/tui/_gc_cycles.py`` helper.

Three bounded data-surface probes, each with the same shape:

1. artifact-links snapshot loaded with **nonempty** rows, emitted as
   edge/chip results through the relations-deck (``load_relations_extras``)
   and the files-pane (``build_files_relation_index`` /
   ``artifact_link_edges``) consumers, across cache replacement, normal
   success, and degraded/error completion;
2. notification snapshot plus unread reconcile over a session-rich roster
   (plan-session root, nested gate/monitor turns, completed rows, replaced
   roster), preserving manual unread and the pending-ack generation fence;
3. artifact-ref bead/agent entity-catalog replacement on realistic store
   fixtures, preserving the completion cap, ordering, token invalidation,
   and labels.

Cold/replaced and warm cache paths are measured separately: zero on a warm
cache hit alone never proves an obsolete generation was released. Every
SAVEALL regression drops the old generation first, then asserts the fixed
payload types are absent from cyclic garbage while the current generation
stays usable. Only the test-process cache generation is replaced or
invalidated; no production TTL is touched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.relations import artifact_links as artifact_links_mod
from sase.ace.tui.relations import build_files_relation_index
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.ace.tui.relations.link_index import link_index_for_snapshot
from sase.notifications import Notification
from sase.ace.tui.widgets.artifacts.files_data import (
    FileVersion,
    FilesSnapshot,
    LogicalFile,
)
from sase.ace.tui.widgets.decks.record.model import RecordSubject
from sase.ace.tui.widgets.decks.record.relations import load_relations_extras
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
)
from sase.ace.tui.widgets._artifact_ref_entity_catalogs import (
    _BEAD_CACHE,
    load_agent_candidate_catalog,
    load_bead_candidate_catalog,
)
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationEdge
from sase.sdd._artifact_link_store_support import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from tests.ace.tui._gc_cycles import AGENT_TYPE, measure_cycle_garbage
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent as make_session_agent,
    make_plan_root,
)

SNAPSHOT_TYPE = "sase.ace.tui.relations.artifact_links.ArtifactLinksSnapshot"
EDGE_TYPE = "sase.core.artifact_relations.RelationEdge"
CHIP_TYPE = "sase.ace.tui.relations.link_index.LinkChip"


def _write_aggregate(path: Path, rows: Any, *, pad: int = 0) -> None:
    payload = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "rows": rows,
        "pad": "x" * pad,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_single_project(
    monkeypatch: pytest.MonkeyPatch, aggregate: Path, project: str = "alpha"
) -> None:
    monkeypatch.setattr(artifact_links_mod, "_project_keys", lambda _p: (project,))
    monkeypatch.setattr(
        artifact_links_mod,
        "artifact_link_aggregate_path",
        lambda _project_key: aggregate,
    )


@pytest.fixture(autouse=True)
def _clear_relation_caches():
    from sase.ace.tui.relations import _native_link_index as native_link_index_mod

    artifact_links_mod._CACHE.clear()
    native_link_index_mod.clear_native_link_index_cache()
    yield
    artifact_links_mod._CACHE.clear()
    native_link_index_mod.clear_native_link_index_cache()


_LINK_ROWS = (
    {
        "source_ref": "file:doc",
        "relation": "implements",
        "target_ref": "bead:sase-r8",
        "description": "extends requirement",
        "origin": "manual",
        "uses": 3,
    },
    {
        "source_ref": "plan:202608/design.md",
        "relation": "implements",
        "target_ref": "file:doc",
        "description": "frontmatter link",
        "origin": "derived",
        "uses": 2,
    },
    {
        "source_ref": "agent:demo.athena.1",
        "relation": "awaits",
        "target_ref": "bead:sase-r8",
        "description": "wait_for_beads names bead sase-r8",
        "origin": "projected",
        "created_by": "projection:agent-wait-bead",
        "uses": 1,
    },
)


def _files_snapshot(rows: tuple[dict[str, Any], ...]) -> FilesSnapshot:
    version = FileVersion(
        version_id="doc-v1",
        logical_id="doc",
        label="doc",
        kind="file",
        origin="ref",
        origins=frozenset({"ref"}),
        created_at=None,
        agents=(),
        projects=("alpha",),
    )
    logical = LogicalFile(
        logical_id="doc",
        label="doc",
        kind="file",
        versions=(version,),
        agents=(),
        projects=("alpha",),
        origins=frozenset({"ref"}),
        latest_seen_at=None,
    )
    return FilesSnapshot(
        rows=(logical,),
        project="alpha",
        complete=True,
        view_modes={"doc-v1": "text"},
        view_mode_counts={"text": 1},
        origin_counts={"ref": 1},
        artifact_links=ArtifactLinksSnapshot(
            rows=tuple({**row, "_project": "alpha"} for row in rows),
        ),
    )


def _files_contract():
    return compile_builtin_contract("files", label="F", icon="x", accent="#0")


def test_relation_consumers_emit_nonempty_edges_and_chips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Populated snapshot reaches the deck and files-pane consumers."""
    aggregate = tmp_path / "aggregate.json"
    _write_aggregate(aggregate, list(_LINK_ROWS))
    _patch_single_project(monkeypatch, aggregate)

    snapshot = artifact_links_mod.load_artifact_links_snapshot(None)
    assert len(snapshot.rows) == len(_LINK_ROWS)
    assert snapshot.errors == ()

    # Warm path serves the cached live generation.
    assert artifact_links_mod.load_artifact_links_snapshot(None) is snapshot

    # Files-pane consumer: real edge projection over known targets.
    contract = _files_contract()
    edges = artifact_links_mod.artifact_link_edges(
        snapshot,
        contract=contract,
        known_targets=(ArtifactEntryTarget("files", ("doc",)),),
        project_hint="alpha",
    )
    assert len(edges) >= 2
    assert all(isinstance(edge, RelationEdge) for edge in edges)
    assert {edge.relation for edge in edges} >= {"implements"}

    files_index = build_files_relation_index(
        _files_snapshot(_LINK_ROWS), contract=contract
    )
    row = ArtifactEntryTarget("files", ("doc",))
    implements = files_index.edges_for_relation(row, "implements")
    assert implements
    assert implements[0].target == ArtifactEntryTarget(
        "beads", ("alpha", "task", "sase-r8")
    )
    implemented_by = files_index.edges_for_relation(row, "implemented-by")
    assert implemented_by
    assert implemented_by[0].target == ArtifactEntryTarget(
        "ref:plan", ("alpha", "archive", "202608/design.md")
    )

    # Relations-deck consumer: chips for a linked agent subject.
    chips = link_index_for_snapshot(snapshot).chips_for("agent:demo.athena.1")
    assert len(chips) == 1
    assert chips[0].neighbor_ref == "bead:sase-r8"

    extras = load_relations_extras(
        RecordSubject(agent_name="demo.athena.1", kind="agent")
    )
    assert extras.snapshot_error is None
    assert tuple(extras.snapshot_source_key or ()) == tuple(snapshot.source_key)
    groups = list(extras.link_groups)
    assert groups
    assert any("bead:sase-r8" in group.neighbor_refs for group in groups)


def test_relation_replacement_releases_obsolete_snapshot_and_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rewritten aggregate replaces the cached generation; old rows retire."""
    aggregate = tmp_path / "aggregate.json"
    _write_aggregate(aggregate, list(_LINK_ROWS))
    _patch_single_project(monkeypatch, aggregate)

    first = artifact_links_mod.load_artifact_links_snapshot(None)
    first_edges = _doc_edges(first)
    assert first_edges
    first_refs = {(edge.source, edge.target) for edge in first_edges}

    replacement_rows = [
        {
            "source_ref": "file:doc",
            "relation": "related",
            "target_ref": "file:other",
            "description": "replaced generation",
            "origin": "manual",
            "uses": 1,
        },
        {
            "source_ref": "agent:demo.athena.1",
            "relation": "awaits",
            "target_ref": "bead:sase-r9",
            "description": "replacement wait",
            "origin": "projected",
            "created_by": "projection:agent-wait-bead",
            "uses": 1,
        },
    ]
    _write_aggregate(aggregate, replacement_rows, pad=64)
    second = artifact_links_mod.load_artifact_links_snapshot(None)
    assert second.source_key != first.source_key
    assert len(artifact_links_mod._CACHE) == 1

    second_edges = _doc_edges(second)
    # The current generation stays usable and no longer serves old edges.
    assert second_edges
    assert {(edge.source, edge.target) for edge in second_edges} != first_refs
    assert all(edge.relation == "related" for edge in second_edges)
    second_chips = link_index_for_snapshot(second).chips_for("agent:demo.athena.1")
    assert [chip.neighbor_ref for chip in second_chips] == ["bead:sase-r9"]
    del first, first_edges, second, second_edges, second_chips

    rewrites: list[int] = []

    def produce() -> None:
        rewrites.append(1)
        _write_aggregate(aggregate, replacement_rows, pad=64 + len(rewrites))
        snapshot = artifact_links_mod.load_artifact_links_snapshot(None)
        edges = _doc_edges(snapshot)
        chips = link_index_for_snapshot(snapshot).chips_for("file:doc")
        extras = load_relations_extras(
            RecordSubject(agent_name="demo.athena.1", kind="agent")
        )
        assert edges and chips and extras.link_groups
        del snapshot, edges, chips, extras

    garbage = measure_cycle_garbage(produce)
    assert garbage.count(SNAPSHOT_TYPE) == 0, garbage.describe()
    assert garbage.count(EDGE_TYPE) == 0, garbage.describe()
    assert garbage.count(CHIP_TYPE) == 0, garbage.describe()


def _doc_edges(snapshot: ArtifactLinksSnapshot):
    return artifact_links_mod.artifact_link_edges(
        snapshot,
        contract=_files_contract(),
        known_targets=(ArtifactEntryTarget("files", ("doc",)),),
        project_hint="alpha",
    )


# ---------------------------------------------------------------------------
# Notifications: session-rich unread reconciliation + roster replacement
# ---------------------------------------------------------------------------

NOTIFICATION_TYPE = "sase.notifications.Notification"


def _make_notification(
    *,
    sender: str = "user-agent",
    action: str | None = "JumpToAgent",
    cl_name: str | None = "demo",
    raw_suffix: str | None = "20260507090000",
    dismissed: bool = False,
    silent: bool = False,
) -> Notification:
    action_data: dict[str, str] = {}
    if cl_name is not None:
        action_data["cl_name"] = cl_name
    if raw_suffix is not None:
        action_data["raw_suffix"] = raw_suffix
    return Notification(
        id=f"test-{cl_name}-{raw_suffix}",
        timestamp="2026-05-07T09:00:00",
        sender=sender,
        action=action,
        action_data=action_data,
        dismissed=dismissed,
        silent=silent,
    )


class _SurfaceUnreadApp(AgentsMixinCore):
    """Minimal cached-reconcile harness with a session-rich roster."""

    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self.current_idx = 0
        self.current_tab = "agents"
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._pending_bulk_read_agent_ids: (
            set[tuple[AgentType, str, str | None]] | None
        ) = None
        self._agent_info_metrics_cache: tuple[object, ...] | None = None
        self._notification_snapshot_cache = None
        self._pending_ack_overlay: dict[Any, tuple[int, int | None]] = {}
        self.patch_calls: list[Agent] = []

    def _try_patch_agent_row(self, agent: Agent, **kwargs: object) -> bool:
        self.patch_calls.append(agent)
        return True

    def _refresh_agents_display(self, **refresh_kwargs: object) -> None:
        return None


def _session_rich_roster(
    prefix: str,
) -> tuple[Agent, Agent, Agent, Agent, Agent]:
    """Plan-session root + member, nested gate, completed + manual + running."""
    root = make_plan_root(name=f"{prefix}--plan")
    member = make_session_agent(
        f"{prefix}--code", role="code", parent_timestamp=root.raw_suffix
    )
    root.followup_agents = [member]
    root.runtime_children = [member]
    member.agent_session_container = root
    gate = make_session_agent(
        f"{prefix}--gate", role="gate", parent_timestamp=root.raw_suffix
    )
    gate.gate_id = "gate-1"
    manual = make_session_agent(
        f"{prefix}--manual", role="code", parent_timestamp=root.raw_suffix
    )
    running = make_session_agent(
        f"{prefix}--run",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="RUNNING",
    )
    return root, member, gate, manual, running


def _completion_for(agent: Agent, **kwargs: Any) -> Notification:
    return _make_notification(
        cl_name=agent.cl_name, raw_suffix=agent.raw_suffix, **kwargs
    )


def _family_app(prefix: str) -> tuple[_SurfaceUnreadApp, tuple[Agent, ...]]:
    """Two session families: a nested root+member+gate+running, and a root."""
    root, member, gate, _manual, running = _session_rich_roster(prefix)
    solo = make_plan_root(name=f"{prefix}--solo")
    app = _SurfaceUnreadApp([root, member, gate, running, solo])
    return app, (root, member, gate, running, solo)


def test_session_rich_unread_reconcile_marks_completed_and_keeps_fences() -> None:
    """Nested-turn completions flag the session root; fences survive."""
    app, (root, member, gate, running, solo) = _family_app("unread")
    app._manual_unread_agent_ids.add(solo.identity)
    app._unread_completed_agent_ids.add(solo.identity)
    # In-flight ack for the root: the member completion must stay read.
    app._pending_ack_overlay[root.identity] = (1, None)

    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[
            _completion_for(member),
            _completion_for(gate),
            _completion_for(gate, dismissed=True),
            _completion_for(running),
        ],
        generation=7,
    )
    app._reconcile_unread_from_cached_notifications()

    # Nested member/gate completions would project onto the session root,
    # but the pending-ack fence holds that root read while the ack is in flight.
    assert root.identity not in app._unread_completed_agent_ids
    assert member.identity not in app._unread_completed_agent_ids
    assert gate.identity not in app._unread_completed_agent_ids
    # Manual unread survives with no matching notification.
    assert solo.identity in app._unread_completed_agent_ids
    # RUNNING rows never reconcile to unread.
    assert running.identity not in app._unread_completed_agent_ids


def test_session_rich_unread_reconcile_projects_nested_turns_onto_root() -> None:
    """A nested turn completion without fences flags its session root."""
    app, (root, member, _gate, _running, _solo) = _family_app("nested")
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[_completion_for(member)],
        generation=7,
    )
    app._reconcile_unread_from_cached_notifications()

    assert app._unread_completed_agent_ids == {root.identity}


def test_session_rich_roster_replacement_releases_old_rows() -> None:
    """Replacing the roster retires old unread without pinning old rows."""
    app, (root, member, _gate, _running, _solo) = _family_app("replace-a")
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[_completion_for(member)],
        generation=7,
    )
    app._reconcile_unread_from_cached_notifications()
    assert app._unread_completed_agent_ids == {root.identity}

    # Replace the roster: old rows drop, new generation flags the new root.
    new_app, (new_root, new_member, _n_gate, _n_run, _n_solo) = _family_app("replace-b")
    new_app._notification_snapshot_cache = SimpleNamespace(
        notifications=[_completion_for(new_member)],
        generation=8,
    )
    new_app._reconcile_unread_from_cached_notifications()

    assert new_app._unread_completed_agent_ids == {new_root.identity}
    assert root.identity not in new_app._unread_completed_agent_ids
    del app, root, member, new_app, new_root, new_member

    def produce() -> None:
        live, (old_root, old_member, _o_gate, _o_run, _o_solo) = _family_app("gc")
        live._notification_snapshot_cache = SimpleNamespace(
            notifications=[_completion_for(old_member)],
            generation=9,
        )
        live._reconcile_unread_from_cached_notifications()
        assert live._unread_completed_agent_ids == {old_root.identity}
        live._agents = []
        live._notification_snapshot_cache = None
        del live, old_root, old_member

    garbage = measure_cycle_garbage(produce)
    assert garbage.count(AGENT_TYPE) == 0, garbage.describe()
    assert garbage.count(NOTIFICATION_TYPE) == 0, garbage.describe()


# ---------------------------------------------------------------------------
# Catalogs: bead/agent entity-catalog replacement
# ---------------------------------------------------------------------------

CATALOG_MOD = "sase.ace.tui.widgets._artifact_ref_entity_catalogs"
BEAD_CATALOG_TYPE = f"{CATALOG_MOD}._ArtifactRefBeadCandidateCatalog"
BEAD_CANDIDATE_TYPE = f"{CATALOG_MOD}._ArtifactRefBeadCandidate"
AGENT_CATALOG_TYPE = f"{CATALOG_MOD}._ArtifactRefAgentCandidateCatalog"
AGENT_CANDIDATE_TYPE = f"{CATALOG_MOD}._ArtifactRefAgentCandidate"
ISSUE_TYPE = "sase.bead.model.Issue"


@pytest.fixture()
def _clear_bead_cache():
    _BEAD_CACHE.clear()
    yield
    _BEAD_CACHE.clear()


def _make_issue(index: int) -> Issue:
    return Issue(
        id=f"sase-surface-{index}",
        title=f"Surface issue {index}",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.TASK,
        tier=BeadTier.PLAN,
        updated_at=f"2026-07-29T12:{index // 60:02d}:{index % 60:02d}Z",
        created_at="2026-07-29T12:00:00Z",
    )


def _bead_context(root: Path, tmp_path: Path) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts.jsonl",
        repositories=(),
        projects=(),
        bead_stores=(ArtifactRefBeadStore("sase", "sase", root),),
    )


def test_bead_catalog_replacement_serves_new_generation(
    tmp_path: Path, _clear_bead_cache: None
) -> None:
    """Rewritten stores invalidate the token; ordering/labels hold."""
    root = tmp_path / "beads"
    root.mkdir()
    (root / "issues.jsonl").write_text("{}\n", encoding="utf-8")
    context = _bead_context(root, tmp_path)

    first_issues = [_make_issue(index) for index in range(3)]
    with patch("sase.core.bead_read_facade.list_issues", return_value=first_issues):
        first = load_bead_candidate_catalog(context)
    assert [row.payload for row in first.rows] == [
        "sase-surface-2",
        "sase-surface-1",
        "sase-surface-0",
    ]
    assert first.truncated == 0
    assert all(row.label.startswith("Surface issue") for row in first.rows)
    # Warm path reuses the cached live generation.
    with patch(
        "sase.core.bead_read_facade.list_issues",
        side_effect=AssertionError("warm path must not reload"),
    ):
        assert load_bead_candidate_catalog(context).rows == first.rows

    second_issues = [_make_issue(index) for index in range(3, 6)]
    (root / "issues.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    with patch("sase.core.bead_read_facade.list_issues", return_value=second_issues):
        second = load_bead_candidate_catalog(context)
    assert [row.payload for row in second.rows] == [
        "sase-surface-5",
        "sase-surface-4",
        "sase-surface-3",
    ]
    assert second.rows != first.rows
    del first, second, first_issues, second_issues

    generations: list[list[Issue]] = [
        [_make_issue(index) for index in range(count, count + 2)]
        for count in range(10, 40, 2)
    ]
    queries: list[int] = []

    def produce() -> None:
        queries.append(1)
        issues = generations[len(queries) % len(generations)]
        (root / "issues.jsonl").write_text("{}\n" * len(queries), encoding="utf-8")
        with patch("sase.core.bead_read_facade.list_issues", return_value=issues):
            catalog = load_bead_candidate_catalog(context)
            assert len(catalog.rows) == 2
            assert catalog.truncated == 0
        del catalog, issues

    garbage = measure_cycle_garbage(produce)
    assert garbage.count(ISSUE_TYPE) == 0, garbage.describe()
    assert garbage.count(BEAD_CATALOG_TYPE) == 0, garbage.describe()
    assert garbage.count(BEAD_CANDIDATE_TYPE) == 0, garbage.describe()


def _agent_context(agent_root: Path, tmp_path: Path) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts.jsonl",
        repositories=(),
        projects=(),
        agent_roots=(ArtifactRefAgentRoot("sase", agent_root),),
        agent_owner=ArtifactRefAgentOwner("bryan", "athena"),
    )


def _make_agent_dir(agent_root: Path, name: str, mtime: float) -> None:
    entry = agent_root / "agents" / name
    entry.mkdir(parents=True)
    (entry / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    os.utime(entry, (mtime, mtime))


def test_agent_catalog_replacement_picks_up_new_agent_dirs(
    tmp_path: Path,
) -> None:
    """Uncached agent scans order by mtime; new dirs appear, labels hold."""
    agent_root = tmp_path / "agents-root"
    base = 1_780_000_000.0
    _make_agent_dir(agent_root, "demo.athena.1", base + 2)
    _make_agent_dir(agent_root, "demo.athena.2", base + 1)
    context = _agent_context(agent_root, tmp_path)

    first = load_agent_candidate_catalog(context)
    assert [row.payload for row in first.rows] == [
        "demo.athena.1",
        "demo.athena.2",
    ]
    assert first.truncated == 0
    assert all(row.label for row in first.rows)
    assert all(row.detail for row in first.rows)
    del first

    _make_agent_dir(agent_root, "demo.athena.3", base + 3)
    second = load_agent_candidate_catalog(context)
    assert [row.payload for row in second.rows] == [
        "demo.athena.3",
        "demo.athena.1",
        "demo.athena.2",
    ]
    del second

    def produce() -> None:
        catalog = load_agent_candidate_catalog(context)
        assert len(catalog.rows) == 3
        assert catalog.rows[0].payload == "demo.athena.3"
        del catalog

    garbage = measure_cycle_garbage(produce)
    assert garbage.count(AGENT_CATALOG_TYPE) == 0, garbage.describe()
    assert garbage.count(AGENT_CANDIDATE_TYPE) == 0, garbage.describe()


def test_relation_degraded_completion_records_errors_and_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed aggregates degrade to recorded errors, not retained rows."""
    aggregate = tmp_path / "aggregate.json"
    aggregate.write_text("{not json", encoding="utf-8")
    _patch_single_project(monkeypatch, aggregate)

    snapshot = artifact_links_mod.load_artifact_links_snapshot(None)
    assert snapshot.rows == ()
    assert snapshot.errors
    assert (
        artifact_links_mod.artifact_link_edges(
            snapshot,
            contract=_files_contract(),
            known_targets=(ArtifactEntryTarget("files", ("doc",)),),
            project_hint="alpha",
        )
        == ()
    )
    del snapshot

    def produce() -> None:
        snapshot = artifact_links_mod.load_artifact_links_snapshot(None)
        assert snapshot.rows == () and snapshot.errors
        edges = artifact_links_mod.artifact_link_edges(
            snapshot,
            contract=_files_contract(),
            known_targets=(ArtifactEntryTarget("files", ("doc",)),),
            project_hint="alpha",
        )
        assert edges == ()
        del snapshot, edges

    garbage = measure_cycle_garbage(produce)
    assert garbage.count(SNAPSHOT_TYPE) == 0, garbage.describe()
    assert garbage.count(EDGE_TYPE) == 0, garbage.describe()
