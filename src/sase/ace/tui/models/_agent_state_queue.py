"""Model, workspace, and runner-queue fields for the Agents tab model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_types import LinkedRepoMetadata


@dataclass
class AgentStateQueueFields:
    """Provider, workspace, wait-directive, and runner-slot state for one row."""

    # Model name from %model directive (only when explicitly set)
    model: str | None = None

    # LLM provider name (e.g., "claude", "agy")
    llm_provider: str | None = None

    # Effective reasoning-effort level (e.g. "xhigh"), resolved from the
    # %effort/@effort directive or llm_provider.default_effort. Rendered as a
    # uniform suffix on the Model field across every provider.
    reasoning_effort: str | None = None

    # Bare launch-time alias recorded when %model:@<alias> was used. Rendered
    # as a provenance chip and never re-resolved at display time.
    model_alias: str | None = None

    # VCS provider display name (e.g., "GitHub", "Mercurial")
    vcs_provider: str | None = None

    # Resolved directory the agent ran in. This matters for directory-mode
    # agents where workspace_num is 0 and no RUNNING-field claim exists.
    workspace_dir: str | None = None

    # Linked repositories resolved at agent launch. Populated from
    # ``agent_meta.json["linked_repos"]`` during existing metadata enrichment.
    linked_repos: tuple[LinkedRepoMetadata, ...] = field(
        default_factory=tuple,
        compare=False,
    )

    # Agent name assigned via %id directive or manual TUI naming
    agent_name: str | None = None

    # Precomputed name used by the Agents-tab row annotation and detail header.
    # Session root rows present the bare container name while retaining their
    # concrete persisted member name in ``agent_name``.
    presented_agent_name: str | None = field(
        default=None,
        init=False,
        compare=False,
    )

    # Precomputed identity used for hood/neighbor relationships. Unlike
    # ``presented_agent_name``, this retains a concrete agent session member suffix;
    # only explicit prefixes belonging to the selected current owner are
    # removed during snapshot normalization.
    presented_identity_name: str | None = field(
        default=None,
        init=False,
        compare=False,
    )

    # Names this agent is waiting for (from %wait directives)
    waiting_for: list[str] = field(default_factory=list)

    # Bead IDs this agent is waiting to reach closed status.
    waiting_for_beads: list[str] = field(default_factory=list)

    # Hood names whose current members this agent is waiting for.
    waiting_for_hoods: list[str] = field(default_factory=list)

    # Duration wait in seconds (from %wait(time=5m) directive)
    wait_duration: float | None = None

    # Absolute time wait target as ISO 8601 string (from %wait(time=1430) directive)
    wait_until: str | None = None

    # Runner-slot wait metadata projected from waiting.json / agent_meta.json.
    # ``queue_capacity`` is the canonical authored budget; ``wait_runners`` is
    # the display alias kept in sync by :meth:`set_queue_capacity`. Occupied
    # capacity units and per-waiter admission limits are projected separately
    # from the snapshot below. ``queue_capacity_multiplier`` is the mutually
    # exclusive ``<M>x`` form; its presence means explicit.
    queue_capacity: int | None = None
    queue_capacity_multiplier: float | None = None
    queue_capacity_explicit: bool = False
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    wait_priority: int | None = None
    wait_priority_explicit: bool = False
    queue_weight: float | None = None
    queue_weight_explicit: bool = False
    queue_weight_invalid: bool = False
    queue_weight_error: str | None = None
    slot_requested_at: str | None = None
    held_by: str | None = None
    hold_expires_at: float | None = None

    # Snapshot-derived display context. These values are recomputed from the
    # already-loaded Agents refresh payload after full and artifact-delta
    # merges; rendering them never triggers another filesystem scan. Queue
    # position and size cover every live slot waiter in shared Rust display
    # order, even while the runner pool is full.
    runner_slots_in_use: int | None = None
    runner_occupied_capacity: float | None = None
    runner_effective_limit: float | None = None
    runner_admission_limit: float | None = None
    runner_slot_queue_position: int | None = None
    runner_slot_queue_size: int | None = None
    runner_capacity_blockers: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    # True while this row's own pending_question.json marker exists. Root rows
    # with this flag have yielded their runner slot; agent session status propagation
    # must not be used as a substitute because a child question remains exempt.
    runner_slot_yielded: bool = False

    # Explicit artifacts directory path (for workflow steps loaded from marker files)
    artifacts_dir: str | None = None

    # Embedded workflow name for steps within embedded workflows
    # (e.g., "git", "propose")
    embedded_workflow_name: str | None = None

    # Whether this is a pre-prompt step from an embedded workflow
    is_pre_prompt_step: bool = False

    # Whether this agent should be hidden by default (shown with '.' toggle)
    hidden: bool = False

    def set_queue_capacity(
        self,
        value: int | None,
        *,
        explicit: bool = False,
        multiplier: float | None = None,
    ) -> None:
        """Set canonical capacity and keep the wait_runners display alias in sync.

        Integer and multiplier forms are mutually exclusive: setting one
        clears the other. When both are supplied the integer wins, matching
        persisted compatibility reads.
        """
        if multiplier is not None and value is None:
            self.queue_capacity = None
            self.queue_capacity_explicit = explicit
            self.queue_capacity_multiplier = multiplier
            self.wait_runners = None
            self.wait_runners_explicit = False
            return
        self.queue_capacity = value
        self.queue_capacity_explicit = explicit
        self.queue_capacity_multiplier = None
        self.wait_runners = value
        self.wait_runners_explicit = explicit
