"""Agent metadata enrichment from `agent_meta.json` and prompt-step markers.

Both filesystem (`enrich_agent_from_meta`, `enrich_agent_from_prompt_markers`)
and snapshot/wire (`enrich_agent_from_meta_wire`,
`enrich_agent_from_prompt_markers_wire`) variants live here so they can stay
in lockstep — every field assignment in the wire variant mirrors the
filesystem variant.
"""

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from zoneinfo import ZoneInfo

from sase.core.agent_scan_wire import (
    AgentMetaWire,
    PromptStepMarkerWire,
    WaitingMarkerWire,
)
from sase.core.time import get_timezone

from ._json_cache import load_json_cached
from ..agent import Agent


@lru_cache(maxsize=1)
def _cached_timezone() -> ZoneInfo:
    return get_timezone()


def _parse_utc_to_eastern(iso_str: str) -> datetime:
    """Parse a UTC ISO 8601 timestamp and convert to Eastern time (naive)."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(_cached_timezone()).replace(tzinfo=None)


def enrich_agent_from_meta(agent: Agent, artifacts_dir: str | None) -> None:
    """Read agent_meta.json and populate model/vcs_provider fields.

    Args:
        agent: The Agent to enrich (modified in place).
        artifacts_dir: Path to the artifacts directory, or None.
    """
    if not artifacts_dir:
        return

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        data = load_json_cached(meta_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return

    if not isinstance(data, dict):
        return

    if data.get("model"):
        agent.model = data["model"]
    if data.get("llm_provider"):
        agent.llm_provider = data["llm_provider"]
    if data.get("vcs_provider"):
        agent.vcs_provider = data["vcs_provider"]
    if data.get("workspace_dir"):
        agent.workspace_dir = data["workspace_dir"]
    if data.get("name"):
        agent.agent_name = data["name"]
    if data.get("wait_for"):
        agent.waiting_for = data["wait_for"]
    if data.get("approve"):
        agent.approve = True
    if data.get("hidden"):
        agent.hidden = True
    if data.get("role_suffix"):
        agent.role_suffix = data["role_suffix"]
    if data.get("parent_timestamp") and agent.parent_timestamp is None:
        agent.parent_timestamp = data["parent_timestamp"]
    if data.get("workspace_num") is not None and agent.workspace_num is None:
        try:
            agent.workspace_num = int(data["workspace_num"])
        except (ValueError, TypeError):
            pass

    # Retry-chain lineage (spawn-on-retry)
    if data.get("retry_of_timestamp"):
        agent.retry_of_timestamp = data["retry_of_timestamp"]
    raw_retry_attempt = data.get("retry_attempt")
    if isinstance(raw_retry_attempt, int):
        agent.retry_attempt = raw_retry_attempt
    if data.get("retry_chain_root_timestamp"):
        agent.retry_chain_root_timestamp = data["retry_chain_root_timestamp"]
    if data.get("retried_as_timestamp"):
        agent.retried_as_timestamp = data["retried_as_timestamp"]
    if data.get("retry_terminal"):
        agent.retry_terminal = bool(data["retry_terminal"])
    if data.get("retry_error_category"):
        agent.retry_error_category = data["retry_error_category"]

    def _append_timestamp_field(
        raw_value: object,
        target: list[datetime],
    ) -> None:
        values: list[str] = []
        if isinstance(raw_value, str):
            values = [raw_value]
        elif isinstance(raw_value, list):
            values = [v for v in raw_value if isinstance(v, str)]
        for value in values:
            try:
                target.append(_parse_utc_to_eastern(value))
            except ValueError:
                continue

    # Parse plan_submitted_at (when plan was submitted for review)
    _append_timestamp_field(data.get("plan_submitted_at"), agent.plan_times)

    # Parse feedback_submitted_at (when feedback was given on the plan)
    _append_timestamp_field(data.get("feedback_submitted_at"), agent.feedback_times)

    # Parse questions_submitted_at (when agent submitted questions)
    _append_timestamp_field(data.get("questions_submitted_at"), agent.questions_times)

    # Parse retry_started_at (list of timestamps, one per retry/fallback)
    retry_started_at = data.get("retry_started_at")
    if isinstance(retry_started_at, list):
        for ts in retry_started_at:
            if isinstance(ts, str):
                try:
                    agent.retry_times.append(_parse_utc_to_eastern(ts))
                except ValueError:
                    pass

    # Parse run_started_at (actual start time after waiting period)
    run_started_at = data.get("run_started_at")
    if isinstance(run_started_at, str):
        try:
            agent.run_start_time = _parse_utc_to_eastern(run_started_at)
        except ValueError:
            pass

    # Parse stopped_at (completion time for DONE/FAILED agents)
    stopped_at = data.get("stopped_at")
    if isinstance(stopped_at, str):
        try:
            agent.stop_time = _parse_utc_to_eastern(stopped_at)
        except ValueError:
            pass

    # Check for waiting.json to set WAITING status (takes precedence over PLANNING
    # since the agent can't plan until its dependencies are resolved)
    waiting_path = Path(artifacts_dir) / "waiting.json"
    if waiting_path.exists() and agent.status == "RUNNING":
        agent.status = "WAITING"
        # waiting.json may contain an updated waiting_for list (e.g. from the TUI
        # "w" keymap), which takes precedence over agent_meta.json's wait_for.
        try:
            with open(waiting_path, encoding="utf-8") as f:
                waiting_data = json.load(f)
            if isinstance(waiting_data, dict):
                if waiting_data.get("waiting_for"):
                    agent.waiting_for = waiting_data["waiting_for"]
                # Read wait_duration from waiting.json (preferred source)
                raw_dur = waiting_data.get("wait_duration")
                if raw_dur is not None:
                    try:
                        agent.wait_duration = float(raw_dur)
                    except (ValueError, TypeError):
                        pass
                # Read wait_until from waiting.json
                raw_until = waiting_data.get("wait_until")
                if isinstance(raw_until, str) and raw_until:
                    agent.wait_until = raw_until
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: read wait_duration from agent_meta.json if not set from waiting.json
    if agent.wait_duration is None:
        raw_dur = data.get("wait_duration")
        if raw_dur is not None:
            try:
                agent.wait_duration = float(raw_dur)
            except (ValueError, TypeError):
                pass

    # Fallback: read wait_until from agent_meta.json if not set from waiting.json
    if agent.wait_until is None:
        raw_until = data.get("wait_until")
        if isinstance(raw_until, str) and raw_until:
            agent.wait_until = raw_until

    # Set PLANNING / PLAN APPROVED / PLAN COMMITTED / EPIC APPROVED status
    # for agents launched with %plan directive
    if data.get("plan") and agent.status == "RUNNING":
        if data.get("plan_approved"):
            plan_action = data.get("plan_action")
            if plan_action == "commit":
                agent.status = "PLAN COMMITTED"
            elif plan_action == "epic":
                agent.status = "EPIC APPROVED"
            else:
                agent.status = "PLAN APPROVED"
        else:
            agent.status = "PLANNING"


def enrich_agent_from_prompt_markers(agent: Agent, artifacts_dir: str) -> None:
    """Read prompt_step_*.json markers and populate meta_* fields on step_output.

    Args:
        agent: The Agent to enrich (modified in place).
        artifacts_dir: Path to the artifacts directory.
    """
    artifacts_path = Path(artifacts_dir)
    meta_fields: dict[str, str] = {}
    for marker_file in sorted(artifacts_path.glob("prompt_step_*.json")):
        try:
            data = load_json_cached(marker_file)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        output = data.get("output")
        if isinstance(output, dict):
            for k, v in output.items():
                if k.startswith("meta_") and v:
                    meta_fields[k] = str(v)
    if meta_fields:
        if agent.step_output is None:
            agent.step_output = {}
        agent.step_output.update(meta_fields)


def enrich_agent_from_meta_wire(
    agent: Agent,
    meta: AgentMetaWire | None,
    waiting: WaitingMarkerWire | None,
) -> None:
    """Snapshot-aware mirror of :func:`enrich_agent_from_meta`.

    Mirrors every field assignment performed by the filesystem-backed
    helper so callers using a snapshot get identical Agent state. When
    *meta* is ``None`` the function is a no-op (matching the original's
    early-return when ``agent_meta.json`` is missing or unreadable).
    """
    if meta is None:
        return

    if meta.model:
        agent.model = meta.model
    if meta.llm_provider:
        agent.llm_provider = meta.llm_provider
    if meta.vcs_provider:
        agent.vcs_provider = meta.vcs_provider
    if meta.workspace_dir:
        agent.workspace_dir = meta.workspace_dir
    if meta.name:
        agent.agent_name = meta.name
    if meta.wait_for:
        agent.waiting_for = list(meta.wait_for)
    if meta.approve:
        agent.approve = True
    if meta.hidden:
        agent.hidden = True
    if meta.role_suffix:
        agent.role_suffix = meta.role_suffix
    if meta.parent_timestamp and agent.parent_timestamp is None:
        agent.parent_timestamp = meta.parent_timestamp
    if meta.workspace_num is not None and agent.workspace_num is None:
        agent.workspace_num = meta.workspace_num

    if meta.retry_of_timestamp:
        agent.retry_of_timestamp = meta.retry_of_timestamp
    if meta.retry_attempt is not None:
        agent.retry_attempt = meta.retry_attempt
    if meta.retry_chain_root_timestamp:
        agent.retry_chain_root_timestamp = meta.retry_chain_root_timestamp
    if meta.retried_as_timestamp:
        agent.retried_as_timestamp = meta.retried_as_timestamp
    if meta.retry_terminal:
        agent.retry_terminal = True
    if meta.retry_error_category:
        agent.retry_error_category = meta.retry_error_category

    def _append(values: list[str], target: list[datetime]) -> None:
        for value in values:
            try:
                target.append(_parse_utc_to_eastern(value))
            except ValueError:
                continue

    _append(meta.plan_submitted_at, agent.plan_times)
    _append(meta.feedback_submitted_at, agent.feedback_times)
    _append(meta.questions_submitted_at, agent.questions_times)
    for ts in meta.retry_started_at:
        try:
            agent.retry_times.append(_parse_utc_to_eastern(ts))
        except ValueError:
            continue
    if meta.run_started_at:
        try:
            agent.run_start_time = _parse_utc_to_eastern(meta.run_started_at)
        except ValueError:
            pass
    if meta.stopped_at:
        try:
            agent.stop_time = _parse_utc_to_eastern(meta.stopped_at)
        except ValueError:
            pass

    # waiting.json overrides RUNNING → WAITING and updates wait fields.
    # The filesystem helper only consults waiting.json when agent_meta
    # was successfully read; mirror that gate by handling it after the
    # meta-driven assignments.
    if waiting is not None and agent.status == "RUNNING":
        agent.status = "WAITING"
        if waiting.waiting_for:
            agent.waiting_for = list(waiting.waiting_for)
        if waiting.wait_duration is not None:
            agent.wait_duration = waiting.wait_duration
        if waiting.wait_until:
            agent.wait_until = waiting.wait_until

    if agent.wait_duration is None and meta.wait_duration is not None:
        agent.wait_duration = meta.wait_duration
    if agent.wait_until is None and meta.wait_until:
        agent.wait_until = meta.wait_until

    if meta.plan and agent.status == "RUNNING":
        if meta.plan_approved:
            if meta.plan_action == "commit":
                agent.status = "PLAN COMMITTED"
            elif meta.plan_action == "epic":
                agent.status = "EPIC APPROVED"
            else:
                agent.status = "PLAN APPROVED"
        else:
            agent.status = "PLANNING"


def enrich_agent_from_prompt_markers_wire(
    agent: Agent,
    prompt_steps: list[PromptStepMarkerWire],
) -> None:
    """Snapshot-aware mirror of :func:`enrich_agent_from_prompt_markers`.

    Collects ``meta_*`` fields from each prompt step's ``output`` dict and
    merges them into ``agent.step_output``. Records in the snapshot are
    already sorted by ``file_name`` (matching the filesystem ``glob`` +
    ``sorted`` order) so iteration order is deterministic.
    """
    meta_fields: dict[str, str] = {}
    for step in prompt_steps:
        output = step.output
        if not isinstance(output, dict):
            continue
        for k, v in output.items():
            if k.startswith("meta_") and v:
                meta_fields[k] = str(v)
    if meta_fields:
        if agent.step_output is None:
            agent.step_output = {}
        agent.step_output.update(meta_fields)
