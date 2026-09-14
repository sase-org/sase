"""Typed sudo gate construction and terminal workflow.

Submodules are intentionally not re-exported here: sudo command resources import
``sase.sudo.commands`` in a fresh Python process, and a lightweight package init
keeps that path free of notification-gate validation import cycles.
"""
