"""Boolean query evaluation against typed profile query rows."""

from __future__ import annotations

from sase.ace.query.profile_evaluator_types import ArtifactQueryRow, ProfileFieldValue
from sase.ace.query.types import (
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.ace.query_profile import CompiledQueryProfile, QueryFieldSpec
from sase.ace.query_profile.registry import (
    HOST_DATE_BOUND_KEYS,
    HOST_DURATION_BOUND_KEYS,
)
from sase.core.patch import strip_reverted_suffix


def evaluate_expr(
    expr: QueryExpr,
    row: ArtifactQueryRow,
    profile: CompiledQueryProfile,
) -> bool:
    if isinstance(expr, StringMatch):
        if expr.is_error_suffix:
            return "error_suffix" in row.predicates
        if expr.is_running_agent:
            return "running_agent" in row.predicates
        if expr.is_running_process:
            return "running_process" in row.predicates
        return _match_string(row.searchable_text, expr)
    if isinstance(expr, PropertyMatch):
        return _match_field(profile, row, expr)
    if isinstance(expr, NotExpr):
        return not evaluate_expr(expr.operand, row, profile)
    if isinstance(expr, AndExpr):
        return all(evaluate_expr(item, row, profile) for item in expr.operands)
    if isinstance(expr, OrExpr):
        return any(evaluate_expr(item, row, profile) for item in expr.operands)
    raise TypeError(f"Unknown expression type: {type(expr)}")


def _match_string(text: str, expr: StringMatch) -> bool:
    if expr.case_sensitive:
        return expr.value in text
    return expr.value.casefold() in text.casefold()


def _match_field(
    profile: CompiledQueryProfile,
    row: ArtifactQueryRow,
    expr: PropertyMatch,
) -> bool:
    field = profile.field(expr.key)
    if field is None:
        return False
    values = row.fields.get(expr.key, ())
    if not values:
        return False
    if field.value_kind == "bool":
        desired = expr.value == "true"
        return any(isinstance(value, bool) and value is desired for value in values)
    if field.value_kind == "int":
        try:
            desired_int = int(expr.value)
        except ValueError:
            return False
        return _match_int_field(expr.key, values, desired_int)
    if field.value_kind == "date":
        try:
            desired_epoch = int(expr.value)
        except ValueError:
            return False
        return _match_date_field(expr.key, values, desired_epoch)
    return _match_text_field(profile, field, values, expr.value)


def _match_date_field(
    key: str,
    values: tuple[ProfileFieldValue, ...],
    desired_epoch: int,
) -> bool:
    int_values = _field_int_values(values)
    direction = HOST_DATE_BOUND_KEYS.get(key)
    if direction == ">=":
        return any(value >= desired_epoch for value in int_values)
    if direction == "<=":
        return any(value <= desired_epoch for value in int_values)
    return any(value == desired_epoch for value in int_values)


def _match_int_field(
    key: str,
    values: tuple[ProfileFieldValue, ...],
    desired_int: int,
) -> bool:
    int_values = _field_int_values(values)
    direction = HOST_DURATION_BOUND_KEYS.get(key)
    if direction == ">=":
        return any(value >= desired_int for value in int_values)
    if direction == "<=":
        return any(value <= desired_int for value in int_values)
    return any(value == desired_int for value in int_values)


def _field_int_values(values: tuple[ProfileFieldValue, ...]) -> tuple[int, ...]:
    return tuple(
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool)
    )


def _match_text_field(
    profile: CompiledQueryProfile,
    field: QueryFieldSpec,
    values: tuple[ProfileFieldValue, ...],
    desired: str,
) -> bool:
    desired_text = desired.casefold()
    if field.key == "sibling" and profile.pane_id == "patches":
        desired_text = strip_reverted_suffix(desired).casefold()
    haystack = tuple(str(value).casefold() for value in values)
    if field.value_kind == "enum":
        return desired_text in haystack
    if "*" in desired_text:
        # `*` matches any run of characters, including an empty run.
        # Exact-match fields and `sha` anchor the glob to the whole value;
        # substring fields match anywhere inside it. Mirrors `match_glob`
        # in sase-core's query evaluator.
        anchored = field.exact_match or field.key.casefold() == "sha"
        return any(
            match_glob(desired_text, value, anchored=anchored) for value in haystack
        )
    if field.key == "sha":
        return any(value.startswith(desired_text) for value in haystack)
    if field.exact_match:
        return desired_text in haystack
    return any(desired_text in value for value in haystack)


def match_glob(pattern: str, value: str, *, anchored: bool) -> bool:
    """Match a case-folded *pattern* containing `*` against *value*.

    Only `*` is special (`?` compares literally); consecutive `*` collapse.
    When *anchored*, the pattern must match the whole value, otherwise it may
    match any substring of it. Two-pointer matching with backtracking on `*`,
    mirroring sase-core's `match_glob`.
    """

    if anchored:
        return _glob_full(pattern, value)
    return any(_glob_prefix(pattern, value, start) for start in range(len(value) + 1))


def _glob_full(pattern: str, value: str) -> bool:
    pattern_idx = 0
    value_idx = 0
    star: int | None = None
    mark = 0
    while value_idx < len(value):
        if pattern_idx < len(pattern) and pattern[pattern_idx] == "*":
            pattern_idx = _skip_stars(pattern, pattern_idx)
            if pattern_idx == len(pattern):
                return True
            star = pattern_idx
            mark = value_idx
        elif pattern_idx < len(pattern) and pattern[pattern_idx] == value[value_idx]:
            pattern_idx += 1
            value_idx += 1
        elif star is not None:
            pattern_idx = star
            mark += 1
            value_idx = mark
        else:
            return False
    return _skip_stars(pattern, pattern_idx) == len(pattern)


def _glob_prefix(pattern: str, value: str, start: int) -> bool:
    pattern_idx = 0
    value_idx = start
    star: int | None = None
    mark = start
    while True:
        if pattern_idx == len(pattern):
            return True
        if pattern[pattern_idx] == "*":
            pattern_idx = _skip_stars(pattern, pattern_idx)
            if pattern_idx == len(pattern):
                return True
            star = pattern_idx
            mark = value_idx
        elif value_idx < len(value) and pattern[pattern_idx] == value[value_idx]:
            pattern_idx += 1
            value_idx += 1
        elif star is not None:
            mark += 1
            if mark > len(value):
                return False
            pattern_idx = star
            value_idx = mark
        else:
            return False


def _skip_stars(pattern: str, index: int) -> int:
    while index < len(pattern) and pattern[index] == "*":
        index += 1
    return index
