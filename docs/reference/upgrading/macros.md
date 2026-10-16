---
title: Macro migration notes
description: Migration notes for macro names, prompt fields, and launch syntax.
---

# Macro migration notes

This page preserves macro renaming and placeholder migration history.

## Agent launch spellings

Older agent selectors use `family` where current prompts and config use `session`. The
compatibility parser also maps older shell gate fields and values to `turn`; proc list
and run commands use `--name`. Supplying both an older and current spelling for the same
field is an error. Write session and turn forms in new prompts and config.

## Workflow launch syntax

Use `#name` for inline macros and `#!name` for standalone workflows. A top-level
`sase run '#sync'` invocation remains accepted with a warning; write
`sase run '#!sync'`. Macro swarms accept `#!name` as a compatibility prefix; write
`#name` in new prompts.

## Workflow configuration

Standalone workflow definitions belong in YAML files under the file-backed macro
sources. Top-level `workflows:` blocks in project, user, or overlay config are ignored.
See [Macro discovery](../macros/discovery.md#discovery-order) for the supported sources.

## Template and input aliases

| Accepted form       | Canonical form     |
| ------------------- | ------------------ |
| `{{ wait_chats }}`  | `{{ wait.chats }}` |
| `{{ cl_name }}`     | `{{ patch_name }}` |
| input type `string` | input type `line`  |
| `wraps_all: true`   | `tags: vcs`        |

Use the canonical form in new templates, inputs, and workflow definitions.

## Renamed from xprompts

<a id="retired-macro-spellings"></a>

SASE's reusable prompt definitions were called **xprompts** before this release and are
now called **macros**. The retired syntax aliases below keep working as accepted
aliases; help, completion, examples, and output show only the macro spelling.
`%xprompts_enabled` regions stay accepted permanently as an alias of `%macros_enabled`.

The aliases cover command, configuration, and discovery spellings. Python integrations
must import `sase.macro`: the retired Python package and package source directories
shown in the table were removed. Those table entries record source moves rather than
accepted aliases.

A retired spelling in a new command, config key, frontmatter key, environment variable,
or `sase path` target is accepted as its macro replacement. The retired entry-point
group in the table is loaded, a plugin's packaged copy of the retired definition
directory is read, and the retired definition directories in the table are visible to
expansion, workflow loading, completion, catalogs, and save choices. Config keys and
frontmatter keys are an error when both spellings are present. A retired config or
frontmatter value still counts when it is null, an empty mapping, false, or an empty
string. The plugin-disable environment variable (macro form
`SASE_DISABLE_PLUGIN_MACROS`) is the same kind of error: setting both names is an error
even when both values are empty. The LSP command environment variable is different. A
non-empty `SASE_MACRO_LSP_CMD` wins and the retired value is ignored. An empty or
whitespace macro value does not count as set, so a retired command is then considered.
State files and agent artifact filenames already written under the old names stay
readable; new writes use only the macro spelling. Those files are separate from the
definition directories above, which stay visible as aliases. A default `sase doctor` run
includes the config check for retired names in this rename. That check lists retired
config keys, frontmatter keys, non-empty retired definition directories, keymap
overrides, set retired environment variables (names only), and plugins still registered
on the retired entry-point group. It does not report the state files or agent artifact
filenames in the table, and it does not report the region alias above.

| Retired spelling                                                                                                                      | Replacement                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `sase xprompt …`, `sase path xprompts-dir`, `xprompts-schema`, `xprompts-collection-schema`, `xprompt-catalog`                        | `sase macro …`, `sase path macros-dir`, `macros-schema`, `macros-collection-schema`, `macro-catalog`               |
| `%xprompts_enabled`                                                                                                                   | `%macros_enabled`                                                                                                  |
| `sase/xprompts/`, `~/sase/xprompts/`, `~/.xprompts/`, `~/xprompts/`                                                                   | `sase/macros/`, `~/sase/macros/`, `~/.macros/`, `~/macros/`                                                        |
| package `sase.xprompt`, `src/sase/xprompts/`, `src/sase/default_xprompts/`                                                            | `sase.macro`, `src/sase/macros/`, `src/sase/default_macros/`                                                       |
| config `xprompts:`, `xprompt_aliases:`, `auto_xprompt_menu`, `xprompt_placeholder_args`, `mentors[].xprompt`; frontmatter `xprompts:` | `macros:`, `macro_aliases:`, `auto_macro_menu`, `macro_placeholder_args`, `mentors[].macro`; frontmatter `macros:` |
| keymap actions `focus_xprompt`, `clear_xprompt_focus`, `start_last_vcs_xprompt_in_editor`                                             | `focus_macro`, `clear_macro_focus`, `start_last_vcs_macro_in_editor`                                               |
| entry-point group `sase_xprompts`; env `SASE_XPROMPT_*`, `SASE_*_XPROMPTS`                                                            | `sase_macros`; `SASE_MACRO_*`, `SASE_*_MACROS`                                                                     |
| `sase-xprompt-lsp`, crate `sase_xprompt_lsp`, `sase.xpromptLsp.*`                                                                     | `sase-macro-lsp`, `sase_macro_lsp`, `sase.macroLsp.*`                                                              |
| `~/.sase/vcs_xprompt_mru.json`, `~/.sase/xprompt_save_state.json` (key `xprompt`), `~/.sase/xprompt_lsp/`                             | `vcs_macro_mru.json`, `macro_save_state.json` (key `macro`), `macro_lsp/`                                          |
| agent artifacts `xprompts.json`, `xprompts_<step>.json`, `raw_xprompt.md`, `submitted_xprompt.md`                                     | `macros.json`, `macros_<step>.json`, `raw_prompt.md`, `submitted_prompt.md`                                        |
| doctor ids `config.model_xprompts`, `config.xprompt_definitions`, `config.xprompt_directives`, `tools.xprompt_lsp`                    | `config.model_macros`, `config.macro_definitions`, `config.macro_directives`, `tools.macro_lsp`                    |
| Telegram `/xprompts`; mobile route `/api/v1/xprompts/catalog`                                                                         | `/macros`; `/api/v1/macros/catalog`                                                                                |
| `%proc` origin `xprompt-proc` / field `xprompt_proc`                                                                                  | `prompt-proc` / `prompt_proc`                                                                                      |

The old page `sase.sh/xprompt/` redirects here.

## Legacy Placeholders

For templates that do not use Jinja2 syntax, a legacy placeholder mode is available.
Placeholders use `{N}` syntax (1-indexed):

```
Review the {1} module and check for {2:correctness}.
```

- `{1}` -- required first positional argument.
- `{2:correctness}` -- second positional argument with default `correctness`.

Legacy mode is auto-detected: if the body contains no Jinja2 markers, legacy
substitution is used.

## Related

- [Macro reference](../macros/index.md)
