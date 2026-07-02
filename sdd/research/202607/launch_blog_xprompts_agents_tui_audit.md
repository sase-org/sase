# Launch Blog Audit: XPrompts, Agents Tab, And TUI Onboarding

Date: 2026-07-02

## Question

What are the three highest-value product improvements to consider before publishing an initial SASE blog post focused on
xprompts, the Agents tab, the TUI, and the install/init/configure path?

## Bottom Line

The broad install and command-line readiness story is no longer the main launch risk. The current README opens with
`uv tool install sase`, `sase version`, `sase doctor`, one authenticated provider CLI, an explicit `#cd:$(pwd)` first
run, and the 15-minute quickstart link (`README.md:18-55`). `INSTALL.md` also makes `uv tool install` canonical, routes
plugin installation through the Admin Center Updates tab, and treats `sase doctor` as the machine-specific authority for
runtime tools (`INSTALL.md:3-20`, `INSTALL.md:42-59`, `INSTALL.md:111-122`). The PyPI smoke harness covers version,
Rust-core import, `sase doctor`, config dump, `sase xprompt list`, and a scratch bead flow (`smoke/pypi/README.md:22-31`;
`smoke/pypi/smoke_check.sh:323-339`).

The remaining risk is the live TUI path readers will see after the post. The strongest pre-post improvements are:

1. Make the XPrompts tab able to load or insert every visible catalog row, including config-backed xprompts and YAML
   workflows.
2. Turn the empty Agents tab into a first-run readiness hub that explicitly connects `doctor`, `init`, Config, Updates,
   and XPrompts.
3. Harden the TUI demo path by moving XPrompt Browser catalog/git work off the event loop and adding a focused visual or
   terminal smoke for the exact blog path.

## Context Audited

- CLI and docs for install/init/config: root help, `sase init`, `sase doctor`, README, `INSTALL.md`, `docs/init.md`, and
  `docs/configuration.md`.
- XPrompt loading and authoring: `docs/xprompt.md`, the xprompt loader, XPrompt Browser catalog/list/preview/action
  modules, inline-expansion helper, and browser tests.
- Agents/TUI: Agents onboarding widget, visibility predicates, dynamic launch/plugin probes, onboarding tests, and ACE
  XPrompt Browser docs.
- Existing launch research: June install/readiness, blog-launch, new-user onboarding, and TUI/xprompt freeze research.
- Long-term SASE memory, read through `sase memory read` as required:
  `generated_skills.md` for skill/xprompt generation constraints and `tui_perf.md` for event-loop responsiveness rules.

## 1. Make XPrompt Browser Load Every Visible Row

Priority: P0 before an xprompt-centered post.

Current state:

- The xprompt reference model is strong. Docs explain inline fragments as `#name`, standalone workflows as `#!name`, and
  the launch-vs-expansion split (`docs/xprompt.md:1-28`). Discovery order covers CWD, home, project-specific, config,
  plugin, default, and internal sources (`docs/xprompt.md:176-209`), and reference syntax is well documented
  (`docs/xprompt.md:250-280`).
- The loader and browser already collect a rich catalog. `get_all_xprompts()` merges internal, defaults, plugins, config,
  project-specific, and file-based prompts (`src/sase/xprompt/loader.py:98-150`); the browser adds project-local
  `sase.yml` xprompts from known projects because ACE disables normal project-local config loading
  (`src/sase/ace/tui/modals/xprompt_browser_catalog.py:26-41`).
- Every browser row already has an insertion string (`src/sase/ace/tui/modals/xprompt_browser_catalog.py:43-60`), and
  the preview shows it (`src/sase/ace/tui/modals/xprompt_browser_preview.py:70-85`).
- The useful action is artificially narrower than the catalog. `Ctrl+I` is bound to `load_xprompt`
  (`src/sase/ace/tui/modals/xprompt_browser_pane.py:52-64`), but `_highlighted_loadable_item()` rejects any
  YAML-backed source, including config-backed simple xprompts and workflow files
  (`src/sase/ace/tui/modals/xprompt_browser_pane.py:230-240`). The action returns without feedback for those rows
  (`src/sase/ace/tui/modals/xprompt_browser_pane.py:246-259`).
- The tests lock in that no-op: config-backed rows hide the hint and keep the modal open on `Ctrl+I`
  (`tests/ace/tui/test_xprompt_browser_load_keymap.py:1-8`, `tests/ace/tui/test_xprompt_browser_load_keymap.py:131-147`).
  The ACE docs, however, summarize the key as "Load the highlighted xprompt into the home prompt bar"
  (`docs/ace.md:1118-1131`).

Why this matters for the blog:

The post will likely show xprompts as reusable prompts plus workflows. A reader opening `#` -> XPrompts will see rows
whose preview says "Insertion: #!sync" or similar, but the obvious load key may disappear or do nothing for exactly the
workflow/config examples that make xprompts interesting. That makes the browser feel like a catalog rather than a launch
surface.

Recommended change:

- Replace the source-path based loadability rule with workflow-semantics behavior:
  - If `expand_inline_xprompt()` succeeds, keep the current high-value inline expansion into the prompt bar.
  - If inline expansion is not valid because the row is a workflow or has side effects, load `item.insertion` into the
    home prompt bar instead of no-oping.
  - If expansion fails for a true error, show a recoverable notification and offer insertion of the reference.
- Rename the user-facing hint from `^i: load` to something like `^i: load/insert` or `^i: send to prompt`, and show it
  for every selectable row.
- Update `docs/ace.md` to say simple prompt-part rows may expand to editable text, while workflows/config rows load the
  runnable reference.
- Update `test_xprompt_browser_load_keymap.py` so config-backed simple xprompts and standalone workflows both open the
  prompt bar. Keep one negative test for actual expansion errors.

Expected payoff:

This turns the XPrompts tab into a complete demo path: browse, preview, and immediately run or edit the selected
reference. It also removes a docs/code mismatch without changing xprompt resolution semantics.

## 2. Add First-Run Readiness And Configuration To The Empty Agents Tab

Priority: P0 before an Agents-tab/TUI-centered post.

Current state:

- The command-line onboarding pieces are good and visible: root help lists `doctor`, `init`, `version`, `ace`, `run`, and
  `agent`, with examples for `sase doctor`, `sase init -c`, explicit `#cd:$(pwd)`, `sase ace`, and `sase agent list`
  (`src/sase/main/parser.py:64-119`).
- `sase init` is a coordinator for memory, SDD, and skills (`src/sase/main/parser_init.py:48-73`), and its docs explain
  check/apply behavior, non-interactive `--yes`, and the memory/SDD/skills order (`docs/init.md:3-19`,
  `docs/init.md:52-88`).
- `sase doctor` is a bounded read-only support/readiness command with JSON, verbose, deep, strict, and targeted checks
  (`src/sase/main/parser_doctor.py:20-80`).
- The Admin Center Config tab is a strong interactive configuration surface: it shows provenance, edit targets,
  validation, diff preview, and source-preserving writes (`docs/configuration.md:54-85`).
- The Agents empty state appears only after the first agent load, when there is no active search and no visible agents
  (`src/sase/ace/tui/actions/agents/_display_detail.py:130-136`). It already uses off-thread probes for launch targets
  and plugin presence (`src/sase/ace/tui/actions/agents/_display_detail.py:167-268`).
- The current empty-state content is mostly "start from prompt", tab orientation, optional plugin recommendation, help,
  and docs link (`src/sase/ace/tui/widgets/agent_onboarding.py:66-109`,
  `src/sase/ace/tui/widgets/agent_onboarding.py:221-306`). Tests verify visibility, dynamic launch-target copy, and the
  plugin card (`tests/ace/tui/test_agents_onboarding.py:162-330`).

Gap:

The empty Agents tab is the first in-app moment for a cold reader, but it does not mention the readiness/configuration
commands the launch funnel depends on: `sase doctor`, `sase init -c`, `sase init --yes`, provider readiness, Config tab,
Models/provider settings, or the XPrompts tab. A user who opens `sase ace` early can be told how to start an agent, but
not how to verify that SASE is installed, initialized, and configured enough for that action to succeed.

Recommended change:

- Add a small "Ready your setup" card before "Start from the prompt" when the Agents tab is empty. Keep it static for the
  first pass:
  - `sase doctor` checks install/config/provider/state.
  - `sase init -c` checks generated AGENTS.md, memory, SDD, and skills drift.
  - `#` opens Admin Center; Config edits settings, Updates installs plugins, XPrompts manages prompts.
- If you want one dynamic signal, reuse the existing off-thread onboarding refresh pattern and start with low-risk
  probes only:
  - whether any provider executable is configured/detected through existing doctor/provider helpers;
  - whether init check has drift;
  - whether plugins are absent, which the onboarding already probes.
- Keep the copy command-first and terse. Avoid turning the empty state into docs. The goal is to make the first TUI
  screen route users to the same readiness path as README and INSTALL.
- Add tests next to `test_agents_onboarding.py` asserting the new card appears, step numbering remains stable, and the
  existing plugin/launch-target visibility still works.

Expected payoff:

This closes the loop between the blog's install/init/configure section and the TUI. The Agents tab becomes a useful
first-run state instead of just an empty-state guide for launching agents.

## 3. Harden The TUI Demo Path Before Sending Readers Into It

Priority: P1 before publication if there is time; P0 if the blog will include live TUI screenshots/video or ask users to
open the XPrompts tab immediately.

Current state:

- The CLI release smoke is strong but provider-independent and mostly non-TUI. It checks `sase doctor`, config dump,
  `sase xprompt list`, and beads in a scratch repo (`smoke/pypi/README.md:22-31`;
  `smoke/pypi/smoke_check.sh:327-339`).
- The XPrompt Browser loads all rows synchronously in `__init__` (`src/sase/ace/tui/modals/xprompt_browser_pane.py:66-80`).
  That path can read all known project-local `sase.yml` xprompts (`src/sase/xprompt/loader.py:80-95`) and classify/group
  the full catalog before the pane is composed.
- XPrompt editing correctly suspends the TUI while `$EDITOR` owns the terminal
  (`src/sase/ace/tui/modals/xprompt_browser_actions.py:48-55`,
  `src/sase/ace/tui/modals/xprompt_browser_actions.py:116-124`), but the optional commit/pull/push/chezmoi-apply flow
  runs synchronous subprocesses inside the confirm callback (`src/sase/ace/tui/modals/xprompt_browser_actions.py:196-272`).
- The SASE TUI performance memory says multi-second work should be off the Textual event loop, use tracked background
  tasks, and cache disk reads by mtime where practical. That is directly relevant to catalog loading and git/chezmoi work.

Recommended change:

- Move XPrompt Browser catalog loading to a tracked background task with a loading row, error row, and last-refreshed
  state. Keep the current grouping/filtering behavior once the data arrives.
- Cache catalog source reads by mtime where the existing xprompt loader structure makes that cheap, especially for
  known-project local config scans.
- Move post-edit commit/pull/push and `chezmoi apply` into the same tracked-task pattern used by the Updates tab, and
  surface status in the Tasks tab instead of blocking the modal callback.
- Add one launch-path TUI smoke or visual test that opens ACE on an empty Agents tab, verifies the onboarding/readiness
  copy, opens Admin Center, switches to XPrompts, and exercises `Ctrl+I` on at least one simple xprompt and one workflow
  reference. This does not need provider auth or a real agent run.

Expected payoff:

The blog can confidently send users into `sase ace` and `#` -> XPrompts without relying on the current machine's catalog
size, project count, git remote latency, or chezmoi state. It also gives you a repeatable screenshot/demo guardrail for
the public TUI path, complementing the existing CLI PyPI smoke.

## What Not To Prioritize For This Post

- A new install flow. The current README, INSTALL guide, root help, `doctor`, and PyPI smoke already cover the main
  install/readiness problems that June research flagged.
- A new xprompt reference model. The docs and loader behavior are mature; the issue is the TUI action affordance for
  already-discovered rows.
- A broad TUI tutorial engine. The empty Agents state and Admin Center are already the right surfaces. A readiness card
  plus a complete XPrompts load action should be enough for the first post.
- Reworking generated skills. The xprompt-skill workflow is documented and governed by generated-skill memory; no
  launch-blocking gap showed up for this post's topic.

