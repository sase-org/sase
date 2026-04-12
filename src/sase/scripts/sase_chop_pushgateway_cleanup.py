#!/usr/bin/env python3
"""Pushgateway stale group cleanup chop script."""

from sase.telemetry import cleanup_stale_groups


def main() -> None:
    cleanup_stale_groups()


if __name__ == "__main__":
    main()
