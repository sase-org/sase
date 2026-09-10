"""Install, verify, stamp, list, and refresh shell-completion scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sase
from sase.completion.install_stamp import (
    InstallStamp,
    OWNER_LOCAL,
    list_stamps,
    read_stamp,
    resolve_stamp_target,
    stamp_is_chezmoi,
    stamp_owns_path,
    write_stamp,
)
from sase.completion.install_targets import (
    CompletionInstallError,
    DetectedShell,
    ForeignInstallError,
    SUPPORTED_SHELLS,
    TargetChoice,
    ZSH_PROBE_TIMEOUT_SECONDS,
    detect_shell,
    fpath_hint_line,
    probe_zsh_comps,
    resolve_target,
    script_path,
)


RECOMMENDED_ZSTYLE = """\
# Recommended compsys styles for sase (grouped, described, menu-selected):
zstyle ':completion:*' menu select
zstyle ':completion:*' group-name ''
zstyle ':completion:*:descriptions' format '%F{yellow}-- %d --%f'
zstyle ':completion:*' verbose yes
zstyle ':completion:*' list-grouped true
zstyle ':completion:*' use-cache on
"""

EmitFn = Callable[[str], tuple[str, str]]
ExpectedFn = Callable[[Sequence[str]], Mapping[str, "_ExpectedCompletion"]]
ZcompileFn = Callable[[Path], None]
VerifyFn = Callable[[], str | None]
WritableFn = Callable[[Path], bool]


@dataclass(frozen=True, slots=True)
class InstallStep:
    """One reported step of an install or dry-run."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Outcome of ``sase completion install``."""

    shell: DetectedShell
    target: TargetChoice
    script: Path
    steps: tuple[InstallStep, ...]
    stamp: InstallStamp | None
    registered: bool | None
    fpath_hint: str | None
    ok: bool
    exit_code: int


@dataclass(frozen=True, slots=True)
class ShellInstallStatus:
    """Resolved ``sase completion list`` row for one shell."""

    shell: str
    generator: bool
    status: str
    path: str | None
    zwc: str
    stamp_version: str | None
    owner: str | None
    drift_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _ExpectedCompletion:
    """Current generated completion script and structural digest for one shell."""

    script: str
    digest: str


@dataclass(frozen=True, slots=True)
class _ScriptPublication:
    """A staged script publication result."""

    wrote_script: bool


@dataclass(frozen=True, slots=True)
class RefreshShellOutcome:
    """One shell's result from the update-time refresh hook."""

    shell: str
    ok: bool
    detail: str
    target: str | None


@dataclass(frozen=True, slots=True)
class CompletionRefreshReport:
    """Result of the ``sase update`` completion refresh."""

    attempted: bool
    outcomes: tuple[RefreshShellOutcome, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "shells": [
                {
                    "detail": outcome.detail,
                    "ok": outcome.ok,
                    "shell": outcome.shell,
                    "target": outcome.target,
                }
                for outcome in self.outcomes
            ],
        }


def _utc_timestamp() -> str:
    """Return a second-precision UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _completion_payload(text: str) -> str:
    """Return generated completion text with the on-disk trailing newline."""
    return text if text.endswith("\n") else f"{text}\n"


def zwc_path(script: Path) -> Path:
    """Return the ``zcompile`` output path for *script*."""
    return script.with_name(f"{script.name}.zwc")


def _zwc_freshness(shell: str, script: Path) -> str:
    """Return ``fresh`` / ``stale`` / ``missing`` / ``n/a`` for *script*."""
    if shell != "zsh":
        return "n/a"
    compiled = zwc_path(script)
    try:
        if not compiled.is_file():
            return "missing"
        if not script.is_file():
            return "stale"
        if compiled.stat().st_mtime < script.stat().st_mtime:
            return "stale"
    except OSError:
        return "missing"
    return "fresh"


def _emit_script_and_digest(shell: str) -> tuple[str, str]:
    """Build the live spec once and return ``(script, digest)`` for *shell*."""
    expected = _expected_scripts_for_shells((shell,))[shell]
    return expected.script, expected.digest


def _expected_scripts_for_shells(
    shells: Sequence[str],
) -> Mapping[str, _ExpectedCompletion]:
    """Build the live spec once and emit current completion scripts for *shells*."""
    from sase.completion.build import build_spec

    spec = build_spec()
    digest = spec.structural_digest()
    return {
        shell: _ExpectedCompletion(_emit_script(shell, spec), digest)
        for shell in shells
    }


def _emit_script(shell: str, spec: object) -> str:
    """Emit the current completion script for *shell* from *spec*."""
    from sase.completion.model import CompletionSpec

    if not isinstance(spec, CompletionSpec):
        raise CompletionInstallError("completion spec has an unexpected type")

    if shell == "bash":
        from sase.completion.emit_bash import emit_bash

        return emit_bash(spec)
    elif shell == "fish":
        from sase.completion.emit_fish import emit_fish

        return emit_fish(spec)
    elif shell == "zsh":
        from sase.completion.emit_zsh import emit_zsh

        return emit_zsh(spec)
    else:
        raise CompletionInstallError(f"unsupported shell: {shell}")


def _zcompile_script(
    path: Path,
    *,
    timeout: float = ZSH_PROBE_TIMEOUT_SECONDS,
    zsh: str | None = None,
) -> None:
    """``zcompile`` *path*. Mandatory for zsh; not an optimization."""
    binary = zsh or shutil.which("zsh")
    if binary is None:
        raise CompletionInstallError("zsh is not on PATH; cannot zcompile")
    try:
        completed = subprocess.run(
            [binary, "-c", "zcompile -U -- $1", "sase-zcompile", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompletionInstallError(f"zcompile timed out for {path}") from exc
    except OSError as exc:
        raise CompletionInstallError(f"zcompile failed for {path}: {exc}") from exc
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "unknown error").strip()
        raise CompletionInstallError(f"zcompile failed for {path}: {err}")


def _publish_script(
    script: Path,
    text: str,
    *,
    shell: str,
    zcompile_fn: ZcompileFn | None,
) -> _ScriptPublication:
    """Stage and publish generated completion bytes for one shell."""
    script.parent.mkdir(parents=True, exist_ok=True)
    payload = _completion_payload(text)
    tmp = script.with_name(f".{script.name}.{os.getpid()}.tmp")
    tmp_zwc = zwc_path(tmp)
    final_zwc = zwc_path(script)
    wrote_script = False
    try:
        tmp.write_text(payload, encoding="utf-8")
        if shell == "zsh":
            try:
                (zcompile_fn or _zcompile_script)(tmp)
            except OSError as exc:
                raise CompletionInstallError(
                    f"zcompile failed for {tmp}: {exc}"
                ) from exc
            if not tmp_zwc.is_file():
                raise CompletionInstallError(f"zcompile did not create {tmp_zwc}")

        current = _read_text(script)
        if current != payload:
            os.replace(tmp, script)
            wrote_script = True
        else:
            tmp.unlink(missing_ok=True)

        if shell == "zsh":
            os.replace(tmp_zwc, final_zwc)
    except Exception:
        tmp.unlink(missing_ok=True)
        tmp_zwc.unlink(missing_ok=True)
        raise
    return _ScriptPublication(wrote_script=wrote_script)


def _read_text(path: Path) -> str | None:
    """Return text for *path*, or ``None`` when it is absent or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _remove_superseded_script(
    previous: InstallStamp | None, script: Path
) -> InstallStep | None:
    """Delete the script a prior install stamped at a different path.

    Only the stamped path is touched: the stamp is sase's own record of what
    it wrote, so a file it names is never a user's or another tool's. Returns
    ``None`` when there is nothing to clean up.
    """
    if previous is None:
        return None
    stale = Path(previous.target).expanduser()
    try:
        same = stale.resolve() == script.expanduser().resolve()
    except OSError:
        same = stale == script
    if same:
        return None

    removed: list[Path] = []
    for path in (stale, zwc_path(stale)):
        try:
            if path.is_file():
                path.unlink()
                removed.append(path)
        except OSError as exc:
            return InstallStep("migrate", "warn", f"could not remove {path}: {exc}")
    if not removed:
        return None
    return InstallStep(
        "migrate",
        "ok",
        "removed superseded " + ", ".join(str(path) for path in removed),
    )


def install_completion(
    *,
    requested: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    target: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    scanned: Sequence[Path] | None = None,
    writable: WritableFn | None = None,
    parent: str | None | object = ...,
    emit_fn: EmitFn | None = None,
    zcompile_fn: ZcompileFn | None = None,
    verify_fn: VerifyFn | None = None,
    version: str | None = None,
    timestamp: str | None = None,
) -> InstallResult:
    """Install completion for one shell and return a step-by-step result."""
    env = os.environ if environ is None else environ
    home_path = Path.home() if home is None else home
    detected = detect_shell(requested=requested, environ=env, parent=parent)
    choice = resolve_target(
        detected.name,
        target=target,
        environ=env,
        home=home_path,
        scanned=scanned,
        writable=writable,
    )
    script = script_path(choice.directory, detected.name)
    previous = read_stamp(detected.name)
    steps: list[InstallStep] = [
        InstallStep("detect", _planned(dry_run), detected.source),
        InstallStep(
            "target", _planned(dry_run), f"{choice.directory} ({choice.reason})"
        ),
    ]

    if stamp_is_chezmoi(previous) and not force:
        steps.append(
            InstallStep(
                "ownership",
                "fail",
                "target is managed by chezmoi; pass --force to convert to a local install",
            )
        )
        return _result(
            detected,
            choice,
            script,
            steps,
            ok=False,
            exit_code=1,
            fpath_hint=_hint(detected.name, choice.directory, home_path),
        )

    try:
        _require_writable_or_creatable(script, shell=detected.name, force=force)
    except CompletionInstallError as exc:
        steps.append(InstallStep("write", "fail", str(exc)))
        return _result(
            detected,
            choice,
            script,
            steps,
            ok=False,
            exit_code=1,
            fpath_hint=_hint(detected.name, choice.directory, home_path),
        )

    if dry_run:
        steps.extend(_dry_run_steps(detected.name, previous=previous, script=script))
        return _result(
            detected,
            choice,
            script,
            steps,
            ok=True,
            exit_code=0,
            fpath_hint=_hint(detected.name, choice.directory, home_path),
        )

    emit = emit_fn or _emit_script_and_digest
    try:
        text, digest = emit(detected.name)
        publication = _publish_script(
            script,
            text,
            shell=detected.name,
            zcompile_fn=zcompile_fn,
        )
    except OSError as exc:
        steps.append(InstallStep("write", "fail", f"cannot write {script}: {exc}"))
        return _result(detected, choice, script, steps, ok=False, exit_code=1)
    except CompletionInstallError as exc:
        step_name = "zcompile" if detected.name == "zsh" else "write"
        steps.append(InstallStep(step_name, "fail", str(exc)))
        return _result(detected, choice, script, steps, ok=False, exit_code=1)
    write_detail = str(script) if publication.wrote_script else f"{script} unchanged"
    steps.append(InstallStep("write", "ok", write_detail))
    if detected.name == "zsh":
        steps.append(InstallStep("zcompile", "ok", str(zwc_path(script))))
    else:
        steps.append(InstallStep("zcompile", "skip", "not required"))

    stamp = InstallStamp(
        shell=detected.name,
        version=sase.__version__ if version is None else version,
        digest=digest,
        target=str(script),
        timestamp=_utc_timestamp() if timestamp is None else timestamp,
        owner=OWNER_LOCAL,
    )
    try:
        write_stamp(stamp)
    except OSError as exc:
        steps.append(InstallStep("stamp", "fail", str(exc)))
        return _result(
            detected,
            choice,
            script,
            steps,
            stamp=stamp,
            ok=False,
            exit_code=1,
        )
    steps.append(InstallStep("stamp", "ok", f"{stamp.version} @ {script}"))

    migrate_step = _remove_superseded_script(previous, script)
    if migrate_step is not None:
        steps.append(migrate_step)

    registered, verify_step, hint, verify_failed = _verify_install(
        detected.name,
        choice.directory,
        home_path,
        verify_fn=verify_fn,
        env=env,
    )
    steps.append(verify_step)
    ok = not verify_failed
    return _result(
        detected,
        choice,
        script,
        steps,
        stamp=stamp,
        registered=registered,
        fpath_hint=hint,
        ok=ok,
        exit_code=0 if ok else 1,
    )


def list_shell_statuses(
    *,
    version: str | None = None,
    expected_fn: ExpectedFn | None = None,
) -> tuple[ShellInstallStatus, ...]:
    """Return the resolved install status of every supported shell."""
    running = sase.__version__ if version is None else version
    stamps = {shell: read_stamp(shell) for shell in SUPPORTED_SHELLS}
    stamped_shells = tuple(
        shell for shell, stamp in stamps.items() if stamp is not None
    )
    expected = (
        (expected_fn or _expected_scripts_for_shells)(stamped_shells)
        if stamped_shells
        else {}
    )
    return tuple(
        _status_for_shell(
            shell,
            running=running,
            stamp=stamps[shell],
            expected=expected.get(shell),
        )
        for shell in SUPPORTED_SHELLS
    )


def _skip_refresh_verify() -> str | None:
    """Skip ``${_comps[sase]}`` probing during update-time refresh."""
    return None


def refresh_stamped_completions(
    *,
    shell: str | None = None,
    dry_run: bool = False,
    install_fn: Callable[..., InstallResult] | None = None,
) -> CompletionRefreshReport:
    """Regenerate, zcompile, and restamp every shell that already has a stamp."""
    stamps = list_stamps()
    if shell is not None and shell not in SUPPORTED_SHELLS:
        raise CompletionInstallError(f"unsupported shell: {shell}")
    if shell is not None:
        stamps = tuple(stamp for stamp in stamps if stamp.shell == shell)
    if not stamps:
        if shell is not None:
            return CompletionRefreshReport(
                attempted=True,
                outcomes=(
                    RefreshShellOutcome(
                        shell=shell,
                        ok=True,
                        detail=f"no stamped {shell} completion install",
                        target=None,
                    ),
                ),
            )
        return CompletionRefreshReport(attempted=True, outcomes=())
    installer = install_fn or install_completion
    statuses = {row.shell: row for row in list_shell_statuses()}
    outcomes: list[RefreshShellOutcome] = []
    for stamp in stamps:
        status = statuses[stamp.shell]
        if stamp_is_chezmoi(stamp):
            outcomes.append(
                RefreshShellOutcome(
                    shell=stamp.shell,
                    ok=False,
                    detail=(
                        f"legacy chezmoi-managed {stamp.target} is not refreshed "
                        "automatically; migrate the managed install first"
                    ),
                    target=stamp.target,
                )
            )
            continue
        if dry_run:
            outcomes.append(
                RefreshShellOutcome(
                    shell=stamp.shell,
                    ok=True,
                    detail=_refresh_dry_run_detail(status),
                    target=stamp.target,
                )
            )
            continue
        target_dir = resolve_stamp_target(stamp.target).parent
        try:
            # fpath probing is first-install only; it false-fails disposable dirs.
            result = installer(
                requested=stamp.shell,
                force=True,
                target=target_dir,
                verify_fn=_skip_refresh_verify,
            )
        except Exception as exc:  # noqa: BLE001 - refresh must never abort update.
            outcomes.append(
                RefreshShellOutcome(
                    shell=stamp.shell,
                    ok=False,
                    detail=str(exc),
                    target=stamp.target,
                )
            )
            continue
        outcomes.append(
            RefreshShellOutcome(
                shell=stamp.shell,
                ok=result.ok,
                detail=_refresh_detail(result),
                target=str(result.script),
            )
        )
    return CompletionRefreshReport(attempted=True, outcomes=tuple(outcomes))


def _refresh_stamped_completions(
    *,
    install_fn: Callable[..., InstallResult] | None = None,
) -> CompletionRefreshReport:
    """Backward-compatible wrapper for existing injected refresh hooks."""
    return refresh_stamped_completions(install_fn=install_fn)


def _refresh_dry_run_detail(status: ShellInstallStatus) -> str:
    target = status.path or "<unset>"
    if status.status == "installed":
        return f"already current at {target}"
    reasons = "; ".join(status.drift_reasons)
    suffix = f" ({reasons})" if reasons else ""
    return f"would refresh {target}{suffix}"


def maybe_refresh_installed_completions(
    refresh_fn: Callable[[], CompletionRefreshReport] | None = None,
) -> CompletionRefreshReport:
    """Run the update-time completion refresh after a successful update.

    Failures are reported, never fatal.
    """
    fn = refresh_fn or _refresh_stamped_completions
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - update must keep succeeding.
        return CompletionRefreshReport(
            attempted=True,
            outcomes=(
                RefreshShellOutcome(
                    shell="*",
                    ok=False,
                    detail=str(exc),
                    target=None,
                ),
            ),
        )


def _status_for_shell(
    shell: str,
    *,
    running: str,
    stamp: InstallStamp | None = None,
    expected: _ExpectedCompletion | None = None,
) -> ShellInstallStatus:
    if stamp is None:
        stamp = read_stamp(shell)
    if stamp is None:
        return ShellInstallStatus(
            shell=shell,
            generator=True,
            status="not installed",
            path=None,
            zwc="n/a",
            stamp_version=None,
            owner=None,
        )
    script = resolve_stamp_target(stamp.target)
    present = script.is_file()
    freshness = _zwc_freshness(shell, script)
    drift_reasons: list[str] = []
    if not present:
        status = "missing"
        drift_reasons.append("stamped script is missing")
    else:
        if stamp.version != running:
            drift_reasons.append(
                f"stamp version {stamp.version} differs from running {running}"
            )
        if expected is None:
            drift_reasons.append("current generated completion could not be assessed")
        elif stamp.digest != expected.digest:
            drift_reasons.append(
                f"stamp digest {stamp.digest} differs from running {expected.digest}"
            )
        if expected is not None:
            current = _read_text(script)
            if current is None:
                drift_reasons.append("installed script cannot be read")
            elif current != _completion_payload(expected.script):
                drift_reasons.append("installed script differs from current generator")

    if present and stamp_is_chezmoi(stamp):
        drift_reasons.append(
            "legacy chezmoi-managed install is not refreshed automatically"
        )

    if not present:
        status = "missing"
    elif stamp_is_chezmoi(stamp) and drift_reasons:
        status = "managed stale"
    elif stamp_is_chezmoi(stamp):
        status = "managed"
    elif drift_reasons:
        status = "stale"
    elif freshness == "stale" or freshness == "missing":
        status = "zwc stale"
        drift_reasons.append(f".zwc is {freshness}")
    else:
        status = "installed"
    return ShellInstallStatus(
        shell=shell,
        generator=True,
        status=status,
        path=stamp.target,
        zwc=freshness,
        stamp_version=stamp.version,
        owner=stamp.owner,
        drift_reasons=tuple(drift_reasons),
    )


def _require_writable_or_creatable(
    script: Path,
    *,
    shell: str,
    force: bool,
) -> None:
    if not script.exists():
        return
    if stamp_owns_path(shell, script) or force:
        return
    raise ForeignInstallError(
        f"{script} exists and was not written by sase; pass --force to overwrite"
    )


def _verify_install(
    shell: str,
    directory: Path,
    home: Path,
    *,
    verify_fn: VerifyFn | None,
    env: Mapping[str, str],
) -> tuple[bool | None, InstallStep, str | None, bool]:
    hint = _hint(shell, directory, home)
    if shell != "zsh":
        return None, InstallStep("verify", "skip", "zsh registration only"), hint, False
    probe = verify_fn or (lambda: probe_zsh_comps(env=env))
    value = probe()
    if value is None:
        return (
            None,
            InstallStep("verify", "skip", "could not probe ${_comps[sase]}"),
            hint,
            False,
        )
    if value == "UNSET":
        return (
            False,
            InstallStep(
                "verify",
                "fail",
                f"_comps[sase] is UNSET; add this line before compinit: {hint}",
            ),
            hint,
            True,
        )
    return True, InstallStep("verify", "ok", f"_comps[sase]={value}"), None, False


def _hint(shell: str, directory: Path, home: Path) -> str | None:
    if shell != "zsh":
        return None
    return fpath_hint_line(directory, home=home)


def _dry_run_steps(
    shell: str, *, previous: InstallStamp | None, script: Path
) -> tuple[InstallStep, ...]:
    zcompile = (
        InstallStep("zcompile", "planned", "zcompile the script")
        if shell == "zsh"
        else InstallStep("zcompile", "skip", "not required")
    )
    verify = (
        InstallStep("verify", "planned", "probe ${_comps[sase]}")
        if shell == "zsh"
        else InstallStep("verify", "skip", "zsh registration only")
    )
    steps = [
        InstallStep("write", "planned", "write the script atomically"),
        zcompile,
        InstallStep("stamp", "planned", "write ~/.sase/completion/stamp/<shell>.json"),
    ]
    if previous is not None and Path(previous.target).expanduser() != script:
        steps.append(
            InstallStep("migrate", "planned", f"remove superseded {previous.target}")
        )
    steps.append(verify)
    return tuple(steps)


def _planned(dry_run: bool) -> str:
    return "planned" if dry_run else "ok"


def _result(
    detected: DetectedShell,
    choice: TargetChoice,
    script: Path,
    steps: Sequence[InstallStep],
    *,
    ok: bool,
    exit_code: int,
    stamp: InstallStamp | None = None,
    registered: bool | None = None,
    fpath_hint: str | None = None,
) -> InstallResult:
    return InstallResult(
        shell=detected,
        target=choice,
        script=script,
        steps=tuple(steps),
        stamp=stamp,
        registered=registered,
        fpath_hint=fpath_hint,
        ok=ok,
        exit_code=exit_code,
    )


def _refresh_detail(result: InstallResult) -> str:
    if result.ok:
        return f"refreshed {result.script}"
    failed = next((step for step in result.steps if step.status == "fail"), None)
    if failed is not None:
        return failed.detail
    return "refresh failed"


__all__ = [
    "CompletionInstallError",
    "CompletionRefreshReport",
    "DetectedShell",
    "ForeignInstallError",
    "InstallResult",
    "InstallStep",
    "RECOMMENDED_ZSTYLE",
    "RefreshShellOutcome",
    "ShellInstallStatus",
    "install_completion",
    "list_shell_statuses",
    "maybe_refresh_installed_completions",
    "refresh_stamped_completions",
    "zwc_path",
]
