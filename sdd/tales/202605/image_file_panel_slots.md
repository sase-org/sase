---
create_time: 2026-05-07 17:24:38
status: done
prompt: sdd/prompts/202605/image_file_panel_slots.md
---
# Plan: Completed-Agent Image File Panel Slots

## Goal

Ensure that when a completed agent adds or modifies an image file, as determined from the agent's VCS diff/changed-file
discovery, that image appears as a normal file-panel slot on the Agents tab. The user should be able to select the agent
and cycle to the image with `<ctrl+n>` / `<ctrl+p>`, with the existing file-panel image preview renderer handling the
display.

## Current Architecture

Completed `ace-run` agents already discover added/modified images during finalization:

- `src/sase/axe/image_attachments.py` identifies supported image paths from local tracked changes, untracked files,
  saved diff files, and optionally the head commit.
- `src/sase/axe/run_agent_exec.py` calls `collect_agent_image_paths(...)` after completion and passes `image_paths` to
  `build_done_marker(...)`.
- `src/sase/axe/run_agent_phases.py` writes `image_paths` into `done.json` for successful completed runs.

The file panel can already render static image files:

- `src/sase/ace/tui/widgets/file_panel/_display.py` detects supported image paths and uses the TUI image preview layer.
- `src/sase/ace/tui/widgets/file_panel/__init__.py` cycles through `_file_list` with `<ctrl+n>` / `<ctrl+p>`.
- `src/sase/ace/tui/widgets/agent_detail.py` uses `agent.all_files` for completed agents.

The Python direct completed-agent loader also already maps `done.json["image_paths"]` into `Agent.extra_files`:

- `src/sase/ace/tui/models/_loaders/_done_loaders.py::_done_extra_files(...)` includes `plan_path`,
  `markdown_pdf_paths`, and `image_paths`, deduped in order.

The production TUI loading path, however, uses the Rust artifact scan snapshot:

- `src/sase/ace/tui/models/agent_loader.py` calls `_scan_artifacts_for_loader()`.
- `load_done_agents_from_snapshot(...)` then reads `record.done.image_paths`.
- The Python `DoneMarkerWire` type already has `image_paths`, but the sibling Rust scanner currently does not include
  that field in `DoneMarkerWire` or `done_marker_from_object(...)`.

That means `image_paths` can be present in `done.json`, but be dropped by the Rust snapshot before the Agents-tab loader
builds the completed `Agent`. The direct-loader unit test is insufficient because it bypasses the Rust snapshot path.

## Implementation Steps

1. Preserve `image_paths` in the Rust artifact scan wire.
   - Add `image_paths: Vec<String>` with `#[serde(default)]` to
     `../sase-core/crates/sase_core/src/agent_scan/wire.rs::DoneMarkerWire`.
   - Parse it with `coerce_str_list(data.get("image_paths"))` in
     `../sase-core/crates/sase_core/src/agent_scan/scanner.rs::done_marker_from_object`.
   - This is backward compatible for old `done.json` files because the field defaults to an empty list.

2. Strengthen Rust/Python scan parity fixtures.
   - Add at least one image path to the completed-agent `done.json` fixture in both:
     `tests/agent_scan_golden/fixture_builder.py` `../sase-core/crates/sase_core/tests/agent_scan_parity.rs`
   - Update assertions in: `tests/test_core_agent_scan_records.py`
     `../sase-core/crates/sase_core/tests/agent_scan_parity.rs`
   - This verifies the Rust scanner emits image paths and the Python rehydration layer preserves them.

3. Add an Agents-tab loader regression test for the snapshot path.
   - Extend `tests/ace/tui/test_image_file_panels.py` with a test that builds a snapshot/record containing
     `DoneMarkerWire(image_paths=[...])` and asserts `load_done_agents_from_snapshot(...)` or
     `_build_done_agent_from_record(...)` yields an `Agent` whose `extra_files` includes the image paths in file-panel
     order.
   - Keep the existing direct-loader test; it covers the filesystem fallback/private helper path.

4. Leave the image renderer and keymap code unchanged unless tests expose a real issue.
   - The cycling mechanism is already based on `agent.all_files`.
   - The static image preview path is already implemented and covered.
   - The desired behavior should come from ensuring completed-agent image paths survive into `Agent.extra_files`.

## Verification

Run focused checks first:

- Python targeted tests:
  - `pytest tests/ace/tui/test_image_file_panels.py tests/test_core_agent_scan_records.py`
- Rust targeted test:
  - `cargo test -p sase_core agent_scan_parity --manifest-path ../sase-core/Cargo.toml`

Then run the repo-required check after installing this workspace if needed:

- `just install`
- `just check`

If the Rust core workspace has its own formatting/check command available, run the targeted cargo test and any formatter
needed by the edited Rust files.
