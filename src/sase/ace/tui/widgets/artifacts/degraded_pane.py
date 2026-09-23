"""Visible failure state for a provider tab that could not be resolved."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from .lifecycle import ArtifactsPaneLifecycle
from .shell import build_degraded_card


class ArtifactsDegradedPane(ArtifactsPaneLifecycle, Vertical):
    """Visible failure state for a provider tab that could not be resolved."""

    def __init__(
        self,
        *,
        provider_kind: str,
        provider_label: str,
        error: str,
        error_code: str | None = None,
        error_source: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_kind = provider_kind
        self.provider_label = provider_label
        self.error = error
        self.error_code = error_code
        self.error_source = error_source
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        hero_text, card_text = build_degraded_card(
            provider_kind=self.provider_kind,
            provider_label=self.provider_label,
            error=self.error,
            error_code=self.error_code,
            error_source=self.error_source,
        )
        hero = Static(hero_text, classes="artifacts-degraded-hero")
        card = Static(card_text, classes="artifacts-degraded-card")
        card.border_title = "Provider unavailable"
        yield hero
        yield card


__all__ = ["ArtifactsDegradedPane"]
