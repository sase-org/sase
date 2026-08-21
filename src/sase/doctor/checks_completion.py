"""Advisory completion-install checks for ``sase doctor``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from sase.completion.install import ShellInstallStatus, list_shell_statuses, zwc_path
from sase.completion.install_stamp import InstallStamp, list_stamps
from sase.completion.install_targets import probe_zsh_comps
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


_CHECK_TITLE = "Shell completion install"
_REG_TITLE = "Shell completion registration"
StatusProbe = Callable[[], tuple[ShellInstallStatus, ...]]
CompsProbe = Callable[[], str | None]
StampsProbe = Callable[[], tuple[InstallStamp, ...]]


def completion_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return completion-install check specs."""
    del context
    return (
        CheckSpec(
            id="completion.install",
            group="completion",
            title=_CHECK_TITLE,
            runner=_check_completion_install,
        ),
        CheckSpec(
            id="completion.registration",
            group="completion",
            title=_REG_TITLE,
            runner=_check_completion_registration,
            deep=True,
        ),
    )


def _check_completion_install(
    *,
    statuses: Sequence[ShellInstallStatus] | None = None,
    status_fn: StatusProbe | None = None,
) -> DiagnosticCheck:
    """Advise on stamped completion scripts, ``.zwc`` freshness, and version.

    File presence alone is not accepted as evidence of a working install:
    only a stamp plus the checks below can produce OK.
    """
    rows = (
        tuple(statuses)
        if statuses is not None
        else (status_fn or list_shell_statuses)()
    )
    stamped = tuple(row for row in rows if row.stamp_version is not None)
    if not stamped:
        return _check(
            "completion.install",
            _CHECK_TITLE,
            "SKIP",
            "no sase completion install is stamped",
            data=_status_data(rows),
            next_steps=("Install with `sase completion install`.",),
        )

    problems = tuple(_install_problem(row) for row in stamped)
    failed = tuple(item for item in problems if item is not None)
    details = tuple(_install_detail(row) for row in stamped)
    if failed:
        return _check(
            "completion.install",
            _CHECK_TITLE,
            "WARN",
            _join_problems(failed),
            details=details,
            next_steps=(
                "Reinstall with `sase completion install --force`.",
                "Rerun `sase doctor -C completion.install -v`.",
            ),
            data=_status_data(rows),
        )
    return _check(
        "completion.install",
        _CHECK_TITLE,
        "OK",
        f"{len(stamped)} stamped shell(s) match the running sase version",
        details=details,
        data=_status_data(rows),
    )


def _check_completion_registration(
    *,
    stamps: Sequence[InstallStamp] | None = None,
    stamps_fn: StampsProbe | None = None,
    probe: CompsProbe | None = None,
) -> DiagnosticCheck:
    """Deep check: ``_comps[sase]`` must resolve. File presence is not enough."""
    resolved = tuple(stamps) if stamps is not None else (stamps_fn or list_stamps)()
    zsh_stamps = tuple(stamp for stamp in resolved if stamp.shell == "zsh")
    if not zsh_stamps:
        return _check(
            "completion.registration",
            _REG_TITLE,
            "SKIP",
            "no stamped zsh completion install to probe",
            data={"stamped_zsh": False, "comps": None},
        )

    comps = (probe or probe_zsh_comps)()
    if comps is None:
        return _check(
            "completion.registration",
            _REG_TITLE,
            "SKIP",
            "could not probe interactive zsh for ${_comps[sase]}",
            data={"stamped_zsh": True, "comps": None},
            next_steps=(
                "Install zsh or rerun `sase doctor -C completion.registration -D`.",
            ),
        )
    if comps == "UNSET":
        target = zsh_stamps[0].target
        hint_dir = _parent_display(target)
        return _check(
            "completion.registration",
            _REG_TITLE,
            "WARN",
            "_comps[sase] is UNSET; the script is not registered",
            details=(
                f"stamped path: {target}",
                "file presence is not evidence of a working zsh install",
                f"fpath=({hint_dir} $fpath)   # must appear BEFORE compinit",
            ),
            next_steps=(
                "Add the fpath line before compinit and open a new shell.",
                "Then rerun `sase doctor -C completion.registration -D`.",
            ),
            data={"stamped_zsh": True, "comps": "UNSET", "target": target},
        )
    return _check(
        "completion.registration",
        _REG_TITLE,
        "OK",
        f"_comps[sase] resolves to {comps}",
        data={"stamped_zsh": True, "comps": comps},
    )


def _install_problem(row: ShellInstallStatus) -> str | None:
    if row.status == "missing":
        return f"{row.shell}: stamped script is missing"
    if row.status == "stale":
        return f"{row.shell}: stamp version {row.stamp_version} is stale"
    if row.status == "zwc stale":
        return f"{row.shell}: .zwc is {row.zwc}"
    return None


def _install_detail(row: ShellInstallStatus) -> str:
    path = row.path or "<unset>"
    extra = ""
    if row.shell == "zsh" and row.path:
        extra = f" zwc={zwc_path(Path(row.path))}"
    return (
        f"{row.shell}: {row.status} path={path} zwc={row.zwc} "
        f"stamp={row.stamp_version} owner={row.owner or '—'}{extra}"
    )


def _status_data(rows: Sequence[ShellInstallStatus]) -> Mapping[str, object]:
    return {
        "shells": [
            {
                "path": row.path,
                "owner": row.owner,
                "shell": row.shell,
                "stamp_version": row.stamp_version,
                "status": row.status,
                "zwc": row.zwc,
            }
            for row in rows
        ]
    }


def _join_problems(problems: Sequence[str]) -> str:
    if len(problems) == 1:
        return problems[0]
    return f"{len(problems)} completion install problems"


def _parent_display(target: str) -> str:
    from sase.core.paths import shorten_path

    return shorten_path(str(Path(target).expanduser().parent))


def _check(
    check_id: str,
    title: str,
    status: CheckStatus,
    summary: str,
    *,
    details: Sequence[str] = (),
    next_steps: Sequence[str] = (),
    data: Mapping[str, object] | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=check_id,
        group="completion",
        status=status,
        title=title,
        summary=summary,
        details=details,
        next_steps=next_steps,
        data=data or {},
    )


__all__ = [
    "completion_check_specs",
]
