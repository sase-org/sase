---
description: Find new medium-to-long article recommendations with a multi-runtime research pass.
input:
  topic:
    type: text
    description: Reading request or topic to search for.
  reference_query:
    type: text
    default: |
      LIST WITHOUT ID title + " (" + url + ")"
      FROM "ref"
      WHERE
        source_path AND url AND (
          parent = [[ai_ref]]
          OR parent.parent = [[ai_ref]]
          OR parent.parent.parent = [[ai_ref]]
          OR parent.parent.parent.parent = [[ai_ref]]
          OR parent.parent.parent.parent.parent = [[ai_ref]]
        )
      SORT title
    description: Obsidian Dataview query whose title and URL rows should be excluded.
xprompts:
  _article_search_agent:
    content: |
      Can you recommend recent, medium-to-long articles that I would likely enjoy reading for this request?

      {{ topic }}

      Use the `/bob_query` skill to run this Obsidian Dataview query against my Obsidian vault before searching:

      {{ "```dataview" }}
      {{ reference_query }}
      {{ "```" }}

      Treat every Title and URL returned in the result table as off-limits, including entries marked unread. Search the
      current web only after building that exclusion set. Do not manually read the old aggregate reference notes unless
      the Dataview command fails.

      Return a ranked list of recommendations. For each item, include the title, link, publication date when available,
      publisher or author when useful, and a short relevance rationale. Prefer substantive essays, engineering writeups,
      surveys, papers with readable HTML, or long-form posts over short announcements.
---

%id:reads.{@1}.agy
%model("agy/Gemini 3.5 Flash (High)")
%g:read
#_article_search_agent

---

%id:reads.{@1}.cld
%model:claude/opus
%g:read
#_article_search_agent

---

%id:reads.{@1}.cdx
%model:codex/gpt-5.6-sol
%g:read
#_article_search_agent

---

%id:reads.{@1}.final
%wait:reads.{@1}.agy
%wait:reads.{@1}.cld
%wait:reads.{@1}.cdx
%g:read

The three article-search agents have finished. Their chat transcript paths are available here:

{% raw %}{{ wait_chats }}{% endraw %}

Read those transcripts first, then consolidate their recommendations for this request:

{{ topic }}

The reference Dataview query that was used as the exclusion source was:

{{ "```dataview" }}
{{ reference_query }}
{{ "```" }}

Deduplicate recommendations by URL and by title. Rank the final list using both consensus across the three agents and
your own judgement about fit, freshness, depth, and usefulness. It is fine to favor a strong single-agent find over a
weaker consensus item.

Return a final ranked reading list. For each item, include the title, link, publication date when available, which
agents recommended it, and a concise reason it is worth reading. Resolve duplicate uncertainty against the transcripts
and Dataview table data, rerunning `/bob_query` only if needed. Call out any near-duplicates or candidates you
exclude because they appear to already be in the reference table.
