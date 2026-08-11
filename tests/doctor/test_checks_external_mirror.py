"""Tests for the ``axe.external_mirror`` doctor check."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.doctor.checks_external_mirror import _check_external_mirror
from sase.doctor.runner import DoctorContext
from sase.external_mirror.auth import TrackerProbe


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")


def _configured(monkeypatch: pytest.MonkeyPatch, *, configured: bool = True) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_external_mirror._is_mirror_chop_configured",
        lambda: configured,
    )


def _enabled_projects(
    monkeypatch: pytest.MonkeyPatch, projects: tuple[str, ...]
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_external_mirror._enabled_project_keys",
        lambda: projects,
    )


def _probes(monkeypatch: pytest.MonkeyPatch, probes: dict[str, TrackerProbe]) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_external_mirror.read_tracker_probes",
        lambda: probes,
    )


def test_skip_when_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configured(monkeypatch, configured=False)

    check = _check_external_mirror(_context(tmp_path))

    assert check.status == "SKIP"
    assert check.id == "axe.external_mirror"


def test_warn_when_no_fresh_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configured(monkeypatch)
    _enabled_projects(monkeypatch, ("sase",))
    _probes(monkeypatch, {})

    check = _check_external_mirror(_context(tmp_path))

    assert check.status == "WARN"
    assert "sase" in check.data["stale_or_missing_projects"]


def test_warn_when_stale_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configured(monkeypatch)
    _enabled_projects(monkeypatch, ("sase",))
    _probes(
        monkeypatch,
        {
            "sase": TrackerProbe(
                project="sase",
                outcome="ok",
                source="chop",
                detail="",
                observed_at="2020-01-01T00:00:00+00:00",
            )
        },
    )

    check = _check_external_mirror(_context(tmp_path))

    assert check.status == "WARN"


def test_warn_on_rate_limited_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configured(monkeypatch)
    _enabled_projects(monkeypatch, ("sase",))
    _probes(
        monkeypatch,
        {
            "sase": TrackerProbe(
                project="sase",
                outcome="rate_limited",
                source="chop",
                detail="",
                observed_at=datetime.now(UTC).isoformat(),
            )
        },
    )

    check = _check_external_mirror(_context(tmp_path))

    assert check.status == "WARN"
    assert "sase" in check.data["degraded_projects"]


def test_error_on_auth_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configured(monkeypatch)
    _enabled_projects(monkeypatch, ("sase",))
    _probes(
        monkeypatch,
        {
            "sase": TrackerProbe(
                project="sase",
                outcome="auth_error",
                source="chop",
                detail="",
                observed_at=datetime.now(UTC).isoformat(),
            )
        },
    )

    check = _check_external_mirror(_context(tmp_path))

    assert check.status == "ERROR"
    assert "sase" in check.data["auth_failed_projects"]


def test_ok_when_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configured(monkeypatch)
    _enabled_projects(monkeypatch, ("sase",))
    _probes(
        monkeypatch,
        {
            "sase": TrackerProbe(
                project="sase",
                outcome="ok",
                source="chop",
                detail="",
                observed_at=datetime.now(UTC).isoformat(),
            )
        },
    )

    check = _check_external_mirror(_context(tmp_path))

    assert check.status == "OK"


def test_cli_sourced_probe_alone_does_not_produce_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configured(monkeypatch)
    _enabled_projects(monkeypatch, ("sase",))
    _probes(
        monkeypatch,
        {
            "sase": TrackerProbe(
                project="sase",
                outcome="ok",
                source="cli",
                detail="",
                observed_at=datetime.now(UTC).isoformat(),
            )
        },
    )

    check = _check_external_mirror(_context(tmp_path))

    assert check.status == "WARN"
