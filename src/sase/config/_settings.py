"""Validated accessors for individual values held in the merged config.

Each accessor projects one merged-config value into a typed Python result and
falls back to the package default when the value is missing or malformed: a
hand-edited ``~/.config/sase/sase.yml`` must never turn a routine command into
a traceback.  Accessors that run on formatting or scheduling paths widen that
to catching load failures outright, which each one notes.

Reads go through :mod:`sase.config.core` rather than binding
``load_merged_config`` at import time so the facade keeps owning the cache and
remains the single patch point every accessor here honors.
"""

from __future__ import annotations

from typing import Any

from sase.markdown_width import DEFAULT_MARKDOWN_PRINT_WIDTH
from sase.markdown_wrap import MIN_PROSE_WRAP_WIDTH


DEFAULT_MAX_RUNNING_AGENTS = 10
DEFAULT_MAX_AGENT_PIPE_CHAIN = 8
DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP = 3
DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS = 60
DEFAULT_PROC_HISTORY_LIMIT = 100
DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT = 50
DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN = 20
DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES = 1024 * 1024 * 1024
DEFAULT_ARTIFACT_RETENTION_ENABLED = False
DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL = 3
DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS = 90
DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS = 14
DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS = 3600


def _merged_config() -> dict[str, Any]:
    """Return the effective config through the ``sase.config.core`` facade.

    The import is deferred because ``core`` imports this module at load time.
    """
    from sase.config.core import load_merged_config

    return load_merged_config()


def get_use_chezmoi() -> bool:
    """Return whether chezmoi path remapping is enabled."""
    return bool(_merged_config().get("use_chezmoi", False))


def get_configured_max_running_agents() -> int:
    """Return the validated configured global runner limit.

    The merged-config cache lets admission callers poll this accessor without
    reparsing unchanged YAML while still observing live edits.
    """
    value = _merged_config().get("max_running_agents", DEFAULT_MAX_RUNNING_AGENTS)
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_MAX_RUNNING_AGENTS


def get_max_agent_pipe_chain() -> int:
    """Return the configured ``sase pipe`` family-chain bound.

    The original agent is depth 0. A pipe is refused when the next link
    would exceed this value. Malformed configuration falls back to the
    package default rather than allowing an unbounded chain.
    """
    value = _merged_config().get("max_agent_pipe_chain", DEFAULT_MAX_AGENT_PIPE_CHAIN)
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_MAX_AGENT_PIPE_CHAIN


def get_runner_slot_deference_seconds_per_step() -> int:
    """Return the configured per-priority-step delay, falling back on errors.

    Unlike the effective runner limit, deference is a politeness optimization:
    malformed or unavailable configuration must never strand a runner.
    """
    try:
        runner_slots = _merged_config().get("runner_slots", {})
    except Exception:  # noqa: BLE001 - deference configuration is fail-open.
        return DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP
    value = (
        runner_slots.get(
            "deference_seconds_per_step",
            DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP,
        )
        if isinstance(runner_slots, dict)
        else DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_RUNNER_SLOT_DEFERENCE_SECONDS_PER_STEP


def get_runner_slot_deference_max_seconds() -> int:
    """Return the configured deference cap, falling back on errors.

    Unlike the effective runner limit, deference is a politeness optimization:
    malformed or unavailable configuration must never strand a runner.
    """
    try:
        runner_slots = _merged_config().get("runner_slots", {})
    except Exception:  # noqa: BLE001 - deference configuration is fail-open.
        return DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS
    value = (
        runner_slots.get(
            "deference_max_seconds",
            DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS,
        )
        if isinstance(runner_slots, dict)
        else DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_RUNNER_SLOT_DEFERENCE_MAX_SECONDS


def get_proc_history_limit() -> int:
    """Return the validated configured finished-proc retention limit."""
    merged = _merged_config()
    procs = merged.get("procs", {})
    if isinstance(procs, dict) and "history_limit" in procs:
        value = procs["history_limit"]
    else:
        tasks = merged.get("tasks", {})
        value = (
            tasks.get("history_limit", DEFAULT_PROC_HISTORY_LIMIT)
            if isinstance(tasks, dict)
            else DEFAULT_PROC_HISTORY_LIMIT
        )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_PROC_HISTORY_LIMIT


# Legacy accessor alias; retire after every caller moves to the proc spelling.
get_task_history_limit = get_proc_history_limit


def get_markdown_print_width() -> int:
    """Return the validated configured Markdown prose width.

    Formatting must never hard-fail: a malformed ``~/.config/sase/sase.yml``
    turning ``sase plan propose`` into a traceback would be far worse than
    wrapping at the shipped default, so this accessor is fail-open.
    """
    try:
        markdown = _merged_config().get("markdown", {})
    except Exception:  # noqa: BLE001 - prose width is fail-open.
        return DEFAULT_MARKDOWN_PRINT_WIDTH
    value = (
        markdown.get("print_width", DEFAULT_MARKDOWN_PRINT_WIDTH)
        if isinstance(markdown, dict)
        else DEFAULT_MARKDOWN_PRINT_WIDTH
    )
    # Below ``MIN_PROSE_WRAP_WIDTH`` ``wrap_markdown()`` silently returns text
    # unwrapped, so the floor is the schema's ``minimum`` too.
    if type(value) is int and value >= MIN_PROSE_WRAP_WIDTH:
        return value
    return DEFAULT_MARKDOWN_PRINT_WIDTH


def _artifact_capture_config() -> dict[str, Any]:
    artifacts = _merged_config().get("artifacts", {})
    capture = artifacts.get("capture", {}) if isinstance(artifacts, dict) else {}
    return capture if isinstance(capture, dict) else {}


def get_artifact_capture_max_stored_per_agent() -> int:
    """Return the validated per-run automatic artifact byte-copy cap."""
    value = _artifact_capture_config().get(
        "max_stored_per_agent",
        DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_MAX_STORED_PER_AGENT


def get_artifact_capture_max_history_scan() -> int:
    """Return the validated VCS history-search bound for artifact capture."""
    value = _artifact_capture_config().get(
        "max_history_scan",
        DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_MAX_HISTORY_SCAN


def get_artifact_capture_max_file_size_bytes() -> int:
    """Return the maximum size of one pooled prompt artifact."""
    value = _artifact_capture_config().get(
        "max_file_size_bytes",
        DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_MAX_FILE_SIZE_BYTES


def get_artifact_capture_pool_max_bytes() -> int:
    """Return the workspace-local prompt-artifact pool budget."""
    value = _artifact_capture_config().get(
        "pool_max_bytes",
        DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES,
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_ARTIFACT_CAPTURE_POOL_MAX_BYTES


def _artifact_retention_config() -> dict[str, Any]:
    artifacts = _merged_config().get("artifacts", {})
    retention = artifacts.get("retention", {}) if isinstance(artifacts, dict) else {}
    return retention if isinstance(retention, dict) else {}


def get_artifact_retention_enabled() -> bool:
    """Return whether automatic artifact retention is enabled."""
    value = _artifact_retention_config().get(
        "enabled",
        DEFAULT_ARTIFACT_RETENTION_ENABLED,
    )
    if type(value) is bool:
        return value
    return DEFAULT_ARTIFACT_RETENTION_ENABLED


def get_artifact_retention_keep_per_label() -> int:
    """Return the validated automatic artifact generations kept per label."""
    value = _artifact_retention_config().get(
        "keep_per_label",
        DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_ARTIFACT_RETENTION_KEEP_PER_LABEL


def get_artifact_retention_max_age_days() -> int:
    """Return the validated automatic artifact age bound in days."""
    value = _artifact_retention_config().get(
        "max_age_days",
        DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_ARTIFACT_RETENTION_MAX_AGE_DAYS


def get_artifact_retention_trash_grace_days() -> int:
    """Return the validated artifact trash grace period in days."""
    value = _artifact_retention_config().get(
        "trash_grace_days",
        DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS,
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_ARTIFACT_RETENTION_TRASH_GRACE_DAYS


def get_gate_shell_reclaim_grace_seconds() -> int:
    """Return the grace period before a missed gate-shell deadline is lost."""
    try:
        gate = _merged_config().get("gate", {})
    except Exception:  # noqa: BLE001 - maintenance cleanup should fail open.
        return DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS
    shell = gate.get("shell", {}) if isinstance(gate, dict) else {}
    value = (
        shell.get(
            "reclaim_grace_seconds",
            DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS,
        )
        if isinstance(shell, dict)
        else DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS
    )
    if type(value) is int and value >= 0:
        return value
    return DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS
