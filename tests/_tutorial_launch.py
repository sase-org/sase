"""Agent-launch polling helpers for the tutorial tests."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tests._tutorial_support import (
    APPEAR_TIMEOUT_SECONDS,
    WAIT_TIMEOUT_SECONDS,
    TutorialBlock,
    TutorialEnv,
    TutorialStepError,
    sase_binary,
)


@dataclass
class AgentListProbe:
    """One ``sase agent list -a -j`` invocation, including failures."""

    rows: list[dict[str, object]]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""


def _sase_home(tutorial: TutorialEnv) -> Path:
    raw = tutorial.env.get("SASE_HOME")
    if raw:
        return Path(raw)
    return tutorial.home / ".sase"


def _bounded_text(text: str, *, max_lines: int = 40, max_chars: int = 4000) -> str:
    if not text:
        return "(empty)"
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = ["...", *lines[-max_lines:]]
    clipped = "\n".join(lines)
    if len(clipped) > max_chars:
        return "..." + clipped[-max_chars:]
    return clipped


def _artifact_agent_names(tutorial: TutorialEnv) -> list[str]:
    """Return agent names recorded in ``agent_meta.json`` under the tutorial HOME."""
    names: list[str] = []
    seen: set[str] = set()
    projects = _sase_home(tutorial) / "projects"
    if not projects.is_dir():
        return names
    for meta in projects.rglob("agent_meta.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name")
        if not name or not isinstance(name, str) or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _artifact_dir_dump(tutorial: TutorialEnv, *, max_paths: int = 20) -> str:
    projects = _sase_home(tutorial) / "projects"
    if not projects.is_dir():
        return f"(no projects dir at {projects})"
    paths = sorted(projects.rglob("agent_meta.json"))
    if not paths:
        children = sorted(path.name for path in projects.iterdir())
        label = ", ".join(children) if children else "none"
        return f"(no agent_meta.json under {projects}; children: {label})"
    lines: list[str] = []
    for path in paths[:max_paths]:
        done = path.with_name("done.json").is_file()
        running = path.with_name("running.json").is_file()
        lines.append(f"  {path} done={done} running={running}")
    extra = len(paths) - max_paths
    if extra > 0:
        lines.append(f"  ... {extra} more")
    return "\n".join(lines)


def _list_agent_rows(tutorial: TutorialEnv) -> AgentListProbe:
    """List running and recently completed agents in the tutorial HOME."""
    binary = sase_binary()
    try:
        result = subprocess.run(
            [str(binary), "agent", "list", "-a", "-j"],
            cwd=str(tutorial.work),
            env=tutorial.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except OSError as exc:
        return AgentListProbe(rows=[], error=f"OSError: {exc}")
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return AgentListProbe(
            rows=[],
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            error="timed out after 60s",
        )
    rows: list[dict[str, object]] = []
    try:
        parsed = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return AgentListProbe(
            rows=[],
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            error=f"invalid JSON: {exc}",
        )
    if isinstance(parsed, list):
        rows = [row for row in parsed if isinstance(row, dict)]
    return AgentListProbe(
        rows=rows,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        error="" if result.returncode == 0 else f"exit {result.returncode}",
    )


def _new_agent_names(
    rows: list[dict[str, object]],
    *,
    known_names: frozenset[str],
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str) or not name or name in known_names or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def known_agent_names(tutorial: TutorialEnv) -> frozenset[str]:
    listed = _new_agent_names(_list_agent_rows(tutorial).rows, known_names=frozenset())
    return frozenset(listed) | frozenset(_artifact_agent_names(tutorial))


def _launch_diagnostics(
    tutorial: TutorialEnv,
    *,
    launch_result: subprocess.CompletedProcess[str] | None,
    probe: AgentListProbe,
    known_names: frozenset[str],
) -> str:
    parts: list[str] = []
    if launch_result is None:
        parts.append("sase run result: (not captured)")
    else:
        parts.append(f"sase run exit {launch_result.returncode}")
        parts.append("sase run stdout:")
        parts.append(_bounded_text(launch_result.stdout or ""))
        parts.append("sase run stderr:")
        parts.append(_bounded_text(launch_result.stderr or ""))
    if probe.error:
        parts.append(f"sase agent list -a error: {probe.error}")
    rc = "n/a" if probe.returncode is None else str(probe.returncode)
    parts.append(f"sase agent list -a exit {rc}")
    parts.append("sase agent list -a stdout:")
    parts.append(_bounded_text(probe.stdout))
    if probe.stderr.strip():
        parts.append("sase agent list -a stderr:")
        parts.append(_bounded_text(probe.stderr))
    listed = [
        f"{row.get('name')}:{row.get('status')}"
        for row in probe.rows
        if row.get("name")
    ]
    parts.append(f"listed agents: {listed or '(none)'}")
    parts.append(
        "known names before launch: "
        + (", ".join(sorted(known_names)) if known_names else "(none)")
    )
    disk_names = _artifact_agent_names(tutorial)
    parts.append(
        "artifact agent_meta names: "
        + (", ".join(disk_names) if disk_names else "(none)")
    )
    parts.append("artifact dirs:")
    parts.append(_artifact_dir_dump(tutorial))
    return "\n".join(parts)


def wait_for_launch(
    block: TutorialBlock,
    tutorial: TutorialEnv,
    *,
    launch_result: subprocess.CompletedProcess[str] | None = None,
    known_names: frozenset[str] = frozenset(),
) -> None:
    """Wait for a ``sase run`` block's agents to reach a terminal success.

    Fakey can finish between ``sase run`` returning and the first poll, and a
    just-spawned agent is ``STARTING`` before ``RUNNING``. Listing therefore
    includes recently completed agents, treats any new name as appeared, and
    falls back to ``agent_meta.json`` on disk when the listing index is stale.
    """
    deadline = time.monotonic() + APPEAR_TIMEOUT_SECONDS
    probe = AgentListProbe(rows=[])
    names: list[str] = []
    while True:
        probe = _list_agent_rows(tutorial)
        names = _new_agent_names(probe.rows, known_names=known_names)
        if not names:
            names = [
                name
                for name in _artifact_agent_names(tutorial)
                if name not in known_names
            ]
        if names or time.monotonic() >= deadline:
            break
        time.sleep(2)  # sase-test-wait: poll for agent registration
    if not names:
        raise TutorialStepError(
            block,
            detail="no agents appeared after `sase run` within 60s",
            output=_launch_diagnostics(
                tutorial,
                launch_result=launch_result,
                probe=probe,
                known_names=known_names,
            ),
        )
    binary = sase_binary()
    try:
        settled = subprocess.run(
            [str(binary), "agent", "wait", *names, "-t", "300", "-q"],
            cwd=str(tutorial.work),
            env=tutorial.env,
            capture_output=True,
            text=True,
            timeout=WAIT_TIMEOUT_SECONDS + 60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TutorialStepError(
            block,
            detail=f"timed out waiting 300s for agents {names}",
            output=_launch_diagnostics(
                tutorial,
                launch_result=launch_result,
                probe=probe,
                known_names=known_names,
            ),
        ) from exc
    output = (settled.stdout or "") + (settled.stderr or "")
    if settled.returncode != 0:
        raise TutorialStepError(
            block,
            detail=f"`sase agent wait` exited {settled.returncode}",
            output=output
            + "\n"
            + _launch_diagnostics(
                tutorial,
                launch_result=launch_result,
                probe=probe,
                known_names=known_names,
            ),
        )
