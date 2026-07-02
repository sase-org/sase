---
create_time: 2026-07-02
updated_time: 2026-07-02
status: research
---

# Launch Audit — XPrompts, Agents Tab, and the TUI (Install / Init / Configure)

## Question

Before publishing the initial SASE launch blog post — which walks a brand-new user through
**install → initialize → configure**, then through **XPrompts**, the **Agents tab**, and the **TUI**
(`docs/blog/posts/hello-sase-your-first-15-minutes.md` and `docs/blog/posts/xprompts-in-depth.md`) —
what are the highest-value improvements to make so a reader who follows the steps literally does not
hit a broken promise?

## Method

Four parallel code audits, each verifying the blog's concrete claims against the source and against
read-only CLI runs (`sase version`, `sase doctor`, `sase core health`, `sase init -c`,
`sase agent list`, `sase xprompt expand --trace`). No `sase run` and no interactive `sase ace` were
launched. A few anchor claims were re-verified by hand for this write-up.

## The Unifying Finding

Every audited surface produced the **same failure mode**: the walkthrough tells the reader to run an
exact command, and the tool's *default* behavior contradicts the promise — usually **silently**.

| Blog step | Reader is told | What actually happens by default |
| --- | --- | --- |
| Step 2 `sase doctor` | it reports "an authentication gap" and verifies a "usable provider" | doctor never checks auth; on success the readiness row is even hidden |
| Step 3 `sase agent list` | shows the run "while thinking **or after it finishes**" | default lists only *running* agents; a finished quickstart run shows "No running agents" |
| Step 6 `#docstring` / `#three_phase` | copy the example, run the tag | the flagship `three_phase.md` example does not parse; a typo'd/unknown `#tag` is echoed to the model with **no error** |
| Step 4 ACE screenshot | matches the tabs you see | the embedded infographic shows a different, stale tab bar ("CLs" first) |

A launch reader is exactly the person who runs commands verbatim and trusts the output. The three
recommendations below are ordered by how likely a reader is to hit the problem × how much it damages
trust × how cheap the fix is. All three are mostly **doc/blog edits plus one small code change each**,
so they are realistic to land before publishing.

---

## Recommendation 1 — XPrompts: fix the flagship example and stop silent failures

**Why it's #1.** XPrompts is a headline concept with its own dedicated post, and its *marquee
copy-paste example does not run* — in **both** the blog and the reference docs. Worse, the failure is
invisible, because SASE echoes unresolved `#tags` straight to the model with no warning. A reader who
follows Step 6 and then reads the XPrompts post will copy a broken example, get no error, and quietly
send literal `#three_phase` text to their model.

### 1a. The `three_phase.md` fan-out example is malformed (doc/blog edit)

`docs/blog/posts/xprompts-in-depth.md:101-119` has **two** independent defects:

- The caption line `# xprompts/three_phase.md` sits **inside** the fenced block, so it becomes file
  content. Frontmatter is only parsed when line 1 is exactly `---` (`src/sase/xprompt/loader_parsing.py:30`),
  so the heading disables frontmatter entirely.
- `input: target: word` is **invalid YAML** (`mapping values are not allowed here`), and invalid
  frontmatter is silently dropped (`src/sase/xprompt/loader_parsing.py:50-52`), leaving `target`
  undefined.

Verified: the blog-exact file → `❌ XPrompt template error: 'target' is undefined`; a corrected file
(shortform `input:` / newline / `  target: word`, no heading) → expands to `Draft a plan for login.`

The linked reference (`docs/xprompt.md:1736-1752`) uses **valid** shortform YAML but *also* leads with
`# xprompts/three_phase.md` inside the fence, so copied verbatim it fails identically (re-verified by
hand for this write-up).

**Fix:** move the filename caption outside the code fence in both files, and use the two-line
shortform `input:` block in the blog. This is a pure text edit but it is the single most-copied
example in the XPrompts story.

### 1b. Unknown/typo'd `#tag` is silently passed through (small code change)

`sase xprompt expand '#docstirng_typo_xyz'` prints the literal token and exits 0 (re-verified). No
warning, no diagnostic — at expansion time or at launch. This is the worst first-run xprompt
experience and it *masks* 1a and 1c: the reader can't tell the difference between "worked" and "typo,
sent raw to the model."

**Fix:** when a token matches xprompt-reference syntax (`#name`) but resolves to nothing, emit a stderr
warning — at minimum in `sase xprompt expand`, ideally at every dispatch site. High trust payoff for a
small change.

### 1c. Project auto-namespacing can make `#docstring` silently fail (doc caveat)

When cwd is a *recognized* SASE project, CWD `xprompts/` entries are namespaced as
`{project}/docstring` (`src/sase/xprompt/loader_sources.py:206-210`, `loader.py:142-148`), so plain
`#docstring` no longer resolves — and per 1b it then passes through as literal text. Step 6 tells the
reader to create `xprompts/docstring.md` "in your project root" and never mentions this. It works in a
plain unregistered directory; it can silently fail in a real project.

**Fix:** one-line caveat in the blog (and it's already documented at `docs/xprompt.md:205-209`). Fixing
1b makes this self-diagnosing.

### Smaller xprompt corrections (bundle in)

- **Plugin priority off-by-one:** the blog says a plugin's commit XPrompt is "priority 8"; the
  canonical table it links puts plugin packages at **priority 7** (`docs/xprompt.md:189`).
- **`crs` is not a shipped default xprompt:** the blog lists `crs`, `fix_hook`, and the commit
  workflows as overridable defaults. Only `fix_hook.md` and `commit.yml` ship in core; `crs` is a
  `get_by_tag` hook with a Python fallback (`src/sase/xprompt/workflows/crs.py:92-93`). Reword to
  "`fix_hook` and the commit workflows," or explain crs is a tag hook.
- **`sase xprompt expand` shows only the first segment** of a multi-agent xprompt
  (`src/sase/xprompt/processor.py:189-193`), yet the blog sells `expand --trace` as *the* debugging
  tool. A reader debugging `three_phase` sees 1 of 3 segments. Consider a "N segments (showing first)"
  note or an all-segments flag.

**What's solid:** discovery order, first-match-wins, typed-input types (`word/line/text/path/int/bool/float`),
the directive set and forms (`%model/%name/%wait/%auto/%repeat/%alt`, `%name:!reviewer`,
`%wait(planner, time=5m)`, `#t` deferral), the `---` segment separator, plugin env vars, and
`--trace` to stderr all verified TRUE against code.

---

## Recommendation 2 — Install/Doctor: stop over-promising provider readiness

**Why it's #2.** This is Step 2, it is the readiness gate the whole quickstart leans on, and the
promise appears in **three** places (blog, `INSTALL.md`, `README.md`). The most common real first-run
failure — "provider CLI installed but not logged in" — sails straight through doctor, then `sase run`
fails *after* the blog told the reader the provider was verified.

### 2a. Doctor does not verify auth, but the docs say it catches "authentication gaps"

`src/sase/doctor/checks_providers.py:47-49` hard-codes
`auth: not verified (doctor is read-only and does not call provider APIs)`, and the `llm.default`
check only confirms the executable exists (`shutil.which`). Yet:

- Blog Step 2 (`hello-sase-your-first-15-minutes.md:58`): "if the provider check reports a missing
  executable or **an authentication gap**…"
- `INSTALL.md:121`: "must be installed **and authenticated**. `sase doctor` reports readiness."
- `README.md:51`: "reports a missing provider executable or **authentication gap**…"

**Fix (cheapest correct):** reword all three to "detects a missing or misconfigured provider
*executable*; it does not log you in or verify credentials." (Optional larger fix: add a bounded auth
probe to `llm.default`.)

### 2b. On success, the readiness row is hidden

When a provider *is* present, `llm.default` returns OK but is suppressed by the "first-OK-per-group"
render rule (`src/sase/diagnostics/render.py:117-134`), because `llm.registry` is the group's first
check. So a healthy user sees only a **static** `5 provider(s), 34 known model(s)` count that is
identical whether or not any CLI is installed. The blog's "Verified that SASE can find a usable
coding-agent provider" is therefore never actually visible.

**Fix:** always render `llm.default` (it's the readiness check), or fold executable-found status into
the shown `llm.registry` summary.

### 2c. A fresh no-provider machine gets a red ERROR + exit 1 with no reassurance

For a reader whose only gap is "haven't installed a provider yet," `sase doctor` exits 1 and paints an
ERROR panel among ~10 stacked tables, with **no consolidated "next action" line** (confirmed absent
from `-j` output; `src/sase/diagnostics/render.py:60-81`). A first-timer may conclude the *install*
is broken.

**Fix:** (doc) one sentence in Step 2 / `INSTALL.md`: "Until a provider CLI is on PATH, `sase doctor`
reports ERROR and exits non-zero — that's expected; install a provider and rerun." (code, optional) a
top-of-report "Next action:" line surfacing the highest-severity check's next step.

**Note on the failure path:** when a provider *is* misconfigured, the `llm.default` next-step message
is excellent — actionable install + auth commands + a rerun hint. The gap is only that the *missing-auth*
and *success* cases don't behave as the docs claim. The install spine itself
(`uv tool install` → `sase version` → `sase core health`) verified solid and matches the docs.

---

## Recommendation 3 — Agents tab: make the finished run visible where the blog points

**Why it's #3.** This is Step 3–4, the first place the reader looks for their work. The blog's read-only
"summarize this repo" task is fast and `sase run` is detached, so the run is very often **DONE** by the
time the reader types `sase agent list` — and the default view hides it.

### 3a. `sase agent list` hides finished runs (small code change or blog edit)

Default lists only running/waiting agents; done agents are skipped
(`src/sase/agent/running.py:241`, `src/sase/agents/cli_list.py:46`). The blog Step 3 promises the run
appears "while the model is thinking **or after it finishes**." Live check confirmed: default showed 5
running; `-a` added 9 DONE rows. A reader whose run finished sees:

```
╭──── Running Agents (0) ────╮
│ No running agents.         │
│ Start one with sase run <xprompt> or sase ace. │
╰────────────────────────────╯
```

…and reasonably concludes their run vanished.

**Fix:** default to including recently-completed agents (small per-project cap, like a lighter `-a`),
**or** change the blog to `sase agent list -a`. Either way, add a hint to the empty-state panel
(`cli_list.py:97-100`): "Add `-a` to include recently completed agents." (3b.)

### 3b. Empty-state never mentions `-a` (tiny code edit)

Covered above — the "No running agents" panel gives no path to the finished run. One string change.

### Bundle-in quick wins (medium value)

- **PROMPT column is dominated by directives.** Rows lead with `%name:… %model:… #gh:…` before any
  human text; the blog's own `#cd:$(pwd) summarize…` spends the 80-char budget on the absolute path
  (`cli_list.py:36`). Strip/de-prioritize leading `%…`/`#…` directives when building the snippet.
- **`sase agent show` prints no reply for completed agents** — only the prompt and (running-only) a
  live-tail hint (`src/sase/agents/cli_show.py:81-85`). The blog promises a discoverable "reply
  transcript," but the natural `list → show` drill-down can't display it for a finished run. Print the
  response (or a `sase chat`/artifacts pointer) for DONE agents.
- **Cryptic default names.** The first unnamed agent is literally named `0`
  (`src/sase/agent/names/_auto.py`), so NAME conveys nothing and the truncated, directive-heavy PROMPT
  column is the only identity. Consider a prompt-derived fallback label, or have the blog recommend
  `%name:`.
- **"Workspace path" is a number.** Both the tab header and CLI surface `#N` / `workspace_num`, never
  the `sase_<N>` path (`_agent_display_header.py:203-205`, `cli_list.py:78`). Soften the blog to
  "workspace (number)."

**What's solid:** the Agents tab's empty-state onboarding pane is a genuine strength (see TUI notes),
and the "retry chain" and (for running agents) "reply transcript" claims hold on the tab itself.

---

## Runner-up: TUI framing (fix if time allows)

Not in the top 3 only because it doesn't hard-block the linear walkthrough, but both items are cheap
and reader-visible:

- **The embedded infographic is stale (HIGH-visibility, easy fix).**
  `docs/blog/posts/hello-sase-your-first-15-minutes.md:103` embeds
  `docs/images/sase_tui_tabs_infographic.png`, whose tab bar reads **CLs | Agents | AXE** and leads
  with "CLs." The live TUI leads with **Agents** and labels the ChangeSpecs tab **"PRs"**
  (`src/sase/ace/tui/tab_order.py:16`, `widgets/tab_bar.py:19-23`); the blog prose itself says
  "Agents… PRs…." A reader comparing the picture to their screen sees a different first tab and a
  different label. **Fix:** regenerate the PNG with order **Agents | PRs | AXE** and label the teal
  tab "PRs."
- **The blog omits the SASE Admin Center.** `#` opens a six-sub-tab surface (Config, Logs, Projects,
  Tasks, Updates, XPrompts — `src/sase/ace/tui/modals/config_center_modal.py:48-65`), and `INSTALL.md`
  treats its **Updates** tab as *the* recommended plugin-install / keep-current path. A blog-only
  reader never learns `#` exists, then hits `INSTALL.md` saying "press `#` … then `5`" with no prior
  introduction. **Fix:** add one bullet to Step 4 or the component map.
- **Minor:** the onboarding pane (a real strength) only shows on an empty Agents tab, so a reader who
  launched an agent in Step 3 never sees it; the tab label renders "AXE" not "Axe"; `docs/ace.md:47-55`
  still lists tabs PRs-first. "ACE has three tabs" is otherwise **accurate** — count, labels, and
  order match code.

---

## Priority Checklist (for the pre-publish pass)

| # | Change | Type | Effort |
| --- | --- | --- | --- |
| 1a | Fix `three_phase.md` example (blog + `docs/xprompt.md`): caption outside fence, valid shortform `input:` | doc | XS |
| 1b | Warn on unresolved `#tag` in `sase xprompt expand` (ideally at launch) | code | S |
| 1c | Blog caveat: project detection namespaces CWD xprompts | doc | XS |
| 1x | Fix plugin priority (7 not 8); reword `crs` as tag hook, not shipped default | doc | XS |
| 2a | Reword doctor "authentication gap" → "missing/misconfigured executable" (blog, INSTALL, README) | doc | XS |
| 2b | Always render `llm.default` readiness row | code | S |
| 2c | Note "ERROR is expected until a provider is installed"; optional "Next action" line | doc (+code) | XS–S |
| 3a | `sase agent list` include recent-done by default **or** blog uses `-a` | code/doc | S |
| 3b | Add `-a` hint to the empty-state panel | code | XS |
| R1 | Regenerate `sase_tui_tabs_infographic.png` (Agents | PRs | AXE) | asset | S |
| R2 | Add one Admin Center (`#`) bullet to the blog | doc | XS |

## Bottom Line

The blog's conceptual model is accurate across all three concepts — the gaps are all "the default
command output contradicts the sentence the reader just read." The three highest-value fixes, in
order: **(1)** repair the broken flagship XPrompt example and make unresolved `#tags` fail loudly;
**(2)** stop `sase doctor` from promising auth verification it doesn't do; **(3)** make
`sase agent list` show the finished run the blog says it will. Each is mostly a doc edit plus one small
code change, all landable before publishing.
