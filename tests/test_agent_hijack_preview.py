"""Read-only hijack preview and continuation-context preparation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.agent.hijack import preview as recovery


def _record(artifacts: Path, *, state: str = "held") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "hijack_id": "h-123",
        "agent_name": "worker",
        "artifacts_dir": str(artifacts),
        "workspace_num": 4,
        "workspace_dir": str(artifacts.parent / "workspace"),
        "provider": "claude",
        "model": "opus",
        "effort": "high",
        "model_alias": "large",
        "model_alias_trail": ["large"],
        "model_origin": "prompt",
        "run_duration_seconds": 2700,
        "last_tool": "Bash `just check`",
        "last_tool_age_seconds": 1320,
        "repo_diffs": [
            {"files_changed": 5, "insertions": 212, "deletions": 31},
            {"files_changed": 1, "insertions": 3, "deletions": 1},
        ],
        "snapshots": [{"reference": "snap-123"}],
        "stale_lock_files": [".git/index.lock"],
        "state": state,
        "revision": 7,
        "hijacked_at": "2026-11-03T10:00:00+00:00",
    }


def _install_preview_fakes(monkeypatch: Any) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []

    monkeypatch.setattr(
        recovery,
        "agent_hijack_config",
        lambda: type(
            "Config",
            (),
            {"escalation_ladder": ("@large", "@xlarge"), "successor_context": "fork"},
        )(),
    )
    monkeypatch.setattr(
        recovery,
        "build_alias_candidates",
        lambda ladder: {
            "@large": ["claude/opus@high"],
            "@xlarge": ["claude/opus@xhigh"],
        },
    )
    monkeypatch.setattr(recovery, "escalation_wire_schema_version", lambda: 1)
    monkeypatch.setattr(
        recovery, "hijack_recovery_preview_wire_schema_version", lambda: 1
    )
    monkeypatch.setattr(
        recovery,
        "hijack_escalation_target",
        lambda request: {
            "schema_version": 1,
            "available": True,
            "kind": "escalate",
            "from_rung": "@large",
            "to_rung": "@xlarge",
            "concrete": "claude/opus@xhigh",
            "reason": None,
        },
    )

    def assemble(request: dict[str, Any]) -> dict[str, Any]:
        requests.append(request)
        return {
            "schema_version": 1,
            "hijack_id": request["hijack_id"],
            "revision": request["revision"],
            "header": request["header"],
            "default_action": "escalate",
            "actions": [
                {
                    "action": "escalate",
                    "available": True,
                    "label": "Escalate",
                    "detail": "@large → @xlarge",
                    "target": "claude/opus@xhigh",
                },
                {
                    "action": "continue",
                    "available": True,
                    "label": "Continue",
                    "detail": "same model",
                    "target": "claude/opus@high",
                },
            ],
        }

    monkeypatch.setattr(recovery, "assemble_hijack_recovery_preview", assemble)
    return requests


def test_recovery_preview_gathers_header_model_lineage_and_diff_facts(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"hijack_lineage": {"to_rung": "@large"}}), encoding="utf-8"
    )
    record = _record(artifacts)
    requests = _install_preview_fakes(monkeypatch)

    result = recovery.hijack_recovery_preview(record)

    assert result.default_action == "escalate"
    assert result.revision == 7
    assert result.header["agent_name"] == "worker"
    assert result.header["workspace_num"] == 4
    assert result.header["model_display"] == "claude/opus@high"
    assert result.header["run_duration_display"] == "45m"
    assert result.header["files_changed"] == 6
    assert result.header["insertions"] == 215
    assert result.header["deletions"] == 32
    assert result.action("escalate") is not None
    request = requests[0]
    assert request["state"] == "held"
    assert request["continue_target"] == "claude/opus@high"
    assert request["escalate"]["concrete"] == "claude/opus@xhigh"
    assert request["header"] == result.header


def test_recovery_preview_passes_resolving_state_to_rust(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    requests = _install_preview_fakes(monkeypatch)

    result = recovery.hijack_recovery_preview(_record(artifacts, state="resolving"))

    assert result.state == "resolving"
    assert requests[0]["state"] == "resolving"


def test_continuation_falls_back_to_brief_when_expanded_fork_exceeds_budget(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_prompt.md").write_text("Do the task.\n", encoding="utf-8")
    (artifacts / "chat.md").write_text(
        "## Prompt\n\nDo the task.\n\n## Response\n\nPartial work\n",
        encoding="utf-8",
    )
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    _install_preview_fakes(monkeypatch)
    prompt_requests: list[dict[str, Any]] = []

    def make_prompt(request: dict[str, Any]) -> str:
        prompt_requests.append(request)
        directive = (
            f"#fork:{request['hijacked_name']}\n"
            if request["context_mode"] == "fork"
            else ""
        )
        transcript = (
            f" Transcript: `{request['transcript_path']}`."
            if request["transcript_path"]
            else ""
        )
        return f"%model:{request['model_target']}\n{directive}FRAME{transcript}\nDo the task."

    fork_builds: list[dict[str, Any]] = []

    def build_fork(sources: object, **kwargs: object) -> str:
        fork_builds.append(dict(kwargs))
        return "EXPANDED HIJACK TRANSCRIPT"

    decisions: list[str] = []

    def decide(prompt: str, *, model_target: str) -> dict[str, Any]:
        decisions.append(prompt)
        if "EXPANDED HIJACK TRANSCRIPT" in prompt:
            return {
                "kind": "refuse",
                "estimated_prompt_bytes": 900_000,
                "target_prompt_bytes": 800_000,
            }
        return {
            "kind": "fits",
            "estimated_prompt_bytes": len(prompt),
            "target_prompt_bytes": 800_000,
        }

    monkeypatch.setattr(recovery, "continuation_wire_schema_version", lambda: 1)
    monkeypatch.setattr(recovery, "hijack_continuation_prompt", make_prompt)
    monkeypatch.setattr(recovery, "build_fork_injected_history", build_fork)
    monkeypatch.setattr(recovery, "_budget_decision", decide)

    result = recovery.build_hijack_continuation_prompt(_record(artifacts))

    assert result.context_mode == "brief"
    assert result.model_target == "claude/opus@high"
    assert "#fork:" not in result.prompt
    assert f"Transcript: `{artifacts / 'chat.md'}`" in result.prompt
    assert fork_builds == [{"record_shadow_measurement": False}]
    assert [request["context_mode"] for request in prompt_requests] == ["fork", "brief"]
    assert len(decisions) == 2


def test_continuation_keeps_fork_when_budget_preflight_fits(
    tmp_path: Path, monkeypatch: Any
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_prompt.md").write_text("Do the task.\n", encoding="utf-8")
    (artifacts / "chat.md").write_text("partial transcript", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    _install_preview_fakes(monkeypatch)
    monkeypatch.setattr(recovery, "continuation_wire_schema_version", lambda: 1)
    monkeypatch.setattr(
        recovery,
        "hijack_continuation_prompt",
        lambda request: (
            f"%model:{request['model_target']}\n#fork:worker\nFRAME\nDo the task."
        ),
    )
    monkeypatch.setattr(
        recovery, "build_fork_injected_history", lambda *_args, **_kwargs: "HISTORY"
    )
    monkeypatch.setattr(
        recovery,
        "_budget_decision",
        lambda *_args, **_kwargs: {"kind": "fits", "target_prompt_bytes": 800_000},
    )

    result = recovery.build_hijack_continuation_prompt(_record(artifacts))

    assert result.context_mode == "fork"
    assert "#fork:worker" in result.prompt
    assert result.transcript_path == str(artifacts / "chat.md")
