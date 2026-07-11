"""Handler for ``sase plan list``."""

from __future__ import annotations

import argparse
import json
import sys

from sase.main.plan_inventory import (
    build_plan_inventory,
    plan_inventory_to_json,
    render_plan_inventory,
)


def handle_plan_list_command(args: argparse.Namespace) -> None:
    """Render the plan proposal/approval inventory."""
    try:
        inventory = build_plan_inventory(tiers=tuple(getattr(args, "tier", ()) or ()))
    except Exception as exc:
        print(f"sase plan list: cannot read plan inventory: {exc}", file=sys.stderr)
        sys.exit(1)

    if bool(getattr(args, "json", False)):
        json.dump(plan_inventory_to_json(inventory), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    render_plan_inventory(inventory)
