"""Prevent current agent-session surfaces from drifting back to family terminology."""

from __future__ import annotations

import re
from pathlib import Path


import pytest

pytestmark = pytest.mark.contract

_ROOT = Path(__file__).resolve().parents[1]

# Agent-family identifiers for the renamed concept. Bare ``family`` locals and
# unrelated meanings (model_family, vcs_family, RelationKind.FAMILY,
# font-family, target_family, familiar, ...) are out of scope here.
_FAMILY_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:agent_family[A-Za-z0-9_]*|AgentFamily[A-Za-z0-9_]*|"
    r"AGENT_FAMILY[A-Za-z0-9_]*|family_shell[A-Za-z0-9_]*|"
    r"FamilyShell[A-Za-z0-9_]*|family_attach[A-Za-z0-9_]*|"
    r"family_id[A-Za-z0-9_]*|family_name[A-Za-z0-9_]*|"
    r"family_role[A-Za-z0-9_]*|find_agent_family[A-Za-z0-9_]*)",
)

# Every exception below is one of: the canonical legacy-reader homes
# (plan_chain, core/wire), a legacy durable-data reader, the
# legacy_agent_family_syntax sunset-flag branch, the sidecar families/ redirect
# stubs, or the removed workflow-kind error.
# New exceptions must name an equally explicit migration boundary.
_FAMILY_IDENTIFIER_ALLOWLIST = {
    # Canonical legacy-key homes.
    Path("src/sase/plan_chain.py"),
    Path("src/sase/core/wire.py"),
    # Sunset-flag branch: definition, enforcement, and callers.
    Path("src/sase/agent/legacy_agent_family_syntax.py"),
    Path("src/sase/feature_flags/registry.py"),
    Path("src/sase/agent/_agent_session_attach_directives.py"),
    Path("src/sase/agent/_agent_session_attach_launch.py"),
    Path("src/sase/agent/_agent_session_attach_types.py"),
    Path("src/sase/agent/agent_session_attach.py"),
    Path("src/sase/agents/cli_search.py"),
    Path("src/sase/ace/tui/models/agent_live_query_engine.py"),
    Path("src/sase/ace/tui/models/agent_live_query_pushdown.py"),
    Path("src/sase/ace/tui/widgets/artifacts/agents_query.py"),
    Path("src/sase/llm_provider/continuation_budget_persistence.py"),
    Path("src/sase/main/parser_gate.py"),
    Path("src/sase/notification_gates/model_request.py"),
    Path("src/sase/notification_gates/model_shell.py"),
    Path("src/sase/xprompt/_directive_edit_identity.py"),
    Path("src/sase/config/sase.schema.json"),
    # Legacy durable-data and pre-contract wire readers.
    Path("src/sase/core/agent_scan_wire_conversion.py"),
    Path("src/sase/core/agent_cleanup_wire.py"),
    Path("src/sase/core/agent_hold_facade.py"),
    Path("src/sase/core/agent_identity_facade.py"),
    Path("src/sase/core/agent_launch_wire_from_dict.py"),
    Path("src/sase/core/runner_slots/_admission_predicates.py"),
    Path("src/sase/core/wait_dependency_resolution/_artifact_state.py"),
    Path("src/sase/core/wait_dependency_resolution/_index.py"),
    Path("src/sase/agent/launch_request_continuation.py"),
    Path("src/sase/agent/launch_request_followup.py"),
    Path("src/sase/agent/names/_registry_entries.py"),
    Path("src/sase/agents_sync/v2_validation.py"),
    Path("src/sase/ace/tui/models/_fleet_agents_identity.py"),
    Path("src/sase/ace/tui/models/_fleet_agents_nodes.py"),
    Path("src/sase/ace/tui/models/_fleet_agents_promotion.py"),
    Path("src/sase/ace/tui/models/_fleet_agents_rows.py"),
    Path("src/sase/ace/tui/models/agent_bundle.py"),
    Path("src/sase/ace/tui/widgets/_directive_completion_agents.py"),
    Path("src/sase/axe/run_agent_wait_slots.py"),
    Path("src/sase/dispatch/launch.py"),
    Path("src/sase/gate_shell/store.py"),
    Path("src/sase/integrations/_agent_list_entry_builder.py"),
    Path("src/sase/monitor/store.py"),
    Path("src/sase/scripts/_agent_chat_from_name_common.py"),
    Path("src/sase/shells/followup.py"),
    # Historical-data normalization (reads pre-rename inventory metadata).
    Path("src/sase/agents_sync/inventory.py"),
    # Sidecar families/ permanent-redirect stubs for historical footer links.
    Path("src/sase/sase_agent.py"),
    Path("src/sase/sdd/hosted_links.py"),
    Path("src/sase/agents_sync/rendering.py"),
    # Removed legacy workflow kind: rejected with a migration error.
    Path("src/sase/xprompt/workflow_loader_definition.py"),
    Path("src/sase/xprompt/workflow_loader.py"),
}

_STALE_PHRASES = (
    "agent family",
    "agent families",
    "FAMILY SHELLS",
    "family=",
    "kind:family",
    "--next-fork family",
    "<family>--",
    "families/",
)

# Intentional survivors: the one formerly-called clause, the historical
# families/ footer-link stubs, and the unrelated vcs_family example.
_STALE_PHRASE_ALLOWLIST = {
    ("docs/agent_sessions.md", "agent families"),
    ("docs/commit_workflows.md", "families/"),
    ("docs/agents_sidecar.md", "families/"),
    ("docs/plugins.md", "family="),
    ("sase/memory/glossary/sase-agent-session.md", "agent family"),
}

_STALE_PHRASE_SCOPES = (
    Path("docs"),
    Path("src/sase/xprompts"),
    Path("sase/memory"),
)


def test_current_source_avoids_agent_family_identifiers() -> None:
    findings: list[str] = []
    candidates = [
        *sorted((_ROOT / "src").rglob("*.py")),
        *sorted((_ROOT / "src").rglob("*.json")),
    ]
    for path in candidates:
        relative = path.relative_to(_ROOT)
        if relative in _FAMILY_IDENTIFIER_ALLOWLIST:
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _FAMILY_IDENTIFIER_RE.search(line):
                findings.append(f"{relative}:{line_number}: {line.strip()}")

    assert findings == []


def test_current_docs_skills_and_memory_avoid_stale_family_phrases() -> None:
    findings: list[str] = []
    for scope in _STALE_PHRASE_SCOPES:
        for path in sorted((_ROOT / scope).rglob("*.md")):
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
