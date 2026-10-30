"""Publication consumes frozen auto state and snapshot bytes without re-evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.autonomy import gates as autonomy_gates
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.service import create_gate
from tests._notification_gates_fixtures import custom_gate_spec


def test_frozen_auto_does_not_evaluate_or_log_again(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del gate_home
    calls: list[str] = []
    real_evaluate = autonomy_gates.evaluate_gate

    def counting(*args, **kwargs):
        calls.append("evaluate")
        return real_evaluate(*args, **kwargs)

    monkeypatch.setattr(autonomy_gates, "evaluate_gate", counting)
    logs: list[object] = []
    monkeypatch.setattr(
        autonomy_gates, "append_decision_log", lambda **kwargs: logs.append(kwargs)
    )

    spec = custom_gate_spec(request_id="frozen-auto-1")
    result = create_gate(
        spec,
        frozen_auto={
            "decision": {"profile": "manual", "outcome": "ask"},
            "policy_block": {"profile": "manual"},
            "auto_execute": False,
        },
    )

    assert calls == []
    assert logs == []
    assert result.request_id == "frozen-auto-1"
    assert result.notification_id is not None


def test_snapshot_bytes_are_used_instead_of_mutated_source(
    gate_home: Path, tmp_path: Path
) -> None:
    del gate_home
    source = tmp_path / "notes.md"
    source.write_text("original snapshot\n", encoding="utf-8")
    spec = custom_gate_spec(request_id="frozen-bytes-1")
    spec["resources"] = [
        *list(spec["resources"]),
        {"path": "notes.md", "role": "editable", "source": str(source)},
    ]
    source.write_text("mutated after stage\n", encoding="utf-8")

    result = create_gate(
        spec,
        frozen_auto={
            "decision": {"profile": "manual"},
            "policy_block": {},
            "auto_execute": False,
        },
        resource_bytes={"notes.md": b"original snapshot\n"},
    )

    owned = result.bundle_path / "notes.md"
    assert owned.read_bytes() == b"original snapshot\n"


def test_missing_snapshot_for_source_resource_fails_closed(
    gate_home: Path, tmp_path: Path
) -> None:
    del gate_home
    source = tmp_path / "notes.md"
    source.write_text("live bytes\n", encoding="utf-8")
    spec = custom_gate_spec(request_id="missing-snap-1")
    spec["resources"] = [
        *list(spec["resources"]),
        {"path": "notes.md", "role": "editable", "source": str(source)},
    ]

    from sase.notification_gates.models import GateError

    with pytest.raises(GateError, match="snapshot missing"):
        create_gate(
            spec,
            frozen_auto={
                "decision": {"profile": "manual"},
                "policy_block": {},
                "auto_execute": False,
            },
            resource_bytes={},
        )
    assert not bundle_paths("custom", "missing-snap-1").root.exists()
