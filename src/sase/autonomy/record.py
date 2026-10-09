"""Thin Python adapter over the core autonomy record bindings.

All ``%auto`` state lives in one core-owned ``agent_meta.autonomy`` record
(``%auto`` E1 ``record`` phase). Python never re-implements the schema,
translation, projection, or evaluation: every function below delegates to
``sase_core_rs`` and only handles flag checks, meta-dict plumbing, and
fail-closed reads.

Legacy keys (``approve``, ``auto_approve_plan_action``,
``auto_approve_argument``, ``plan``) are read only through
:func:`read_record` (record first, legacy translation second) and written
only through :func:`record_meta_patch` (flag-off branch). The ``A`` toggle
rewrite and host-composed successor inheritance belong to the ``inherit``
phase, which builds on this module.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: ``agent_meta.json`` keys that only carry ``%auto`` state. With the
#: ``autonomy_record_only`` sunset flag on, launches and autonomy mutations
#: write none of these; the record projection reproduces them for readers
#: that have not moved onto the record yet.
LEGACY_AUTONOMY_KEYS = (
    "approve",
    "auto_approve_plan_action",
    "auto_approve_argument",
    "plan",
)

#: Gate kinds :func:`auto_applies` understands, with the standard option
#: IDs and executable capabilities of each kind's automatic selection.
_GATE_STANDARD_REQUESTS: dict[str, dict[str, list[str]]] = {
    "plan": {
        "option_ids": ["approve", "commit"],
        "capabilities": ["approve_archive", "approve", "first"],
    },
    "epic_plan": {
        "option_ids": ["approve"],
        "capabilities": ["approve_archive", "approve", "first"],
    },
    "question": {
        "option_ids": ["submit"],
        "capabilities": ["approve_archive", "approve", "first"],
    },
}


def record_only() -> bool:
    """Return whether only ``agent_meta.autonomy`` carries ``%auto`` state."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.feature_flags.snapshot import current_flags

    return current_flags().enabled(FeatureFlag.autonomy_record_only)


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def resolve_selection(
    selection: str | None,
    *,
    source: str = "prompt",
    surface: str = "launch",
    principal: str = "host",
) -> dict[str, Any]:
    """Resolve a ``%auto`` selection text to a revision-1 record dict.

    *selection* is the text after ``%auto`` (``""`` for bare ``%auto``) or
    ``None`` when the prompt carries none. Unknown spellings raise the
    classifier's ``invalid-auto`` message as ``ValueError``.
    """
    from sase.core.rust import require_rust_binding

    resolve = require_rust_binding("autonomy_resolve_selection")
    record = resolve(
        {
            "selection": selection,
            "source": source,
            "actor": {
                "kind": "host",
                "surface": surface,
                "principal": principal,
            },
            "now": _utc_now(),
        }
    )
    return dict(record)


def read_record(meta: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the autonomy record for an ``agent_meta`` mapping.

    The stored record wins; otherwise the legacy keys translate through
    core (``source: legacy``); mappings with neither give ``None``
    (Manual). Never raises: an unusable record or translation fails
    closed to ``None``.
    """
    if meta is None:
        return None
    try:
        stored = meta.get("autonomy")
    except AttributeError:
        return None
    if isinstance(stored, dict) and stored:
        return dict(stored)
    try:
        if not any(key in meta for key in LEGACY_AUTONOMY_KEYS):
            return None
    except TypeError:
        return None
    try:
        from sase.core.rust import require_rust_binding

        translate = require_rust_binding("autonomy_record_from_legacy_meta")
        return dict(translate(dict(meta)))
    except Exception:
        return None


def live_record(artifacts_dir: str | Path) -> dict[str, Any] | None:
    """Return the live autonomy record for an artifacts dir, if any.

    Missing, unreadable, or non-dict meta means ``None``, failing closed.
    """
    from sase.axe.agent_meta import read_live_agent_meta

    try:
        meta = read_live_agent_meta(artifacts_dir)
    except Exception:
        return None
    if not meta:
        return None
    return read_record(meta)


def legacy_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    """Reproduce today's legacy writer output from a record's selection."""
    from sase.core.rust import require_rust_binding

    project = require_rust_binding("autonomy_legacy_projection")
    return dict(project(dict(record)))


def refresh_record_from_legacy(
    meta: Mapping[str, Any],
    *,
    source: str = "tui",
    surface: str = "tui",
) -> dict[str, Any] | None:
    """Resolve a fresh record reflecting *meta*'s legacy ``%auto`` keys.

    Used after a legacy-only write (the ``A`` toggle, revive) so the
    stored record tracks the mutation. Translates first to reuse the
    compatibility table (including the ``epic_plan`` and action-only
    shapes), then resolves that selection fresh so the record carries
    the mutating source instead of ``legacy``. Metas with no ``%auto``
    state give a manual record. Returns ``None`` only when the bindings
    are unavailable, in which case the caller must keep its legacy
    behavior unchanged.
    """
    from sase.core.rust import require_rust_binding

    try:
        translate = require_rust_binding("autonomy_record_from_legacy_meta")
        translated = translate(dict(meta))
    except Exception:
        return None
    profile = translated.get("profile")
    selection = translated.get("selection")
    if profile == "manual" or selection in (None, "manual"):
        # ``""`` is the valid bare-``%auto`` selection, not a missing one.
        selection = None
    return resolve_selection(selection, source=source, surface=surface)


#: Legacy keys :func:`retune_meta_record` drops with the flag on. ``plan``
#: is deliberately absent: it doubles as a plan-flow status marker written
#: by revive and plan submission, which the toggle never removed either,
#: so retuning preserves it exactly as today.
RETUNE_DROP_KEYS = (
    "approve",
    "auto_approve_plan_action",
    "auto_approve_argument",
)

#: Legacy keys that trigger a retune (:func:`retune_meta_record` callers
#: gate on these, never on ``plan`` alone, for the same dual-use reason).
RETUNE_TRIGGER_KEYS = RETUNE_DROP_KEYS


def retune_meta_record(meta: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``meta["autonomy"]`` from its legacy ``%auto`` keys.

    Call only after a write that touched the legacy keys (the ``A``
    toggle patch, revive data): absent legacy keys mean Manual, so an
    unconditional recompute would clobber a live record on any other
    path. Drops the ``%auto`` keys with ``autonomy_record_only`` on,
    keeps both with it off, and always preserves ``plan`` (a dual-use
    status marker), exactly as the toggle does today. Returns *meta*
    unchanged when the bindings are unavailable, preserving today's
    legacy behavior exactly.
    """
    record = refresh_record_from_legacy(meta)
    if record is None:
        return meta
    meta["autonomy"] = record
    if record_only():
        for key in RETUNE_DROP_KEYS:
            meta.pop(key, None)
    else:
        meta.update(
            {
                key: value
                for key, value in legacy_projection(record).items()
                if key != "prompt_mode" and value not in (None, False)
            }
        )
    return meta


def with_legacy_projection(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *meta* with missing legacy ``%auto`` keys filled.

    Explicitly stored legacy keys always win; only absent keys project
    from the stored record, so pre-E1 and mixed states read unchanged. A
    missing binding or an unusable record returns an unmodified copy.
    Never mutates the input, so loader-local views cannot leak projected
    keys back to disk.
    """
    filled = dict(meta)
    record = filled.get("autonomy")
    if not isinstance(record, dict) or not record:
        return filled
    try:
        projection = legacy_projection(record)
    except Exception:
        return filled
    for key in (
        "approve",
        "auto_approve_plan_action",
        "auto_approve_argument",
        "plan",
    ):
        if key not in filled and projection.get(key) not in (None, False):
            filled[key] = projection[key]
    return filled


def record_meta_patch(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the ``agent_meta`` keys to set for *record*.

    Always sets ``autonomy``. With ``autonomy_record_only`` off it also
    sets the projected legacy keys; with the flag on it sets none of
    them, so callers starting from a fresh dict simply never add them.
    Callers mutating an existing dict must additionally drop
    :data:`LEGACY_AUTONOMY_KEYS` when :func:`record_only` holds: use
    :func:`apply_record_meta_patch` for that.
    """
    patch: dict[str, Any] = {"autonomy": dict(record)}
    if not record_only():
        projection = legacy_projection(record)
        # Today's writers only persist meaningful keys (``approve``/``plan``
        # when true, the argument/action when present); ``prompt_mode`` is
        # for ``set_prompt_auto_mode``, never a meta key. Dropping the
        # false/None entries reproduces the historical writer output
        # exactly, including the manual case writing no legacy keys.
        for key, value in projection.items():
            if key == "prompt_mode":
                continue
            if value is False or value is None:
                continue
            patch[key] = value
    return patch


def apply_record_meta_patch(
    agent_meta: dict[str, Any], record: Mapping[str, Any]
) -> dict[str, Any]:
    """Write *record* into *agent_meta* honoring the sunset flag."""
    agent_meta.update(record_meta_patch(record))
    if record_only():
        for key in LEGACY_AUTONOMY_KEYS:
            agent_meta.pop(key, None)
    return agent_meta


def evaluate(
    record: Mapping[str, Any] | None,
    gate_kind: str,
    option_ids: list[str],
    capabilities: list[str],
) -> dict[str, Any]:
    """Evaluate one gate request against *record* through core.

    A ``None`` record is Manual and always asks.
    """
    from sase.core.rust import require_rust_binding

    run = require_rust_binding("autonomy_evaluate")
    if record is None:
        record = {
            "schema_version": 1,
            "profile": "manual",
            "selection": "manual",
            "policy": {
                "gates": {"plan": "ask", "epic": "ask", "question": "ask"},
                "on_ask": "park",
            },
            "overrides": {},
            "source": "legacy",
            "revision": 0,
            "digest": "",
        }
    return dict(
        run(
            dict(record),
            {
                "gate_kind": gate_kind,
                "option_ids": list(option_ids),
                "capabilities": list(capabilities),
            },
        )
    )


def auto_applies(record: Mapping[str, Any] | None, gate_kind: str) -> bool:
    """Return whether *record* auto-resolves a gate of *gate_kind*.

    Runs core ``evaluate`` with that kind's standard option IDs and
    capabilities. Unknown kinds ask. A ``None`` record is Manual.
    """
    standard = _GATE_STANDARD_REQUESTS.get(gate_kind)
    if standard is None:
        return False
    decision = evaluate(
        record,
        gate_kind,
        standard["option_ids"],
        standard["capabilities"],
    )
    return decision.get("outcome") == "auto"


def selection_to_prompt_prefix(selection: object) -> str:
    """Return the ``%auto`` prompt prefix for a record *selection*.

    ``""`` (bare ``%auto``) gives ``"%auto\\n"``; ``"tale"``/``"plan"``/``"epic"``
    give the suffixed spelling; anything else (``"manual"``, ``None``,
    unknown) gives ``""`` so callers never emit a prompt that fails at
    launch. This preserves ``:plan`` exactly, unlike the legacy
    ``prompt_mode`` projection where ``:plan`` and bare share ``plan``.
    """
    if selection == "":
        return "%auto\n"
    if selection in ("tale", "plan", "epic"):
        return f"%auto:{selection}\n"
    return ""


def _actor_wire(
    *,
    kind: str = "host",
    surface: str = "",
    principal: str = "",
) -> dict[str, Any]:
    return {"kind": kind, "surface": surface, "principal": principal}


def autonomy_inherit_record(
    predecessor: Mapping[str, Any],
    *,
    predecessor_name: str = "",
    explicit_selection: str | None = None,
    actor_kind: str = "host",
    surface: str = "",
    principal: str = "",
) -> dict[str, Any]:
    """Seed a host-composed successor record from *predecessor* via core.

    Returns the core ``{status, record, reason}`` dict. An explicit
    ``%auto`` selection narrows under agent semantics; a refused widening
    keeps the inherited record. Raises the core error message as
    ``ValueError`` when the predecessor record cannot parse.
    """
    from sase.core.rust import require_rust_binding

    inherit = require_rust_binding("autonomy_inherit")
    result = inherit(
        dict(predecessor),
        {
            "predecessor_name": predecessor_name,
            "explicit_selection": explicit_selection,
            "actor": _actor_wire(kind=actor_kind, surface=surface, principal=principal),
            "now": _utc_now(),
        },
    )
    return dict(result)


def mutate_record(
    record: Mapping[str, Any],
    selection: str,
    *,
    expected_revision: int | None = None,
    actor_kind: str = "human",
    surface: str = "",
    principal: str = "",
) -> dict[str, Any]:
    """Apply a ``%auto`` selection change to *record* via core.

    Returns the core ``{status, record, reason}`` dict with status
    ``applied``, ``unchanged``, ``refused``, or ``stale``.
    """
    from sase.core.rust import require_rust_binding

    mutate = require_rust_binding("autonomy_mutate")
    request: dict[str, Any] = {
        "selection": selection,
        "actor": _actor_wire(kind=actor_kind, surface=surface, principal=principal),
        "now": _utc_now(),
    }
    if expected_revision is not None:
        request["expected_revision"] = expected_revision
    result = mutate(dict(record), request)
    return dict(result)


def summarize_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the core summary wire for *record*, or ``None`` when unusable.

    Fails closed: a missing binding or an unusable record gives ``None``,
    so inspect surfaces render the record without its summary.
    """
    try:
        from sase.core.rust import require_rust_binding

        summarize = require_rust_binding("autonomy_summary")
        return dict(summarize(dict(record)))
    except Exception:
        return None


def profiles_catalog() -> list[dict[str, Any]]:
    """Return the built-in autonomy profile catalog from core."""
    from sase.core.rust import require_rust_binding

    catalog = require_rust_binding("autonomy_profiles")
    return [dict(profile) for profile in catalog()]


def decision_sentence(decision: Mapping[str, Any], gate_kind: str) -> str | None:
    """Return one human line for a core decision, or ``None`` when unusable.

    Accepts full decisions and durable policy blocks (which carry the same
    deciding fields). Fails closed to ``None``.
    """
    try:
        from sase.core.rust import require_rust_binding

        sentence = require_rust_binding("autonomy_decision_sentence")
        text = sentence(dict(decision), {"gate_kind": gate_kind})
    except Exception:
        return None
    return text if isinstance(text, str) and text else None


def read_decision_log(query: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return decision-log entries newest first for *query*.

    *query* carries ``{since, agent, gate_kind, outcome, limit}``; ``since``
    accepts the same DATE tokens the CLI ``--since`` options accept.
    """
    from sase.core.paths import sase_home
    from sase.core.rust import require_rust_binding

    read = require_rust_binding("autonomy_read_decisions")
    return [dict(entry) for entry in read(str(sase_home()), dict(query))]


#: Coverage line every inspect view ends with (E1 contract wording).
COVERAGE_LINE = "Covers host checkpoints only · the agent's shell is not restricted"


__all__ = [
    "COVERAGE_LINE",
    "LEGACY_AUTONOMY_KEYS",
    "apply_record_meta_patch",
    "auto_applies",
    "autonomy_inherit_record",
    "decision_sentence",
    "evaluate",
    "legacy_projection",
    "live_record",
    "mutate_record",
    "profiles_catalog",
    "read_decision_log",
    "read_record",
    "record_meta_patch",
    "record_only",
    "refresh_record_from_legacy",
    "resolve_selection",
    "RETUNE_DROP_KEYS",
    "RETUNE_TRIGGER_KEYS",
    "retune_meta_record",
    "selection_to_prompt_prefix",
    "summarize_record",
    "with_legacy_projection",
]
