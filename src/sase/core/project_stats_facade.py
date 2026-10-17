"""Pass project statistics requests and responses through the Rust wire unchanged."""

from typing import Any

from sase.core.rust import require_rust_binding


def query_project_stats(request: dict[str, Any]) -> dict[str, Any]:
    """Run the GIL-releasing project statistics binding."""
    binding = require_rust_binding("project_stats_query")
    result: dict[str, Any] = binding(request)
    return result
