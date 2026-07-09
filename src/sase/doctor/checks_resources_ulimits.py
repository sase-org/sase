"""Process resource-limit checks for ``sase doctor`` resources."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.axe.config import AxeConfig, load_axe_config
from sase.diagnostics import CheckStatus, DiagnosticCheck

_ULIMIT_NOFILE_BASE_FLOOR = 1024
_ULIMIT_NOFILE_PER_RUNNER = 128
_ULIMIT_NPROC_BASE_FLOOR = 128
_ULIMIT_NPROC_PER_RUNNER = 16

type _GetRLimitFn = Callable[[int], tuple[int, int]]
type _ImportResourceModuleFn = Callable[[], Any | None]


def check_ulimits(
    *,
    axe_config: AxeConfig | None = None,
    getrlimit_fn: _GetRLimitFn | None = None,
    resource_module: Any | None = None,
    import_resource_module_fn: _ImportResourceModuleFn | None = None,
) -> DiagnosticCheck:
    """Check soft process/file limits against configured runner concurrency."""
    if resource_module is None:
        import_resource_module_fn = import_resource_module_fn or import_resource_module
        resource_module = import_resource_module_fn()
    if resource_module is None:
        return DiagnosticCheck(
            id="resources.ulimits",
            group="resources",
            status="SKIP",
            title="Process resource limits",
            summary="Python resource limits are unavailable on this platform",
            data={"available": False, "limits": []},
        )

    axe_config = axe_config or load_axe_config()
    getrlimit_fn = getrlimit_fn or resource_module.getrlimit
    concurrency = _configured_runner_concurrency(axe_config)
    floors = _ulimit_floors(concurrency)
    rows: list[dict[str, Any]] = []

    for row_name, resource_name, floor in (
        ("nofile", "RLIMIT_NOFILE", floors["nofile"]),
        ("nproc", "RLIMIT_NPROC", floors["nproc"]),
    ):
        constant = getattr(resource_module, resource_name, None)
        if constant is None:
            rows.append(
                {
                    "name": row_name,
                    "resource": resource_name,
                    "available": False,
                    "status": "SKIP",
                    "soft": None,
                    "hard": None,
                    "soft_display": None,
                    "hard_display": None,
                    "floor": floor,
                    "problem": f"{resource_name} is unavailable on this platform",
                }
            )
            continue
        try:
            soft, hard = getrlimit_fn(constant)
        except OSError as exc:
            rows.append(
                {
                    "name": row_name,
                    "resource": resource_name,
                    "available": True,
                    "status": "WARN",
                    "soft": None,
                    "hard": None,
                    "soft_display": None,
                    "hard_display": None,
                    "floor": floor,
                    "problem": f"{resource_name} could not be read: {type(exc).__name__}: {exc}",
                }
            )
            continue
        rows.append(
            _ulimit_row(
                name=row_name,
                resource_name=resource_name,
                soft=int(soft),
                hard=int(hard),
                floor=floor,
                infinity=int(resource_module.RLIM_INFINITY),
            )
        )

    statuses = {row["status"] for row in rows}
    problems = tuple(str(row["problem"]) for row in rows if row.get("problem"))
    status: CheckStatus
    if "WARN" in statuses:
        status = "WARN"
    elif statuses == {"SKIP"}:
        status = "SKIP"
    else:
        status = "OK"

    return DiagnosticCheck(
        id="resources.ulimits",
        group="resources",
        status=status,
        title="Process resource limits",
        summary=_ulimit_summary(status, rows, concurrency),
        details=problems,
        next_steps=_ulimit_next_steps() if status == "WARN" else (),
        data={
            "available": status != "SKIP",
            "max_hook_runners": axe_config.max_hook_runners,
            "max_agent_runners": axe_config.max_agent_runners,
            "configured_runner_concurrency": concurrency,
            "floors": floors,
            "limits": rows,
        },
    )


_check_ulimits = check_ulimits


def import_resource_module() -> Any | None:
    try:
        import resource
    except ImportError:
        return None
    return resource


def _configured_runner_concurrency(config: AxeConfig) -> int:
    values = (config.max_hook_runners, config.max_agent_runners)
    return max(1, sum(_positive_int(value) for value in values))


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if not isinstance(value, str):
        return 0
    try:
        parsed = int(value)
    except ValueError:
        return 0
    return max(parsed, 0)


def _ulimit_floors(concurrency: int) -> dict[str, int]:
    return {
        "nofile": max(
            _ULIMIT_NOFILE_BASE_FLOOR,
            concurrency * _ULIMIT_NOFILE_PER_RUNNER,
        ),
        "nproc": max(
            _ULIMIT_NPROC_BASE_FLOOR,
            concurrency * _ULIMIT_NPROC_PER_RUNNER,
        ),
    }


def _ulimit_row(
    *,
    name: str,
    resource_name: str,
    soft: int,
    hard: int,
    floor: int,
    infinity: int,
) -> dict[str, Any]:
    soft_unlimited = _is_unlimited_limit(soft, infinity)
    hard_unlimited = _is_unlimited_limit(hard, infinity)
    problem = None
    status: CheckStatus = "OK"
    if not soft_unlimited and soft < floor:
        status = "WARN"
        problem = (
            f"{resource_name} soft limit {soft} is below the recommended floor {floor}"
        )
    return {
        "name": name,
        "resource": resource_name,
        "available": True,
        "status": status,
        "soft": None if soft_unlimited else soft,
        "hard": None if hard_unlimited else hard,
        "soft_display": "unlimited" if soft_unlimited else str(soft),
        "hard_display": "unlimited" if hard_unlimited else str(hard),
        "floor": floor,
        "problem": problem,
    }


def _is_unlimited_limit(value: int, infinity: int) -> bool:
    return value == infinity or value < 0


def _ulimit_summary(
    status: CheckStatus,
    rows: list[dict[str, Any]],
    concurrency: int,
) -> str:
    if status == "SKIP":
        return "process resource limits are unavailable"
    if status == "WARN":
        failed = [row for row in rows if row["status"] == "WARN"]
        return (
            f"{len(failed)} resource limit(s) are low for {concurrency} runner slot(s)"
        )
    checked = sum(1 for row in rows if row["status"] == "OK")
    return (
        f"{checked} resource limit(s) meet the floor for {concurrency} runner slot(s)"
    )


def _ulimit_next_steps() -> tuple[str, ...]:
    return (
        "Raise the reported soft limit(s), for example with shell `ulimit` settings or systemd `LimitNOFILE`/`TasksMax` configuration.",
        "Lower `axe.max_hook_runners` or `axe.max_agent_runners` if this host intentionally runs fewer concurrent jobs.",
    )
