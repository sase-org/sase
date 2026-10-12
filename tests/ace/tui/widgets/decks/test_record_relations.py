"""Record Relations and Links card behavior."""

from __future__ import annotations

from types import SimpleNamespace

from rich.console import Group

from sase.ace.tui.relations.link_index import LinkChip
from sase.ace.tui.widgets.decks.record.model import RecordSubject
from sase.ace.tui.widgets.decks.record.relations import (
    ArtifactLinkGroup,
    RelationsExtras,
    links_card,
    load_relations_extras,
    relations_card,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text


def _text(card: object) -> str:
    renderables = card.renderables
    return renderable_to_text(Group(*renderables)) or ""


def _chip(
    relation: str,
    label: str,
    neighbor: str,
    *,
    directed: bool = True,
    this_is_source: bool = True,
) -> LinkChip:
    return LinkChip(
        relation=relation,
        label=label,
        directed=directed,
        this_is_source=this_is_source,
        neighbor_ref=neighbor,
        neighbor_target=None,
        accent="#87D7FF",
        icon="•",
        why="",
        origin="manual",
        uses=0,
        created_by="",
        created_at="",
        writable=True,
    )


def _patch_link_sources(monkeypatch, chips: tuple[LinkChip, ...]) -> None:
    import sase.ace.tui.widgets.decks.record.relations as module

    snapshot = SimpleNamespace(source_key=(("project", 1, 2),), errors=())
    monkeypatch.setattr(
        module, "load_artifact_links_snapshot", lambda _project: snapshot
    )
    monkeypatch.setattr(
        module,
        "link_index_for_snapshot",
        lambda _snapshot: SimpleNamespace(chips_for=lambda _reference: chips),
    )
    monkeypatch.setattr(
        module, "reference_for_agent_name", lambda name: f"agent:{name}"
    )


def test_relations_resolve_live_and_archived_parent_retry_refs(
    monkeypatch, tmp_path
) -> None:
    import sase.ace.dismissed_agents as dismissed_agents
    import sase.ace.tui.widgets.decks.record.relations as module

    monkeypatch.setattr(dismissed_agents, "dismissed_bundles_dir", lambda: tmp_path)
    _patch_link_sources(monkeypatch, ())
    queried: list[set[str] | None] = []

    def _query(_root, *, suffixes, visibility):
        queried.append(suffixes)
        assert visibility is None
        return [
            SimpleNamespace(
                raw_suffix="archived-old",
                agent_name="child-copy",
                cl_name="child-copy",
                is_workflow_child=True,
            ),
            SimpleNamespace(
                raw_suffix="archived-old",
                agent_name="parent-copy",
                cl_name="parent-copy",
                is_workflow_child=False,
            ),
        ]

    monkeypatch.setattr(module, "query_summaries", _query)
    subject = RecordSubject(
        agent_name="current",
        agent_session="session-current",
        agent_session_role="code",
        presented_clan_name="clan-current",
        agent_clan_generation="g4",
        parent_timestamp="live-parent",
        parent_workflow="release-flow",
        retry_of_timestamp="archived-old",
        retried_as_timestamp="missing-new",
        retry_attempt=2,
        related_live_names=(("live-parent", "presented-parent"),),
    )

    extras = load_relations_extras(subject)
    refs = dict(extras.resolved_refs)
    assert queried == [{"archived-old", "missing-new"}]
    assert refs == {
        "clan": "@agent:clan-current",
        "parent": "@agent:presented-parent",
        "retry_of": "@agent:parent-copy",
        "session": "@agent:session-current",
        "workflow": "@agent:release-flow",
    }

    rendered = _text(relations_card(subject, extras))
    assert "Session: @agent:session-current · code" in rendered
    assert "Clan: @agent:clan-current · generation g4" in rendered
    assert "Parent: @agent:presented-parent" in rendered
    assert "Workflow: @agent:release-flow" in rendered
    assert "Retry: @agent:parent-copy → @agent:missing-new · attempt 2" in rendered


def test_archived_parent_resolves_from_summary_index(monkeypatch, tmp_path) -> None:
    import sase.ace.dismissed_agents as dismissed_agents
    import sase.ace.tui.widgets.decks.record.relations as module

    monkeypatch.setattr(dismissed_agents, "dismissed_bundles_dir", lambda: tmp_path)
    _patch_link_sources(monkeypatch, ())
    monkeypatch.setattr(
        module,
        "query_summaries",
        lambda _root, **_kwargs: [
            SimpleNamespace(
                raw_suffix="archived-parent",
                agent_name="archive-parent",
                cl_name="archive-parent",
                is_workflow_child=False,
            )
        ],
    )

    subject = RecordSubject(parent_timestamp="archived-parent")
    extras = load_relations_extras(subject)

    assert dict(extras.resolved_refs)["parent"] == "@agent:archive-parent"
    assert "Parent: @agent:archive-parent" in _text(relations_card(subject, extras))


def test_links_group_by_direction_relation_and_cap_each_group(monkeypatch) -> None:
    chips = tuple(
        _chip("implements", "implements", f"bead:item-{index}") for index in range(4)
    ) + (
        _chip(
            "implements",
            "implemented by",
            "agent:upstream",
            this_is_source=False,
        ),
        _chip(
            "cites",
            "cited by",
            "plan:source",
            this_is_source=False,
        ),
        _chip(
            "related",
            "related",
            "file:other.md",
            directed=False,
        ),
    )
    _patch_link_sources(monkeypatch, chips)

    extras = load_relations_extras(RecordSubject(agent_name="current"))
    assert [
        (group.direction, group.relation, group.label, len(group.neighbor_refs))
        for group in extras.link_groups
    ] == [
        ("outgoing", "implements", "implements", 4),
        ("incoming", "cites", "cited by", 1),
        ("incoming", "implements", "implemented by", 1),
        ("related", "related", "related", 1),
    ]

    rendered = _text(links_card(RecordSubject(), extras))
    assert rendered.index("Outgoing · implements") < rendered.index(
        "Incoming · cited by"
    )
    assert rendered.index("Incoming · cited by") < rendered.index("Related · related")
    assert "bead:item-0" in rendered
    assert "bead:item-2" in rendered
    assert "bead:item-3" not in rendered
    assert "+1 more" in rendered
    assert "agent:upstream" in rendered
    assert "plan:source" in rendered


def test_container_relations_list_member_references() -> None:
    subject = RecordSubject(
        kind="container",
        location="archive",
        member_names=("swarm.one", "swarm.two"),
    )
    rendered = _text(relations_card(subject, RelationsExtras()))
    assert "@agent:swarm.one" in rendered
    assert "@agent:swarm.two" in rendered


def test_empty_links_and_snapshot_errors_degrade_visibly(monkeypatch) -> None:
    import sase.ace.tui.widgets.decks.record.relations as module

    empty = RelationsExtras(snapshot_source_key=())
    rendered = _text(links_card(RecordSubject(), empty))
    assert rendered == "No artifact links"

    monkeypatch.setattr(
        module,
        "load_artifact_links_snapshot",
        lambda _project: (_ for _ in ()).throw(RuntimeError("snapshot unreadable")),
    )
    extras = load_relations_extras(RecordSubject(agent_name="current"))
    rendered = _text(links_card(RecordSubject(), extras))
    assert "No artifact links" in rendered
    assert "Link index unavailable: snapshot unreadable" in rendered


def test_links_card_shows_each_relation_group_and_overflow() -> None:
    extras = RelationsExtras(
        link_groups=(
            ArtifactLinkGroup(
                direction="outgoing",
                relation="implements",
                label="implements",
                neighbor_refs=("bead:one", "bead:two", "bead:three", "bead:four"),
            ),
        )
    )
    rendered = _text(links_card(RecordSubject(), extras))
    assert "Outgoing · implements" in rendered
    assert all(f"bead:{word}" in rendered for word in ("one", "two", "three"))
    assert "bead:four" not in rendered
    assert "+1 more" in rendered
