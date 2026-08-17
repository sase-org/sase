"""Tests for completion install, list status, and the update refresh hook."""

from __future__ import annotations

from pathlib import Path

from sase.completion.install import (
    CompletionRefreshReport,
    ForeignInstallError,
    RefreshShellOutcome,
    install_completion,
    list_shell_statuses,
    maybe_refresh_installed_completions,
    _refresh_stamped_completions,
    zwc_path,
)
from sase.completion.install_stamp import read_stamp
from sase.feature_flags import FeatureFlag, current_flags, override_flags


def _emit(shell: str) -> tuple[str, str]:
    return f"# generated {shell}\n", f"digest-{shell}"


def _zcompile(path: Path) -> None:
    zwc_path(path).write_text("zwc\n", encoding="utf-8")


def _install(tmp_path: Path, *, shell: str = "zsh", **kwargs: object):
    target = tmp_path / "zfunc"
    defaults: dict[str, object] = {
        "requested": shell,
        "target": target,
        "home": tmp_path,
        "parent": None,
        "emit_fn": _emit,
        "zcompile_fn": _zcompile,
        "verify_fn": lambda: "_sase",
        "version": "0.16.0",
        "timestamp": "2026-08-17T12:00:00Z",
    }
    defaults.update(kwargs)
    return install_completion(**defaults)  # type: ignore[arg-type]


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    target = tmp_path / "zfunc"
    result = _install(tmp_path, dry_run=True)

    assert result.ok
    assert result.exit_code == 0
    assert result.shell.source == "explicit"
    assert not target.exists()
    assert read_stamp("zsh") is None
    assert {step.status for step in result.steps} <= {"planned", "ok", "skip"}
    assert any(
        step.name == "write" and step.status == "planned" for step in result.steps
    )


def test_install_writes_zcompiles_stamps_and_verifies(tmp_path: Path) -> None:
    result = _install(tmp_path)

    script = tmp_path / "zfunc" / "_sase"
    assert result.ok
    assert result.exit_code == 0
    assert script.read_text(encoding="utf-8") == "# generated zsh\n"
    assert zwc_path(script).is_file()
    stamp = read_stamp("zsh")
    assert stamp is not None
    assert stamp.version == "0.16.0"
    assert stamp.digest == "digest-zsh"
    assert stamp.target == str(script)
    assert result.registered is True


def test_foreign_file_requires_force(tmp_path: Path) -> None:
    target = tmp_path / "zfunc"
    script = target / "_sase"
    script.parent.mkdir()
    script.write_text("hand written\n", encoding="utf-8")

    result = _install(tmp_path)
    assert result.exit_code == 1
    assert any(step.status == "fail" for step in result.steps)
    assert script.read_text(encoding="utf-8") == "hand written\n"
    assert read_stamp("zsh") is None

    forced = _install(tmp_path, force=True)
    assert forced.ok
    assert script.read_text(encoding="utf-8") == "# generated zsh\n"
    assert read_stamp("zsh") is not None


def test_owned_file_can_be_overwritten_without_force(tmp_path: Path) -> None:
    first = _install(tmp_path)
    assert first.ok
    script = tmp_path / "zfunc" / "_sase"
    second = _install(tmp_path, emit_fn=lambda shell: (f"# v2 {shell}\n", "digest-2"))
    assert second.ok
    assert script.read_text(encoding="utf-8") == "# v2 zsh\n"


def test_reinstall_removes_the_previously_stamped_script(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "oh-my-zsh" / "plugins" / "z"
    plugin_dir.mkdir(parents=True)
    assert _install(tmp_path, target=plugin_dir).ok
    stale = plugin_dir / "_sase"
    assert stale.is_file()
    assert zwc_path(stale).is_file()

    result = _install(tmp_path)

    assert result.ok
    assert not stale.exists()
    assert not zwc_path(stale).exists()
    assert (tmp_path / "zfunc" / "_sase").is_file()
    assert any(
        step.name == "migrate" and step.status == "ok" and str(stale) in step.detail
        for step in result.steps
    )
    stamp = read_stamp("zsh")
    assert stamp is not None
    assert stamp.target == str(tmp_path / "zfunc" / "_sase")


def test_reinstall_to_the_same_target_reports_no_migration(tmp_path: Path) -> None:
    assert _install(tmp_path).ok

    result = _install(tmp_path)

    assert result.ok
    assert (tmp_path / "zfunc" / "_sase").is_file()
    assert not any(step.name == "migrate" for step in result.steps)


def test_dry_run_announces_a_pending_migration_without_removing_anything(
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "oh-my-zsh" / "plugins" / "z"
    plugin_dir.mkdir(parents=True)
    assert _install(tmp_path, target=plugin_dir).ok
    stale = plugin_dir / "_sase"

    result = _install(tmp_path, dry_run=True)

    assert result.ok
    assert stale.is_file()
    assert any(
        step.name == "migrate"
        and step.status == "planned"
        and str(stale) in step.detail
        for step in result.steps
    )


def test_verify_unset_prints_fpath_hint_and_fails(tmp_path: Path) -> None:
    result = _install(tmp_path, verify_fn=lambda: "UNSET")

    assert result.exit_code == 1
    assert result.registered is False
    assert result.fpath_hint is not None
    assert "BEFORE compinit" in result.fpath_hint
    assert read_stamp("zsh") is not None


def test_list_status_resolves_installed_stale_missing_and_zwc(
    tmp_path: Path,
) -> None:
    installed = _install(tmp_path)
    assert installed.ok
    rows = {row.shell: row for row in list_shell_statuses(version="0.16.0")}
    assert rows["zsh"].status == "installed"
    assert rows["zsh"].zwc == "fresh"
    assert rows["zsh"].stamp_version == "0.16.0"
    assert rows["bash"].status == "not installed"

    stale = {row.shell: row for row in list_shell_statuses(version="0.17.0")}
    assert stale["zsh"].status == "stale"

    script = tmp_path / "zfunc" / "_sase"
    zwc_path(script).unlink()
    missing_zwc = {row.shell: row for row in list_shell_statuses(version="0.16.0")}
    assert missing_zwc["zsh"].status == "zwc stale"
    assert missing_zwc["zsh"].zwc == "missing"

    script.unlink()
    missing = {row.shell: row for row in list_shell_statuses(version="0.16.0")}
    assert missing["zsh"].status == "missing"


def test_refresh_rewrites_every_stamped_shell(tmp_path: Path) -> None:
    _install(tmp_path, shell="zsh")
    _install(
        tmp_path,
        shell="bash",
        target=tmp_path / "bash-comp",
        verify_fn=lambda: None,
    )

    seen: list[str] = []

    def _installer(**kwargs: object):
        seen.append(str(kwargs["requested"]))
        return _install(
            tmp_path,
            shell=str(kwargs["requested"]),
            target=kwargs["target"],
            force=True,
        )

    report = _refresh_stamped_completions(install_fn=_installer)
    assert report.attempted
    assert {outcome.shell for outcome in report.outcomes} == {"bash", "zsh"}
    assert all(outcome.ok for outcome in report.outcomes)
    assert set(seen) == {"bash", "zsh"}


def test_maybe_refresh_respects_both_flag_states() -> None:
    calls: list[int] = []

    def _refresh() -> CompletionRefreshReport:
        calls.append(1)
        return CompletionRefreshReport(
            attempted=True,
            outcomes=(RefreshShellOutcome("zsh", True, "refreshed", "/tmp/_sase"),),
        )

    with override_flags(completion_refresh_on_update=False):
        disabled = maybe_refresh_installed_completions(_refresh)
    assert disabled.attempted is False
    assert calls == []
    assert current_flags().enabled(FeatureFlag.completion_refresh_on_update) is False

    with override_flags(completion_refresh_on_update=True):
        enabled = maybe_refresh_installed_completions(_refresh)
    assert enabled.attempted is True
    assert calls == [1]
    assert enabled.outcomes[0].ok is True


def test_maybe_refresh_swallows_failures() -> None:
    def _boom() -> CompletionRefreshReport:
        raise RuntimeError("generator exploded")

    with override_flags(completion_refresh_on_update=True):
        report = maybe_refresh_installed_completions(_boom)
    assert report.attempted is True
    assert report.outcomes[0].ok is False
    assert "generator exploded" in report.outcomes[0].detail


def test_foreign_error_type_is_public() -> None:
    assert issubclass(ForeignInstallError, Exception)


def test_bash_install_skips_zcompile_and_verify(tmp_path: Path) -> None:
    result = _install(
        tmp_path,
        shell="bash",
        target=tmp_path / "bash-comp",
        verify_fn=lambda: "should-not-run",
    )
    assert result.ok
    assert (tmp_path / "bash-comp" / "sase").is_file()
    statuses = {step.name: step.status for step in result.steps}
    assert statuses["zcompile"] == "skip"
    assert statuses["verify"] == "skip"
