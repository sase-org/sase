"""Handler for the ``sase version`` command."""

from __future__ import annotations

import argparse
import json

from sase.version.inventory import collect_runtime_version_inventory
from sase.version.render import (
    render_runtime_version_inventory,
    runtime_version_inventory_to_json_payload,
)


def handle_version_command(args: argparse.Namespace) -> int:
    """Handle ``sase version``."""
    inventory = collect_runtime_version_inventory()

    if args.json:
        print(
            json.dumps(
                runtime_version_inventory_to_json_payload(inventory),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        render_runtime_version_inventory(inventory, verbose=bool(args.verbose))

    return 0
