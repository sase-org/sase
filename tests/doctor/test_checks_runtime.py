"""Tests for Phase 2 doctor runtime checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest

from sase.doctor.checks_runtime import (
    _check_git_transport_margin,
    _check_install_management,
    _check_runtime_environment,
    _check_runtime_node,
    runtime_check_specs,
)
from sase.doctor.runner import DoctorContext
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason, UvToolInstall
from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord


def _record(
    *,
    source_root: str,
    install_type: Literal["editable", "wheel"] = "editable",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name="sase",
        role="host",
        display_version="0.1.3",
        distribution_version="0.1.3",
        source_version="0.1.3",
        import_module="sase",
        import_path=f"{source_root}/src/sase",
        code_directory=f"{source_root}/src/sase",
        source_root=source_root,
        distribution_location="/venv/site-packages",
        install_type=install_type,
        git=None,
    )


def _context(cwd: Path, source_root: str) -> DoctorContext:
    context = DoctorContext(cwd=cwd, project=None, sase_home=cwd / ".sase")
    context._runtime_inventory = RuntimeVersionInventory(
        executable="/bin/sase",
        python_executable="/bin/python",
        python_version="3.12.8",
        packages=(_record(source_root=source_root),),
    )
    return context


def _plain_context(cwd: Path) -> DoctorContext:
    return DoctorContext(
        cwd=cwd,
        project=None,
        sase_home=cwd / ".sase",
        env={"PATH": "/usr/bin"},
    )


def _path_context(cwd: Path, path: Path | None = None) -> DoctorContext:
    return DoctorContext(
        cwd=cwd,
        project=None,
        sase_home=cwd / ".sase",
        env={"PATH": str(path) if path is not None else ""},
    )


def _make_executable(directory: Path, name: str) -> Path:
    executable = directory / name
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def _npm_provider_payload(*, provider: str = "codex") -> dict[str, object]:
    return {
        "providers": {
            provider: {
                "autodetect_cli_name": provider,
                "install": {
                    "manager": "npm",
                    "package": f"@example/{provider}",
                    "scope": "global",
                },
            }
        }
    }


def _non_npm_provider_payload() -> dict[str, object]:
    return {
        "providers": {
            "agy": {
                "autodetect_cli_name": "agy",
                "install": {
                    "manager": "curl",
                    "package": None,
                    "scope": None,
                },
            }
        }
    }


def test_runtime_check_specs_registers_node_check(tmp_path: Path) -> None:
    ids = [spec.id for spec in runtime_check_specs(_plain_context(tmp_path))]

    assert "runtime.node" in ids
    assert "vcs.git_transport_margin" in ids


def test_git_transport_margin_ok_when_log_absent(tmp_path: Path) -> None:
    context = DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={"SASE_TUI_GIT_OPS_PATH": str(tmp_path / "missing.jsonl")},
    )

    check = _check_git_transport_margin(context)

    assert check.status == "OK"
    assert check.data["sample_count"] == 0


def test_git_transport_margin_ok_for_healthy_profile(tmp_path: Path) -> None:
    log_path = tmp_path / "tui_git_ops.jsonl"
    _write_git_ops(
        log_path,
        [
            _git_op("plans", 8.0, 120.0, reference_repo_used=False),
            _git_op("plans", 12.0, 120.0, reference_repo_used=True),
            _git_op("beads", 4.0, 120.0, reference_repo_used=True),
        ],
    )
    context = DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={"SASE_TUI_GIT_OPS_PATH": str(log_path)},
    )

    check = _check_git_transport_margin(context)

    assert check.status == "OK"
    assert check.data["high_sample_count"] == 0


def test_git_transport_margin_warns_for_degrading_profile(tmp_path: Path) -> None:
    log_path = tmp_path / "tui_git_ops.jsonl"
    _write_git_ops(
        log_path,
        [
            _git_op("plans", 12.0, 120.0, reference_repo_used=False),
            _git_op("plans", 110.0, 120.0, reference_repo_used=False),
            _git_op("plans", 116.0, 120.0, reference_repo_used=False),
            _git_op("beads", 3.0, 120.0, reference_repo_used=True),
            _git_op("plans", 114.0, 120.0, reference_repo_used=False),
        ],
    )
    context = DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={"SASE_TUI_GIT_OPS_PATH": str(log_path)},
    )

    check = _check_git_transport_margin(context)

    assert check.status == "WARN"
    assert check.data["high_sample_count"] == 3
    assert any("plans" in detail for detail in check.details)
    assert any("without reference" in detail for detail in check.details)


def test_runtime_environment_warns_on_editable_source_root_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    installed = tmp_path / "installed"
    installed.mkdir()

    monkeypatch.setattr(
        "sase.doctor.checks_runtime._current_checkout_root",
        lambda _cwd: checkout,
    )

    check = _check_runtime_environment(_context(checkout, str(installed)))

    assert check.status == "WARN"
    assert "differs from the current checkout" in check.summary
    assert "just install" in check.next_steps[0]


def _git_op(
    store: str,
    duration_seconds: float,
    timeout_seconds: float,
    *,
    reference_repo_used: bool,
) -> dict[str, object]:
    return {
        "event": "sdd_git_operation",
        "operation": "sdd.clone.remote",
        "status": "ok",
        "duration_ms": duration_seconds * 1000.0,
        "timeout_seconds": timeout_seconds,
        "duration_limit_ratio": duration_seconds / timeout_seconds,
        "sdd_store_name": store,
        "sdd_store_path": f"/tmp/workspace/sase/repos/{store}",
        "reference_repo_used": reference_repo_used,
        "cmd": ["git", "clone", "git@example.test:private/repo.git"],
    }


def _write_git_ops(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_runtime_environment_ok_when_editable_source_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(
        "sase.doctor.checks_runtime._current_checkout_root",
        lambda _cwd: checkout,
    )

    check = _check_runtime_environment(_context(checkout, str(checkout)))

    assert check.status == "OK"


def test_runtime_node_skips_without_npm_installed_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_runtime.llm_registry.get_llm_metadata_payload",
        _non_npm_provider_payload,
    )

    check = _check_runtime_node(_path_context(tmp_path))

    assert check.status == "SKIP"
    assert "no npm-installed" in check.summary
    assert check.data["providers"] == ()


def test_runtime_node_warns_when_tooling_and_npm_provider_cli_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_runtime.llm_registry.get_llm_metadata_payload",
        _npm_provider_payload,
    )

    check = _check_runtime_node(_path_context(tmp_path))

    assert check.status == "WARN"
    assert check.data["missing_tools"] == ("node", "npm")
    assert check.data["missing_provider_clis"] == ("codex",)
    assert any("codex" in detail and "missing" in detail for detail in check.details)
    assert any("Node.js/npm" in step for step in check.next_steps)


def test_runtime_node_ok_when_node_and_npm_exist_even_if_provider_cli_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(bin_dir, "node")
    _make_executable(bin_dir, "npm")
    monkeypatch.setattr(
        "sase.doctor.checks_runtime.llm_registry.get_llm_metadata_payload",
        _npm_provider_payload,
    )

    check = _check_runtime_node(_path_context(tmp_path, bin_dir))

    assert check.status == "OK"
    assert check.data["missing_tools"] == ()
    assert check.data["missing_provider_clis"] == ("codex",)


def test_runtime_node_ok_when_provider_cli_exists_without_node_or_npm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = _make_executable(bin_dir, "codex")
    monkeypatch.setattr(
        "sase.doctor.checks_runtime.llm_registry.get_llm_metadata_payload",
        _npm_provider_payload,
    )

    check = _check_runtime_node(_path_context(tmp_path, bin_dir))

    assert check.status == "OK"
    assert check.data["missing_tools"] == ("node", "npm")
    assert check.data["missing_provider_clis"] == ()
    assert check.data["providers"][0]["executable"] == str(codex)


def test_install_management_ok_for_confirmed_uv_tool_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_dir = tmp_path / "uv" / "tools"
    sase_dir = tool_dir / "sase"
    receipt = sase_dir / "uv-receipt.toml"

    def fake_probe(**_: object) -> UvToolInstall:
        return UvToolInstall(
            uv_path="/usr/bin/uv",
            tool_dir=tool_dir,
            sase_dir=sase_dir,
            receipt_path=receipt,
        )

    monkeypatch.setattr("sase.doctor.checks_runtime.probe_uv_tool_install", fake_probe)

    check = _check_install_management(_plain_context(tmp_path))

    assert check.id == "install.management"
    assert check.group == "install"
    assert check.status == "OK"
    assert check.data["managed"] is True
    assert check.data["reason"] is None
    assert check.data["uv_path"] == "/usr/bin/uv"
    assert check.data["tool_dir"] == str(tool_dir)
    assert check.data["sys_prefix"] == str(sase_dir)
    assert check.data["receipt_path"] == str(receipt)


@pytest.mark.parametrize(
    ("reason", "uv_path"),
    [
        (NotUvToolReason.UV_MISSING, None),
        (NotUvToolReason.WRONG_PREFIX, "/usr/bin/uv"),
        (NotUvToolReason.NO_RECEIPT, "/usr/bin/uv"),
    ],
)
def test_install_management_warns_for_unmanaged_installs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: NotUvToolReason,
    uv_path: str | None,
) -> None:
    tool_dir = tmp_path / "uv" / "tools"
    expected_sase_dir = tool_dir / "sase"
    receipt = expected_sase_dir / "uv-receipt.toml"
    sys_prefix = tmp_path / "venv"

    def fake_probe(**_: object) -> NotUvToolInstall:
        return NotUvToolInstall(
            reason=reason,
            sys_prefix=sys_prefix,
            expected_sase_dir=expected_sase_dir,
            receipt_path=receipt,
            uv_path=uv_path,
        )

    monkeypatch.setattr("sase.doctor.checks_runtime.probe_uv_tool_install", fake_probe)

    check = _check_install_management(_plain_context(tmp_path))

    assert check.status == "WARN"
    assert check.data["managed"] is False
    assert check.data["reason"] == reason.value
    assert check.data["uv_path"] == uv_path
    assert check.data["tool_dir"] == str(tool_dir)
    assert check.data["sys_prefix"] == str(sys_prefix)
    assert check.data["receipt_path"] == str(receipt)
    assert any("sase update" in detail for detail in check.details)
    assert any("uv tool install sase" in step for step in check.next_steps)
