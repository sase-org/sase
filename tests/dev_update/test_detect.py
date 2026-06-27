"""Tests for latest dev-version detection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.dev_update.detect import detect_dev_latest
import sase.dev_update.detect as detect_mod
from sase.version._git import GitUpstreamStatus
from sase.version._models import (
    GitProbeResult,
    GitVersionMetadata,
    VersionPackageRecord,
)


def _record(
    name: str = "sase",
    *,
    install_type: str = "editable",
    source_root: str | None = "/repo",
    display_version: str = "0.5.0+1.gaaaaaaaaa",
    role: str = "host",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version=display_version,
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=source_root,
        distribution_location=None,
        install_type=install_type,  # type: ignore[arg-type]
        git=None,
    )


def _status(
    *,
    dirty: bool = False,
    detached: bool = False,
    upstream: str | None = "origin/main",
    ahead: int | None = 0,
    behind: int | None = 0,
) -> GitUpstreamStatus:
    return GitUpstreamStatus(
        root="/repo",
        upstream=upstream,
        remote="origin" if upstream else None,
        remote_branch="main" if upstream else None,
        detached=detached,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
    )


def _probe(_root: Path, _ref: str = "HEAD") -> GitProbeResult:
    return GitProbeResult(
        GitVersionMetadata(
            root="/repo",
            commit="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            short_commit="bbbbbbbbb",
            tag="v0.5.0",
            distance=4,
            dirty=False,
        )
    )


def test_detect_dev_latest_reports_update_available_after_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetches: list[GitUpstreamStatus] = []
    monkeypatch.setattr(
        detect_mod, "classify_git_upstream", lambda _root: _status(behind=2)
    )
    monkeypatch.setattr(detect_mod, "probe_git_metadata_at_ref", _probe)
    monkeypatch.setattr(detect_mod, "fetch_git_upstream", fetches.append)

    latest = detect_dev_latest(_record(), offline=False)

    assert latest.state == "update_available"
    assert latest.update_available is True
    assert latest.current_version == "0.5.0+1.gaaaaaaaaa"
    assert latest.latest_version == "0.5.0+4.gbbbbbbbbb"
    assert latest.upstream == "origin/main"
    assert latest.behind == 2
    assert len(fetches) == 1


def test_detect_dev_latest_offline_uses_cached_ref_without_update_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detect_mod, "classify_git_upstream", lambda _root: _status(behind=3)
    )
    monkeypatch.setattr(detect_mod, "probe_git_metadata_at_ref", _probe)

    def fail_fetch(_status: GitUpstreamStatus) -> None:
        raise AssertionError("offline detection must not fetch")

    monkeypatch.setattr(detect_mod, "fetch_git_upstream", fail_fetch)

    latest = detect_dev_latest(_record(), offline=True)

    assert latest.state == "offline"
    assert latest.update_available is False
    assert latest.latest_version == "0.5.0+4.gbbbbbbbbb"


@pytest.mark.parametrize(
    ("status", "state", "reason"),
    [
        (_status(dirty=True, behind=1), "dirty", "local changes"),
        (_status(ahead=1, behind=1), "diverged", "diverged"),
        (
            _status(detached=True, upstream=None, ahead=None, behind=None),
            "detached",
            "detached",
        ),
        (_status(upstream=None, ahead=None, behind=None), "no_upstream", "no upstream"),
    ],
)
def test_detect_dev_latest_non_actionable_states(
    monkeypatch: pytest.MonkeyPatch,
    status: GitUpstreamStatus,
    state: str,
    reason: str,
) -> None:
    monkeypatch.setattr(detect_mod, "classify_git_upstream", lambda _root: status)
    monkeypatch.setattr(detect_mod, "probe_git_metadata_at_ref", _probe)
    monkeypatch.setattr(detect_mod, "fetch_git_upstream", lambda _status: None)

    latest = detect_dev_latest(_record(), offline=False)

    assert latest.state == state
    assert latest.update_available is False
    assert reason in latest.reason


def test_detect_dev_latest_fetch_failure_is_non_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detect_mod, "classify_git_upstream", lambda _root: _status(behind=2)
    )
    monkeypatch.setattr(detect_mod, "probe_git_metadata_at_ref", _probe)

    def fail_fetch(_status: GitUpstreamStatus) -> None:
        raise subprocess.CalledProcessError(1, ["git"], stderr="network down")

    monkeypatch.setattr(detect_mod, "fetch_git_upstream", fail_fetch)

    latest = detect_dev_latest(_record(), offline=False)

    assert latest.state == "fetch_failed"
    assert latest.update_available is False
    assert latest.fetch_error == "network down"
    assert latest.latest_version == "0.5.0+4.gbbbbbbbbb"


def test_detect_dev_latest_rejects_non_editable_record() -> None:
    latest = detect_dev_latest(_record(install_type="wheel"), offline=False)

    assert latest.state == "unavailable"
    assert latest.update_available is False
    assert "not an editable install" in latest.reason
