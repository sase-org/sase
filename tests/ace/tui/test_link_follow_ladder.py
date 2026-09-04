"""Host-owned reveal-ladder behavior for ``$`` link-follow."""

from __future__ import annotations

from sase.ace.query_history import QueryHistoryStacks
from sase.ace.query_profile import (
    beads_query_schema,
    compile_query_profile,
    procs_query_schema,
)
from sase.ace.tui.actions.link_follow import _link_follow_outcomes
from sase.core.artifact_entry_target import ArtifactEntryTarget

from ._link_follow_helpers import _App, _Pane, _chip


class _Probe:
    def __init__(self, matching: dict[str, bool], *, default: bool = False) -> None:
        self.matching = matching
        self.default = default

    def matches(self, query: str) -> bool:
        return self.matching.get(query, self.default)


def test_follow_prefers_fold_expansion_over_any_query_change() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    pane = _Pane(
        targets=(origin,),
        selected=origin,
        query="kind:log limit:40",
        foldable=True,
        target_after_limit=target,
    )
    app = _App(
        chips=(_chip("file:hidden.txt", target),),
        panes={"files": pane},
    )

    app._follow_link_number(1)

    assert pane.expanded_folds == [target]
    assert pane.applied_queries == []
    assert pane.selected_entry_target() == target
    assert app.notifications == []
    assert app._query_history.get("files") in (
        None,
        QueryHistoryStacks(prev=[], next=[]),
    )


def test_follow_uses_identity_query_before_widening() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    selected = ArtifactEntryTarget("beads", ("demo", "task", "sase-open"))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-closed"))
    probe = _Probe(
        {
            "project:demo -status:closed": False,
            "project:demo": True,
            "-status:closed": False,
        }
    )
    pane = _Pane(
        targets=(selected,),
        selected=selected,
        query="project:demo -status:closed",
        target_after_limit=target,
        probe=probe,
        query_profile=compile_query_profile(beads_query_schema()),
        identity_row={"fields": {"id": "sase-closed"}},
        reveal_when=lambda query: query.strip() == "id:sase-closed",
    )
    app = _App(
        chips=(_chip("bead:sase-closed", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": pane,
        },
    )
    _link_follow_outcomes.clear()

    app._follow_link_number(1)

    assert pane.applied_queries == [("id:sase-closed", True)]
    assert pane.selected_entry_target() == target
    assert _link_follow_outcomes["identity"] == 1


def test_follow_skips_identity_when_dialect_has_no_field() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    selected = ArtifactEntryTarget("beads", ("demo", "task", "sase-open"))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-closed"))
    probe = _Probe(
        {
            "project:demo -status:closed": False,
            "project:demo": True,
            "-status:closed": False,
        }
    )
    pane = _Pane(
        targets=(selected,),
        selected=selected,
        query="project:demo -status:closed",
        target_after_limit=target,
        probe=probe,
        query_profile=compile_query_profile(procs_query_schema()),
        identity_row={"fields": {"id": "sase-closed"}},
        reveal_when=lambda query: (
            "project:demo" in query and "-status:closed" not in query
        ),
    )
    app = _App(
        chips=(_chip("bead:sase-closed", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": pane,
        },
    )

    app._follow_link_number(1)

    assert pane.applied_queries == [("project:demo limit:all", True)]
    assert pane.selected_entry_target() == target


def test_follow_widens_excluding_term_instead_of_neutral_query() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    selected = ArtifactEntryTarget("beads", ("demo", "task", "sase-open"))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-closed"))
    probe = _Probe(
        {
            "project:demo -status:closed": False,
            "project:demo": True,
            "-status:closed": False,
        }
    )
    pane = _Pane(
        targets=(selected,),
        selected=selected,
        query="project:demo -status:closed",
        target_after_limit=target,
        probe=probe,
        reveal_when=lambda query: (
            "project:demo" in query and "-status:closed" not in query
        ),
    )
    app = _App(
        chips=(_chip("bead:sase-closed", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": pane,
        },
    )

    app._follow_link_number(1)

    assert pane.applied_queries == [("project:demo limit:all", True)]
    assert pane.selected_entry_target() == target


def test_follow_uses_limit_all_only_after_widening_returns_nothing() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    selected = ArtifactEntryTarget("agents", ("builder",))
    target = ArtifactEntryTarget("agents", ("hidden",))
    pane = _Pane(
        targets=(selected,),
        selected=selected,
        query="status:RUNNING AND name:hidden",
        target_after_limit=target,
        probe=_Probe({}),
        reveal_when=lambda query: query.strip() == "limit:all",
    )
    app = _App(
        chips=(_chip("agent:hidden", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "agents": pane,
        },
    )

    app._follow_link_number(1)

    assert pane.applied_queries == [("limit:all", True)]
    assert pane.selected_entry_target() == target


def test_follow_records_exactly_one_history_entry_for_two_rewrites() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    probe = _Probe(
        {
            "project:demo -status:closed": False,
            "project:demo -status:closed limit:all": False,
            "project:demo": True,
            "-status:closed": False,
        }
    )
    pane = _Pane(
        targets=(origin,),
        selected=origin,
        query="project:demo -status:closed limit:40",
        target_after_limit=target,
        probe=probe,
        reveal_when=lambda query: (
            "project:demo" in query and "-status:closed" not in query
        ),
    )
    app = _App(
        chips=(_chip("file:hidden.txt", target),),
        panes={"files": pane},
    )

    app._follow_link_number(1)

    assert pane.applied_queries == [
        ("project:demo -status:closed limit:all", True),
        ("project:demo limit:all", True),
    ]
    stacks = app._query_history["files"]
    assert [record.source for record in stacks.prev] == [
        "project:demo -status:closed limit:40"
    ]
    assert stacks.next == []
    assert "limit:all" not in {record.source for record in stacks.prev}
    assert pane.selected_entry_target() == target

    app.action_prev_query()
    assert pane.host_limit_query() == "project:demo -status:closed limit:40"
    assert pane.selected_entry_target() == origin

    app.action_next_query()
    assert pane.host_limit_query() == "project:demo limit:all"


def test_second_follow_does_not_stack_history_while_lens_is_live() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    first = ArtifactEntryTarget("files", ("first.txt",))
    second = ArtifactEntryTarget("files", ("second.txt",))
    pane = _Pane(
        targets=(origin,),
        selected=origin,
        query="kind:log limit:40",
        target_after_limit=first,
    )
    app = _App(
        chips=(
            _chip("file:first.txt", first),
            _chip("file:second.txt", second),
        ),
        panes={"files": pane},
    )

    app._follow_link_number(1)
    origin_query = app._link_reveals["files"].origin
    assert [record.source for record in app._query_history["files"].prev] == [
        "kind:log limit:40"
    ]

    pane.target_after_limit = second
    pane.reveal_when = lambda query: query.strip() == "limit:all"
    app._follow_link_number(2)

    stacks = app._query_history["files"]
    assert [record.source for record in stacks.prev] == ["kind:log limit:40"]
    assert app._link_reveals["files"].origin == origin_query


def test_dangling_ref_says_no_such_artifact() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    app = _App(
        chips=(_chip("bug:missing", None),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )

    app._follow_link_number(1)

    assert app.notifications == [("No such artifact: bug:missing", "warning")]
    assert app._link_trail == []


def test_follow_closes_open_filter_session_and_records_one_rewrite() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    pane = _Pane(
        targets=(origin,),
        selected=origin,
        query="kind:log limit:40",
        target_after_limit=target,
        filter_session_open=True,
    )
    app = _App(
        chips=(_chip("file:hidden.txt", target),),
        panes={"files": pane},
    )

    app._follow_link_number(1)

    assert pane.closed_sessions == 1
    assert not pane._filter_session_open
    assert [record.source for record in app._query_history["files"].prev] == [
        "kind:log limit:40"
    ]
    assert pane.selected_entry_target() == target
