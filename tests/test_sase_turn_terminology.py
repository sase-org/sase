"""Prevent current sase-turn surfaces from drifting back to shell terminology."""

from __future__ import annotations

import re
from pathlib import Path


import pytest

pytestmark = pytest.mark.contract

_ROOT = Path(__file__).resolve().parents[1]

# Shell-concept identifiers for the renamed concept. Unrelated meanings
# (``shell=True``, ``run_shell_command``, ``DetectedShell``,
# ``SUPPORTED_SHELLS``, login shells, ``shell_names`` plural vars holding
# Unix shell names, completion ``$SHELL`` handling, Artifacts-pane chrome,
# ...) are out of scope here; the ``shell_name``/``shell_kind`` arms use a
# trailing boundary so the Unix-shell ``shell_names`` plurals do not match.
_TURN_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:gate_shell[A-Za-z0-9_]*|GateShell[A-Za-z0-9_]*|"
    r"GATE_SHELL[A-Za-z0-9_]*|agent_session_shell[A-Za-z0-9_]*|"
    r"AgentSessionShell[A-Za-z0-9_]*|proc_shell[A-Za-z0-9_]*|"
    r"ProcShell[A-Za-z0-9_]*|PROC_SHELL[A-Za-z0-9_]*|"
    r"plan_shell[A-Za-z0-9_]*|question_shell[A-Za-z0-9_]*|"
    r"monitor_shell[A-Za-z0-9_]*|shell_name(?![A-Za-z0-9])|"
    r"shell_kind(?![A-Za-z0-9])|shell_member[A-Za-z0-9_]*|"
    r"shell_followup[A-Za-z0-9_]*|ShellFollowup[A-Za-z0-9_]*|"
    r"SHELL_FOLLOWUP[A-Za-z0-9_]*|SHELL_MEMBER[A-Za-z0-9_]*|"
    r"launch_shell_followup|resolve_shell_next_action|"
    r"normalize_gate_shell_bool_args|_requested_shell_names|"
    r"pending-shell-followup|sase\.shells|sase/shells)",
)

# Every exception below is one of: the canonical legacy-key homes
# (plan_chain, core/wire), a legacy durable-data or pre-contract wire
# reader, a dual-core binding fallback that works against both the old and
# the new core, the legacy_sase_shell_syntax sunset-flag branch, Unix-shell
# handling (completion install targets) whose ``shell_name`` helper is an
# unrelated meaning, or the deferred follow-up rename cluster
# (turns/gate_turn/monitor follow-up helpers and the wait-dependency
# shell-member/shell-followup names; see the audit-deploy PROPOSED
# FOLLOW-UP note on bead sase-1ab.9).
# New exceptions must name an equally explicit migration boundary.
_TURN_IDENTIFIER_ALLOWLIST = {
    # Canonical legacy-key homes.
    Path("src/sase/plan_chain.py"),
    Path("src/sase/core/wire.py"),
    # Sunset-flag branch: definition, enforcement, and callers.
    Path("src/sase/agent/legacy_sase_shell_syntax.py"),
    Path("src/sase/main/gate_handler.py"),
    Path("src/sase/main/proc_handler.py"),
    # Legacy durable-data and pre-contract wire readers.
    Path("src/sase/core/agent_launch_wire_from_dict.py"),
    Path("src/sase/core/agent_scan_wire_conversion.py"),
    Path("src/sase/core/agent_scan_wire_markers.py"),
    Path("src/sase/core/runner_slots/_admission_capacity_records.py"),
    Path("src/sase/core/wait_dependency_resolution/_artifact_state.py"),
    Path("src/sase/core/wait_dependency_resolution/_index.py"),
    Path("src/sase/core/wait_dependency_resolution/_index_entities.py"),
    Path("src/sase/core/wait_dependency_resolution/_types.py"),
    Path("src/sase/agent/launch_preview.py"),
    Path("src/sase/agent/launch_hold_preview.py"),
    Path("src/sase/agent/launch_proc_runtime.py"),
    Path("src/sase/agent/launch_admission_runtime.py"),
    Path("src/sase/gate_turn/store.py"),
    Path("src/sase/monitor/store.py"),
    Path("src/sase/history/chat_fork/proc.py"),
    Path("src/sase/scripts/_fork_proc_sources.py"),
    Path("src/sase/integrations/_editor_helper_agents.py"),
    Path("src/sase/notification_gates/cli_show.py"),
    Path("src/sase/plan_gate_turn/create.py"),
    Path("src/sase/procs/__init__.py"),
    Path("src/sase/procs/models/__init__.py"),
    Path("src/sase/procs/models/common.py"),
    Path("src/sase/procs/models/operations.py"),
    Path("src/sase/procs/models/proc.py"),
    Path("src/sase/procs/request.py"),
    Path("src/sase/procs/runner.py"),
    Path("src/sase/procs/store.py"),
    Path("src/sase/turns/member.py"),
    # Dual-core binding fallbacks (old core exposes only the legacy name).
    Path("src/sase/core/agent_launch_facade.py"),
    Path("src/sase/core/agent_scan_facade.py"),
    # Unix-shell handling: unrelated meaning (login-shell basenames).
    Path("src/sase/completion/install_targets.py"),
    # Deferred follow-up rename cluster (see bead sase-1ab.9 notes).
    Path("src/sase/turns/followup.py"),
    Path("src/sase/gate_turn/followup.py"),
    Path("src/sase/gate_turn/followup_policy.py"),
    Path("src/sase/gate_turn/kind_next_action.py"),
    Path("src/sase/monitor/followup.py"),
    # Cluster mirror comment (references SUCCESSFUL_SHELL_FOLLOWUP_OUTCOMES).
    Path("src/sase/monitor_state.py"),
}

_STALE_PHRASES = (
    "sase shell",
    "sase shells",
    "agent shell",
    "agent shells",
    "gate shell",
    "gate shells",
    "proc shell",
    "proc shells",
    "monitor shell",
    "monitor shells",
    "session shell",
    "session shells",
    "SESSION SHELLS",
    "AGENT SHELL",
    "PROC SHELL",
    "--next-fork shell",
    '"fork": "shell"',
    "gate.shell.",
    "gate_shell_reclaim",
)

# Intentional survivors: the formerly-called bridge clauses in the renamed
# glossary strands. Decision records stay verbatim (immutable history) and
# are out of scope here.
_STALE_PHRASE_ALLOWLIST = {
    ("sase/memory/glossary/sase-turn.md", "sase shell"),
    ("sase/memory/glossary/agent-turn.md", "agent shell"),
    ("sase/memory/glossary/gate-turn.md", "gate shell"),
    ("sase/memory/glossary/named-proc.md", "proc shell"),
}

_STALE_PHRASE_SCOPES = (
    Path("docs"),
    Path("src/sase/xprompts"),
    Path("sase/memory"),
)


def test_current_source_avoids_shell_concept_identifiers() -> None:
    findings: list[str] = []
    candidates = [
        *sorted((_ROOT / "src").rglob("*.py")),
        *sorted((_ROOT / "src").rglob("*.json")),
    ]
    for path in candidates:
        relative = path.relative_to(_ROOT)
        if relative in _TURN_IDENTIFIER_ALLOWLIST:
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _TURN_IDENTIFIER_RE.search(line):
                findings.append(f"{relative}:{line_number}: {line.strip()}")

    assert findings == []


def test_current_docs_skills_and_memory_avoid_stale_shell_phrases() -> None:
    findings: list[str] = []
    for scope in _STALE_PHRASE_SCOPES:
        for path in sorted((_ROOT / scope).rglob("*.md")):
            relative = path.relative_to(_ROOT)
            # Accepted decision records are immutable history and keep the
            # old word on purpose (bridged by the Gate Turn strand).
            if relative.parts[:3] == ("sase", "memory", "decisions"):
                continue
            content = path.read_text(encoding="utf-8")
            for phrase in _STALE_PHRASES:
                if (
                    phrase in content
                    and (
                        relative.as_posix(),
                        phrase,
                    )
                    not in _STALE_PHRASE_ALLOWLIST
                ):
                    findings.append(f"{relative}: {phrase}")
        yml_paths = (
            sorted((_ROOT / scope).rglob("*.yml"))
            if scope == Path("src/sase/xprompts")
            else []
        )
        for path in yml_paths:
            relative = path.relative_to(_ROOT)
            content = path.read_text(encoding="utf-8")
            for phrase in _STALE_PHRASES:
                if (
                    phrase in content
                    and (
                        relative.as_posix(),
                        phrase,
                    )
                    not in _STALE_PHRASE_ALLOWLIST
                ):
                    findings.append(f"{relative}: {phrase}")

    assert findings == []
