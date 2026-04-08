"""``sase telemetry export-config`` — export bundled monitoring config."""

from __future__ import annotations

import argparse
import importlib.abc
import importlib.resources
import shutil
import sys
from pathlib import Path

from rich.console import Console


def _copy_tree(src: importlib.abc.Traversable, dest: Path) -> list[Path]:
    """Recursively copy a Traversable tree to *dest*, returning written paths."""
    written: list[Path] = []
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            written.extend(_copy_tree(item, target))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
            written.append(target)
    return written


def handle_telemetry_export_config(args: argparse.Namespace) -> None:
    """Copy the bundled monitoring config to a user-specified directory."""
    output_dir = Path(getattr(args, "output_dir", None) or "./sase-monitoring")
    force: bool = getattr(args, "force", False)
    console = Console()

    if output_dir.exists() and not force:
        console.print(
            f"[red]Directory already exists:[/red] {output_dir}\n"
            "[dim]Use --force / -f to overwrite.[/dim]"
        )
        sys.exit(1)

    if output_dir.exists() and force:
        shutil.rmtree(output_dir)

    monitoring = importlib.resources.files("sase.telemetry").joinpath("monitoring")
    output_dir.mkdir(parents=True, exist_ok=True)
    written = _copy_tree(monitoring, output_dir)

    console.print(f"[green]Wrote {len(written)} files to {output_dir}/[/green]\n")
    for path in sorted(written):
        console.print(f"  {path}")
    console.print(
        f"\n[cyan]Next steps:[/cyan]\n  cd {output_dir} && docker compose up -d"
    )
