---
create_time: 2026-06-26 07:45:04
status: done
prompt: sdd/prompts/202606/update_dedup_plugin_rows.md
---
# Plan: Deduplicate Plugin Rows in `sase update`

## Problem

`sase update` currently renders duplicated plugin rows when the uv tool receipt contains duplicated plugin requirements.
This is a real receipt shape for dev/editable installs: uv can record an editable plugin entry followed by a bare index
entry for the same distribution. The receipt parser intentionally preserves the raw requirement list, and
`ToolReceipt.reconstruct()` already dedupes it for install/update command construction.

The bug is that display and target-selection code bypass that deduped path:

- `src/sase/uv_tool/render.py::summarize_update()` iterates `receipt.injected_plugins()` directly, so duplicated receipt
  entries become duplicated “already current” rows and inflated counts.
- `src/sase/main/update_handler.py::_planned_packages()` also iterates `receipt.injected_plugins()`, so
  `sase update --dry-run` and dry-run JSON can duplicate plugin rows too.
- `src/sase/plugins/cli_update.py` uses `receipt.injected_plugins()` for `sase plugin update --all` targets, so
  duplicate receipt entries can produce duplicated `--upgrade-package` flags and duplicated JSON/result rows.

## Design

Make “deduped injected plugins in receipt order” a receipt-level API, then switch user-facing inventory and bulk-target
surfaces to that API.

1. Add a small helper on `ToolReceipt`, likely `deduped_injected_plugins()`, that returns `self.reconstruct().plugins`.
   - This reuses the existing normalized-name dedupe behavior and first-occurrence-wins policy.
   - It keeps raw `injected_plugins()` unchanged for callers/tests that intentionally need to inspect the receipt
     exactly as uv wrote it.
   - It avoids scattering `receipt.reconstruct().plugins` across renderers and handlers.

2. Update top-level update surfaces to use the deduped list.
   - `summarize_update()` should render one outcome per primary/plugin distribution.
   - `_planned_packages()` should report one planned plugin per distribution.
   - JSON counts should then naturally reflect unique packages.

3. Update plugin update targeting to use the deduped list.
   - `sase plugin update --all` should build one target per installed plugin distribution.
   - `_match_injected()` can also iterate the deduped list, though matching would still work either way.
   - Single-plugin update behavior remains unchanged: a query resolves by normalized distribution name and preserves the
     first receipt occurrence.

4. Keep command-building semantics unchanged.
   - `build_install()` and `build_upgrade_packages()` already dedupe through `receipt.reconstruct()`.
   - No Rust changes are needed; this is Python packaging/CLI behavior.
   - No CLI shape or JSON schema version change is needed because this fixes duplicate entries rather than changing
     payload fields.

## Regression Tests

Add focused tests using a dev-style receipt with duplicate plugin entries:

- `tests/uv_tool/test_receipt.py`: verify the new helper collapses duplicates while `injected_plugins()` still preserves
  the raw receipt.
- `tests/uv_tool/test_render.py`: `summarize_update()` should produce exactly `sase`, `sase-core-rs`, `sase-github`,
  `sase-telegram` for the sample dev receipt, with no duplicated `sase-github` / `sase-telegram` “already current”
  outcomes.
- `tests/main/test_update_command.py`: `sase update --dry-run -j` should return unique package names and the non-dry-run
  JSON counts should not include duplicates.
- `tests/test_plugin_cli_update.py`: `sase plugin update --all` should emit one `--upgrade-package` flag per unique
  plugin and its dry-run JSON should list unique plugins.

## Verification

Run the focused test set first:

```bash
uv run pytest tests/uv_tool/test_receipt.py tests/uv_tool/test_render.py tests/main/test_update_command.py tests/test_plugin_cli_update.py
```

Then run the repo’s standard check if the focused tests pass:

```bash
just check
```
