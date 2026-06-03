# Launching sase's First Blog Post(s): Strategy & Playbook

_Research date: 2026-06-03_

## Question

How should sase release its first blog post(s) to maximize the project's chance of
success? What should the first posts be about, where should they be distributed, how
should they be timed, and how do we position sase in a crowded market?

## TL;DR Recommendations

1. **Write two posts, not one.** Lead with a *narrative launch / "why we built this"*
   post, and have a *technical deep-dive* ready as the follow-up. Developers reward
   substance over announcements.
2. **Position around "durable / structured," not "parallel agents."** The
   parallel-agent-orchestration space is already crowded (Vibe Kanban, Conductor,
   Crystal, Claude Squad, Composio AO, etc.). sase's defensible angle is the *operating
   layer* — ChangeSpecs, scheduling, memory, SDD/beads, commit flow — that makes agent
   work **dependable and repeatable**, not just parallel.
3. **Make GitHub the primary destination, not a landing page.** HN/Reddit audiences
   trust a real repo + README + a <15 min "hello world" more than marketing copy.
4. **Distribute on the channels developers actually read:** Show HN, relevant
   subreddits, Lobsters, dev.to/Hashnode cross-post, and a Twitter/X thread. The blog is
   the home base; these are the amplifiers.
5. **Launch Tue–Thu, ~7–10am PT / 10am–1pm ET.** Be online and responsive for the first
   2 hours — early engagement drives algorithmic visibility everywhere.
6. **Avoid superlatives and sales language.** "fastest/best/first" and corporate-speak
   are instant turnoffs to the HN/Lobsters crowd. Modest, factual, first-person
   dev-to-dev voice wins.

---

## 1. Market context: why positioning matters most

The single biggest risk is **getting lumped in with the dozen "Kanban board for AI
agents" tools** that launched in 2025–2026. The category is well-populated:

- **Tier 2 (local multi-agent orchestration):** Conductor (Microsoft + others), Vibe
  Kanban (now sunsetting to community maintenance), Crystal/Nimbalyst, Claude Squad,
  Composio Agent Orchestrator, Gastown, Cursor Background Agents.
- **Tier 3 (cloud):** Claude Code Web, GitHub Copilot Coding Agent, Jules (Google),
  Codex Web (OpenAI).

Most of these stop at "spawn N agents in isolated worktrees + a diff/merge dashboard."
The recurring *unsolved* complaint in the space is everything **around** the run: task
alignment, durable state, conflict/merge decisions, review state, and keeping work tied
back to its origin.

**That gap is sase's story.** sase is not "another way to run agents in parallel" — it is
the **durable operating layer** that makes agent-driven engineering *repeatable*:

- **ChangeSpecs** — tracked CL/PR-sized units with lifecycle state, comments, mentors,
  metadata.
- **AXE** — a background daemon for scheduling, hooks, mentors, and workflow runs
  (nobody else in the list has real scheduling/automation).
- **XPrompt** — reusable prompt templates + typed YAML workflows, not shell history.
- **Memory** — tiered agent memory with audited reads and human-reviewed writes.
- **SDD + Beads** — spec-driven planning + git-portable issue tracking.
- **Commit finalizer + multi-runtime uniformity** — same capabilities across Claude,
  Gemini, Codex, Qwen, OpenCode.

**Recommended one-line positioning:** _"Coding agents are useful one run at a time. sase
gives agent runs a durable operating layer — isolated workspaces, reusable prompts,
scheduling, status, review state, and commit flow — so agent-driven engineering becomes
dependable instead of disposable."_

Lean into what's genuinely differentiated and **honestly name the alternatives** — HN
respects "here's what's different from X" far more than pretending competitors don't
exist.

---

## 2. What the first post(s) should be

There are two proven first-post archetypes; do **both**, in sequence.

### Post A — The launch / origin story (publish first)
A clear problem→solution narrative. Best when you have a real backstory, which sase has
(running many agents, needing them to be tracked and repeatable). Structure:

1. The problem: coding agents are powerful per-run but undependable across runs.
2. Why existing tools don't fully solve it (the orchestration-only gap above).
3. What sase does and the core mental model (ACE / AXE / ChangeSpecs / XPrompt / Memory).
4. A concrete end-to-end example: one real task from prompt → workspace → ChangeSpec →
   review → commit. Show the TUI.
5. What's still rough / limitations (builds enormous credibility on HN).
6. Invitation for feedback + link to repo & docs.

### Post B — The technical deep-dive (publish 1–2 weeks later, or hold as the HN angle)
Pick **one** opinionated, genuinely interesting subsystem and go deep. Strong candidates,
roughly in order of "HN catnip":

- **"Giving coding agents durable memory: tiered, audited, human-reviewed."** Memory is a
  hot, contested topic and sase's audited-read / reviewed-write model is distinctive.
- **"Why we built a structured operating layer instead of another agent Kanban board."**
  Opinion + architecture; directly stakes the positioning claim.
- **"Running agents as a background daemon: scheduling, hooks, and mentors (AXE)."**
  Differentiator almost no competitor has.
- **"One commit workflow across 5 agent runtimes."** The uniform-runtime design is a real
  engineering story and counters runtime lock-in fears.
- **"ChangeSpecs: treating each agent task as a tracked CL/PR-sized unit."**

> **Format guidance from the research:** Launch announcements work when "you have a story
> to tell"; technical deep-dives and opinion pieces are what actually travel on HN /
> Reddit / Lobsters. Developers reward content they can scan, reference, and revisit —
> not promotional posts. Documentation and a <15-minute "hello world" matter more than
> flashy marketing; if getting started takes longer, people bounce to a competitor.

**Asset checklist before publishing:**
- [ ] Repo README polished (it *is* your landing page for this audience).
- [ ] Quick start verified to work in <15 minutes from a clean machine.
- [ ] At least one good screenshot/GIF of the ACE TUI (posts with images perform better).
- [ ] A short demo video or asciinema (second-best to free hands-on access).
- [ ] Transparent note on license / how it's free / any future monetization plan.
- [ ] Docs (sase.sh) link-checked.

---

## 3. Distribution playbook (the blog is home base; these amplify)

Growth comes from **consistent distribution**, not a one-time drop. Be where developers
already are.

| Channel | Role | Tactical notes |
| --- | --- | --- |
| **Hacker News (Show HN)** | Highest-leverage single shot | Link to **GitHub**, not the landing page. Post a strong opening comment (see §4). Show HN "show" tab is less competitive and accrues upvotes longer. |
| **Reddit** | Targeted, durable | Post to subs correlated with the user base (e.g. r/ClaudeAI, r/programming, r/commandline, r/devtools-style communities). Follow each sub's rules; tailor the post per community. Devs increasingly Google "X reddit." |
| **Lobsters** | High-quality technical discussion | Higher signal than HN on technical topics; invite-only, so get someone to submit, or earn an invite by publishing good content. |
| **dev.to / Hashnode / Medium** | Cross-post (canonical = your blog) | Republish the deep-dive to reach engaged readers without owning the channel. Set canonical URL back to sase's blog. |
| **Twitter/X** | Thread + visuals | Code snippets, the TUI GIF, a tight thread version of the origin post. Devs lurk here more than they admit. |
| **Slack/Discord communities** | Warm distribution | Share where relevant; observe norms, ~9:1 give-to-take ratio, don't spam. |
| **Newsletters** | Echo / second wave | Pitch relevant dev newsletters; great for the "repetition" effect. |
| **YouTube / demo** | Searchable how-to | Optional; devs use it like Google for "how to do X." |

**SEO seeds for later** (the four search intents that convert for dev tools): how-to
guides ("how to run multiple Claude Code agents in parallel"), "tools for X," "X
alternatives," and head-to-head "sase vs <competitor>" comparison pages.

---

## 4. The Hacker News launch, specifically

HN can make or break first-week traction, and it has strict cultural rules.

**Title**
- Use the `Show HN:` prefix. Be crystal-clear and explicit about what it is.
- Highlight **open-source** in the title — HN heavily favors it.
- **Do not** use superlatives ("fastest," "best," "first"). Modest language is stronger.

**Opening comment (post it yourself, immediately) — 7-part structure:**
1. Who you are (brief background).
2. One clear sentence: what sase does.
3. The problem — why it's hard and why it matters.
4. Backstory — what motivated you to build it.
5. The solution with real technical detail — go deep.
6. What's different — honest contrast vs the orchestration-only tools.
7. Invite feedback — name the specific feedback you want.

**Conduct**
- Be online for the **first 2 hours** and respond to *every* comment, positive or
  negative — visible discussion drives upvotes.
- When answering critics, first agree with something (even just their intent), then
  respond technically. Treat critics as doing you a favor; you're persuading *readers*,
  not just the commenter.
- **Never** ask for upvotes and **never** plant booster comments from friends/co-founders
  — HN's ring-detection is good and it backfires.
- Make pricing/monetization transparent if relevant.

**Timing:** Tue–Thu, roughly 7–10am PT (10am–1pm ET). Earlier in the week tends to do
better; avoid Fri/weekends and Monday noise. There's no perfect time — it's a tradeoff
between eyeballs and ease of reaching the front page.

---

## 5. Sequencing: treat it as a mini launch, not a single post

A lightweight version of the "launch week" model fits a small team:

1. **Pre-set (now):** lock scope — which 1–2 posts, which subsystems, which channels.
2. **Pre-launch (~1 week out):** polish README/docs/quick start; record demo; line up the
   screenshots/GIF; draft the HN opening comment; optionally a "coming soon" teaser.
3. **Launch day:** publish Post A on the blog → Show HN → Reddit (1–2 subs) → X thread →
   relevant Discords. Stay responsive all day.
4. **Second wave (1–2 weeks later):** publish Post B (deep-dive), cross-post to
   dev.to/Lobsters, pitch a newsletter. Re-launching the same idea reaches everyone who
   missed it the first time — repetition is a feature, not a bug.
5. **Retro:** review what landed; iterate. First launches rarely peak — most of the value
   is the learning for the next one.

**Operational prep:** expect a flood of bugs, feature requests, and questions at once.
Have a feedback channel ready (GitHub Discussions/issues) so complaints land somewhere
constructive, and be ready to ship fixes fast — responsiveness in the first 24–48h reads
as "this project is alive and maintained."

---

## 6. Success metrics

Pick a few and watch them; don't over-index on a single launch spike.

- **Reach/engagement:** HN front-page time & comment count, Reddit upvotes/comments,
  blog reads, X impressions.
- **Adoption:** GitHub stars, installs, repeat usage / weekly active users, docs traffic.
- **Community:** issues/discussions opened, first external contributors.

Rough early-traction sanity checks cited in the research (treat as directional, not
gospel): ~1,000 installs and a few hundred weekly-active users by week 4, plus signs of
*usage + contributions + engagement* together, suggest you're finding fit. The honest
caveat: there's no proof launch-weeks beat spaced-out launches — success comes from
iterating across multiple launches.

---

## 7. Concrete next steps

- [ ] Decide the two post topics (recommend: origin story + memory **or**
      "why structured, not just parallel" deep-dive).
- [ ] Lock the positioning line (§1) and use it verbatim in README, HN comment, and post.
- [ ] Polish README + verify <15-min quick start on a clean machine.
- [ ] Capture ACE TUI screenshot/GIF + short demo.
- [ ] Draft the Show HN opening comment using the 7-part structure (§4).
- [ ] Identify 1–2 target subreddits + any Discords; check their self-promo rules.
- [ ] Schedule launch for a Tue–Thu morning PT; block the calendar to be responsive.

---

## Sources

- [How to launch a dev tool on Hacker News — markepear](https://www.markepear.dev/blog/dev-tool-hacker-news-launch)
- [My favorite developer marketing channels — markepear](https://www.markepear.dev/blog/developer-marketing-channels)
- [How to do launch weeks for developer tools — Evil Martians](https://evilmartians.com/chronicles/how-to-do-launch-weeks-for-developer-tools-startups-and-small-teams)
- [How to do a successful Hacker News launch — Lucas F. Costa](https://www.lucasfcosta.com/blog/hn-launch)
- [How to crush your Hacker News launch — DEV](https://dev.to/dfarrell/how-to-crush-your-hacker-news-launch-10jk)
- [Hacker News Posting Guide: Rules, Show HN, and Timing — Syften](https://syften.com/blog/hacker-news-marketing/)
- [Promote Your Open Source Project: Step-by-Step Launch Guide — daily.dev](https://business.daily.dev/resources/promote-open-source-project-step-by-step-launch-guide/)
- [Developer Go-to-Market Strategy: From Launch to Adoption — daily.dev](https://business.daily.dev/resources/developer-go-to-market-strategy-from-launch-to-adoption/)
- [3 types of new feature blog posts — Appcues](https://www.appcues.com/blog/new-feature-release-blog-posts)
- [9 Open-Source Agent Orchestrators for AI Coding (2026) — Augment Code](https://www.augmentcode.com/tools/open-source-agent-orchestrators)
- [From Conductor to Orchestrator: Practical Guide to Multi-Agent Coding in 2026 — htdocs.dev](https://htdocs.dev/posts/from-conductor-to-orchestrator-a-practical-guide-to-multi-agent-coding-in-2026/)
- [The Code Agent Orchestra — Addy Osmani](https://addyosmani.com/blog/code-agent-orchestra/)
- [Vibe Kanban — Orchestrate AI Coding Agents](https://vibekanban.com/)
- [Lobsters](https://lobste.rs/)
