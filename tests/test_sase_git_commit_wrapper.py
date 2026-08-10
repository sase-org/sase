"""Tests for the ``sase_git_commit`` wrapper script."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from sase.scripts import _get_script_path


def test_wrapper_writes_invocation_marker_before_delegating(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "20260522112233"
    artifacts_dir.mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_sase = bin_dir / "sase"
    fake_sase.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[[ "$1" == "stitch" ]]\n'
        '[[ "$2" == "create" ]]\n'
        '[[ -f "${SASE_ARTIFACTS_DIR}/commit_skill_invoked.json" ]]\n'
        'printf \'%s\\n\' "$@" >"${SASE_ARTIFACTS_DIR}/fake_sase_args.txt"\n',
        encoding="utf-8",
    )
    fake_sase.chmod(fake_sase.stat().st_mode | stat.S_IXUSR)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "SASE_ARTIFACTS_DIR": str(artifacts_dir),
        "SASE_AGENT_TIMESTAMP": "20260522112233",
        "SASE_COMMIT_METHOD": "propose",
    }
    result = subprocess.run(
        [
            "bash",
            str(_get_script_path("sase_git_commit")),
            "-M",
            "commit_message.md",
            "-f",
            "src/foo.py",
            "--file=tests/test_foo.py",
            "-B",
            "--type",
            "propose",
        ],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    marker = json.loads((artifacts_dir / "commit_skill_invoked.json").read_text())
    assert marker["run_id"] == "20260522112233"
    assert marker["cwd"] == str(workdir)
    assert marker["files"] == ["src/foo.py", "tests/test_foo.py"]
    assert marker["method"] == "create_proposal"
    assert marker["method_source"] == "cli"
    assert marker["cli_method"] == "create_proposal"
    assert marker["env_method"] == "create_proposal"
    assert marker["raw_cli_method"] == "propose"
    assert marker["raw_env_method"] == "propose"
    assert marker["wrapper"] == "sase_git_commit"
    assert (artifacts_dir / "fake_sase_args.txt").read_text().splitlines() == [
        "stitch",
        "create",
        "-M",
        "commit_message.md",
        "-f",
        "src/foo.py",
        "--file=tests/test_foo.py",
        "-B",
        "--type",
        "propose",
    ]
