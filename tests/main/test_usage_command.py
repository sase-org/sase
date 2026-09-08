"""Tests for the ``sase usage`` command group."""

from __future__ import annotations

import json

import pytest

from sase.llm_provider.usage.refresh import (
    _UsageRefreshProviderResult,
    UsageRefreshReceipt,
)
from sase.llm_provider.usage.store import (
    ProviderUsageStateError,
    ProviderUsageStoreRead,
)
from sase.main import usage_handler
from sase.main.usage_handler import _UsageOperationResult, handle_usage_command
from tests.main.parser_cli_helpers import parse_sase_args


def _snapshot(*providers: dict[str, object]) -> dict[str, object]:
    return {
        "attention": None,
        "collection_health": "ok" if providers else "empty",
        "generated_at": 1_800_000_000.0,
        "providers": list(providers),
        "schema_version": 1,
    }


def _provider(name: str, *, status: str = "ok") -> dict[str, object]:
    return {
        "account_generation": 1,
        "account_mode": "chatgpt",
        "attention": None,
        "collection_reason": None,
        "collection_status": status,
        "completeness": "complete" if status == "ok" else "partial",
        "context_ref": f"{name}:default:1",
        "diagnostic": None,
        "known_constraints": [],
        "last_attempt_at": 1_800_000_000.0,
        "last_full_observation_at": 1_800_000_000.0 if status == "ok" else None,
        "plan": "Plus",
        "provider": name,
        "summary": None,
        "windows": [],
    }


def _read(snapshot: dict[str, object]) -> ProviderUsageStoreRead:
    return ProviderUsageStoreRead(version=1, snapshot=snapshot, diagnostics=())


def test_usage_defaults_to_list() -> None:
    args = parse_sase_args(["usage"])

    assert args.command == "usage"
    assert args.usage_subcommand == "list"


def test_list_json_filters_cached_snapshot(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        usage_handler, "_registered_provider_names", lambda: ("codex", "grok")
    )
    monkeypatch.setattr(
        usage_handler,
        "_load_provider_usage_read",
        lambda: _read(_snapshot(_provider("codex"), _provider("grok"))),
    )

    code = handle_usage_command(parse_sase_args(["usage", "list", "-p", "codex", "-j"]))
    output = capsys.readouterr()

    assert code == 0
    payload = json.loads(output.out)
    assert [item["provider"] for item in payload["providers"]] == ["codex"]
    assert payload["requested_providers"] == ["codex"]
    assert output.err == ""


def test_list_empty_plain_cache_points_at_refresh(monkeypatch, capsys) -> None:
    monkeypatch.setattr(usage_handler, "_registered_provider_names", lambda: ("codex",))
    monkeypatch.setattr(
        usage_handler, "_load_provider_usage_read", lambda: _read(_snapshot())
    )

    code = handle_usage_command(parse_sase_args(["usage", "list", "--plain"]))
    output = capsys.readouterr()

    assert code == 0
    assert "No observations yet; run sase usage refresh." in output.out
    assert output.err == ""


def test_json_and_plain_conflict_is_usage_error(capsys) -> None:
    code = handle_usage_command(parse_sase_args(["usage", "list", "-j", "-P"]))
    output = capsys.readouterr()

    assert code == 2
    assert "--json and --plain cannot be combined" in output.err


def test_unknown_provider_is_usage_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(usage_handler, "_registered_provider_names", lambda: ("codex",))
    monkeypatch.setattr(
        usage_handler,
        "_load_provider_usage_read",
        lambda: pytest.fail("unknown providers must fail before store reads"),
    )

    code = handle_usage_command(parse_sase_args(["usage", "list", "-p", "bogus"]))
    output = capsys.readouterr()

    assert code == 2
    assert "unknown provider 'bogus'" in output.err


def test_unreadable_store_exits_one(monkeypatch, capsys) -> None:
    monkeypatch.setattr(usage_handler, "_registered_provider_names", lambda: ("codex",))

    def fail_read() -> ProviderUsageStoreRead:
        raise ProviderUsageStateError("bad cache")

    monkeypatch.setattr(usage_handler, "_load_provider_usage_read", fail_read)

    code = handle_usage_command(parse_sase_args(["usage", "list", "-j"]))
    output = capsys.readouterr()

    assert code == 1
    payload = json.loads(output.out)
    assert payload["error"]["code"] == "usage_store_unreadable"
    assert "bad cache" in payload["error"]["message"]


def test_refresh_background_emits_receipt_without_waiting(monkeypatch, capsys) -> None:
    monkeypatch.setattr(usage_handler, "_registered_provider_names", lambda: ("codex",))
    receipt = UsageRefreshReceipt(
        schema_version=1,
        origin="cli",
        operation_ids=("op123",),
        providers=(
            _UsageRefreshProviderResult(
                provider="codex",
                status="reserved",
                reason="never_observed",
                operation_id="op123",
            ),
        ),
    )
    calls: list[tuple[tuple[str, ...] | None, bool, str]] = []

    def submit(
        providers: tuple[str, ...] | None,
        *,
        explicit: bool,
        origin: str,
    ) -> UsageRefreshReceipt:
        calls.append((providers, explicit, origin))
        return receipt

    monkeypatch.setattr(usage_handler, "submit_usage_refresh", submit)
    monkeypatch.setattr(
        usage_handler,
        "_wait_for_operation_ids",
        lambda *args, **kwargs: pytest.fail("background refresh must not wait"),
    )

    code = handle_usage_command(
        parse_sase_args(["usage", "refresh", "-b", "-p", "codex", "-j"])
    )
    output = capsys.readouterr()

    assert code == 0
    assert calls == [(("codex",), True, "cli")]
    assert json.loads(output.out)["operation_ids"] == ["op123"]


def test_refresh_foreground_exits_one_for_unauthenticated_result(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(usage_handler, "_registered_provider_names", lambda: ("codex",))
    monkeypatch.setattr(
        usage_handler,
        "submit_usage_refresh",
        lambda providers, *, explicit, origin: UsageRefreshReceipt(
            schema_version=1,
            origin=origin,
            operation_ids=("op123",),
            providers=(
                _UsageRefreshProviderResult(
                    provider="codex",
                    status="reserved",
                    reason="never_observed",
                    operation_id="op123",
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        usage_handler,
        "_wait_for_operation_ids",
        lambda operation_ids, *, stream: (
            _UsageOperationResult(
                proc_id=operation_ids[0],
                success=True,
                message="usage refresh completed",
                error=None,
                payload={
                    "providers": [
                        {
                            "outcome": "unauthenticated",
                            "provider": "codex",
                            "reason_code": "logged_out",
                        }
                    ]
                },
                proc_status="success",
            ),
        ),
    )
    monkeypatch.setattr(
        usage_handler,
        "_load_provider_usage_read",
        lambda: _read(_snapshot(_provider("codex", status="unauthenticated"))),
    )

    code = handle_usage_command(
        parse_sase_args(["usage", "refresh", "-p", "codex", "--plain"])
    )
    output = capsys.readouterr()

    assert code == 1
    assert "Subscription usage" in output.out
    assert "Usage refresh" in output.err
