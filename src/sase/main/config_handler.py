"""Handler for the 'sase config' command."""

import argparse
import sys


def handle_config_command(args: argparse.Namespace) -> None:
    """Handle the 'sase config' subcommands."""
    config_sub = getattr(args, "config_subcommand", None)

    if config_sub == "init":
        from .config_init_handler import run_config_init

        sys.exit(run_config_init(args))

    elif config_sub == "layers":
        from sase.config.core import DEPRECATED_TOP_LEVEL_KEYS, load_config_layers

        layers = load_config_layers()
        for layer in layers:
            status = "loaded" if layer.exists else "not found"
            path_str = layer.path or "(built-in)"
            print(f"--- {layer.name} [{status}] ---")
            print(f"  path: {path_str}")
            print(f"  list_strategy: {layer.list_strategy}")
            if layer.exists and layer.keys:
                print(f"  keys: {', '.join(layer.keys)}")
            if layer.unsupported_keys:
                print(
                    f"  unsupported keys (ignored): {', '.join(layer.unsupported_keys)}"
                )
            for deprecated_key in layer.deprecated_keys:
                replacement = DEPRECATED_TOP_LEVEL_KEYS[deprecated_key]
                print(f"  deprecated key: {deprecated_key} (rename to '{replacement}')")
            if layer.retired_keys:
                print(
                    f"  retired keys (ignored; remove): {', '.join(layer.retired_keys)}"
                )
            print()
        sys.exit(0)

    elif config_sub == "mentor-match":
        from sase.ace.patch import find_all_patches
        from sase.ace.scheduler.mentor_profile_matching import (
            trace_profile_matching,
        )

        all_patches = find_all_patches()
        target = None
        for cs in all_patches:
            if cs.name == args.patch_name:
                target = cs
                break

        if target is None:
            print(f"Patch not found: {args.patch_name}")
            sys.exit(1)

        traces = trace_profile_matching(target)
        if not traces:
            print("No mentor profiles loaded in merged config.")
            sys.exit(0)

        for t in traces:
            match_str = "MATCH" if t.overall_match else "NO MATCH"
            print(f"--- {t.profile_name}: {match_str} ---")
            for cr in t.criteria_results:
                if not cr.configured:
                    print(f"  {cr.criterion}: (not configured)")
                    continue
                result = "MATCH" if cr.matched else "NO MATCH"
                detail = f" — {cr.details}" if cr.details else ""
                print(f"  {cr.criterion}: {result}{detail}")
            print()
        sys.exit(0)

    elif config_sub == "migrate-keymap-actions":
        from pathlib import Path

        import yaml  # type: ignore[import-untyped]

        from sase.ace.tui.keymaps.registry import LEGACY_APP_KEY_ALIASES
        from sase.config._edit_yaml import set_key, unset_key
        from sase.config.core import load_config_layers

        migrated_paths: list[str] = []
        for layer in load_config_layers():
            if not layer.loaded or not layer.path:
                continue
            path = Path(layer.path)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            data = yaml.safe_load(text) or {}
            if not isinstance(data, dict):
                continue
            ace_cfg = data.get("ace")
            keymaps_cfg = ace_cfg.get("keymaps") if isinstance(ace_cfg, dict) else None
            app_overrides = (
                keymaps_cfg.get("app") if isinstance(keymaps_cfg, dict) else None
            )
            if not isinstance(app_overrides, dict):
                continue

            updated_text = text
            changed = False
            for legacy, canonical in LEGACY_APP_KEY_ALIASES.items():
                if legacy not in app_overrides:
                    continue
                if canonical in app_overrides:
                    print(
                        f"{path}: skipping {legacy} -> {canonical} "
                        f"({canonical} is already configured)"
                    )
                    continue
                value = app_overrides[legacy]
                updated_text = set_key(
                    updated_text, ("ace", "keymaps", "app", canonical), value
                )
                updated_text = unset_key(
                    updated_text, ("ace", "keymaps", "app", legacy)
                )
                changed = True
            if changed and updated_text != text:
                path.write_text(updated_text, encoding="utf-8")
                migrated_paths.append(str(path))

        if migrated_paths:
            print("Migrated renamed keymap actions in:")
            for migrated_path in migrated_paths:
                print(f"  {migrated_path}")
        else:
            print("No renamed keymap actions found in any config layer.")
        sys.exit(0)

    elif config_sub == "show":
        from sase.config.core import load_merged_config

        import yaml  # type: ignore[import-untyped]

        merged = load_merged_config()
        key = getattr(args, "key", None)
        if key:
            if key not in merged:
                print(f"Key not found: {key}")
                print(f"Available keys: {', '.join(sorted(merged.keys()))}")
                sys.exit(1)
            print(yaml.dump({key: merged[key]}, default_flow_style=False), end="")
        else:
            print(yaml.dump(merged, default_flow_style=False), end="")
        sys.exit(0)

    else:
        print(
            "Usage: sase config {init,layers,mentor-match,migrate-keymap-actions,show}"
        )
        sys.exit(1)
