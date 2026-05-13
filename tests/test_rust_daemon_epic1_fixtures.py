"""Epic 1 daemon fixture corpus validation.

These tests prove the committed source-store fixtures are readable by the
current direct loaders. They intentionally do not implement or route through
daemon behavior.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from sase.core import bead_read_facade, parser_facade
from sase.core.agent_artifact_facade import read_explicit_agent_artifact_index
from sase.core.agent_scan_facade import (
    AgentArtifactScanOptionsWire,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import agent_scan_wire_to_json_dict
from sase.core.notification_store_facade import read_notifications_snapshot
from sase.core.notification_store_wire import notification_store_wire_to_json_dict
from sase.notifications import pending_actions
from sase.xprompt.loader_sources import load_xprompt_from_file


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rust_daemon_epic1"
SOURCES = FIXTURE_ROOT / "sources"
EXPECTED = FIXTURE_ROOT / "expected"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _expected(name: str) -> Any:
    return _read_json(EXPECTED / name)


def _count(value: object) -> int:
    return len(value or [])  # type: ignore[arg-type]


def test_manifest_paths_exist_and_records_intentional_gaps() -> None:
    manifest = _read_json(FIXTURE_ROOT / "manifest.json")

    family_ids = {family["id"] for family in manifest["families"]}
    assert {
        "changespec_sase",
        "changespec_legacy_gp",
        "notifications",
        "pending_actions",
        "agent_artifacts",
        "explicit_artifacts",
        "dismissed_state",
        "dismissed_bundles",
        "beads",
        "sdd_documents",
        "workflow_state",
        "xprompt_catalogs",
        "history",
        "axe_state",
        "mobile_bridge",
        "editor_helpers",
        "largeish",
    } <= family_ids

    for family in manifest["families"]:
        for rel_path in family["source_paths"]:
            assert (FIXTURE_ROOT / rel_path).exists(), rel_path
        for rel_path in family["expected_snapshot_paths"]:
            assert (FIXTURE_ROOT / rel_path).exists(), rel_path

    missing_ids = {item["id"] for item in manifest["missing"]}
    assert missing_ids == {
        "plugin_execution",
        "provider_subprocesses",
        "vcs_provider_side_effects",
    }


def test_changespec_fixtures_parse_to_expected_snapshot() -> None:
    actual = []
    for name in ("demo.sase", "demo-archive.sase", "legacy.gp", "legacy-archive.gp"):
        path = SOURCES / "changespec" / name
        specs = parser_facade.parse_project_file(str(path))
        actual.append(
            {
                "path": f"sources/changespec/{name}",
                "specs": [
                    {
                        "bug": spec.bug,
                        "cl": spec.cl,
                        "comments": _count(spec.comments),
                        "commits": _count(spec.commits),
                        "deltas": _count(spec.deltas),
                        "hooks": _count(spec.hooks),
                        "mentors": _count(spec.mentors),
                        "name": spec.name,
                        "parent": spec.parent,
                        "status": spec.status,
                    }
                    for spec in specs
                ],
            }
        )

    assert actual == _expected("changespec_snapshot.json")


def test_notification_and_pending_action_fixtures_load_to_expected_snapshots(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    notification_path = tmp_path / "notifications.jsonl"
    shutil.copyfile(
        SOURCES / "notifications" / "notifications.jsonl", notification_path
    )
    snapshot = notification_store_wire_to_json_dict(
        read_notifications_snapshot(notification_path, include_dismissed=True)
    )
    notifications = snapshot["notifications"]
    actual_notifications = {
        "ids": [row["id"] for row in notifications],
        "state_counts": {
            "action_backed": sum(1 for row in notifications if row.get("action")),
            "dismissed": sum(1 for row in notifications if row.get("dismissed")),
            "muted": sum(1 for row in notifications if row.get("muted")),
            "read": sum(1 for row in notifications if row.get("read")),
            "snoozed": sum(1 for row in notifications if row.get("snooze_until")),
            "unread": sum(1 for row in notifications if not row.get("read")),
        },
        "stats": snapshot["stats"],
    }
    assert actual_notifications == _expected("notifications_snapshot.json")

    monkeypatch.setattr(
        pending_actions,
        "PENDING_ACTIONS_PATH",
        SOURCES / "pending_actions" / "current" / "actions.json",
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        SOURCES / "pending_actions" / "legacy" / "pending_actions.json",
    )
    store = pending_actions._load_store(include_legacy=True)
    actual_pending = {
        "prefixes": sorted(store["actions"]),
        "states": {
            key: value["state"] for key, value in sorted(store["actions"].items())
        },
        "transports": {
            key: [item["transport"] for item in value.get("transports", [])]
            for key, value in sorted(store["actions"].items())
        },
    }
    assert actual_pending == _expected("pending_actions_snapshot.json")


def test_agent_artifact_and_explicit_artifact_fixtures_match_snapshots(
    tmp_path: Path,
) -> None:
    options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=True,
        include_done_markers=True,
        include_workflow_state=True,
        include_waiting=True,
    )
    scan = agent_scan_wire_to_json_dict(
        scan_agent_artifacts(SOURCES / "agent_artifacts" / "projects", options)
    )

    def status(row: dict[str, Any]) -> str:
        if row.get("done"):
            return str(row["done"].get("outcome"))
        if row.get("waiting"):
            return "waiting"
        if row.get("running"):
            return "running"
        if row.get("workflow_state"):
            return str(row["workflow_state"].get("status"))
        return "unknown"

    actual_scan = {
        "records": [
            {
                "agent_name": (row.get("agent_meta") or {}).get("name")
                or (row.get("workflow_state") or {}).get("workflow_name"),
                "has_done": row.get("done") is not None,
                "has_waiting": row.get("waiting") is not None,
                "has_workflow_state": row.get("workflow_state") is not None,
                "prompt_steps": len(row.get("prompt_steps") or []),
                "status": status(row),
                "timestamp": row["timestamp"],
                "workflow": row["workflow_dir_name"],
            }
            for row in scan["records"]
        ],
        "stats": scan["stats"],
    }
    assert actual_scan == _expected("agent_artifacts_snapshot.json")

    explicit_root = tmp_path / "explicit_artifacts"
    shutil.copytree(SOURCES / "explicit_artifacts", explicit_root)
    rows = read_explicit_agent_artifact_index(explicit_root / "index.jsonl")
    actual_explicit = [
        {
            "agent_name": row.agent_name,
            "explicit": row.explicit,
            "id": row.id,
            "kind": row.kind,
            "label": row.label,
            "project": row.project,
            "raw_timestamp": row.raw_timestamp,
            "workflow": row.workflow,
        }
        for row in rows
    ]
    assert actual_explicit == _expected("explicit_artifacts_snapshot.json")


def test_bead_fixture_loads_through_rust_read_facade() -> None:
    beads_dir = SOURCES / "beads"
    actual = {
        "blocked_ids": [issue.id for issue in bead_read_facade.blocked(beads_dir)],
        "doctor_contains": bead_read_facade.doctor(beads_dir),
        "issue_ids": [issue.id for issue in bead_read_facade.list_issues(beads_dir)],
        "ready_ids": [issue.id for issue in bead_read_facade.ready(beads_dir)],
        "stats": bead_read_facade.stats(beads_dir),
    }
    assert actual == _expected("beads_snapshot.json")


def test_catalog_history_and_operational_fixtures_match_snapshots(
    monkeypatch: Any,
) -> None:
    assert _sdd_snapshot() == _expected("sdd_snapshot.json")
    assert _workflow_snapshot() == _expected("workflow_snapshot.json")
    assert _xprompt_snapshot() == _expected("xprompts_snapshot.json")
    assert _history_snapshot(monkeypatch) == _expected("history_snapshot.json")
    assert _dismissed_snapshot() == _expected("dismissed_snapshot.json")
    assert _axe_snapshot() == _expected("axe_snapshot.json")
    assert _mobile_snapshot() == _expected("mobile_snapshot.json")
    assert _editor_snapshot() == _expected("editor_snapshot.json")
    assert _largeish_snapshot() == _expected("largeish_snapshot.json")


def _sdd_snapshot() -> dict[str, Any]:
    docs = sorted(
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in (SOURCES / "sdd").rglob("*.md")
    )
    return {
        "documents": docs,
        "frontmatter_docs": sum(
            1
            for rel_path in docs
            if (FIXTURE_ROOT / rel_path).read_text().startswith("---")
        ),
    }


def _workflow_snapshot() -> dict[str, Any]:
    workflow_dir = (
        SOURCES
        / "agent_artifacts/projects/demo/artifacts/workflow-review/20260513100000"
    )
    state = _read_json(workflow_dir / "workflow_state.json")
    return {
        "current_step_index": state["current_step_index"],
        "prompt_step_files": sorted(
            path.name for path in workflow_dir.glob("prompt_step_*.json")
        ),
        "script_outputs": sorted(
            path.name for path in workflow_dir.glob("script_step_*.stdout")
        ),
        "status": state["status"],
        "steps": [step["name"] for step in state["steps"]],
        "workflow_name": state["workflow_name"],
    }


def _xprompt_snapshot() -> dict[str, Any]:
    xprompt_paths = [
        SOURCES / "xprompts/package/package_demo.md",
        SOURCES / "xprompts/user/user_demo.md",
        SOURCES / "xprompts/project/project_demo.md",
        SOURCES / ".config/sase/xprompts/demo/config_demo.md",
    ]
    prompts = [load_xprompt_from_file(path) for path in xprompt_paths]
    return {
        "names": sorted(prompt.name for prompt in prompts),
        "tags": {
            prompt.name: sorted(tag.value for tag in prompt.tags) for prompt in prompts
        },
    }


def _history_snapshot(monkeypatch: Any) -> dict[str, Any]:
    from sase.history import chat, file_references, prompt

    monkeypatch.setattr(
        prompt, "_PROMPT_HISTORY_FILE", SOURCES / "history/prompt_history.json"
    )
    monkeypatch.setattr(
        file_references,
        "_HISTORY_FILE",
        SOURCES / "history/file_reference_history.json",
    )
    prompts = prompt._load_prompt_history()
    chat_text = (
        SOURCES / "history/chats/202605/demo-run-agent-20260513103000.md"
    ).read_text(encoding="utf-8")
    return {
        "chat_previous_turns": len(
            chat._extract_previous_conversation_turns(chat_text)
        ),
        "file_references": file_references.load_file_references(),
        "prompt_entries": [
            {
                "cancelled": entry.cancelled,
                "text": entry.text,
                "workspace": entry.workspace,
            }
            for entry in prompts
        ],
    }


def _dismissed_snapshot() -> dict[str, Any]:
    dismissed = _read_json(SOURCES / "dismissed/dismissed_agents.json")
    current_bundle = _read_json(
        SOURCES / "dismissed_bundles/202605/bundle-current.json"
    )
    legacy_bundle = _read_json(SOURCES / "dismissed_bundles/legacy_bundle.json")
    return {
        "bundle_ids": [current_bundle["bundle_id"], legacy_bundle["bundle_id"]],
        "dismissed_names": [item["name"] for item in dismissed["dismissed"]],
        "legacy_item_count": len(legacy_bundle["items"]),
    }


def _axe_snapshot() -> dict[str, Any]:
    scheduler = _read_json(SOURCES / "axe/scheduler_state.json")
    checks = _read_jsonl(SOURCES / "axe/checks.jsonl")
    log_lines = [
        line
        for line in (SOURCES / "logs/axe-run.log")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return {
        "checks": [f"{row['name']}:{row['status']}" for row in checks],
        "log_lines": len(log_lines),
        "scheduler_running": scheduler["running"],
    }


def _mobile_snapshot() -> dict[str, Any]:
    bridge = _read_json(SOURCES / "mobile/bridge_state.json")
    audit = _read_jsonl(SOURCES / "mobile/audit.jsonl")
    return {
        "audit_routes": [row["route"] for row in audit],
        "paired": bridge["paired"],
        "session_id": bridge["session_id"],
    }


def _editor_snapshot() -> dict[str, Any]:
    helper = _read_json(SOURCES / "editor/helper_request.json")
    lsp = _read_json(SOURCES / "editor/lsp_completion_request.json")
    return {
        "helper_method": helper["method"],
        "lsp_method": lsp["method"],
        "project": helper["params"]["project"],
    }


def _largeish_snapshot() -> dict[str, Any]:
    rows = _read_jsonl(SOURCES / "largeish/agent_index_seed.jsonl")
    bead_ids = _read_json(SOURCES / "largeish/bead_ids.json")["ids"]
    return {
        "agent_seed_rows": len(rows),
        "bead_ids": len(bead_ids),
        "scale_rows": sum(1 for row in rows if row["name"].startswith("scale_")),
    }
