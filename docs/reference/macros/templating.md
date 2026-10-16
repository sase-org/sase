---
title: Macro template rendering
description: Template context, placeholders, protected content, aliases, and expansion.
---

# Macro template rendering

This page documents template rendering, placeholders, protected regions, and expansion.

## Jinja2 Integration

When the template body contains Jinja2 markers (`{{ }}`, `{% %}`, or `{# #}`), it is
rendered as a Jinja2 template. Arguments (both positional and named) are available in
the template context.

```markdown
---
input: { user: word, verbose: { type: bool, default: false } }
---

Hello, {{ user }}.

{% if verbose %} Here is the detailed explanation... {% endif %}
```

### Template Context

| Variable                                | Description                                                                                                |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `{{ name }}`                            | Named argument or input mapped by name                                                                     |
| `{{ _1 }}`                              | First positional argument (1-indexed)                                                                      |
| `{{ _2 }}`                              | Second positional argument, etc.                                                                           |
| `{{ _args }}`                           | List of all positional arguments                                                                           |
| `{{ root }}`                            | Absolute path to the primary workspace directory (omitted if unresolvable)                                 |
| `{{ wait.chats }}`                      | List of chat-transcript paths for agents named in `%wait:<name>` directives, in the order they appear      |
| `{{ wait.artifacts }}`                  | Lazy list of non-chat artifact metadata dictionaries produced by those waited agents; no file contents     |
| `{{ agents["build"].path }}`            | Output variables loaded from `%wait:build` when that agent used `sase var set path=...`                    |
| `{{ agents["p--plan"].plan_file }}`     | Proposed plan path of a submitted planner row, synthesized from `%wait:p--plan` (no `sase var set` needed) |
| `{{ agents["planner"].created_epic }}`  | First epic a waited target launched, synthesized from `%wait:planner` (no `sase var set` needed)           |
| `{{ agents["planner"].created_epics }}` | Every epic a waited target launched, synthesized from `%wait:planner` (no `sase var set` needed)           |
| `{{ patch_name }}`                      | Name of the patch the agent run works on                                                                   |
| `{{ workspace_num }}`                   | 1-based number of the workspace directory assigned to the agent run                                        |
| `{{ n }}` / `{{ N }}`                   | Current [%repeat](directive-composition.md#repeat-directive) iteration (1-based) and total iteration count                         |
| `{{ provider_name }}`                   | Name of the LLM provider rendering a skill file (skill frontmatter only)                                   |
| `{{ provider_tool_name }}`              | Display name of the provider tool rendering a skill file (skill frontmatter only)                          |
| `{{ provider_native_ask_tool }}`        | Name of the provider's native ask-user-question tool (skill frontmatter only)                              |
| `{{ range(...) }}`                      | Jinja globals: `range`, `dict`, `lipsum`, `cycler`, `joiner`, `namespace`                                  |

Accepted template aliases are listed in
[Macro migration notes](../upgrading/macros.md#template-and-input-aliases).

Named arguments and positional-to-name mappings take priority; if a macro is called
within a workflow step, the workflow's execution scope is also available (macro args
override scope values on conflict).

The `wait` namespace is only populated while an agent run is rendering its executable
prompt. `wait.artifacts` is evaluated on first access and returns plain dictionaries
with metadata such as `wait_name`, `agent_name`, `ref`, `kind`, `label`, `path`,
`source_path`, and nullable VCS provenance fields. Read artifact contents explicitly
with `sase artifact read <ref> "<reason>"` when the prompt needs bytes.

A macro that needs runtime-only names such as `wait.artifacts` defers them with
`{% raw %}...{% endraw %}`, and the deferred template renders in the launch-time
top-level pass, where fenced and inline code are literal. A `{{ ... }}` inside backticks
there is never substituted, while an enclosing `{% for %}` still repeats the literal
once per item, so deferred expressions must stay outside code spans. Rendered values
still go through literal-preserving prompt formatting, so `__` and `*` in paths survive.

Availability: conditional names render only when their precondition holds — `n`/`N` need
[%repeat](directive-composition.md#repeat-directive), `agents`/`wait_chats` need `%wait`, and the `provider_*`
names need truthy `skill` frontmatter in macro scope. A prompt that declares its own
`input:` frontmatter renders before any agent run exists, so the run-time names above
(`wait`, `patch_name`, `workspace_num`, `cl_name`, `n`, `N`, `agents`, `wait_chats`) are
unavailable there. Typing `{{` in the prompt input or an editor with the macro LSP
offers exactly the names that render in the current scope; see
[Editor LSP](cli-and-editor.md#editor-lsp).

### Filters

| Filter                              | Description                                                                                                          |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `{{ plan_file \| plan_ref_path }}`  | Returns the `YYYYmm/<name>.md` portion of a plan path or `plan:` reference; passes non-plan values through unchanged |
| `{{ "grok" \| provider_disabled }}` | `true` when the named LLM provider has an active machine-wide disable; `false` otherwise                             |
| `{{ "grok" \| provider_enabled }}`  | `true` when the named LLM provider has no active machine-wide disable; `false` otherwise                             |

Both provider filters accept an optional mode argument — `"any"` (the default),
`"hard"`, or `"soft"` — so `{{ "grok" \| provider_disabled("soft") }}` is `true` only
for an active soft disable. A non-string, blank, or unknown provider name returns
not-disabled rather than raising, so a templating slip cannot claim a provider is down;
a corrupt disable-state file likewise fails open. An unknown mode raises `ValueError` so
the typo fails loudly at render time.

The positive form exists for
[static conditional segments](directive-syntax.md#static-conditional-segments), where the condition must
read as a single `should_run=` value:

```text
Always launch this segment.
---
%if(should_run={{ "grok" | provider_enabled }})
This segment is dropped whole whenever grok is disabled.
```

## Raw Prompt Placeholders

sase's TUI recognizes valid single-line `<label>` tags as raw placeholders. A label must
be nonempty, contain no leading or trailing whitespace, and be at most 100 characters.
Raw placeholders are highlighted in prompt panes, the prompt-stash, trash, and
pinned-stash previews, and the agent panel's raw-prompt header. They participate in
placeholder completion and feed the saved common-placeholder history described in
[sase's TUI completion](../tui/prompt-completion.md#completion). Repeated tags with the same exact,
case-sensitive inner text are one logical placeholder. Tags inside inline code, fenced
code blocks, or `%macros_enabled:false` regions stay literal and are excluded from
highlighting, completion history, launch-time collection, and conversion.

Classification is syntactic rather than HTML-aware: `<div>`, `</div>`, and an
angle-bracket link destination outside a code zone are placeholders too, and a preceding
backslash does not escape them. Keep literal angle-bracket markup in an inline or fenced
code zone, place it in a disabled macro region, or use the launch panel's keep-literal
control.

By default, submitting a prompt from sase's TUI opens **Fill in this prompt** whenever
the prompt body contains a live raw placeholder. The panel shows raw placeholders first
and then any frontmatter-declared inputs, so both kinds are resolved before the agents
launch. Enter one value per distinct label to replace every matching occurrence across
all segments, or press `Ctrl+L` on a placeholder field to keep that tag literal. YAML
frontmatter itself is not scanned. Set
`ace.prompt_inputs.collect_raw_placeholders: false` to skip only raw-placeholder
collection and launch the tags unchanged; declared
[`input:`](multi-agent-prompts.md#frontmatter-declared-inputs) values are still collected. Non-interactive
`sase run` does not collect raw placeholders.

When an sase's TUI draft is saved through the whole-stack macro flow (`gX` or `Ctrl+G X`
in macro mode), live raw placeholders are converted before the save preview into
required `text` inputs:

```text
Deploy <service> to <target file>
```

becomes:

```markdown
---
input:
  service: text
  target_file: text
---

Deploy {{ service }} to {{ target_file }}
```

The `gL` active-pane conversion applies the same rewrite when it creates a
frontmatter-local macro. A fresh `gx` mini-macro extraction applies it to the copied
origin-pane body before the mini pane opens and seeds the mini definition's inferred
inputs. Raw placeholders typed later in the mini pane are saved as edited; the mini save
review does not run another conversion pass. Generated names are Jinja-safe slugs
allocated in document order; collisions receive `_2`, `_3`, and so on. During macro
saves, a generated name that matches an authored input is reused instead of redeclared,
preserving its type, default, and description. All conversion paths reuse a matching
undeclared Jinja variable. Repeated occurrences are substituted together, tags in
literal zones remain untouched, and inserted values are not scanned again for more
placeholders. Saving the same draft as a snippet keeps the original active-pane body
rather than applying this macro-only conversion. Writing an already bound macro with
`gw` saves the body as edited and does not perform a new conversion pass.

Set `ace.prompt_inputs.macro_placeholder_args: false` to keep live raw placeholders
literal during `gX`, `gL`, and fresh `gx` extraction and mint no placeholder-derived
`text` inputs. Undeclared Jinja variables still become required `gL` inputs.

## Command Substitution

Macro arguments support shell command substitution using `$(cmd)` syntax. The command is
executed via the shell and its output replaces the `$(cmd)` expression.

```
#bug:$(branch_bug)           # Use output of branch_bug command as the argument
#review:$(git diff HEAD~1)   # Pass git diff output as argument
```

Nested parentheses are supported: `$(echo $(date))`. To include a literal `$(`, escape
it as `\$(`.

Failed commands or commands producing empty output result in an empty string
replacement. Command outputs are cached within a single expansion pass to avoid
redundant execution.

## Protected Content

### Fenced Code Blocks

Content inside triple-backtick fenced code blocks is automatically protected from macro
expansion:

````
Here's an example:

```
#foo will NOT be expanded inside this code block
```

But #foo HERE will be expanded normally.
````

This prevents accidental expansion of `#name` patterns in code examples, documentation,
and similar content. The `%if::` and `%proc::` forms are the exception: the immediately
following `bash` or `python` fence belongs to that directive, so its content is captured
as opaque structured code and the directive plus fence are stripped from the model
prompt. See [Typed launch units](directive-syntax.md#typed-launch-units).

### Disabled Regions

You can explicitly disable macro expansion for a region of text using the
`%macros_enabled` directive:

```
%macros_enabled:false
This content is passed through verbatim.
#foo will NOT be expanded here.
%macros_enabled:true
Normal expansion resumes here.
#foo WILL be expanded.
```

The markers are stripped from the final output. This is useful for embedding raw macro
syntax in documentation or for passing literal `#name` patterns to downstream consumers.

The closing `%macros_enabled:true` marker may appear either on its own line or
**inline** at the end of a content line. In both forms the marker (and any whitespace
immediately preceding an inline marker) is stripped from the final output, so prompts
authored as natural prose can re-enable expansion mid-line:

```
%macros_enabled:false
... raw content where #foo and @bar are passed through verbatim. %macros_enabled:true
And expansion resumes here.
```

## Macro Aliases

Macro aliases provide raw text-level substitution that runs _before_ any other macro
processing. They are defined in the `macro_aliases` config field in `sase.yml`.

These are global shorthand aliases for macro names and raw refs. They are separate from
ProjectSpec `PROJECT_NAME` and `PROJECT_ALIASES`, which map friendly project refs such
as `bob` to canonical directory-key projects such as `gh_bbugyi200__bob` at the launch
boundary. Project names and aliases are canonicalized before macro expansion so launch
artifacts and history store the canonical directory-key project name.

The built-in defaults provide two shorthand aliases:

| Alias | Target    | Usage             |
| ----- | --------- | ----------------- |
| `c`   | `commit`  | `#c` → `#commit`  |
| `p`   | `propose` | `#p` → `#propose` |

Additional aliases can be added in user config files:

```yaml
macro_aliases:
  deploy_notes: "release-notes" # #deploy_notes → #release-notes
  gh_foo: "gh:foo/bar" # #gh_foo  → #gh:foo/bar
```

When the processor encounters `#alias_name` in a prompt, it replaces the alias name
portion with the target string before any macro resolution occurs. This is particularly
useful when the target contains characters (like `:`) that must be present in the raw
text for other processing logic — such as VCS directory-switching — to work correctly.

See
[Configuration Reference: macro_aliases](../config/prompts-and-tools.md#macroaliases)
for the full field specification.

## Recursive Expansion

Macro bodies can reference other macros. Expansion is iterative: after each round of
substitution, the result is scanned again for new `#name` references. This continues
until no known references remain, up to a maximum of 100 iterations (to guard against
circular references).

## Related

- [Macro reference](index.md)
- [Arguments and typed inputs](arguments.md)
