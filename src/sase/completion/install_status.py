"""List and assess installed shell-completion state."""

from __future__ import annotations

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
from sase.completion.install_stamp import (
    InstallStamp,
    read_stamp,
    resolve_stamp_target,
    stamp_is_chezmoi,
)
from sase.completion.install_targets import SUPPORTED_SHELLS


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
            current = read_text(script)
            if current is None:
                drift_reasons.append("installed script cannot be read")
            elif current != completion_payload(expected.script):
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
