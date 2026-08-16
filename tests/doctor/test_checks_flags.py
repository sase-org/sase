"""OK / WARN / ERROR fixtures for the ``flags.*`` doctor checks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sase.doctor.checks_flags import (
    _check_flags_due,
    _check_flags_overrides,
    _check_flags_registry,
    flag_check_specs,
)
from sase.doctor.runner import DoctorContext
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import FeatureFlagDiagnostic
from tests.feature_flags._helpers import demo_flag, flag_bead, snapshot_for


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={},
    )


def test_flag_check_specs_are_registered() -> None:
    specs = flag_check_specs(_context(Path("/tmp")))
    assert [spec.id for spec in specs] == [
        "flags.due",
        "flags.overrides",
        "flags.registry",
    ]
    assert {spec.group for spec in specs} == {"flags"}


def test_flags_registry_ok_when_definition_and_bead_match(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_registry(
        _context(tmp_path),
        definitions={str(flag.key): flag},
        beads=(flag_bead("demo_flag"),),
        is_managed=True,
    )

    assert check.status == "OK"
    assert check.id == "flags.registry"


def test_flags_registry_warns_when_store_is_unavailable(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_registry(
        _context(tmp_path),
        definitions={str(flag.key): flag},
        beads=None,
        is_managed=True,
    )

    assert check.status == "WARN"
    assert "unavailable" in check.summary


def test_flags_registry_errors_when_closed_bead_survives(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_registry(
        _context(tmp_path),
        definitions={str(flag.key): flag},
        beads=(flag_bead("demo_flag", status="closed"),),
        is_managed=True,
    )

    assert check.status == "ERROR"
    assert any("closed" in detail for detail in check.details)


def test_flags_registry_skips_when_not_sase_managed(tmp_path: Path) -> None:
    check = _check_flags_registry(
        _context(tmp_path),
        definitions={},
        beads=(),
        is_managed=False,
    )

    assert check.status == "SKIP"


def test_flags_overrides_ok_when_clean(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_overrides(
        _context(tmp_path),
        snapshot=snapshot_for(flag),
        env_raw=None,
    )

    assert check.status == "OK"
    assert check.id == "flags.overrides"


def test_flags_overrides_warns_on_inherited_env(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_overrides(
        _context(tmp_path),
        snapshot=snapshot_for(
            flag,
            enabled={"demo_flag": True},
            source="env",
            source_detail=SASE_FEATURE_FLAGS_ENV,
        ),
        env_raw='{"demo_flag": true}',
    )

    assert check.status == "WARN"
    assert any("inherited" in detail for detail in check.details)


def test_flags_overrides_warns_on_unknown_config_key(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_overrides(
        _context(tmp_path),
        snapshot=snapshot_for(
            flag,
            diagnostics=(
                FeatureFlagDiagnostic(
                    severity="warning",
                    code="unknown_key",
                    message="unknown feature flag 'stale_flag' ignored",
                    source="user",
                ),
            ),
        ),
        env_raw=None,
    )

    assert check.status == "WARN"
    assert any("unknown" in detail for detail in check.details)


def test_flags_overrides_errors_on_malformed_env(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_overrides(
        _context(tmp_path),
        snapshot=snapshot_for(flag),
        env_raw="not-json",
    )

    assert check.status == "ERROR"
    assert any(SASE_FEATURE_FLAGS_ENV in detail for detail in check.details)


def test_flags_due_ok_when_live(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_due(
        _context(tmp_path),
        definitions={str(flag.key): flag},
        beads=(flag_bead("demo_flag"),),
        is_managed=True,
        today=date(2026, 8, 16),
        release="0.16.0",
    )

    assert check.status == "OK"
    assert check.id == "flags.due"


def test_flags_due_warns_when_soon(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_due(
        _context(tmp_path),
        definitions={str(flag.key): flag},
        beads=(flag_bead("demo_flag"),),
        is_managed=True,
        today=date(2026, 12, 15),
        release="0.16.0",
    )

    assert check.status == "WARN"
    assert any("approaching" in detail for detail in check.details)


def test_flags_due_errors_when_overdue(tmp_path: Path) -> None:
    flag = demo_flag("demo_flag")
    check = _check_flags_due(
        _context(tmp_path),
        definitions={str(flag.key): flag},
        beads=(flag_bead("demo_flag"),),
        is_managed=True,
        today=date(2026, 12, 15),
        release="0.19.0",
    )

    assert check.status == "ERROR"
    assert any("overdue" in detail for detail in check.details)
