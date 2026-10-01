"""Project labels derived live from a clan's direct members."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_clan import clan_project_labels
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType

_GENERATION = "20261001120000"
_START = datetime(2026, 10, 1, 12, 0, 0)


def _member(
    name: str,
    suffix: str,
    *,
    status: str = "RUNNING",
    project_file: str = "/projects/bob-cli/bob-cli.sase",
    project_display_name: str | None = None,
    clan: str | None = "research",
    generation: str | None = _GENERATION,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file=project_file,
        status=status,
        start_time=_START,
        run_start_time=_START,
        raw_suffix=suffix,
        agent_name=name,
        agent_clan=clan,
        agent_clan_generation=generation,
        project_display_name=project_display_name,
    )


def _container(members: list[Agent], clan: str = "research") -> Agent:
    containers = [
        row
        for row in project_clan_tree(members)
        if row.is_clan_container and row.agent_clan == clan
    ]
    assert containers, "expected a clan container"
    return containers[0]


def test_single_project_label() -> None:
    container = _container(
        [
            _member("research.one", "one"),
            _member("research.two", "two"),
        ]
    )

    assert clan_project_labels(container) == ("bob-cli",)


def test_display_name_wins_over_project_file_key() -> None:
    container = _container(
        [
            _member(
                "research.one",
                "one",
                project_file="/projects/other/other.sase",
                project_display_name="bob-cli",
            ),
        ]
    )

    assert clan_project_labels(container) == ("bob-cli",)


def test_project_file_parent_is_the_fallback() -> None:
    container = _container(
        [
            _member(
                "research.one",
                "one",
                project_file="/projects/sase/sase.sase",
            ),
        ]
    )

    assert clan_project_labels(container) == ("sase",)


def test_dominant_project_first_with_casefold_tiebreak() -> None:
    container = _container(
        [
            _member("research.one", "one", project_file="/projects/sase/sase.sase"),
            _member(
                "research.two", "two", project_file="/projects/chezmoi/chezmoi.sase"
            ),
            _member("research.three", "three", project_file="/projects/sase/sase.sase"),
            _member(
                "research.four", "four", project_file="/projects/bob-cli/bob-cli.sase"
            ),
            _member(
                "research.five", "five", project_file="/projects/bob-cli/bob-cli.sase"
            ),
        ]
    )

    # bob-cli and sase tie at two members each; the tie breaks alphabetically.
    assert clan_project_labels(container) == ("bob-cli", "sase", "chezmoi")


def test_case_insensitive_deduplication_keeps_first_spelling() -> None:
    container = _container(
        [
            _member(
                "research.one",
                "one",
                project_file="/projects/x/x.sase",
                project_display_name="Bob-CLI",
            ),
            _member(
                "research.two",
                "two",
                project_file="/projects/x/x.sase",
                project_display_name="bob-cli",
            ),
        ]
    )

    assert clan_project_labels(container) == ("Bob-CLI",)


def test_members_without_a_project_are_skipped() -> None:
    container = _container(
        [
            _member("research.one", "one", project_file=""),
            _member("research.two", "two"),
        ]
    )

    assert clan_project_labels(container) == ("bob-cli",)


def test_empty_clan_gives_no_labels() -> None:
    container = _container([_member("research.one", "one")])
    container.runtime_children = []

    assert clan_project_labels(container) == ()


def test_non_clan_agent_gives_no_labels() -> None:
    member = _member("research.one", "one", clan=None, generation=None)

    assert clan_project_labels(member) == ()


def test_rows_from_another_clan_or_generation_are_excluded() -> None:
    container = _container(
        [
            _member("research.one", "one"),
            _member(
                "other.one",
                "other-one",
                clan="other",
                project_file="/projects/sase/sase.sase",
            ),
            _member(
                "research.stale",
                "stale",
                generation="20000101000000",
                project_file="/projects/chezmoi/chezmoi.sase",
            ),
        ]
    )

    assert clan_project_labels(container) == ("bob-cli",)


def test_duplicate_member_identity_counts_once() -> None:
    container = _container(
        [
            _member("research.one", "one"),
            _member(
                "research.one",
                "one",
                project_file="/projects/sase/sase.sase",
            ),
        ]
    )

    assert clan_project_labels(container) == ("bob-cli",)


def test_session_member_turns_are_not_counted_separately() -> None:
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="session-test",
        project_file="/projects/bob-cli/bob-cli.sase",
        status="DONE",
        start_time=_START,
        stop_time=_START,
        raw_suffix="20261001120000",
        agent_name="alpha--0",
        agent_session="alpha",
        agent_session_role="root",
        role_suffix="--0",
        agent_clan="research",
        agent_clan_generation=_GENERATION,
    )
    turn = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="session-test",
        project_file="/projects/sase/sase.sase",
        status="RUNNING",
        start_time=_START,
        run_start_time=_START,
        raw_suffix="20261001120100",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name="alpha--code",
        agent_session="alpha",
        agent_session_role="code",
        agent_clan="research",
        agent_clan_generation=_GENERATION,
    )
    root.followup_agents = [turn]
    turn.agent_session_container = root
    container = _container([root, turn])

    assert [member.identity for member in container.runtime_children] == [
        root.identity
    ] or turn not in container.runtime_children
    assert clan_project_labels(container) == ("bob-cli",)
