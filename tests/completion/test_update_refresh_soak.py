"""Production-path soak for ``completion_refresh_on_update``.

Uses disposable, explicitly passed directories rather than the operator's
home. Cycles go through ``handle_update_command`` with a successful managed
upgrade; refresh uses the production stamped-install path unless a test
injects a per-shell failure.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import sase
from sase.completion.install import (
    InstallResult,
    _refresh_stamped_completions,
    install_completion,
    list_shell_statuses,
    zwc_path,
)
from sase.completion.install_stamp import (
    OWNER_CHEZMOI,
    InstallStamp,
    read_stamp,
    write_stamp,
)
from tests.completion._update_refresh_harness import (
    OLD_STAMP_VERSION,
    SOAK_CYCLES,
    STALE_MARKER,
    assert_unmanaged_refresh,
    generated_version_marker,
    install_unmanaged_shells,
    mark_scripts_stale,
    refresh_by_shell,
    successful_update,
    unmanaged_script,
    unmanaged_target,
)

zsh = shutil.which("zsh")
pytestmark = pytest.mark.skipif(zsh is None, reason="zsh is not on PATH")


def test_three_update_cycles_refresh_bash_fish_and_zsh(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scripts = install_unmanaged_shells(tmp_path)
    mark_scripts_stale(scripts)
    for stamp in (read_stamp(shell) for shell in scripts):
        assert stamp is not None
        assert stamp.version == OLD_STAMP_VERSION

    snapshots: list[dict[str, str]] = []
    for _ in range(SOAK_CYCLES):
        payload = successful_update(tmp_path, capsys)
        assert_unmanaged_refresh(scripts, payload)
        snapshots.append(
            {shell: path.read_text(encoding="utf-8") for shell, path in scripts.items()}
        )
        statuses = {row.shell: row for row in list_shell_statuses()}
        for shell in scripts:
            assert statuses[shell].status == "installed"
            assert statuses[shell].stamp_version == sase.__version__
        assert statuses["zsh"].zwc == "fresh"

    assert snapshots[0] == snapshots[1] == snapshots[2]
    for shell, script in scripts.items():
        assert generated_version_marker() in script.read_text(encoding="utf-8")
        assert script.stat().st_size > len(STALE_MARKER)


def test_mixed_installed_and_absent_shells(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scripts = install_unmanaged_shells(tmp_path, shells=("bash", "zsh"))
    mark_scripts_stale(scripts)
    fish_script = unmanaged_script(tmp_path, "fish")

    payload = successful_update(tmp_path, capsys)
    assert_unmanaged_refresh(scripts, payload)
    assert not fish_script.exists()
    assert read_stamp("fish") is None
    statuses = {row.shell: row for row in list_shell_statuses()}
    assert statuses["fish"].status == "not installed"

    second = successful_update(tmp_path, capsys)
    assert_unmanaged_refresh(scripts, second)
    assert not fish_script.exists()


@pytest.mark.parametrize("fail_shell", ["bash", "fish", "zsh"])
def test_per_shell_failure_is_nonfatal_and_isolated(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fail_shell: str,
) -> None:
    scripts = install_unmanaged_shells(tmp_path)
    mark_scripts_stale(scripts)
    home = tmp_path / "home"

    def _installer(**kwargs: object) -> InstallResult:
        requested = str(kwargs["requested"])
        if requested == fail_shell:
            raise RuntimeError(f"{fail_shell} generator exploded")
        target = kwargs["target"]
        assert isinstance(target, Path)
        verify_fn = kwargs.get("verify_fn")
        return install_completion(
            requested=requested,
            force=True,
            target=target,
            home=home,
            parent=None,
            verify_fn=verify_fn if callable(verify_fn) else None,
        )

    payload = successful_update(
        tmp_path,
        capsys,
        refresh_fn=lambda: _refresh_stamped_completions(install_fn=_installer),
    )
    by_shell = refresh_by_shell(payload)
    assert set(by_shell) == set(scripts)
    assert by_shell[fail_shell]["ok"] is False
    assert f"{fail_shell} generator exploded" in by_shell[fail_shell]["detail"]
    assert scripts[fail_shell].read_text(encoding="utf-8") == STALE_MARKER
    if fail_shell == "zsh":
        assert not zwc_path(scripts["zsh"]).exists()

    recovered = {
        shell: script for shell, script in scripts.items() if shell != fail_shell
    }
    assert_unmanaged_refresh(recovered, payload, exact=False)


def test_chezmoi_managed_scripts_are_skipped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scripts = install_unmanaged_shells(tmp_path, shells=("bash", "zsh"))
    mark_scripts_stale(scripts)
    fish_dir = unmanaged_target(tmp_path, "fish")
    fish_script = unmanaged_script(tmp_path, "fish")
    fish_dir.mkdir(parents=True)
    fish_script.write_text("# chezmoi-managed fish\n", encoding="utf-8")
    write_stamp(
        InstallStamp(
            shell="fish",
            version=OLD_STAMP_VERSION,
            digest="digest-fish",
            target=str(fish_script),
            timestamp="2026-08-21T12:00:00Z",
            owner=OWNER_CHEZMOI,
        )
    )

    payload = successful_update(tmp_path, capsys)
    by_shell = refresh_by_shell(payload)
    assert by_shell["fish"]["ok"] is True
    assert "skipped chezmoi-managed" in by_shell["fish"]["detail"]
    assert fish_script.read_text(encoding="utf-8") == "# chezmoi-managed fish\n"
    fish_stamp = read_stamp("fish")
    assert fish_stamp is not None
    assert fish_stamp.owner == OWNER_CHEZMOI
    assert fish_stamp.version == OLD_STAMP_VERSION
    assert_unmanaged_refresh(scripts, payload, exact=False)
