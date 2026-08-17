"""Trusted BeadStaleCleanup gate construction, presentation, and command coverage."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sase.bead.stale_cleanup_gate import (
    BEAD_STALE_CLEANUP_PREVIEW_PATH,
    create_bead_stale_cleanup_gate,
    execute_bead_stale_cleanup_gate_command,
)
from sase.notification_gates.registry import adapter_for_kind
from sase.notifications import pending_actions
from sase.notifications.priority import is_priority
from sase.notifications.store import load_notifications

from .stale_cleanup_gate_test_helpers import (
    DEFAULT_STALE_AS_OF,
    stale_cleanup_bead,
    stale_cleanup_spec,
)


def test_bead_stale_cleanup_gate_builds_canonical_spec_preview_and_pending_action(
    gate_home: Path,
) -> None:
    del gate_home
    beads = [
        stale_cleanup_bead(),
        stale_cleanup_bead(
            bead_id="sase-task.2",
            title="Document the other cache path",
            created_at="2026-08-02T09:14:02-04:00",
            plus_one_count=0,
            size=None,
        ),
    ]
    gate = create_bead_stale_cleanup_gate(
        request_id="bead-stale-cleanup-canonical",
        beads=beads,
        omitted_count=12,
        min_plus_ones=1,
        stale_after_days=7,
        stale_cleanup_min_beads=10,
        stale_as_of=DEFAULT_STALE_AS_OF,
        producer={"chop": "bead_stale_cleanup"},
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "bead_stale_cleanup"
    assert request["query"] == "close"
    assert request["branches"] == [["close"]]
    assert request["primary_branch"] == ["close"]
    assert request["payload"] == {
        "beads": beads,
        "omitted_count": 12,
        "min_plus_ones": 1,
        "stale_after_days": 7,
        "stale_cleanup_min_beads": 10,
        "stale_as_of": DEFAULT_STALE_AS_OF,
    }
    [close_option] = request["options"]
    assert close_option["id"] == "close"
    assert close_option["label"] == "Close selected"
    assert close_option["icon"] == "🧹"
    assert close_option["feedback"] == "optional"
    assert [field["id"] for field in close_option["inputs"]] == ["bead_1", "bead_2"]
    assert [field["default"] for field in close_option["inputs"]] == ["close", "close"]
    assert close_option["inputs"][0]["required"] is False
    assert close_option["inputs"][0]["choices"] == [
        {"value": "close", "label": "Close"},
        {"value": "keep", "label": "Keep"},
    ]
    assert close_option["inputs"][0]["label"] == (
        "sase-task.1 — Follow up on cache invalidation"
    )
    assert (
        "sase · +0 · created 2026-08-01 (16 days ago)"
        in close_option["inputs"][0]["help"]
    )
    assert request["presentation"]["sender"] == "bead"
    assert request["presentation"]["icon"] == "🧹"
    assert request["presentation"]["title"] == "Stale Task Cleanup"
    assert request["presentation"]["notes"] == [
        "2 stale task beads · no +1 after 7 days"
    ]
    assert request["presentation"]["tags"] == ["bead", "task", "stale"]
    assert request["presentation"]["panel"] == "beads"
    assert request["presentation"]["panel_icon"] == "◈"
    assert "origin_agent" not in request["presentation"]
    preview = (gate.bundle_path / BEAD_STALE_CLEANUP_PREVIEW_PATH).read_text(
        encoding="utf-8"
    )
    assert "# Stale task beads" in preview
    assert "fewer than 1 +1 report" in preview
    assert "at least 7 days" in preview
    assert "at least 10 such beads" in preview
    assert "sase-task.1" in preview
    assert "sase-task.2" in preview
    assert "16d" in preview
    assert "12 additional stale task beads were omitted from this roster." in preview

    [notification] = load_notifications()
    assert notification.action == "BeadStaleCleanup"
    assert notification.sender == "bead"
    assert notification.icon == "🧹"
    assert notification.tags == ["bead", "task", "stale"]
    assert notification.action_data["panel"] == "beads"
    assert notification.action_data["panel_icon"] == "◈"
    assert is_priority(notification)
    [entry] = pending_actions.read_pending_action_store()["actions"].values()
    assert entry["action_kind"] == "bead_stale_cleanup"
    adapter = adapter_for_kind("bead_stale_cleanup")
    assert adapter.auto_policy == "forbidden"
    assert adapter.generic_form is True
    assert adapter.neutral_only is True
    assert adapter.default_feedback == "optional"
    assert adapter.display_title == "Stale Task Cleanup"
    assert adapter.action == "BeadStaleCleanup"


def test_bead_stale_cleanup_truncates_long_input_labels(gate_home: Path) -> None:
    del gate_home
    long_title = "x" * 200
    spec = stale_cleanup_spec(
        request_id="bead-stale-cleanup-long-title",
        beads=[stale_cleanup_bead(title=long_title)],
    )
    from sase.notification_gates.service import create_gate

    gate = create_gate(spec)
    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    label = request["options"][0]["inputs"][0]["label"]
    assert len(label) <= 120
    assert label.endswith("…")


def _run_command(gate_bundle_path: Path, command_path: Path, stdin: bytes) -> Any:
    return subprocess.run(
        [str(command_path)],
        cwd=gate_bundle_path,
        input=stdin,
        capture_output=True,
        check=False,
    )


def test_bead_stale_cleanup_command_defaults_absent_fields_to_close(
    gate_home: Path,
) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    spec = stale_cleanup_spec(
        request_id="bead-stale-cleanup-default-close",
        beads=[
            stale_cleanup_bead(),
            stale_cleanup_bead(bead_id="sase-task.2"),
        ],
    )
    gate = create_gate(spec)
    command_path = gate.bundle_path / "commands" / "close"

    completed = _run_command(gate.bundle_path, command_path, b"{}\n")

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "action": "close",
        "close_bead_indexes": [1, 2],
    }


def test_bead_stale_cleanup_command_keep_removes_exactly_that_index(
    gate_home: Path,
) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    spec = stale_cleanup_spec(
        request_id="bead-stale-cleanup-keep-one",
        beads=[
            stale_cleanup_bead(),
            stale_cleanup_bead(bead_id="sase-task.2"),
            stale_cleanup_bead(bead_id="sase-task.3"),
        ],
    )
    gate = create_gate(spec)
    command_path = gate.bundle_path / "commands" / "close"

    completed = _run_command(
        gate.bundle_path,
        command_path,
        json.dumps({"bead_2": "keep"}).encode(),
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "action": "close",
        "close_bead_indexes": [1, 3],
    }


def test_bead_stale_cleanup_command_all_keep_exits_2(gate_home: Path) -> None:
    del gate_home
    from sase.notification_gates.service import create_gate

    spec = stale_cleanup_spec(
        request_id="bead-stale-cleanup-all-keep",
        beads=[
            stale_cleanup_bead(),
            stale_cleanup_bead(bead_id="sase-task.2"),
        ],
    )
    gate = create_gate(spec)
    command_path = gate.bundle_path / "commands" / "close"

    completed = _run_command(
        gate.bundle_path,
        command_path,
        json.dumps({"bead_1": "keep", "bead_2": "keep"}).encode(),
    )

    assert completed.returncode == 2
    assert (
        b"select at least one bead to close, or dismiss this gate" in completed.stderr
    )


def _run_execute(bead_count: int, raw: object) -> tuple[int, str, str]:
    stdin = io.StringIO(raw if isinstance(raw, str) else json.dumps(raw) + "\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr
    try:
        code = execute_bead_stale_cleanup_gate_command(bead_count)
    finally:
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
    return code, stdout.getvalue(), stderr.getvalue()


def test_bead_stale_cleanup_command_rejects_non_object_stdin() -> None:
    code, _stdout, stderr = _run_execute(1, [1, 2])
    assert code == 2
    assert "must be an object" in stderr


def test_bead_stale_cleanup_command_rejects_unknown_field_id() -> None:
    code, _stdout, stderr = _run_execute(1, {"bead_9": "close"})
    assert code == 2
    assert "unknown field id" in stderr


def test_bead_stale_cleanup_command_rejects_out_of_range_value() -> None:
    code, _stdout, stderr = _run_execute(1, {"bead_1": "maybe"})
    assert code == 2
    assert "bead_1" in stderr
