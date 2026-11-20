"""Tests for signature-grouped scheduler errors with durable counts."""

from pathlib import Path
from unittest.mock import patch

import pytest

# Import through the public seam first: sase.axe._state_scheduler imports
# sase.axe.state at module top, so it must never be imported directly first.
from sase.axe.state import (
    append_error,
    read_error_counts,
    read_errors,
)

import sase.axe._state_scheduler as sched
import sase.axe._state_scheduler_errors as sched_errors
import sase.axe._state_scheduler_shared as sched_shared


@pytest.fixture
def temp_state_dir(tmp_path: Path):
    """Isolate axe state and reset in-process error accounting."""
    state_dir = tmp_path / ".sase" / "axe"
    sched_shared.pending_write_failures = 0
    sched_shared.pending_corrupt_files = 0
    del sched_shared.pending_increments[:]
    sched_shared.pending_overflow = 0
    sched_shared.logged_kinds.clear()
    with patch("sase.axe.state.axe_state_dir", return_value=state_dir):
        yield state_dir
    sched_shared.pending_write_failures = 0
    sched_shared.pending_corrupt_files = 0
    del sched_shared.pending_increments[:]
    sched_shared.pending_overflow = 0
    sched_shared.logged_kinds.clear()


def _error(job: str, text: str, routine: str = "axe") -> dict:
    return {
        "timestamp": "2026-11-19T10:00:00-05:00",
        "lumberjack": routine,
        "job": job,
        "error": text,
        "traceback": "tb",
    }


def test_counter_keeps_exact_totals_past_ring_cap(temp_state_dir: Path) -> None:
    for index in range(150):
        entry = _error("agent_publication", f"boom {index}")
        entry["failure_signature"] = f"sig-{index:03d}"
        append_error(entry)
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 150
    assert counter["schema_version"] == 1
    assert counter["interval_start"]
    assert len(counter["groups"]) == 150
    assert sum(group["count"] for group in counter["groups"].values()) == 150
    errors = read_errors()
    assert len(errors) == sched.ERROR_RING_CAP
    assert all("failure_signature" in entry for entry in errors)
    assert errors[0]["failure_signature"] == "sig-050"
    assert errors[-1]["failure_signature"] == "sig-149"


def test_normalized_text_groups_share_one_signature(temp_state_dir: Path) -> None:
    from sase.core.axe_error_facade import signature_for_entry

    try:
        first = signature_for_entry(_error("agent_publication", "storm failure 1"))
        second = signature_for_entry(_error("agent_publication", "storm failure 999"))
    except (AttributeError, ImportError):
        pytest.skip("sase_core_rs without error-signature bindings")
    assert first == second
    for index in range(10):
        append_error(_error("agent_publication", f"storm failure {index}"))
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 10
    assert len(counter["groups"]) == 1


def test_loud_signature_cannot_evict_rare_ones(temp_state_dir: Path) -> None:
    for index in range(1000):
        append_error(_error("agent_publication", f"storm failure number {index}"))
    append_error(_error("housekeeping", "disk full on retention pass"))
    append_error(_error("orchestrator", "routine crash-looping"))
    append_error(_error("sdd-sidecar", "clone recovery failed"))
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 1003
    errors = read_errors()
    assert len(errors) <= sched.ERROR_RING_CAP
    jobs = {entry["job"] for entry in errors}
    assert {"housekeeping", "orchestrator", "sdd-sidecar"} <= jobs
    ring_signatures = {entry["failure_signature"] for entry in errors}
    for signature in ring_signatures:
        assert (
            sum(1 for entry in errors if entry["failure_signature"] == signature)
            <= sched.ERROR_RING_PER_SIGNATURE_CAP
        )


def test_explicit_failure_signature_wins(temp_state_dir: Path) -> None:
    append_error(
        {
            "timestamp": "2026-11-19T10:00:00-05:00",
            "lumberjack": "sdd-sidecar",
            "job": "workspace_sdd_clone_recovery",
            "error": "some long recovery detail text",
            "traceback": "tb",
            "failure_signature": "pinned-signature",
        }
    )
    errors = read_errors()
    assert errors[0]["failure_signature"] == "pinned-signature"
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 1
    (group,) = counter["groups"].values()
    assert group["signature"] == "pinned-signature"
    assert group["count"] == 1
    assert group["first_ts"] == group["last_ts"] == "2026-11-19T10:00:00-05:00"


def test_forced_write_failure_is_counted_and_logged_once(
    temp_state_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with patch.object(
        sched_errors, "write_json_value_atomic", side_effect=OSError("disk full")
    ):
        with caplog.at_level("WARNING"):
            append_error(_error("agent_publication", "first failure"))
            append_error(_error("agent_publication", "second failure"))
    warnings = [
        record for record in caplog.records if "Failed to write" in record.message
    ]
    assert len(warnings) == 2  # one per failure kind: counter, then ring
    assert sched_shared.pending_write_failures == 4
    append_error(_error("agent_publication", "third failure"))
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 3
    assert counter["write_failures"] == 4


def test_lock_open_failure_is_counted_and_logged_once(
    temp_state_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    lock_path = temp_state_dir / "recent_errors.json.lock"
    lock_path.mkdir(parents=True)  # open(lock, "a+") now fails with an OSError
    with caplog.at_level("WARNING"):
        append_error(_error("agent_publication", "first failure"))
        append_error(_error("agent_publication", "second failure"))
    warnings = [
        record for record in caplog.records if "Failed to lock" in record.message
    ]
    assert len(warnings) == 1
    assert sched_shared.pending_write_failures == 2
    assert len(sched_shared.pending_increments) == 2
    assert read_error_counts() is None
    lock_path.rmdir()
    append_error(_error("agent_publication", "third failure"))
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 3
    assert counter["write_failures"] == 2
    assert sched_shared.pending_write_failures == 0
    assert len(read_errors()) == 1


def test_corrupt_ring_is_preserved_aside(temp_state_dir: Path) -> None:
    ring = temp_state_dir / "recent_errors.json"
    ring.parent.mkdir(parents=True, exist_ok=True)
    ring.write_text("{not valid json")
    append_error(_error("agent_publication", "after corruption"))
    backups = list(temp_state_dir.glob("recent_errors.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "{not valid json"
    errors = read_errors()
    assert len(errors) == 1
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 1
    assert counter["corrupt_files"] == 1


def test_corrupt_counter_is_preserved_aside(temp_state_dir: Path) -> None:
    counter_file = temp_state_dir / "error_counts.json"
    counter_file.parent.mkdir(parents=True, exist_ok=True)
    counter_file.write_text("[1, 2, 3]")
    append_error(_error("agent_publication", "after corruption"))
    backups = list(temp_state_dir.glob("error_counts.json.corrupt-*"))
    assert len(backups) == 1
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 1
    assert counter["corrupt_files"] == 1


def test_grouped_facade_shapes() -> None:
    from sase.core.axe_error_facade import (
        group_errors,
        normalize_error_signature,
        signature_for_entry,
    )

    assert normalize_error_signature(
        "failed for project nut after 900s, pid 1"
    ) == normalize_error_signature("failed for project nut after 30s, pid 99999")
    assert normalize_error_signature("missing target x") != normalize_error_signature(
        "lock timeout y"
    )
    explicit = {"error": "anything", "failure_signature": "kept"}
    assert signature_for_entry(explicit) == "kept"
    response = group_errors(
        [
            {
                "routine": "axe",
                "job": "agent_publication",
                "signature": "sig-a",
                "timestamp": "2026-11-19T10:00:00-05:00",
                "sample": "first",
            },
            {
                "routine": "axe",
                "job": "agent_publication",
                "signature": "sig-a",
                "timestamp": "2026-11-19T10:05:00-05:00",
                "sample": "second",
            },
        ]
    )
    assert response["schema_version"] == 1
    (group,) = response["groups"]
    assert group["count"] == 2
    assert group["first_ts"] == "2026-11-19T10:00:00-05:00"
    assert group["last_ts"] == "2026-11-19T10:05:00-05:00"
    assert group["sample"] == "first"
