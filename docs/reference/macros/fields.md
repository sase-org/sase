---
title: Macro fields
description: The snippet, skill, and memory fields available in macro front matter.
---

# Macro fields

This page documents the snippet, skill, and memory fields available to macros.

## Snippet Field

Macros can opt-in to sase's TUI snippet expansion by setting the `snippet` field in
their front matter. When set, the macro's content is converted into a snippet template
and merged into sase's TUI snippet registry at startup, so users can expand it by typing
the trigger word and pressing `Tab`.

```markdown
---
name: review
snippet: true
input:
  language: word
---

Review this {{ language }} code for correctness and style.
```

**Values:**

| Value           | Behavior                                                   |
| --------------- | ---------------------------------------------------------- |
| `true`          | Use the macro's base name (part after last `/`) as trigger |
| `"custom_name"` | Use the custom string as the trigger word                  |

**Conversion rules:**

- Normal macro references in the content are expanded before conversion, so snippets can
  compose reusable macros
- `{{ input_name }}` placeholders for required inputs become snippet tabstops (`$1`,
  `$2`, etc.)
- `{{ input_name }}` placeholders for inputs with defaults are pre-filled with the
  default value
- Placeholder mode for `{N}` templates is described in
  [Macro migration notes](../upgrading/macros.md#legacy-placeholders)
- Macros with complex Jinja2 control flow (`{% %}` or `{# #}`) are skipped
- User-defined snippets in `ace.snippets` take precedence over macro-derived snippets on
  name collision

Snippet templates can reuse other snippets with `#[trigger]` after the macro snippets
and `ace.snippets` entries are merged. The referenced snippet's `$1`, `$2`, ... tabstops
are spliced into the caller and renumbered in document order:

```yaml
ace:
  snippets:
    greet: "Hello $1!$0"
    welcome: "#[greet] Welcome to $1.$0"
```

`welcome` expands as `Hello $1! Welcome to $2.$0`. Positional arguments fill the
referenced tabstops before the splice: `#[greet(World)]` or `#[greet:World]` expands as
`Hello World!`.

After the merge, each effective snippet also gains a generated initial-capital alias —
only the first character of the trigger and of the resolved template is uppercased. A
macro-derived `foo` therefore expands as both `foo` and `Foo`, already-capitalized
triggers produce no extra entry, an explicitly authored `Foo` is never replaced, and
both spellings can be referenced with `#[foo]` / `#[Foo]`. The aliases are runtime-only.
See [Capitalized aliases](../tui/snippets.md#capitalized-aliases) for the complete
rule.

Snippets saved from sase's TUI prompt panel become available immediately to all prompt
inputs in that running TUI. With `use_chezmoi` enabled, this includes a snippet written
only to the chezmoi source tree: sase's TUI keeps a session overlay until the applied
config catches up. The optional confirmed commit/push flow applies chezmoi; saving by
itself does not apply unconfirmed source changes.

Editor clients receive the same templates through `sase lsp` when they support LSP
snippets. To troubleshoot the raw registry, run:

```bash
printf '{"schema_version":1}\n' | sase editor helper-bridge snippet-catalog
```

See [Snippets](../tui/snippets.md#snippets-1) for snippet usage in the prompt input
widget and editor completion, and [Snippets panel](../tui/prompt-completion-panels.md#snippets-panel)
for sase's TUI browse-and-edit panel (`gT` / `Ctrl+G T`).

### Snippet CLI

`sase snippet` inspects the same composed catalog sase's TUI and the editor helper use.
Bare `sase snippet` defaults to `sase snippet list`. `-p/--project` accepts a display
name, alias, or project key, and output always renders the configured project name.

```bash
sase snippet list
sase snippet list todo -f names
sase snippet list Hello --definitions
sase snippet show greet
sase snippet show Greet -f markdown
sase snippet add todo "TODO($1)$0"
sase snippet add todo "TODO($1)$0" -F
sase snippet delete todo -n
sase snippet delete todo -a -f json
```

Each effective explicit trigger appears once. Generated initial-capital aliases (`foo` →
`Foo`) are metadata on that source entry, not extra rows; lookup still maps an alias or
unique prefix back to the explicit trigger. Macro-derived entries are viewable and
linkable, but they are source-edited: converting the generated template back into
macro/Jinja source would be lossy. Add and delete write only `ace.snippets`
contributions; deleting a read-only, plugin, or macro-derived entry is refused and the
command points at its source. When a config overlay is removed, the command reports the
definition that becomes effective next.

`sase snippet add TRIGGER TEMPLATE` validates a nonblank alphanumeric/underscore trigger
and a nonblank template, writes the resolved `ace.snippet_config_path` by default, and
supports `-t/--target`, `-n/--dry-run`, and `-f/--format rich|json`. It refuses an
accidental overwrite or shadow unless `-F/--force` is given and names the source that
currently wins. Dry runs run the same validation and planning as a real write without
touching the destination, config caches, chezmoi, or git.

`sase snippet delete TRIGGER` removes the winning writable `ace.snippets` contribution.
`-a/--all` removes every writable config-layer contribution. The output includes a
shell-quotable `sase snippet add …` restore command (with `-F` when restoring would
shadow again) and any newly revealed lower-priority definition.

`sase snippet list [PATTERN]` supports `-d/--definitions` matching and
`-f/--format table|names|json`. The table shows trigger, origin, calls, backlinks, and a
compact raw-template summary. Names and JSON are color-free and pipe-safe.

`sase snippet show TRIGGER` supports `-f/--format rich|markdown|json` and prints the raw
template, composed expansion, source stack, aliases, calls, backlinks, unresolved calls,
and cycle diagnostics.

See [CLI Reference](cli-and-editor.md#prompt-and-workflow-authoring).

Source: `src/sase/macro/snippet_bridge.py`, `src/sase/macro/models.py`,
`src/sase/snippet/`

## Skill Field

A skill is a Markdown source that lives in a canonical `skills/` directory _and_ sets a
truthy `skill` field in its front matter. Both halves are required, and the rule is
two-way: a `skill:` declaration in an ordinary `macros/` directory or a config entry is
rejected with a migration diagnostic, and a file in a `skills/` directory that declares
no truthy `skill` value is rejected the same way. `sase skill list` shows the loaded
skill catalog without writing files, and reports misplaced sources instead of silently
dropping them.

`sase skill init` reads that catalog to determine which sources should be rendered into
per-provider `SKILL.md` files and deployed to agent skill directories; it refuses to
generate anything while any placement violation remains. By default, generated skill
files begin with a `sase skill use <name> --reason ...` directive so SASE can audit
which skills an agent used; set `log_skill_use: false` in a skill source to omit that
directive (see below). Recorded skill uses can be summarized and inspected with
`sase skill log`. The compatibility alias `sase init skills` runs the same initializer.

```markdown
---
# sase/skills/sase_git_commit.md
name: sase_git_commit
skill: true
description: Commit changes using sase stitch create for git-based VCS
---

Commit instructions here...
```

### Canonical Skill Sources

Skill sources are discovered from these directories, first source wins:

| Scope          | Directory                                            | `#` reference             |
| -------------- | ---------------------------------------------------- | ------------------------- |
| Project        | `<project>/sase/skills/`                             | `#<project>/skill/<name>` |
| Home           | `~/sase/skills/` (`home/sase/skills/` under chezmoi) | `#skill/<name>`           |
| Project (home) | `~/sase/skills/<project>/`                           | `#<project>/skill/<name>` |
| Plugin         | the plugin's `skills/` resource directory            | `#skill/<name>`           |
| Package        | `src/sase/macros/skills/`                            | `#skill/<name>`           |

Ordinary project and home macros, workflows, and shared `steps/` stay under
`sase/macros/`; that tree never holds a skill. Bundled SASE skill Markdown is the
package-source exception and lives in the nested `src/sase/macros/skills/` resource.

### Source, Reference, and Provider Names

One skill source carries three distinct names, and they are not interchangeable:

- The **source name** is the file stem (or the front matter `name`), e.g. `sase_plan`.
- The **macro reference name** is namespaced with a `skill/` segment, so
  `#skill/sase_plan` expands the source inline. A project-scoped source is qualified
  further: `#app/skill/foo`.
- The **provider skill name** is the bare source name, so the installed agent skill is
  invoked as `/sase_plan` and generated files keep their existing
  `.../skills/sase_plan/SKILL.md` paths.

This split was a hard cutover: there is no `#sase_plan` compatibility alias, no fallback
from `#foo` to `#skill/foo`, and no read compatibility for the old bundled Markdown
`src/sase/skills/` layout. `sase doctor`, `sase validate`, `sase macro show`,
`sase skill list`, and `sase skill init` all name the offending source and the exact
move required.

Machine-readable surfaces carry both names: `sase macro list`, the structured catalog,
and the mobile/editor helper bridges emit `name` as the `#` reference alongside
`is_skill` and a `skill_name` field holding the `/` name. `sase macro show` prints the
reference, a `slash` row, and a `skill · /<name>` chip.

**Values:**

| Value               | Behavior                            |
| ------------------- | ----------------------------------- |
| `true`              | Deploy to all registered providers  |
| `["claude", "agy"]` | Deploy only to the listed providers |

The `description` field provides a human-readable summary shown in `sase macro list` and
`sase skill list` output. The structured catalog also marks these entries with
`is_skill: true`; sase's TUI and editor clients use that flag together with `skill_name`
to offer slash-skill completions such as `/sase_plan` while keeping ordinary macros out
of slash completion results. `#` completion inserts `#skill/sase_plan`, `/` completion
inserts `/sase_plan`, and both resolve the same source definition for argument hints,
hover, and definition navigation.

The optional `log_skill_use` boolean field controls the generated audit directive. It
defaults to `true`, so generated skills instruct the agent to run
`sase skill use <name> --reason ...` as their first step. Set `log_skill_use: false` to
suppress that directive for skills that should not record their own use (the bundled
`/sase_plan` and `/sase_memory_read` skills set this). The field only affects sources
that are also marked as skills.

**Workflow:** Edit packaged skill sources in `src/sase/macros/skills/`, or add a source
to a project's `sase/skills/` or your `~/sase/skills/` directory. Saving a draft that
declares `skill:` from sase's TUI only offers those canonical directories, and the
ordinary macro and config writers refuse a request that would smuggle a skill definition
into `sase/macros/`. Do not include the `sase skill use` directive yourself; the
generator injects it unless `log_skill_use: false` is set. Then run `sase skill list`
and `sase skill init --dry-run` (or `--diff`) to preview. Commit the source change and
land it on the canonical branch before deploying, then run `sase skill init --force`: a
chezmoi deploy is refused when `src/sase/macros/skills/` is dirty, when `HEAD` is not an
ancestor of the canonical branch, or when it would move the destination off the source
commit recorded in the provenance manifest — see
[Commit Before Deploying](../agents/initialization.md#commit-before-deploying). The same manifest is also an
ownership registry for generated source/live skill-file pairs. When a source changes
name, is deleted, or stops targeting a provider, a full `sase skill init --force` deployment
tombstones the retired pair, commits the source-side removal, deletes the live target
immediately before `chezmoi apply --force`, and keeps the tombstone so an interrupted
cleanup can be retried idempotently. When `use_chezmoi` is enabled, `sase skill init`
commits, pushes, and applies the generated files unless passed `--no-commit`,
`--no-push`, or `--no-apply`; those skip flags also leave retired live targets untouched
for a later full deployment. Do not edit deployed `SKILL.md` files directly.
`sase init skills` is a compatibility alias for `sase skill init`.

Editing an existing skill source from sase's TUI targets it like any other macro
definition, and saving it offers `sase skill init` in place of a bare commit/push, since
that command already commits, pushes, and deploys for you — see
[Editing an Existing Macro from the TUI](../tui/prompt-input.md#editing-an-existing-macro-from-the-tui).

Provider plugins declare where generated skills should be written. A source can target
multiple providers, and a provider can have multiple filesystem targets. Built-in
targets are:

`sase skill list` reports retired managed targets as deletion drift, including both the
chezmoi source path and the live home path that the next successful full deployment will
remove.

| Provider          | Skill target(s)                                     |
| ----------------- | --------------------------------------------------- |
| Claude            | `~/.claude/skills/<skill>/SKILL.md`                 |
| Codex             | `~/.codex/skills/<skill>/SKILL.md`                  |
| Antigravity (agy) | `~/.gemini/antigravity-cli/skills/<skill>/SKILL.md` |
| Qwen              | `~/.qwen/skills/<skill>/SKILL.md`                   |
| OpenCode          | `~/.config/opencode/skills/<skill>/SKILL.md`        |
| Muse Code         | `~/.config/muse/skills/<skill>/SKILL.md`            |
| Grok Build        | `~/.grok/skills/<skill>/SKILL.md`                   |

### Bundled Skills

The following skills ship in `src/sase/macros/skills/` and are deployed by
`sase skill init`. They are packaged with sase, included in `sase macro list` as
`skill/<name>`, and available to prompt completion clients even when a checkout does not
have local skill files. Coding agents invoke them by their provider names, such as
`/sase_plan` or `/sase_repo`; expand one inline as `#skill/sase_plan`. Other scopes can
add more skill sources, so `sase skill list` may show entries that are not bundled here:

| Skill                | Purpose                                                                                       |
| -------------------- | --------------------------------------------------------------------------------------------- |
| `sase_agents_status` | Report on currently running SASE agents                                                       |
| `sase_chats`         | Inspect prior SASE agent prompts and responses                                                |
| `sase_final`         | Submit the current turn's SASE finalizer declaration                                          |
| `sase_gate`          | Create a durable custom confirmation gate for a proposed command or decision                  |
| `sase_git_commit`    | Commit through `sase stitch create` for git and GitHub workflows                              |
| `sase_handoff`       | Hand this agent's turn to the next session member with `sase pipe`                            |
| `sase_memory_read`   | Perform audited reference memory reads through `sase memory read`                             |
| `sase_memory_write`  | Gate every SASE memory-file create, edit, or delete before making it                          |
| `sase_monitor`       | Run a long command without blocking your turn                                                 |
| `sase_new_task`      | Use before creating, filing, proposing, or otherwise recording any new SASE task bead         |
| `sase_notify`        | Inspect SASE notifications and notification inbox entries                                     |
| `sase_patches`       | Inspect and reason about Patches, stitches, hooks, comments, and mentors                      |
| `sase_plan`          | Create and submit an implementation plan when provider-native plan mode is disabled           |
| `sase_project`       | Inspect or manage project lifecycle state and aliases                                         |
| `sase_questions`     | Ask the user structured questions when the provider-native question tool is disabled          |
| `sase_repo`          | Open and audit linked, sidecar, other-project, or external repositories before accessing them |
| `sase_run`           | Request an agent-initiated launch through `LaunchApproval`                                    |
| `sase_sudo`          | Request reviewed privileged execution through a typed sudo gate instead of raw sudo           |
| `sase_var`           | Attach named output variables to the current SASE agent run                                   |

The sudo request workflow behind `sase_sudo` is described under
[Sudo Requests](../automation/sudo.md).

## Memory Field

Every valid, flat, non-README [SASE memory note](../memory/memory.md) that declares `type: core`
or `type: reference` frontmatter is automatically a macro — no opt-in field is required.
A note's filename remains its identity: `sase/memory/sase_beads.md` (or the home
equivalent) is invoked as `#memory/sase_beads`. Nested files such as
`sase/memory/assets/**` and `README.md` are never catalog entries. Type-free memory-web
descriptors are not catalog entries either: their bodies are already loaded through the
generated `## Memory Webs` instruction section, while strand bodies come from
`sase memory read <web>:<keyword>` (see [Memory Webs](../memory/memory.md#memory-webs)).

The `memory/` reference segment is reserved. There is no bare `#sase_beads` alias for
`#memory/sase_beads`, no `#memory/long/sase_beads` compatibility form, and an ordinary
macro, workflow, config entry, plugin, or skill that claims the `memory/` namespace is
rejected with a load diagnostic rather than silently losing the collision.

Resolution is contextual and first-wins: the selected project's note shadows a same-stem
home note, and an explicit registered-project selection reads only that project's
workspace rather than merging in another project's notes. Memory trees that coexist in
either scope use the memory subsystem's exclusive
collision policy. See
[Memory Order](../upgrading/content-layout.md#memory-order).

Expansion uses the ordinary simple-Markdown-macro rendering path after memory
frontmatter is stripped: a `#memory/<stem>` reference takes no arguments and does not
synthesize the `## Children` section that [`sase memory read`](../memory/memory.md#audited-reads)
appends. Macro references already authored in the note body still expand recursively.

`#memory/<stem>` is a launch-time, explicitly authored inclusion, not an audited
agent-side lookup: catalog discovery, previews, and expansion never append
`sase memory read` audit events. Use `/sase_memory_read` (`sase memory read`) instead
when an already-running agent needs to consult reference memory on its own and have that
access recorded. This is explicit prompt composition only — it does not restore the
retired dynamic-memory runtime, so there is no keyword matching, prompt scanning, or
automatic context injection.

Editing an existing note from sase's TUI targets it like any other macro definition, and
saving it offers `sase memory init` in place of a bare commit/push, since that command
already regenerates `AGENTS.md` and the provider instruction shims and commits and
pushes for you — see
[Editing an Existing Macro from the TUI](../tui/prompt-input.md#editing-an-existing-macro-from-the-tui).
With `use_chezmoi` enabled, the write itself redirects to the chezmoi source rather than
the applied copy under `~/sase/memory/`; see
[Paths That Did Not Move](../content-layout.md#paths-that-did-not-move).

Source: `src/sase/macro/loader_memory.py`, `src/sase/content_layout.py`.

## Related

- [Macro reference](index.md)
- [Built-in and configured macros](built-ins.md)
