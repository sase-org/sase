"""Pure formatting for the contention sampler's log lines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tests._contention_sampler_common import BYTE_PEAKS, PRINT_LIMIT


def _gib(value: object) -> str:
    return f"{value / 2**30:.1f}G" if isinstance(value, int) else "?"


def _peak_text(key: str, value: object) -> str:
    is_bytes = key in BYTE_PEAKS or key.startswith("min_free_")
    return f"{key} {_gib(value) if is_bytes else value}"


def running_workers(
    workers: Mapping[int, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Workers inside a test, longest-running first."""
    running = [
        record
        for record in workers.values()
        if record.get("nodeid") and record.get("finished_at") is None
    ]
    return sorted(running, key=lambda record: record.get("started_at") or 0.0)


def _age(now: float, started: object) -> str:
    return f"{now - started:.0f}s" if isinstance(started, (int, float)) else "?"


def format_progress_text(progress: Mapping[str, Any] | None, now: float) -> str:
    if not progress:
        return "progress none yet"
    controller = progress.get("controller") or {}
    collection = controller.get("collection") or {}
    text = (
        f"{progress['repeat']} collected {collection.get('workers_finished', 0)}/"
        f"{controller.get('workers_configured', '?')} workers "
        f"({collection.get('items', 0)} items) tests {controller.get('finished', 0)}"
        f" done {controller.get('failed_reports', 0)} failed"
    )
    running = running_workers(progress.get("workers") or {})
    if running:
        oldest = running[0]
        text += (
            f" | {len(running)} in flight, oldest "
            f"{_age(now, oldest.get('started_at'))} {oldest.get('worker')} "
            f"{oldest.get('nodeid')}"
        )
    if progress.get("kill_count"):
        text += f" | {progress['kill_count']} hazardous kill call(s)"
    return text


def format_sample_text(record: Mapping[str, Any], peaks: Mapping[str, Any]) -> str:
    soak, memory = record["soak"], record["memory"]
    roles = soak["by_role"]
    cgroup = record["cgroup"] or {}
    pressure = record["pressure"]
    parts = [
        f" +{record['elapsed']:.0f}s soak {soak['procs']}p/{soak['threads']}t "
        f"rss {_gib(soak['rss'])} pss {_gib(soak['pss'])} swap "
        f"{_gib(soak['swap'])} majflt {soak['major_faults']}",
        ", ".join(
            f"{group['count']} {name} rss {_gib(group['rss'])} pss {_gib(group['pss'])}"
            for name, group in roles.items()
        ),
        f"host avail {_gib(memory.get('MemAvailable'))}/"
        f"{_gib(memory.get('MemTotal'))} swapfree {_gib(memory.get('SwapFree'))}/"
        f"{_gib(memory.get('SwapTotal'))} oom_kill +"
        f"{peaks.get('oom_kill_delta', '?')}",
        f"psi10 mem {pressure['memory'].get('some', '?')}/"
        f"{pressure['memory'].get('full', '?')} io {pressure['io'].get('full', '?')}"
        f" cpu {pressure['cpu'].get('some', '?')}",
        f"cgroup {_gib(cgroup.get('current'))}/{cgroup.get('max', '?')} "
        f"oom_kill {cgroup.get('events', {}).get('oom_kill', '?')}",
        "free "
        + " ".join(
            f"{label} {_gib(fs['free_bytes'])}/{fs['free_inodes']}i"
            for label, fs in record["filesystems"].items()
            if fs is not None
        ),
    ]
    if "scratch_usage" in record:
        usage = record["scratch_usage"]
        parts.append(
            f"scratch used {_gib(usage['bytes'])} in {usage['entries']} entries"
            + (" (truncated)" if usage["truncated"] else "")
        )
    parts.append(format_progress_text(record.get("progress"), record["at"]))
    return " | ".join(parts)


def format_signal_lines(record: Mapping[str, Any]) -> list[str]:
    where = "inside" if record["sender_in_soak"] else "outside"
    lines = [
        f" +{record['elapsed']:.0f}s {record['signal']} ({record['code']}) from pid "
        f"{record['sender_pid']} uid {record['sender_uid']}, {where} the soak tree "
        f"({record['soak_procs']} soak processes alive)"
    ]
    for item in record["sender_chain"]:
        if "comm" not in item:
            label = "exited before it could be read and was never sampled"
        else:
            worker = f" {item['worker']}" if item.get("worker") else ""
            label = f"{item['comm']} [{item['role']}{worker}]"
            if item.get("gone"):
                label += f" (exited; last sampled at +{item['last_seen_elapsed']:.0f}s)"
            label += f" {item.get('cmdline') or ''}"
        lines.append(f"   sender chain: {item['pid']} {label}")
    if record["sender_worker"]:
        worker = record["sender_worker"]
        lines.append(
            f"   sender's worker {worker.get('worker')} was running "
            f"{worker.get('nodeid')}"
        )
    for item in record["inflight"][:PRINT_LIMIT]:
        lines.append(
            f"   in flight: {item.get('worker')} pid {item.get('pid')} "
            f"{_age(record['at'], item.get('started_at'))} {item.get('nodeid')}"
        )
    for kill in record["kills"]:
        lines.append(
            f"   hazardous kill: {kill.get('worker')} {kill.get('call')} "
            f"({kill.get('reason')}) during {kill.get('nodeid')}"
        )
    return lines


def format_header_text(record: Mapping[str, Any], sampler_pid: int, out: object) -> str:
    memory = record["memory"]
    cgroup = record["cgroup"] or {}
    return (
        f" root pid {record['root_pid']}, sampler pid {sampler_pid} on cpus "
        f"{record['sampler_cpus']} (soak cpus {record['soak_cpus']}), python "
        f"{record['python']}, {record['cpu_count']} cpus, host mem "
        f"{_gib(memory.get('MemTotal'))} swap {_gib(memory.get('SwapTotal'))}, "
        f"cgroup {cgroup.get('path', '?')} max {cgroup.get('max', '?')}, "
        f"out {out}"
    )


def format_peaks_text(peaks: Mapping[str, Any]) -> str:
    return ", ".join(_peak_text(key, value) for key, value in sorted(peaks.items()))
