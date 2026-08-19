"""Model-alias selector parsing and load-balancing rotation state.

Alias values may opt into a round-robin pool with ``|`` separators or an
ordered fallback chain with ``||`` separators.  Parentheses group a ``|``
pool as the primary of a last-resort ``||`` tail (``(A | B) || C``);
unparenthesized mixing of the operators is still rejected.  A pool member
may carry a leading positive-integer weight (``3 grok/grok-4.6``); fallback
and last-resort candidates cannot.  Parsing lives here so runtime,
validation, diagnostics, and display callers share one grammar.  This
module deliberately knows nothing about alias-chain resolution: callers
pass the already-resolved provider/model target for each member when asking
about availability, then select from the resulting boolean mask.

Rotation state is machine-global and best-effort.  The persisted cursor is
the next position in the pool's (possibly weighted) cycle schedule.  A
missing, corrupt, locked, or otherwise unreadable state file always behaves
like a fresh rotation; an LLM launch must never fail merely because usage
accounting could not be saved.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import fcntl
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Literal

from sase.core.paths import sase_home

_STATE_FILENAME = "llm_lb.json"
_LOCK_FILENAME = "llm_lb.lock"
_STATE_VERSION = 1
MAX_POOL_MEMBER_WEIGHT = 99
_WEIGHT_TOKEN_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")

_DIRECT_SIZE_CURSOR_REPLACEMENTS = {
    "xsmall_worker": "xsmall",
    "small_worker": "small",
    "medium_worker": "medium",
    "large_worker": "large",
    "xlarge_worker": "xlarge",
}

_FALLBACK_SIZE_CURSOR_REPLACEMENTS = {
    "cheaper": "xsmall",
    "cheap": "small",
    "smart": "medium",
    "smarter": "large",
}

_DROPPED_RETIRED_CURSOR_KEYS = frozenset(
    {
        "default",
        "epic_lander",
        "big_epic_lander",
        "smartest",
        "cheapest",
    }
)


ModelAliasSelectorMode = Literal["round_robin", "fallback"]


class ModelAliasSelectorError(ValueError):
    """Raised when a selector-valued alias has invalid syntax."""


@dataclass(frozen=True, slots=True)
class ModelAliasSelector:
    """A normalized selector mode and its ordered, non-empty members."""

    mode: ModelAliasSelectorMode
    members: tuple[str, ...]
    weights: tuple[int, ...] = ()
    fallback_members: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        weights = self.weights
        if not weights:
            object.__setattr__(self, "weights", (1,) * len(self.members))
        else:
            if len(weights) != len(self.members):
                raise ValueError("selector weights must match member count")
            if any(weight < 1 or weight > MAX_POOL_MEMBER_WEIGHT for weight in weights):
                raise ValueError(
                    f"selector weights must be between 1 and {MAX_POOL_MEMBER_WEIGHT}"
                )
        if self.fallback_members and self.mode != "round_robin":
            raise ValueError("last-resort fallback requires a load-balanced pool")

    @property
    def weighted(self) -> bool:
        """Return whether any member has a weight greater than 1."""
        return any(weight > 1 for weight in self.weights)

    @property
    def normalized(self) -> str:
        """Return the canonical display/fingerprint spelling."""
        operator = " | " if self.mode == "round_robin" else " || "
        rendered = (
            f"{weight} {member}" if weight > 1 else member
            for weight, member in zip(self.weights, self.members, strict=True)
        )
        pool = operator.join(rendered)
        if not self.fallback_members:
            return pool
        tail = " || ".join(self.fallback_members)
        return f"({pool}) || {tail}"

    @property
    def fingerprint(self) -> str:
        """Return a stable fingerprint that changes whenever membership does."""
        # Keep the historical unweighted round-robin fingerprint stable so
        # existing cursors survive. Fallback selectors never persist a
        # fingerprint. Any weight > 1 is folded into a distinct payload.
        if self.weighted:
            payload = json.dumps(
                [
                    [weight, member]
                    for weight, member in zip(self.weights, self.members, strict=True)
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            payload = json.dumps(
                self.members, ensure_ascii=False, separators=(",", ":")
            )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def concatenated_selector_members(selector: ModelAliasSelector) -> tuple[str, ...]:
    """Return pool members followed by last-resort candidates."""
    return selector.members + selector.fallback_members


def parse_model_alias_selector(value: str) -> ModelAliasSelector | None:
    """Parse *value* when it contains selector syntax, else return ``None``.

    Whitespace around members is ignored.  Leading, trailing, or consecutive
    separators are rejected rather than silently discarding an empty member.
    Mixing ``|`` and ``||`` in one unparenthesized value is rejected.
    Parentheses may wrap a ``|`` pool, optionally followed by a ``||``
    last-resort tail.  A pool member may carry a leading
    ``<weight> <member>`` prefix; the same prefix in a fallback chain is an
    error.  A value without either operator retains the historical
    single-target behavior, including when it starts with a weight-like token.
    """
    if "|" not in value:
        return None
    stripped = value.strip()
    if stripped.startswith("("):
        return _parse_grouped_selector(stripped)
    if "(" in stripped or ")" in stripped:
        raise ModelAliasSelectorError(
            "parentheses may only wrap a '|' load-balanced pool"
        )
    return _parse_flat_selector(stripped)


def _parse_flat_selector(value: str) -> ModelAliasSelector:
    """Parse a parenthesis-free ``|`` pool or ``||`` fallback chain."""
    if "||" in value:
        if "|" in value.replace("||", ""):
            raise ModelAliasSelectorError(
                "model alias values cannot mix '|' load balancing with '||' "
                "ordered fallback"
            )
        mode: ModelAliasSelectorMode = "fallback"
        operator = "||"
        selector_name = "ordered fallback chains"
    else:
        mode = "round_robin"
        operator = "|"
        selector_name = "load-balanced alias pools"

    members = tuple(part.strip() for part in value.split(operator))
    if any(not member for member in members):
        raise ModelAliasSelectorError(
            f"{selector_name} cannot contain empty members; remove leading, "
            f"trailing, or consecutive '{operator}' separators"
        )
    parsed_members: list[str] = []
    parsed_weights: list[int] = []
    for position, member in enumerate(members, start=1):
        prefix = split_pool_member_weight_prefix(member)
        if prefix is None:
            parsed_members.append(member)
            parsed_weights.append(1)
            continue
        token, rest = prefix
        if mode == "fallback":
            raise ModelAliasSelectorError(
                "ordered fallback chains cannot weight candidates; remove "
                f"the '{token} ' prefix from candidate {position}"
            )
        parsed_members.append(rest)
        parsed_weights.append(_parse_pool_member_weight(token))
    return ModelAliasSelector(
        mode=mode,
        members=tuple(parsed_members),
        weights=tuple(parsed_weights),
    )


def _split_leading_group(value: str) -> tuple[str, str]:
    """Return ``(inside, rest)`` for a leading parenthesized group."""
    depth = 0
    for index, char in enumerate(value):
        if char == "(":
            if depth != 0:
                raise ModelAliasSelectorError("nested parentheses are not allowed")
            depth = 1
        elif char == ")":
            if depth != 1:
                raise ModelAliasSelectorError("unmatched parentheses")
            return value[1:index], value[index + 1 :].strip()
    raise ModelAliasSelectorError("unmatched parentheses")


def _parse_last_resort_tail(rest: str) -> tuple[str, ...]:
    """Parse ``|| C [|| D]...`` after a parenthesized pool."""
    if not rest.startswith("||"):
        raise ModelAliasSelectorError(
            "parenthesized pools may only be followed by '||' last-resort candidates"
        )
    if "(" in rest or ")" in rest:
        raise ModelAliasSelectorError(
            "last-resort candidates cannot be parenthesized pools"
        )
    if "|" in rest.replace("||", ""):
        raise ModelAliasSelectorError(
            "model alias values cannot mix '|' load balancing with '||' "
            "ordered fallback"
        )
    parts = [part.strip() for part in rest.split("||")]
    if parts[0]:
        raise ModelAliasSelectorError(
            "parenthesized pools may only be followed by '||' last-resort candidates"
        )
    candidates = parts[1:]
    if any(not candidate for candidate in candidates):
        raise ModelAliasSelectorError("empty last-resort candidate")
    parsed: list[str] = []
    for position, candidate in enumerate(candidates, start=1):
        prefix = split_pool_member_weight_prefix(candidate)
        if prefix is not None:
            token, _rest = prefix
            raise ModelAliasSelectorError(
                "ordered fallback chains cannot weight candidates; remove "
                f"the '{token} ' prefix from candidate {position}"
            )
        parsed.append(candidate)
    return tuple(parsed)


def _parse_grouped_selector(value: str) -> ModelAliasSelector:
    """Parse ``(A | B)`` grouping or ``(A | B) || C [|| D]...`` last-resort."""
    inside, rest = _split_leading_group(value)
    if "||" in inside or "|" not in inside:
        raise ModelAliasSelectorError(
            "parentheses may only wrap a '|' load-balanced pool"
        )
    pool = _parse_flat_selector(inside)
    if not rest:
        return pool
    return ModelAliasSelector(
        mode="round_robin",
        members=pool.members,
        weights=pool.weights,
        fallback_members=_parse_last_resort_tail(rest),
    )


def split_pool_member_weight_prefix(text: str) -> tuple[str, str] | None:
    """Return ``(token, rest)`` when *text* starts with a numeric weight prefix."""
    parts = text.strip().split(None, 1)
    if len(parts) != 2 or _WEIGHT_TOKEN_RE.fullmatch(parts[0]) is None:
        return None
    return parts[0], parts[1]


def _parse_pool_member_weight(token: str) -> int:
    if token.isdigit():
        weight = int(token)
        if 1 <= weight <= MAX_POOL_MEMBER_WEIGHT:
            return weight
    raise ModelAliasSelectorError(
        "load-balanced pool weights must be between 1 and "
        f"{MAX_POOL_MEMBER_WEIGHT}; got '{token}'"
    )


@lru_cache(maxsize=256)
def _weighted_schedule(weights: tuple[int, ...]) -> tuple[int, ...]:
    """Return the smooth weighted round-robin cycle for *weights*."""
    if not weights:
        return ()
    total = sum(weights)
    current = [0] * len(weights)
    schedule: list[int] = []
    for _ in range(total):
        for index, weight in enumerate(weights):
            current[index] += weight
        pick = max(range(len(weights)), key=current.__getitem__)
        schedule.append(pick)
        current[pick] -= total
    return tuple(schedule)


def rotation_state_path() -> Path:
    """Return the lazily-resolved machine-global rotation state path."""
    return sase_home() / _STATE_FILENAME


@contextmanager
def _locked_state() -> Iterator[None]:
    """Serialize state reads and read/modify/write cursor updates."""
    lock_path = sase_home() / _LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace *path* with a JSON representation of *data*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _delete_state_best_effort() -> None:
    try:
        rotation_state_path().unlink()
    except (FileNotFoundError, OSError):
        pass


def _read_entries_unlocked() -> tuple[dict[str, dict[str, Any]], bool]:
    """Return valid cursor entries and whether corrupt data was discarded."""
    try:
        raw = rotation_state_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, False
    except OSError:
        return {}, False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        _delete_state_best_effort()
        return {}, True
    if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
        _delete_state_best_effort()
        return {}, True
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, dict):
        _delete_state_best_effort()
        return {}, True

    entries: dict[str, tuple[int, int, str, dict[str, Any]]] = {}
    changed = set(data) - {"version", "entries"} != set()
    for order, (alias, raw_entry) in enumerate(raw_entries.items()):
        if not isinstance(alias, str) or not isinstance(raw_entry, dict):
            changed = True
            continue
        normalized_alias, priority = _normalize_cursor_key(alias.strip())
        if normalized_alias is None:
            changed = True
            continue
        stored_alias = raw_entry.get("alias")
        fingerprint = raw_entry.get("fingerprint")
        cursor = raw_entry.get("cursor")
        if (
            stored_alias != alias
            or not isinstance(fingerprint, str)
            or isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or cursor < 0
        ):
            changed = True
            continue
        if normalized_alias != alias:
            changed = True
        entry = {
            "alias": normalized_alias,
            "fingerprint": fingerprint,
            "cursor": cursor,
        }
        previous = entries.get(normalized_alias)
        if previous is None or (priority, order) >= (previous[0], previous[1]):
            entries[normalized_alias] = (priority, order, alias, entry)
        else:
            changed = True
        if set(raw_entry) != {"alias", "fingerprint", "cursor"}:
            changed = True
    changed = changed or len(entries) != len(raw_entries)
    changed = changed or any(
        normalized != original
        for normalized, (_priority, _order, original, _entry) in entries.items()
    )
    return (
        {
            normalized: entry
            for normalized, (_priority, _order, _original, entry) in entries.items()
        },
        changed,
    )


def _normalize_cursor_key(key: str) -> tuple[str | None, int]:
    if not key or key in _DROPPED_RETIRED_CURSOR_KEYS:
        return None, 0
    if key in _DIRECT_SIZE_CURSOR_REPLACEMENTS:
        return _DIRECT_SIZE_CURSOR_REPLACEMENTS[key], 2
    if key in _FALLBACK_SIZE_CURSOR_REPLACEMENTS:
        return _FALLBACK_SIZE_CURSOR_REPLACEMENTS[key], 1
    return key, 3


def _write_entries_unlocked(entries: dict[str, dict[str, Any]]) -> None:
    if not entries:
        _delete_state_best_effort()
        return
    _atomic_write_json(
        rotation_state_path(), {"version": _STATE_VERSION, "entries": entries}
    )


def _selection_index(
    cursor: int,
    availability: Sequence[bool],
    schedule: tuple[int, ...],
) -> int:
    """Return the first available schedule position at/after *cursor*."""
    total = len(schedule)
    if total == 0:
        raise ValueError("load-balanced alias pool is empty")
    for offset in range(total):
        position = (cursor + offset) % total
        if availability[schedule[position]]:
            return position
    return 0  # defensive; the all-false case is handled by the caller


def select_model_alias_pool_member(
    alias: str,
    selector: ModelAliasSelector,
    availability: Sequence[bool],
    *,
    consume: bool = False,
) -> int:
    """Return the selected member index, optionally advancing its cursor.

    The cursor is keyed by the alias that owns the pool and names the next
    position in the pool's weighted cycle.  A pool fingerprint mismatch
    resets selection to the start of the schedule.  When every member is
    unavailable the unfiltered pool is retained, allowing normal provider
    diagnostics to explain why the selected launch cannot run.
    """
    if selector.mode != "round_robin":
        raise ValueError("cursor selection requires a load-balanced alias pool")
    if len(availability) != len(selector.members):
        raise ValueError("availability mask does not match alias pool")
    cleaned_alias = alias.strip()
    if not cleaned_alias:
        raise ValueError("load-balanced alias owner is empty")

    schedule = _weighted_schedule(selector.weights)
    any_available = any(availability)

    try:
        with _locked_state():
            entries, changed = _read_entries_unlocked()
            entry = entries.get(cleaned_alias)
            cursor = 0
            if entry is not None and entry.get("fingerprint") == selector.fingerprint:
                cursor = int(entry["cursor"])
            if not any_available:
                if changed:
                    _write_entries_unlocked(entries)
                return 0
            position = _selection_index(cursor, availability, schedule)
            if consume:
                entries[cleaned_alias] = {
                    "alias": cleaned_alias,
                    "fingerprint": selector.fingerprint,
                    "cursor": (position + 1) % len(schedule),
                }
                _write_entries_unlocked(entries)
            elif changed:
                _write_entries_unlocked(entries)
            return schedule[position]
    except Exception:
        # Cursor accounting is advisory.  Resolution and launch diagnostics are
        # more important than surfacing a state-file/lock failure here.
        if not any_available:
            return 0
        return schedule[_selection_index(0, availability, schedule)]


def select_model_alias_fallback_member(availability: Sequence[bool]) -> int:
    """Return the first available fallback member, preserving member zero.

    Ordered fallback selection is deliberately stateless.  When no provider is
    available, member zero remains selected so normal provider diagnostics can
    explain the failed launch.
    """
    if not availability:
        raise ValueError("ordered fallback chain is empty")
    return next((index for index, available in enumerate(availability) if available), 0)


def select_model_alias_selector_index(
    alias: str,
    selector: ModelAliasSelector,
    states: Sequence[MemberAvailability],
    *,
    consume: bool = False,
) -> int:
    """Return the selected index into the concatenated member list.

    Pool members are chosen with today's round-robin cursor when any pool
    member is selectable (including an all-soft pool).  The last-resort tail
    is used only when every pool member is unavailable.  Diverting to the
    tail never reads or advances the pool cursor.
    """
    members = concatenated_selector_members(selector)
    if len(states) != len(members):
        raise ValueError("availability states do not match selector members")
    if selector.mode == "fallback":
        return select_model_alias_fallback_member(fallback_availability_mask(states))
    pool_count = len(selector.members)
    pool_mask = pool_availability_mask(states[:pool_count])
    if any(pool_mask) or not selector.fallback_members:
        return select_model_alias_pool_member(
            alias, selector, pool_mask, consume=consume
        )
    tail_index = select_model_alias_fallback_member(
        fallback_availability_mask(states[pool_count:])
    )
    return pool_count + tail_index


class MemberAvailability(StrEnum):
    """Tri-state member availability driving the ``|`` and ``||`` mask rules."""

    PREFERRED = "preferred"
    SPARING = "sparing"
    UNAVAILABLE = "unavailable"


def pool_availability_mask(states: Sequence[MemberAvailability]) -> list[bool]:
    """Spare sparing members while any preferred member can cover.

    A ``|`` load-balanced pool prefers hard-available members: when at least
    one member is :attr:`MemberAvailability.PREFERRED`, every
    :attr:`MemberAvailability.SPARING` member maps to ``False`` so the pool
    only rotates among preferred members. When no member is preferred (every
    member is sparing or unavailable), sparing members map to ``True`` so an
    everyone-soft pool still rotates normally.
    :attr:`MemberAvailability.UNAVAILABLE` always maps to ``False``.
    """
    any_preferred = any(state == MemberAvailability.PREFERRED for state in states)
    return [
        state == MemberAvailability.PREFERRED
        if any_preferred
        else state != MemberAvailability.UNAVAILABLE
        for state in states
    ]


def fallback_availability_mask(states: Sequence[MemberAvailability]) -> list[bool]:
    """Treat sparing members as available so a soft disable never diverts ``||``.

    A ``||`` ordered fallback chain never diverts past a soft-disabled
    candidate: both :attr:`MemberAvailability.PREFERRED` and
    :attr:`MemberAvailability.SPARING` members map to ``True``.
    :attr:`MemberAvailability.UNAVAILABLE` always maps to ``False``.
    """
    return [state != MemberAvailability.UNAVAILABLE for state in states]
