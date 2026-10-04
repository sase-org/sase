"""Tests for dev-update core compatibility planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.dev_update.core_pin import CorePin
from sase.dev_update.plan import plan_dev_update
import sase.dev_update._plan_roots as plan_mod
import sase.dev_update._plan_status as pin_mod
from tests.dev_update._plan_helpers import probe, record, status


@pytest.fixture(autouse=True)
def _stub_fetch_git_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", lambda _status: None)


def test_core_pin_gate_skips_host_when_dirty_core_lacks_pinned_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": status("/repo/sase", behind=1),
        "/repo/sase-core": status("/repo/sase-core", dirty=True, behind=0),
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
    monkeypatch.setattr(
        pin_mod,
        "read_core_pin",
        lambda _host, _ref: CorePin("sase-core-revision.txt", "a" * 40),
    )
    contains_calls: list[tuple[str, str]] = []

    def contains(core_root: Path, _sha: str, ref: str) -> bool:
        contains_calls.append((str(core_root), ref))
        return False

    monkeypatch.setattr(pin_mod, "core_contains_revision", contains)

    plan = plan_dev_update([host, core], host_record=host)

    host_plan = next(
        package for package in plan.packages if package.record.name == "sase"
    )
    assert host_plan.status == "skipped"
    assert "sase-core aaaaaaaaaaaa (sase-core-revision.txt)" in host_plan.reason
    assert "checkout has local changes" in host_plan.reason
    assert next(
        root for root in plan.roots if root.git_root == "/repo/sase"
    ).status == ("skipped")
    assert contains_calls == [
        ("/repo/sase-core", "HEAD"),
        ("/repo/sase-core", "HEAD"),
    ]
    assert plan.reconcile_steps == ()


def test_core_pin_gate_names_actionable_core_upstream_missing_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": status("/repo/sase", behind=1),
        "/repo/sase-core": status("/repo/sase-core", behind=1),
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
    monkeypatch.setattr(
        pin_mod,
        "read_core_pin",
        lambda _host, ref: CorePin(
            "sase-core-revision.txt", "e" * 40 if ref == "origin/main" else "f" * 40
        ),
    )
    monkeypatch.setattr(
        pin_mod,
        "core_contains_revision",
        lambda _root, sha, _ref: sha == "f" * 40,
    )

    plan = plan_dev_update([host, core], host_record=host)

    host_plan = next(
        package for package in plan.packages if package.record.name == "sase"
    )
    assert host_plan.status == "skipped"
    assert "actionable sase-core upstream origin/main" in host_plan.reason
    assert "does not contain the pinned revision" in host_plan.reason
    assert next(
        package for package in plan.packages if package.record.name == core.name
    ).status == ("actionable")


@pytest.mark.parametrize(
    ("core_status", "contains_result", "expected_core_ref"),
    [
        (status("/repo/sase-core", behind=1), True, "origin/main"),
        (status("/repo/sase-core", behind=0), True, "HEAD"),
    ],
)
def test_core_pin_gate_allows_host_when_core_target_contains_pin(
    monkeypatch: pytest.MonkeyPatch,
    core_status: GitUpstreamStatus,
    contains_result: bool,
    expected_core_ref: str,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": status("/repo/sase", behind=1),
        "/repo/sase-core": core_status,
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
    monkeypatch.setattr(
        pin_mod,
        "read_core_pin",
        lambda _host, _ref: CorePin("sase-core-revision.txt", "b" * 40),
    )
    calls: list[str] = []

    def contains(_root: Path, _sha: str, ref: str) -> bool:
        calls.append(ref)
        return contains_result

    monkeypatch.setattr(pin_mod, "core_contains_revision", contains)

    plan = plan_dev_update([host, core], host_record=host)

    expected_actionable = {"sase"}
    if core_status.strictly_behind:
        expected_actionable.add("sase-core-rs")
    assert {package.record.name for package in plan.actionable} == expected_actionable
    assert calls == [expected_core_ref]


def test_current_host_enriches_dirty_core_skip_reason_when_pin_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": status("/repo/sase", behind=0),
        "/repo/sase-core": status("/repo/sase-core", dirty=True, behind=0),
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
    monkeypatch.setattr(
        pin_mod,
        "read_core_pin",
        lambda _host, _ref: CorePin("sase-core-revision.txt", "c" * 40),
    )
    monkeypatch.setattr(pin_mod, "core_contains_revision", lambda *_args: False)

    plan = plan_dev_update([host, core], host_record=host)

    assert plan.actionable == ()
    core_plan = next(
        package for package in plan.packages if package.record.name == core.name
    )
    assert core_plan.status == "skipped"
    assert "checkout has local changes" in core_plan.reason
    assert "sase-core cccccccccccc (sase-core-revision.txt)" in core_plan.reason
    assert "installed sase" in core_plan.reason
    assert plan.reconcile_steps == ()


def test_current_host_skips_actionable_core_when_its_upstream_lacks_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": status("/repo/sase", behind=0),
        "/repo/sase-core": status("/repo/sase-core", behind=1),
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
    monkeypatch.setattr(
        pin_mod,
        "read_core_pin",
        lambda *_args: CorePin("sase-core-revision.txt", "f" * 40),
    )
    monkeypatch.setattr(pin_mod, "core_contains_revision", lambda *_args: False)

    plan = plan_dev_update([host, core], host_record=host)

    assert plan.actionable == ()
    core_plan = next(
        package for package in plan.packages if package.record.name == core.name
    )
    assert core_plan.status == "skipped"
    assert "actionable sase-core upstream origin/main" in core_plan.reason
    core_root = next(root for root in plan.roots if root.git_root == "/repo/sase-core")
    assert core_root.status == "skipped"
    assert "actionable sase-core upstream origin/main" in core_root.reason
    assert plan.reconcile_steps == ()


@pytest.mark.parametrize("pin", [None, CorePin("sase-core-revision.txt", "d" * 40)])
def test_core_pin_gate_fails_open_when_pin_or_containment_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
    pin: CorePin | None,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": status("/repo/sase", behind=1),
        "/repo/sase-core": status("/repo/sase-core", dirty=True, behind=0),
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
    monkeypatch.setattr(pin_mod, "read_core_pin", lambda *_args: pin)
    monkeypatch.setattr(pin_mod, "core_contains_revision", lambda *_args: None)

    plan = plan_dev_update([host, core], host_record=host)

    assert {package.record.name for package in plan.actionable} == {"sase"}


@pytest.mark.parametrize("checker_exists", [True, False])
def test_plan_dev_update_adds_optional_core_binding_check_after_import_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    checker_exists: bool,
) -> None:
    host_root = tmp_path / "sase"
    checker = host_root / "tools" / "check_sase_core_rs_bindings"
    if checker_exists:
        checker.parent.mkdir(parents=True)
        checker.touch()
    core_root = tmp_path / "sase-core"
    core_root.mkdir()
    host = record("sase", role="host", source_root=str(host_root))
    core = record("sase-core-rs", role="core", source_root=str(core_root))
    statuses = {
        str(host_root): status(str(host_root), behind=1),
        str(core_root): status(str(core_root), behind=1),
    }
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
    monkeypatch.setattr(pin_mod, "read_core_pin", lambda *_args: None)

    plan = plan_dev_update(
        [host, core], host_record=host, tool_python="/tool/bin/python"
    )

    kinds = [step.kind for step in plan.reconcile_steps]
    assert kinds[-1] == (
        "rust_binding_check" if checker_exists else "rust_health_check"
    )
    if checker_exists:
        health_index = kinds.index("rust_health_check")
        binding = plan.reconcile_steps[health_index + 1]
        assert binding.kind == "rust_binding_check"
        assert binding.label == "Verify sase-core-rs exposes the bindings sase requires"
        assert binding.command[:2] == ("/tool/bin/python", str(checker))
        assert binding.command[2:4] == ("--src", str(host_root / "src" / "sase"))
        assert binding.command[4] == "--remedy"
