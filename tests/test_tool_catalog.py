"""Project-layer tool catalog loading and operational tool_runs policy."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache, load_merged_config
from sase.config.tools import (
    ToolCatalogError,
    ToolRunsConfigError,
    get_tool_runs_config,
    load_project_tool_catalog,
)
from sase.core.tool_run import tool_run_normalize_definition


def _write_project_tools(root: Path, tools: dict[object, object]) -> Path:
    config_dir = root / "sase"
    config_dir.mkdir(parents=True)
    path = config_dir / "sase.yml"
    path.write_text(yaml.dump({"tools": tools}), encoding="utf-8")
    return path


def test_sase_project_catalog_has_five_named_tools() -> None:
    catalog = load_project_tool_catalog()
    names = [entry.name for entry in catalog.entries]
    assert names == ["check", "check-full", "install", "test", "test-visual"]
    by_name = {entry.name: entry for entry in catalog.entries}
    assert by_name["check"].definition["argv"] == ["just", "check"]
    assert by_name["check"].definition["stages"] == "run_silent"
    assert by_name["check"].definition["args"] == "deny"
    assert by_name["check-full"].definition["argv"] == ["just", "check-full"]
    assert by_name["install"].definition["stages"] == "none"
    assert by_name["test"].definition["args"] == "allow"
    assert by_name["test-visual"].definition["argv"] == ["just", "test-visual"]
    assert all(entry.digest for entry in catalog.entries)


def test_check_tools_probe_lint_toolchain() -> None:
    """E4 hermetic-baseline: `check` and `check-full` version-probe ruff,
    mypy, symvision, and prettier so a changed lint toolchain moves the
    fingerprint digest and an unavailable probe is explicit incompleteness."""

    catalog = load_project_tool_catalog()
    by_name = {entry.name: entry for entry in catalog.entries}
    for tool in ("check", "check-full"):
        toolchain = by_name[tool].definition["fingerprint"]["toolchain"]
        assert {"ruff", "mypy", "symvision", "prettier"} <= set(toolchain)
        assert all(
            isinstance(toolchain[name], list) and toolchain[name]
            for name in ("ruff", "mypy", "symvision", "prettier")
        )


def test_missing_catalog_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: None)
    catalog = load_project_tool_catalog()
    assert catalog.entries == ()
    assert catalog.path is None


def test_malformed_project_yaml_is_actionable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "sase.yml"
    path.write_text("tools: [not, a, mapping\n", encoding="utf-8")
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    with pytest.raises(ToolCatalogError, match="sase.yml"):
        load_project_tool_catalog()


def test_unknown_tool_field_names_the_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _write_project_tools(
        tmp_path,
        {"check": {"argv": ["just", "check"], "shell": True}},
    )
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    with pytest.raises(ToolCatalogError, match=r"tools\.check"):
        load_project_tool_catalog()


def test_empty_argv_names_the_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _write_project_tools(tmp_path, {"check": {"argv": []}})
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    with pytest.raises(ToolCatalogError, match=r"tools\.check"):
        load_project_tool_catalog()


def test_non_project_tools_do_not_change_execution_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    user_dir = tmp_path / "cfg"
    user_dir.mkdir()
    (user_dir / "sase.yml").write_text(
        yaml.dump({"tools": {"check": {"argv": ["echo", "user"]}}}),
        encoding="utf-8",
    )
    (user_dir / "sase_machine.yml").write_text(
        yaml.dump({"tools": {"check": {"argv": ["echo", "overlay"]}}}),
        encoding="utf-8",
    )
    path = _write_project_tools(
        tmp_path / "proj",
        {"check": {"argv": ["just", "check"], "description": "project"}},
    )
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", user_dir)
    monkeypatch.setattr("sase.config.core.get_local_config_path", lambda: path)
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    monkeypatch.setattr(
        "sase.config.core.selected_overlay_paths",
        lambda: [user_dir / "sase_machine.yml"],
    )
    clear_config_cache()
    merged = load_merged_config()
    assert merged["tools"]["check"]["argv"] == ["just", "check"]
    catalog = load_project_tool_catalog()
    assert [entry.name for entry in catalog.entries] == ["check"]
    assert catalog.entries[0].definition["argv"] == ["just", "check"]
    assert any("ignoring tools" in item for item in catalog.diagnostics)


def test_user_tools_without_project_catalog_do_not_appear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    user_dir = tmp_path / "cfg"
    user_dir.mkdir()
    (user_dir / "sase.yml").write_text(
        yaml.dump({"tools": {"check": {"argv": ["echo", "user"]}}}),
        encoding="utf-8",
    )
    project_config = tmp_path / "proj" / "sase" / "sase.yml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text("is_sase_managed: false\n", encoding="utf-8")
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", user_dir)
    monkeypatch.setattr(
        "sase.config.core.get_local_config_path", lambda: project_config
    )
    monkeypatch.setattr(
        "sase.config.tools.get_local_config_path", lambda: project_config
    )
    clear_config_cache()
    merged = load_merged_config()
    assert "tools" not in merged or merged["tools"] in ({}, None)
    catalog = load_project_tool_catalog()
    assert catalog.entries == ()


def test_deep_merge_would_splice_tool_argv_lists() -> None:
    """Document why tools must not ride the ordinary recursive merge."""
    from sase.config.core import _deep_merge

    spliced = _deep_merge(
        {"tools": {"check": {"argv": ["echo", "user"]}}},
        {"tools": {"check": {"argv": ["just", "check"]}}},
    )
    assert spliced["tools"]["check"]["argv"] == ["echo", "user", "just", "check"]


def test_tool_runs_defaults_are_positive_and_consistent() -> None:
    policy = get_tool_runs_config()
    assert policy["summary_days"] == 180
    assert policy["detail_days"] == 60
    assert policy["log_days"] == 14
    assert policy["detail_days"] <= policy["summary_days"]
    assert policy["log_days"] <= policy["detail_days"]
    assert policy["log_max_bytes"] == 2147483648
    assert policy["run_log_max_bytes"] == 268435456
    assert policy["event_max_bytes"] == 16777216


def test_tool_runs_rejects_inconsistent_horizons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"tool_runs": {"summary_days": 10, "detail_days": 20, "log_days": 1}},
    )
    with pytest.raises(ToolRunsConfigError, match="detail_days"):
        get_tool_runs_config()


def _minimal_definition(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "name": "check",
        "argv": ["just", "check"],
        "description": "Run the repository scoped check.",
    }
    payload.update(overrides)
    return payload


def test_check_declares_normalized_receipt_policy() -> None:
    """E4 landing-proof: only `check` carries an opt-in receipt policy,
    normalized to sorted accept verbs and the 2h TTL literal. The beta flag
    is removed, so the policy is always exposed on the loaded definition."""

    catalog = load_project_tool_catalog()
    by_name = {entry.name: entry for entry in catalog.entries}
    policy = by_name["check"].definition["receipt"]
    assert policy["accept"] == ["no_new_failures", "pass"]
    assert policy["ttl"] == "2h"
    for tool in ("check-full", "install", "test", "test-visual"):
        assert "receipt" not in by_name[tool].definition


def test_receipt_policy_only_edit_preserves_definition_digest() -> None:
    """E4 core-pin-catalog: receipt policy lives outside definition identity,
    so declaring or editing it never moves the definition digest. `pass` is
    always accepted even when only `no_new_failures` is written."""

    base = tool_run_normalize_definition(_minimal_definition())
    assert base["digest"]
    assert "receipt" not in base["definition"]
    with_policy = tool_run_normalize_definition(
        _minimal_definition(receipt={"accept": ["no_new_failures"], "ttl": "2h"})
    )
    assert with_policy["digest"] == base["digest"]
    policy = with_policy["definition"]["receipt"]
    assert policy["accept"] == ["no_new_failures", "pass"]
    assert policy["ttl"] == "2h"


def test_toolchain_probe_change_moves_definition_digest() -> None:
    """E4 core-pin-catalog: fingerprint toolchain inputs are inside definition
    identity, so the phase-1 lint probes intentionally move the digest."""

    without_probe = tool_run_normalize_definition(
        _minimal_definition(
            fingerprint={"toolchain": {"python": ["python", "--version"]}}
        )
    )
    with_probe = tool_run_normalize_definition(
        _minimal_definition(
            fingerprint={
                "toolchain": {
                    "python": ["python", "--version"],
                    "ruff": ["ruff", "--version"],
                }
            }
        )
    )
    assert with_probe["digest"] != without_probe["digest"]


def test_receipt_policy_rejects_unknown_accept_and_overlong_ttl() -> None:
    """E4 core-pin-catalog: the bounded receipt wire refuses unknown verdicts
    and TTLs past the 2h cap instead of persisting them."""

    with pytest.raises(RuntimeError, match="unknown receipt accept token"):
        tool_run_normalize_definition(
            _minimal_definition(receipt={"accept": ["flaky"], "ttl": "2h"})
        )
    with pytest.raises(RuntimeError, match="7200 seconds"):
        tool_run_normalize_definition(
            _minimal_definition(receipt={"accept": ["pass"], "ttl": "3h"})
        )
