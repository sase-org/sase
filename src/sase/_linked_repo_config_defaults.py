"""Managed defaults injection and revision-pin helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import re
from pathlib import Path
from typing import Any

from sase._linked_repo_config_keys import (
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_ATTACHMENTS_DESCRIPTION,
    DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION,
    DEFAULT_BEADS_DESCRIPTION,
    DEFAULT_LINKED_REPO_MARKER,
    DEFAULT_LINKED_REPOS_CONFIG_KEY,
    DEFAULT_PLANS_DESCRIPTION,
    REVISION_PIN_CONFIG_KEY,
    SIDECAR_BUILTIN_CONFIG_KEY,
    SIDECAR_CUSTOM_CONFIG_KEY,
    SIDECAR_REMOTE_URL_KEY,
    SIDECAR_REPO_MARKER,
    SIDECAR_REPO_REF_KEY,
    SIDECAR_ROLE_KEY,
    SIDECAR_SLUG_KEY,
    optional_entry_text,
)
from sase._linked_repo_identity import resolve_sidecar_repo_identity
from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
)


def _beads_public_for_injection(
    config: Mapping[str, Any] | None,
    merged: Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether the beads sidecar in *config*/*merged* is public.

    Mirrors :func:`sase.bead.attachments.provenance.bead_store_visibility`
    applied to the config being merged: default ``public`` when beads are a
    sidecar without an explicit visibility, ``private`` for non-sidecar
    (legacy) bead storage or an explicit private visibility.
    """

    try:
        mapping = config if isinstance(config, Mapping) else {}
        repos = mapping.get("repos")
        sidecar = repos.get("sidecar") if isinstance(repos, Mapping) else None
        if isinstance(sidecar, Mapping):
            for bucket in (
                sidecar.get(SIDECAR_BUILTIN_CONFIG_KEY),
                sidecar.get(SIDECAR_CUSTOM_CONFIG_KEY),
            ):
                if isinstance(bucket, Mapping) and "beads" in bucket:
                    entry = bucket.get("beads")
                    if isinstance(entry, Mapping):
                        visibility = (
                            str(entry.get("visibility") or "public").strip().lower()
                        )
                        return visibility == "public"
                    return True
        for entry in merged:
            if not isinstance(entry, Mapping):
                continue
            for key in (SIDECAR_ROLE_KEY, "role", "name"):
                try:
                    value = entry.get(key)
                except Exception:
                    continue
                if isinstance(value, str) and value.strip() == BEADS_SIDECAR_ROLE:
                    visibility = (
                        str(entry.get("visibility") or "public").strip().lower()
                    )
                    return visibility == "public"
        # No beads sidecar entry: non-sidecar (legacy) bead storage counts
        # as private, so no public attachments role is injected. The one
        # exception is a config that never mentions beads at all, where the
        # managed defaults below inject a public beads sidecar; treat that
        # as public.
        if not isinstance(sidecar, Mapping):
            return False
        return True
    except Exception:
        return False


def inject_default_linked_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    local_config: Mapping[str, Any],
    config: Mapping[str, Any] | None = None,
) -> list[Mapping[str, Any]]:
    """Inject managed-project sidecar repos unless locally disabled."""

    merged = list(entries)
    if local_config.get("is_sase_managed") is not True:
        return merged
    if local_config.get(DEFAULT_LINKED_REPOS_CONFIG_KEY) is False:
        return merged

    project_name = Path(primary_workspace_dir).resolve(strict=False).name
    if not project_name:
        return merged

    configured_names = {
        name.strip()
        for entry in entries
        if isinstance((name := entry.get("name")), str) and name.strip()
    }
    configured_sidecar_tokens = {
        token
        for entry in entries
        for token in (
            optional_entry_text(entry, SIDECAR_ROLE_KEY),
            optional_entry_text(entry, SIDECAR_SLUG_KEY),
        )
        if token
    }
    defaults = (
        ("plans", f"{project_name}--plans", DEFAULT_PLANS_DESCRIPTION, True, True),
        ("beads", f"{project_name}--beads", DEFAULT_BEADS_DESCRIPTION, False, True),
    )
    for role, name, description, auto_clone, auto_sync in defaults:
        if name in configured_names or {role, name}.intersection(
            configured_sidecar_tokens
        ):
            continue
        merged.append(
            {
                "name": name,
                "path": f"../{name}",
                "description": description,
                "auto_clone": auto_clone,
                "auto_sync": auto_sync,
                DEFAULT_LINKED_REPO_MARKER: True,
                SIDECAR_REPO_MARKER: True,
                SIDECAR_ROLE_KEY: role,
                SIDECAR_SLUG_KEY: name,
                SIDECAR_REPO_REF_KEY: name,
                SIDECAR_REMOTE_URL_KEY: None,
            }
        )

    for hidden_role, hidden_description, hidden_visibility in (
        (AGENTS_SIDECAR_ROLE, DEFAULT_AGENTS_DESCRIPTION, "public"),
        (
            ATTACHMENTS_SIDECAR_ROLE,
            DEFAULT_ATTACHMENTS_DESCRIPTION,
            "public",
        ),
        (
            ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
            DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION,
            "private",
        ),
    ):
        if hidden_role == ATTACHMENTS_SIDECAR_ROLE and not _beads_public_for_injection(
            config if config is not None else local_config, merged
        ):
            continue
        hidden_identity = resolve_sidecar_repo_identity(
            {
                "name": hidden_role,
                DEFAULT_LINKED_REPO_MARKER: True,
            },
            primary_workspace_dir=primary_workspace_dir,
            default_entry=True,
            config=config if config is not None else local_config,
        )
        if hidden_identity is not None and not (
            hidden_identity.slug in configured_names
            or {hidden_role, hidden_identity.slug}.intersection(
                configured_sidecar_tokens
            )
        ):
            merged.append(
                {
                    "name": hidden_identity.slug,
                    "path": f"../{hidden_identity.slug}",
                    "description": hidden_description,
                    "auto_clone": False,
                    "auto_sync": False,
                    "visibility": hidden_visibility,
                    DEFAULT_LINKED_REPO_MARKER: True,
                    SIDECAR_REPO_MARKER: True,
                    SIDECAR_ROLE_KEY: hidden_role,
                    SIDECAR_SLUG_KEY: hidden_identity.slug,
                    SIDECAR_REPO_REF_KEY: hidden_identity.repo,
                    SIDECAR_REMOTE_URL_KEY: hidden_identity.remote_url,
                }
            )
    return merged


_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:")


def normalize_revision_pin(raw: Any) -> str | None:
    """Normalize a ``repos.linked[].revision_pin`` value.

    Returns the normalized relative POSIX-style path, or ``None`` when no
    pin is declared. Raises :class:`ValueError` for absolute paths and for
    paths that escape the primary checkout.
    """

    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("revision_pin must be a string")
    text = raw.strip().replace("\\", "/")
    if not text:
        raise ValueError("revision_pin must be a nonempty string")
    if (
        text.startswith("/")
        or text.startswith("~")
        or _DRIVE_ABSOLUTE_RE.match(text) is not None
    ):
        raise ValueError(f"revision_pin must be relative to the checkout: {raw!r}")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts:
        raise ValueError("revision_pin must be a nonempty string")
    stack: list[str] = []
    for part in parts:
        if part == "..":
            if not stack:
                raise ValueError(f"revision_pin must stay inside the checkout: {raw!r}")
            stack.pop()
        else:
            stack.append(part)
    if not stack:
        raise ValueError("revision_pin must be a nonempty string")
    return "/".join(stack)


def revision_pin_for_entry(entry: Mapping[str, Any]) -> str | None:
    """Return the normalized ``revision_pin`` for one linked entry, if any."""

    raw = entry.get(REVISION_PIN_CONFIG_KEY)
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        raise ValueError("revision_pin must be a nonempty string")
    return normalize_revision_pin(raw)


def revision_pin_escapes_primary(
    primary_dir: str | Path,
    normalized_pin: str,
) -> bool:
    """Return whether a normalized pin resolves outside *primary_dir*.

    The lexical normalizer already rejects absolute and ``..`` escapes, but
    a relative pin can still leave the checkout through a symlinked parent
    component or a symlinked pin file itself. This resolves the pin's
    parent (and the pin file when it exists) with :func:`os.path.realpath`
    and reports an escape when either resolves outside the resolved
    primary. Missing parents resolve lexically, so legitimate relative
    pins keep working. Any unexpected error fails closed as an escape.
    """

    try:
        primary_real = os.path.realpath(str(primary_dir))
        pin_abs = os.path.join(str(primary_dir), normalized_pin)
        parent_abs = os.path.dirname(pin_abs)
        parent_real = os.path.realpath(parent_abs)
        if parent_real != primary_real and not parent_real.startswith(
            primary_real + os.sep
        ):
            return True
        if os.path.lexists(pin_abs):
            pin_real = os.path.realpath(pin_abs)
            if pin_real != primary_real and not pin_real.startswith(
                primary_real + os.sep
            ):
                return True
            # A symlinked pin file inside the checkout that still resolves
            # inside is allowed; only an outside target escapes.
        return False
    except Exception:  # noqa: BLE001 - fail closed, never fail the caller
        return True
