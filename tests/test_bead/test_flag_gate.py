"""Trusted FlagTriage gate construction, presentation, and command coverage."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sase.bead.flag_gate import (
    FLAG_TRIAGE_PREVIEW_PATH,
    create_flag_triage_gate,
)
from sase.bead.model import FlagRecord
from sase.notification_gates.registry import adapter_for_kind
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications

from .flag_gate_test_helpers import flag_triage_spec


def test_flag_triage_gate_builds_canonical_spec_preview_and_pending_action(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_flag_triage_gate(
        request_id="flag-triage-canonical",
        bead_id="sase-flag.1",
        project="sase",
        title="Remove the prettier_enabled flag",
        flag=FlagRecord(
            key="prettier_enabled",
            remove_by_date="2026-08-01",
            remove_by_release="0.16.0",
        ),
        due_state="due",
        due_as_of="2026-08-16",
        release="0.16.0",
        definition={"kind": "sunset", "description": "Routes prettier formatting."},
        description="Roll out the new formatter by default.",
        notes="Discovered while landing sase-bg.",
        created_by="claude_coder",
        created_at="2026-01-01T00:00:00Z",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "flag_triage"
    assert request["query"] == "remove OR extend OR keep OR close"
    assert request["branches"] == [["remove"], ["extend"], ["keep"], ["close"]]
    assert request["primary_branch"] == ["remove"]
    assert request["payload"] == {
        "bead_id": "sase-flag.1",
        "project": "sase",
        "title": "Remove the prettier_enabled flag",
        "created_at": "2026-01-01T00:00:00Z",
        "size": None,
        "refs": [],
        "flag": {
            "key": "prettier_enabled",
            "remove_by_date": "2026-08-01",
            "remove_by_release": "0.16.0",
        },
        "due_state": "due",
        "due_as_of": "2026-08-16",
        "release": "0.16.0",
        "definition": {"kind": "sunset", "description": "Routes prettier formatting."},
    }
    assert [(option["id"], option["feedback"]) for option in request["options"]] == [
        ("remove", "optional"),
        ("extend", "required"),
        ("keep", "required"),
        ("close", "required"),
    ]
    remove_option = request["options"][0]
    [winner_field] = remove_option["inputs"]
    assert winner_field["id"] == "winner"
    assert winner_field["type"] == "enum"
    assert winner_field["required"] is True
    assert winner_field["choices"] == [
        {"value": "enabled", "label": None},
        {"value": "disabled", "label": None},
    ]
    extend_option = request["options"][1]
    assert [field["id"] for field in extend_option["inputs"]] == ["until", "release"]
    assert all(field["required"] is True for field in extend_option["inputs"])
    assert request["presentation"]["sender"] == "bead"
    assert request["presentation"]["icon"] == "⚑"
    assert request["presentation"]["notes"] == [
        "sase-flag.1 [⚑ prettier_enabled] — Remove the prettier_enabled flag "
        "· DUE ⧗ +15d"
    ]
    assert request["presentation"]["tags"] == ["bead", "flag"]
    assert request["presentation"]["panel"] == "beads"
    assert request["presentation"]["panel_icon"] == "⚑"
    assert request["presentation"]["origin_agent"] == "claude_coder"
    preview = (gate.bundle_path / FLAG_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "# sase-flag.1 — Remove the prettier_enabled flag" in preview
    assert "`prettier_enabled` is due for removal" in preview
    assert "**Remove by:** 2026-08-01 · v0.16.0" in preview
    assert "**Kind:** `sunset`" in preview
    assert "## What this flag does" in preview
    assert "Routes prettier formatting." in preview
    assert "## Description" in preview
    assert "Roll out the new formatter by default." in preview
    assert "## Notes" in preview
    assert "Discovered while landing sase-bg." in preview

    [notification] = load_notifications()
    assert notification.action == "FlagTriage"
    assert notification.sender == "bead"
    assert notification.icon == "⚑"
    assert notification.tags == ["bead", "flag"]
    assert notification.action_data["panel"] == "beads"
    assert notification.action_data["panel_icon"] == "⚑"
    assert notification.action_data["origin_agent"] == "claude_coder"
    [entry] = pending_actions.read_pending_action_store()["actions"].values()
    assert entry["action_kind"] == "flag_triage"
    assert adapter_for_kind("flag_triage").auto_policy == "forbidden"
    assert adapter_for_kind("flag_triage").generic_form is True


def test_flag_triage_gate_omits_blank_origin_agent(gate_home: Path) -> None:
    del gate_home
    gate = create_flag_triage_gate(
        request_id="flag-triage-without-filer",
        bead_id="sase-flag.1",
        project="sase",
        title="Remove the prettier_enabled flag",
        flag=FlagRecord(
            key="prettier_enabled",
            remove_by_date="2026-08-01",
            remove_by_release="0.16.0",
        ),
        due_state="due",
        due_as_of="2026-08-16",
        release="0.16.0",
        created_by="  ",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert "origin_agent" not in request["presentation"]
    preview = (gate.bundle_path / FLAG_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "Filed by" not in preview
    [notification] = load_notifications()
    assert "origin_agent" not in notification.action_data


def _run_command(gate_bundle_path: Path, command_path: Path, stdin: bytes) -> Any:
    return subprocess.run(
        [str(command_path)],
        cwd=gate_bundle_path,
        input=stdin,
        capture_output=True,
        check=False,
    )


def test_flag_triage_remove_command_happy_path(gate_home: Path) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    gate = create_gate(flag_triage_spec(request_id="flag-triage-remove-cmd"))
    command_path = gate.bundle_path / "commands" / "remove"

    completed = _run_command(gate.bundle_path, command_path, b'{"winner": "enabled"}\n')

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"action": "remove", "winner": "enabled"}


def test_flag_triage_remove_command_rejects_bad_winner(gate_home: Path) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    gate = create_gate(flag_triage_spec(request_id="flag-triage-remove-bad-cmd"))
    command_path = gate.bundle_path / "commands" / "remove"

    completed = _run_command(gate.bundle_path, command_path, b'{"winner": "maybe"}\n')

    assert completed.returncode == 2
    assert b"winner" in completed.stderr


def test_flag_triage_extend_command_happy_path(gate_home: Path) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    gate = create_gate(flag_triage_spec(request_id="flag-triage-extend-cmd"))
    command_path = gate.bundle_path / "commands" / "extend"

    completed = _run_command(
        gate.bundle_path,
        command_path,
        json.dumps({"until": "2026-12-01", "release": "0.17.0"}).encode(),
    )

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["action"] == "extend"
    assert result["remove_by_date"] == "2026-12-01"
    assert result["remove_by_release"] == "0.17.0"


def test_flag_triage_extend_command_rejects_unparseable_until(gate_home: Path) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    gate = create_gate(flag_triage_spec(request_id="flag-triage-extend-bad-until"))
    command_path = gate.bundle_path / "commands" / "extend"

    completed = _run_command(
        gate.bundle_path,
        command_path,
        json.dumps({"until": "not-a-date", "release": "0.17.0"}).encode(),
    )

    assert completed.returncode == 2


def test_flag_triage_extend_command_rejects_malformed_release(gate_home: Path) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    gate = create_gate(flag_triage_spec(request_id="flag-triage-extend-bad-release"))
    command_path = gate.bundle_path / "commands" / "extend"

    completed = _run_command(
        gate.bundle_path,
        command_path,
        json.dumps({"until": "2026-12-01", "release": "not-a-release"}).encode(),
    )

    assert completed.returncode == 2


def test_flag_triage_keep_and_close_commands_reject_nonempty_input(
    gate_home: Path,
) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    gate = create_gate(flag_triage_spec(request_id="flag-triage-keep-close-cmd"))

    for option_id in ("keep", "close"):
        command_path = gate.bundle_path / "commands" / option_id
        completed = _run_command(gate.bundle_path, command_path, b'{"unexpected": 1}\n')
        assert completed.returncode == 2
        assert b"must be empty" in completed.stderr

        completed = _run_command(gate.bundle_path, command_path, b"{}\n")
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == {"action": option_id}


def test_flag_triage_command_rejects_unknown_option(gate_home: Path) -> None:
    del gate_home
    from sase.bead.flag_gate import execute_flag_triage_gate_command

    stdin = io.StringIO("{}\n")
    old_stdin = sys.stdin
    sys.stdin = stdin
    try:
        result = execute_flag_triage_gate_command("bogus")
    finally:
        sys.stdin = old_stdin
    assert result == 2
