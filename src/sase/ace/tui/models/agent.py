"""Agent data model for the Agents tab."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.agent_identity_facade import AgentIdentitySnapshot, present_agent_name
from sase.core.paths import shorten_path
from sase.core.time import local_now
from sase.gate_shell.state import is_real_gate_member
from sase.monitor_state import is_monitor_member_role
from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    canonical_plan_chain_suffix,
)
from sase.project_display_names import humanize_cl_name

from ._agent_state import AgentState
from .agent_attempt import AttemptRecord, load_attempt_history
from .agent_source import agent_source
from .agent_time import (
    compute_row_runtime,
    format_compact_duration,
    format_wait_until,
    row_runtime_or_wait_ticks,
    should_display_runtime_suffix,
    wait_countdown_ticks,
    wait_display_agent,
    wait_remaining_seconds,
    wait_until_target_and_reference,
)
from .agent_types import AgentChildLinkage, AgentType, LinkedRepoMetadata

__all__ = [
    "Agent",
    "AgentChildLinkage",
    "AgentType",
    "AttemptRecord",
    "LinkedRepoMetadata",
    "agent_source",
    "compute_row_runtime",
    "format_compact_duration",
    "format_wait_until",
    "row_runtime_or_wait_ticks",
    "should_display_runtime_suffix",
    "wait_countdown_ticks",
    "wait_display_agent",
    "wait_remaining_seconds",
    "wait_until_target_and_reference",
    "load_attempt_history",
]


@dataclass
class Agent(AgentState):
    """Represents a single running agent."""

    def __post_init__(
        self, commit_entry_id: str | None = None
    ) -> None:  # legacy compatibility alias
        if commit_entry_id is not None and self.stitch_id is None:
            self.stitch_id = commit_entry_id
        self.refresh_raw_presented_agent_name()

    @property
    def is_family_root_entry(self) -> bool:
        """Whether this top-level row anchors a persisted agent family."""
        return not self.is_workflow_child and (
            self.plan_chain_root or self.agent_family_role == "root"
        )

    @property
    def is_family_container_row(self) -> bool:
        """Whether this root has at least one real agent-family member."""
        return self.is_family_root_entry and any(
            not child.is_synthetic_planner for child in self.followup_agents
        )

    @property
    def is_plan_family_root_entry(self) -> bool:
        """Whether this family root has plan-family projection semantics.

        True from root metadata recorded at promotion time (``plan_chain_root``
        or a ``--plan``-flavored ``role_suffix``), or from a plan chain the
        family entered later (``derived_plan_family_root``, set during status
        normalization when a promoted root's members reveal a plan chain that
        started after the root was promoted).
        """
        if not self.is_family_root_entry:
            return False
        if self.plan_chain_root:
            return True
        if self.derived_plan_family_root:
            return True
        suffix = canonical_plan_chain_suffix(self.role_suffix)
        return self.agent_family_role == "root" and bool(
            suffix == PLAN_CHAIN_PLAN_SUFFIX
            or (suffix and suffix.startswith(f"{PLAN_CHAIN_PLAN_SUFFIX}-"))
        )

    def family_reference_name(self) -> str | None:
        """Return the family-container name used by prompt references."""
        if not self.is_family_root_entry:
            return self.agent_name
        if self.agent_family:
            return self.agent_family
        if self.agent_name:
            return (
                agent_family_base(self.agent_name, include_legacy_dash=True)
                or self.agent_name
            )
        return None

    def presented_clan_reference_name(self) -> str | None:
        """Return the local-display clan identity without external reads."""
        raw_clan = self.agent_clan
        if not raw_clan:
            return None
        if self.is_clan_container:
            return self.presented_agent_name or raw_clan
        raw_name = self.agent_name or ""
        presented_name = self.presented_identity_name or raw_name
        prefix = f"{raw_clan}."
        if raw_name.startswith(prefix):
            suffix = raw_name[len(raw_clan) :]
            if suffix and presented_name.endswith(suffix):
                return presented_name[: -len(suffix)]
        return raw_clan

    def presented_family_reference_name(self) -> str | None:
        """Return the local-display family identity without external reads."""
        raw_family = self.agent_family
        if not raw_family:
            return self.presented_agent_name or self.family_reference_name()
        raw_name = self.agent_name or ""
        presented_name = self.presented_identity_name or raw_name
        if raw_name.startswith(raw_family):
            suffix = raw_name[len(raw_family) :]
            if suffix and presented_name.endswith(suffix):
                return presented_name[: -len(suffix)]
        if self.is_family_root_entry and presented_name:
            return presented_name
        return raw_family

    def refresh_raw_presented_agent_name(self) -> None:
        """Refresh the presentation source without config or selector I/O."""
        self.presented_identity_name = self.agent_name
        if self.is_family_root_entry:
            self.presented_agent_name = self.family_reference_name()
        elif self.is_clan_container and self.agent_clan:
            self.presented_agent_name = self.agent_clan
        else:
            self.presented_agent_name = self.agent_name

    def refresh_presented_agent_name(
        self,
        identity: AgentIdentitySnapshot | None = None,
    ) -> None:
        """Refresh the final local presentation from one identity snapshot."""
        snapshot = identity or AgentIdentitySnapshot.current()
        self.refresh_raw_presented_agent_name()
        if self.presented_agent_name:
            self.presented_agent_name = present_agent_name(
                self.presented_agent_name,
                snapshot,
            )
        if self.presented_identity_name:
            self.presented_identity_name = present_agent_name(
                self.presented_identity_name,
                snapshot,
            )
        self.waiting_for = [
            present_agent_name(name, snapshot) for name in self.waiting_for
        ]

    @property
    def effective_workspace_num(self) -> int | None:
        """Workspace number considering meta_workspace from step_output.

        Workflow step agents may store their workspace number in
        ``step_output["meta_workspace"]`` rather than in :attr:`workspace_num`.
        This property mirrors the display logic in ``_build_header_text``.
        """
        meta_ws = None
        if self.step_output and isinstance(self.step_output, dict):
            raw = self.step_output.get("meta_workspace")
            if raw is not None:
                try:
                    meta_ws = int(raw)
                except (ValueError, TypeError):
                    pass
        if meta_ws is not None:
            return meta_ws
        return self.workspace_num

    def get_display_type(self, *, is_expanded: bool = False) -> str:
        """Compute display type with optional fold-state context.

        When collapsed: always [agent].
        When expanded: [workflow] for anonymous, [<workflow_name>] for named.
        """
        if self.appears_as_agent:
            if not is_expanded:
                return "agent"
            if self.is_anonymous:
                return "workflow"
            return self.workflow if self.workflow else "agent"
        if self.is_gate:
            return "gate"
        if self.is_proc_shell:
            return "proc"
        if self.is_workflow_child and self.step_type:
            return self.step_type
        if self.agent_type == AgentType.RUNNING:
            return "agent"
        return "agent"

    @property
    def display_type(self) -> str:
        """Human-readable agent type for display (default: collapsed context)."""
        return self.get_display_type(is_expanded=False)

    @property
    def display_name(self) -> str:
        """Name to show in list display.

        Top-level workflow entries show the workflow name (e.g. "refresh_cl_desc")
        instead of the Patch name, since that's what the user cares about.
        """
        if self.is_clan_container and self.agent_clan:
            return self.presented_agent_name or self.agent_clan
        if self.is_proc_shell:
            return (
                self.proc_label
                or self.presented_agent_name
                or self.agent_name
                or self.proc_id
                or "proc shell"
            )
        if self.is_gate:
            return (
                self.gate_label
                or self.gate_kind
                or self.presented_agent_name
                or self.agent_name
                or self.gate_id
                or "gate shell"
            )
        if (
            self.agent_type == AgentType.WORKFLOW
            and not self.appears_as_agent
            and not self.is_workflow_child
            and self.workflow
        ):
            return self.workflow
        if self.is_project_agent and self.project_display_name:
            return self.project_display_name
        return humanize_cl_name(self.cl_name)

    @property
    def display_label(self) -> str:
        """Combined label for list display: Type + name."""
        return f"[{self.display_type}] {self.display_name}"

    @property
    def display_status(self) -> str:
        """Presentation status label."""
        return self.status

    @property
    def is_monitor(self) -> bool:
        """Whether this row is the monitor member, not the starter back-reference."""
        return is_monitor_member_role(self.agent_family_role, self.role_suffix)

    @property
    def is_gate(self) -> bool:
        """Whether this row is the durable gate-shell member."""
        return is_real_gate_member(self.agent_family_role, self.gate_id)

    @property
    def is_proc_shell(self) -> bool:
        """Whether this row projects one stand-alone durable proc shell."""
        return self.agent_type == AgentType.PROC_SHELL

    @property
    def start_time_display(self) -> str:
        """Formatted start time for display."""
        if self.start_time is None:
            return "Unknown"
        return self.start_time.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def timestamps_display(self) -> str:
        """Multi-timestamp display for the metadata panel.

        Each timestamp on its own line, with subsequent lines indented
        to align with the first (matching the width of ``Timestamps: ``).

        - START is the launch/artifact timestamp for agents that did not wait
        - WAIT replaces START once an agent enters a pre-run wait phase
        - RUN is the actual execution timestamp when known
        - DONE shown for completed agents
        """
        parts: list[str] = []
        fmt = "%Y-%m-%d %H:%M:%S"
        # Pad tag to 5 chars so timestamps align.
        tag_width = 5

        def _fmt(tag: str, ts: str, extra: str | None = None) -> str:
            line = f"{tag.ljust(tag_width)} | {ts}"
            if extra:
                line += f" | {extra}"
            return line

        first_tag = (
            "WAIT"
            if self.wait_start_time is not None or self.status in {"WAITING", "QUEUED"}
            else "START"
        )
        first_time = self.wait_start_time or self.start_time
        parts.append(
            _fmt(first_tag, first_time.strftime(fmt) if first_time else "Unknown")
        )
        if self.run_start_time is not None:
            parts.append(_fmt("RUN", self.run_start_time.strftime(fmt)))

        # Collect remaining timestamps and sort chronologically
        middle: list[tuple[datetime, str]] = []
        for pt in self.plan_times:
            middle.append((pt, "PLAN"))
        for ft in self.feedback_times:
            middle.append((ft, "FBACK"))
        for qt in self.questions_times:
            middle.append((qt, "QUEST"))
        for rt in self.retry_times:
            middle.append((rt, "RETRY"))
        if self.code_time is not None:
            middle.append((self.code_time, "CODE"))
        if self.epic_time is not None:
            middle.append((self.epic_time, "EPIC"))
        middle.sort(key=lambda t: t[0])
        for ts, tag in middle:
            extra = None
            if tag == "FBACK":
                path = self.feedback_plan_paths.get(ts)
                if path:
                    extra = shorten_path(path)
            parts.append(_fmt(tag, ts.strftime(fmt), extra))

        if self.stop_time is not None:
            parts.append(_fmt("DONE", self.stop_time.strftime(fmt)))

        # Indent subsequent lines by width of "Timestamps: " (12 chars)
        indent = " " * 12
        return ("\n" + indent).join(parts)

    @property
    def start_time_short(self) -> str:
        """Short formatted start time (HH:MM) for list display."""
        if self.start_time is None:
            return "?"
        return self.start_time.strftime("%H:%M")

    @property
    def start_time_compact(self) -> str:
        """Compact formatted start time (e.g. 'Apr 12 20:25') for sidebar use."""
        if self.start_time is None:
            return "?"
        return self.start_time.strftime("%b %d %H:%M")

    @property
    def duration_display(self) -> str:
        """Display how long the agent has been running."""
        if self.start_time is None:
            return "?"
        end = self.stop_time or local_now()
        delta = end - self.start_time
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h{minutes}m"
        elif minutes > 0:
            return f"{minutes}m{seconds}s"
        else:
            return f"{seconds}s"

    @property
    def all_files(self) -> list[str]:
        """All displayable file paths (diff + extras) for multi-file panel."""
        files: list[str] = []
        if self.diff_path:
            files.append(self.diff_path)
        files.extend(self.extra_files)
        return files

    @property
    def identity(self) -> tuple["AgentType", str, str | None]:
        """Unique identifier for this agent instance."""
        if self.is_clan_container and self.agent_clan:
            return (
                AgentType.RUNNING,
                f"clan:{self.agent_clan}",
                self.agent_clan_generation,
            )
        return (self.agent_type, self.cl_name, self.raw_suffix)

    @property
    def is_retry_attempt(self) -> bool:
        """True when this agent is a retry of an earlier failed attempt."""
        return self.retry_attempt > 0

    @property
    def is_retried_parent(self) -> bool:
        """True when this agent failed but was retried by a downstream child."""
        return self.retried_as_timestamp is not None

    @property
    def child_linkage(self) -> AgentChildLinkage:
        """Classify this row's parent linkage.

        Workflow steps carry ``parent_workflow`` and render as workflow
        children. Family members/follow-ups carry only ``parent_timestamp`` and
        render under the parent agent without being workflow steps.
        """
        if self.parent_workflow is not None:
            return AgentChildLinkage.WORKFLOW_STEP
        if self.parent_timestamp is not None:
            return AgentChildLinkage.FAMILY_MEMBER
        return AgentChildLinkage.ROOT

    @property
    def is_child_row(self) -> bool:
        """True when this row is any kind of child in the Agents tab."""
        return self.child_linkage is not AgentChildLinkage.ROOT

    @property
    def is_workflow_step_child(self) -> bool:
        """True when this row is a child step of a workflow row."""
        return self.child_linkage is AgentChildLinkage.WORKFLOW_STEP

    @property
    def is_family_member_child(self) -> bool:
        """True when this row is a family/follow-up child row."""
        return self.child_linkage is AgentChildLinkage.FAMILY_MEMBER

    @property
    def is_workflow_child(self) -> bool:
        """Historical alias for rows folded under another row.

        This remains true for both workflow-step children and family-member
        children so existing fold/navigation behavior is preserved. New code
        that needs the child kind should use :attr:`child_linkage`.
        """
        return self.is_child_row

    @property
    def is_agent_entry(self) -> bool:
        """Check if this entry represents an agent process (with tools support).

        Agent entries run an LLM agent and may have tool-call artifacts:
        RUNNING agents, plus WORKFLOW entries that appear as agents
        and workflow child steps of type ``agent``.
        """
        if self.is_clan_container:
            return False
        if self.is_monitor:
            return False
        if self.is_gate:
            return False
        if self.is_proc_shell:
            return False
        if self.agent_type == AgentType.RUNNING:
            return True
        if self.agent_type == AgentType.WORKFLOW:
            if self.appears_as_agent:
                return True
            if self.is_workflow_child and self.step_type == "agent":
                return True
        return False

    @property
    def is_project_agent(self) -> bool:
        """Check if this agent runs against a project (not a specific Patch)."""
        if self.is_clan_container:
            return False
        if not self.project_file:
            return False
        project_name = Path(self.project_file).parent.name
        return self.cl_name == project_name

    # --- Delegated to agent_artifacts module ---

    def get_artifacts_dir(self) -> str | None:
        """Get the artifacts directory path for this agent."""
        from sase.ace.tui.models.artifact_files import get_artifacts_dir

        return get_artifacts_dir(self)

    def extract_artifacts_timestamp(self) -> str | None:
        """Extract and convert timestamp from raw_suffix to artifacts format."""
        from sase.ace.tui.models.artifact_files import extract_artifacts_timestamp

        return extract_artifacts_timestamp(self)

    def get_raw_xprompt_content(self) -> str | None:
        """Get the raw xprompt content (before preprocessing/expansion)."""
        from sase.ace.tui.models.artifact_files import get_raw_xprompt_content

        return get_raw_xprompt_content(self)

    def get_live_reply_content(self) -> str | None:
        """Get the live reply content for running agents."""
        from sase.ace.tui.models.artifact_files import get_live_reply_content

        return get_live_reply_content(self)

    def get_timestamped_reply_chunks(self) -> list[tuple[str, str]] | None:
        """Load live reply split into timestamped chunks."""
        from sase.ace.tui.models.artifact_files import get_timestamped_reply_chunks

        return get_timestamped_reply_chunks(self)

    def get_response_content(self) -> str | None:
        """Get the response content for DONE agents."""
        from sase.ace.tui.models.artifact_files import get_response_content

        return get_response_content(self)

    def get_chat_response_content(self) -> str | None:
        """Get response content from agent_meta.json chat_path."""
        from sase.ace.tui.models.artifact_files import get_chat_response_content

        return get_chat_response_content(self)

    # --- Delegated to agent_bundle module ---

    def to_bundle_dict(self) -> dict[str, Any]:
        """Serialize this Agent to a dict for bundle persistence."""
        from sase.ace.tui.models.agent_bundle import to_bundle_dict

        return to_bundle_dict(self)

    @staticmethod
    def from_bundle_dict(data: dict[str, Any]) -> "Agent":
        """Reconstruct an Agent from a bundle dict."""
        from sase.ace.tui.models.agent_bundle import from_bundle_dict

        return from_bundle_dict(data)
