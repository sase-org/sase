"""Shared builders for no-new receipt tests."""

from __future__ import annotations

from typing import Any

import pytest


def core_supports_no_new() -> bool:
    """Return whether the installed core seals the accept policy.

    The sase-core revision pin moves past the accept-capable core commit
    after that commit lands; until then no-new tests skip instead of
    failing against a core that seals every intent as pass.
    """

    try:
        from sase.core.continuation_facade import seal_conditional_completion
        from tests.core._continuation_facade_helpers import (
            make_prepare_request,
        )

        request = make_prepare_request()
        request["accept"] = "no_new_failures"
        intent = seal_conditional_completion(request)
        return intent.get("accept") == "no_new_failures"
    except Exception:  # noqa: BLE001 - any failure means unsupported.
        return False


needs_no_new_core = pytest.mark.skipif(
    not core_supports_no_new(),
    reason="installed core predates the sealed accept policy",
)


def make_meta(**overrides: object) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "monitor_id": "monitor-1",
        "monitor_completion_ref": "cci:no-new",
        "monitor_profile": "verify",
        "monitor_tool_run_id": "run-1",
        "monitor_cwd": "/repo",
        "monitor_command": "just check",
        "monitor_execution_argv": ["just", "check"],
        "workspace_dir": "/ws/20",
        "continuation_monitor_result_id": "result-1",
    }
    meta.update(overrides)
    return meta


class _Resolved:
    tool_name = "check"
    digest = "d" * 64
    adhoc = False
    definition = {"receipt": {"accept": ["pass", "no_new_failures"]}}

    def resolved_project_identity(self) -> str:
        return "sase"


def _fingerprint(*identities: str) -> dict[str, Any]:
    repos = list(identities) or ["sase"]
    return {
        "schema_version": 1,
        "definition_digest": "d" * 64,
        "extra_args_digest": "e" * 64,
        "repos": [{"identity": identity} for identity in repos],
        "completeness": {"complete": True, "missing": []},
    }


def receipt(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "receipt_id": "rc-1",
        "source_run_id": "run-1",
        "verdict": "no_new_failures",
        "signature_refs": [
            {
                "extractor": "triage",
                "extractor_version": 1,
                "signature": "known:flake-1",
            }
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def tool_doubles(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Wire the settled ToolRun, triage, fingerprint, and receipt doubles."""

    run = {
        "run_id": "run-1",
        "state": "failed",
        "tool_name": "check",
        "definition_digest": "d" * 64,
        "extra_args_digest": "e" * 64,
        "owner_kind": "monitor",
        "owner_id": "monitor-1",
        "project": "sase",
        "exit_code": 1,
    }
    lookup = {"outcome": "covered", "receipt": receipt(), "refusal": None}
    doubles = {
        "run": run,
        "triage": {"verdict": "no_new_failures"},
        "fingerprint": _fingerprint(),
        "lookup": lookup,
    }
    monkeypatch.setattr(
        "sase.core.tool_run.tool_run_show",
        lambda _run_id: {"run": dict(doubles["run"])},
    )
    monkeypatch.setattr(
        "sase.core.tool_run.tool_run_triage_show",
        lambda _request: dict(doubles["triage"]),
    )
    monkeypatch.setattr(
        "sase.tool.argv.resolve_run_argv",
        lambda _words, **_kwargs: _Resolved(),
    )
    monkeypatch.setattr(
        "sase.tool.receipts.receipt_policy_for_resolved",
        lambda _resolved: {"accept": ["pass", "no_new_failures"], "ttl": "2h"},
    )
    monkeypatch.setattr(
        "sase.tool.observe.observe_fingerprint",
        lambda _resolved: dict(doubles["fingerprint"]),
    )
    monkeypatch.setattr(
        "sase.core.tool_run.tool_run_receipt_lookup",
        lambda _payload: dict(doubles["lookup"]),
    )
    return doubles
