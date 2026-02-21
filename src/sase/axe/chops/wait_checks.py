"""Wait dependency resolution chop.

Scans all waiting.json markers across projects and resolves dependencies
by checking if named agents have completed. Writes ready.json when all
dependencies for a waiting agent are satisfied.
"""

import json
from pathlib import Path

from sase.agent_names import find_named_agent
from sase.axe.chop_registry import ChopContext, register_chop


@register_chop("wait_checks")
def run_wait_checks(ctx: ChopContext) -> None:
    """Resolve wait dependencies for blocked agents.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/waiting.json`` and
    checks whether each dependency (named agent) has a ``done.json``.
    When all dependencies are satisfied, writes ``ready.json`` to
    unblock the waiting agent.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

            waiting_path = artifact_dir / "waiting.json"
            if not waiting_path.exists():
                continue

            # Already resolved — skip
            ready_path = artifact_dir / "ready.json"
            if ready_path.exists():
                continue

            try:
                with open(waiting_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict):
                continue

            waiting_for = data.get("waiting_for", [])
            if not isinstance(waiting_for, list) or not waiting_for:
                continue

            # Check if all dependencies are done
            all_done = True
            for name in waiting_for:
                agent = find_named_agent(name)
                if agent is None or not agent.is_done:
                    all_done = False
                    break

            if all_done:
                cl_name = data.get("cl_name", "unknown")
                ctx.log_callback(
                    "wait_checks",
                    f"Dependencies satisfied for {cl_name}, "
                    f"waited on: {', '.join(waiting_for)}",
                )
                try:
                    with open(ready_path, "w", encoding="utf-8") as f:
                        json.dump(
                            {"resolved_deps": waiting_for},
                            f,
                            indent=2,
                        )
                except OSError:
                    pass
