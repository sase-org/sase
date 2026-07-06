"""Golden tests for malformed scan record inputs."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_scan_facade import scan_agent_artifacts

from .agent_scan_golden.fixture_builder import TS_MALFORMED, TS_WAITING
from .core_agent_scan_helpers import (
    core_agent_scan_fixture_root as _fixture_root,
    record_by_timestamp,
)


def test_waiting_marker_decode_error_does_not_crash(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_WAITING)
    # waiting.json was malformed; the wire reports None and the scan
    # counts the decode error.
    assert rec.waiting is None
    assert rec.agent_meta is not None
    assert rec.agent_meta.wait_for == ["upstream"]
    assert rec.agent_meta.wait_duration == 600.0


def test_malformed_agent_meta_is_skipped(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_MALFORMED)
    # The directory was visited so the record exists, but agent_meta is
    # None because the file failed to decode.
    assert rec.agent_meta is None
    assert rec.has_done_marker is False
    assert rec.done is None
