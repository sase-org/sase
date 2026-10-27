"""Footprint: a local usage census for finding what sase should delete.

This package is intentionally import-free. Hot paths import submodules such as
``sase.footprint.ids`` and ``sase.footprint.paths`` directly so recording a CLI
or TUI hit never pays for heavier imports.
"""
