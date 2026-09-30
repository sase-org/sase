"""TUI add-note uploads queue through the shared CLI helpers.

TUI-authored attachments must drain through the bead sync worker via the
same pre/post-write upload protocol as the CLI note verbs instead of
stranding bytes locally.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions._artifacts_beads_common import (
    _NoteUploadPlan,
    _plan_note_attachment_upload,
    _queue_note_attachment_upload,
)


def _wire(name: str = "log.txt") -> dict[str, Any]:
    return {
        "name": name,
        "sha256": "ab" * 32,
        "size_bytes": 8,
        "mime_type": "text/plain",
        "visibility": "public",
    }


def test_empty_wires_plan_skips_and_queues_nothing(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.bead.attachments.upload.pre_write_upload",
        lambda *args, **kwargs: calls.append("pre") or ("git", {}, None, False),
    )
    monkeypatch.setattr(
        "sase.bead.attachments.upload.post_write_queue",
        lambda *args, **kwargs: calls.append("post"),
    )
    plan = _plan_note_attachment_upload([], ["attached log.txt"], project_key="sase")
    assert plan.placement == "skip"
    _queue_note_attachment_upload(object(), [], ["attached log.txt"], plan)
    _queue_note_attachment_upload(object(), [_wire()], None, plan)
    assert calls == []


def test_plan_carries_project_key_to_pre_write(
    monkeypatch: Any,
) -> None:
    seen: dict[str, Any] = {}

    def fake_pre(
        wires: list[dict[str, Any]],
        echo_rows: list[str],
        *,
        local_only: bool,
        bead_context: Any = None,
    ) -> tuple[str, dict[str, Any], str | None, bool]:
        seen["project_key"] = getattr(bead_context, "project_key", None)
        seen["local_only"] = local_only
        return ("public", {"public": object()}, "sase", False)

    monkeypatch.setattr("sase.bead.attachments.upload.pre_write_upload", fake_pre)
    echo = ["attached log.txt"]
    plan = _plan_note_attachment_upload([_wire()], echo, project_key="sase")
    assert plan.placement == "public"
    assert plan.project_key == "sase"
    assert seen == {"project_key": "sase", "local_only": False}


def test_queueable_placements_register_post_write(
    monkeypatch: Any,
) -> None:
    posted: list[dict[str, Any]] = []

    def fake_post(mutation: Any, wires: Any, echo_rows: Any, **kwargs: Any) -> None:
        posted.append({"wires": wires, "echo_rows": echo_rows, "kwargs": kwargs})

    monkeypatch.setattr("sase.bead.attachments.upload.post_write_queue", fake_post)
    for placement in ("git", "large", "mixed", "public", "public_pending"):
        posted.clear()
        stores = {"git": object()}
        echo = ["attached log.txt"]
        wires = [_wire()]
        mutation = object()
        _queue_note_attachment_upload(
            mutation,
            wires,
            echo,
            _NoteUploadPlan(
                placement=placement,
                stores=stores,
                project_key="sase",
                require_upload=False,
            ),
        )
        assert len(posted) == 1, placement
        assert posted[0]["wires"] is wires
        assert posted[0]["echo_rows"] is echo
        assert posted[0]["kwargs"]["placement"] == placement
        assert posted[0]["kwargs"]["stores"] is stores
        assert posted[0]["kwargs"]["project_key"] == "sase"


def test_non_queueable_placements_skip_post_write(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.bead.attachments.upload.post_write_queue",
        lambda *args, **kwargs: calls.append("post"),
    )
    for placement in ("skip", "local_only", "no_store", "uploaded"):
        _queue_note_attachment_upload(
            object(),
            [_wire()],
            ["attached log.txt"],
            _NoteUploadPlan(placement=placement),
        )
    assert calls == []
