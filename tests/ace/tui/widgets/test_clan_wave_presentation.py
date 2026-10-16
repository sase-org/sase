from sase.ace.tui.models._agent_clan_waves import (
    ClanWaveSummary,
    _ClanWaveState,
    _ClanWaveView,
)
from sase.ace.tui.widgets._clan_wave_presentation import format_clan_wave_pips


def _wave(number: int | None, state: _ClanWaveState, *, kind: str = "number"):
    return _ClanWaveView(
        number=number,
        kind=kind,
        member_identities=(f"member-{number}",),
        ghost_names=(),
        state=state,
        predecessor_identities=(),
    )


def test_clan_wave_pips_render_each_numbered_state_and_seal() -> None:
    summary = ClanWaveSummary(
        layered=True,
        numbered_wave_count=6,
        has_seal=True,
        waves=(
            _wave(1, _ClanWaveState.FAILED),
            _wave(2, _ClanWaveState.NEEDS_YOU),
            _wave(3, _ClanWaveState.IN_FLIGHT),
            _wave(4, _ClanWaveState.DONE),
            _wave(5, _ClanWaveState.NOT_STARTED),
            _wave(6, _ClanWaveState.DISMISSED_ONLY),
            _wave(None, _ClanWaveState.DONE, kind="seal"),
        ),
        members=(),
        unresolved_identities=(),
    )

    pips = format_clan_wave_pips(summary)

    assert pips.plain == "✗▲◐●○· ∎"
    assert pips.spans[-1].style is not None
    assert "#5FD75F" in str(pips.spans[-1].style)


def test_clan_wave_pips_compact_more_than_twelve_numbered_waves() -> None:
    numbered = tuple(
        _wave(
            index,
            _ClanWaveState.IN_FLIGHT if index == 1 else _ClanWaveState.DONE,
        )
        for index in range(1, 15)
    )
    summary = ClanWaveSummary(
        layered=True,
        numbered_wave_count=14,
        has_seal=True,
        waves=(*numbered, _wave(None, _ClanWaveState.NOT_STARTED, kind="seal")),
        members=(),
        unresolved_identities=(),
    )

    assert format_clan_wave_pips(summary).plain == "◐ 13/14 ∎"


def test_clan_wave_pips_are_absent_for_flat_clans() -> None:
    summary = ClanWaveSummary(
        layered=False,
        numbered_wave_count=1,
        has_seal=False,
        waves=(_wave(1, _ClanWaveState.IN_FLIGHT),),
        members=(),
        unresolved_identities=(),
    )

    assert format_clan_wave_pips(summary).plain == ""
