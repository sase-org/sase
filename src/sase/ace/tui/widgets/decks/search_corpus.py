"""Searchable text corpus for one deck panel."""

from __future__ import annotations

from typing import Any

from rich.console import Group


def deck_search_corpus(panel: Any) -> str:
    """Return searchable text for ``panel``'s active deck."""
    try:
        from .model import DeckId
    except Exception:
        return ""
    try:
        deck = panel.deck
    except Exception:
        return ""
    if deck is DeckId.MAIN:
        try:
            from ..renderable_text import renderable_to_text

            parts: list[str] = []
            document = getattr(panel, "_main_document", None)
            cards = getattr(document, "cards", ()) or ()
            for card in cards:
                title = getattr(card, "title", "") or ""
                parts.append(f"── {title} ──")
                try:
                    text = renderable_to_text(Group(*card.renderables)) or ""
                except Exception:
                    text = ""
                parts.append(text)
            return "\n".join(parts).strip()
        except Exception:
            return ""
    if deck is DeckId.FILES:
        try:
            view = panel.file_view
            content = view.get_current_content()
            if content:
                return content
            full = view.get_full_content()
            return full if isinstance(full, str) else ""
        except Exception:
            return ""
    if deck is DeckId.TOOLS:
        try:
            runs_text = panel.tool_runs_view.get_tool_runs_text()
        except Exception:
            runs_text = None
        try:
            calls_text = panel.tools_view.get_llm_calls_text() or ""
        except Exception:
            calls_text = ""
        if not runs_text:
            return calls_text
        if not calls_text:
            return runs_text
        return f"{runs_text}\n{calls_text}"
    if deck is DeckId.FINAL:
        try:
            return panel.final_view.get_final_text() or ""
        except Exception:
            return ""
    return ""


__all__ = ["deck_search_corpus"]
