"""Helpers for parser tests that know their top-level command."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from sase.main.parser import create_parser, parser_only_hint


def parse_sase_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse *argv* through the same narrow-parser hint the CLI entry point uses."""

    return create_parser(only=parser_only_hint(["sase", *argv])).parse_args(argv)
