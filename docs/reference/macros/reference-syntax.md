---
title: Macro files and reference syntax
description: Macro file format, reference forms, workspace references, and project tags.
---

# Macro files and reference syntax

This page documents macro file front matter, references, workspace targets, and project tags.

## File Format

A macro file is a Markdown file with optional YAML front matter delimited by `---`
lines. Everything after the closing `---` is the template body.

```markdown
---
name: greet
description: Greet a named user.
input:
  user_name:
    type: word
    description: User name to include in the greeting.
---

Hello, {{ user_name }}! Welcome aboard.
```

### Front Matter Fields

| Field         | Required | Description                                                                        |
| ------------- | -------- | ---------------------------------------------------------------------------------- |
| `name`        | No       | Macro name (defaults to filename stem)                                             |
| `input`       | No       | Input parameter definitions (see [Typed Inputs](arguments.md#typed-inputs))                    |
| `snippet`     | No       | Opt-in to sase's TUI snippet expansion (see [Snippet Field](fields.md#snippet-field) below) |
| `description` | No       | Human-readable one-line description of what the macro does                         |
| `skill`       | No       | Marks this macro as an agent skill source for `sase skill init` (see below)        |
| `macros`      | No       | File-local helper macros whose names must start with `_`                           |

If no front matter is present, the entire file content is the template body and the
filename stem is the name.

Markdown macro files can carry file-local helper macros under `macros:`. These helpers
use the same structured format as config-based macros, including typed inputs and
descriptions, and they can reference each other transitively. During expansion they
inherit the containing macro's arguments and template scope, so a helper can use values
such as `{{ topic }}` from the outer macro. They are visible only while expanding the
containing macro and must use `_`-prefixed names such as `_review_rules`; they do not
leak into the global catalog, completion catalog, or other macro files. This underscore
rule also applies to local macros in ad hoc prompt front matter, while YAML
workflow-local macros follow the workflow rules described in
[workflow specification](../workflows.md).

## Reference Syntax

Reference inline-capable macros inside any prompt with the `#` prefix, including
markdown-defined macro swarms whose body contains top-level `---` segment separators.
Use `#!` only for standalone YAML workflows that do not have a `prompt_part` step. The
marker must appear at the start of the string, after whitespace, or after one of
`([{"'`. For macro swarms, `#!name` is an accepted compatibility prefix; write `#name`
in new prompts. Each `#name` or `#!name` use is a _macro invocation_; the file or
config entry it names is the macro.

| Syntax                        | Description                                                    |
| ----------------------------- | -------------------------------------------------------------- |
| `#name`                       | Inline/template reference, no arguments                        |
| `#name(args)`                 | Inline parenthesis syntax with comma-separated arguments       |
| `#name:arg`                   | Inline colon syntax, passes `arg` as a single positional arg   |
| `#name:a,b,c`                 | Inline colon syntax with comma-separated multiple args         |
| `` #name:`arg with spaces` `` | Colon+backtick syntax for args containing spaces (single only) |
| `#name+`                      | Plus syntax, equivalent to `#name:true`                        |
| `#ns/name`                    | Namespaced reference (e.g., project-specific)                  |
| `#!name`                      | Standalone workflow reference, no args                         |
| `#!name(args)`                | Standalone workflow reference with parenthesized arguments     |
| `#!name:arg`                  | Standalone workflow reference with one colon-style arg         |
| `#!name!!` / `#!name??`       | Standalone workflow with an explicit HITL approval override    |

sase's TUI and editor clients that enable standard LSP on-type formatting smooth the
colon-to-parentheses transition while typing: with the caret immediately after an
argument-opening colon, typing `(` removes that colon. For example, `%q:` becomes `%q()`
in sase's TUI, with the cursor between the parentheses, and `#review:` can become
`#review()`. The rule is syntax-aware; ordinary prose colons, URLs, unknown directives,
double-colon shorthand, fenced or inline code, disabled macro regions, prompt
frontmatter, and Jinja tags are left alone.

Accepting a macro entry with optional inputs from completion inserts the reference with
a completion-owned trailing space (for example, `#optional ` with the caret after the
space). Typing `(` immediately after that space deletes only the owned space and opens
parenthesized arguments — `#optional()` with the caret between the parentheses —
followed by the existing argument menu, including `topic=`; accepting that row produces
`#optional(topic=)`. The rewrite applies only while the accepted reference and space are
intact, the selection is empty, and the widget is in insert mode: any other key consumes
eligibility, pasted or manually typed lookalike text never acquires it, and a zero-input
macro keeps its space with ordinary pairing behavior. Suffix text and snippet
placeholders are preserved, and the automatic argument menu respects `auto_macro_menu`;
disabling that menu does not disable the space rewrite. In external editors over LSP,
the same rewrite needs a client that executes completion-item commands, applies `(`
on-type formatting, and requests completion on the advertised `(` trigger. Clients
missing those facilities retain ordinary editing, and the server cannot reproduce the
widget's exact move-away-and-back cancellation.

For double-colon text shorthand, typing `(` immediately after the `::` and any ASCII
spaces moves the delimiter after a new argument pair instead: `#review:: ` becomes
`#review():: ` with the caret inside `()`, and `#review:: body` becomes
`#review():: body`. The authored spaces and suffix text are preserved exactly, and tabs,
newlines, nonbreaking spaces, existing argument lists, and literal regions keep ordinary
insertion behavior. This pairing applies to macro references (including `#!name::`) and
to the `%proc::` and `%clan::` / `%c::` directive forms; other directives followed by
`::`, such as `%if::` or `%q::`, just insert `()`.

When a `#` macro reference already has a closed parenthesized argument list, typing `(`
immediately after its `)` continues the list: `#review(path=a)` becomes
`#review(path=a,|)`, and `#review(path=a):: body` becomes `#review(path=a,|):: body`,
where `|` marks the caret. The edit adds a comma after the last non-whitespace argument
character and moves the caret before `)`; an empty list or an argument list that already
ends in a comma only moves the caret. In the TUI, the remaining argument menu opens when
`auto_macro_menu` is enabled. This applies to `#` macro references, not `%` directives.
Over LSP, on-type formatting makes the text edit; the menu comes from the client's next
completion request, so it may appear after the next argument character or when
completion is invoked manually.

Examples:

```bash
sase run '#!sync'
sase run '+sase #!sync'
```

Top-level `sase run '#sync'` invocations are accepted with a warning that points to
`#!sync`; new invocations should use the standalone prefix. Inline expansion contexts
reject standalone workflows instead of passing literal `#sync` text to the model. Shell
examples should use single quotes around `#!...` so `!` is not interpreted by
interactive shells. See [Macro migration notes](../upgrading/macros.md#workflow-launch-syntax).

A `#`-shaped token that matches no known macro, workspace ref, or plugin-provided
reference is **not** an error: it is passed to the agent as literal text. Because a typo
would otherwise be invisible, launching scans the prompt first and reports each
unresolved name — `sase run` prints one warning per name (with a `did you mean '#…'?`
suggestion when a close match exists, and a pointer to `sase macro list`), and sase's
TUI raises one aggregated toast,
`Unknown macro reference(s): #foo - passed through as literal text`. The scan is a
best-effort diagnostic: it never blocks or alters the launch, and references inside
literal zones (inline code, fenced code, disabled regions) are ignored.

For workspace references, underscores can be used as an alternative to colons:
`#gh_sase` is equivalent to `#gh:sase`. The underscore is normalized to a colon before
pattern matching, so both forms work identically. This is useful in contexts where
colons are inconvenient.

Provider-backed references also support `@name` agent references in the ref portion. The
`@name` is resolved at runtime to the named agent's Patch (branch name), allowing one
agent's prompt to target another agent's workspace:

```
#gh:@planner     resolves to e.g. #gh:planner_add_config_parser
#gh_@reviewer    same, underscore form
```

This is useful when chaining agents — for example, a review agent can target the branch
created by a prior agent using `@name` instead of hardcoding the branch name.

### VCS Workspace References

Workspace-managing workflows use the same `#name:ref` reference syntax as macros, but
they control where the agent runs before the rest of the prompt is executed. Built-in
`#git` references are VCS-backed; provider plugins can add other workspace refs such as
`#gh`.

| Reference           | Behavior                                                       |
| ------------------- | -------------------------------------------------------------- |
| `#git:<ref>`        | Run in a bare-git workspace                                    |
| `#gh:<ref>`         | Run in a GitHub workspace, when the GitHub plugin is installed |
| `#<provider>:<ref>` | Run through any other installed workspace provider             |

Prompts that do not contain a workspace reference are normalized to `#git:home`, so a
bare prompt runs from the managed bare-git `home` project by default and gets normal
numbered workspace, checkout, diff, and release behavior.

By default, a missing `home` ProjectSpec is bootstrapped as a managed empty bare-git
project at the default `home` paths. An existing project owned by another workspace
provider is never converted in place: a mismatched `#git:home` fails with a hint to use
the provider's VCS tag. To make bare prompts use an existing home/dotfiles bare
repository, register a bare repository whose basename resolves to `home`, for example
`#git:/path/to/home.git`.

Provider-prefixed refs that point at a known project name are preserved as workspace
launches even if the matching workspace plugin is not loaded in the current process.
Known projects come from `~/.sase/projects/*/*.sase` (with `~/.sase/projects/*/*.gp`
accepted as a fallback). A launch such as `#gh:sase #!sync`
therefore targets the registered `sase` project, allocates a numbered workspace for
non-wait runs, and lets dispatch surfaces strip the wrapper ref when identifying an
embedded workflow body.

Known projects may also declare `PROJECT_NAME` and `PROJECT_ALIASES` in their
ProjectSpec. Friendly refs in VCS workspace tags are canonicalized before workspace
resolution and macro expansion, so `#gh:bob #p` is processed as a ref to the
directory-key project when that project declares `PROJECT_NAME: bob` or alias `bob`. The
rewrite is exact and applies to colon, underscore, and parenthesized workspace-ref
forms; it does not rewrite owner/repo paths such as `#gh:bbugyi200/bob`, partial project
names, prose, or fenced code examples. The tag must also match the registered project's
actual workspace provider. A provider-mismatched alias is left unchanged rather than
canonicalized to that project's directory key, but this does not make it a rejected
reference: because an unknown slashless `#git:` name triggers bare-git project
initialization, `#git:<github-alias>` may create a separate bare-git project named after
the alias. Use `#gh:<github-alias>` for the registered GitHub project.
Provider-mismatched entries are pruned from the VCS-reference history. See
[Project Names and Aliases](../work-units/project-spec.md#project-names-and-aliases) for validation
and management commands.

GitHub `owner/repo` refs use `PROJECT_NAME` after first use. Resolving `#gh:foo-org/foo`
creates or reuses the canonical project whose `WORKSPACE_DIR` is
`~/projects/github/foo-org/foo/`; for a new repo that canonical directory key is
typically `gh_foo-org__foo`, with `PROJECT_NAME: foo`. A second repo with the same
basename, such as `#gh:bar-org/foo`, gets a different canonical project such as
`gh_bar-org__foo` and the next available display name, for example `foo_1`. Future
launches can use `#gh:foo` and `#gh:foo_1`, and those refs canonicalize before prompt
history, metadata, and artifacts are written.

For compatibility, existing basename ProjectSpecs are reused when their `WORKSPACE_DIR`
already matches the GitHub repo. Owner/repo fallback avoids basename routing when
duplicate GitHub basenames would make that ambiguous; direct `owner/repo` refs match the
GitHub workspace path first, then only use a basename fallback when it is unambiguous.

A known project can also be targeted with its shorter `+<project>` tag, such as `+sase`,
which expands to the canonical workspace reference at launch; see
[Project Tags](#project-tags), which also covers `+query` project/Patch completion.

sase's TUI and the macro LSP also provide token-local completion at the root of
registered VCS workflow refs. Typing `:` or `(` after a workflow tag, such as `#gh:` or
`#git(`, opens project and active PR-sized Patch rows scoped to that provider. Providers
can add fast local namespace rows; the GitHub plugin derives organization rows from
enabled GitHub project records and `github_orgs`. Accepting a project or Patch completes
the current token, for example `#gh:sase ` or `#gh(sase)`. Accepting a namespace inserts
a trailing slash such as `#gh:sase-org/` without closing the token, so repository
completion can immediately take over.

sase's TUI and the macro LSP also complete repositories inside provider refs after the
namespace slash. Typing `#gh:bbugyi200/` asks the registered GitHub workspace plugin for
repositories owned by `bbugyi200`; typing `#gh:bbugyi200/sa` narrows the menu toward
matching repository names. Accepting a row rewrites only the current ref value, so colon
form becomes `#gh:bbugyi200/sase ` and parenthesized form becomes `#gh(bbugyi200/sase)`.
The hook is provider-agnostic: another workspace plugin can support the same UX for
nested namespaces such as `#gl:group/subgroup/` by implementing repository candidate
listing.

Known-project discovery defaults to enabled ProjectSpecs. Disabled and sibling records
are omitted from broad project-local macro catalogs and completion menus. An explicitly
typed known-project `#` VCS ref is a launch-time exception: launch preparation writes
`PROJECT_STATE: enabled` before claiming the workspace. This is a persistent state
change, so use `sase project enable <project>` first when you prefer to make the
transition separately. A `+<project>` tag for a disabled project is rejected instead of
re-enabling it (see [Project Tags](#project-tags)). A checkout cwd or mobile `project`
value is context rather than a workspace ref; a prompt without an explicit ref defaults
to `#git:home`. Direct claims that bypass launch preparation remain blocked while the
ProjectSpec is disabled. Management and history code paths that need hidden projects opt
into an all-state scan explicitly.

Double underscores (`__`) in macro names are treated as forward slashes (`/`), enabling
flat references to namespaced macros. For example, `#foo__bar` resolves to the macro
registered as `foo/bar`, and `#a__b__c` resolves to `a/b/c`. Single underscores are not
affected. This is useful when `/` is inconvenient in certain input contexts (e.g., shell
completion or certain prompt editors).

Markdown headings like `# Heading` are not matched because a space after `#` prevents
the pattern from firing.

### Project Tags

A project tag is the short `+<project>` spelling of a known-project workspace reference.
`+sase fix the flaky test` targets the same workspace as `#gh:sase fix the flaky test`,
without you having to remember which provider the project uses. At launch, each tag that
resolves to a registered project is rewritten in place to that project's canonical
`#<workflow>:<directory-key>` reference, such as `#gh:gh_sase-org__sase`. Prompt
history, agent metadata, workspace claims, and the VCS MRU therefore record exactly what
a typed `#gh:sase` would have produced.

```bash
sase run '+sase summarize the open TODOs'
sase run '%model:opus +bob-cli fix the failing test'
sase run '%{+sase | +bob-cli} audit the README'   # one agent per project
```

**Syntax.** A tag is `+` followed by a name that starts with an ASCII letter and
continues with letters, digits, `_`, `.`, or `-`, without ending in `.` or `-`. The `+`
must sit at the start of the text or directly after whitespace, `{`, or `|`. The name
must be followed by whitespace, `|`, `}`, or the end of the text. So `C++`, `a+b`,
`(+sase)`, and `+sase,` are ordinary text. Tags inside fenced code, inline code,
disabled macro regions, and the leading YAML frontmatter block are ignored.

**Resolution.** A tag name matches a project's `PROJECT_NAME`, its directory key, or any
of its `PROJECT_ALIASES`. An exact match wins first, then a case-insensitive one, so
`+SASE` works too. The catalog covers enabled and disabled projects plus the
system-managed `home` project (`+home` expands to `#git:home`); sibling records are
excluded. A project whose `PROJECT_NAME` does not fit the tag syntax, such as one that
starts with a digit, gets no `+<name>` spelling in completion or display. A typed tag
can still reach it through a tag-shaped alias or directory key, or you can keep using
its `#<workflow>:<name>` reference. See
[Project Names and Aliases](../work-units/project-spec.md#project-names-and-aliases) for how names and
aliases are kept unique.

**Launch validation.** Tags are checked before anything is spawned, and a failing prompt
aborts the whole launch:

| Tag situation                                       | Result                                                                                                                     |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Resolves to an enabled project (or `home`)          | Expands to `#<workflow>:<directory-key>`.                                                                                  |
| Resolves to a disabled project                      | Error: `` `+beta` is disabled — `sase project enable beta` ``. Unlike a typed `#` ref, a tag does not re-enable a project. |
| Resolves to a project with no detected VCS provider | Error naming the unclaimed workspace.                                                                                      |
| Matches more than one project                       | Error listing the candidates; run `sase doctor` to find the collision.                                                     |
| Unknown, and _anchored_ (first word on its line)    | Error such as `Unknown project tag +ssae (line 1). Did you mean +sase, +home, or +bob-cli? Known: +bob-cli +home +sase`.   |
| Unknown, anywhere else                              | Left alone as plain text, so `run chmod +x build.sh` still launches.                                                       |

A tag is anchored when it is the first word on its line, ignoring leading whitespace and
leading `%directive` tokens (`%m:opus +ssae ...` is anchored). A resolved tag counts as
a workspace target wherever it appears, not only when anchored.

Each launch unit may name only one workspace target, and tags and `#` workspace refs
count together. `+sase +bob-cli do x` and `+sase #git:notes do x` both fail with
`Only one workspace target is allowed per launch unit, ...`. Each `---` segment of a
[multi-agent prompt](multi-agent-prompts.md#multi-agent-prompts) and each branch of a `%{a | b}` alternative
is its own unit, which is why the fan-out example above is valid. A segment containing a
resolvable tag is treated as already having a workspace reference, so the default
`#git:home` prefix is not added next to it.

Tags resolve against the launching machine's projects. `sase run`, sase's TUI, and
agent-requested launches (whose LaunchApproval preview reports tag errors) all validate
and expand tags the same way. `sase bead work` is the exception: it writes `+<project>`
prefixes itself and expands them without this validation, so, like a typed `#` ref, it
re-enables a disabled project. A prompt forwarded through
[remote dispatch](directive-syntax.md#remote-dispatch) is sent verbatim and resolves on the remote host. A
launch rejected by tag validation is kept in prompt history as a cancelled prompt, so
you can recover and fix it. When sase's TUI already has its project catalog cached, it
checks tags before the prompt editor closes: the error appears as a toast and the prompt
stays in place for editing.

**Completion.** sase's TUI and the macro LSP share one `+` project/Patch completion
helper. Typing `+query` wherever a tag may start opens a picker of enabled launchable
projects and active PR-sized Patches in `WIP`, `Draft`, `Ready`, or `Mailed` status. A
tag may start at the beginning of the prompt or after whitespace (including a newline or
tab), `{`, or `|`, while `a+b`, `c++`, and `#+query` are not triggers. Project rows show
`+name` in the project's accent color, with the provider and the `#<workflow>:<name>`
reference as detail. sase's TUI also marks the current project. Rows are ordered current
project first, then most recently launched, then by name, with Patch rows last.
Accepting a project row removes the `+query` token and places the project's tag (for
example `+sase `), or `#<workflow>:<name> ` when the name does not fit tag syntax, at
the earliest existing workspace target in the same `---` segment — or at that segment's
leading tag position (after frontmatter and `%directive` tokens) when the segment has no
target yet. Accepting a Patch row places a reference such as `#gh:my_change ` the same
way. Either way, the other workspace targets in the segment are removed, so the accepted
prompt keeps exactly one. The helper filters by `PROJECT_NAME`, directory-key project
name, project alias, or Patch name prefix. It omits the system-managed `home` project,
disabled projects, sibling records, non-launchable projects, and projects with no
detected VCS provider, even though `+home` and disabled-project tags still resolve when
typed.

The macro LSP also checks tags as you type. Hovering a tag shows its project. An
anchored unknown tag gets a warning with `Use +<suggestion>` quick fixes, an ambiguous
tag is an error, and a tag whose project has no detected provider gets a warning. A
`refactor.rewrite` code action turns a plain project ref such as `#gh:sase` into
`+sase`.

**Display.** sase's TUI prefers the tag spelling wherever it seeds a project prompt: the
`+` launch picker, project quick launches, the repeat-last-launch prefill, new stacked
prompt panes, `ctrl+p`/`ctrl+n` VCS MRU cycling, and artifact-reference prompts. Patch
targets keep their `#<workflow>:<patch>` form. Agent panels and the prompt editor also
show known-project refs such as `#gh:gh_sase-org__sase` as `+sase`. That display form is
used only where the rewritten text would scan as a tag again, so copied, relaunched, and
forked prompts expand the same way. Disabled projects get the tag spelling too, so
relaunching such a prompt is rejected until you run `sase project enable`, where the
original `#` ref would have re-enabled the project. Patch refs, `owner/repo` refs,
`@agent` refs, parenthesized forms, and refs with `!!`/`??` suffixes keep their `#`
spelling. Tags render as chips: a dim `+` and a bold name in the project's accent color,
the same color as the `project:` chip in each tab's launch-context cluster. Disabled
projects and `home` render neutral, and an anchored unknown tag is underlined in the
warning color. These surfaces read a cached project catalog that sase's TUI warms in the
background. Until it is warm, they briefly fall back to the `#` spelling, and launch
still validates tags.

CLI views follow the same display rules: `sase agent show`, `sase prompt list`,
`sase prompt search`, and `sase prompt show -f markdown` load the project catalog and
show known-project refs as `+<project>` tags. The first three accent-color the tags on a
color terminal; `sase prompt show -f markdown` writes them as plain text. Raw and JSON
output (`sase prompt show`, `sase prompt list --json`, and `sase prompt search -f json`)
keeps the exact stored text. `sase macro show` accent-colors tags in its highlighted
body, and `sase project list` and `sase project show` print each project's tag. The
[SASE Pager](../../pager.md#syntax-highlighting) colors resolved tags in Markdown prose with
the same accent styling when the project catalog is already loaded (in practice, inside
sase's TUI).

### Artifact References

Artifact references are prompt syntax, not macros. They use `@<kind>:<argument>` to cite
a durable document, entity, revision, or file, and SASE resolves them late in prompt
preprocessing after macro expansion. The retired `#ref/<kind>:<argument>` renderer
syntax is not accepted.

See [Artifact References](../artifact-references.md) for the grammar, live kinds,
compatibility aliases, provider specs, publication links, and allow-listed `@file`
roots.

## Related

- [Macro reference](index.md)
- [Arguments and typed inputs](arguments.md)
