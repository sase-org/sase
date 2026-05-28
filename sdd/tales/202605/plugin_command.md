---
create_time: 2026-05-28 16:54:48
status: done
prompt: sdd/prompts/202605/plugin_command.md
---
# Plan: `sase plugin`

## Goal

Add a polished `sase plugin` CLI surface that makes the installed plugin/chop state understandable before SASE starts
mutating package environments. The first implementation should solve the research's highest-confidence gap: inventory
and diagnostics. It should make the same-environment rule visible, show which SASE entry points are active, explain chop
availability versus activation, and give concrete next steps when the user's preferred plugin/chop setup is not working.

## Product Shape

Ship two subcommands first:

- `sase plugin list [-j|--json] [-v|--verbose]`
- `sase plugin doctor [-j|--json] [-v|--verbose]`

Do not implement `add`, `remove`, or `sync` in this first slice. The research calls those important, but they need an
install-profile model so SASE does not guess wrong about `uv tool`, `pipx`, editable checkouts, or ordinary virtualenvs.
The first command should be the diagnostic foundation those later mutating commands reuse.

The human output should use Rich tables/panels with restrained color:

- concise status labels: `OK`, `WARN`, `ERROR`, `SKIP`
- grouped sections: plugin entry points, resource plugins, configured chops, available unconfigured chops, install
  guidance
- no decorative noise; output should stay readable when copied into agent chats or terminals without color

JSON output should be stable and boring:

- top-level `schema_version: 1`
- machine-readable entry point records, chop records, checks, and overall status
- no ANSI, no Rich formatting

## Technical Design

Add a small internal package, probably `src/sase/plugins/`, with these responsibilities:

1. `inventory.py`
   - Enumerate installed distributions with SASE entry points.
   - Cover entry point groups:
     - `sase_llm`
     - `sase_vcs`
     - `sase_workspace`
     - `sase_xprompts`
     - `sase_config`
     - future-friendly `sase_plugin_manifest` if present
   - Map each entry point to package name/version/distribution metadata.
   - For resource groups (`sase_xprompts`, `sase_config`, `sase_plugin_manifest`), attempt to load the entry point and
     capture load errors, because those failures are currently only debug logs.
   - For provider groups, inspect metadata without importing provider classes unless doctor explicitly needs a probe.

2. `chops.py`
   - Load `AxeConfig`.
   - Enumerate configured chops by lumberjack.
   - For script chops, reuse `discover_chop_script()` so doctor reports the exact resolution path AXE will use.
   - Enumerate available `sase_chop_*` scripts from configured chop dirs, the running interpreter's script directory,
     and `PATH`, so same-environment package installs become visible even when commands are not shell-linked.
   - Mark each chop as configured, available-only, missing, or agent-backed.

3. `doctor.py`
   - Build checks from inventory and chop data.
   - Error on resource entry points that fail to load.
   - Error on configured script chops whose executable cannot be resolved.
   - Warn on installed/available chop scripts that are not configured.
   - Warn when plugin resource loading is disabled by `SASE_DISABLE_PLUGINS`, `SASE_DISABLE_PLUGIN_CONFIG`, or
     `SASE_DISABLE_PLUGIN_XPROMPTS`.
   - Add lightweight first-party guidance:
     - if a GitHub plugin entry point is present, check for `gh` and optionally `gh auth status`
     - if Telegram chop scripts are present, check required Telegram env vars and `pass` without auto-enabling anything
   - Return `0` for `OK`/`WARN`, `1` for `ERROR`.

4. `render.py`
   - Render the human `list` and `doctor` output.
   - Keep Rich styling centralized so JSON and data collection remain simple to test.

Wire the command through the existing argparse architecture:

- add `src/sase/main/parser_plugin.py`
- add `src/sase/main/plugin_handler.py`
- import/register the parser in `src/sase/main/parser.py` in sorted command order
- dispatch from `src/sase/main/entry.py` in sorted command order
- every option gets both short and long forms per repo guidance

## UX Details

`sase plugin list` should answer:

- which packages contribute SASE entry points
- which groups and names they contribute
- whether resource plugins load successfully
- which chops are configured and whether script chops resolve
- which `sase_chop_*` scripts are available but not configured

`sase plugin doctor` should answer:

- "Will this installed plugin/chop setup actually work from this `sase` executable?"
- "What is broken?"
- "What should I run next?"

Examples of guidance:

- no third-party entry points: show `uv tool install "sase[github]"` as first-party bundle guidance, but phrase it as a
  recommendation until package extras are actually released
- package installed in wrong environment: infer this only from absence of SASE entry points and explain the same-env
  rule generally; do not claim to have found another venv
- Telegram scripts available but inactive: recommend explicit chop activation in future terms and point to current
  `axe.lumberjacks` config, not automatic enablement

## Tests

Add focused tests rather than broad integration tests:

- parser accepts `sase plugin list -j`, `sase plugin list --json`, `sase plugin doctor -j`, and `--verbose`
- inventory groups entry points by distribution and captures load failures from fake resource entry points
- chop inventory reports:
  - configured script resolved
  - configured script missing
  - agent-backed chop skipped from script resolution
  - available unconfigured `sase_chop_*` script beside `sys.executable`
- doctor status aggregation returns `ERROR` for missing configured scripts and resource load failures
- handler JSON output is valid and has `schema_version: 1`
- human output includes stable section labels and avoids tracebacks for missing optional tools

Run at least:

```bash
just install
just check
```

If `just check` is too broad for iteration, run targeted pytest first, then finish with `just check` because this will
touch implementation files.

## Follow-On Work

After this diagnostic command lands, implement in separate slices:

1. first-party optional dependencies in `pyproject.toml`
2. an install-profile model that records `uv tool`/`pipx`/venv/editable provenance
3. `sase plugin add/remove` using that install profile
4. `sase_plugin_manifest` package metadata
5. `sase chop available/enable/disable` with a managed config overlay
6. `sase plugin sync` for a portable preferred-set manifest

Those later commands should reuse the inventory and doctor modules from this first slice.
