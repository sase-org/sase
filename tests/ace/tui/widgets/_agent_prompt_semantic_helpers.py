"""Helpers for agent-prompt semantic highlighting tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.xprompt.glossary_catalog import EditorGlossaryCatalog
from sase.xprompt.repo_mention_catalog import EditorRepoMentionCatalog


def semantic_theme() -> SimpleNamespace:
    return SimpleNamespace(
        primary="#AD8301",
        accent="#907AA9",
        foreground="#FFFCF0",
        background="#100F0F",
    )


def install_panel_semantics(
    panel: Any,
    *,
    glossary: EditorGlossaryCatalog | None = None,
    repo: EditorRepoMentionCatalog | None = None,
    glossary_warm: bool = True,
    repo_warm: bool = True,
    skills: list[Any] | None = None,
    warm_calls: list[str] | None = None,
) -> SimpleNamespace:
    """Attach memory-only catalog getters and a theme to *panel*."""
    recorded = warm_calls if warm_calls is not None else []

    def _glossary(_context: object, *, schedule: bool = True) -> object:
        if schedule and not glossary_warm:
            recorded.append("glossary")
        return glossary

    def _repo(_context: object, *, schedule: bool = True) -> object:
        if schedule and not repo_warm:
            recorded.append("repo")
        return repo

    app = SimpleNamespace(
        current_theme=semantic_theme(),
        get_prompt_glossary_catalog=_glossary,
        is_prompt_glossary_catalog_warm=lambda _context: glossary_warm,
        warm_prompt_glossary_catalog=lambda _context: recorded.append("glossary"),
        get_prompt_repo_mention_catalog=_repo,
        is_prompt_repo_mention_catalog_warm=lambda _context: repo_warm,
        warm_prompt_repo_mention_catalog=lambda _context: recorded.append("repo"),
        get_prompt_catalog_assist_entries=lambda _project, *, schedule=True: (
            skills or []
        ),
    )
    panel.app = app
    return app
