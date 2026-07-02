---
create_time: 2026-07-02
updated_time: 2026-07-02
status: research
---

# Consolidated Launch Audit: XPrompts, Agents Tab, TUI, and Setup

## Research Question

SASE's initial launch post is expected to focus on xprompts, the Agents tab, the
TUI, and what users need to do to install, initialize, and configure SASE. What
are the three highest-value improvements to consider before publishing?

## Inputs Consolidated

This file consolidates and verifies the two prior agent outputs:

- `sdd/research/202607/launch_blog_xprompts_agents_tui_audit.md`
- `sdd/research/202607/blog_launch_xprompts_agents_tui_audit.md`

Both were useful, but they emphasized different risk models. The first focused
on TUI and XPrompt Browser product polish. The second focused on command and
documentation mismatches a blog reader will hit by following the current draft
posts literally. The final ranking below gives priority to failures that are:

- likely in a first session;
- directly contradicted by the blog, README, or install guide;
- silent or confusing rather than self-explanatory;
- cheap enough to land before publication.

Verification included source reads, targeted CLI checks, and the required SASE
long-term memory reads for generated xprompt skills and TUI responsiveness.

## Bottom Line

The core model is strong: SASE has a clear install spine, a real xprompt
resolution system, a useful Agents tab, and an Admin Center with configuration,
updates, and xprompt management. The launch risk is not missing architecture.
It is that the public walkthrough currently asks a new user to run exact
commands whose default behavior can contradict the surrounding prose.

The three highest-value improvements are:

1. Make the xprompt path runnable and fail-loud.
2. Make setup readiness claims match what `sase doctor` actually verifies.
3. Make the first agent/TUI experience show the record the blog promises and
   name the Admin Center explicitly.

## 1. Make the XPrompt Path Runnable and Fail-Loud

Priority: highest. XPrompts are a headline concept, and the current flagship
example plus unresolved-tag behavior can make a new reader silently send the
wrong text to a model.

### Findings

The multi-agent `three_phase.md` example in
`docs/blog/posts/xprompts-in-depth.md:101` is broken as written:

- The filename caption `# xprompts/three_phase.md` is inside the fenced code
  block, so it becomes file content. Frontmatter parsing only happens when line
  1 is exactly `---` (`src/sase/xprompt/loader_parsing.py:30`).
- The blog's `input: target: word` form is invalid YAML, and invalid
  frontmatter is treated as absent (`src/sase/xprompt/loader_parsing.py:50`).
- A direct reproduction of the blog-style file failed with
  `XPrompt '#three_phase' template error: 'target' is undefined`.

The reference docs have the same leading-caption problem. `docs/xprompt.md:1737`
starts the copyable block with `# xprompts/three_phase.md`; its YAML shape is
valid, but the first-line caption still disables frontmatter if copied as file
content.

Unresolved xprompt references are too quiet. `sase xprompt expand
'#docstirng_typo_xyz'` prints `#docstirng_typo_xyz` and exits 0. That makes a
typo, a missing file, or a project namespacing issue look like successful
expansion.

There is also a project-local caveat: when SASE detects a project, local CWD
xprompts are namespaced as `{project}/name`
(`src/sase/xprompt/loader_sources.py:208`). The blog tells users to create
`xprompts/docstring.md` and run `#docstring`; that can work in an unregistered
directory but fail silently in a recognized project unless the user uses the
namespaced reference.

The XPrompt Browser is a related product gap. It already builds rows for config,
project, plugin, default, and workflow-backed entries and stores an insertion
string for each row (`src/sase/ace/tui/modals/xprompt_browser_catalog.py:33` and
`:59`). But `Ctrl+I` only works for non-YAML rows and no-ops for config-backed
entries or workflows (`src/sase/ace/tui/modals/xprompt_browser_pane.py:230` and
`:257`). If the blog sends readers to Admin Center -> XPrompts, this makes the
catalog feel incomplete exactly where workflows should be compelling.

### Recommended Changes

Before publishing:

- Fix both copyable `three_phase.md` examples:
  - put the filename caption outside the code fence;
  - make the file begin with `---`;
  - use the valid shortform:

```yaml
input:
  target: word
```

- Warn on unresolved `#name` references. At minimum, `sase xprompt expand`
  should emit a stderr warning when a token parses as an xprompt reference but
  resolves to nothing. Ideally launch paths should do the same.
- Add a one-line blog caveat that detected projects namespace local CWD
  xprompts, so the reference may be `#project/docstring` rather than
  `#docstring`.
- Correct two smaller doc claims in the xprompt post:
  - plugin xprompts are priority 7, not priority 8
    (`src/sase/xprompt/loader.py:134`);
  - `crs` is a tag hook point, not a core-shipped default xprompt in the same
    way as `fix_hook` or `commit.yml`.

If time allows before launch:

- Make XPrompt Browser `Ctrl+I` load or insert every visible row. For simple
  prompt-part rows, keep inline expansion. For workflows/config rows, insert
  the runnable reference such as `#!name` or `#name` instead of no-oping. Rename
  the hint to "load/insert" or "send to prompt."
- Add one browser test covering a simple xprompt and one workflow/config row.

## 2. Make Setup Readiness Match `sase doctor`

Priority: high. This is the install/init/configure gate for the whole launch
post. The current docs imply SASE verifies provider authentication, but doctor
explicitly does not.

### Findings

The current public text over-promises provider readiness:

- Blog Step 2 says doctor reports a missing executable or "an authentication
  gap" and verifies a usable coding-agent provider
  (`docs/blog/posts/hello-sase-your-first-15-minutes.md:58` and `:62`).
- `README.md:51` repeats the "authentication gap" wording.
- `INSTALL.md:121` says one provider CLI must be installed and authenticated
  and that `sase doctor` reports readiness.

The code is more conservative. `src/sase/doctor/checks_providers.py:47` defines
the detail string `auth: not verified (doctor is read-only and does not call
provider APIs)`. A targeted runtime check confirmed `llm.default` can return
OK with `"auth_verified": false` and `"auth_status": "not_verified"` when the
executable is present.

The readiness row can also be hidden in default output. Non-verbose diagnostic
rendering shows all non-OK checks, plus only the first OK check in each group
(`src/sase/diagnostics/render.py:117`). Since `llm.registry` is the first OK
check in the `llm` group, the more important `llm.default` executable-readiness
row can disappear on a healthy machine.

This makes the first-run story weaker than it needs to be:

- missing executable is diagnosed;
- provider auth is not checked;
- successful provider executable detection may not be visible;
- a no-provider machine exits non-zero without a concise "this is expected until
  you install a provider" message in the docs.

### Recommended Changes

Before publishing:

- Reword the blog, README, and install guide:
  - doctor detects missing or misconfigured provider executables;
  - doctor does not log into providers or verify credentials;
  - users still need to complete the provider's own auth flow.
- Add a short note that `sase doctor` exits non-zero until a provider executable
  is available, and that this is expected during first setup.
- Make the launch post mention both readiness commands:
  - `sase doctor` for install/config/provider executable/state checks;
  - `sase init -c` for AGENTS.md, memory, SDD, and generated skill drift.

Small code improvement:

- Always render `llm.default` in default doctor output, or fold its executable
  result into the visible `llm.registry` summary. That row is the one users
  expect after the blog says "provider readiness."

TUI setup improvement if time allows:

- Add a compact "Ready your setup" card to the empty Agents tab that points to
  `sase doctor`, `sase init -c`, and Admin Center tabs for Config, Updates, and
  XPrompts. The current empty Agents onboarding is strong, but it mainly teaches
  launching and tab orientation; it does not connect the TUI back to install,
  init, and configuration readiness.

## 3. Make the First Agent/TUI Experience Match the Blog

Priority: high. This is where a reader expects to see the durable record created
by their first `sase run`.

### Findings

The current quickstart says:

```bash
sase run "#cd:$(pwd) summarize what this repository does; do not change files"
sase agent list
```

It then says `sase agent list` gives the first visible handle for the record
"while the model is thinking or after it finishes"
(`docs/blog/posts/hello-sase-your-first-15-minutes.md:77`). That is false by
default for a fast completed run.

`sase agent list` calls `list_running_agents()` unless `--all/-a` is passed
(`src/sase/agents/cli_list.py:46`). The running-agent scan explicitly skips
records with a done marker (`src/sase/agent/running.py:241`). If the first
read-only task finishes quickly, the default empty state says only:

```text
No running agents.
Start one with sase run <xprompt> or sase ace.
```

It never mentions `-a` (`src/sase/agents/cli_list.py:94`).

The natural drill-down is also thin for completed runs. `sase agent show` prints
the prompt and a live-tail hint only for non-done agents; it does not print the
completed reply or point clearly to the saved chat transcript
(`src/sase/agents/cli_show.py:74`).

The TUI framing has two cheap visible mismatches:

- The live tab order is Agents, PRs, AXE
  (`src/sase/ace/tui/tab_order.py:16`; labels in
  `src/sase/ace/tui/widgets/tab_bar.py:19`). The embedded infographic in the
  blog is stale and shows CLs first.
- The blog says ACE has three tabs, which is true for the top-level bar, but it
  omits the SASE Admin Center. `#` opens Config, Logs, Projects, Tasks, Updates,
  and XPrompts (`src/sase/ace/tui/modals/config_center_modal.py:48`). INSTALL
  relies on Admin Center -> Updates for plugin install/update guidance, so the
  launch post should name it.

### Recommended Changes

Before publishing:

- Either change the blog command to `sase agent list -a`, or make `sase agent
  list` include a small recent-completed window by default.
- Add an empty-state hint: "Add `-a` to include recently completed agents."
- Make `sase agent show` useful for DONE agents by printing the reply, or at
  least pointing to `sase chat show` / the response transcript path.
- Regenerate `docs/images/sase_tui_tabs_infographic.png` so it shows
  Agents | PRs | AXE.
- Add one sentence or bullet in Step 4: press `#` for the SASE Admin Center,
  including Config, Updates, and XPrompts.

If there is time:

- Strip or de-prioritize leading directives in the `sase agent list` prompt
  snippet. The current 80-character prompt column can be consumed by `%...` or
  `#cd:/long/path` before showing the human request.
- Add one launch-path TUI smoke or visual test: open ACE on an empty Agents tab,
  confirm onboarding/readiness copy, open Admin Center, switch to XPrompts, and
  exercise load/insert for one simple xprompt and one workflow reference.

## Runner-Up: TUI Responsiveness Around XPrompts

This did not make the top three because the current blog-reader failures are
more direct, but it is the strongest product-polish item from the first research
note.

The XPrompt Browser loads its catalog synchronously in `__init__`
(`src/sase/ace/tui/modals/xprompt_browser_pane.py:66`). The catalog can scan
known project-local config xprompts and classify/group the full set before the
pane is composed. Post-edit commit/pull/push and `chezmoi apply` are also
synchronous subprocess work in the modal action path. The TUI performance memory
explicitly says multi-second disk/subprocess work should run off the Textual
event loop through tracked background tasks.

If the launch post includes live XPrompts-tab screenshots or videos, consider:

- loading the browser catalog in a tracked background task with a loading row;
- caching source reads by mtime where practical;
- moving post-edit git/chezmoi work into the Tasks surface;
- adding a smoke/visual guard for the exact public demo path.

## Do Not Prioritize Before This Post

- A new installer. The install spine is already coherent: `uv tool install`,
  `sase version`, `sase doctor`, provider CLI, `sase init`, and ACE/Admin Center.
- A new xprompt model. Discovery order, typed inputs, directives, plugin
  sources, and segment fan-out are largely correct.
- A broad TUI tutorial system. The existing Agents onboarding and Admin Center
  are the right surfaces; the launch issue is connecting them to the blog's
  setup path and making default commands tell the truth.

## Final Ranking

1. XPrompts: fix `three_phase`, warn on unresolved `#tags`, document project
   namespacing, and make the browser load/insert visible rows if the blog sends
   users there.
2. Setup readiness: stop promising auth verification from `sase doctor`, show
   `llm.default`, and connect `doctor`, `init -c`, Config, Updates, and
   XPrompts.
3. Agents/TUI: make finished first runs visible with `-a` or a recent-done
   default, improve the empty state and completed `show`, refresh the stale TUI
   infographic, and mention the `#` Admin Center.

