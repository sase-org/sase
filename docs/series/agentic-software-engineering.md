# Agentic Software Engineering Series

SASE, short for **Structured Agentic Software Engineering**, uses **agentic software engineering** to mean software work
where AI agents operate inside durable engineering systems: plans, work queues, review records, tests, commits,
dependencies, and handoffs. The series explains why that coordination layer matters and how SASE implements it.

The canonical essays live on the [SASE Blog](../blog/index.md). This page is the series hub: it lists the eight posts
that make up the series and points readers at the current product guides for further reading.

## The Series

The series has eight posts. Posts 1 and 2 set up the _why_ and the _how_; Posts 3–7 each go deep on one subsystem; Post
8 looks forward. Read in numbered order for the full arc, or jump straight to the subsystem post you care about — each
is self-contained.

| Post                                                                                                                         | Status               |
| ---------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| [Post 1: Why Coding Agents Need Orchestration](../blog/posts/why-coding-agents-need-orchestration.md)                        | Published 2026-05-08 |
| [Post 2: Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents](../blog/posts/hello-sase-your-first-15-minutes.md) | Published 2026-05-10 |
| [Post 3: XPrompts in Depth — From One File to Full Workflows](../blog/posts/xprompts-in-depth.md)                            | Published 2026-05-12 |
| [Post 4: AXE — The Background Daemon That Keeps Agent Work Moving](../blog/posts/axe-background-daemon.md)                   | Published 2026-05-14 |
| [Post 5: Beads and SDD — Planning Multi-Agent Work That Actually Lands](../blog/posts/beads-and-sdd.md)                      | Published 2026-05-16 |
| [Post 6: Commit Workflows — The Pluggable Path From Diff to PR](../blog/posts/commit-workflows-plugins.md)                   | Published 2026-05-18 |
| [Post 7: ChangeSpecs in Practice — Review State Outside the Chat](../blog/posts/changespecs-in-practice.md)                  | Published 2026-05-20 |
| [Post 8: What's Next — Shared Memory, Mobile, and the Web Surface](../blog/posts/whats-next-memory-mobile-web.md)            | Published 2026-05-22 |

## Reader Paths

After the two posts, the current product guides make each concept concrete:

- [ACE TUI](../ace.md) for the interactive control surface.
- [Spec-Driven Development](../sdd.md) for plans, epics, legends, and executable phase work.
- [ChangeSpecs](../change_spec.md) for reviewable CL/PR-sized work records.
- [Beads](../beads.md) for issue-like work items, dependency ordering, and multi-agent epic execution.
- [XPrompts](../xprompt.md) for reusable prompt templates and workflow packaging.
- [GitHub](https://github.com/sase-org/sase) for source, issues, and implementation details.

## Publishing Notes

The blog is the canonical publishing surface for SASE essays. Series posts keep stable slugs, include frontmatter dates
and categories, and link back here so readers can move between the series hub and the individual posts without relying
on archive pages alone.
