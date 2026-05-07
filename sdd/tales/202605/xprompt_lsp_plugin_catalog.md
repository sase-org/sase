---
create_time: 2026-05-07 13:51:55
status: done
prompt: sdd/prompts/202605/xprompt_lsp_plugin_catalog.md
---
# Plan: Include Plugin XPrompts in the XPrompt LSP Catalog

## Problem

The xprompt LSP marks plugin-provided xprompts/workflows such as `#gh` as unknown even though the regular SASE runtime
accepts them.

Observed source of truth:

- `#gh` is contributed by the `sase-github` plugin as `../sase-github/src/sase_github/xprompts/gh.yml`.
- The Python helper catalog sees it: `sase mobile helper-bridge xprompt-catalog` returns `gh` with
  `source_bucket: plugin`.
- The Rust LSP catalog does not currently ingest `sase_xprompts` or `sase_config` entry-point resources.
- `CatalogCache::command_backed()` prefers the Rust catalog and only falls back to the Python helper when Rust returns
  an empty catalog or errors. Since built-ins make the Rust catalog non-empty, the Python helper never gets a chance to
  supply plugin entries.

## Goals

- Make the xprompt LSP recognize plugin workflows/xprompts, including `#gh`, `#new_pr_desc`, `#prdd`, and Mercurial
  plugin prompts when those plugins are installed.
- Preserve the current fast Rust-backed catalog path for normal editor use.
- Keep catalog precedence aligned with Python runtime behavior:
  - xprompts: built-in internal < default markdown < plugin package xprompts < config/plugin config/user config/local
    layers < memory/project/file overrides
  - workflows: built-in internal < plugin workflows < config workflows < project/file overrides
- Respect existing plugin disable environment variables (`SASE_DISABLE_PLUGINS`, `SASE_DISABLE_PLUGIN_XPROMPTS`,
  `SASE_DISABLE_PLUGIN_CONFIG`).
- Keep the Python/Rust boundary clean: Python discovers Python package entry points; Rust consumes explicit file-system
  metadata.

## Proposed Design

1. Extend the Python `sase lsp` wrapper to export plugin catalog metadata.

   Add LSP-only environment values from `src/sase/integrations/xprompt_lsp.py`:
   - `SASE_XPROMPT_PLUGIN_DIRS_JSON`: JSON list of `{ "module": "...", "path": "..." }` entries for each enabled
     `sase_xprompts` plugin whose package has an `xprompts/` resource directory.
   - `SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON`: JSON list of `{ "module": "...", "path": "..." }` entries for each enabled
     `sase_config` plugin whose package has a `default_config.yml`.

   Use the existing Python plugin-discovery helpers so the wrapper matches runtime discovery and honors disable env
   vars. Use `setdefault` semantics like the existing package path envs so explicit user overrides still win.

2. Teach the Rust core catalog loader to consume that metadata.

   In `../sase-core/crates/sase_core/src/xprompt_catalog.rs`:
   - Parse the two JSON env vars into deterministic module/path maps.
   - Add plugin xprompt directory loading:
     - `.md` files become xprompts with `source_path = "plugin:{module}/{filename}"`.
     - `.yml`/`.yaml` files become workflows with `source_path = "plugin:{module}/{filename}"`.
   - Add plugin config loading:
     - xprompts/workflows from plugin `default_config.yml` use `source_path = "plugin_config:{module}"`.
   - Insert these sources at the same precedence points as the Python loaders.
   - Keep plugin entries bucketed as `plugin` in `classify_source`.
   - Optionally resolve `plugin:` and `plugin_config:` source labels back to real files for definition support when the
     metadata includes a path.

3. Keep direct `sase-xprompt-lsp` invocation from silently losing plugins.

   Normal Neovim resolution prefers `sase lsp`, so the wrapper env path will cover the common path. For standalone
   binary use, update `CatalogCache` so that when plugin metadata env vars are absent, the server may still use the
   command helper catalog as a canonical fallback/overlay. If the helper is unavailable or times out, keep the Rust
   catalog result so built-ins and local files still work.

   This avoids a split where `sase lsp` works but a directly launched `sase-xprompt-lsp` still reports `#gh` as unknown.

4. Add targeted tests.

   Python repo:
   - Extend `tests/main/test_lsp_handler.py` to verify `_prepare_xprompt_lsp_environment()` emits plugin metadata from
     fake discovered modules.
   - Verify explicit env overrides are preserved.
   - Verify disable env behavior for plugin xprompt/config discovery.

   Rust core repo:
   - Add `xprompt_catalog` tests that construct a `CatalogLoader` with plugin xprompt dirs and plugin config paths, then
     assert plugin `.md`, plugin workflow `.yml`, and plugin config entries are present and bucketed as `plugin`.
   - Add a precedence test where user/local config overrides a plugin entry with the same name.
   - Add definition-path coverage if plugin source resolution is implemented.

   Rust LSP repo:
   - Add/adjust catalog-cache tests so the fast Rust catalog path is used when plugin metadata is present.
   - Add coverage for helper fallback when plugin metadata is absent and Rust returns a non-empty built-in-only catalog.

5. Verify end to end.
   - Run `just install` in this workspace before Python checks if needed.
   - Run focused Python tests for the LSP wrapper and plugin catalog behavior.
   - Run focused Rust tests in `../sase-core` for `sase_core` and `sase_xprompt_lsp`.
   - Smoke test the real catalog:
     - `sase mobile helper-bridge xprompt-catalog` already shows `gh`.
     - Start/query the LSP path or call its catalog-backed diagnostics/completion test path to confirm `#gh` no longer
       produces an unknown-xprompt diagnostic.
   - Because this change touches the SASE repo, finish with `just check` in this workspace. If any sibling plugin repo
     is modified, run that repo's `just check` too; the current plan should not require plugin repo edits.

## Risks and Mitigations

- Rust and Python catalog behavior can drift. Mitigation: keep Python responsible for entry-point discovery and make
  Rust consume concrete paths; add tests at the precedence boundaries.
- Plugin resource paths from `importlib.resources` can be non-file-system resources in packaged contexts. Mitigation:
  only export directories/files that can be represented as real paths; fall back to the Python helper when metadata is
  absent.
- Helper fallback can add latency. Mitigation: use it only when plugin metadata is absent, which should mainly be direct
  standalone binary use rather than the normal `sase lsp` wrapper path.
