#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Scans all waiting.json markers across projects and resolves dependencies
by checking if named agents have completed. Writes ready.json when all
dependencies for a waiting agent are satisfied.
"""

import argparse
import json
from pathlib import Path

from sase.agent_names import find_named_agent
from sase.axe.chop_script_context import read_chop_context


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    read_chop_context(args.context)  # validate context file

    def log(message: str, style: str | None = None) -> None:
        print(message)

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

            # Already resolved -- skip
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
                log(
                    f"[wait_checks] Dependencies satisfied for {cl_name}, "
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


if __name__ == "__main__":
    main()
