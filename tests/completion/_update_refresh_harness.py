"""Reusable unmanaged-directory harness for update-time completion refresh soaks."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import sase
from sase.completion.install import (
    CompletionRefreshReport,
    install_completion,
    zwc_path,
)
from sase.completion.install_stamp import read_stamp
from sase.completion.install_targets import SUPPORTED_SHELLS, script_path
from sase.feature_flags import override_flags
from sase.main.update_handler import handle_update_command
from sase.uv_tool.runner import parse_uv_output
from tests.main.update_command_helpers import (
    _UPGRADE_OUTPUT,
    _args,
    _install as _uv_tool_install,
    _versions,
)

STALE_MARKER = "STALE-UNMANAGED-COMPLETION\n"
OLD_STAMP_VERSION = "0.15.0"
SOAK_CYCLES = 3


def generated_version_marker(version: str | None = None) -> str:
    """Return the emitter header fragment that names the running sase version."""
    return f"(sase {sase.__version__ if version is None else version})"


def unmanaged_target(root: Path, shell: str) -> Path:
    """Return a disposable install directory for *shell* under *root*."""
    return root / "completions" / shell


def unmanaged_script(root: Path, shell: str) -> Path:
    """Return the completion script path for *shell* under *root*."""
    return script_path(unmanaged_target(root, shell), shell)


def install_unmanaged_shells(
    root: Path,
    shells: Sequence[str] = SUPPORTED_SHELLS,
    *,
    version: str = OLD_STAMP_VERSION,
    emit_fn: Callable[[str], tuple[str, str]] | None = None,
    zcompile_fn: Callable[[Path], None] | None = None,
) -> dict[str, Path]:
    """Install stamped unmanaged completion scripts into disposable directories."""
    scripts: dict[str, Path] = {}
    home = root / "home"
    for shell in shells:
        result = install_completion(
            requested=shell,
            target=unmanaged_target(root, shell),
            home=home,
            parent=None,
            verify_fn=lambda: None,
            version=version,
            emit_fn=emit_fn,
            zcompile_fn=zcompile_fn,
        )
        assert result.ok, result.steps
        scripts[shell] = result.script
    return scripts


def mark_scripts_stale(scripts: Mapping[str, Path]) -> None:
    """Replace installed scripts with a stale marker and drop zsh ``.zwc`` files."""
    for script in scripts.values():
        script.write_text(STALE_MARKER, encoding="utf-8")
        zwc_path(script).unlink(missing_ok=True)


def successful_update(
    tmp_path: Path,
    capsys: Any,
    *,
    refresh_fn: Callable[[], CompletionRefreshReport] | None = None,
) -> dict[str, Any]:
    """Run a successful managed ``sase update`` with completion refresh enabled."""
    with override_flags(completion_refresh_on_update=True):
        code = handle_update_command(
            _args(json=True),
            probe_fn=lambda: _uv_tool_install(tmp_path / "uv-tool"),
            run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
            axe_running_fn=lambda: False,
            version_fn=_versions,
            clock=lambda: 0.0,
            refresh_completions_fn=refresh_fn,
        )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is True
    return payload


def refresh_by_shell(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index ``completion_refresh.shells`` by shell name."""
    refresh = payload["completion_refresh"]
    assert refresh["attempted"] is True
    return {row["shell"]: row for row in refresh["shells"]}


def assert_unmanaged_refresh(
    scripts: Mapping[str, Path],
    payload: Mapping[str, Any],
    *,
    exact: bool = True,
) -> None:
    """Assert a successful refresh rewrote stamps, scripts, and zsh bytecode."""
    wanted = tuple(scripts)
    by_shell = refresh_by_shell(payload)
    if exact:
        assert set(by_shell) == set(wanted)
    else:
        assert set(wanted) <= set(by_shell)
    marker = generated_version_marker()
    for shell in wanted:
        outcome = by_shell[shell]
        script = scripts[shell]
        text = script.read_text(encoding="utf-8")
        assert outcome["ok"] is True, outcome
        assert outcome["target"] == str(script)
        assert STALE_MARKER not in text
        assert marker in text
        stamp = read_stamp(shell)
        assert stamp is not None
        assert stamp.version == sase.__version__
        assert stamp.owner == "local"
        assert stamp.target == str(script)
        if shell == "zsh":
            compiled = zwc_path(script)
            assert compiled.is_file()
            assert compiled.stat().st_mtime >= script.stat().st_mtime
            assert "refreshed" in outcome["detail"]
