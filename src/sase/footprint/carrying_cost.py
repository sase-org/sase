"""AST-based carrying-cost enrichment for the generated Footprint catalog."""

from __future__ import annotations

import ast
from pathlib import Path

from sase.footprint.catalog import CatalogEntry

type _Function = ast.FunctionDef | ast.AsyncFunctionDef
type _Definition = ast.ClassDef | _Function


def carrying_cost_enrichment(
    entries: list[CatalogEntry] | tuple[CatalogEntry, ...],
    *,
    source_root: Path | None = None,
) -> dict[str, int]:
    """Return Python handler LOC by feature ID, parsing each source file once.

    Catalog ``src`` values use ``sase/...py:qualified_symbol``. Non-Python
    entries and sources without a symbol do not have a handler LOC value.
    """
    root = (source_root or Path(__file__).resolve().parents[2]).resolve()
    parsed: dict[Path, ast.Module | None] = {}
    result: dict[str, int] = {}

    for entry in entries:
        source = entry.src
        if not source or ":" not in source:
            continue
        filename, _, symbol = source.partition(":")
        if not filename.endswith(".py") or not symbol:
            continue
        relative = Path(filename)
        if relative.parts and relative.parts[0] == "src":
            relative = Path(*relative.parts[1:])
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue

        if path not in parsed:
            parsed[path] = _parse_file(path)
        module = parsed[path]
        if module is None:
            continue
        definition = _find_definition(module, symbol.split("."))
        if definition is None or definition.end_lineno is None:
            continue
        starts = [definition.lineno]
        starts.extend(
            decorator.lineno for decorator in getattr(definition, "decorator_list", ())
        )
        result[entry.id] = max(0, definition.end_lineno - min(starts) + 1)

    return result


def _parse_file(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None


def _find_definition(
    module: ast.Module,
    path: list[str],
) -> _Definition | None:
    nodes: list[ast.stmt] = module.body
    found: _Definition | None = None
    for component in path:
        found = next(
            (
                node
                for node in nodes
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.name == component
            ),
            None,
        )
        if found is None:
            return None
        nodes = (
            found.body
            if isinstance(found, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            else []
        )
    return found


__all__ = ["carrying_cost_enrichment"]
