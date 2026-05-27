---
create_time: 2026-05-26 21:26:24
status: done
prompt: sdd/prompts/202605/sase45_pyvision_cleanup.md
---
# SASE-45 Pyvision Cleanup Plan

## Goal

Finish the post-close cleanup for `sase-45` by removing the unused-public-symbol findings from `just pyvision` without
weakening the structured episodic-memory MVP contract.

## Findings

After closing `sase-45`, `just pyvision` reports these public symbols as unused in production source:

- `EpisodeBuildReportWire`
- `EpisodeBuildRequestWire`
- `episode_wire_schema_version`

These symbols were intentionally part of the episode wire contract, so the preferred fix is to make the CLI use them
instead of deleting the contract types.

## Plan

1. Update `src/sase/memory/cli_episodes.py` so `sase memory episodes build -j` includes structured `build_request` and
   `build_report` payloads based on `EpisodeBuildRequestWire` and `EpisodeBuildReportWire`.
2. Use the Rust-backed `episode_wire_schema_version()` facade in production episode CLI payloads so the public facade
   function is no longer test-only.
3. Add focused CLI assertions for the new build request/report JSON fields.
4. Rerun the focused episode tests, `just pyvision`, and `just check`.
5. Final step: confirm `sase-45` is closed, re-close it if necessary, and keep the plan frontmatter status as `done`.
