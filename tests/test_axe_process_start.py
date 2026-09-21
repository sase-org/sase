"""Tests for the stable ``sase`` executable the service units launch."""

from pathlib import Path
from unittest.mock import patch

from sase.axe._process_start import canonical_axe_start_command


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    return path


def _ephemeral_python(home: Path) -> Path:
    workspace = home / ".local" / "state" / "sase" / "workspaces" / "sase-org"
    return _executable(workspace / "sase" / "sase_42" / ".venv" / "bin" / "python")


def _resolve(
    home: Path,
    *,
    executable: Path,
    path_sase: Path | None = None,
    primary_sase: Path | None = None,
) -> str | None:
    with (
        patch("sase.axe._process_start.Path.home", return_value=home),
        patch("sase.axe._process_start.sys.executable", str(executable)),
        patch(
            "sase.axe._process_start.shutil.which",
            return_value=str(path_sase) if path_sase is not None else None,
        ),
        patch(
            "sase.axe._process_start._resolve_primary_workspace_sase",
            return_value=str(primary_sase) if primary_sase is not None else None,
        ),
    ):
        return canonical_axe_start_command()


def test_prefers_local_bin_sase_over_an_ephemeral_workspace(tmp_path: Path) -> None:
    canonical = _executable(tmp_path / ".local" / "bin" / "sase")
    ephemeral_python = _ephemeral_python(tmp_path)
    _executable(ephemeral_python.parent / "sase")

    assert _resolve(tmp_path, executable=ephemeral_python) == str(canonical)


def test_skips_ephemeral_path_hit_for_the_primary_workspace(tmp_path: Path) -> None:
    ephemeral_python = _ephemeral_python(tmp_path)
    ephemeral_sase = _executable(ephemeral_python.parent / "sase")
    primary = _executable(tmp_path / "primary" / ".venv" / "bin" / "sase")

    resolved = _resolve(
        tmp_path,
        executable=ephemeral_python,
        path_sase=ephemeral_sase,
        primary_sase=primary,
    )

    assert resolved == str(primary)


def test_returns_none_when_only_ephemeral_candidates_exist(tmp_path: Path) -> None:
    ephemeral_python = _ephemeral_python(tmp_path)
    ephemeral_sase = _executable(ephemeral_python.parent / "sase")

    resolved = _resolve(
        tmp_path,
        executable=ephemeral_python,
        path_sase=ephemeral_sase,
    )

    assert resolved is None


def test_falls_back_to_a_durable_interpreter_sibling(tmp_path: Path) -> None:
    python = _executable(tmp_path / "venv" / "bin" / "python")
    sibling = _executable(python.parent / "sase")

    assert _resolve(tmp_path, executable=python) == str(sibling)
