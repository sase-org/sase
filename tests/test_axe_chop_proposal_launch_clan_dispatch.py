"""Typed clan-dispatch coverage for chop proposal launches."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.axe.chop_typed_admission import make_axe_chop_agent_dispatcher
from sase.xprompt.directives import extract_prompt_directives
from tests._axe_chop_proposal_launch_clan_dispatch_helpers import (
    capturing_launch,
    clan_marker_path,
    clan_unit,
    clan_unit_metadata,
)


def test_typed_clan_dispatch_declares_the_originally_planned_declarer(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    unit = clan_unit(
        "unit-1",
        identity="toobig-x.first",
        clan_declared=True,
        clan="toobig-x",
        clan_tribe="chop",
        clan_summary="[bold]Large[/bold]",
    )
    metadata = {
        "unit-1": clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        )
    }
    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "toobig-x.first"),
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, identity, message, results = dispatcher(unit, "fp-1")

    assert ok is True
    assert identity == "toobig-x.first"
    assert message is None
    assert len(results) == 1
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.name == "toobig-x.first"
    assert directives.clan == "toobig-x"
    assert directives.clan_declared is True
    assert directives.clan_tribe == "chop"
    assert directives.clan_summary == "[bold]Large[/bold]"
    assert clan_marker_path(tmp_path, "toobig-x").exists()


def test_typed_clan_dispatch_promotes_next_member_when_declarer_skipped(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    # unit-1 is the statically planned declarer, but admission skipped it
    # (its `%if` predicate was false) so the dispatcher never runs for it.
    joiner_unit = clan_unit(
        "unit-2", identity="second", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        "unit-1": clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        ),
        "unit-2": clan_unit_metadata(
            "unit-2",
            clan="toobig-x",
            member_id="second",
            agent_name="toobig-x.second",
            declares_clan=False,
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "toobig-x.second"),
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, identity, _message, _results = dispatcher(joiner_unit, "fp-2")

    assert ok is True
    assert identity == "toobig-x.second"
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.name == "toobig-x.second"
    assert directives.clan == "toobig-x"
    assert directives.clan_declared is True
    assert directives.clan_tribe == "chop"
    assert directives.clan_summary == "[bold]Large[/bold]"


def test_typed_clan_dispatch_promotes_after_several_leading_skips(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    # unit-1 and unit-2 are both skipped; only unit-3 ever dispatches.
    third_unit = clan_unit(
        "unit-3", identity="third", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        f"unit-{n}": clan_unit_metadata(
            f"unit-{n}",
            clan="toobig-x",
            member_id=name,
            agent_name=f"toobig-x.{name}",
            declares_clan=(n == 1),
        )
        for n, name in ((1, "first"), (2, "second"), (3, "third"))
    }
    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "toobig-x.third"),
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(third_unit, "fp-3")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.name == "toobig-x.third"
    assert directives.clan_declared is True


def test_typed_clan_dispatch_all_skipped_batch_writes_no_clan_marker(
    tmp_path: Path,
) -> None:
    metadata = {
        "unit-1": clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        )
    }
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None
    # The dispatcher exists, but admission never called it because every
    # member was skipped or condition-errored, so no clan is ever claimed.
    assert not clan_marker_path(tmp_path, "toobig-x").exists()


def test_typed_clan_dispatch_promotion_is_durable_across_fresh_dispatcher(
    tmp_path: Path,
) -> None:
    """A restarted coordinator builds a brand-new dispatcher closure; the
    declarer claim must still come from the durable bundle dir, not from
    Python state carried over in the previous closure."""
    pytest.importorskip("sase_core_rs")
    declarer_unit = clan_unit(
        "unit-1",
        identity="toobig-x.first",
        clan_declared=True,
        clan="toobig-x",
        clan_tribe="chop",
        clan_summary="[bold]Large[/bold]",
    )
    joiner_unit = clan_unit(
        "unit-2", identity="second", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        "unit-1": clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        ),
        "unit-2": clan_unit_metadata(
            "unit-2",
            clan="toobig-x",
            member_id="second",
            agent_name="toobig-x.second",
            declares_clan=False,
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []

    dispatcher_1 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "toobig-x.first"),
        bundle_dir=tmp_path,
    )
    assert dispatcher_1 is not None
    dispatcher_1(declarer_unit, "fp-1")

    dispatcher_2 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "toobig-x.second"),
        bundle_dir=tmp_path,
    )
    assert dispatcher_2 is not None
    dispatcher_2(joiner_unit, "fp-2")

    assert len(calls) == 2
    _, first_directives = extract_prompt_directives(calls[0][0])
    _, second_directives = extract_prompt_directives(calls[1][0])
    assert first_directives.clan_declared is True
    assert second_directives.clan_declared is False
    assert second_directives.clan == "toobig-x"
    assert second_directives.name == "toobig-x.second"


def test_typed_clan_dispatch_failed_declarer_blocks_second_declaration(
    tmp_path: Path,
) -> None:
    """A declarer launch that fails must still hold the declarer claim, so a
    later member cannot accidentally declare the same clan a second time."""
    pytest.importorskip("sase_core_rs")
    declarer_unit = clan_unit(
        "unit-1", identity="toobig-x.first", clan_declared=True, clan="toobig-x"
    )
    joiner_unit = clan_unit(
        "unit-2", identity="second", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        "unit-1": clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        ),
        "unit-2": clan_unit_metadata(
            "unit-2",
            clan="toobig-x",
            member_id="second",
            agent_name="toobig-x.second",
            declares_clan=False,
        ),
    }

    def _empty_launch(
        prompt: str, *, extra_env: dict[str, str]
    ) -> list[SimpleNamespace]:
        del prompt, extra_env
        return []

    dispatcher_1 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_empty_launch,
        bundle_dir=tmp_path,
    )
    assert dispatcher_1 is not None
    ok, identity, message, results = dispatcher_1(declarer_unit, "fp-1")
    assert ok is False
    assert identity is None
    assert message == "agent_dispatch_produced_no_results"
    assert results == []
    assert clan_marker_path(tmp_path, "toobig-x").exists()

    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher_2 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "toobig-x.second"),
        bundle_dir=tmp_path,
    )
    assert dispatcher_2 is not None
    dispatcher_2(joiner_unit, "fp-2")

    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.clan_declared is False
    assert directives.clan == "toobig-x"
    assert directives.name == "toobig-x.second"
