"""Bead doctor read-model and seal-watch status.

Split from ``tests.test_bead.test_cli_doctor``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead import cli_admin, cli_admin_doctor
from tests.test_bead._cli_doctor_helpers import doctor_args


def test_doctor_reports_read_model_status_without_git_backed_cache(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_admin.handle_bead_doctor(doctor_args())

    output = capsys.readouterr().out
    assert "Read model: unavailable (" in output
    assert "Read model verify:" not in output


def test_doctor_verify_cache_reports_match(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core import bead_read_facade

    monkeypatch.setattr(
        bead_read_facade,
        "read_model_verify_cache",
        lambda _beads_dir: {
            "compared": True,
            "matched": True,
            "replay_issues": 3,
            "cache_issues": 3,
            "differing_ids": [],
            "reason": "cache matches replay: 3 issues",
        },
    )

    cli_admin.handle_bead_doctor(doctor_args(verify_cache=True))

    output = capsys.readouterr().out
    assert "Read model: unavailable (" in output
    assert "Read model verify: cache matches replay (3 issues)" in output


def test_doctor_verify_cache_reports_drift(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core import bead_read_facade

    monkeypatch.setattr(
        bead_read_facade,
        "read_model_verify_cache",
        lambda _beads_dir: {
            "compared": True,
            "matched": False,
            "replay_issues": 3,
            "cache_issues": 2,
            "differing_ids": ["beads-9"],
            "reason": "1 differing issue",
        },
    )

    cli_admin.handle_bead_doctor(doctor_args(verify_cache=True))

    output = capsys.readouterr().out
    assert "Read model verify: DRIFT (1 differing issue; replay=3 cache=2)" in output
    assert "Read model verify: differing ids: beads-9" in output


def test_doctor_renders_fresh_read_model_status_line() -> None:
    line = cli_admin_doctor._render_read_model_status(
        {
            "location": "/repo/.git/sase/bead-read-model/model.sqlite",
            "fresh": True,
            "reason": "served from cache",
            "generation": 4,
            "size_bytes": 1024,
            "last_sweep_age_secs": 3,
            "streams": 2,
            "issues": 7,
            "serve_count": 11,
            "tail_count": 2,
            "rebuild_count": 1,
            "last_refresh": "tail",
            "last_refresh_reason": "3 tail events over 2 streams",
        }
    )

    assert line == (
        "Read model: /repo/.git/sase/bead-read-model/model.sqlite "
        "(generation 4, 1024 bytes, 7 issues, last sweep 3s ago, fresh, "
        "outcomes serve=11 tail=2 rebuild=1, "
        "last refresh: tail (3 tail events over 2 streams))"
    )
    legacy_line = cli_admin_doctor._render_read_model_status(
        {
            "location": "/repo/.git/sase/bead-read-model/model.sqlite",
            "fresh": True,
            "reason": "served from cache",
            "generation": 4,
            "size_bytes": 1024,
            "last_sweep_age_secs": 3,
            "streams": 2,
            "issues": 7,
        }
    )
    assert legacy_line == (
        "Read model: /repo/.git/sase/bead-read-model/model.sqlite "
        "(generation 4, 1024 bytes, 7 issues, last sweep 3s ago, fresh)"
    )
    assert (
        cli_admin_doctor._render_read_model_status(None)
        == "Read model: unavailable with the installed core"
    )
    assert cli_admin_doctor._render_read_model_verify(None) == [
        "Read model verify: unavailable with the installed core"
    ]


def _seal_watch_report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": 1,
        "available": True,
        "reason": "no sealed-archive trigger fires",
        "warn": False,
        "triggers": [
            {
                "name": "hot_stream_files",
                "value": 2108,
                "threshold": 10000,
                "unit": "files",
                "warn": False,
                "detail": "2,108 hot stream files",
            },
            {
                "name": "stat_sweep_ms",
                "value": 4,
                "threshold": 50,
                "unit": "ms",
                "warn": False,
                "detail": "full stat sweep 4 ms",
            },
            {
                "name": "store_tree_bytes",
                "value": 36700160,
                "threshold": 262144000,
                "unit": "bytes",
                "warn": False,
                "detail": "store working tree 35 MiB",
            },
        ],
    }
    report.update(overrides)
    return report


def test_doctor_renders_seal_watch_ok_lines() -> None:
    assert cli_admin_doctor._render_seal_watch_triggers(_seal_watch_report()) == [
        "Seal watch hot stream files: OK "
        "(2,108 hot stream files; warn above 10,000 files)",
        "Seal watch stat sweep: OK (full stat sweep 4 ms; warn above 50 ms)",
        "Seal watch store tree: OK "
        "(store working tree 35 MiB; warn above 262,144,000 bytes)",
    ]


def test_doctor_renders_seal_watch_warn_with_design_pointer() -> None:
    report = _seal_watch_report(warn=True)
    triggers = report["triggers"]
    assert isinstance(triggers, list)
    hot = triggers[0]
    assert isinstance(hot, dict)
    hot.update(
        {
            "value": 12401,
            "warn": True,
            "detail": "12,401 hot stream files",
        }
    )

    lines = cli_admin_doctor._render_seal_watch_triggers(report)

    assert lines[0] == (
        "Seal watch hot stream files: WARN "
        "(12,401 hot stream files exceeds 10,000 files; "
        "see docs/beads.md#sealed-segments-gated-design)"
    )
    assert lines[1].startswith("Seal watch stat sweep: OK (")


def test_doctor_renders_seal_watch_unavailable() -> None:
    assert cli_admin_doctor._render_seal_watch_triggers(None) == [
        "Seal watch: unavailable with the installed core"
    ]
    assert cli_admin_doctor._render_seal_watch_triggers(
        {
            "schema_version": 1,
            "available": False,
            "reason": "no event store",
            "warn": False,
            "triggers": [],
        }
    ) == ["Seal watch: unavailable (no event store)"]


def test_doctor_reports_seal_watch_triggers(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core import bead_read_facade

    monkeypatch.setattr(
        bead_read_facade,
        "seal_watch_triggers",
        lambda _beads_dir: _seal_watch_report(),
    )

    cli_admin.handle_bead_doctor(doctor_args())

    output = capsys.readouterr().out
    assert "Seal watch hot stream files: OK (" in output
    assert "Seal watch stat sweep: OK (" in output
    assert "Seal watch store tree: OK (" in output
