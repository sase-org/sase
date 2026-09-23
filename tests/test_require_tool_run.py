"""Contract tests for the guarded-recipe gate (`tools/require_tool_run`).

The gate refuses a raw agent invocation of `check` / `check-full` unless the
agent runs inside `sase tool run` for that project root or names an explicit
bypass. These tests pin the full behavior matrix from the recipe-guard phase
plus the Justfile wiring that makes the gate the first dependency, so a later
edit cannot silently drop it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "tools" / "require_tool_run"
GUARDED = ("check", "check-full")


@pytest.fixture(autouse=True)
def _sase_on_path(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Put a stub `sase` on PATH so the refusal path never depends on the host.

    The gate fails open when `sase` is not on PATH, and CI runs pytest from
    the venv without putting its `bin` on PATH. The stub is never executed.
    """
    stub_dir = tmp_path_factory.mktemp("sase-stub-bin")
    stub = stub_dir / "sase"
    stub.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    stub.chmod(0o755)
    path = os.environ.get("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{path}")


def _run(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if env:
        base.update(env)
    return subprocess.run(
        [str(GUARD), *args],
        env=base,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _agent_env(**extra: str) -> dict[str, str]:
    return {"SASE_AGENT": "1", **extra}


def test_guard_script_is_executable_sh() -> None:
    assert GUARD.is_file()
    assert os.access(GUARD, os.X_OK)
    first = GUARD.read_text(encoding="utf-8").splitlines()[0]
    assert first == "#!/bin/sh"


def test_guard_never_starts_sase(tmp_path: Path) -> None:
    """The override exists for when `sase` is broken, so the guard must not
    execute it on any path: refusal, wrapped allow, or bypass."""
    spy_dir = tmp_path / "bin"
    spy_dir.mkdir()
    marker = tmp_path / "sase-called"
    spy = spy_dir / "sase"
    spy.write_text(f"#!/bin/sh\necho called >> {marker}\nexit 0\n", encoding="utf-8")
    spy.chmod(0o755)
    path = f"{spy_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}"
    root = os.path.realpath(tmp_path)

    _run("check", env={**_agent_env(), "PATH": path})
    _run(
        "check",
        env={
            **_agent_env(SASE_TOOL_NAME="check", SASE_TOOL_PROJECT_ROOT=root),
            "PATH": path,
        },
        cwd=tmp_path,
    )
    _run("check", env={**_agent_env(SASE_TOOL_BYPASS="x"), "PATH": path})

    assert not marker.exists()


def test_human_ci_and_finalizer_envs_run_raw() -> None:
    assert _run("check").returncode == 0
    assert _run("check", env={"CI": "true"}).returncode == 0
    assert _run("check-full", env={"CI": "true"}).returncode == 0


def test_monitor_and_proc_supervisor_envs_run_raw() -> None:
    assert _run("check", env={"SASE_MONITOR_ID": "m1"}).returncode == 0
    proc = _run("check", env={"SASE_PROC_ID": "p1"})
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_agent_raw_invocation_is_refused_with_three_lines() -> None:
    for recipe in GUARDED:
        proc = _run(recipe, env=_agent_env())
        assert proc.returncode == 2
        assert proc.stdout == ""
        lines = proc.stderr.splitlines()
        assert len(lines) == 3
        assert f"`just {recipe}`" in lines[0]
        assert f"sase tool run {recipe}" in lines[1]
        assert f"SASE_TOOL_BYPASS='<reason>' just {recipe}" in lines[2]


def test_agent_wrapped_as_this_tool_for_this_root_is_allowed(
    tmp_path: Path,
) -> None:
    root = os.path.realpath(tmp_path)
    proc = _run(
        "check",
        env=_agent_env(SASE_TOOL_NAME="check", SASE_TOOL_PROJECT_ROOT=root),
        cwd=tmp_path,
    )
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_agent_wrapped_as_a_different_tool_is_refused(tmp_path: Path) -> None:
    root = os.path.realpath(tmp_path)
    proc = _run(
        "check",
        env=_agent_env(SASE_TOOL_NAME="check-full", SASE_TOOL_PROJECT_ROOT=root),
        cwd=tmp_path,
    )
    assert proc.returncode == 2


def test_agent_wrapped_for_a_different_project_root_is_refused(
    tmp_path: Path,
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    proc = _run(
        "check",
        env=_agent_env(
            SASE_TOOL_NAME="check",
            SASE_TOOL_PROJECT_ROOT=os.path.realpath(other),
        ),
        cwd=tmp_path,
    )
    assert proc.returncode == 2


def test_recording_failure_stays_wrapped(tmp_path: Path) -> None:
    """`SASE_TOOL_NAME` is exported even when recording failed, so the child
    of a fail-open `sase tool run check` is allowed without a run id."""
    root = os.path.realpath(tmp_path)
    proc = _run(
        "check",
        env=_agent_env(SASE_TOOL_NAME="check", SASE_TOOL_PROJECT_ROOT=root),
        cwd=tmp_path,
    )
    assert proc.returncode == 0


def test_ad_hoc_run_never_matches_a_guarded_recipe(tmp_path: Path) -> None:
    proc = _run(
        "check",
        env=_agent_env(SASE_TOOL_NAME="ad-hoc", SASE_TOOL_PROJECT_ROOT=""),
        cwd=tmp_path,
    )
    assert proc.returncode == 2


def test_bypass_with_a_reason_is_allowed_with_one_line() -> None:
    proc = _run("check", env=_agent_env(SASE_TOOL_BYPASS="stale install"))
    assert proc.returncode == 0
    lines = proc.stderr.splitlines()
    assert len(lines) == 1
    assert "stale install" in lines[0]


def test_empty_bypass_does_not_bypass() -> None:
    proc = _run("check", env=_agent_env(SASE_TOOL_BYPASS=""))
    assert proc.returncode == 2


def test_missing_sase_on_path_fails_open_with_one_line(tmp_path: Path) -> None:
    proc = _run("check", env={**_agent_env(), "PATH": str(tmp_path)})
    assert proc.returncode == 0
    lines = proc.stderr.splitlines()
    assert len(lines) == 1
    assert "not on PATH" in lines[0]


def test_missing_tool_name_is_a_usage_error() -> None:
    proc = _run()
    assert proc.returncode == 2
    assert "usage" in proc.stderr.lower()


def _recipe_dependencies(header: str) -> list[str]:
    """Split a Justfile recipe header's dependency list into tokens.

    Parenthesized groups (e.g. `(_require-tool-run "check")`) and quoted
    strings count as single tokens.
    """
    deps: list[str] = []
    token = ""
    depth = 0
    quote: str | None = None
    for char in header:
        if quote is not None:
            token += char
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
            token += char
        elif char == "(":
            depth += 1
            token += char
        elif char == ")":
            depth -= 1
            token += char
        elif char.isspace() and depth == 0:
            if token:
                deps.append(token)
                token = ""
        else:
            token += char
    if token:
        deps.append(token)
    return deps


def _justfile_recipe_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in (ROOT / "Justfile").read_text(encoding="utf-8").splitlines():
        if ": " in line or line.endswith(":"):
            name, _, rest = line.partition(":")
            if name in GUARDED:
                headers[name] = rest.strip()
    return headers


@pytest.mark.parametrize("recipe", GUARDED)
def test_guarded_recipe_runs_the_guard_first(recipe: str) -> None:
    headers = _justfile_recipe_headers()
    assert recipe in headers
    deps = _recipe_dependencies(headers[recipe])
    assert deps
    assert deps[0] == f'(_require-tool-run "{recipe}")'


def test_require_tool_run_helper_recipe_exists() -> None:
    justfile = (ROOT / "Justfile").read_text(encoding="utf-8")
    assert "\n_require-tool-run name:\n" in justfile
    assert "    @tools/require_tool_run {{ name }}\n" in justfile
