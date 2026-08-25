"""CLI wrapper for ``sase memory web migrate``."""

from __future__ import annotations

import argparse
import sys

from sase.memory.web.migrate import (
    MemoryWebMigrationError,
    migrate_memory_web,
    render_migration_report,
)


def handle_memory_web_migrate_command(args: argparse.Namespace) -> None:
    """Migrate a supported config-backed memory web into strand files."""

    try:
        report = migrate_memory_web(
            args.web,
            project_ref=getattr(args, "project", None),
            dry_run=getattr(args, "dry_run", False),
        )
    except MemoryWebMigrationError as exc:
        print(f"sase memory web migrate: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(render_migration_report(report))


__all__ = ["handle_memory_web_migrate_command"]
