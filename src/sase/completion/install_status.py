"""List and assess installed shell-completion state."""

from __future__ import annotations

import hashlib
from pathlib import Path

import sase
from sase.completion.install_models import (
    ExpectedFn,
    ExpectedCompletion,
    ShellInstallStatus,
)
from sase.completion.install_scripts import (
    completion_payload,
    expected_scripts_for_shells,
    read_text,
    zwc_freshness,
)
from sase.completion.loader import emit_loader
from sase.completion.install_stamp import (
    InstallStamp,
    REPRESENTATION_LOADER,
    REPRESENTATION_RAW,
    read_stamp,
    resolve_stamp_target,
    stamp_is_chezmoi,
)
from sase.completion.install_targets import SUPPORTED_SHELLS
from sase.completion.runtime_cache import RuntimeGrammarStatus, assess_cached_grammar


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
        (expected_fn or expected_scripts_for_shells)(stamped_shells)
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


def _status_for_shell(
    shell: str,
    *,
    running: str,
    stamp: InstallStamp | None = None,
    expected: ExpectedCompletion | None = None,
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
    freshness = zwc_freshness(shell, script)
    drift_reasons: list[str] = []
    grammar_status: RuntimeGrammarStatus | None = None
    if not present:
        status = "missing"
        drift_reasons.append("stamped script is missing")
    elif stamp.representation == REPRESENTATION_LOADER:
        _assess_loader_script(
            shell,
            script=script,
            stamp=stamp,
            drift_reasons=drift_reasons,
        )
        if expected is None:
            drift_reasons.append("current generated completion could not be assessed")
        try:
            grammar_status = assess_cached_grammar(shell, expected=expected)
        except Exception as exc:  # noqa: BLE001 - diagnostics should stay readable.
            drift_reasons.append(f"runtime grammar cache could not be assessed: {exc}")
        else:
            if grammar_status.status != "current":
                drift_reasons.extend(grammar_status.drift_reasons)
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
            current = read_text(script)
            if current is None:
                drift_reasons.append("installed script cannot be read")
            elif current != completion_payload(expected.script):
                drift_reasons.append("installed script differs from current generator")

    if (
        present
        and stamp_is_chezmoi(stamp)
        and stamp.representation == REPRESENTATION_RAW
    ):
        drift_reasons.append(
            "legacy chezmoi-managed raw snapshot should be refreshed to a loader; "
            "migrate the managed source to prevent rollback on the next apply"
        )

    if not present:
        status = "missing"
    elif stamp_is_chezmoi(stamp) and drift_reasons:
        status = "managed stale"
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
        representation=stamp.representation,
        loader_status=_loader_status(stamp, drift_reasons, present=present),
        grammar_status=None if grammar_status is None else grammar_status.status,
        grammar_path=None if grammar_status is None else grammar_status.path,
    )


def _assess_loader_script(
    shell: str,
    *,
    script: Path,
    stamp: InstallStamp,
    drift_reasons: list[str],
) -> None:
    current_loader = emit_loader(shell, owner=stamp.owner)
    current_digest = _sha256_text(current_loader)
    if stamp.loader_digest is not None and stamp.loader_digest != current_digest:
        drift_reasons.append("stamp loader digest differs from running loader")
    installed = read_text(script)
    if installed is None:
        drift_reasons.append("installed loader cannot be read")
    elif installed != completion_payload(current_loader):
        drift_reasons.append("installed loader differs from running loader")


def _loader_status(
    stamp: InstallStamp,
    drift_reasons: list[str],
    *,
    present: bool,
) -> str | None:
    if stamp.representation != REPRESENTATION_LOADER:
        return None
    if not present:
        return "missing"
    if any("loader" in reason for reason in drift_reasons):
        return "stale"
    return "current"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
