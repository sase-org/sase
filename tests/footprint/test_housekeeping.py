"""Tests for the Footprint AXE job and doctor check."""

from __future__ import annotations

from datetime import date
import tomllib
from pathlib import Path

import yaml

from sase.doctor.checks_footprint import _check_footprint_spool
from sase.doctor.runner import DoctorContext
from sase.scripts import sase_chop_footprint_fold


def test_footprint_spool_doctor_warns_for_unfolded_old_records(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    spool = home / "footprint" / "spool"
    spool.mkdir(parents=True)
    filename = "2026-10-01.jsonl"
    (spool / filename).write_text("record\n", encoding="ascii")
    monkeypatch.setattr(
        "sase.core.footprint_facade.footprint_status",
        lambda *_args, **_kwargs: {
            "spool_pending": [{"file": filename, "bytes_pending": 12}]
        },
    )
    context = DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=home,
        env={"SASE_FOOTPRINT": "local"},
    )

    check = _check_footprint_spool(context, today=date(2026, 10, 10))

    assert check.status == "WARN"
    assert check.data["pending_bytes"] == 12
    assert "2026-10-01" in check.summary


def test_footprint_spool_doctor_skips_when_mode_is_off(tmp_path: Path) -> None:
    context = DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / "home",
        env={"SASE_FOOTPRINT": "off"},
    )

    check = _check_footprint_spool(context, today=date(2026, 10, 10))

    assert check.status == "SKIP"


def test_hourly_job_is_registered_and_emits_fold_summary(monkeypatch) -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["sase_job_footprint_fold"] == (
        "sase.scripts.sase_chop_footprint_fold:main"
    )
    defaults = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    jobs = defaults["axe"]["routines"]["housekeeping"]["jobs"]
    assert any(
        job["name"] == "footprint_fold" and job["script"] == "sase_job_footprint_fold"
        for job in jobs
    )

    class Runtime:
        def __init__(self) -> None:
            self.summary = None
            self.reason = None

        def log(self, _message: str, _color: str) -> None:
            pass

        def emit_summary(self, summary, *, reason=None):
            self.summary = summary
            self.reason = reason
            return summary

    monkeypatch.setattr(
        sase_chop_footprint_fold,
        "fold_ledger",
        lambda: {
            "folded": True,
            "reason": None,
            "fold": {"files_folded": 1, "records_folded": 2},
            "prune": {"daily_deleted": 0, "coverage_deleted": 0},
        },
    )
    runtime = Runtime()

    sase_chop_footprint_fold._run(runtime)

    assert runtime.summary["records_folded"] == 2
    assert runtime.summary["folded"] is True
