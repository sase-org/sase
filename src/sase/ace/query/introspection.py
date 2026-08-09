"""Query AST introspection helpers (terminal/submitted/project filter detection)."""

from ..patch import Patch
from .matchers import get_base_status
from .types import AndExpr, NotExpr, OrExpr, PropertyMatch, QueryExpr


def _build_name_to_base_status(
    all_patches: list[Patch],
) -> dict[str, str]:
    """Return a ``name.lower() -> base_status`` map for the given list.

    Cached and reused across the per-filter helpers so a single pass over
    ``_filter_patches`` doesn't rebuild this map three times.
    """
    return {cs.name.lower(): get_base_status(cs.status) for cs in all_patches}


def query_explicitly_targets_terminal(
    expr: QueryExpr,
    all_patches: list[Patch] | None = None,
    *,
    status_map: dict[str, str] | None = None,
) -> bool:
    """Check if query explicitly references terminal status Patches.

    This is used to determine whether to auto-disable the hide_reverted filter.
    The query targets terminal statuses if:
    - It contains status:reverted or status:archived (case-insensitive)
    - It contains name:<spec_name> where the spec has Reverted/Archived status
    - It contains ancestor:<spec_name> where the spec has Reverted/Archived status

    Args:
        expr: The parsed query expression.
        all_patches: List of all Patches for name/ancestor lookups.
        status_map: Optional pre-built ``name -> base_status`` map; built
            from ``all_patches`` if not provided.

    Returns:
        True if the query explicitly targets terminal status Patches.
    """
    if status_map is None:
        status_map = _build_name_to_base_status(all_patches) if all_patches else {}

    def _check_expr(e: QueryExpr) -> bool:
        """Recursively check if expression targets terminal statuses."""
        if isinstance(e, PropertyMatch):
            if e.key == "status" and e.value.lower() in ("reverted", "archived"):
                return True
            if e.key in ("name", "ancestor", "sibling"):
                # Check if the referenced spec is terminal
                ref_status = status_map.get(e.value.lower(), "")
                if ref_status in ("Reverted", "Archived"):
                    return True
            return False
        elif isinstance(e, NotExpr):
            # NOT expressions don't count as "targeting" terminal
            return False
        elif isinstance(e, AndExpr):
            return any(_check_expr(op) for op in e.operands)
        elif isinstance(e, OrExpr):
            return any(_check_expr(op) for op in e.operands)
        else:
            # StringMatch doesn't target terminal specifically
            return False

    return _check_expr(expr)


def query_explicitly_targets_submitted(
    expr: QueryExpr,
    all_patches: list[Patch] | None = None,
    *,
    status_map: dict[str, str] | None = None,
) -> bool:
    """Check if query explicitly references Submitted status Patches.

    Used to determine whether to auto-disable the hide_submitted filter.
    Returns True if the query contains status:submitted, or name:/ancestor:/sibling:
    references to a Patch with Submitted status.

    Args:
        expr: The parsed query expression.
        all_patches: List of all Patches for name/ancestor lookups.
        status_map: Optional pre-built ``name -> base_status`` map; built
            from ``all_patches`` if not provided.

    Returns:
        True if the query explicitly targets Submitted status Patches.
    """
    if status_map is None:
        status_map = _build_name_to_base_status(all_patches) if all_patches else {}

    def _check_expr(e: QueryExpr) -> bool:
        if isinstance(e, PropertyMatch):
            if e.key == "status" and e.value.lower() == "submitted":
                return True
            if e.key in ("name", "ancestor", "sibling"):
                ref_status = status_map.get(e.value.lower(), "")
                if ref_status == "Submitted":
                    return True
            return False
        elif isinstance(e, NotExpr):
            return False
        elif isinstance(e, AndExpr):
            return any(_check_expr(op) for op in e.operands)
        elif isinstance(e, OrExpr):
            return any(_check_expr(op) for op in e.operands)
        else:
            return False

    return _check_expr(expr)


def get_sole_project_filter(expr: QueryExpr) -> str | None:
    """Extract the project name if the query has exactly one project filter.

    Walks the parsed query AST and collects all non-negated PropertyMatch nodes
    with key == "project". Returns the project name if there is exactly one such
    filter; otherwise returns None.

    Filters inside NotExpr or OrExpr branches are excluded.

    Args:
        expr: The parsed query expression.

    Returns:
        The project name string if exactly one project filter, else None.
    """
    projects: list[str] = []

    def _collect(e: QueryExpr) -> None:
        if isinstance(e, PropertyMatch):
            if e.key == "project":
                projects.append(e.value)
        elif isinstance(e, AndExpr):
            for op in e.operands:
                _collect(op)
        elif isinstance(e, (NotExpr, OrExpr)):
            # Negated and OR-branched project filters don't count
            return
        # StringMatch: nothing to collect

    _collect(expr)
    if len(projects) == 1:
        return projects[0]
    return None
