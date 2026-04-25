"""Module-level metric singletons.

All variables start as stubs.  ``init_telemetry()`` replaces them with real
``prometheus_client`` objects when telemetry is enabled.

Consumers import from here::

    from sase.telemetry.metrics import AGENT_RUNS
    AGENT_RUNS.labels(llm_provider="claude", status="ok", workflow="").inc()
"""

from __future__ import annotations

from sase.telemetry._stubs import StubCounter, StubGauge, StubHistogram

# ---------------------------------------------------------------------------
# Agent Lifecycle
# ---------------------------------------------------------------------------
AGENT_RUNS: StubCounter = StubCounter()
AGENT_RUN_DURATION: StubHistogram = StubHistogram()
AGENT_ACTIVE: StubGauge = StubGauge()
AGENT_SPAWNS: StubCounter = StubCounter()
AGENT_KILLS: StubCounter = StubCounter()

# ---------------------------------------------------------------------------
# LLM Provider
# ---------------------------------------------------------------------------
LLM_INVOCATIONS: StubCounter = StubCounter()
LLM_INVOCATION_DURATION: StubHistogram = StubHistogram()
LLM_ERRORS: StubCounter = StubCounter()
LLM_RETRIES: StubCounter = StubCounter()
RETRY_SPAWNS_TOTAL: StubCounter = StubCounter()
LLM_INPUT_TOKENS: StubCounter = StubCounter()
LLM_OUTPUT_TOKENS: StubCounter = StubCounter()
LLM_CACHE_READ_TOKENS: StubCounter = StubCounter()

# ---------------------------------------------------------------------------
# Axe Orchestrator
# ---------------------------------------------------------------------------
AXE_CYCLES: StubCounter = StubCounter()
AXE_CYCLE_DURATION: StubHistogram = StubHistogram()
AXE_LUMBERJACKS_ACTIVE: StubGauge = StubGauge()
AXE_LUMBERJACK_RESTARTS: StubCounter = StubCounter()
AXE_ERRORS: StubCounter = StubCounter()

# ---------------------------------------------------------------------------
# Hooks / Mentors / Workflows
# ---------------------------------------------------------------------------
HOOK_EXECUTIONS: StubCounter = StubCounter()
HOOK_DURATION: StubHistogram = StubHistogram()
HOOK_RETRIES: StubCounter = StubCounter()
MENTOR_EXECUTIONS: StubCounter = StubCounter()
WORKFLOW_EXECUTIONS: StubCounter = StubCounter()
WORKFLOW_DURATION: StubHistogram = StubHistogram()
ZOMBIE_DETECTIONS: StubCounter = StubCounter()

# ---------------------------------------------------------------------------
# Beads
# ---------------------------------------------------------------------------
BEAD_OPERATIONS: StubCounter = StubCounter()
BEAD_STATUS_TRANSITIONS: StubCounter = StubCounter()
BEAD_ACTIVE: StubGauge = StubGauge()

# ---------------------------------------------------------------------------
# VCS / Workspace
# ---------------------------------------------------------------------------
VCS_COMMITS: StubCounter = StubCounter()
VCS_OPERATIONS: StubCounter = StubCounter()
WORKSPACE_ACQUISITIONS: StubCounter = StubCounter()
WORKSPACE_RELEASES: StubCounter = StubCounter()
WORKSPACE_ACTIVE: StubGauge = StubGauge()

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
NOTIFICATIONS_SENT: StubCounter = StubCounter()


# ---------------------------------------------------------------------------
# Metric definitions used by _registry.init_telemetry() to create real
# prometheus_client objects.  Each entry is (module_attr, kind, name,
# documentation, label_names, extra_kwargs).
# ---------------------------------------------------------------------------
METRIC_DEFS: list[tuple[str, str, str, str, list[str], dict]] = [
    # -- Agent Lifecycle --
    (
        "AGENT_RUNS",
        "counter",
        "sase_agent_runs_total",
        "Total agent runs",
        ["llm_provider", "status", "workflow"],
        {},
    ),
    (
        "AGENT_RUN_DURATION",
        "histogram",
        "sase_agent_run_duration_seconds",
        "Agent run duration",
        ["llm_provider", "workflow"],
        {"buckets": [10, 30, 60, 120, 300, 600, 1800, 3600]},
    ),
    (
        "AGENT_ACTIVE",
        "gauge",
        "sase_agent_active",
        "Currently active agents",
        ["llm_provider", "project"],
        {},
    ),
    (
        "AGENT_SPAWNS",
        "counter",
        "sase_agent_spawns_total",
        "Total agent spawns",
        ["llm_provider", "project"],
        {},
    ),
    (
        "AGENT_KILLS",
        "counter",
        "sase_agent_kills_total",
        "Total agent kills (reason=user for SIGTERM from TUI; reason=error for unhandled exceptions)",
        ["reason"],
        {},
    ),
    # -- LLM Provider --
    (
        "LLM_INVOCATIONS",
        "counter",
        "sase_llm_invocations_total",
        "Total LLM invocations",
        ["provider", "status"],
        {},
    ),
    (
        "LLM_INVOCATION_DURATION",
        "histogram",
        "sase_llm_invocation_duration_seconds",
        "LLM invocation duration",
        ["provider"],
        {},
    ),
    (
        "LLM_ERRORS",
        "counter",
        "sase_llm_errors_total",
        "Total LLM errors",
        ["provider", "error_type"],
        {},
    ),
    (
        "LLM_RETRIES",
        "counter",
        "sase_llm_retries_total",
        "Total LLM retries",
        ["provider"],
        {},
    ),
    (
        "RETRY_SPAWNS_TOTAL",
        "counter",
        "sase_llm_retry_spawns_total",
        "Total cross-process retry spawns (parent agent failed; spawned a fresh detached child to retry)",
        ["outcome"],
        {},
    ),
    (
        "LLM_INPUT_TOKENS",
        "counter",
        "sase_llm_input_tokens_total",
        "Total LLM input tokens",
        ["provider"],
        {},
    ),
    (
        "LLM_OUTPUT_TOKENS",
        "counter",
        "sase_llm_output_tokens_total",
        "Total LLM output tokens",
        ["provider"],
        {},
    ),
    (
        "LLM_CACHE_READ_TOKENS",
        "counter",
        "sase_llm_cache_read_tokens_total",
        "Total LLM cache read tokens",
        ["provider"],
        {},
    ),
    # -- Axe Orchestrator --
    (
        "AXE_CYCLES",
        "counter",
        "sase_axe_cycles_total",
        "Total axe cycles",
        ["cycle_type"],
        {},
    ),
    (
        "AXE_CYCLE_DURATION",
        "histogram",
        "sase_axe_cycle_duration_seconds",
        "Axe cycle duration",
        ["cycle_type"],
        {},
    ),
    (
        "AXE_LUMBERJACKS_ACTIVE",
        "gauge",
        "sase_axe_lumberjacks_active",
        "Currently active lumberjacks",
        [],
        {},
    ),
    (
        "AXE_LUMBERJACK_RESTARTS",
        "counter",
        "sase_axe_lumberjack_restarts_total",
        "Total lumberjack restarts",
        [],
        {},
    ),
    (
        "AXE_ERRORS",
        "counter",
        "sase_axe_errors_total",
        "Total axe errors",
        ["error_type"],
        {},
    ),
    # -- Hooks / Mentors / Workflows --
    (
        "HOOK_EXECUTIONS",
        "counter",
        "sase_hook_executions_total",
        "Total hook executions",
        ["hook_type", "status"],
        {},
    ),
    (
        "HOOK_DURATION",
        "histogram",
        "sase_hook_duration_seconds",
        "Hook execution duration",
        ["hook_type"],
        {},
    ),
    (
        "HOOK_RETRIES",
        "counter",
        "sase_hook_retries_total",
        "Total hook retries",
        ["hook_type"],
        {},
    ),
    (
        "MENTOR_EXECUTIONS",
        "counter",
        "sase_mentor_executions_total",
        "Total mentor executions",
        ["status"],
        {},
    ),
    (
        "WORKFLOW_EXECUTIONS",
        "counter",
        "sase_workflow_executions_total",
        "Total workflow executions",
        ["workflow", "status"],
        {},
    ),
    (
        "WORKFLOW_DURATION",
        "histogram",
        "sase_workflow_duration_seconds",
        "Workflow execution duration",
        ["workflow"],
        {},
    ),
    (
        "ZOMBIE_DETECTIONS",
        "counter",
        "sase_zombie_detections_total",
        "Total zombie detections",
        [],
        {},
    ),
    # -- Beads --
    (
        "BEAD_OPERATIONS",
        "counter",
        "sase_bead_operations_total",
        "Total bead operations",
        ["operation"],
        {},
    ),
    (
        "BEAD_STATUS_TRANSITIONS",
        "counter",
        "sase_bead_status_transitions_total",
        "Total bead status transitions",
        ["from_status", "to_status"],
        {},
    ),
    (
        "BEAD_ACTIVE",
        "gauge",
        "sase_bead_active",
        "Currently active beads",
        ["project", "status"],
        {},
    ),
    # -- VCS / Workspace --
    (
        "VCS_COMMITS",
        "counter",
        "sase_vcs_commits_total",
        "Total VCS commits",
        ["provider", "type"],
        {},
    ),
    (
        "VCS_OPERATIONS",
        "counter",
        "sase_vcs_operations_total",
        "Total VCS operations",
        ["provider", "operation", "status"],
        {},
    ),
    (
        "WORKSPACE_ACQUISITIONS",
        "counter",
        "sase_workspace_acquisitions_total",
        "Total workspace acquisitions",
        ["project"],
        {},
    ),
    (
        "WORKSPACE_RELEASES",
        "counter",
        "sase_workspace_releases_total",
        "Total workspace releases",
        ["project"],
        {},
    ),
    (
        "WORKSPACE_ACTIVE",
        "gauge",
        "sase_workspace_active",
        "Currently active workspaces",
        ["project"],
        {},
    ),
    # -- Notifications --
    (
        "NOTIFICATIONS_SENT",
        "counter",
        "sase_notifications_sent_total",
        "Total notifications sent",
        ["type", "status"],
        {},
    ),
]
