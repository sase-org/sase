"""Pure helpers behind the Models panel's persistent alias **Edit** / **Reset**.

Phase 3 (epic sase-5e) lets the Models panel write a model alias's *persistent*
value in ``sase.yml`` (and reset it back to the implicit fallback). The actual
plan/validation/preview is shared domain logic and lives in the Rust core behind
:func:`sase.config.plan_config_edit`; this module only adds the two thin,
alias-specific pieces around it so the modal stays declarative and these can be
unit-tested without Textual:

- :func:`plan_alias_edit` — map a bare alias name to its
  ``llm_provider.model_aliases.<alias>`` config path and plan a set/unset edit
  against the default writable layer (chezmoi source remapping is applied by the
  Rust-backed planner).
- :func:`build_alias_commit_offer` — after a write, decide whether to offer a
  commit+push for the *actually written* file. Git-root detection on that path
  is what transparently handles both the ``use_chezmoi`` on branch (the written
  file is the chezmoi source inside the chezmoi repo) and the off branch (the
  user ``sase.yml``); returns ``None`` when the target is not in a git repo or
  has no pending changes, so the caller skips the offer gracefully.

No Textual imports: callable from a worker thread or a plain unit test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

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

#: Dotted config path to the ``additionalProperties`` map of model aliases.
MODEL_ALIASES_FIELD_PREFIX = "llm_provider.model_aliases"


def _alias_field_path(alias: str) -> str:
    """Return the dotted config path for the *alias* map key.

    For example ``_alias_field_path("coder")`` is
    ``"llm_provider.model_aliases.coder"``.
    """
    cleaned = alias.strip()
    if not cleaned:
        raise ValueError("alias name must be non-empty")
    return f"{MODEL_ALIASES_FIELD_PREFIX}.{cleaned}"


def plan_alias_edit(
    alias: str,
    op: ConfigEditOp,
    *,
    inventory: ConfigInventory | None = None,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan a set/unset edit of ``llm_provider.model_aliases.<alias>``.

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
        _alias_field_path(alias),
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


@dataclass(frozen=True)
class AliasCommitOffer:
    """A ready-to-run commit+push offer for a written alias edit."""

    git_root: str
    file_path: str
    rel_path: str
    message: str


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
    from sase.ace.tui.modals.xprompt_browser_helpers import (
        get_git_root,
        has_git_changes,
    )
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    git_root = get_git_root(target_path)
    if git_root is None or not has_git_changes(git_root, target_path):
        return None
    rel_path = os.path.relpath(target_path, git_root)
    verb = "Reset" if op == "unset" else "Update"
    subject = f"chore: {verb} model alias @{alias}"
    message = apply_auto_commit_type_tag(subject, "config")
    return AliasCommitOffer(
        git_root=git_root,
        file_path=target_path,
        rel_path=rel_path,
        message=message,
    )


__all__ = [
    "MODEL_ALIASES_FIELD_PREFIX",
    "AliasCommitOffer",
    "AliasEditOutcome",
    "build_alias_commit_offer",
    "plan_alias_edit",
]
