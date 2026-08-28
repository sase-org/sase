from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from tests._github_actions_ci_helpers import _load_setup_sase_action
from tests._github_actions_ci_helpers import _setup_sase_install_script
from tests._github_actions_ci_helpers import _write_executable


pytestmark = pytest.mark.contract


def test_setup_sase_action_installs_downloaded_core_artifacts() -> None:
    steps = _load_setup_sase_action()["runs"]["steps"]

    assert any(
        step.get("uses") == "actions/download-artifact@v4"
        and step.get("with", {}).get("name") == "sase-core-wheel"
        for step in steps
    )
    install_script = _setup_sase_install_script()
    assert 'SASE_CORE_WHEEL="${wheels[0]}" just "$INSTALL_RECIPE"' in install_script
    assert "sase-core-sha.txt" in install_script
    assert "sase-xprompt-lsp" in install_script
    assert 'lsp_tmp="$(mktemp "${lsp_dest}.tmp.XXXXXX")"' in install_script
    assert '"$lsp_dest" --version' in install_script


def test_setup_sase_action_exports_wheel_for_the_whole_job() -> None:
    """Later `just` recipes must still see the wheel build-core produced.

    Every recipe re-enters `_setup`, and `_core-overrides-arg` only lifts the
    published sase-core-rs window when SASE_CORE_WHEEL is set. Scoping the
    variable to the install step alone lets the editable install silently
    re-resolve sase-core-rs back inside the pyproject window.
    """
    install_script = _setup_sase_install_script()

    assert 'echo "SASE_CORE_WHEEL=${wheels[0]}" >> "$GITHUB_ENV"' in install_script


def test_setup_sase_install_script_records_the_wheel_in_github_env(
    tmp_path: Path,
) -> None:
    """Run the action's install script the way a runner would."""
    artifact_dir = tmp_path / "sase-core-wheel"
    artifact_dir.mkdir()
    wheel = artifact_dir / "sase_core_rs-0.18.1-cp312-abi3-manylinux_2_39_x86_64.whl"
    wheel.touch()
    (artifact_dir / "sase-core-sha.txt").write_text("deadbeef\n", encoding="utf-8")
    _write_executable(
        artifact_dir / "sase-xprompt-lsp",
        '#!/bin/sh\nprintf "lsp %s\\n" "$1"\n',
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "just",
        (
            "#!/bin/sh\n"
            "mkdir -p .venv/bin\n"
            'printf "just %s SASE_CORE_WHEEL=%s\\n" "$1" "$SASE_CORE_WHEEL"\n'
        ),
    )

    github_env = tmp_path / "github_env"
    github_env.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CORE_ARTIFACT_DIR": str(artifact_dir),
        "INSTALL_RECIPE": "install",
        "GITHUB_ENV": str(github_env),
    }

    result = subprocess.run(
        ["bash", "-e", "-c", _setup_sase_install_script()],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert f"just install SASE_CORE_WHEEL={wheel}" in result.stdout
    assert "lsp --version" in result.stdout
    installed_lsp = tmp_path / ".venv" / "bin" / "sase-xprompt-lsp"
    assert installed_lsp.is_file()
    assert installed_lsp.stat().st_mode & stat.S_IXUSR
    assert (
        f"SASE_CORE_WHEEL={wheel}"
        in github_env.read_text(encoding="utf-8").splitlines()
    )


@pytest.mark.parametrize(
    ("lsp_count", "diagnostic"),
    [
        (0, "error: expected exactly one sase-xprompt-lsp binary, found 0"),
        (2, "error: expected exactly one sase-xprompt-lsp binary, found 2"),
    ],
)
def test_setup_sase_install_script_rejects_missing_or_duplicate_lsp_artifacts(
    tmp_path: Path,
    lsp_count: int,
    diagnostic: str,
) -> None:
    artifact_dir = tmp_path / "sase-core-wheel"
    artifact_dir.mkdir()
    (artifact_dir / "sase_core_rs-0.18.1-cp312-abi3-manylinux_2_39_x86_64.whl").touch()
    (artifact_dir / "sase-core-sha.txt").write_text("deadbeef\n", encoding="utf-8")
    for index in range(lsp_count):
        _write_executable(
            artifact_dir / f"lsp-{index}" / "sase-xprompt-lsp",
            '#!/bin/sh\nprintf "lsp\\n"\n',
        )

    github_env = tmp_path / "github_env"
    github_env.touch()
    env = {
        **os.environ,
        "CORE_ARTIFACT_DIR": str(artifact_dir),
        "INSTALL_RECIPE": "install",
        "GITHUB_ENV": str(github_env),
    }

    result = subprocess.run(
        ["bash", "-e", "-c", _setup_sase_install_script()],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert diagnostic in result.stderr


@pytest.mark.parametrize(
    ("provenance_count", "diagnostic"),
    [
        (0, "error: expected exactly one sase-core-sha.txt provenance file, found 0"),
        (2, "error: expected exactly one sase-core-sha.txt provenance file, found 2"),
    ],
)
def test_setup_sase_install_script_rejects_missing_or_duplicate_provenance(
    tmp_path: Path,
    provenance_count: int,
    diagnostic: str,
) -> None:
    artifact_dir = tmp_path / "sase-core-wheel"
    artifact_dir.mkdir()
    (artifact_dir / "sase_core_rs-0.18.1-cp312-abi3-manylinux_2_39_x86_64.whl").touch()
    _write_executable(
        artifact_dir / "sase-xprompt-lsp",
        '#!/bin/sh\nprintf "lsp\\n"\n',
    )
    for index in range(provenance_count):
        provenance_dir = artifact_dir / f"sha-{index}"
        provenance_dir.mkdir()
        (provenance_dir / "sase-core-sha.txt").write_text(
            "deadbeef\n",
            encoding="utf-8",
        )

    github_env = tmp_path / "github_env"
    github_env.touch()
    env = {
        **os.environ,
        "CORE_ARTIFACT_DIR": str(artifact_dir),
        "INSTALL_RECIPE": "install",
        "GITHUB_ENV": str(github_env),
    }

    result = subprocess.run(
        ["bash", "-e", "-c", _setup_sase_install_script()],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert diagnostic in result.stderr
