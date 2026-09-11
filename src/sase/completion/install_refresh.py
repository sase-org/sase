"""Update-time refresh for stamped shell-completion installs."""

from __future__ import annotations

from collections.abc import Callable

from sase.completion.install_flow import install_completion
from sase.completion.install_models import (
    CompletionRefreshReport,
    InstallResult,
    RefreshShellOutcome,
    ShellInstallStatus,
)
from sase.completion.install_stamp import (
    list_stamps,
    resolve_stamp_target,
    stamp_is_chezmoi,
)
from sase.completion.install_status import list_shell_statuses
from sase.completion.install_targets import CompletionInstallError, SUPPORTED_SHELLS


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


def _refresh_detail(result: InstallResult) -> str:
    if result.ok:
        return f"refreshed {result.script}"
    failed = next((step for step in result.steps if step.status == "fail"), None)
    if failed is not None:
        return failed.detail
    return "refresh failed"
