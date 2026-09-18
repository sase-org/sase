"""Tests for completion install, list status, and the update refresh hook."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sase.completion.loader import emit_loader
from sase.completion.install_scripts import completion_payload
from sase.completion.install import (
    CompletionInstallError,
    CompletionRefreshReport,
    ForeignInstallError,
    InstallResult,
    RefreshShellOutcome,
    _ExpectedCompletion,
    install_completion,
    list_shell_statuses,
    maybe_refresh_installed_completions,
    refresh_stamped_completions,
    _refresh_stamped_completions,
    zwc_path,
)
from sase.completion.install_stamp import (
    REPRESENTATION_LOADER,
    REPRESENTATION_RAW,
    InstallStamp,
    read_stamp,
    write_stamp,
)
from sase.completion.runtime_cache import RuntimeGrammarStatus, ensure_cached_grammar


def _emit(shell: str) -> tuple[str, str]:
    return f"# generated {shell}\n", f"digest-{shell}"


def _expected(shells: tuple[str, ...] | list[str]):
    return {
        shell: _ExpectedCompletion(script, digest)
        for shell in shells
        for script, digest in (_emit(shell),)
    }


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
    assert stamp.owner == "local"
    assert stamp.representation == REPRESENTATION_RAW
    assert result.registered is True


def test_default_install_writes_loader_and_records_runtime_grammar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    grammar = tmp_path / "cache" / "sase.bash"

    def _ensure(shell: str, **kwargs: object) -> Path:
        assert shell == "bash"
        assert kwargs["loader_path"] == tmp_path / "bash-comp" / "sase"
        assert kwargs["owner"] == "local"
        grammar.parent.mkdir(parents=True)
        grammar.write_text("# cached bash grammar\n", encoding="utf-8")
        return grammar

    def _assess(shell: str, **_kwargs: object) -> RuntimeGrammarStatus:
        assert shell == "bash"
        return RuntimeGrammarStatus(
            shell="bash",
            status="current",
            path=str(grammar),
            structural_digest="digest-bash",
        )

    monkeypatch.setattr("sase.completion.install_flow.ensure_cached_grammar", _ensure)
    monkeypatch.setattr("sase.completion.install_flow.assess_cached_grammar", _assess)

    result = install_completion(
        requested="bash",
        target=tmp_path / "bash-comp",
        home=tmp_path,
        parent=None,
        version="0.17.0",
        timestamp="2026-09-18T12:00:00Z",
    )

    script = tmp_path / "bash-comp" / "sase"
    text = script.read_text(encoding="utf-8")
    assert result.ok
    assert "completion ensure bash" in text
    assert "--owner 'local'" in text
    stamp = read_stamp("bash")
    assert stamp is not None
    assert stamp.representation == REPRESENTATION_LOADER
    assert stamp.digest == "digest-bash"
    assert (
        stamp.loader_digest
        == hashlib.sha256(
            emit_loader("bash", owner="local").encode("utf-8")
        ).hexdigest()
    )


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
    rows = {
        row.shell: row
        for row in list_shell_statuses(version="0.16.0", expected_fn=_expected)
    }
    assert rows["zsh"].status == "installed"
    assert rows["zsh"].zwc == "fresh"
    assert rows["zsh"].stamp_version == "0.16.0"
    assert rows["zsh"].owner == "local"
    assert rows["zsh"].drift_reasons == ()
    assert rows["bash"].status == "not installed"
    assert rows["bash"].owner is None

    stale = {
        row.shell: row
        for row in list_shell_statuses(version="0.17.0", expected_fn=_expected)
    }
    assert stale["zsh"].status == "stale"
    assert "stamp version" in stale["zsh"].drift_reasons[0]

    script = tmp_path / "zfunc" / "_sase"
    zwc_path(script).unlink()
    missing_zwc = {
        row.shell: row
        for row in list_shell_statuses(version="0.16.0", expected_fn=_expected)
    }
    assert missing_zwc["zsh"].status == "zwc stale"
    assert missing_zwc["zsh"].zwc == "missing"

    script.unlink()
    missing = {
        row.shell: row
        for row in list_shell_statuses(version="0.16.0", expected_fn=_expected)
    }
    assert missing["zsh"].status == "missing"


def test_list_status_detects_same_version_command_tree_drift(tmp_path: Path) -> None:
    assert _install(tmp_path).ok

    rows = {
        row.shell: row
        for row in list_shell_statuses(
            version="0.16.0",
            expected_fn=lambda shells: {
                shell: _ExpectedCompletion("# generated zsh\n", "digest-new")
                for shell in shells
            },
        )
    }

    assert rows["zsh"].status == "stale"
    assert any("stamp digest" in reason for reason in rows["zsh"].drift_reasons)


def test_list_status_detects_emitter_only_drift(tmp_path: Path) -> None:
    assert _install(tmp_path).ok

    rows = {
        row.shell: row
        for row in list_shell_statuses(
            version="0.16.0",
            expected_fn=lambda shells: {
                shell: _ExpectedCompletion("# regenerated differently\n", "digest-zsh")
                for shell in shells
            },
        )
    }

    assert rows["zsh"].status == "stale"
    assert any("script differs" in reason for reason in rows["zsh"].drift_reasons)


def test_list_status_detects_damaged_script(tmp_path: Path) -> None:
    assert _install(tmp_path).ok
    script = tmp_path / "zfunc" / "_sase"
    script.write_text("# damaged\n", encoding="utf-8")

    rows = {
        row.shell: row
        for row in list_shell_statuses(version="0.16.0", expected_fn=_expected)
    }

    assert rows["zsh"].status == "stale"
    assert any("script differs" in reason for reason in rows["zsh"].drift_reasons)


def test_list_status_distinguishes_loader_from_runtime_grammar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    calls: list[tuple[str, ...]] = []

    def _expected(shells: tuple[str, ...] | list[str]):
        calls.append(tuple(shells))
        return {
            shell: _ExpectedCompletion(f"# generated {shell}\n", f"digest-{shell}")
            for shell in shells
        }

    grammar = ensure_cached_grammar("bash", expected_fn=_expected)
    script = tmp_path / "bash-comp" / "sase"
    script.parent.mkdir()
    loader = emit_loader("bash", owner="local")
    script.write_text(completion_payload(loader), encoding="utf-8")
    write_stamp(
        InstallStamp(
            shell="bash",
            version="0.16.0",
            digest="digest-bash",
            target=str(script),
            timestamp="2026-08-17T12:00:00Z",
            representation=REPRESENTATION_LOADER,
            loader_digest=hashlib.sha256(loader.encode("utf-8")).hexdigest(),
        )
    )

    rows = {
        row.shell: row
        for row in list_shell_statuses(version="0.16.0", expected_fn=_expected)
    }
    assert rows["bash"].status == "installed"
    assert rows["bash"].representation == REPRESENTATION_LOADER
    assert rows["bash"].loader_status == "current"
    assert rows["bash"].grammar_status == "current"
    assert rows["bash"].grammar_path == str(grammar)

    grammar.write_text("# corrupt\n", encoding="utf-8")
    stale = {
        row.shell: row
        for row in list_shell_statuses(version="0.16.0", expected_fn=_expected)
    }
    assert stale["bash"].status == "stale"
    assert stale["bash"].loader_status == "current"
    assert stale["bash"].grammar_status == "corrupt"
    assert any("checksum" in reason for reason in stale["bash"].drift_reasons)


def test_zcompile_failure_preserves_previous_script_and_stamp(tmp_path: Path) -> None:
    assert _install(tmp_path).ok
    script = tmp_path / "zfunc" / "_sase"
    before = script.read_text(encoding="utf-8")
    stamp_before = read_stamp("zsh")
    assert stamp_before is not None

    def _fail_zcompile(_path: Path) -> None:
        raise CompletionInstallError("zcompile exploded")

    result = _install(
        tmp_path,
        emit_fn=lambda shell: (f"# broken {shell}\n", "digest-broken"),
        zcompile_fn=_fail_zcompile,
    )

    assert result.exit_code == 1
    assert any(
        step.name == "zcompile" and step.status == "fail" for step in result.steps
    )
    assert script.read_text(encoding="utf-8") == before
    assert read_stamp("zsh") == stamp_before


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


def test_refresh_skips_zsh_registration_probe(tmp_path: Path) -> None:
    assert _install(tmp_path).ok
    verify_fns: list[object] = []

    def _installer(**kwargs: object) -> InstallResult:
        verify_fn = kwargs.get("verify_fn")
        assert callable(verify_fn)
        verify_fns.append(verify_fn)
        return _install(tmp_path, target=kwargs["target"], force=True)

    report = _refresh_stamped_completions(install_fn=_installer)
    assert report.outcomes[0].ok is True
    assert verify_fns[0]() is None  # type: ignore[operator]


def test_refresh_dry_run_does_not_reinstall(tmp_path: Path) -> None:
    assert _install(tmp_path).ok
    calls: list[object] = []

    def _installer(**kwargs: object) -> InstallResult:
        calls.append(kwargs)
        raise AssertionError("dry-run must not reinstall")

    dry_run = refresh_stamped_completions(dry_run=True, install_fn=_installer)
    assert dry_run.outcomes[0].ok is True
    assert (
        "would refresh" in dry_run.outcomes[0].detail
        or "already current" in dry_run.outcomes[0].detail
    )
    assert calls == []


def test_chezmoi_owned_stamp_refuses_local_takeover_without_force(
    tmp_path: Path,
) -> None:
    target = tmp_path / "zfunc"
    script = target / "_sase"
    target.mkdir()
    script.write_text("# managed\n", encoding="utf-8")
    write_stamp(
        InstallStamp(
            shell="zsh",
            version="0.16.0",
            digest="digest-zsh",
            target=str(script),
            timestamp="2026-08-17T12:00:00Z",
            owner="chezmoi",
        )
    )

    result = _install(tmp_path, target=target)

    assert result.exit_code == 1
    assert any(
        step.name == "ownership" and step.status == "fail" for step in result.steps
    )
    assert script.read_text(encoding="utf-8") == "# managed\n"

    forced = _install(tmp_path, target=target, force=True)
    assert forced.ok
    stamp = read_stamp("zsh")
    assert stamp is not None
    assert stamp.owner == "local"


def test_refresh_rewrites_chezmoi_owned_stamps_and_preserves_owner(
    tmp_path: Path,
) -> None:
    target = tmp_path / "zfunc"
    script = target / "_sase"
    target.mkdir()
    script.write_text("# managed\n", encoding="utf-8")
    write_stamp(
        InstallStamp(
            shell="zsh",
            version="0.16.0",
            digest="digest-zsh",
            target=str(script),
            timestamp="2026-08-17T12:00:00Z",
            owner="chezmoi",
        )
    )

    seen: list[dict[str, object]] = []

    def _installer(**kwargs: object) -> InstallResult:
        seen.append(dict(kwargs))
        return _install(
            tmp_path,
            target=kwargs["target"],
            force=True,
            owner=kwargs["owner"],
        )

    report = _refresh_stamped_completions(install_fn=_installer)

    assert report.outcomes[0].shell == "zsh"
    assert report.outcomes[0].ok is True
    assert "refreshed" in report.outcomes[0].detail
    assert report.outcomes[0].target == str(script)
    assert seen[0]["owner"] == "chezmoi"
    assert seen[0]["force_cache"] is True
    stamp = read_stamp("zsh")
    assert stamp is not None
    assert stamp.owner == "chezmoi"


def test_maybe_refresh_runs_the_injected_refresher() -> None:
    calls: list[int] = []

    def _refresh() -> CompletionRefreshReport:
        calls.append(1)
        return CompletionRefreshReport(
            attempted=True,
            outcomes=(RefreshShellOutcome("zsh", True, "refreshed", "/tmp/_sase"),),
        )

    report = maybe_refresh_installed_completions(_refresh)
    assert report.attempted is True
    assert calls == [1]
    assert report.outcomes[0].ok is True


def test_maybe_refresh_swallows_failures() -> None:
    def _boom() -> CompletionRefreshReport:
        raise RuntimeError("generator exploded")

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
