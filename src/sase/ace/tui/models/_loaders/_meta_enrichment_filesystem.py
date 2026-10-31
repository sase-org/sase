"""Filesystem-backed agent metadata enrichment public import path."""

from __future__ import annotations

from ._meta_enrichment_filesystem_impl import enrich_agent_from_meta

__all__ = ["enrich_agent_from_meta"]
