"""Plan and execute a single config edit.

The *decision* logic — target file, dotted key path, set-vs-unset, the
candidate merged config, the effective-merge preview, and schema validation of
the candidate — is shared domain logic and lives in the Rust core
(``config_plan_edit``). This module wraps that and adds the two Python-only
pieces:

- the **target-file text diff** preview, produced by applying the edit in
  memory with ``ruamel.yaml`` (comment/order/quote preserving) and diffing the
  old vs. new text — no write happens during planning; and
- the **source-preserving write** itself (:func:`apply_config_edit`), which
  writes the exact text the diff previewed to the chezmoi-resolved target.

"Reset to default" is modeled as an ``unset`` of the key in the chosen mutable
scope (the key is deleted, not overwritten with the literal default), so the
lower-priority layer's value — ultimately the schema default — becomes
effective again.

No Textual imports: callable from a worker thread. :func:`apply_config_edit` is
side-effecting and must only run from a tracked background task.
"""

from __future__ import annotations

import dataclasses
import difflib
from collections.abc import MutableMapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.config.core import (
    DEPRECATED_TOP_LEVEL_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    get_use_chezmoi,
)
from sase.config.inventory import ConfigDiagnostic, ConfigInventory
from sase.config.targets import resolve_write_path
from sase.core.rust import require_rust_binding


if TYPE_CHECKING:
    from ruamel.yaml import YAML


class ConfigEditError(RuntimeError):
    """Raised when a config edit cannot be planned or applied."""


# --- Edit operation -------------------------------------------------------


@dataclass(frozen=True)
class ConfigEditOp:
    """A set/unset operation on a field.

    Use :meth:`set_value` to assign a value or :meth:`unset` to remove the key
    (the latter is also how "reset to default" is expressed).
    """

    kind: str
    value: Any = None

    @classmethod
    def set_value(cls, value: Any) -> ConfigEditOp:
        """An operation that sets the field to *value*."""
        return cls("set", value)

    @classmethod
    def unset(cls) -> ConfigEditOp:
        """An operation that removes the field from the target layer."""
        return cls("unset")

    def to_wire(self) -> dict[str, Any]:
        if self.kind == "unset":
            return {"kind": "unset"}
        return {"kind": "set", "value": self.value}


# --- Source-preserving YAML writer ----------------------------------------


def _yaml() -> YAML:
    """Build a round-trip YAML handler that preserves comments and quotes.

    ``ruamel.yaml`` is imported lazily so merely importing this module (and
    therefore ``sase.config``) stays cheap on every CLI/TUI startup; the cost is
    paid only when a config write is actually planned or executed.
    """
    from ruamel.yaml import YAML

    handler = YAML()
    handler.preserve_quotes = True
    # Avoid ruamel re-wrapping long scalars (e.g. descriptions / paths).
    handler.width = 4096
    return handler


def _dump(handler: YAML, data: Any) -> str:
    buffer = StringIO()
    handler.dump(data, buffer)
    return buffer.getvalue()


def set_key(text: str, key_path: tuple[str, ...], value: Any) -> str:
    """Return *text* with *value* set at *key_path*, preserving formatting.

    Intermediate mappings are created as needed. Comments, key order, and quote
    style elsewhere in the document are preserved by the round-trip loader.
    """
    from ruamel.yaml.comments import CommentedMap

    if not key_path:
        raise ConfigEditError("cannot set an empty key path")
    handler = _yaml()
    data = handler.load(text) if text.strip() else None
    if not isinstance(data, MutableMapping):
        data = CommentedMap()
    node: MutableMapping[Any, Any] = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            child = CommentedMap()
            node[segment] = child
        node = child
    node[key_path[-1]] = value
    return _dump(handler, data)


def unset_key(text: str, key_path: tuple[str, ...]) -> str:
    """Return *text* with the key at *key_path* removed, preserving formatting.

    A no-op (returns *text* unchanged) when the document is empty or the path
    does not resolve to an existing key.
    """
    if not key_path or not text.strip():
        return text
    handler = _yaml()
    data = handler.load(text)
    if not isinstance(data, MutableMapping):
        return text
    node: MutableMapping[Any, Any] = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            return text
        node = child
    last = key_path[-1]
    if last not in node:
        return text
    del node[last]
    return _dump(handler, data)


# --- Edit plan ------------------------------------------------------------


@dataclass(frozen=True)
class ConfigWritePlan:
    """The logical, frontend-agnostic write plan from the Rust core."""

    file: str | None
    layer: str
    key_path: tuple[str, ...]
    op: str
    has_value: bool
    new_value: Any

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigWritePlan:
        return cls(
            file=payload.get("file"),
            layer=payload["layer"],
            key_path=tuple(payload["key_path"]),
            op=payload["op"],
            has_value=payload["has_value"],
            new_value=payload["new_value"],
        )


@dataclass(frozen=True)
class ConfigEffectivePreview:
    """The before/after effective value for the edited field."""

    path: str
    has_before: bool
    before: Any
    has_after: bool
    after: Any
    changed: bool

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigEffectivePreview:
        return cls(
            path=payload["path"],
            has_before=payload["has_before"],
            before=payload["before"],
            has_after=payload["has_after"],
            after=payload["after"],
            changed=payload["changed"],
        )


@dataclass(frozen=True)
class EditPlanResult:
    """The full result of planning a config edit (no write performed).

    Combines the Rust write-plan/preview/validation with the Python-computed
    target-file text diff. ``new_text`` is exactly what :func:`apply_config_edit`
    writes, so the previewed diff and the written bytes can never disagree.
    """

    schema_version: int
    write_plan: ConfigWritePlan
    candidate_config: dict[str, Any]
    effective_preview: ConfigEffectivePreview
    validation: tuple[ConfigDiagnostic, ...]
    diagnostics: tuple[ConfigDiagnostic, ...]
    target_path: str | None
    used_chezmoi: bool
    current_text: str
    new_text: str
    text_diff: str

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when the candidate config has no validation errors."""
        return not any(d.severity == "error" for d in self.validation)


def _apply_to_text(text: str, write_plan: ConfigWritePlan) -> str:
    if write_plan.op == "set":
        return set_key(text, write_plan.key_path, write_plan.new_value)
    return unset_key(text, write_plan.key_path)


def _unified_diff(old: str, new: str, target: Path | None) -> str:
    label = str(target) if target is not None else "config"
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
        )
    )


def plan_config_edit(
    inventory: ConfigInventory,
    path: str,
    target: str,
    op: ConfigEditOp,
    *,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan a single set/unset edit against *target* layer for field *path*.

    Calls the Rust core for the write-plan, candidate merged config, effective
    preview, and validation, then computes the target-file text diff in memory
    (chezmoi source remapping is applied to the write target). No file is
    written.

    Args:
        inventory: The inventory built by
            :func:`sase.config.inventory.build_config_inventory` (carries the
            schema + layer stack needed to re-plan).
        path: Dotted field path to edit.
        target: Name of the writable target layer.
        op: The set/unset operation.
        use_chezmoi: Override chezmoi remapping; defaults to the effective
            ``use_chezmoi`` config value.

    Raises:
        ConfigEditError: when the Rust core rejects the request (e.g. an
            unknown target layer).
    """
    request = {
        "schema": inventory.schema,
        "layers": list(inventory.layer_inputs),
        "target_layer": target,
        "path": path,
        "op": op.to_wire(),
        "deprecations": dict(DEPRECATED_TOP_LEVEL_KEYS),
        "unsupported": sorted(UNSUPPORTED_TOP_LEVEL_KEYS),
    }
    binding = require_rust_binding("config_plan_edit")
    try:
        payload = binding(request)
    except ValueError as exc:
        raise ConfigEditError(str(exc)) from exc

    write_plan = ConfigWritePlan.from_wire(payload["write_plan"])

    chezmoi = get_use_chezmoi() if use_chezmoi is None else use_chezmoi
    write_path = resolve_write_path(write_plan.file, use_chezmoi=chezmoi)
    current_text = (
        write_path.read_text(encoding="utf-8")
        if write_path is not None and write_path.is_file()
        else ""
    )
    new_text = _apply_to_text(current_text, write_plan)
    text_diff = _unified_diff(current_text, new_text, write_path)

    return EditPlanResult(
        schema_version=payload["schema_version"],
        write_plan=write_plan,
        candidate_config=payload["candidate_config"],
        effective_preview=ConfigEffectivePreview.from_wire(
            payload["effective_preview"]
        ),
        validation=tuple(
            ConfigDiagnostic.from_wire(item) for item in payload["validation"]
        ),
        diagnostics=tuple(
            ConfigDiagnostic.from_wire(item) for item in payload["diagnostics"]
        ),
        target_path=str(write_path) if write_path is not None else None,
        used_chezmoi=chezmoi,
        current_text=current_text,
        new_text=new_text,
        text_diff=text_diff,
    )


# --- Deprecated-key migration ---------------------------------------------


def _migration_target_layer(inventory: ConfigInventory) -> dict[str, Any] | None:
    """The highest-priority writable layer that sets ``sibling_repos``.

    Layer inputs are ordered low → high priority, so the last writable match
    is the one whose ``sibling_repos`` value actually wins. Returns ``None``
    when no writable layer sets the deprecated key (nothing to migrate).
    """
    match: dict[str, Any] | None = None
    for layer in inventory.layer_inputs:
        value = layer.get("value")
        if (
            layer.get("writable")
            and isinstance(value, dict)
            and "sibling_repos" in value
        ):
            match = layer
    return match


def plan_repo_key_migration(
    inventory: ConfigInventory, *, use_chezmoi: bool | None = None
) -> EditPlanResult | None:
    """Plan the ``sibling_repos`` → ``linked_repos`` migration.

    Folds the deprecated ``sibling_repos`` list into ``linked_repos`` in the
    one writable file where it is set: ``linked_repos`` becomes that file's
    existing ``linked_repos`` followed by its ``sibling_repos`` entries, and
    ``sibling_repos`` is removed. Reuses :func:`plan_config_edit` for the
    ``linked_repos`` write-plan, candidate merge, effective preview, and
    validation, then folds the ``sibling_repos`` removal into ``new_text`` /
    ``text_diff`` so the previewed diff and the written bytes still agree.

    Returns ``None`` when no writable layer sets ``sibling_repos``.
    """
    target = _migration_target_layer(inventory)
    if target is None:
        return None
    value = target["value"]
    existing = value.get("linked_repos")
    siblings = value.get("sibling_repos")
    existing_list = list(existing) if isinstance(existing, list) else []
    sibling_list = list(siblings) if isinstance(siblings, list) else []
    new_linked = [*existing_list, *sibling_list]

    plan = plan_config_edit(
        inventory,
        "linked_repos",
        target["name"],
        ConfigEditOp.set_value(new_linked),
        use_chezmoi=use_chezmoi,
    )
    combined_text = unset_key(plan.new_text, ("sibling_repos",))
    write_path = Path(plan.target_path) if plan.target_path is not None else None
    combined_diff = _unified_diff(plan.current_text, combined_text, write_path)
    return dataclasses.replace(plan, new_text=combined_text, text_diff=combined_diff)


# --- Write execution ------------------------------------------------------


@dataclass(frozen=True)
class AppliedResult:
    """The outcome of a source-preserving config write."""

    path: str
    op: str
    key_path: tuple[str, ...]
    created: bool
    used_chezmoi: bool


def apply_config_edit(plan: EditPlanResult) -> AppliedResult:
    """Write the planned edit to disk (source-preserving).

    Writes exactly ``plan.new_text`` to the chezmoi-resolved ``plan.target_path``
    that the diff previewed, creating parent directories as needed. Side
    effecting; only ever call from a tracked background task.

    Raises:
        ConfigEditError: when the plan has no writable target file.
    """
    if plan.target_path is None:
        raise ConfigEditError("edit plan has no writable target file")
    path = Path(plan.target_path)
    created = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.new_text, encoding="utf-8")
    return AppliedResult(
        path=str(path),
        op=plan.write_plan.op,
        key_path=plan.write_plan.key_path,
        created=created,
        used_chezmoi=plan.used_chezmoi,
    )
