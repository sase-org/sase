"""Pure per-row derivation rules: kind, lifecycle booleans, and patch."""

from __future__ import annotations

_LEAF_RESERVATION_KINDS = frozenset({"claimed", "auto_prefix"})
_ATTENTION_STATUSES = frozenset({"FAILED", "WAITING"})


def classify_kind(
    *,
    name: str,
    container_kind: str | None,
    reservation_kind: str | None,
    agent_type: str | None,
    is_workflow_child: bool,
) -> tuple[str, ...]:
    """Return the multi-valued ``kind`` tuple for one registry entry.

    A workflow parent or child run overlays onto the base container/leaf
    kind (``agent``/``member`` can also be ``workflow`` or
    ``workflow-child``), matching the idiom multi-valued ``kind``/``type``
    fields already use elsewhere in the Artifacts query corpus.
    """
    kinds: list[str] = []
    if container_kind == "family":
        kinds.append("family")
    elif container_kind == "clan":
        kinds.append("clan")
    elif reservation_kind in _LEAF_RESERVATION_KINDS:
        kinds.append("member" if "--" in name else "agent")
    else:
        # A reservation not yet materialized into a run (planned, template,
        # or a foreign owner namespace); not one of the six documented
        # kinds, but every registry entry must classify into something.
        kinds.append("other")

    if is_workflow_child:
        kinds.append("workflow-child")
    elif agent_type == "workflow":
        kinds.append("workflow")

    return tuple(kinds)


def is_dismissed(state: str | None) -> bool:
    """Return whether *state* is the registry's dismissed lifecycle value."""
    return state == "dismissed"


def is_revivable(*, dismissed: bool, bundle_path: str | None) -> bool:
    """Return whether a dismissed row has a bundle available to revive.

    Trusts the dismissed summary index's ``bundle_path`` rather than
    ``stat()``-ing every candidate: the summary index is itself built by
    scanning bundle files, so a matching row already implies the file
    existed as of the last index sync, and a per-row filesystem check over
    the full registry (thousands of ``stat()`` calls) does not fit the
    ≤400ms snapshot budget. The revive action re-verifies the bundle at
    the moment it actually mutates anything, which is where a stale-index
    race (file pruned after the last sync) must be caught regardless.
    """
    return dismissed and bundle_path is not None


def has_attention(status: str | None) -> bool:
    """Return whether *status* means the row wants a human's attention."""
    if not status:
        return False
    return status.upper() in _ATTENTION_STATUSES


def is_retrying(
    *,
    retry_attempt: int | None,
    retry_of_timestamp: str | None,
    retried_as_timestamp: str | None,
    retry_chain_root_timestamp: str | None,
) -> bool:
    """Return whether the row participates in a retry chain."""
    if retry_attempt and retry_attempt > 0:
        return True
    return bool(
        retry_of_timestamp or retried_as_timestamp or retry_chain_root_timestamp
    )


def known_project_keys() -> frozenset[str]:
    """Return every currently-configured project key and alias.

    Used to keep ``patch`` from lying by reporting a project key as a
    patch name. Only covers *currently enabled* projects — an archived or
    renamed project's key can still slip through as a false "patch" — a
    known, documented gap rather than a silent one; see the ``dialect``
    phase's field-set note.
    """
    try:
        from sase.core.paths import sase_projects_dir
        from sase.core.project_lifecycle_facade import list_project_records

        records = list_project_records(sase_projects_dir())
    except (ImportError, OSError, RuntimeError):
        return frozenset()
    keys: set[str] = set()
    for record in records:
        keys.add(record.project_name)
        keys.update(record.aliases)
    return frozenset(keys)


def derive_patch(
    *,
    cl_name: str | None,
    meta_patch: str | None,
    known_keys: frozenset[str],
) -> str | None:
    """Return the best patch-name guess, excluding known project keys.

    ``meta_patch`` (the dismissed archive's dedicated patch-name field) is
    preferred over ``cl_name``, which is dominated by project keys rather
    than patch names.
    """
    for candidate in (meta_patch, cl_name):
        if candidate and candidate not in known_keys:
            return candidate
    return None
