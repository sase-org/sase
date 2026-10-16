---
title: "Prompt and tool configuration"
description: "Configuration for hooks, plugins, mentors, macros, and named tools."
---

# Prompt and tool configuration

Configuration for hooks, plugins, mentors, macros, and named tools.

<a id="filehooks"></a>

## file_hooks

Defines non-gating commands that run once per matching file event. Use
`sase file-hook list` to inspect the effective hooks, including the config layer that
contributed each entry; add `-j/--json` for machine-readable output. Use
`sase file-hook history` and `sase file-hook show` to inspect producer audits for
whether a matching event was dispatched, unmatched, or failed before a command ran.

```yaml
file_hooks:
  - name: research-highlights
    description: Render new research reports into Highlights PDFs.
    command: bob highlights create
    filters:
      projects: [sase]
      sidecars: [research]
      path_globs: ["20*/**/*.md", "!20*/*__*.md", "!20*/*/*__*.md"]
      agent_name_globs:
        - "!research.*.cdx"
        - "!research.*.cld"
        - "!research.*.grk"
        - "!research.*.mus"
        - "!research.*.gem"
      ops: [ADD]
      producers: [commit, sdd, finalizer]
    timeout: 120s
```

Hook fields:

[Generated reference for `file_hooks`](prompts.md#file_hooks)

Without `use`, `name` and `command` are required. With `use`, SASE deep-merges the local
entry over the installed provider's template, defaults `name` to the provider ID, and
requires any fields the provider marks as local. `use` must be qualified as
`<plugin>@<id>`, where `<plugin>` is the literal `builtin` or the installed distribution
name; a bare, unprefixed, or unknown `use` value disables only that invalid entry, is
reported while `sase file-hook list` loads effective hooks, and also fails
`sase doctor -C config.file_hooks` and `sase validate` so a disappeared hook can never
go unnoticed. A plugin can therefore ship safe defaults while requiring the
machine-specific command or destination in user configuration.

Filter fields under `filters`:

[Generated reference for `file_hooks`](prompts.md#file_hooks)

Matching semantics:

- **Event sources.** Hooks receive files from commits created by `sase stitch create`
  (producer `commit`), commits written through the SDD sidecar commit path (producer
  `sdd`), and `sase artifact create` (producer `artifact`, treated as `ADD`). Finalizer
  reconciliation re-derives a commit's events (producer `finalizer`). Direct engine
  dispatch uses producer `dispatch`.
- **Ops.** Commit operations come from `git diff --name-status`; renames split into
  `REMOVE` plus `ADD`, root-commit files are `ADD`, and unknown status letters fold to
  `MODIFY`.
- **Path glob matching.** `filters.path_globs` match the file's repo-root-relative POSIX
  path. Positive globs are OR-ed, while any matching `!` negative veto-excludes the
  file. `*` does not cross `/`; `**` does. A negative-only list means “everything
  except.” Dotfiles are eligible.
- **Agent-name matching.** `filters.agent_name_globs` match the resolved SASE agent
  name. Positives are OR-ed and `!` vetoes, exactly as for paths. Agent names contain no
  `/`, so `*` spans the whole name (`research.*.cld` matches `research.7.cld`). An event
  with no resolvable agent name matches a negative-only list, but never a list
  containing any positive pattern.
- **Attribution.** The agent name is resolved in the producing process from
  `$SASE_ARTIFACTS_DIR/agent_meta.json`'s `name`, falling back to `$SASE_AGENT_NAME`, so
  a commit made outside a SASE agent has no agent name.
- **Causes.** Ordinary user-originated commits always remain eligible. Internally
  generated commits are ignored unless their cause appears in `filters.causes`; the
  current non-user cause is `artifact_links`, used when SASE updates managed Links and
  Referenced By blocks in artifact sidecars. This opt-in prevents a projection update
  from recursively triggering ordinary document-processing hooks.
- **Filters.** All configured dimensions are AND-ed. `filters.projects` compares
  alias-resolved, user-facing project names, never ProjectSpec keys. `filters.sidecars`
  compares sidecar role names. `filters.producers` compares the dispatch producer
  identity; omitting it matches every producer. A project-local `sase/sase.yml`
  declaration without `filters.projects` is automatically scoped to the detected
  project.
- **Execution.** Runs are post-write and non-gating. Hook configuration, matching,
  persistence, spawn, or command failures never fail or block an artifact copy or a
  commit. Each matched command runs with the absolute path appended as a shell-quoted
  final argument and reports success or failure through a SASE notification. Every hook
  command also receives the producing project's display name (as `sase project list`
  shows it) in `SASE_FILE_HOOK_PROJECT`. The variable is unset when the project is
  missing or `unknown`, and any inherited value is removed first, so quote it as
  `"$SASE_FILE_HOOK_PROJECT"` (for example
  `command: bob ref create --include-id -P "$SASE_FILE_HOOK_PROJECT"`); a value
  containing spaces or shell punctuation then still arrives as one argument.
- **Artifact store paths.** Artifact events match against the original
  repository-relative path, but the detached command receives the durable stored copy.
  That copy is content-addressed and may use a digest-suffixed basename such as
  `<stem>-<sha256-prefix>.md`. Hooks whose output identity depends on the input basename
  should set `filters.producers` to the committed-file producers (`commit`, `sdd`,
  `finalizer`) so they do not run against the stored copy.
- **Producer audits.** Every configured-event dispatch attempt persists a bounded record
  under the file-hook state root (`audit/`) before returning. That record explains a
  filter miss, a dispatched or already-present batch, or a producer failure without
  relying on Python logging. Successful matches continue to use batches and run logs as
  the execution record. Audits follow the same 30-day retention as batches, runner logs,
  and run logs.
- **Producer failures vs command-run failures.** A _producer_ failure is a problem
  before a hook command runs: config load, event capture, batch persistence, or runner
  spawn. Those create one non-gating `file-hooks` error notification that points at the
  audit record. Ordinary no-hooks and filter-miss outcomes stay quiet. A _command-run_
  failure is the hook command itself exiting non-zero or timing out; that evidence stays
  on the batch run log and the existing per-run notification.
- **Finalizer reconciliation.** After a successful built-in commit marker is verified,
  finalization re-derives the committed file events and ensures the deterministic commit
  batch exists. An already-dispatched batch is reused without spawning again; a missed
  first dispatch is retried.

The user layer (`~/.config/sase/sase.yml`) replaces the bundled/default `file_hooks`
list. Selected machine overlays (`sase_*.yml`) and project-local `sase/sase.yml`
concatenate entries onto the effective list, matching `mentor_profiles` merge behavior.
Hook names must remain unique across the effective list; invalid or duplicate entries
are warned about and skipped. Unknown `file_hooks` keys are rejected the same way, so a
hook carrying one is skipped with a warning rather than silently losing that filter.
Filter fields at the hook top level are no longer accepted; move `projects`, `sidecars`,
`path_globs`, `agent_name_globs`, `ops`, `causes`, and `producers` under `filters`. Note
that `globs` was renamed to `filters.path_globs`; the old key is not accepted.

Source: `src/sase/config/file_hooks.py`, `src/sase/file_hooks/engine.py`,
`src/sase/file_hooks/audit.py`, `src/sase/file_hooks/producer.py`,
`src/sase/config/sase.schema.json`

## plugins

Declares the distributions this project needs installed in the running environment. A
linked or sidecar checkout is not an install.

```yaml
plugins:
  required:
    - sase-github
    - sase-research-artifacts>=0.2
```

[Generated reference for `plugins`](prompts.md#plugins)

Every non-`builtin` `<plugin>@` prefix used anywhere in this project config — artifact
references, file hooks, and `bead.task_types[].use` — must name a distribution listed
here. That single rule keeps a project's declared dependencies honest.

Enforcement is graded by blast radius:

| Surface                                                          | Behavior                                                                                         |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `sase memory init`, `sase validate`                              | Hard error, raised before any memory-drift comparison so a missing plugin never looks like drift |
| `sase bead create -T 'task(<slug>)'` for a missing plugin's slug | Hard error naming the plugin and `sase plugin install <name>`                                    |
| `sase doctor -C plugins.required`                                | `ERROR` severity, listing each missing requirement and the install command                       |
| Interactive human CLI and sase's TUI                             | A `PluginsRequired` gate offering to install                                                     |
| Agent / non-interactive contexts                                 | Fail closed with the human-directed command; never auto-install                                  |
| `sase bead show` / `list` of an unknown type                     | Degraded render, never a failure                                                                 |

`use:` values themselves must be qualified as `<plugin>@<id>`, where `<plugin>` is the
literal `builtin` or a distribution name. A bare value is a hard error that names the
correct replacement when the live registry can resolve it.

See [Task Types](../work-units/beads.md#task-types) for how required plugins feed the
committed `sase/task_types.json` snapshot, and
[Required Plugin Notification](../automation/notification-types.md#required-plugin-notification)
for the human install offer.

Source: `src/sase/plugins/required.py`, `src/sase/config/sase.schema.json`

<a id="mentorprofiles"></a>

## mentor_profiles

Defines mentor agents that run automated code reviews when a Patch's diff, changed
files, or amend notes match configurable criteria. Each profile groups one or more
mentors with shared matching rules. See the
[Mentors reference](../automation/mentors.md) for the full mentor system reference.

```yaml
mentor_profiles:
  - profile_name: python_review
    file_globs:
      - "*.py"
    mentors:
      - mentor_name: style_checker
        role: "Python style expert"
        focus_areas:
          - focus_name: style
            description: "PEP 8 compliance and code style"
          - focus_name: naming
            description: "Variable and function naming conventions"

  - profile_name: first_commit_review
    first_commit: true
    mentors:
      - mentor_name: architecture
        role: "Software architect"
        focus_areas:
          - focus_name: design
            description: "Overall design and architectural patterns"
```

**Profile fields:**

[Generated reference for `mentor_profiles`](prompts.md#mentor_profiles)

\*At least one of `file_globs`, `diff_regexes`, `amend_note_regexes`, or `first_commit`
must be provided per profile.

**Mentor fields:**

[Generated reference for `mentor_profiles`](prompts.md#mentor_profiles)

**Focus area fields:**

[Generated reference for `mentor_profiles`](prompts.md#mentor_profiles)

Mentors run automatically on Patches with Ready or Mailed status when their matching
criteria are met. Mentor comments are structured JSON with severity levels (error,
warning, suggestion) that can be reviewed and applied through the Mentor Review modal in
sase's TUI (`,C`).

Source: `src/sase/config/mentor.py`

## metahooks

Metahooks intercept failing hooks before the summarize agent runs. They match based on
the hook command (substring match) and the hook output (regex match). When a metahook
matches, it can trigger specialized handling instead of the default summarization.

```yaml
metahooks:
  - name: scuba
    hook_command: sase_hg_presubmit
    output_regex: "SCUBA_ERROR.*timeout"

  - name: flaky_test
    hook_command: blaze test
    output_regex: "FLAKY"
```

[Generated reference for `metahooks`](prompts.md#metahooks)

Source: `src/sase/config/metahook.py`

## macros

Defines reusable prompt snippets that can be referenced with `#name` syntax in any
prompt. Supports both simple string content and structured definitions with typed inputs
and Jinja2 templates.

```yaml
macros:
  # Simple string format
  greeting: "Hello, please review this code."

  # Structured format with inputs
  review:
    input:
      language: word
      strict: { type: bool, default: false }
    content: "Review this {{ language }} code.{{ ' Be strict.' if strict }}"

  # With tags for semantic role lookup
  my_crs:
    content: "Summarize the code review..."
    tags: [crs]
```

Macros use the shared first-wins content-layout order:

1. Project `sase/macros/`, then legacy project `.macros/` and `macros/`
2. Home `~/sase/macros/`, then legacy home `~/.macros/` and `~/macros/`
3. `~/sase/macros/{project}/`, then legacy `~/.config/sase/macros/{project}/`
4. Project `sase/sase.yml` (root `sase.yml` is an exclusive legacy fallback)
5. User `sase_*.yml` overlays, then `~/.config/sase/sase.yml`
6. Plugin config and package default config
7. Plugin macro resources
8. `<sase_package>/default_macros/*.md`, then `<sase_package>/macros/*.md`

Earlier sources win on name conflicts. Project and home canonical directories are the
only writable filesystem destinations; legacy directories remain read-compatible but are
not offered for new saves. File-based macros use YAML front matter for metadata and the
file body for content. The
[Macro discovery table](../macros/discovery.md#discovery-order) lists every source
separately.

Source: `src/sase/macro/loader.py` <a id="macroaliases"></a>

## macro_aliases

Defines raw text-level alias substitutions that are applied _before_ any macro
processing. This is useful for creating shorthand references where the alias must be
present in the raw text for other processing logic (such as VCS directory-switching) to
work correctly.

```yaml
macro_aliases:
  c: commit # #c → #commit
  p: propose # #p → #propose
  deploy_notes: "release-notes" # #deploy_notes → #release-notes
  gh_foo: "gh:foo/bar" # #gh_foo → #gh:foo/bar
```

[Generated reference for `macro_aliases`](prompts.md#macro_aliases)

The built-in defaults provide `#c` as a shorthand for `#commit` and `#p` for `#propose`.
Additional aliases can be added in user config files.

Each entry maps an alias name to a target string. When the processor encounters
`#alias_name` in a prompt, it replaces it with `#target` before any other macro
resolution occurs. Only `#`-prefixed references are substituted; the alias name must
match `[a-zA-Z_][a-zA-Z0-9_]*`.

Source: `src/sase/macro/processor.py`

## tools

Named tool catalogs are project-owned complete entries in `sase/sase.yml`. SASE does not
read argv from the recursively merged config: `tools:` in builtin, plugin, user, or
machine layers is diagnosed and ignored so list concatenation and deep merge cannot
change execution identity. Malformed project YAML or catalog fields are actionable
errors, not an empty catalog.

```yaml
tools:
  check:
    argv: [just, check]
    description: Run the repository scoped check.
    stages: run_silent
    inputs: [Justfile]
    env: [SASE_PYTEST_WORKERS]
    args: deny
    fingerprint:
      toolchain:
        python: [python, --version]
```

[Generated reference for `tools`](prompts.md#tools)

`sase tool list` reports LAST (newest native result for this project and definition) and
TYPICAL (median duration of up to 30 normally exited native runs in 30 days). Missing
samples render as an em dash, never as zero or an ETA. It also reports CLASS (the
effective duration class, `short` when unset) and calibrates each declaration against
the corpus (see [Duration classes](../automation/tools.md#duration-classes)).

Source: `src/sase/config/sase.schema.json`, `src/sase/config/tools.py`,
`src/sase/main/tool_handler.py`

## Related

- [Prompts and tools configuration](prompts.md) — generated keys and defaults.
- [Macros](../macros/index.md) — macro behavior and syntax.
