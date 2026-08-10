from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "sase_bead"

FAKE_SASE = """#!/usr/bin/env bash
set -euo pipefail

mode="${FAKE_SASE_MODE:-delegate}"
state_file="${FAKE_SASE_STATE:?}"
log_file="${FAKE_SASE_LOG:?}"

printf '%s\\n' "$*" >>"$log_file"

attempt=0
if [[ -f "$state_file" ]]; then
  attempt="$(<"$state_file")"
fi
attempt=$((attempt + 1))
printf '%s\\n' "$attempt" >"$state_file"

case "$mode" in
  transient)
    if [[ "$attempt" -eq 1 ]]; then
      printf 'refresh raced on attempt %s\\n' "$attempt" >&2
      exit 42
    fi
    printf 'in_progress\\nextra detail should be truncated\\n'
    ;;
  persistent)
    printf 'missing on attempt %s\\n' "$attempt" >&2
    exit 43
    ;;
  multiline)
    printf 'closed\\nsecondary line\\n'
    ;;
  delegate)
    printf 'delegated:%s\\n' "$*"
    printf 'delegate stderr\\n' >&2
    exit 7
    ;;
  *)
    printf 'unknown fake mode: %s\\n' "$mode" >&2
    exit 99
    ;;
esac
"""


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def _copy_wrapper(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    tools_dir = repo / "tools"
    bin_dir = repo / ".venv" / "bin"
    tools_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    wrapper = tools_dir / "sase_bead"
    shutil.copy2(WRAPPER, wrapper)
    wrapper.chmod(wrapper.stat().st_mode | 0o111)

    fake_sase = bin_dir / "sase"
    _write_executable(fake_sase, FAKE_SASE)
    return wrapper, repo


def _run_wrapper(
    wrapper: Path,
    repo: Path,
    tmp_path: Path,
    *args: str,
    mode: str,
    status_only: bool = True,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    log_file = tmp_path / "fake-sase.log"
    env = os.environ.copy()
    env["FAKE_SASE_MODE"] = mode
    env["FAKE_SASE_STATE"] = str(tmp_path / "fake-sase-state")
    env["FAKE_SASE_LOG"] = str(log_file)
    if status_only:
        env["SASE_SYMVISION_BEAD_STATUS_ONLY"] = "1"
    else:
        env.pop("SASE_SYMVISION_BEAD_STATUS_ONLY", None)

    result = subprocess.run(
        [str(wrapper), *args],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, log_file


def _logged_calls(log_file: Path) -> list[str]:
    return log_file.read_text(encoding="utf-8").splitlines()


def test_symvision_status_show_retries_transient_failure(tmp_path: Path) -> None:
    wrapper, repo = _copy_wrapper(tmp_path)

    result, log_file = _run_wrapper(
        wrapper, repo, tmp_path, "show", "sase-i8", mode="transient"
    )

    assert result.returncode == 0
    assert result.stdout == "in_progress\n"
    assert result.stderr == ""
    assert _logged_calls(log_file) == ["bead show sase-i8", "bead show sase-i8"]


def test_symvision_status_show_preserves_persistent_failure(tmp_path: Path) -> None:
    wrapper, repo = _copy_wrapper(tmp_path)

    result, log_file = _run_wrapper(
        wrapper, repo, tmp_path, "show", "sase-missing", mode="persistent"
    )

    assert result.returncode == 43
    assert result.stdout == ""
    assert result.stderr == "missing on attempt 3\n"
    assert _logged_calls(log_file) == [
        "bead show sase-missing",
        "bead show sase-missing",
        "bead show sase-missing",
    ]


def test_symvision_status_show_truncates_to_primary_status_line(
    tmp_path: Path,
) -> None:
    wrapper, repo = _copy_wrapper(tmp_path)

    result, log_file = _run_wrapper(
        wrapper, repo, tmp_path, "show", "sase-i8", mode="multiline"
    )

    assert result.returncode == 0
    assert result.stdout == "closed\n"
    assert result.stderr == ""
    assert _logged_calls(log_file) == ["bead show sase-i8"]


def test_non_status_show_invocations_delegate_without_retry(tmp_path: Path) -> None:
    wrapper, repo = _copy_wrapper(tmp_path)

    result, log_file = _run_wrapper(
        wrapper,
        repo,
        tmp_path,
        "list",
        "--json",
        mode="delegate",
        status_only=True,
    )

    assert result.returncode == 7
    assert result.stdout == "delegated:bead list --json\n"
    assert result.stderr == "delegate stderr\n"
    assert _logged_calls(log_file) == ["bead list --json"]
