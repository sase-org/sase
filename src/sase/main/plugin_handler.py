"""Handler for ``sase plugin`` subcommands."""

from __future__ import annotations

import argparse
import json
import sys

from sase.plugins.chops import chop_inventory_to_dict, collect_chop_inventory
from sase.plugins.doctor import (
    aggregate_check_status,
    build_inventory_checks,
    build_plugin_doctor_report,
    doctor_check_to_dict,
    doctor_report_to_dict,
)
from sase.plugins.inventory import collect_plugin_inventory, plugin_inventory_to_dict
from sase.plugins.render import render_plugin_doctor, render_plugin_list


def handle_plugin_command(args: argparse.Namespace) -> None:
    """Dispatch ``sase plugin`` subcommands."""
    sub = getattr(args, "plugin_subcommand", None)
    if sub == "list":
        sys.exit(_handle_plugin_list(args))
    if sub == "doctor":
        sys.exit(_handle_plugin_doctor(args))

    print("Usage: sase plugin {doctor,list}", file=sys.stderr)
    sys.exit(1)


def _handle_plugin_list(args: argparse.Namespace) -> int:
    plugin_inventory = collect_plugin_inventory()
    chop_inventory = collect_chop_inventory()
    checks = build_inventory_checks(plugin_inventory, chop_inventory)

    if args.json:
        payload = {
            "schema_version": 1,
            "command": "list",
            "status": aggregate_check_status(checks),
            "plugins": plugin_inventory_to_dict(plugin_inventory),
            "chops": chop_inventory_to_dict(chop_inventory),
            "checks": [doctor_check_to_dict(check) for check in checks],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        render_plugin_list(
            plugin_inventory,
            chop_inventory,
            checks,
            verbose=bool(args.verbose),
        )
    return 0


def _handle_plugin_doctor(args: argparse.Namespace) -> int:
    report = build_plugin_doctor_report()

    if args.json:
        print(json.dumps(doctor_report_to_dict(report), indent=2, sort_keys=True))
    else:
        render_plugin_doctor(report, verbose=bool(args.verbose))
    return 1 if report.status == "ERROR" else 0
