"""Status aggregation for the axe process facade."""

from sase.ace.patch import count_agent_runners_global, count_hook_runners_global

from . import _process_probe as process_probe
from .config import load_axe_config
from .state import read_lumberjack_status, read_status


def get_axe_status() -> dict | None:
    """Get current axe daemon status for TUI display.

    Aggregates the orchestrator status with per-lumberjack statuses.

    Returns:
        Status dict, or None if not running.
    """
    pid = process_probe.get_axe_pid()
    if pid is None:
        return None

    status = read_status()
    if status is not None:
        result: dict = {
            "pid": status.pid,
            "started_at": status.started_at,
            "status": status.status,
            "full_check_interval": status.full_check_interval,
            "hook_interval": status.hook_interval,
            "max_hook_runners": status.max_hook_runners,
            "max_agent_runners": status.max_agent_runners,
            "zombie_timeout": status.zombie_timeout,
            "query": status.query,
            "current_hook_runners": status.current_hook_runners,
            "current_agent_runners": status.current_agent_runners,
            "last_full_cycle": status.last_full_cycle,
            "last_hook_cycle": status.last_hook_cycle,
            "next_full_cycle": status.next_full_cycle,
            "total_patches": status.total_patches,
            "filtered_patches": status.filtered_patches,
            "uptime_seconds": status.uptime_seconds,
        }
    else:
        # No legacy status.json: construct from config + live data.
        config = load_axe_config()
        result = {
            "pid": pid,
            "started_at": "",
            "status": "running",
            "full_check_interval": 0,
            "hook_interval": 0,
            "max_hook_runners": config.max_hook_runners,
            "max_agent_runners": config.max_agent_runners,
            "zombie_timeout": config.zombie_timeout_seconds,
            "query": config.query,
            "current_hook_runners": 0,
            "current_agent_runners": 0,
            "last_full_cycle": None,
            "last_hook_cycle": None,
            "next_full_cycle": None,
            "total_patches": 0,
            "filtered_patches": 0,
            "uptime_seconds": 0,
        }

    lumberjacks_status: dict[str, dict] = {}
    lumberjack_start_times: list[str] = []
    for name in get_lumberjack_names():
        lumberjack_status = read_lumberjack_status(name)
        if lumberjack_status is not None:
            lumberjacks_status[name] = {
                "pid": lumberjack_status.pid,
                "status": lumberjack_status.status,
                "interval": lumberjack_status.interval,
                "chops": lumberjack_status.chops,
                "cycles_run": lumberjack_status.cycles_run,
                "errors_encountered": lumberjack_status.errors_encountered,
                "uptime_seconds": lumberjack_status.uptime_seconds,
            }
            lumberjack_start_times.append(lumberjack_status.started_at)
    if lumberjacks_status:
        result["lumberjacks"] = lumberjacks_status

    # Derive started_at and current runner counts from live data. The
    # legacy status.json is not written by the new orchestrator architecture,
    # so its fields can be stale from a previous run.
    if lumberjack_start_times:
        result["started_at"] = min(lumberjack_start_times)
    result["current_hook_runners"] = count_hook_runners_global()
    result["current_agent_runners"] = count_agent_runners_global()

    return result


def get_lumberjack_names() -> list[str]:
    """Return configured lumberjack names from the axe config.

    Returns:
        Sorted list of lumberjack names.
    """
    config = load_axe_config()
    return sorted(config.lumberjacks.keys())
