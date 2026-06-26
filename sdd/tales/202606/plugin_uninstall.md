---
create_time: 2026-06-26 15:48:41
status: done
prompt: sdd/prompts/202606/plugin_uninstall.md
---
# Plan: `sase plugin uninstall <plugin>`

## Goal

Add `sase plugin uninstall <plugin>` as the inverse of `sase plugin install <plugin>`: remove one injected plugin from
the same managed `uv tool install sase` environment, preserve the primary `sase` install and every other injected
plugin, and expose the same capability from the SASE Admin Center Plugins tab.

## Context From Existing Code

- The current plugin lifecycle implementation is centered in Python:
  - `src/sase/plugins/operations.py` is the console-free plan/execute layer for install and update.
  - CLI handlers keep rendering, JSON, and exit-code mapping in `src/sase/plugins/cli_install.py` and
    `src/sase/plugins/cli_update.py`.
  - The Admin Center Plugins tab calls the same operations layer, plans in Textual workers, previews the exact `uv` argv
    in `PluginActionConfirmModal`, and executes long-running `uv` work as tracked background tasks.
- `uv tool install --with ...` replaces the injected plugin set, so uninstall should rebuild the full receipt-derived
  install command with the target plugin omitted.
- `src/sase/uv_tool/runner.py` already parses removed packages from uv output, so uninstall results can reuse the
  existing `ChangeKind.REMOVED` path.
- CLI rules require sorted subcommands, good help text, and short aliases for public options.
- TUI performance rules require no blocking receipt/catalog/subprocess work on the Textual event loop.

## Design

Implement uninstall as a third first-class plugin mutation beside install and update.

1. Add a pure uv command/reconstruction path for removing one injected plugin.
   - Extend `ToolReceipt` reconstruction with an omit/remove path, or add an equivalent helper that filters all raw
     receipt plugin entries matching a normalized distribution name before dedupe.
   - Add a `build_uninstall(...)` uv argv builder in `src/sase/uv_tool/commands.py` that renders
     `uv tool install <primary> --with <remaining plugins...>` with optional `--color`.
   - Preserve editable primary installs, editable plugin installs, git/url plugin specs, receipt order, and dedupe
     behavior.
   - Remove all duplicate receipt entries for the target normalized name, not only the first deduped entry.

2. Add console-free uninstall planning/execution to `src/sase/plugins/operations.py`.
   - New typed outcomes, likely:
     - `UninstallReady`: target requirement/display name plus exact argv.
     - `UninstallOutcome`: ready plan, `UvChangeSet`, elapsed time.
     - `UninstallUnknown`: target matched neither receipt nor catalog, with suggestions.
     - An already-absent/known-not-installed outcome, treated as a no-op success for an idempotent uninstall.
   - Resolution order:
     - Probe that this process is running from a managed `uv tool install sase`; otherwise return `NotUvTool`.
     - Read the uv receipt as the source of truth.
     - Match the target against injected plugins first using the same short/repo/full-name normalization strategy as
       update, so installed community/raw plugins resolve without a catalog fetch.
     - Only on a receipt miss, load the catalog to distinguish “known but already absent” from “unknown name with
       suggestions”.
   - `execute_uninstall` runs the ready argv and returns elapsed time plus parsed uv changes.
   - Keep catalog/receipt/uv dependencies injectable for tests and TUI use.

3. Add the CLI command.
   - Register `uninstall` in `src/sase/main/parser_plugin.py`, keeping plugin subcommands sorted as
     `{install,list,show,uninstall,update}`.
   - Provide excellent `-h|--help` text and examples.
   - Support:
     - positional `<plugin>`
     - `-j|--json`
     - `-n|--dry-run`
     - `-r|--refresh`
   - Dispatch from `src/sase/main/plugin_handler.py`.
   - Add `src/sase/plugins/cli_uninstall.py`, mirroring install/update handler structure:
     - plan first
     - render no-op already-absent result without running uv
     - dry-run prints/returns the exact uv argv
     - execute with spinner for terminals
     - stable schema-versioned JSON
     - consistent non-zero errors for unmanaged uv installs, unknown names, receipt errors, catalog errors, and uv
       failures.

4. Add Rich renderers.
   - Extend `src/sase/plugins/render_results.py` and `src/sase/plugins/render.py` with uninstall result, dry-run, and
     no-op renderers.
   - Use the existing result table style so removed packages display with the red removed glyph and `(removed)` note.
   - Add user-facing copy that clarifies running agents should be restarted to unload the plugin.

5. Add Admin Center Plugins tab support.
   - Add a `plugins_browser_uninstall.py` mixin parallel to install/update.
   - Add a keybinding such as `x uninstall` for installed highlighted plugins.
   - Gate the action exactly like update:
     - hidden/disabled when SASE is not a managed uv tool install
     - offered only for installed highlighted plugins
     - short-circuit with a toast if invoked on a non-installed row
   - Plan uninstall off-thread using `run_worker(..., thread=True)`.
   - Reuse `PluginActionConfirmModal` to preview the exact `uv` command before execution.
   - Execute through `_submit_tracked_task` with a `plugin-uninstall:<name>` dedup key.
   - On completion, toast a concise success/error message and refresh the catalog/installed merge so the row flips from
     installed to available.
   - Update summary and hint copy from “Install/update unavailable” to a broader plugin-mutations message.

6. Tests.
   - `tests/uv_tool/test_commands.py`:
     - uninstall argv removes one plugin and preserves the primary plus remaining plugins
     - editable/dev duplicate receipt entries are fully removed for the target
   - `tests/test_plugin_operations.py`:
     - not uv tool
     - receipt-first ready plan without catalog fetch
     - known but already absent no-op
     - unknown target with suggestions
     - catalog and receipt errors propagate
     - offline forwarded only on catalog miss
     - execute success timing and uv failure propagation
   - New `tests/test_plugin_cli_uninstall.py`:
     - parser flags and required positional
     - success rendering and JSON
     - dry-run rendering and JSON
     - unmanaged uv install
     - already absent no-op
     - unknown target
     - uv failure
   - TUI tests:
     - uninstall hint is present only for installed highlighted plugins
     - not-uv-tool state hides uninstall affordance
     - preview modal opens with uninstall argv and summary
     - confirmed uninstall executes through tracked task and reloads the catalog
     - terminal plan outcomes toast correctly
   - Visual coverage:
     - add or update the plugin action PNG snapshot coverage for an uninstall preview if the shared modal copy/layout
       changes.

7. Verification.
   - Run targeted tests first:
     - `pytest tests/uv_tool/test_commands.py tests/test_plugin_operations.py tests/test_plugin_cli_uninstall.py`
     - `pytest tests/ace/tui/test_plugins_browser_pane_uninstall.py`
   - Run affected existing tests:
     - `pytest tests/test_plugin_cli_install.py tests/test_plugin_cli_update.py tests/test_plugin_cli_list.py tests/test_plugin_cli_show.py`
     - `pytest tests/ace/tui/test_plugins_browser_pane_install.py tests/ace/tui/test_plugins_browser_pane_update.py tests/ace/tui/test_plugins_browser_pane_loading.py`
   - If visual snapshots are changed or added, run the relevant visual snapshot test and inspect/update the intended PNG
     artifacts.
   - Because this repo requires it after file changes, run `just install` if needed and then `just check` before final
     handoff.

## Non-Goals

- Do not add `sase plugin uninstall --all`; removing all plugins is more destructive and was not requested.
- Do not implement a separate TUI uninstall backend. CLI and TUI should share the operations layer.
- Do not refactor plugin lifecycle code into Rust as part of this change; the existing install/update lifecycle is
  already Python-based and this should extend that established boundary rather than reshaping the architecture.
