"""Small YAML helpers shared by config edit text rewriters."""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ruamel.yaml import YAML


def make_yaml() -> YAML:
    """Build a round-trip YAML handler that preserves comments and quotes."""
    from ruamel.yaml import YAML

    handler = YAML()
    handler.preserve_quotes = True
    # Match the house style for block sequences when dumping full documents.
    handler.indent(mapping=2, sequence=4, offset=2)
    # Avoid ruamel re-wrapping long scalars, such as descriptions and paths.
    handler.width = 4096
    return handler


def dump_yaml(handler: YAML, data: Any) -> str:
    buffer = StringIO()
    handler.dump(data, buffer)
    return buffer.getvalue()
