"""Archive marks, mark expansion, and footer binding tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_actions import (
    archive_markable_key,
    archive_marked_count,
    archive_marked_run_keys,
    clear_archive_marks,
    guard_archive_live_action,
    toggle_archive_mark,
)
from sase.ace.tui.widgets._keybinding_bindings_agents import AgentBindingsMixin
from sase.ace.tui.models.agent_archive_view import ARCHIVE_SECTION_PULSE
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_actions_helpers import make_owner, open_archive


def _column_owner_with_members() -> SimpleNamespace:
    from sase.ace.tui.actions.agents._archive_column import column_runtime
    from sase.ace.tui.models.agent_archive_list import (
        ArchiveListItem,
        ArchiveListModel,
        ITEM_CONTAINER,
        ITEM_MEMBER,
    )

    owner = make_owner()
    open_archive(owner, selected_key="container:archive:u.m@clan1")
    member_rows = [
        {
            "archive_key": {
                "source_username": "u",
                "source_machine": "m",
                "source_run_id": "m1",
            },
            "container_key": "archive:u.m@clan1",
            "agent_name": "swarm.one",
        },
        {
            "archive_key": {
                "source_username": "u",
                "source_machine": "m",
                "source_run_id": "m2",
            },
            "container_key": "archive:u.m@clan1",
            "agent_name": "swarm.two",
        },
    ]
    items = (
        ArchiveListItem(
            key="container:archive:u.m@clan1",
            kind=ITEM_CONTAINER,
            selectable=True,
        ),
        *(
            ArchiveListItem(
                key=f"u.m@m{index}",
                kind=ITEM_MEMBER,
                selectable=True,
                member_of="archive:u.m@clan1",
                row=row,
            )
            for index, row in enumerate(member_rows, start=1)
        ),
    )
    runtime = column_runtime(owner)
    runtime.model = ArchiveListModel(
        items=items,
        index={item.key: index for index, item in enumerate(items)},
    )
    return owner


def _bindings_for_owner(owner: SimpleNamespace) -> list[tuple[str, str]]:
    """Compute footer bindings from live Archive state, like the footer does."""
    from sase.ace.tui.models.agent_archive_view import is_archive_container_key

    key = archive_markable_key(owner)
    mixin = AgentBindingsMixin()
    mixin._kd = lambda name: name  # type: ignore[attr-defined]
    return mixin._compute_archive_bindings(
        marked_count=archive_marked_count(owner),
        has_selection=key is not None,
        selection_is_container=bool(key and is_archive_container_key(key)),
    )


def test_toggle_mark_routes_to_archive_marks(monkeypatch: Any) -> None:
    from sase.ace.tui.actions.marking import MarkingMixin

    owner = make_owner()
    app = MarkingMixin()
    app.__dict__.update(owner.__dict__)
    open_archive(app, selected_key="u.m@r1")
    refreshed: list[bool] = []
    footer_refreshed: list[bool] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._archive_column.refresh_column",
        lambda _owner, **_kwargs: refreshed.append(True),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._archive_column.refresh_archive_footer",
        lambda _owner: footer_refreshed.append(True),
    )
    with override_flags(agents_archive_view=True):
        app.action_toggle_mark()
    assert app._agents_archive_view.archive.marks == frozenset({"u.m@r1"})
    assert app._marked_agents == set()
    assert refreshed == [True]
    assert footer_refreshed == [True]


def test_mark_banner_tail_pulse_rejected() -> None:
    owner = make_owner()
    with override_flags(agents_archive_view=True):
        open_archive(owner, selected_key="banner:day:2026-10-10")
        assert toggle_archive_mark(owner) is False
        open_archive(owner, selected_key="tail:day:2026-10-10")
        assert toggle_archive_mark(owner) is False
        open_archive(owner, selected_key="u.m@r1")
        owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_PULSE
        assert archive_markable_key(owner) is None
        assert toggle_archive_mark(owner) is False
        assert archive_marked_count(owner) == 0


def test_archive_marks_independent_from_inbox_marks() -> None:
    owner = make_owner()
    owner._marked_agents = {("cl", "live", None)}
    open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        assert toggle_archive_mark(owner) is True
        assert owner._agents_archive_view.archive.marks == frozenset()
        assert toggle_archive_mark(owner) is True
        assert owner._marked_agents == {("cl", "live", None)}
        assert archive_marked_count(owner) == 1
        assert clear_archive_marks(owner) == 1
        assert archive_marked_count(owner) == 0
        assert owner._marked_agents == {("cl", "live", None)}


def test_archive_marks_parked_with_view_state() -> None:
    owner = make_owner()
    open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
    with override_flags():
        assert archive_marked_count(owner) == 0
        assert clear_archive_marks(owner) == 0


def test_marked_run_keys_expand_containers() -> None:
    owner = _column_owner_with_members()
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        expanded = archive_marked_run_keys(owner)
    assert "container:archive:u.m@clan1" in expanded
    assert "u.m@m1" in expanded
    assert "u.m@m2" in expanded


def test_marked_run_keys_exclude_inbox_identities() -> None:
    owner = _column_owner_with_members()
    owner._marked_agents = {("cl", "live", None)}
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        expanded = archive_marked_run_keys(owner)
    assert ("cl", "live", None) not in expanded  # type: ignore[comparison-overlap]
    assert all(isinstance(key, str) for key in expanded)


def test_archive_footer_bindings_selection() -> None:
    owner = make_owner()
    with override_flags(agents_archive_view=True):
        open_archive(owner, selected_key="u.m@r1")
        bindings = _bindings_for_owner(owner)
    assert ("toggle_mark", "mark") in bindings
    assert ("act_on_agent", "restore…") in bindings
    assert not any("kill" in label or "Inbox" in label for _key, label in bindings)


def test_archive_footer_bindings_empty_without_selection() -> None:
    owner = make_owner()
    with override_flags(agents_archive_view=True):
        open_archive(owner, selected_key=None)
        assert _bindings_for_owner(owner) == []


def test_archive_footer_bindings_container_and_marks() -> None:
    owner = _column_owner_with_members()
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        bindings = _bindings_for_owner(owner)
    labels = [label for _key, label in bindings]
    assert "expand" in labels
    assert "unmark (1)" in labels


def test_compute_archive_bindings_restore_without_live_chips() -> None:
    from sase.ace.tui.widgets._keybinding_bindings_agents import AgentBindingsMixin

    mixin = AgentBindingsMixin()
    mixin._kd = lambda name: name  # type: ignore[attr-defined]
    bindings = mixin._compute_archive_bindings(
        marked_count=2,
        has_selection=True,
        selection_is_container=True,
        deck_card_count=3,
        card_blocks_navigable=True,
        deck_view_cycle_available=True,
    )
    text = " ".join(f"{key} {label}" for key, label in bindings)
    for live in ("kill", "wait", "retry", "cleanup", "tabs", "Inbox"):
        assert live not in text
    assert ("act_on_agent", "restore…") in bindings


def test_unread_attention_accounting_untouched() -> None:
    owner = make_owner()
    before_unread = set(owner._unread_completed_agent_ids)
    open_archive(owner, selected_key="u.m@r1")
    with override_flags(agents_archive_view=True):
        assert toggle_archive_mark(owner) is True
        assert clear_archive_marks(owner) == 1
        assert guard_archive_live_action(owner, "toggle_agent_unread") is True
    assert owner._unread_completed_agent_ids == before_unread
