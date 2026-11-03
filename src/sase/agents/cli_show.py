"""``sase agent show`` — detail panel for a single agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.agent.names import find_named_agent
from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.llm_provider.model_label import append_model_field
from sase.project_display_names import (
    project_display_name_for,
    humanize_vcs_refs_in_text,
)


def handle_agents_show(args: argparse.Namespace) -> None:
    """Render a full detail panel for the named agent."""
    from sase.project_tags import ensure_project_tag_catalog

    ensure_project_tag_catalog()
    name: str = args.name
    agent = find_named_agent(name)
    if agent is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)

    artifacts_dir = Path(agent.artifacts_dir)
    meta = _read_json(artifacts_dir / "agent_meta.json")
    done = _read_json(artifacts_dir / "done.json") if agent.is_done else None

    body = Text()
    body.append("Name: ", style="bold")
    body.append(f"{name}\n")
    body.append("Status: ", style="bold")
    if agent.is_done:
        outcome = agent.outcome or "completed"
        if outcome == "hijacked":
            from sase.agent.hijack.core import agent_hijack_status_for_done_marker

            recovery = done.get("recovery") if done else None
            recovery_arg = recovery if isinstance(recovery, dict) else None
            status = (
                agent_hijack_status_for_done_marker(outcome, recovery_arg) or "HIJACKED"
            )
            body.append(f"{status}\n")
        else:
            body.append(f"DONE ({outcome})\n")
    else:
        body.append("RUNNING\n")
    body.append("Artifacts dir: ", style="bold")
    body.append(f"{artifacts_dir}\n")

    info = parse_agent_artifact_path(artifacts_dir)
    project = (
        info.project_name
        if info is not None
        else artifacts_dir.parent.parent.parent.name
    )
    body.append("Project: ", style="bold")
    body.append(f"{project_display_name_for(project)}\n")

    # Uniform ``Model: PROVIDER(model) @ <effort>`` shape shared with the ACE
    # TUI so the effective model/provider/reasoning-effort reads identically.
    append_model_field(
        body,
        _optional_str(meta.get("model")),
        _optional_str(meta.get("llm_provider")),
        _optional_str(meta.get("reasoning_effort")),
        _optional_str(meta.get("model_alias")),
    )
    _append_autonomy_section(body, meta)
    if meta.get("pid"):
        body.append("PID: ", style="bold")
        body.append(f"{meta['pid']}\n")

    if done:
        if done.get("finished_at"):
            body.append("Finished at: ", style="bold")
            body.append(f"{done['finished_at']}\n")
        if done.get("outcome"):
            body.append("Outcome: ", style="bold")
            body.append(f"{done['outcome']}\n")
        _append_hijack_section(body, agent, done)

    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    raw_prompt_path = resolve_raw_prompt_path(artifacts_dir)
    if raw_prompt_path is not None and raw_prompt_path.exists():
        try:
            prompt_text = raw_prompt_path.read_text(encoding="utf-8").strip()
        except OSError:
            prompt_text = "<failed to read prompt>"
        body.append("\nPrompt:\n", style="bold")
        try:
            from sase.project_tag_style import rich_text_with_project_tags

            body.append_text(
                rich_text_with_project_tags(
                    humanize_vcs_refs_in_text(prompt_text) + "\n"
                )
            )
        except Exception:
            body.append(humanize_vcs_refs_in_text(prompt_text) + "\n")

    if not agent.is_done:
        body.append("\nLive tail: ", style="bold")
        body.append(f"tail -f {artifacts_dir}/live_reply.md\n")

    Console().print(Panel(body, title=f"Agent: {name}", border_style="cyan"))


def _append_hijack_section(body: Text, agent: object, done: dict[str, object]) -> None:
    """Append the Hijack detail block for a hijacked run."""
    from sase.agent.hijack.custody import (
        ACTIVE_CUSTODY_STATES,
        format_diff_summary,
        record_for_agent,
    )

    artifacts_dir = str(getattr(agent, "artifacts_dir", "") or "")
    agent_name = getattr(agent, "name", None)
    record = record_for_agent(
        artifacts_dir=artifacts_dir or None,
        agent_name=agent_name if isinstance(agent_name, str) else None,
    )
    if record is None and done.get("outcome") != "hijacked":
        return
    body.append("\nHijack\n", style="bold")
    state = str((record or {}).get("state") or "settled")
    body.append("  State: ", style="bold")
    body.append(f"{state}\n")
    recovery = done.get("recovery")
    if isinstance(recovery, dict) and recovery.get("state"):
        body.append("  Recovery: ", style="bold")
        body.append(f"{recovery['state']}\n")
    if record is None:
        return
    hijack_id = record.get("hijack_id")
    if hijack_id:
        body.append("  Id: ", style="bold")
        body.append(f"{hijack_id}\n")
    summary = format_diff_summary(record)
    if summary:
        body.append("  Evidence: ", style="bold")
        body.append(f"{summary}\n")
    snapshots = record.get("snapshots") or []
    refs: list[str] = []
    if isinstance(snapshots, list):
        for entry in snapshots:
            if not isinstance(entry, dict):
                continue
            ref = str(entry.get("reference") or entry.get("fingerprint") or "")
            if ref:
                refs.append(ref)
    if refs:
        body.append("  Snapshots: ", style="bold")
        body.append(f"{', '.join(refs)}\n")
    if str(record.get("state") or "") in ACTIVE_CUSTODY_STATES:
        body.append("  Next: ", style="bold")
        body.append("recover in ACE (Enter on the HIJACKED row)\n")


def _append_autonomy_section(body: Text, meta: dict[str, object]) -> None:
    """Append the shared Autonomy section for one agent's live meta."""
    from sase.autonomy.cli_shared import autonomy_lines
    from sase.autonomy.record import read_record

    record = read_record(meta)
    if record is None:
        return
    body.append("\nAutonomy:\n", style="bold")
    body.append_text(autonomy_lines(record))
    body.append("\n")


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
