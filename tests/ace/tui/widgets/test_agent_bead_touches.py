"""Tests for the per-agent bead-touch loader and merge (bead sase-14j.4)."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest

import sase.ace.tui.bead_touches as bead_touches
from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.ace.tui.bead_touches import (
    MAX_KEPT_TOUCHES,
    _BeadTouchDisplayEvent,
    BeadTouchEntry,
    _canonical_bead_id,
    load_bead_touches_for_agent_context,
    merge_bead_touch_entries,
    own_bead_ids_for_agent,
)
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.bead_touch_index_facade import BeadTouch, BeadTouchQuery
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _touch(
    actor: str,
    bead_id: str,
    *,
    verbs: dict[str, int] | None = None,
    title: str = "",
    first_at: str = "",
    last_at: str = "",
) -> BeadTouch:
    return BeadTouch(
        actor=actor,
        bead_id=bead_id,
        title=title,
        verbs=dict(verbs or {}),
        first_at=first_at,
        last_at=last_at,
    )


def _display(touch: BeadTouch, label: str | None = None) -> _BeadTouchDisplayEvent:
    return _BeadTouchDisplayEvent(touch=touch, agent_label=label)


def _read(
    ref: str,
    timestamp: str,
    *,
    read_id: str,
    label: str | None = None,
    reason: str = "needed it",
) -> ArtifactReadDisplayEvent:
    return ArtifactReadDisplayEvent(
        event=ArtifactReadEvent(
            schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
            id=read_id,
            timestamp=timestamp,
            project="test",
            cwd="/tmp/test",
            ref=ref,
            reason=reason,
            agent_name="alpha",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/test/artifacts",
            recorded_link=False,
            resolved_path=None,
        ),
        agent_label=label,
    )


_FAKE_GLOBALIZED = {
    "alpha": "owner.machine.alpha",
    "beta": "owner.machine.beta",
}


def _fake_globalize(name: str, identity: object = None) -> str:
    return _FAKE_GLOBALIZED.get(name, name)


class _StubSnapshot:
    @classmethod
    def current(cls) -> AgentIdentitySnapshot:
        return AgentIdentitySnapshot.unconfigured()


@pytest.fixture
def _loader_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Stub project, index path, identity, and caches for loader tests."""
    index_path = tmp_path / "agent_bead_touches.json"
    index_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        bead_touches, "_project_name_for_agent", lambda agent: "test-proj"
    )
    monkeypatch.setattr(bead_touches, "touch_index_path", lambda project: index_path)
    monkeypatch.setattr(bead_touches, "AgentIdentitySnapshot", _StubSnapshot)
    monkeypatch.setattr(bead_touches, "globalize_owned_agent_name", _fake_globalize)
    monkeypatch.setattr(bead_touches, "_bead_touches_cache", {})
    monkeypatch.setattr(bead_touches, "_bead_touches_context_cache", {})
    monkeypatch.setattr(bead_touches, "_bead_touches_snapshot_cache", OrderedDict())
    return {"index_path": index_path}


def _stub_query(
    monkeypatch: pytest.MonkeyPatch, touches: list[BeadTouch]
) -> list[object]:
    calls: list[object] = []

    def _query(index_path: object, actors: object = None) -> BeadTouchQuery:
        calls.append(index_path)
        return BeadTouchQuery(schema_version=1, generation="g", touches=tuple(touches))

    monkeypatch.setattr(bead_touches, "query_touch_index", _query)
    return calls


# --- _canonical_bead_id -------------------------------------------------------


def test_canonical_bead_id_strips_prefix_and_whitespace() -> None:
    assert _canonical_bead_id("bead:sase-14j.4") == "sase-14j.4"
    assert _canonical_bead_id("  bead:sase-14j.4  ") == "sase-14j.4"
    assert _canonical_bead_id("sase-14j.4") == "sase-14j.4"
    assert _canonical_bead_id("bead:") == ""
    assert _canonical_bead_id("") == ""
    assert _canonical_bead_id(None) == ""


def test_canonical_bead_id_stays_exact_after_prefix() -> None:
    # No case folding and no suffix matching: dotted names must not merge.
    assert _canonical_bead_id("bead:SASE-14J.4") == "SASE-14J.4"
    assert _canonical_bead_id("plan:202608/design.md") == "plan:202608/design.md"


# --- merge -------------------------------------------------------------------


def test_merge_empty_inputs_returns_empty() -> None:
    assert merge_bead_touch_entries((), (), ()) == ()


def test_merge_single_touch_carries_verbs_title_and_timestamps() -> None:
    touch = _touch(
        "alpha",
        "sase-14j.4",
        verbs={"created": 1, "noted": 2},
        title="Resolve touches",
        first_at="2026-09-20T14:00:00Z",
        last_at="2026-09-20T16:41:02Z",
    )
    (entry,) = merge_bead_touch_entries((_display(touch),), (), ())
    assert entry.bead_id == "sase-14j.4"
    assert entry.title == "Resolve touches"
    assert entry.verbs == {"created": 1, "noted": 2}
    assert entry.first_at == "2026-09-20T14:00:00Z"
    assert entry.last_at == "2026-09-20T16:41:02Z"
    assert entry.own is False
    assert entry.agent_label is None


def test_merge_ranks_newest_touch_first_with_id_tiebreak() -> None:
    older = _touch("a", "sase-9b", last_at="2026-09-20T15:00:00Z")
    newer = _touch("a", "sase-9a", last_at="2026-09-20T16:00:00Z")
    tied_b = _touch("a", "sase-9c", last_at="2026-09-20T16:00:00Z")
    tied_a = _touch("a", "sase-9b2", last_at="2026-09-20T16:00:00Z")
    entries = merge_bead_touch_entries(
        (_display(older), _display(newer), _display(tied_b), _display(tied_a)),
        (),
        (),
    )
    assert [entry.bead_id for entry in entries] == [
        "sase-9a",
        "sase-9b2",
        "sase-9c",
        "sase-9b",
    ]


def test_merge_folds_bead_read_into_touch_row() -> None:
    touch = _touch(
        "alpha",
        "sase-14j.4",
        verbs={"noted": 2},
        title="Resolve touches",
        first_at="2026-09-20T14:00:00Z",
        last_at="2026-09-20T15:00:00Z",
    )
    read = _read("bead:sase-14j.4", "2026-09-20T16:00:00Z", read_id="r1")
    (entry,) = merge_bead_touch_entries((_display(touch),), (read,), ())
    assert entry.verbs == {"noted": 2, "read": 1}
    assert entry.last_at == "2026-09-20T16:00:00Z"
    assert entry.first_at == "2026-09-20T14:00:00Z"
    assert entry.title == "Resolve touches"


def test_merge_counts_repeated_reads_and_read_only_beads() -> None:
    reads = (
        _read("bead:sase-14j.4", "2026-09-20T16:00:00Z", read_id="r1"),
        _read("bead:sase-14j.4", "2026-09-20T16:05:00Z", read_id="r2"),
    )
    (entry,) = merge_bead_touch_entries((), reads, ())
    assert entry.bead_id == "sase-14j.4"
    assert entry.verbs == {"read": 2}
    assert entry.first_at == "2026-09-20T16:00:00Z"
    assert entry.last_at == "2026-09-20T16:05:00Z"


def test_merge_carries_newest_read_reason_first() -> None:
    reads = (
        _read(
            "bead:sase-14j.4",
            "2026-09-20T16:00:00Z",
            read_id="r1",
            reason="  older reason  ",
        ),
        _read(
            "bead:sase-14j.4",
            "2026-09-20T16:05:00Z",
            read_id="r2",
            reason="newer reason",
        ),
        _read(
            "bead:sase-14j.4",
            "2026-09-20T16:06:00Z",
            read_id="r3",
            reason="newer reason",
        ),
        _read(
            "bead:sase-14j.4",
            "",
            read_id="r4",
            reason="   ",
        ),
    )
    (entry,) = merge_bead_touch_entries((), reads, ())
    assert entry.read_reasons == ("newer reason", "older reason")


def test_merge_ignores_non_bead_refs() -> None:
    reads = (
        _read("plan:202608/design.md", "2026-09-20T16:00:00Z", read_id="r1"),
        _read("memory:tui_perf.md", "2026-09-20T16:01:00Z", read_id="r2"),
        _read("bead:", "2026-09-20T16:02:00Z", read_id="r3"),
    )
    assert merge_bead_touch_entries((), reads, ()) == ()


def test_merge_marks_own_beads_including_untouched() -> None:
    touch = _touch(
        "alpha",
        "sase-14j.4",
        verbs={"closed": 1},
        last_at="2026-09-20T16:00:00Z",
    )
    entries = merge_bead_touch_entries(
        (_display(touch),), (), ("sase-14j", "sase-14j.4")
    )
    by_id = {entry.bead_id: entry for entry in entries}
    assert by_id["sase-14j.4"].own is True
    assert by_id["sase-14j.4"].verbs == {"closed": 1}
    untouched = by_id["sase-14j"]
    assert untouched.own is True
    assert untouched.verbs == {}
    assert untouched.last_at == ""
    # Timestamp-less own-only beads sort after every touched bead.
    assert entries[-1].bead_id == "sase-14j"


def test_merge_own_ids_match_after_canonicalization() -> None:
    entries = merge_bead_touch_entries((), (), ("  sase-14j.4  ",))
    assert len(entries) == 1
    assert entries[0].own is True


def test_merge_skips_touches_without_a_bead_id() -> None:
    touch = _touch("alpha", "   ", verbs={"noted": 1})
    assert merge_bead_touch_entries((_display(touch),), (), ()) == ()


def test_merge_takes_first_available_title() -> None:
    first = _touch("a", "sase-1", title="")
    second = _touch("b", "sase-1", title="Kept title")
    (entry,) = merge_bead_touch_entries((_display(first), _display(second)), (), ())
    assert entry.title == "Kept title"


def test_merge_sums_verbs_across_family_producers() -> None:
    first = _touch("a", "sase-1", verbs={"noted": 1})
    second = _touch("b", "sase-1", verbs={"noted": 2, "closed": 1})
    (entry,) = merge_bead_touch_entries(
        (_display(first, "plan"), _display(second, "coder")), (), ()
    )
    assert entry.verbs == {"noted": 3, "closed": 1}
    assert entry.agent_label is None


def test_merge_keeps_shared_family_label() -> None:
    touch = _touch("a", "sase-1", verbs={"noted": 1})
    read = _read("bead:sase-1", "2026-09-20T16:00:00Z", read_id="r1", label="plan")
    (entry,) = merge_bead_touch_entries((_display(touch, "plan"),), (read,), ())
    assert entry.agent_label == "plan"


def test_merge_entry_type_defaults() -> None:
    entry = BeadTouchEntry(bead_id="sase-1")
    assert entry.title == ""
    assert entry.verbs == {}
    assert entry.own is False
    assert entry.agent_label is None


# --- own_bead_ids_for_agent --------------------------------------------------


def test_own_bead_ids_collects_phase_epic_and_derived() -> None:
    agent = make_agent(
        agent_name="worker",
        phase_bead_id="sase-14j.4",
        epic_bead_id="sase-14j",
    )
    assert own_bead_ids_for_agent(agent) == ("sase-14j.4", "sase-14j")


def test_own_bead_ids_dedupes_and_skips_blanks() -> None:
    agent = make_agent(
        agent_name="worker",
        phase_bead_id="sase-14j.4",
        epic_bead_id="sase-14j.4",
    )
    assert own_bead_ids_for_agent(agent) == ("sase-14j.4",)


def test_own_bead_ids_derives_from_bead_work_name() -> None:
    agent = make_agent(agent_name="sase-14j.4")
    assert own_bead_ids_for_agent(agent) == ("sase-14j.4",)


def test_own_bead_ids_empty_for_ordinary_agent() -> None:
    assert own_bead_ids_for_agent(make_agent(agent_name="worker")) == ()


# --- loader ------------------------------------------------------------------


def test_loader_filters_to_agent_by_local_and_globalized_name(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            _touch("alpha", "sase-1", last_at="2026-09-20T16:00:00Z"),
            _touch("owner.machine.alpha", "sase-2", last_at="2026-09-20T17:00:00Z"),
            _touch("beta", "sase-3", last_at="2026-09-20T18:00:00Z"),
            _touch("stranger", "sase-4", last_at="2026-09-20T19:00:00Z"),
            _touch("", "sase-5", last_at="2026-09-20T20:00:00Z"),
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent)

    assert [event.touch.bead_id for event in events] == ["sase-2", "sase-1"]
    assert all(event.agent_label is None for event in events)


def test_loader_returns_empty_when_project_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    calls = _stub_query(monkeypatch, [_touch("alpha", "sase-1")])
    monkeypatch.setattr(bead_touches, "_project_name_for_agent", lambda agent: None)

    assert load_bead_touches_for_agent_context(make_agent()) == ()
    assert calls == []


def test_loader_returns_empty_when_query_fails(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    def _boom(index_path: object, actors: object = None) -> BeadTouchQuery:
        raise ImportError("no extension")

    monkeypatch.setattr(bead_touches, "query_touch_index", _boom)

    assert load_bead_touches_for_agent_context(make_agent(agent_name="alpha")) == ()


def test_loader_caches_snapshot_across_agents(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    calls = _stub_query(monkeypatch, [_touch("alpha", "sase-1")])

    load_bead_touches_for_agent_context(
        make_agent(agent_name="alpha", cl_name="alpha_cl")
    )
    load_bead_touches_for_agent_context(
        make_agent(agent_name="beta", cl_name="beta_cl")
    )

    assert len(calls) == 1


def test_loader_throttles_reread_then_refreshes_on_change(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    calls = _stub_query(monkeypatch, [_touch("alpha", "sase-1")])
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")
    index_path = _loader_env["index_path"]
    assert isinstance(index_path, Path)

    load_bead_touches_for_agent_context(agent)
    assert len(calls) == 1

    # Same stat within the throttle window: no re-query.
    load_bead_touches_for_agent_context(agent)
    assert len(calls) == 1

    # Changed file after the throttle window: re-query.
    index_path.write_text("{}\nmore-bytes-here\n", encoding="utf-8")
    key = bead_touches._cache_key("test-proj", agent)
    bead_touches._bead_touches_cache[key].last_read_monotonic -= 10.0
    snapshot = bead_touches._bead_touches_snapshot_cache["test-proj"]
    snapshot.last_read_monotonic -= 10.0
    load_bead_touches_for_agent_context(agent)
    assert len(calls) == 2


def test_loader_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            _touch("alpha", f"sase-{n}", last_at=f"2026-09-20T16:{n:02d}:00Z")
            for n in range(10)
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent, limit=3)

    assert len(events) == 3
    assert events[0].touch.bead_id == "sase-9"


def test_loader_caps_at_max_kept_touches(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            _touch("alpha", f"sase-{n}", last_at="2026-09-20T16:00:00Z")
            for n in range(MAX_KEPT_TOUCHES + 5)
        ],
    )
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    assert len(load_bead_touches_for_agent_context(agent)) == MAX_KEPT_TOUCHES


def test_family_loader_attributes_touches_with_role_labels(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(
        monkeypatch,
        [
            _touch("alpha", "sase-1", last_at="2026-09-20T16:00:00Z"),
            _touch("owner.machine.beta", "sase-2", last_at="2026-09-20T17:00:00Z"),
            _touch("stranger", "sase-3", last_at="2026-09-20T18:00:00Z"),
        ],
    )
    member = make_agent(agent_name="beta", cl_name="beta_cl", role_suffix="--code")
    root = make_agent(
        agent_name="alpha",
        cl_name="alpha_cl",
        role_suffix="--plan",
        followup_agents=[member],
    )

    events = load_bead_touches_for_agent_context(root)

    assert [(event.touch.bead_id, event.agent_label) for event in events] == [
        ("sase-2", "coder"),
        ("sase-1", "plan"),
    ]


def test_single_member_family_takes_per_agent_path(
    monkeypatch: pytest.MonkeyPatch,
    _loader_env: dict[str, object],
) -> None:
    _stub_query(monkeypatch, [_touch("alpha", "sase-1")])
    agent = make_agent(agent_name="alpha", cl_name="alpha_cl")

    events = load_bead_touches_for_agent_context(agent)

    assert [event.touch.bead_id for event in events] == ["sase-1"]
    assert events[0].agent_label is None


# --- summary wiring ----------------------------------------------------------


def _stub_artifacts_resolvers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reads: tuple[ArtifactReadDisplayEvent, ...] = (),
    touches: tuple[_BeadTouchDisplayEvent, ...] = (),
) -> None:
    """Keep the artifacts-lane resolvers cheap and deterministic."""
    from sase.ace.tui.models.agent_associated_plan import _AgentPlanEnrichment
    from sase.ace.tui.widgets.prompt_panel import _agent_display_header_summary

    monkeypatch.setattr(
        _agent_display_header_summary,
        "resolve_agent_plan_enrichment",
        lambda agent: _AgentPlanEnrichment("ordinary", None, None, ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifact_reads.load_artifact_reads_for_agent_context",
        lambda agent: reads,
    )
    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        lambda agent: touches,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda agent: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._linked_deltas.get_cached_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas."
        "agent_commit_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas.agent_delta_entries",
        lambda agent: [],
    )


def _wiring_agent() -> object:
    return make_agent(
        agent_name="worker",
        cl_name="worker_cl",
        phase_bead_id="sase-14j.4",
        epic_bead_id="sase-14j",
    )


def test_artifacts_lane_resolves_merged_bead_touch_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        build_detail_header_summary,
    )

    touch = _touch(
        "worker",
        "sase-14j.4",
        verbs={"noted": 2},
        title="Resolve touches",
        last_at="2026-09-20T16:00:00Z",
    )
    _stub_artifacts_resolvers(
        monkeypatch,
        touches=(_display(touch),),
        reads=(
            _read("bead:sase-14j.4", "2026-09-20T16:05:00Z", read_id="r1"),
            _read("plan:202608/design.md", "2026-09-20T16:06:00Z", read_id="r2"),
        ),
    )

    summary = build_detail_header_summary(
        _wiring_agent(),
        lanes=frozenset({"artifacts"}),  # type: ignore[arg-type]
    )

    assert summary.ready_lanes == frozenset({"artifacts"})
    assert [entry.bead_id for entry in summary.bead_touch_entries] == [
        "sase-14j.4",
        "sase-14j",
    ]
    worked = summary.bead_touch_entries[0]
    assert worked.verbs == {"noted": 2, "read": 1}
    assert worked.title == "Resolve touches"
    assert worked.own is True
    assert worked.last_at == "2026-09-20T16:05:00Z"
    untouched = summary.bead_touch_entries[1]
    assert untouched.own is True
    assert untouched.verbs == {}
    # The non-bead read stays out of the bead view.
    assert len(summary.bead_touch_entries) == 2


def test_artifacts_lane_empty_index_resolves_empty_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        build_detail_header_summary,
    )

    _stub_artifacts_resolvers(monkeypatch)

    summary = build_detail_header_summary(
        _wiring_agent(),
        lanes=frozenset({"artifacts"}),  # type: ignore[arg-type]
    )

    # The assigned-but-untouched beads still appear as own rows. Both
    # are timestamp-less, so the bead-id tiebreak orders them.
    assert [entry.bead_id for entry in summary.bead_touch_entries] == [
        "sase-14j",
        "sase-14j.4",
    ]
    assert all(entry.verbs == {} for entry in summary.bead_touch_entries)


def test_non_artifacts_lane_leaves_bead_view_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        build_detail_header_summary,
    )

    _stub_artifacts_resolvers(monkeypatch)

    summary = build_detail_header_summary(
        _wiring_agent(),
        lanes=frozenset({"skills"}),  # type: ignore[arg-type]
    )

    assert summary.bead_touch_entries == ()
    assert "artifacts" not in summary.ready_lanes


def test_cache_merge_keeps_bead_view_when_other_lane_rebuilds() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        cache_detail_header_summary,
        get_cached_detail_header_summary,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
        DetailHeaderSummary,
    )

    class _Widget:
        """A bare panel stand-in; the cache lives on an arbitrary attribute."""

    widget = _Widget()
    agent = make_agent()
    view = (BeadTouchEntry(bead_id="sase-14j.4", own=True),)
    cache_detail_header_summary(
        widget,
        agent,  # type: ignore[arg-type]
        DetailHeaderSummary(
            artifact_reads=(),
            bead_touch_entries=view,
        ),
    )

    cache_detail_header_summary(
        widget,
        agent,  # type: ignore[arg-type]
        DetailHeaderSummary(
            skill_uses=(),
            ready_lanes=frozenset({"skills"}),
        ),
    )

    merged = get_cached_detail_header_summary(widget, agent)  # type: ignore[arg-type]
    assert merged is not None
    assert merged.bead_touch_entries == view
