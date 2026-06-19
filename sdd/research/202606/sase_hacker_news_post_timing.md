---
create_time: 2026-06-19
updated_time: 2026-06-19
status: research
---

# SASE Hacker News Post Timing Research

## Question

Bryan plans to publish a blog post to Hacker News to announce and market SASE for the first time. Is there a particular
day or time that should be preferred, assuming the post is done by Sunday, June 21, 2026?

## Executive Recommendation

Post on Wednesday, June 24, 2026 at 11:00 AM Eastern Time.

That is 8:00 AM Pacific and 15:00 UTC. It is the best practical tradeoff I found: it falls inside the current
weekday-morning HN guidance, it was the strongest recent weekday/hour bucket in raw number of stories reaching at least
50 points, and it lets Bryan monitor and reply during the first several hours of discussion.

If that slot is not practical, the best fallback is Tuesday, June 23, 2026 at 11:00 AM Eastern. The next fallback is
Thursday, June 25, 2026 between 9:00 AM and 11:00 AM Eastern.

## Assumptions

- The first public SASE post is a regular HN link submission to the canonical essay, not `Show HN`.
- The objective is not merely the highest statistical chance of getting any points. It is a first public technical
  launch: enough relevant readers, enough discussion, and enough author availability to answer objections.
- Bryan can be online for at least the first 2-4 hours after posting.
- The post and linked try-it path are ready by Sunday, June 21, but there is no need to submit immediately on Sunday.

## HN Constraints That Matter More Than Timing

HN's own rules are the hard constraints:

- The post should be intellectually interesting to technical readers, not just promotional.
- Submit the original canonical URL and use a plain, non-editorialized title.
- Do not solicit upvotes, comments, submissions, or booster replies.
- Do not delete and repost if the first submission disappoints.
- Do not post generated or AI-edited comments.
- Blog posts and other reading material are not `Show HN`; those should be regular submissions.

The HN FAQ also warns against overfitting to points alone: story rank is affected by points and age, but also by flags,
anti-abuse systems, overheated-discussion demotion, account or site weighting, and moderator action.

Timing can help, but it cannot rescue a post that reads like launch copy or arrives when Bryan cannot participate.

## Source Synthesis

The useful public advice falls into two camps.

One camp optimizes for lower competition. Chanind's 2019 BigQuery analysis defined likely front-page posts as stories
with more than 50 points and found that low-activity weekend windows could have a higher chance of crossing that
threshold. The caveat in that same analysis matters for SASE: weekend front-page posts may get less absolute attention.

The other camp optimizes for practical launch reach. Syften's 2026 HN posting guide says there is no magic hour, but a
reasonable default is to post when the US technical audience is awake and the author can reply. Its practical default is
9:00 AM to 12:00 PM Eastern on a weekday.

For a first SASE announcement, the second framing is better. The launch needs serious agent-tool users, skeptical
technical feedback, and live author participation. A quiet Sunday can improve the ratio, but a weekday morning gives a
better reader pool.

## Fresh Data Check

I also pulled a fresh timing sample from the public HN Algolia `search_by_date` index.

Method:

- Source: `https://hn.algolia.com/api/v1/search_by_date`
- Filter: `tags=story`
- Date range: 2025-12-12 00:00 UTC through 2026-06-12 00:00 UTC
- Reason for ending on June 12: leaves one week for scores to mature before this June 19 analysis
- Fetch shape: 12-hour windows with `hitsPerPage=1000`
- Result: 184,131 unique story records, with no truncated windows
- Timezone used below: America/New_York
- Success proxy: story currently has at least 50 points

Limitations:

- `>=50 points` is only a proxy for meaningful HN traction, not a guaranteed front-page marker.
- This does not control for title quality, author reputation, topic, domain, flags, or moderator action.
- Scores are current as of the data pull, so very old and newer stories have different post-submission lifetimes. The
  one-week cutoff reduces but does not eliminate that issue.
- HN Algolia is a search index, not the ranking algorithm itself.

### Day-Level Results

Weekend stories had the highest percentage success rate, but weekday stories produced more total successful posts.

| Day, ET | Stories | Stories >=50 points | Rate |
| --- | ---: | ---: | ---: |
| Monday | 28,613 | 1,816 | 6.35% |
| Tuesday | 30,972 | 1,846 | 5.96% |
| Wednesday | 29,548 | 1,846 | 6.25% |
| Thursday | 29,302 | 1,784 | 6.09% |
| Friday | 26,211 | 1,726 | 6.59% |
| Saturday | 19,452 | 1,416 | 7.28% |
| Sunday | 20,033 | 1,595 | 7.96% |

Interpretation: Sunday is real if optimizing for lower competition. It is not the best launch slot if the goal is broad
technical attention and a lively discussion while the author is available.

### Candidate Slots

The strongest practical slots were around late morning Eastern. Among normal launch windows, Wednesday 11:00 AM Eastern
was the best all-around bucket.

| Candidate slot, ET | Stories | Stories >=50 points | Rate | Notes |
| --- | ---: | ---: | ---: | --- |
| Sunday 11:00 AM | 1,230 | 100 | 8.13% | Strong ratio, weaker launch-day reach. |
| Monday 9:00 AM | 1,872 | 131 | 7.00% | Good data, but leaves little post-Sunday polish time. |
| Tuesday 11:00 AM | 2,200 | 153 | 6.95% | Strong fallback. |
| Wednesday 11:00 AM | 2,152 | 156 | 7.25% | Best blend of weekday volume, rate, and availability. |
| Wednesday 12:00 PM | 2,085 | 151 | 7.24% | Nearly as good, but one hour less Europe-friendly. |
| Thursday 9:00 AM | 1,969 | 137 | 6.96% | Solid fallback. |
| Thursday 1:00 PM | 1,823 | 136 | 7.46% | Good data, but later for Europe and less clearly "morning launch." |

## Practical Posting Plan

- Use Monday and Tuesday after the Sunday completion date for final proofreading, link checks, quickstart checks, and
  first-comment prep.
- Submit the post as a regular link around 11:00 AM Eastern, not as a text post.
- Add one calm first comment with context, a quickstart link, one honest limitation, and the specific feedback wanted.
- Stay in the thread for the first 2-4 hours, then check back later in the day.
- Do not cross-post widely before the HN discussion has had time to form. Early outside traffic can look coordinated
  even when the intent is innocent.
- Do not ask friends, followers, users, or teammates to vote or comment.

## Sources

- Hacker News Guidelines: https://news.ycombinator.com/newsguidelines.html
- Hacker News FAQ: https://news.ycombinator.com/newsfaq.html
- Show HN Guidelines: https://news.ycombinator.com/showhn.html
- Launch HN Instructions: https://news.ycombinator.com/yli.html
- Syften HN posting guide, updated May 7, 2026: https://syften.com/blog/hacker-news-marketing/
- Chanind 2019 HN timing analysis: https://chanind.github.io/2019/05/07/best-time-to-submit-to-hacker-news.html
- Amplify Partners front-page study: https://www.amplifypartners.com/blog-posts/what-gets-to-the-front-page-of-hackernews
- HN Algolia API endpoint used for the fresh sample: https://hn.algolia.com/api/v1/search_by_date

## Final Recommendation

Recommended post time: Wednesday, June 24, 2026 at 11:00 AM Eastern Time, which is 8:00 AM Pacific and 15:00 UTC.
