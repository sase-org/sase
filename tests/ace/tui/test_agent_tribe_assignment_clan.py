"""Tests for clan-scoped tribe reassignment in the Agents tab."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals.agent_tribe_modal import AgentTribeModalResult
from tests.ace.tui._agent_tribe_assignment_helpers import (
    _FakeApp,
    _make_agent,
    _make_clan_container,
    _make_clan_member,
)


def test_clan_tribe_reassignment_rewrites_only_declaring_prompt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    declarer_dir = tmp_path / "declarer"
    joiner_dir = tmp_path / "joiner"
    for artifacts_dir, prompt, name in (
        (
            declarer_dir,
            "%id:research.lead\n"
            "%clan(research, tribe=old, "
            "summary_script=sase_clan_summary_epic)\n"
            "Lead",
            "research.lead",
        ),
        (
            joiner_dir,
            "%id(worker, clan=research)\nWork",
            "research.worker",
        ),
    ):
        artifacts_dir.mkdir()
        (artifacts_dir / "raw_xprompt.md").write_text(prompt, encoding="utf-8")
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "agent_clan": "research",
                    "agent_clan_generation": "g1",
                    "clan_tribe": "old",
                }
            ),
            encoding="utf-8",
        )

    declarer = _make_agent(
        suffix="declarer",
        artifacts_dir=str(declarer_dir),
        agent_name="research.lead",
        agent_clan="research",
        agent_clan_generation="g1",
        clan_tribe="old",
    )
    joiner = _make_agent(
        suffix="joiner",
        artifacts_dir=str(joiner_dir),
        agent_name="research.worker",
        agent_clan="research",
        agent_clan_generation="g1",
        clan_tribe="old",
    )
    app = _FakeApp([declarer, joiner])

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [declarer, joiner],
        )

    assert (declarer_dir / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%id:research.lead\n"
        "%clan(research, tribe=new, "
        "summary_script=sase_clan_summary_epic)\n"
        "Lead"
    )
    assert (joiner_dir / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%id(worker, clan=research)\nWork"
    )
    assert (
        json.loads((declarer_dir / "agent_meta.json").read_text(encoding="utf-8"))[
            "clan_tribe"
        ]
        == "new"
    )
    assert (
        json.loads((joiner_dir / "agent_meta.json").read_text(encoding="utf-8"))[
            "clan_tribe"
        ]
        == "new"
    )


def test_synthetic_clan_row_edit_writes_record_only(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sase.core.agent_clan_record import load_clan_record

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    tribe_file = tmp_path / "agent_tribes.json"
    container = _make_clan_container()
    app = _FakeApp([container])
    assert container.get_artifacts_dir() is None

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [container],
        )

    assert container.clan_tribe == "new"
    record = load_clan_record("research", strict=True)
    assert record is not None
    attribute = record["generations"]["g1"]["tribe"]
    assert attribute["value"] == "new"
    assert attribute["source"] == "edited"
    assert attribute["source_identity"] == "tui"
    assert not tribe_file.exists()
    assert any("for clan research" in m for m, _ in app.notifications)


def test_member_edit_writes_meta_and_record(tmp_path: Path, monkeypatch: Any) -> None:
    from sase.core.agent_clan_record import load_clan_record

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    member_dir = tmp_path / "member"
    member = _make_clan_member(member_dir)
    app = _FakeApp([member])

    with (
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [member],
        )

    assert member.clan_tribe == "new"
    meta = json.loads((member_dir / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["clan_tribe"] == "new"
    prompt = (member_dir / "raw_xprompt.md").read_text(encoding="utf-8")
    assert "%clan(research, tribe=new" in prompt
    record = load_clan_record("research", strict=True)
    assert record is not None
    assert record["generations"]["g1"]["tribe"]["value"] == "new"
    assert record["generations"]["g1"]["tribe"]["source"] == "edited"


def test_clan_edits_deduplicate_to_one_record_write(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    declarer_dir = tmp_path / "declarer"
    joiner_dir = tmp_path / "joiner"
    declarer = _make_clan_member(declarer_dir)
    joiner = _make_clan_member(
        joiner_dir,
        prompt="%id(worker, clan=research)\nWork",
        name="research.worker",
    )
    app = _FakeApp([declarer, joiner])

    captured: dict[str, Any] = {}

    def _capture_submit(target: Any, **kwargs: Any) -> bool:
        captured.update(kwargs)
        return True

    with (
        patch(
            "sase.ace.tui.actions.agent_durable.submit_agent_directive",
            _capture_submit,
        ),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [declarer, joiner],
        )

    updates = captured["payload"]["updates"]
    records = [u["clan_record"] for u in updates if "clan_record" in u]
    assert len(records) == 1
    assert records[0] == {"clan": "research", "generation": "g1", "tribe": "new"}


def test_unset_tombstone_beats_newer_epic_member_after_reload(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = tmp_path / "projects"
    member_dir = projects_root / "myproj" / "artifacts" / "ace-run" / "20260506120000"
    member = _make_clan_member(
        member_dir,
        prompt="%id(worker, clan=research)\nWork",
        name="research.worker",
    )
    app = _FakeApp([member])

    with (
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="unset", tribe=None),
            [member],
        )

    # A newer epic member still carrying clan_tribe=epic must not win.
    newer_dir = projects_root / "myproj" / "artifacts" / "ace-run" / "20260506120100"
    newer_dir.mkdir(parents=True)
    (newer_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "research.newer",
                "agent_clan": "research",
                "agent_clan_generation": "g1",
                "clan_tribe": "epic",
            }
        ),
        encoding="utf-8",
    )
    snapshot = scan_agent_artifacts(projects_root)
    contexts = [
        context
        for context in snapshot.clan_context
        if context.agent_clan == "research" and context.agent_clan_generation == "g1"
    ]
    assert len(contexts) == 1
    assert contexts[0].clan_tribe is None


def test_failed_clan_edit_rolls_back_siblings_and_container(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sase.ace.tui.proc_observer import ObservedProc as ProcInfo

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    member_dir = tmp_path / "member"
    sibling_dir = tmp_path / "sibling"
    member = _make_clan_member(member_dir)
    sibling = _make_clan_member(
        sibling_dir,
        prompt="%id(worker, clan=research)\nWork",
        name="research.worker",
    )
    container = _make_clan_container()
    app = _FakeApp([member, sibling, container])

    captured: dict[str, Any] = {}

    def _capture_submit(target: Any, **kwargs: Any) -> bool:
        captured.update(kwargs)
        return True

    with patch(
        "sase.ace.tui.actions.agent_durable.submit_agent_directive",
        _capture_submit,
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [member],
        )

    # Optimistic display covers the edited member, its sibling, and the
    # synthetic container sharing the same (clan, generation).
    assert member.clan_tribe == "new"
    assert sibling.clan_tribe == "new"
    assert container.clan_tribe == "new"

    proc_info = ProcInfo(
        proc_id="task-0",
        proc_type="agent-directive",
        cl_name="agent-tribes",
        project_file="agent-tribes",
        status="error",
        message="boom",
        started_at=datetime.now(),
    )
    captured["on_complete"](
        TrackedProcCompletion(
            proc_info=proc_info,
            success=False,
            message="boom",
            output="",
            payload=None,
            error="boom",
        )
    )

    assert member.clan_tribe == "old"
    assert sibling.clan_tribe == "old"
    assert container.clan_tribe == "old"
    assert any("persist failed" in m for m, _ in app.notifications)
