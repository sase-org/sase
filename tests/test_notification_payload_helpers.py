from __future__ import annotations

from pathlib import Path

import pytest

from sase.core import notification_store_facade
from sase.notifications import payloads


def test_payload_helpers_batch_values_and_keep_missing_slots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def resolve(path: Path | str, values: list[str]) -> list[str | None]:
        calls.append((str(path), values))
        return [
            None
            if value == "missing-reference"
            else f"resolved:{value}"
            if value.startswith("sase-notification-blob:")
            else value
            for value in values
        ]

    monkeypatch.setattr(
        notification_store_facade, "resolve_notification_payloads", resolve
    )
    path = tmp_path / "notifications.jsonl"
    reference = "sase-notification-blob:v1:hash:10"

    assert payloads.resolve_notification_value(path, "inline") == "inline"
    assert payloads.resolve_notification_note(path, reference) == (
        f"resolved:{reference}"
    )
    assert payloads.resolve_notification_action_data(
        path,
        {"ordinary": "unchanged", "payload": reference, "gone": "missing-reference"},
    ) == {
        "ordinary": "unchanged",
        "payload": f"resolved:{reference}",
        "gone": None,
    }
    assert payloads.resolve_notification_notes(path, ["inline", reference]) == [
        "inline",
        f"resolved:{reference}",
    ]
    assert all(call_path == str(path) for call_path, _ in calls)
