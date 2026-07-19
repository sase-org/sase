"""Real-binding coverage for deterministic clan summary resolution."""

from sase.core.agent_clan_tribe import (
    ClanTribeMemberWire,
    resolve_clan_summary,
    resolve_clan_tribe,
)


def test_real_binding_resolves_latest_explicit_clan_summary() -> None:
    members = [
        ClanTribeMemberWire(
            agent_clan="research",
            agent_clan_generation="g1",
            clan_tribe="research",
            clan_summary="first",
            launch_timestamp="01",
            identity="a",
        ),
        ClanTribeMemberWire(
            agent_clan="research",
            agent_clan_generation="g1",
            clan_summary="[bold]latest[/bold]",
            launch_timestamp="02",
            identity="b",
        ),
        ClanTribeMemberWire(
            agent_clan="research",
            agent_clan_generation="g1",
            launch_timestamp="03",
            identity="c",
        ),
    ]

    summary = resolve_clan_summary("research", "g1", members)
    tribe = resolve_clan_tribe("research", "g1", members)

    assert summary.summary == "[bold]latest[/bold]"
    assert summary.source_launch_timestamp == "02"
    assert summary.source_identity == "b"
    assert tribe.tribe == "research"
