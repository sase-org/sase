#!/usr/bin/env python3
"""Pushgateway stale group cleanup chop script."""

from sase.telemetry import cleanup_stale_groups


def main() -> None:
    deleted = cleanup_stale_groups()
    reason = "" if deleted else " reason=no_stale_groups_or_telemetry_disabled"
    print(f"pushgateway_cleanup: deleted={deleted}{reason}")


if __name__ == "__main__":
    main()
