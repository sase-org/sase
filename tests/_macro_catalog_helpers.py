from __future__ import annotations

from sase.macro.catalog import _CatalogEntry
from sase.macro.models import InputArg, InputType, MemoryType, Macro
from sase.macro.tags import MacroTag


def make_macro(
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
) -> Macro:
    return Macro(
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
            make_macro(
                "a",
                tags=frozenset({MacroTag.vcs}),
                description="A",
                inputs=[InputArg(name="x", type=InputType.LINE)],
                skill=True,
            ),
            bucket="built-in",
            project=None,
        ),
        _CatalogEntry(
            make_macro("b", tags=frozenset({MacroTag.vcs, MacroTag.commit})),
            bucket="project",
            project="alpha",
        ),
        _CatalogEntry(
            make_macro("c", memory_type="core"),
            bucket="config",
            project=None,
        ),
    ]
