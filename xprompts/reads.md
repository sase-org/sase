---
description: Find new medium-to-long article recommendations with a multi-runtime research pass.
input:
  topic:
    type: text
    description: Reading request or topic to search for.
  reference_query:
    type: text
    default: |
      TABLE WITHOUT ID title AS Title, url AS URL
      FROM #ai/reference
      WHERE url
      SORT title ASC
    description: Obsidian Dataview query whose title and URL rows should be excluded.
xprompts:
  _article_search_agent:
    content: |
      Can you recommend recent, medium-to-long articles that I would likely enjoy reading for this request?

      {{ topic }}

      Use the `/bob_dataview` skill to run this Obsidian Dataview query against Bryan's Bob vault before searching:

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

%name:reads.gem-@
%model:gemini/gemini-3.1-pro-preview
%g:read
#_article_search_agent

---

%name:reads.cld-@
%model:claude/opus
%g:read
#_article_search_agent

---

%name:reads.cdx-@
%model:codex/gpt-5.5
%g:read
#_article_search_agent

---

%name:reads.final-@
%wait:reads.gem-@
%wait:reads.cld-@
%wait:reads.cdx-@
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
and Dataview table data, rerunning `/bob_dataview` only if needed. Call out any near-duplicates or candidates you
exclude because they appear to already be in the reference table.
