"""Tests for the external mirror's durable cursor, backoff, and auth state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.external_mirror.auth import (
    classify_provider_error,
    read_tracker_probes,
    record_tracker_probe,
)
from sase.external_mirror.state import (
    _MirrorState,
    is_backed_off,
    mirror_state_document_path,
    next_backoff,
    pr_mirror_state_dir,
    read_mirror_state,
    write_mirror_state,
)


@pytest.fixture(autouse=True)
def _redirect_sase_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_state_round_trips() -> None:
    path = mirror_state_document_path("issues", "sase")
    state = _MirrorState(
        project="sase",
        watermark_updated_at="2026-08-10T18:00:00Z",
        watermark_provider_ids=("I_1", "I_2"),
        backfill_complete=True,
        last_full_scan_at="2026-08-10T06:00:00Z",
        last_success_at="2026-08-10T18:02:11Z",
        upstream_states={"bug:sase#42": "open"},
        failures=0,
        next_attempt_at="",
    )
    write_mirror_state(path, state)

    loaded = read_mirror_state(path, project="sase")

    assert loaded == state


def test_missing_file_yields_fresh_state(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    state = read_mirror_state(path, project="sase")
    assert state == _MirrorState(project="sase")


def test_corrupt_file_yields_fresh_state(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    state = read_mirror_state(path, project="sase")

    assert state == _MirrorState(project="sase")


def test_truncated_file_yields_fresh_state(tmp_path: Path) -> None:
    path = tmp_path / "truncated.json"
    path.write_text('{"schema_version": 1, "project": "sase"', encoding="utf-8")

    state = read_mirror_state(path, project="sase")

    assert state == _MirrorState(project="sase")


def test_wrong_schema_version_yields_fresh_state(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text('{"schema_version": 999, "project": "sase"}', encoding="utf-8")

    state = read_mirror_state(path, project="sase")

    assert state == _MirrorState(project="sase")


def test_backoff_grows_exponentially_and_caps() -> None:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    failures = 0
    seen_delays = []
    for _ in range(10):
        failures, next_attempt_at = next_backoff(failures, now=now)
        parsed = datetime.fromisoformat(next_attempt_at.replace("Z", "+00:00"))
        seen_delays.append((parsed - now).total_seconds())

    assert seen_delays == sorted(seen_delays)
    assert max(seen_delays) <= 3600


def test_is_backed_off() -> None:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    _failures, next_attempt_at = next_backoff(0, now=now)
    state = _MirrorState(next_attempt_at=next_attempt_at)

    assert is_backed_off(state, now=now)
    assert not is_backed_off(state, now=datetime(2026, 9, 1, tzinfo=UTC))
    assert not is_backed_off(_MirrorState(), now=now)


def test_classify_provider_error_auth() -> None:
    error = RuntimeError(
        "gh issue list: GitHub authentication required; run `gh auth login`"
    )
    assert classify_provider_error(error) == "auth_error"


def test_classify_provider_error_rate_limit() -> None:
    error = RuntimeError("gh issue list: GitHub API rate limit exceeded")
    assert classify_provider_error(error) == "rate_limited"


def test_classify_provider_error_defaults_to_unavailable() -> None:
    error = RuntimeError("gh issue list: connection reset by peer")
    assert classify_provider_error(error) == "unavailable"


def test_record_and_read_tracker_probe_round_trips() -> None:
    now = datetime(2026, 8, 10, 18, 2, 11, tzinfo=UTC)
    record_tracker_probe("sase", outcome="ok", source="chop", now=now)
    record_tracker_probe(
        "sase-github", outcome="auth_error", source="chop", detail="boom", now=now
    )

    probes = read_tracker_probes()

    assert probes["sase"].outcome == "ok"
    assert probes["sase"].source == "chop"
    assert probes["sase-github"].outcome == "auth_error"
    assert probes["sase-github"].detail == "boom"


def test_read_tracker_probes_tolerates_missing_file() -> None:
    assert read_tracker_probes() == {}


def test_pr_mirror_state_dir_migrates_legacy_checks_lane_files() -> None:
    from sase.axe.state import lumberjack_state_dir

    legacy_dir = lumberjack_state_dir("checks")
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "external_pr__sase.json").write_text(
        '{"last_provider_id": "PR_1"}', encoding="utf-8"
    )
    (legacy_dir / "external_pr__backoff.json").write_text("{}", encoding="utf-8")

    new_dir = pr_mirror_state_dir()

    assert (new_dir / "external_pr__sase.json").read_text(
        encoding="utf-8"
    ) == '{"last_provider_id": "PR_1"}'
    assert (new_dir / "external_pr__backoff.json").exists()


def test_pr_mirror_state_dir_does_not_overwrite_existing_new_file() -> None:
    from sase.axe.state import lumberjack_state_dir
    from sase.core.paths import sase_subdir

    legacy_dir = lumberjack_state_dir("checks")
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "external_pr__sase.json").write_text("stale", encoding="utf-8")

    new_dir = sase_subdir("external_mirror")
    new_dir.mkdir(parents=True, exist_ok=True)
    (new_dir / "external_pr__sase.json").write_text("fresh", encoding="utf-8")

    resolved = pr_mirror_state_dir()

    assert (resolved / "external_pr__sase.json").read_text(encoding="utf-8") == "fresh"
