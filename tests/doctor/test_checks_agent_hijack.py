"""OK / WARN fixtures for the ``agent_hijack.*`` doctor checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.doctor.checks_agent_hijack import (
    _check_hijack_capability,
    agent_hijack_check_specs,
)
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={},
    )


def _row(
    name: str,
    *,
    is_monitor: bool = False,
    agent_session_role: str | None = None,
    role_suffix: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        is_monitor=is_monitor,
        agent_session_role=agent_session_role,
        role_suffix=role_suffix,
        artifacts_dir=f"/tmp/{name}",
    )


def test_agent_hijack_check_specs_are_registered() -> None:
    specs = agent_hijack_check_specs(_context(Path("/tmp")))
    assert [spec.id for spec in specs] == ["agent_hijack.capability"]
    assert {spec.group for spec in specs} == {"agent_hijack"}


def test_hijack_capability_ok_when_every_llm_runner_stamped(tmp_path: Path) -> None:
    rows = [_row("sase-demo.1"), _row("sase-demo.2")]
    check = _check_hijack_capability(
        _context(tmp_path),
        agents=rows,
        load_meta=lambda _row: {"runner_capabilities": ["hijack"]},
    )
    assert check.status == "OK"
    assert check.data["scanned"] == 2
    assert check.data["missing"] == ()


def test_hijack_capability_skips_monitor_and_gate_members(tmp_path: Path) -> None:
    rows = [
        _row("sase-demo--mon-3", is_monitor=True),
        _row("sase-demo--gate", agent_session_role="gate", role_suffix="gate"),
    ]
    check = _check_hijack_capability(
        _context(tmp_path),
        agents=rows,
        load_meta=lambda _row: {},
    )
    assert check.status == "OK"
    assert check.data["scanned"] == 0


def test_hijack_capability_warns_when_meta_lacks_the_stamp(tmp_path: Path) -> None:
    rows = [_row("legacy.1"), _row("fresh.1")]

    def load_meta(row: SimpleNamespace) -> dict[str, object]:
        if row.name == "fresh.1":
            return {"runner_capabilities": ["hijack"]}
        return {"runner_capabilities": []}

    check = _check_hijack_capability(
        _context(tmp_path),
        agents=rows,
        load_meta=load_meta,
    )
    assert check.status == "WARN"
    assert check.data["missing"] == ("legacy.1",)
    assert any("legacy.1" in detail for detail in check.details)
    assert any("wait for its next turn" in step for step in check.next_steps)
