---
create_time: 2026-06-22
updated_time: 2026-06-22
status: research
---

# SASE Config TUI Panel UX Research

## Question

What should the ideal ACE TUI UX look like for setting SASE configuration fields across any supported SASE
configuration file?

## Short Recommendation

Build a source-aware Config Management modal, not a fourth always-visible ACE tab. The default view should be an
effective-field browser that shows what SASE will actually use, while every edit flow keeps the underlying file/layer
visible before writing.

The core UX should be:

1. Search or browse fields by section.
2. Inspect the effective value, default value, schema description, and contributing config layers.
3. Choose a write target explicitly when the default is not obvious.
4. Preview the YAML diff and validation result.
5. Save through a tracked background task, then refresh the config inventory.

The panel should make merge semantics impossible to miss. A user editing a scalar is overriding a value. A user editing
a list might be replacing defaults in `~/.config/sase/sase.yml` or appending through `sase_*.yml`/project-local
`sase.yml`. Those are different operations and need different labels in the UI.

## Current Configuration Model

SASE configuration is a five-layer merge:

| Layer | Example | Mutability | List behavior |
| --- | --- | --- | --- |
| Built-in defaults | `src/sase/default_config.yml` | read-only for users | concatenate |
| Plugin defaults | plugin `default_config.yml` via `sase_config` entry points | read-only for users | concatenate |
| User base | `~/.config/sase/sase.yml` | mutable | replace |
| User overlays | `~/.config/sase/sase_*.yml` | mutable | concatenate |
| Local project | `./sase.yml` | mutable | concatenate |

Important details:

- `sase ace` disables local CWD config loading for its own process, so the TUI does not accidentally inherit a
  repository's agent-run settings. A config panel must therefore treat project-local config as a selected target, not
  as implicit current-process state.
- `sase config layers` already exposes layer names, paths, list strategies, top-level keys, unsupported keys, and
  deprecated keys. The TUI should reuse the same source model.
- `sase config show` already dumps the effective merged configuration. The TUI should be a guided, provenance-rich
  editor on top of that concept.
- `config/sase.schema.json` is the best machine-readable catalog of supported fields, types, enums, defaults, and
  descriptions. Some domain-specific validation still lives outside JSON Schema.
- `workflows` is an unsupported top-level key and `sibling_repos` is a deprecated alias for `linked_repos`.

Supported config files for the UX should mean:

- mutable user base config;
- mutable user overlay configs;
- mutable selected project-local `sase.yml` files;
- read-only built-in and plugin defaults for provenance, preview, and "open source" inspection;
- chezmoi source-side user config paths when `use_chezmoi` is enabled, with an explicit apply step after writes.

## Existing TUI UX Patterns

The strongest local precedents are two-panel modals:

- Project Management: filter, segmented state tabs, row list, detail panel, marks, confirmations, reload, and editor
  fallback.
- Log panel: source list on the left, bounded preview on the right, explicit refresh, scroll bindings.
- XPrompt browser/location modals: grouped sources, filter-first navigation, preview/detail split, editable/read-only
  labels, config-file source selection.

That points to a modal opened from the command palette and a configurable keybinding. Do not assume `,c`; leader `c`
already has meaning. Add the key only after command-catalog, footer, help, and default-config collision checks.

## Ideal Layout

For normal-width terminals, use three regions:

| Region | Contents |
| --- | --- |
| Source rail | Layers/files: built-in, plugins, user base, overlays, selected project-local configs. Show loaded/missing/invalid/read-only, list strategy, and key count. |
| Field list | Searchable field tree grouped by top-level section. Columns: field path, type, effective summary, source badge, status. |
| Detail/editor | Schema description, effective value, default, layer contributions, validation, write target, and pending diff. |

For narrow terminals, collapse the source rail into a source filter/action and keep the field list plus detail split.

Field rows should be stable and scannable:

```text
llm_provider.provider          string  claude                  user
workspace.root                 string  xdg-state               default
linked_repos                   array   4 entries               local + user
sibling_repos                  array   deprecated              user
axe.lumberjacks.hooks.interval int     5                       default
```

The detail pane should answer four questions without making the user open YAML:

1. What value is effective right now?
2. Why is that value effective?
3. Where will my edit be written?
4. Will the result validate and when will it take effect?

## Source-Aware Editing

The write target should be explicit whenever ambiguity exists.

Default target rules:

- If the field is already set in exactly one mutable highest-priority source, default to that source.
- If editing a project-scoped field from a selected project context, default to that project's `sase.yml`.
- If editing a global scalar with no existing mutable value, default to user base config.
- If editing a list, force the user to choose "replace in user base" or "append in overlay/local" unless the existing
  source makes the intent obvious.
- Built-in and plugin defaults are never direct write targets in normal user mode.

Every save should show a short diff preview:

```diff
 llm_provider:
-  provider: claude
+  provider: codex
```

Then run validation before writing or immediately after constructing the candidate text. A failed validation should keep
the pending edit visible and focus the offending field.

## Field Editors

Use schema-driven editors where possible:

| Field shape | Editor |
| --- | --- |
| boolean | toggle |
| enum | option list |
| integer/number | numeric input with min/max validation |
| string | inline input; multiline editor for long text |
| path-like string | path input with existence hint, not a hard requirement |
| map | key/value table with add/edit/remove |
| array of strings | list editor with add/remove/reorder |
| array of objects | row table plus nested object editor |
| freeform structured config | guided YAML block editor plus schema validation |

High-value specialized editors:

- `linked_repos`: table with name, path, description, workspace strategy, and path resolution preview.
- `llm_provider`: provider/model/alias editor with effective default and worker-lane preview.
- `ace.keymaps`: key capture plus duplicate/invalid binding diagnostics from the existing keymap loader.
- `axe.lumberjacks`: nested lumberjack/chop editor, because list append vs replace matters a lot here.
- `mentor_profiles` and `metahooks`: object-list editors with domain validation.
- `xprompts` and `ace.snippets`: deep-link to the existing xprompt/snippet browser flows rather than duplicating the
  entire editing surface in v1.

Credentials and secret-adjacent fields, such as mobile gateway FCM paths/env names, should never preview file contents.
Show only paths, env var names, and validation hints.

## Validation UX

The panel needs both schema and domain validation:

- JSON Schema for supported keys, types, enums, required object fields, and additional-property errors.
- `load_config_layers()`-style parsing diagnostics for invalid YAML, unsupported keys, and deprecated keys.
- Keymap validation through the ACE keymap registry.
- Domain parsers for axe config, mentor profiles, metahooks, workspace config, LLM provider config, and mobile gateway
  config.
- Effective-merge validation after applying the candidate edit, because a layer can be valid alone but surprising after
  merge.

Validation should be attached to the field and source:

```text
WARN  sibling_repos is deprecated; write new entries to linked_repos.
ERROR ace.keymaps.app.quit conflicts with ace.keymaps.app.kill_agent.
INFO  linked_repos in this local config are resolved relative to the project workspace.
```

Add a one-key migration action for safe deprecations, starting with `sibling_repos -> linked_repos`.

## Runtime Semantics

The panel should label when changes take effect:

| Config area | Effect timing |
| --- | --- |
| Agent launch defaults, LLM provider, linked repos | new launches |
| ACE keymaps/layout behavior | likely current TUI restart unless live reload is explicitly implemented |
| Axe scheduler config | axe restart or next daemon start, depending on field |
| SDD/workspace/bead settings | next command using that config |
| Temporary model overrides | not this panel; keep using the existing temporary override modal/state files |

Do not mix persistent config with runtime state. Existing runtime files such as temporary LLM overrides and project
lifecycle state have their own management surfaces. The config panel may link to those surfaces, but should not fold
them into `sase.yml`.

## Performance Constraints

The audited TUI performance memory is directly relevant:

- Do not parse YAML, validate schema, scan project workspaces, run `chezmoi`, or call subprocesses on the Textual event
  loop.
- Parse schema/defaults once and cache layer inventories with the existing config stat token concept.
- On highlight, render precomputed summaries. Detailed YAML snippets and validation can be loaded lazily or off-thread.
- Writes, `chezmoi apply`, and any git/status checks should run as tracked tasks so they appear in the Task Queue and
  quit confirmation flow.
- Re-read selected identity after awaits/workers before applying UI updates.

## Implementation Shape

Recommended backend model:

```text
ConfigInventory
  sources: list[ConfigSource]
  fields: list[ConfigField]
  diagnostics: list[ConfigDiagnostic]

ConfigField
  path: tuple[str, ...]
  schema: JSON-schema fragment
  default_value
  effective_value
  contributions: list[ConfigContribution]
  supported: bool
  deprecated_replacement: optional path
  write_capabilities
```

Recommended write pipeline:

1. Build a candidate edit against one target source.
2. Preserve unrelated YAML text and comments where practical.
3. Validate the target file parse.
4. Validate the candidate effective merge.
5. Show diff.
6. Write atomically under an edit lock.
7. Clear config caches and refresh inventory.
8. Optionally run `chezmoi apply` as a separate confirmed tracked task.

The current code has one-off YAML mutation helpers for SDD init and config xprompt insertion. A general config panel
should introduce a reusable source-preserving YAML patch backend instead of expanding those ad hoc approaches. If full
comment preservation is not feasible in v1, keep edits narrowly scoped and show the exact diff before write.

Shared behavior such as inventory construction, merge provenance, validation, and YAML write planning should be usable
from a future CLI (`sase config set`, `sase config edit`) and possibly other frontends. Textual rendering, keybindings,
and modal layout stay in the Python TUI layer.

## Alternatives

### Raw YAML File Browser

This would be simple: list config files, open the selected one in `$EDITOR`, run validation after the editor closes.

Reject as the primary UX. It does not solve the hard problem: users still cannot tell which file should own a field or
how list merge semantics will behave. Keep it as an escape hatch.

### Per-Section Wizards

Dedicated flows for LLM provider, linked repos, axe, keymaps, and xprompts would produce excellent focused UX.

Good as a layer on top of the field browser, but poor as the only entry point. SASE has many configuration sections and
plugin-provided defaults; users need one place to answer "where is this value coming from?"

### Source-First Editor

Start with files/layers, then edit keys inside the chosen file.

Useful secondary mode, especially for overlays. Not ideal as the default because users usually know the behavior they
want to change, not the file that currently owns it.

### Effective Field Browser Plus Source-Aware Editor

Recommended. It matches how users reason about behavior while preserving the file/layer details needed to write safely.

## Suggested V1 Scope

V1 should be valuable without solving every nested editor:

- Read-only source/layer browser with diagnostics.
- Effective field browser generated from `config/sase.schema.json`.
- Detail pane with default/effective/contribution stack.
- Safe edits for booleans, enums, strings, numbers, simple maps, and simple string arrays.
- Explicit write target selection for user base, existing overlays, new overlay, and selected project-local config.
- Diff preview and schema validation.
- Raw editor fallback for complex fields.
- Deprecated/unsupported-key warnings.

Defer complex object-list editors (`axe.lumberjacks`, `mentor_profiles`, full `xprompts`) until the inventory/write
pipeline is proven.

## Open Questions

- Should the first release edit all registered project-local `sase.yml` files, or only the currently selected/currently
  inferred project?
- When `use_chezmoi` is enabled, should the panel always write source-side config and offer apply, or should it expose
  both live and source targets?
- Should plugin packages be allowed to expose editable user-overlay templates for their own config sections?
- Should there be a companion `sase config set/unset` CLI before or after the TUI panel?
- Which config changes should hot-reload into the running ACE session, and which should deliberately require restart?

## Local Sources Reviewed

- `docs/configuration.md`
- `src/sase/config/core.py`
- `config/sase.schema.json`
- `src/sase/default_config.yml`
- `src/sase/main/config_handler.py`
- `src/sase/main/ace_handler.py`
- `src/sase/ace/tui/app.py`
- `src/sase/ace/tui/modals/project_management_modal.py`
- `src/sase/ace/tui/modals/log_modal.py`
- `src/sase/ace/tui/modals/xprompt_browser_modal.py`
- `src/sase/ace/tui/modals/xprompt_location_modal.py`
- `src/sase/ace/tui/actions/task_actions.py`
- `src/sase/ace/tui/keymaps/loader.py`
- `src/sase/main/sdd_init_config.py`
- `src/sase/ace/tui/modals/xprompt_config_yaml.py`
- Audited long-memory read: `memory/tui_perf.md`
