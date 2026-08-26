"""Typed clan-dispatch coverage for cross-member wait relinking."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.launch_admission_store import admission_dir, write_unit_receipt
from sase.axe.chop_typed_admission import make_axe_chop_agent_dispatcher
from sase.xprompt.directives import extract_prompt_directives
from tests._axe_chop_proposal_launch_clan_dispatch_helpers import (
    capturing_launch,
    wait_unit,
    wait_unit_metadata,
)


def test_typed_chop_dispatch_restores_wait_from_durable_receipt(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    root = admission_dir(tmp_path)
    write_unit_receipt(
        root,
        logical_id="unit-1",
        fingerprint="fp-1",
        identity="actual.first",
    )
    metadata = {
        "unit-1": wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id="first",
            agent_name="planned.first",
        ),
        "unit-2": wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id="second",
            agent_name="planned.second",
            wait_on="first",
            wait_logical_id="unit-1",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "actual.second"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, identity, message, _results = dispatcher(
        wait_unit("unit-2", identity="second"), "fp-2"
    )

    assert ok is True
    assert identity == "actual.second"
    assert message is None
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == ["actual.first"]
    assert recorded[0]["wait_on"] == "first"
    assert recorded[0]["wait_name"] == "actual.first"


def test_typed_chop_dispatch_preserves_index_zero_wait_reference(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    root = admission_dir(tmp_path)
    write_unit_receipt(
        root,
        logical_id="unit-1",
        fingerprint="fp-1",
        identity="actual.first",
    )
    metadata = {
        "unit-1": wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id=None,
            agent_name="planned.first",
        ),
        "unit-2": wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id=None,
            agent_name="planned.second",
            wait_on=0,
            wait_logical_id="unit-1",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "actual.second"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(wait_unit("unit-2", identity="second"), "fp-2")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == ["actual.first"]
    assert recorded[0]["wait_on"] == 0
    assert recorded[0]["wait_name"] == "actual.first"


def test_typed_chop_dispatch_relinks_wait_across_skipped_middle_member(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    root = admission_dir(tmp_path)
    write_unit_receipt(
        root,
        logical_id="unit-1",
        fingerprint="fp-1",
        identity="actual.first",
    )
    metadata = {
        "unit-1": wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id="first",
            agent_name="planned.first",
        ),
        "unit-2": wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id="second",
            agent_name="planned.second",
            wait_on="first",
            wait_logical_id="unit-1",
        ),
        "unit-3": wait_unit_metadata(
            "unit-3",
            index=2,
            proposal_id="third",
            agent_name="planned.third",
            wait_on="second",
            wait_logical_id="unit-2",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "actual.third"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(wait_unit("unit-3", identity="third"), "fp-3")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == ["actual.first"]
    assert "planned.second" not in calls[0][0]
    assert recorded[0]["wait_on"] == "first"
    assert recorded[0]["wait_name"] == "actual.first"


def test_typed_chop_dispatch_drops_wait_when_no_ancestor_launched(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    metadata = {
        "unit-1": wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id="first",
            agent_name="planned.first",
        ),
        "unit-2": wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id="second",
            agent_name="planned.second",
            wait_on="first",
            wait_logical_id="unit-1",
        ),
        "unit-3": wait_unit_metadata(
            "unit-3",
            index=2,
            proposal_id="third",
            agent_name="planned.third",
            wait_on="second",
            wait_logical_id="unit-2",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=capturing_launch(calls, "actual.third"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(wait_unit("unit-3", identity="third"), "fp-3")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == []
    assert "planned.second" not in calls[0][0]
    assert recorded[0]["wait_on"] is None
    assert recorded[0]["wait_name"] is None
