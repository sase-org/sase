from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.sdd._artifact_link_outbox_io import read_artifact_link_outbox_entries
from sase.sdd._artifact_link_store_support import unique_rows
from sase.sdd.artifact_link_event_publisher import rows_from_events
from sase.sdd.artifact_link_store import ArtifactLinkStore


def install_fake_artifact_link_event_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[dict[str, Any], ...]]:
    drained: list[tuple[dict[str, Any], ...]] = []

    def _drain(
        *,
        store: ArtifactLinkStore,
        agent_name: str | None = None,
        **_kwargs: object,
    ) -> SimpleNamespace:
        entries = read_artifact_link_outbox_entries(store.project_key)
        selected = tuple(
            entry
            for entry in entries
            if agent_name is None or entry.agent_name == agent_name
        )
        events = tuple(dict(entry.event) for entry in selected if entry.event)
        drained.append(events)
        rows = rows_from_events(events)
        prior_rows = tuple(store.load_aggregate().get("rows", ()))
        store._write_aggregate({"rows": unique_rows((*prior_rows, *rows))})  # noqa: SLF001
        return SimpleNamespace(
            queued=len(entries),
            drained=len(events),
            retained=len(entries) - len(events),
            dropped=0,
            committed=bool(events),
            changed_indexes=(),
            event_paths=(),
            publication_error=None,
            skip_diagnostics=(),
        )

    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        _drain,
    )
    return drained
