# Agentic Software Engineering Series

SASE, short for **Structured Agentic Software Engineering**, uses **agentic software engineering** to mean software work
where AI agents operate inside durable engineering systems: plans, work queues, review records, tests, commits,
dependencies, and handoffs. The series explains why that coordination layer matters and how SASE implements it.

The canonical essays live on the [SASE Blog](../blog/index.md). This page is the series hub: it lists the two posts that
make up the series today and points readers at the current product guides for further reading.

## The Series

The series has two posts. Read them in numbered order for the conceptual argument first, hands-on practice second; or
flip the order if you'd rather run the system before reading about why it exists.

| Post                                                                                                                         | Status               |
| ---------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| [Post 1: Why Coding Agents Need Orchestration](../blog/posts/why-coding-agents-need-orchestration.md)                        | Published 2026-05-08 |
| [Post 2: Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents](../blog/posts/hello-sase-your-first-15-minutes.md) | Published 2026-05-10 |

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
