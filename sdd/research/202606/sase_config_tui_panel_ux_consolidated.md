---
create_time: 2026-06-22
updated_time: 2026-06-22
status: research
---

# SASE Config TUI Panel UX Consolidated Research

## Research Request

What should the ideal ACE TUI UX look like for setting SASE configuration fields across any supported SASE
configuration file?

## Consolidation Notes

This note consolidates two independent research outputs:

- `sdd/research/202606/sase_config_tui_panel_ux.md`
- `sdd/research/202606/config_editor_tui_panel_ux.md`

Both drafts found the same core answer: the hard UX problem is not "edit YAML"; it is "show the effective value,
where it came from, and where a safe edit will be written." The main conflict was surface area. One draft recommended a
source-aware modal and the other a fourth ACE tab. This consolidated recommendation uses a full-screen Config
management panel opened from command palette/leader flow for v1, with the same layout promotable to a permanent tab if
config management becomes frequent enough to deserve top-level navigation.

I rechecked the key repo facts on 2026-06-22: config layering and list merge behavior in `src/sase/config/core.py`, ACE's
local-config disable in `src/sase/main/ace_handler.py`, current ACE tabs in `src/sase/ace/tui/app.py` and
`widgets/tab_bar.py`, schema availability in `config/sase.schema.json` and `sase path config-schema`, read-only CLI
inspection in `src/sase/main/config_handler.py`, existing YAML write precedents, and the audited TUI performance memory.

## Bottom Line

Build a schema-driven, provenance-first Config Management panel. It should browse effective configuration by field, not
by file, while making every write target explicit.

The ideal flow:

1. Search or browse a schema-generated field tree.
2. Inspect the effective value, default, description, validation status, and per-layer provenance.
3. Choose the write scope: user base, user overlay, or selected local project config.
4. Edit with a type-appropriate widget where possible, or raw YAML for complex sections.
5. Preview the target-file diff and candidate effective merge before saving.
6. Save through an off-event-loop tracked task, refresh config inventory, and show when the change takes effect.

The differentiators are provenance and scope-aware writes. A plain YAML editor cannot answer "why is this value active?"
or "which file should I edit?" Those are the questions this panel must make obvious.

## Verified Configuration Model

SASE loads a five-layer config stack, lowest to highest priority:

| Layer | Example | Writable? | List behavior |
| --- | --- | --- | --- |
| Built-in defaults | `src/sase/default_config.yml` | No | base |
| Plugin defaults | plugin `default_config.yml` via `sase_config` entry points | No | concatenate |
| User base | `~/.config/sase/sase.yml` | Yes | replace |
| User overlays | `~/.config/sase/sase_*.yml` | Yes | concatenate |
| Local project | `./sase.yml` | Yes | concatenate |

UX consequences:

- Scalars override lower layers; lists are the trap. A list in user base replaces lower lists, while overlays and local
  config append to lower lists. The editor must label this at the point of editing.
- `sase ace` calls `set_include_local_config(False)`, so ACE does not load the current repository's `./sase.yml` for its
  own behavior. Local config should therefore be a deliberate selectable target, not an implicit current-process layer.
- `sase config layers` already exposes useful layer metadata: name, path, loaded status, list strategy, top-level keys,
  unsupported keys, deprecated keys, and parse errors.
- `sase config show [-k KEY]` shows the merged effective config, but there is no general `sase config set` or `unset`
  command today.
- `config/sase.schema.json` is a real form-generation source: Draft-07, strict top level, 976 lines, 22 top-level
  sections, descriptions, defaults, enums, constraints, and nested object definitions. It is already exposed through
  `sase path config-schema`.
- `sibling_repos` is still schema-visible but deprecated in favor of `linked_repos`; `workflows` is unsupported and
  ignored. The panel should surface both as diagnostics instead of hiding them.
- `use_chezmoi` changes home-managed write targets. Existing xprompt flows already remap config/xprompt paths into the
  chezmoi source tree; the config panel should do the same and offer `chezmoi apply` as a separate explicit task.

## Recommended Surface

Use a full-screen Config Management panel/modal in v1, opened from the command palette and a configurable leader action.
This matches the fact that config editing is a focused management task, not something users monitor continuously like
PRs, agents, or AXE.

The same implementation can become a fourth tab later if usage proves it belongs in top-level navigation. Avoid baking
the UX around the tab decision; bake it around a reusable inventory, field browser, and editor.

Normal-width layout:

| Region | Purpose |
| --- | --- |
| Source rail | Built-in, plugin, user base, overlays, selected local configs; loaded/missing/invalid/read-only badges; list strategy; key count. |
| Field tree | Schema-generated sections and fields; searchable by path and description; badges for modified fields and winning layer. |
| Detail/editor | Description, type, default, effective value, provenance stack, write scope, editor widget, diagnostics, and pending diff. |

Narrow terminals can collapse the source rail into a scope/filter picker and keep a two-pane field/detail split.

Example field row shape:

```text
llm_provider.provider          string  claude                  user
timezone                       string  America/New_York        overlay
linked_repos                   array   4 entries               user + local
sibling_repos                  array   deprecated              user
axe.max_agent_runners          int     3                       default
```

The detail pane should answer four questions without sending the user to YAML:

1. What value is effective right now?
2. Why is that value effective?
3. Where will my edit be written?
4. Will the result validate, and when will it take effect?

## Core Interaction Model

### Field Navigation

- Tree mirrors the schema: top-level section, nested object, leaf field.
- `/` filters by dotted path and schema description.
- `m` toggles modified-only for auditing user customization.
- `:` jumps to an exact or fuzzy dotted path.
- Badges show modified state and winning layer (`D`, `P`, `U`, `O`, `L` or equivalent color/label).

### Provenance Strip

For the selected field, show the layer stack in priority order with the winning value marked:

```text
Provenance
* overlay  ~/.config/sase/sase_work.yml     "UTC"       effective
  user     ~/.config/sase/sase.yml          "local"
  default  built-in                         "America/New_York"
  local    ./sase.yml                       off in ACE
```

This is the TUI equivalent of `git config --show-origin`. Selecting a mutable source row should switch the edit scope to
that file. Read-only rows can offer "open source" or "copy value", not direct edit.

### Scope Selector

The write target must always be visible:

- `User`: `~/.config/sase/sase.yml`; default for new global scalar values.
- `Overlay`: existing `sase_*.yml` or "create overlay"; useful for machine/context-specific config.
- `Local`: selected project `./sase.yml`; label clearly that local config is not loaded by ACE itself.
- `Chezmoi source`: when `use_chezmoi` is active, show source-side paths such as `~/.local/share/chezmoi/home/dot_config/sase/sase.yml`
  and offer apply after save.

Defaulting rules:

- If the field is set in exactly one mutable highest-priority source, default to that source.
- If the field is unset and global, default to user base.
- If the field is project-scoped from a selected project context, default to that project's local config.
- If the field is a list, force an explicit choice unless there is a clear existing source.
- Built-in and plugin defaults are never normal write targets.

### List Editing

For arrays, show the chosen scope's merge behavior in the editor:

- User base: "This list replaces lower-layer values."
- Overlay/local: "This list appends to lower-layer values."

Also show a merged preview. For nested lists such as lumberjack chops, the preview must use the same merge implementation
as real config loading; do not reimplement approximate list behavior in the widget.

## Field Editors

Generate the default editor from JSON Schema:

| Field shape | Editor |
| --- | --- |
| boolean | toggle |
| enum | option list / segmented picker |
| integer or number | numeric input with min/max validation |
| string | inline input; multiline editor for long text |
| path-like string | path input with existence hint, not hard failure |
| map | key/value table |
| array of strings | add/remove/reorder list editor |
| array/object complex shapes | row table with nested drill-in form |
| freeform structured config | raw YAML slice editor with validation |

Specialized editors worth prioritizing:

- `ace.keymaps`: grouped action/key table, key-capture input, duplicate/prefix conflict diagnostics from the keymap
  loader.
- `linked_repos`: table with name, path, description, workspace strategy, and path resolution preview.
- `llm_provider`: provider/model/alias editor with effective defaults and retry policy visibility.
- `axe.lumberjacks`: nested lumberjack/chop editor, because list append vs replace is especially consequential.
- `mentor_profiles` and `metahooks`: object-list editors with domain validation.
- `xprompts` and `ace.snippets`: deep-link to existing authoring/browser flows where those are already better than a
  generic settings form.

Keep a universal raw-YAML escape hatch: `e` opens the selected section's YAML slice in `$EDITOR` or an in-TUI text area,
then validates and re-merges before offering a diff.

## Save And Validation UX

Edits should be pending until saved. Saving should show a diff grouped by target file:

```diff
 llm_provider:
-  provider: claude
+  provider: codex
```

Validation should happen at two levels:

- Target-file parse and schema validation: YAML shape, supported keys, types, required fields, enums, constraints, and
  additional-property errors.
- Candidate effective-merge validation: after applying the pending edit to the selected layer, check the merged config
  as SASE will use it.

Attach diagnostics to both field and source:

```text
WARN  sibling_repos is deprecated; migrate to linked_repos.
ERROR ace.keymaps.app.quit conflicts with ace.keymaps.app.kill_agent.
INFO  linked_repos in local config resolve relative to the project workspace.
```

"Reset to default" should mean delete the key from the current mutable scope, allowing lower layers or future defaults to
surface. It should not write the literal default value unless the user explicitly asks for that.

For safe deprecations, include one-key migrations. The first candidate is `sibling_repos -> linked_repos`.

## Runtime Semantics

The panel should show when changes take effect:

| Config area | Likely timing |
| --- | --- |
| Agent launch defaults, LLM provider, linked repos | New launches |
| ACE keymaps/layout behavior | Restart ACE unless live reload is built |
| AXE scheduler config | AXE restart or next daemon start, depending on field |
| SDD/workspace/bead settings | Next command/load using that config |
| Temporary model overrides | Out of scope; keep in existing runtime-state surfaces |

Do not mix persistent config with runtime state. Temporary LLM overrides, task state, project lifecycle state, and
agent-run state can be linked from the panel when relevant, but should not be folded into `sase.yml` editing.

## Performance And Implementation Constraints

The TUI performance rule is strict: do not do YAML parsing, schema parsing, config layer scanning, subprocesses, or writes
on the Textual event loop.

Recommended shape:

```text
ConfigInventory
  sources: list[ConfigSource]
  fields: list[ConfigField]
  diagnostics: list[ConfigDiagnostic]

ConfigField
  path: tuple[str, ...]
  schema_fragment
  default_value
  effective_value
  contributions: list[ConfigContribution]
  deprecated_replacement: optional path
  write_capabilities
```

Load schema/defaults once, cache source inventories using the existing config stat-token idea, and render precomputed
summaries on highlight. Expensive detail snippets, validation, diff generation, writes, `chezmoi apply`, and any git
status checks should run in workers or tracked background tasks. Re-read current tab/selection after awaits before
applying results.

Source-preserving YAML write-back is the main implementation gap. Existing one-off precedents are
`write_sdd_init_config()` and `insert_xprompt_into_config()`, but a general panel needs a reusable setter/unsetter that
preserves unrelated comments, ordering, and formatting where practical. If full round-trip preservation is not available
in v1, keep edits narrowly scoped and always show the exact diff before writing.

By the project's Rust core boundary, layer resolution, provenance, schema-typed get/set planning, merge validation, and
write planning are shared backend behavior: a future CLI, web app, editor integration, and this TUI should all agree.
Textual layout, keybindings, focus, and widget rendering can stay in the Python TUI layer.

## Suggested V1

Ship a useful narrow version before building every specialized editor:

- Full-screen Config Management panel/modal opened from command palette/leader action.
- Read-only source/layer browser with diagnostics.
- Schema-generated field tree with search, modified-only filter, default/effective values, and provenance.
- Explicit write target selection for user base, existing overlays, new overlay, and selected local config.
- Safe edits for booleans, enums, strings, numbers, simple maps, and simple string arrays.
- Array merge-behavior banner and effective preview.
- Diff preview, schema validation, and candidate effective-merge validation.
- Raw YAML escape hatch for complex fields.
- Deprecated/unsupported-key diagnostics and `sibling_repos -> linked_repos` migration.
- Off-event-loop inventory refresh and tracked write/apply tasks.

Defer dedicated editors for `axe.lumberjacks`, full `mentor_profiles`, full `metahooks`, and full xprompt authoring until
the inventory/provenance/write pipeline is proven.

## Open Questions

- Should v1 edit only the currently selected/current project `./sase.yml`, or also all registered project-local config
  files?
- How much overlay management belongs in the panel: create only, or also rename/delete/reorder?
- When `use_chezmoi` is enabled, should the live config path be hidden behind the source path, or shown as read-only
  deployment output?
- Which ACE config changes should hot-reload, and which should deliberately require restart?
- Should a companion `sase config set/unset/edit --dry-run` CLI land before the TUI write flow, or share the backend
  shortly after?

## Sources Checked

- Chat transcripts:
  - `~/.sase/chats/202606/sase-ace_run-260622_123857.md`
  - `~/.sase/chats/202606/sase-ace_run-260622_123900.md`
- Prior research files:
  - `sdd/research/202606/sase_config_tui_panel_ux.md`
  - `sdd/research/202606/config_editor_tui_panel_ux.md`
- Repo sources:
  - `docs/configuration.md`
  - `config/sase.schema.json`
  - `src/sase/default_config.yml`
  - `src/sase/config/core.py`
  - `src/sase/main/ace_handler.py`
  - `src/sase/main/entry.py`
  - `src/sase/main/parser_commands.py`
  - `src/sase/main/config_handler.py`
  - `src/sase/main/sdd_init_config.py`
  - `src/sase/ace/tui/app.py`
  - `src/sase/ace/tui/widgets/tab_bar.py`
  - `src/sase/ace/tui/modals/xprompt_config_yaml.py`
  - `src/sase/ace/tui/modals/xprompt_location_modal.py`
  - `src/sase/ace/tui/modals/xprompt_browser_actions.py`
- Memory:
  - `memory/rust_core_backend_boundary.md`
  - audited `sase memory read tui_perf.md`
