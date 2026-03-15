"""Handler for the ``sase image`` CLI subcommand."""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from sase.image_generation import generate_image
from sase.notifications.senders import notify_image_generated


def handle_image_command(args: argparse.Namespace) -> NoReturn:
    """Generate an image from a text prompt and optionally notify the user."""
    prompt = " ".join(args.prompt or []).strip()

    if not prompt and not sys.stdin.isatty():
        try:
            prompt = sys.stdin.read().strip()
        except OSError:
            prompt = ""

    if not prompt:
        print("Error: image prompt is required", file=sys.stderr)
        sys.exit(1)

    try:
        output_path, _mime_type = generate_image(
            prompt,
            model=args.model,
            output_dir=args.output_dir,
        )
    except Exception as e:
        print(f"Error generating image: {e}", file=sys.stderr)
        sys.exit(1)

    if not args.no_notify:
        notify_image_generated(
            prompt=prompt,
            model=args.model,
            image_file=str(output_path),
        )

    print(output_path)
    sys.exit(0)
