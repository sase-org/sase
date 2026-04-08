"""Tests for ``sase telemetry export-config`` CLI subcommand."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from sase.telemetry.cli_export_config import handle_telemetry_export_config

# All expected files in the monitoring bundle.
EXPECTED_FILES = {
    "docker-compose.yml",
    "prometheus/prometheus.yml",
    "prometheus/alerts.yml",
    "grafana/dashboards/sase.json",
    "grafana/provisioning/dashboards/dashboard.yml",
    "grafana/provisioning/datasources/prometheus.yml",
}


def test_exports_to_default_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config files are written to ./sase-monitoring/ by default."""
    monkeypatch.chdir(tmp_path)
    args = Namespace(output_dir="./sase-monitoring", force=False)
    handle_telemetry_export_config(args)

    out = tmp_path / "sase-monitoring"
    assert out.is_dir()
    for rel in EXPECTED_FILES:
        assert (out / rel).is_file(), f"Missing {rel}"


def test_exports_to_custom_dir(tmp_path: Path) -> None:
    """Config files are written to a user-specified directory."""
    target = tmp_path / "custom-output"
    args = Namespace(output_dir=str(target), force=False)
    handle_telemetry_export_config(args)

    assert target.is_dir()
    for rel in EXPECTED_FILES:
        assert (target / rel).is_file(), f"Missing {rel}"


def test_refuses_existing_dir_without_force(tmp_path: Path) -> None:
    """Exits with error when target exists and --force is not set."""
    target = tmp_path / "existing"
    target.mkdir()
    args = Namespace(output_dir=str(target), force=False)

    with pytest.raises(SystemExit, match="1"):
        handle_telemetry_export_config(args)


def test_force_overwrites_existing_dir(tmp_path: Path) -> None:
    """--force removes and re-creates the target directory."""
    target = tmp_path / "existing"
    target.mkdir()
    (target / "stale-file.txt").write_text("old")

    args = Namespace(output_dir=str(target), force=True)
    handle_telemetry_export_config(args)

    assert not (target / "stale-file.txt").exists()
    for rel in EXPECTED_FILES:
        assert (target / rel).is_file(), f"Missing {rel}"


def test_directory_structure_is_correct(tmp_path: Path) -> None:
    """Verify subdirectory layout matches the monitoring bundle."""
    target = tmp_path / "mon"
    args = Namespace(output_dir=str(target), force=False)
    handle_telemetry_export_config(args)

    assert (target / "prometheus").is_dir()
    assert (target / "grafana" / "dashboards").is_dir()
    assert (target / "grafana" / "provisioning" / "datasources").is_dir()
    assert (target / "grafana" / "provisioning" / "dashboards").is_dir()
