"""Handler for the 'sase config' command."""

import argparse
import sys


def handle_config_command(args: argparse.Namespace) -> None:
    """Handle the 'sase config' subcommands."""
    config_sub = getattr(args, "config_subcommand", None)

    if config_sub == "layers":
        from sase.config.core import load_config_layers

        layers = load_config_layers()
        for layer in layers:
            status = "loaded" if layer.exists else "not found"
            path_str = layer.path or "(built-in)"
            print(f"--- {layer.name} [{status}] ---")
            print(f"  path: {path_str}")
            print(f"  list_strategy: {layer.list_strategy}")
            if layer.exists and layer.keys:
                print(f"  keys: {', '.join(layer.keys)}")
            print()
        sys.exit(0)

    elif config_sub == "mentor-match":
        from sase.ace.changespec import find_all_changespecs
        from sase.ace.scheduler.mentor_profile_matching import (
            trace_profile_matching,
        )

        all_changespecs = find_all_changespecs()
        target = None
        for cs in all_changespecs:
            if cs.name == args.changespec_name:
                target = cs
                break

        if target is None:
            print(f"ChangeSpec not found: {args.changespec_name}")
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
        print("Usage: sase config {layers,mentor-match,show}")
        sys.exit(1)
