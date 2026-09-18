"""Interactive shell-completion install flow."""

from __future__ import annotations

import os
import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import sase
from sase.completion.loader import emit_loader
from sase.completion.install_models import (
    EmitFn,
    InstallResult,
    InstallStep,
    VerifyFn,
    WritableFn,
    ZcompileFn,
)
from sase.completion.install_scripts import (
    emit_script_and_digest,
    publish_script,
    zwc_path,
)
from sase.completion.install_stamp import (
    InstallStamp,
    OWNER_LOCAL,
    REPRESENTATION_LOADER,
    REPRESENTATION_RAW,
    read_stamp,
    stamp_is_chezmoi,
    stamp_owns_path,
    write_stamp,
)
from sase.completion.install_targets import (
    CompletionInstallError,
    DetectedShell,
    ForeignInstallError,
    TargetChoice,
    detect_shell,
    fpath_hint_line,
    probe_zsh_comps,
    resolve_target,
    script_path,
)
from sase.completion.runtime_cache import (
    CompletionCacheError,
    RuntimeGrammarStatus,
    assess_cached_grammar,
    ensure_cached_grammar,
)


def _utc_timestamp() -> str:
    """Return a second-precision UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    owner: str = OWNER_LOCAL,
    force_cache: bool = False,
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

    if stamp_is_chezmoi(previous) and owner == OWNER_LOCAL and not force:
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
        steps.extend(
            _dry_run_steps(
                detected.name,
                previous=previous,
                script=script,
                representation=_representation_for_emit(emit_fn),
            )
        )
        return _result(
            detected,
            choice,
            script,
            steps,
            ok=True,
            exit_code=0,
            fpath_hint=_hint(detected.name, choice.directory, home_path),
        )

    stamp_representation = _representation_for_emit(emit_fn)
    loader_digest: str | None = None
    grammar_status: RuntimeGrammarStatus | None = None
    try:
        if emit_fn is None:
            text, digest, loader_digest, grammar_status = _emit_loader_and_digest(
                detected.name,
                script=script,
                owner=owner,
                force_cache=force_cache,
                zcompile_fn=zcompile_fn,
            )
        else:
            text, digest = emit_fn(detected.name)
        publication = publish_script(
            script,
            text,
            shell=detected.name,
            zcompile_fn=zcompile_fn,
        )
    except CompletionCacheError as exc:
        steps.append(InstallStep("grammar", "fail", str(exc)))
        return _result(detected, choice, script, steps, ok=False, exit_code=1)
    except OSError as exc:
        steps.append(InstallStep("write", "fail", f"cannot write {script}: {exc}"))
        return _result(detected, choice, script, steps, ok=False, exit_code=1)
    except CompletionInstallError as exc:
        step_name = "zcompile" if detected.name == "zsh" else "write"
        steps.append(InstallStep(step_name, "fail", str(exc)))
        return _result(detected, choice, script, steps, ok=False, exit_code=1)
    if grammar_status is not None:
        steps.append(
            InstallStep(
                "grammar",
                "ok",
                f"{grammar_status.status} at {grammar_status.path}",
            )
        )
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
        owner=owner,
        representation=stamp_representation,
        loader_digest=loader_digest,
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
    shell: str,
    *,
    previous: InstallStamp | None,
    script: Path,
    representation: str,
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
        InstallStep(
            "grammar",
            "planned",
            "validate the runtime grammar cache",
        )
        if representation == REPRESENTATION_LOADER
        else InstallStep("grammar", "skip", "raw script export"),
        InstallStep("write", "planned", f"write the {representation} atomically"),
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


def _representation_for_emit(emit_fn: EmitFn | None) -> str:
    return REPRESENTATION_LOADER if emit_fn is None else REPRESENTATION_RAW


def _emit_loader_and_digest(
    shell: str,
    *,
    script: Path,
    owner: str,
    force_cache: bool,
    zcompile_fn: ZcompileFn | None,
) -> tuple[str, str, str, RuntimeGrammarStatus]:
    ensure_cached_grammar(
        shell,
        force=force_cache,
        loader_path=script,
        owner=owner,
        zcompile_fn=zcompile_fn,
    )
    status = assess_cached_grammar(shell)
    if status.status != "current":
        reasons = "; ".join(status.drift_reasons) or status.status
        raise CompletionCacheError(f"runtime grammar cache is not current: {reasons}")
    if not status.structural_digest:
        raise CompletionCacheError("runtime grammar cache did not record a digest")
    text = emit_loader(shell, owner=owner)
    return text, status.structural_digest, _sha256_text(text), status


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
