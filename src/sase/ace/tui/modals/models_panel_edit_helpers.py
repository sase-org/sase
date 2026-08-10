"""Pure helpers behind the Models panel's persistent alias **Edit** / **Reset**.

Phase 3 (epic sase-5e) lets the Models panel write a model alias's *persistent*
value in ``sase.yml`` (and reset it back to the implicit fallback). The actual
plan/validation/preview is shared domain logic and lives in the Rust core behind
:func:`sase.config.plan_config_edit`; this module only adds the two thin,
alias-specific pieces around it so the modal stays declarative and these can be
unit-tested without Textual:

- :func:`plan_alias_edit` — map a bare alias name to its
  ``llm_provider.model_aliases.builtin.<alias>`` config path and plan a
  set/unset edit against the default writable layer (chezmoi source remapping is
  applied by the Rust-backed planner).
- :func:`build_alias_commit_offer` — after a write, decide whether to offer a
  commit+push for the *actually written* file. Git-root detection on that path
  is what transparently handles both the ``use_chezmoi`` on branch (the written
  file is the chezmoi source inside the chezmoi repo) and the off branch (the
  user ``sase.yml``); returns ``None`` when the target is not in a git repo or
  has no pending changes, so the caller skips the offer gracefully.

No Textual imports: callable from a worker thread or a plain unit test.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.llm_provider import AliasKind

from sase.config import (
    AppliedResult,
    ConfigEditError,
    ConfigEditOp,
    ConfigInventory,
    EditPlanResult,
    build_config_inventory,
    default_target_layer,
    plan_config_edit,
)

from .config_commit import ConfigCommitOffer, build_config_commit_offer

#: Dotted config paths to the ``additionalProperties`` maps of model aliases.
MODEL_ALIASES_FIELD_PREFIX = "llm_provider.model_aliases.builtin"
CUSTOM_MODEL_ALIASES_FIELD_PREFIX = "llm_provider.model_aliases.custom"


def _alias_field_path(alias: str) -> str:
    """Return the dotted config path for the *alias* map key.

    For example ``_alias_field_path("medium_worker")`` is
    ``"llm_provider.model_aliases.builtin.medium_worker"``.
    """
    cleaned = alias.strip()
    if not cleaned:
        raise ValueError("alias name must be non-empty")
    return f"{MODEL_ALIASES_FIELD_PREFIX}.{cleaned}"


def _custom_alias_field_path(alias: str, field: str | None = None) -> str:
    """Return the dotted config path for a custom alias or child field."""
    cleaned = alias.strip()
    if not cleaned:
        raise ValueError("alias name must be non-empty")
    path = f"{CUSTOM_MODEL_ALIASES_FIELD_PREFIX}.{cleaned}"
    return f"{path}.{field}" if field else path


def alias_model_edit_path(
    alias: str,
    *,
    kind: AliasKind,
    configured_source: str | None,
) -> str:
    """Return the config path for an Edit action on *alias*."""
    if kind == "user" and configured_source == "custom":
        return _custom_alias_field_path(alias, "model")
    return _alias_field_path(alias)


def alias_reset_path(
    alias: str,
    *,
    kind: AliasKind,
    configured_source: str | None,
) -> str:
    """Return the config path for a Reset action on *alias*."""
    if kind == "user" and configured_source == "custom":
        return _custom_alias_field_path(alias)
    return _alias_field_path(alias)


def plan_alias_edit(
    alias: str,
    op: ConfigEditOp,
    *,
    path: str | None = None,
    inventory: ConfigInventory | None = None,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan a set/unset edit of one model-alias config path.

    Builds the config inventory when one is not supplied, targets the default
    writable layer (typically the user ``sase.yml``), and delegates to the
    Rust-backed :func:`sase.config.plan_config_edit` — which validates the
    candidate, computes the effective before/after, and applies chezmoi source
    remapping to the write target. No file is written.

    Raises:
        ConfigEditError: when no writable config layer is available, or when the
            Rust core rejects the request.
    """
    inv = inventory if inventory is not None else build_config_inventory()
    target = default_target_layer(inv)
    if target is None:
        raise ConfigEditError("no writable config layer available")
    return plan_config_edit(
        inv,
        path or _alias_field_path(alias),
        target,
        op,
        use_chezmoi=use_chezmoi,
    )


@dataclass(frozen=True)
class AliasEditOutcome:
    """The result handed back to the Models panel after a persistent edit.

    ``applied`` is the source-preserving write result (its ``path`` is the file
    that was actually written — the chezmoi source when ``use_chezmoi`` is on).
    """

    alias: str
    applied: AppliedResult


AliasCommitOffer = ConfigCommitOffer


def build_alias_commit_offer(
    target_path: str,
    *,
    op: str,
    alias: str,
) -> AliasCommitOffer | None:
    """Return the commit+push offer for a written alias edit, or ``None``.

    ``None`` means the offer should be skipped gracefully — the written file is
    not inside a git repo, or it has no pending changes. The same logic serves
    both ``use_chezmoi`` branches: *target_path* is whatever was actually
    written (the chezmoi source inside the chezmoi repo when enabled, else the
    user ``sase.yml``), so git-root detection on it is what distinguishes them.

    Args:
        target_path: The file that was written (``AppliedResult.path``).
        op: The write op — ``"set"`` (Edit) or ``"unset"`` (Reset).
        alias: The bare alias name, used in the commit subject.
    """
    verb = "Reset" if op == "unset" else "Update"
    subject = f"chore: {verb} model alias @{alias}"
    return build_config_commit_offer(target_path, subject=subject)


__all__ = [
    "CUSTOM_MODEL_ALIASES_FIELD_PREFIX",
    "MODEL_ALIASES_FIELD_PREFIX",
    "AliasCommitOffer",
    "AliasEditOutcome",
    "alias_model_edit_path",
    "alias_reset_path",
    "build_alias_commit_offer",
    "plan_alias_edit",
]
