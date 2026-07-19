"""Layer composition and provenance tracking for axe configuration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sase.config.core import ConfigLayer
from sase.core.axe_chop_facade import validate_axe_config

from ._config_types import AxeConfigDiagnostic


def _layer_label(layer: ConfigLayer) -> str:
    if layer.path:
        return f"{layer.name}:{layer.path}"
    return layer.name


def _clear_provenance_subtree(provenance: dict[str, str], path: str) -> None:
    prefix_dot = f"{path}." if path else ""
    prefix_index = f"{path}[" if path else "["
    for key in tuple(provenance):
        if key == path or key.startswith(prefix_dot) or key.startswith(prefix_index):
            provenance.pop(key, None)


def _record_provenance_tree(
    value: object,
    *,
    path: str,
    label: str,
    provenance: dict[str, str],
) -> None:
    provenance[path] = label
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _record_provenance_tree(
                child,
                path=child_path,
                label=label,
                provenance=provenance,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _record_provenance_tree(
                child,
                path=f"{path}[{index}]",
                label=label,
                provenance=provenance,
            )


def _merge_with_provenance(
    base: object,
    override: object,
    *,
    path: str,
    label: str,
    list_strategy: str,
    provenance: dict[str, str],
) -> object:
    """Mirror config merge semantics while retaining exact source paths."""
    if isinstance(base, dict) and isinstance(override, dict):
        dict_result = deepcopy(base)
        provenance[path] = label
        for key, value in override.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in dict_result:
                dict_result[key] = _merge_with_provenance(
                    dict_result[key],
                    value,
                    path=child_path,
                    label=label,
                    list_strategy=list_strategy,
                    provenance=provenance,
                )
            else:
                dict_result[key] = deepcopy(value)
                _record_provenance_tree(
                    value,
                    path=child_path,
                    label=label,
                    provenance=provenance,
                )
        return dict_result

    if isinstance(base, list) and isinstance(override, list):
        if list_strategy == "replace":
            _clear_provenance_subtree(provenance, path)
            list_result = deepcopy(override)
            _record_provenance_tree(
                list_result,
                path=path,
                label=label,
                provenance=provenance,
            )
            return list_result
        list_result = deepcopy(base)
        provenance[path] = label
        offset = len(list_result)
        list_result.extend(deepcopy(override))
        for index, child in enumerate(override, start=offset):
            _record_provenance_tree(
                child,
                path=f"{path}[{index}]",
                label=label,
                provenance=provenance,
            )
        return list_result

    _clear_provenance_subtree(provenance, path)
    scalar_result = deepcopy(override)
    _record_provenance_tree(
        scalar_result,
        path=path,
        label=label,
        provenance=provenance,
    )
    return scalar_result


def map_form_chop_layers(layers: list[ConfigLayer]) -> bool:
    """Return whether any raw layer needs keyed chop composition."""
    for layer in layers:
        axe = layer.data.get("axe") if isinstance(layer.data, dict) else None
        lumberjacks = axe.get("lumberjacks") if isinstance(axe, dict) else None
        if not isinstance(lumberjacks, dict):
            continue
        for config in lumberjacks.values():
            if isinstance(config, dict) and isinstance(config.get("chops"), dict):
                return True
    return False


def has_map_form_chops(data: dict[str, Any]) -> bool:
    axe = data.get("axe")
    lumberjacks = axe.get("lumberjacks") if isinstance(axe, dict) else None
    if not isinstance(lumberjacks, dict):
        return False
    return any(
        isinstance(config, dict) and isinstance(config.get("chops"), dict)
        for config in lumberjacks.values()
    )


def _normalize_layer_chop_lists(
    layer: ConfigLayer,
) -> tuple[dict[str, Any], set[str], list[AxeConfigDiagnostic]]:
    """Normalize one layer's legacy chop lists into keyed maps for merging."""
    data = deepcopy(layer.data)
    replacement_paths: set[str] = set()
    diagnostics: list[AxeConfigDiagnostic] = []
    axe = data.get("axe") if isinstance(data, dict) else None
    lumberjacks = axe.get("lumberjacks") if isinstance(axe, dict) else None
    if not isinstance(lumberjacks, dict):
        return data, replacement_paths, diagnostics

    for lumberjack_name, config in lumberjacks.items():
        if not isinstance(config, dict):
            continue
        raw_chops = config.get("chops")
        if not isinstance(raw_chops, list):
            continue
        keyed: dict[str, dict[str, Any]] = {}
        for entry in raw_chops:
            if isinstance(entry, str):
                chop_name = entry
                chop_config: dict[str, Any] = {}
            elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
                chop_name = str(entry["name"])
                chop_config = deepcopy(entry)
            else:
                # The shared validator emits the authoritative shape error.
                continue
            if chop_name in keyed:
                # The raw-layer core validation emits the authoritative
                # duplicate diagnostic with the original list index.
                continue
            keyed[chop_name] = chop_config
        config["chops"] = keyed
        if layer.list_strategy == "replace":
            replacement_paths.add(f"axe.lumberjacks.{lumberjack_name}.chops")
    return data, replacement_paths, diagnostics


def _clear_mapping_path(data: dict[str, Any], path: str) -> None:
    components = path.split(".")
    cursor: dict[str, Any] = data
    for component in components[:-1]:
        child = cursor.get(component)
        if not isinstance(child, dict):
            return
        cursor = child
    cursor.pop(components[-1], None)


def compose_keyed_axe_layers(
    layers: list[ConfigLayer],
) -> tuple[dict[str, Any], dict[str, str], list[AxeConfigDiagnostic]]:
    """Compose keyed chops across raw layers with per-field provenance."""
    merged: object = {}
    provenance: dict[str, str] = {}
    diagnostics: list[AxeConfigDiagnostic] = []
    for layer in layers:
        if not isinstance(layer.data, dict) or "axe" not in layer.data:
            continue
        label = _layer_label(layer)
        raw_diagnostics = validate_axe_config(
            {"axe": layer.data["axe"]},
            provenance={"axe": label},
        )
        diagnostics.extend(
            AxeConfigDiagnostic.from_wire(item) for item in raw_diagnostics
        )
        raw_axe = layer.data["axe"]
        raw_lumberjacks = (
            raw_axe.get("lumberjacks") if isinstance(raw_axe, dict) else None
        )
        if isinstance(raw_lumberjacks, dict) and layer.list_strategy != "replace":
            merged_axe = merged.get("axe") if isinstance(merged, dict) else None
            merged_lumberjacks = (
                merged_axe.get("lumberjacks") if isinstance(merged_axe, dict) else None
            )
            for lumberjack_name, raw_config in raw_lumberjacks.items():
                raw_chops = (
                    raw_config.get("chops") if isinstance(raw_config, dict) else None
                )
                if not isinstance(raw_chops, list):
                    continue
                existing_config = (
                    merged_lumberjacks.get(lumberjack_name)
                    if isinstance(merged_lumberjacks, dict)
                    else None
                )
                existing_chops = (
                    existing_config.get("chops")
                    if isinstance(existing_config, dict)
                    else None
                )
                existing_names = (
                    set(existing_chops) if isinstance(existing_chops, dict) else set()
                )
                for index, raw_chop in enumerate(raw_chops):
                    identity = (
                        raw_chop
                        if isinstance(raw_chop, str)
                        else raw_chop.get("name")
                        if isinstance(raw_chop, dict)
                        else None
                    )
                    if isinstance(identity, str) and identity in existing_names:
                        diagnostics.append(
                            AxeConfigDiagnostic(
                                code="duplicate_chop_identity",
                                message=f"duplicate chop identity `{identity}`",
                                path=(
                                    f"axe.lumberjacks.{lumberjack_name}.chops[{index}]"
                                ),
                                layer=label,
                            )
                        )
        normalized, replacement_paths, layer_diagnostics = _normalize_layer_chop_lists(
            layer
        )
        diagnostics.extend(layer_diagnostics)
        if isinstance(merged, dict):
            for path in replacement_paths:
                _clear_mapping_path(merged, path)
                _clear_provenance_subtree(provenance, path)
        merged = _merge_with_provenance(
            merged,
            {"axe": normalized["axe"]},
            path="",
            label=label,
            list_strategy=layer.list_strategy,
            provenance=provenance,
        )
    unique_diagnostics = list(
        {
            (item.code, item.path, item.layer, item.message): item
            for item in diagnostics
        }.values()
    )
    unique_diagnostics.sort(
        key=lambda item: (item.path or "", item.code, item.layer or "")
    )
    return (
        merged if isinstance(merged, dict) else {},
        provenance,
        unique_diagnostics,
    )


def build_axe_config_provenance(layers: list[ConfigLayer]) -> dict[str, str]:
    """Build dotted-path provenance for the effective ``axe:`` section."""
    merged: object = {}
    provenance: dict[str, str] = {}
    for layer in layers:
        if not isinstance(layer.data, dict) or "axe" not in layer.data:
            continue
        merged = _merge_with_provenance(
            merged,
            {"axe": layer.data["axe"]},
            path="",
            label=_layer_label(layer),
            list_strategy=layer.list_strategy,
            provenance=provenance,
        )
    return provenance
