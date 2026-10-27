"""Public facade for sidecar publication transactions."""

from __future__ import annotations

from sase.agents_sync._commit_publication_transaction_engine import (
    publish_queued_transaction,
)
from sase.agents_sync._commit_publication_transaction_types import (
    DrainResult,
    PublicationTransactionHooks,
)

__all__ = (
    "DrainResult",
    "PublicationTransactionHooks",
    "hood_timeout_stage",
    "publish_queued_transaction",
)


def hood_timeout_stage(stage: str | None) -> bool:
    if not stage:
        return False
    return stage.startswith("hood_publish:") or stage.startswith(
        "prompt_archive_prepare"
    )
