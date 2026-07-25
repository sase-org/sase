"""Immutable data model for the Artifacts Chats pane."""

from __future__ import annotations

from dataclasses import dataclass

from sase.history.chat_catalog_provenance import (
    ChatCatalogEntry,
    ChatCatalogSnapshot,
)


CHATS_FIRST_PAGE_LIMIT = 500


@dataclass(frozen=True, slots=True)
class ChatsSnapshot:
    """One project-scoped catalog result accepted by the UI thread."""

    project: str | None
    catalog: ChatCatalogSnapshot
    complete: bool

    @property
    def entries(self) -> tuple[ChatCatalogEntry, ...]:
        return self.catalog.entries


def pane_snapshot(
    project: str | None,
    catalog: ChatCatalogSnapshot,
    *,
    requested_limit: int | None,
) -> ChatsSnapshot:
    """Wrap a headless result with the request scope used by the pane."""

    return ChatsSnapshot(
        project=project,
        catalog=catalog,
        complete=requested_limit is None or not catalog.truncated,
    )


__all__ = ["CHATS_FIRST_PAGE_LIMIT", "ChatsSnapshot", "pane_snapshot"]
