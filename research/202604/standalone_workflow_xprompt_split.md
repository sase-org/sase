# Unifying xprompts: separating embeddable templates from standalone workflows

## Goal

The `#name` namespace today mixes two operationally distinct things:

1. **Embeddable prompt fragments** — anything whose final contribution is text that
   can be substituted into another prompt. Markdown xprompts and YAML workflows
   *with* a `prompt_part` step both belong here. They compose freely.
2. **Standalone workflows** — YAML workflows whose steps are bash/python/agent/parallel
   only, with no `prompt_part`. They have no inline text representation; they only make
   sense as the entry point of a run. Embedding them silently fails and they fall through
   as literal `#name` text in the host prompt.

The proposal is to give standalone workflows a different prefix (e.g. `#!name`) so
that `#` denotes "true xprompt: substitutes into surrounding text" and the new
prefix denotes "run this workflow standalone, do not try to splice it." The rest of
this note maps the current code so the proposal can be evaluated and scoped without
re-deriving the taxonomy.

## Updated recommendation

Use `#!name` for YAML workflows that do **not** define `prompt_part`, but treat
this as a workflow-reference syntax change rather than a narrow top-level CLI
special case. The important compatibility surface is not only `sase run "#sync"`;
it is also mixed wrapper prompts such as `#gh:sase #sase/fix_just`, where the VCS
workflow contributes context and the standalone workflow is extracted by the
anonymous-workflow flattener.

The safest rule is:

- `#name` means "inline text-capable xprompt/workflow reference."
- `#!name` means "standalone workflow reference; execute/flatten it, never inline
  it."
- For one compatibility window, top-level `#standalone` should still run but emit
  a deprecation warning. Embedded `#standalone` should fail loudly because the
  current literal passthrough is the source of the conceptual leak.

This keeps the mental model clean while preserving the existing `#gh:sase
#!sase/fix_just` composition pattern.

## Current taxonomy in code

Everything ultimately lands in a `Workflow` object
(`src/sase/xprompt/workflow_models.py`). A bare `.md` xprompt is converted to a
single-step workflow whose only step is a `prompt_part`; YAML files become multi-step
workflows directly. From the perspective of the rest of the system, there are three
classifications and the existing predicates already encode them:

| Classification | Predicate | Meaning |
| --- | --- | --- |
| Simple xprompt | `Workflow.is_simple_xprompt()` (`workflow_models.py:234`) | Exactly one step and it's a `prompt_part`. The pure-text case. |
| Embeddable workflow | `Workflow.has_prompt_part()` (`workflow_models.py:180`) | At least one `prompt_part` step plus pre/post sibling steps that run before/after the host agent. |
| Standalone workflow | `not has_prompt_part()` | No `prompt_part`. Has no inline text representation. |

The validator (`workflow_validator_checks.py:39-96`) enforces "at most one
`prompt_part` step per workflow" — so the predicate is also a partition.

### Where embedding splits along this line

There are three embedding/dry-expansion sites and all branch on
`has_prompt_part()`:

- `src/sase/main/query_handler/_embedded_workflows.py:99-101` (top-level
  `sase run "... #foo ..."`):
  > `# Skip workflows without prompt_part (execute as full workflow) … if not workflow.has_prompt_part(): continue`

  The reference is left in the prompt verbatim. There is no error and no log line.

- `src/sase/xprompt/workflow_executor_steps_embedded_expand.py:118-125` (embedded
  inside another workflow's agent step):
  ```
  if not workflow.has_prompt_part():
      logger.warning(
          "skipping #%s — workflow found but has no prompt_part (standalone "
          "workflow cannot be embedded). It will pass through as literal text.",
          name,
      )
      continue
  ```

- `src/sase/sdd/files.py:197-304` (`dry_expand_embedded_workflows`, used when
  writing expanded prompts into specs) leaves workflows without `prompt_part`
  unchanged. This is correct for dry expansion, but a `#!` migration should
  decide whether specs preserve the literal `#!name` invocation or replace it
  with a compact marker such as `[standalone workflow: name]`.

All three confirm the user's premise: standalone workflows cannot be embedded
today. The current behavior is "silently leak the literal `#name` token into the
prompt" — which the LLM may or may not interpret reasonably.

### Where invocation already special-cases the same split

`src/sase/main/query_handler/special_cases.py:171` chooses between two execution
paths based on the same predicate:

```
if workflow.has_prompt_part() and not workflow.is_simple_xprompt():
    _run_query(potential_query)            # multi-step embeddable: route via run_query
                                           # so pre/post steps run around the agent
else:
    execute_workflow(...)                  # standalone or simple: run the workflow directly
```

`src/sase/xprompt/workflow_runner.py:48-83` introduces a helper named
`_find_standalone_workflow_ref` whose docstring already uses the term *standalone* to
mean "workflow with no prompt_part." So the proposed terminology lines up with how the
codebase already talks internally — it just isn't surfaced to users.

That helper is more important than it first appears. It is the mechanism that
makes prompts like `#gh:sase #sase/pylimit_split` execute the
`sase/pylimit_split` workflow rather than send literal `#sase/pylimit_split` to
the model. Any `#!` design has to update:

- the fast path in `_flatten_anonymous_workflow`;
- the slow path in `_find_standalone_workflow_ref`;
- TUI standalone workflow launch in
  `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py`, which currently
  strips a leading `#`, parses the workflow reference, and refuses workflows
  that *do* have `prompt_part`;
- top-level CLI special handling in `special_cases.py`.

If only `special_cases.py` learns `#!`, the TUI and axe subprocess path will
still treat `#!name` as ordinary prompt text.

### Built-in workflows by category

Built-ins live in `src/sase/xprompts/` (plus the `prompt_part`/`xprompt` ones
declared in `default_config.yml`). Current packaged contents:

- **Embeddable workflows** (have `prompt_part`):
  `commit.yml`, `pr.yml`, `propose.yml`, `git.yml`, `json.yml`, `mentor.yml`,
  `make_mentor_changes.yml`, `file.yml`, `resume.yml`, `resume_by_chat.yml`.
- **Standalone workflows** (no `prompt_part`):
  `eval_ifs_loops.yml`, `eval_parallel.yml`, `sync.yml`.
- **Simple xprompts** (single `prompt_part` after conversion):
  every `.md` file in `xprompts/` (`coder.md`, `fix_hook.md`, `summarize.md`) plus
  the config-defined entries (`#plan`, `#epic`, `#review`, `#prompt/approve`, etc.).

The standalone group is small today, but the conceptual cleanup matters more than
the count: `sync` is user-visible (it drives a rebase/conflict-resolution agent) and
the `eval_*` ones are run via `sase xprompt explain` / test fixtures.

Project-local workflows matter more for migration than packaged built-ins. In
this repo, `xprompts/fix_just.yml`, `xprompts/pylimit_split.yml`, and
`xprompts/refresh_docs.yml` are standalone workflows. When loaded with project
context they appear as `sase/fix_just`, `sase/pylimit_split`, and
`sase/refresh_docs`. These are real automation/chop entry points, and many
historical specs/plans reference them through mixed prompts such as `#gh:sase
#sase/fix_just`. A migration should therefore include namespaced local workflows,
not only `#sync` and the `eval_*` examples.

Workflow discovery also has more sources than this repo:

- CWD `.xprompts/*.yml` and `xprompts/*.yml`, namespaced by detected project.
- Home `~/.xprompts/*.yml` and `~/xprompts/*.yml`.
- `~/.config/sase/xprompts/{project}/*.yml`, namespaced by project.
- Plugin workflow resources.
- Internal packaged workflows.

So a one-time migration script should inspect the resolved prompt catalog and use
`Workflow.has_prompt_part()` rather than relying on a hard-coded built-in list.

### The third axis: multi-agent xprompts

Orthogonal to the above — and worth keeping in mind for the prefix design — is
*multi-agent xprompts* (`src/sase/agent/multi_agent_xprompt.py`). These are
markdown xprompts whose body contains `---` segment separators. They fan out into N
agents at dispatch time, but only when referenced as the **sole** content of a
prompt segment. Mixing them with surrounding prose raises
`MultiAgentXPromptUsageError` (`multi_agent_xprompt.py:44-52`).

So embedding constraints already vary by xprompt kind:

| Kind | Inline embeddable | Sole-segment only | Pure-standalone |
| --- | --- | --- | --- |
| Simple xprompt (`.md`, single segment) | yes | n/a | n/a |
| Multi-agent xprompt (`.md`, `---` body) | **no** — usage error | yes | yes (via fan-out) |
| Embeddable workflow (`.yml` with `prompt_part`) | yes | n/a | also runnable via `execute_workflow` |
| Standalone workflow (`.yml`, no `prompt_part`) | **no** — silent passthrough | n/a | yes |

Two of the four kinds are *not* freely embeddable. Today both share the `#` prefix
with the embeddable kinds, so the failure modes only surface at runtime (a warning
log, a usage error, or — worst — a literal `#name` leaking into an LLM prompt).

## Evaluating the `#!` proposal

### What works well

- **Maps cleanly onto an existing partition.** `has_prompt_part()` is already the
  partition function. The prefix would just lift that runtime predicate into the
  surface syntax. No new concept, just a name for one we already have.
- **Catches authoring mistakes earlier.** Today, writing `#sync` inside another
  prompt produces a literal token in the LLM input; `#!sync` would let the parser
  reject the embedding at expansion time with a precise error. Mirror change: in a
  top-level `sase run "#!sync"`, allow it; in a body, raise.
- **Matches an existing user mental model in the docs.** `docs/xprompt.md`
  separates "Built-in XPrompts" (text fragments) from `Relationship to Workflows`
  ("Internally, a standalone xprompt is converted to a single-step workflow with a
  `prompt_part` step…"). The new prefix puts that boundary where users see it
  rather than where the executor sees it.
- **The shell-style `!` choice is mnemonic.** "`#!`" reads as "run this," which is
  the right mental cue.

### Friction points to design around

1. **Multi-agent xprompts are also "non-embeddable."** They share the embedding
   constraint with standalone workflows but are *not* the same thing — they're
   markdown bodies that fan out into multiple sub-agents, all of which can in turn
   contain embeddable references. Two reasonable options:

   - **(a) `#!` covers both.** Any non-embeddable kind uses `#!`. Conceptually
     cleanest — "if it isn't an inline text fragment, it gets `!`." But it bundles
     two distinct dispatch behaviors (workflow exec vs. fan-out), which may be
     surprising.
   - **(b) `#!` for standalone workflows only.** Multi-agent xprompts keep `#`
     (because they *are* xprompts — Markdown templates) but the existing
     usage-error remains the safety net. Less type-system purity, but maps
     1:1 onto the file kind (`.yml-without-prompt-part` vs. everything else).

   Recommend (b): the `#` vs. `#!` distinction tracks *file kind* (markdown xprompt
   vs. workflow YAML without `prompt_part`), and dispatch fan-out vs. single-agent
   stays a within-`#` property of a body. That keeps "what does the prefix mean?"
   easy to teach: `#` = template, `#!` = pipeline.

2. **`#!` vs. shebangs.** Some configs/tools may interpret a leading `#!` line as
   a shebang. The grammar already requires that `#name` not be at column 0 of a
   markdown heading (`docs/xprompt.md` — "Markdown headings like `# Heading` are
   not matched because a space after `#` prevents the pattern from firing"). The
   same allowed-context rule applies, so `#!sync` at the top of a file would still
   need to be at start-of-line / after whitespace / after `([{"'`. Worth confirming
   the regex (`_WORKFLOW_REF_PATTERN` in `_embedded_workflows.py:34-38`) treats `!`
   safely. The current pattern doesn't account for `!` — adding a variant pattern
   for the standalone case is straightforward.

3. **Aliases.** The built-in `xprompt_aliases` (`#c` → `#commit`, `#p` →
   `#propose`) map onto embeddable workflows. The alias mechanism (raw text
   substitution before any other processing) would need to know how to alias a
   `#!name`, or aliases should be restricted to embeddable kinds. Restricting is
   simplest and consistent: aliases produce inline-substitutable text; standalone
   pipelines are unambiguous enough by name.

   Mechanically, `resolve_xprompt_aliases()` only matches `#alias`. It could
   support standalone aliases by allowing an alias target that begins with `!`
   (`sync = !sync`, producing `#!sync`), but that would still invoke the alias as
   `#sync_alias`, not `#!sync_alias`. Prefer no standalone aliases until there is
   evidence users need them.

4. **Naming overlap with existing internal use of "standalone."** Workflow loader
   code already uses *standalone* in `_find_standalone_workflow_ref` for "workflow
   with no `prompt_part`," which is exactly the proposed user-facing meaning. A
   helpful side effect: code and docs converge on one term. No rename needed.

5. **Discoverability and `sase xprompt list`.** Today the listing already tags
   each entry as `"xprompt"` (when `is_simple_xprompt()`) or `"workflow"`
   (everything else, embeddable or not). Splitting `"workflow"` into
   `"embeddable_workflow"` vs. `"standalone_workflow"` (or surfacing the prefix in
   the displayed name) would let `xprompt list` consumers — including the TUI
   browser modals (`src/sase/ace/tui/modals/xprompt_*`) — show the right invocation
   syntax for each entry.

6. **Backward compatibility.** Existing user content with `#sync`, `#eval_parallel`
   etc. should continue to work in *standalone-invocation* contexts (`sase run
   "#sync"`) without breaking. The cheapest path is:

   - Treat `#` as embeddable-only for *expansion sites* (everywhere a prompt body
     gets expanded). If the name resolves to a standalone workflow, raise a clear
     error: `'#sync' is a standalone workflow — use '#!sync'`.
   - Leave top-level `sase run "#name"` and mixed standalone flattening
     permissive for a release, but warn and recommend `#!name`.
   - Accept `#!name` in any context that is allowed to select a standalone
     workflow: sole top-level CLI/TUI invocation, anonymous workflow flattening,
     and mixed VCS-wrapper prompts like `#gh:sase #!sase/pylimit_split`.

7. **Shell and Markdown ergonomics.** Users already have to quote `#...` in many
   shell contexts because unquoted `#` starts a comment. The docs should use
   single quotes for examples (`sase run '#!sync'`) so `!` is not subject to shell
   history expansion in shells/configurations that enable it. In Markdown,
   `#!sync` is not an ATX heading under the usual "space after `#`" rule, but
   code fences must remain protected just like they are today.

8. **HITL suffix interaction.** The existing `!!`/`??` HITL override is a suffix
   on the workflow name (`#foo!!`). `#!foo!!` is unambiguous if parsing first
   strips the standalone marker and then applies `strip_hitl_suffix()` to
   `foo!!`. This order should be tested explicitly.

### Edge: workflows that mix `prompt_part` with significant pre/post work

Embeddable workflows like `git.yml` have many non-prompt-part steps — they do real
work, they just *also* contribute text. The proposed split doesn't change their
classification (they remain `#`), but it's worth being explicit in the docs that
"embeddable" ≠ "small": it just means "produces text that can be inlined." This is
already how the executor treats them; the prefix change doesn't move that line.

### Edge: a prompt can contain both an embeddable wrapper and one standalone workflow

The existing anonymous-workflow flattening deliberately supports exactly one
standalone workflow embedded in a larger wrapper prompt. For example, the VCS
workflow can provide workspace context while the standalone workflow supplies the
actual pipeline:

```text
#gh:sase #sase/pylimit_split %approve
```

The current slow path ignores `#gh:sase` because it has `prompt_part`, finds the
single no-`prompt_part` workflow, and executes that workflow directly. This is
semantically closer to "one standalone workflow plus modifiers/context" than to
ordinary embedding. Under the new syntax, the equivalent should be:

```text
#gh:sase #!sase/pylimit_split %approve
```

This is the strongest argument for a first-class standalone reference parser. A
simple "only allow `#!` when the whole prompt starts with it" rule would break a
useful existing composition mode.

### Edge: existing regex duplication

The `#name` grammar is copied in several places:

- `processor._XPROMPT_PATTERN`;
- `_embedded_workflows._WORKFLOW_REF_PATTERN`;
- `workflow_executor_steps_embedded_types._WORKFLOW_REF_PATTERN`;
- `workflow_runner._REF_PATTERN`;
- `sdd.files.dry_expand_embedded_workflows`' local `_WORKFLOW_REF_PATTERN`;
- `multi_agent_xprompt._REFERENCE_RE`;
- `workflow_validator_extract._XPROMPT_PATTERN`.

Adding `#!` by editing one or two of these will create split-brain behavior. The
implementation should introduce a small shared parser/token model, or at minimum
shared compiled patterns, before changing behavior. That parser should return the
marker kind (`inline` vs. `standalone`), normalized name (`foo__bar` → `foo/bar`
if desired), argument span, parsed args, and match span.

## Proposed implementation shape

1. **Add a shared reference parser.** Create a helper in `sase.xprompt._parsing`
   or a new `references.py` that recognizes both `#name` and `#!name` with the
   current argument syntaxes: parens, colon args, backtick colon args, command
   substitution colon args, `+`, single-colon shorthand, and double-colon
   shorthand where currently supported.
2. **Add `Workflow.kind`.** A property or function is enough:
   `simple_xprompt`, `multi_agent_xprompt`, `embeddable_workflow`,
   `standalone_workflow`. Multi-agent kind requires checking the original
   `XPrompt` body for `---`; it cannot be derived from the converted `Workflow`
   alone unless that metadata is preserved.
3. **Teach execution sites `#!`.** Update `special_cases.py`,
   `_workflow_exec.py`, `_flatten_anonymous_workflow`, and
   `_find_standalone_workflow_ref` to accept standalone references. In the
   flattening paths, prefer explicit `#!` if present; during the compatibility
   window, continue accepting exactly one `#standalone` and warn.
4. **Teach expansion sites to reject the wrong marker.**
   - `#standalone` in an inline expansion site should raise a clear error.
   - `#!embeddable` or `#!simple` should raise: "only workflows without
     `prompt_part` use `#!`."
   - `#!standalone` inside text that is not an executable top-level/flattened
     context should raise rather than pass through to the LLM.
5. **Update discovery outputs.** `sase xprompt list`, TUI xprompt modals, and
   any catalog/browse UI should expose kind and recommended invocation prefix.
   The PDF catalog currently gathers `XPrompt` objects, not workflows, so it is
   not sufficient for this unless it is expanded to include workflows too.
6. **Migrate references.** Search docs, tests, plans/specs/examples, project-local
   automation, and external config/chops for resolved standalone workflow names.
   Use a catalog-aware migration script so namespaced entries like
   `#sase/fix_just` become `#!sase/fix_just`.
7. **Add regression tests.** Cover top-level `#!sync`, `#!sync!!`, mixed
   `#gh:sase #!sase/pylimit_split`, inline rejection of `#sync`, rejection of
   `#!commit`, SDD dry-expansion behavior, TUI `_try_execute_workflow`, and alias
   non-support/support decision.

## Suggested next steps

1. **Lock the predicate as a public concept.** Add an `XPromptKind` enum (or
   similar) on `Workflow` returning one of `simple_xprompt`,
   `embeddable_workflow`, `standalone_workflow`, `multi_agent_xprompt`. All four
   kinds already exist in code; this just names them. Use it in
   `xprompt_handler.py` for `list`/`catalog` output.
2. **Decide prefix scope.** Recommend `#!` covering only standalone workflows
   (option (b) above). Multi-agent xprompts keep `#` and rely on the existing
   sole-segment rule.
3. **Update the parser and error paths.** Avoid hand-editing each duplicated
   regex independently. In `_embedded_workflows.py`,
   `workflow_executor_steps_embedded_expand.py`, and `sdd/files.py`, when a
   `#name` resolves to a standalone workflow, raise or mark it deliberately
   instead of silently skipping.
4. **Migrate built-ins and local workflows.** Rename references in
   docs/tests/example prompts:
   `#sync` → `#!sync`, `#eval_parallel` → `#!eval_parallel`,
   `#eval_ifs_loops` → `#!eval_ifs_loops`,
   `#sase/fix_just` → `#!sase/fix_just`,
   `#sase/pylimit_split` → `#!sase/pylimit_split`, and
   `#sase/refresh_docs` → `#!sase/refresh_docs` where those names resolve in the
   current project. Keep `#`-form working with a deprecation warning for one
   release if any user content is suspected to use it.
5. **Surface the kind in TUI and `xprompt list`.** Show `#!` next to standalone
   workflow names so the user always sees the correct invocation syntax in
   browsers/modals.

## Key files referenced

- `src/sase/xprompt/workflow_models.py` — `Workflow` predicates: `has_prompt_part`,
  `is_simple_xprompt`, `appears_as_agent`, `get_pre_prompt_steps`,
  `get_post_prompt_steps`.
- `src/sase/main/query_handler/_embedded_workflows.py` — top-level embedding;
  skips standalone workflows.
- `src/sase/xprompt/workflow_executor_steps_embedded_expand.py` — workflow-step
  embedding; warns on standalone.
- `src/sase/main/query_handler/special_cases.py` — `sase run "#name"` routing;
  already branches on `has_prompt_part`.
- `src/sase/xprompt/workflow_runner.py` — `_find_standalone_workflow_ref` (uses
  *standalone* in the code-internal sense the proposal would lift to syntax).
- `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py` — TUI path that
  executes no-`prompt_part` workflows directly and refuses prompt-part workflows.
- `src/sase/sdd/files.py` — dry expansion used for spec prompt storage; currently
  leaves standalone workflow references unchanged.
- `src/sase/agent/multi_agent_xprompt.py` — multi-agent xprompts (the other
  not-freely-embeddable kind).
- `src/sase/xprompt/workflow_validator_checks.py` — enforces ≤ 1 `prompt_part`
  step, so the partition is well-defined.
- `docs/xprompt.md` — current user-facing description; would need a new section
  documenting `#!`.
