from __future__ import annotations

from sase.xprompt.catalog import _CatalogEntry
from sase.xprompt.models import InputArg, InputType, MemoryType, XPrompt
from sase.xprompt.tags import XPromptTag


def make_xprompt(
    name: str,
    *,
    source_path: str | None = None,
    tags: frozenset = frozenset(),
    description: str | None = None,
    inputs: list[InputArg] | None = None,
    skill: bool | None = None,
    content: str = "body",
    snippet: bool | None = None,
    memory_type: MemoryType | None = None,
) -> XPrompt:
    return XPrompt(
        name=name,
        content=content,
        inputs=inputs or [],
        source_path=source_path,
        tags=tags,
        description=description,
        skill=skill,
        snippet=snippet,
        memory_type=memory_type,
    )


def seed_entries() -> list[_CatalogEntry]:
    return [
        _CatalogEntry(
            make_xprompt(
                "a",
                tags=frozenset({XPromptTag.vcs}),
                description="A",
                inputs=[InputArg(name="x", type=InputType.LINE)],
                skill=True,
            ),
            bucket="built-in",
            project=None,
        ),
        _CatalogEntry(
            make_xprompt("b", tags=frozenset({XPromptTag.vcs, XPromptTag.commit})),
            bucket="project",
            project="alpha",
        ),
        _CatalogEntry(
            make_xprompt("c", memory_type="short"),
            bucket="config",
            project=None,
        ),
    ]
