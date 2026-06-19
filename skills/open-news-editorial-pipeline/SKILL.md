---
name: open-news-editorial-pipeline
description: Triage and edit Ian Open News knowledge items across RSS intake, local review, small-news PRs, featured-article skills, personal reading notes, and GitHub review chains. Use when working with database/items.jsonl, .cache/rss-candidates.jsonl, editorial_triage, personal_notes, or the two tracks: 開放科技與開放產業發展 and 數位人文與在地知識建構.
---

# Open News Editorial Pipeline

## Core Rule

Treat the local database as the editorial source of truth. Do not skip the local human decision layer: RSS candidates appear in the same RSS 待整理 flow as inbox items, then become small-news PR material, featured-article skill candidates, or archived/dismissed rejects only after a local decision.

## Daily Workflow

1. Fetch RSS into `.cache/rss-candidates.jsonl`.
2. Make sure `triage` and `editorial_triage` exist.
   - `triage` is keyword matching.
   - `editorial_triage` combines keyword fit, prior rejected patterns, prior collected patterns, three viewing reasons, content kind, and next-step hints.
3. Review RSS candidates and inbox items together in the local RSS 待整理 flow.
   - Pure factual news: mark as `ready` with `local_decision.action: direct-pr-small-news`.
   - Worth collecting as a selected article: mark as `triaged` with `local_decision.action: accepted-for-editing`.
   - Not useful: mark existing inbox items as `archived` with `local_decision.action: rejected`, or dismiss RSS candidates into `.cache/rss-dismissed.jsonl`, always with a short reason when available.
   - When acting on an RSS candidate, let the local web flow write it into `database/items.jsonl` only if the decision is confirm-for-skill or direct PR.
4. Keep `/candidates` for already-confirmed selected articles that are waiting for writing/review skills.
5. For small news, prepare one PR containing a list of items, fact-check notes, and minimal database/brief updates.
6. For selected articles, run angle, source research, structure, line, target reader, then fact-check. Open a PR only after the local skill pass produces useful material.
7. After reading published/ready material, use `personal_notes` and `skill_requests` to re-enter the skill workflow when the user adds a new viewpoint.

## Track Judgment

Use `open-tech-open-industry` for open source, open data, data governance, standards, licensing, public digital infrastructure, civic tech, AI governance, supply-chain security, and open industry cases.

Use `digital-humanities-local-knowledge` for cultural memory, local knowledge, museums, archives, digital collections, public history, community writing, local media, cultural heritage, and place-based knowledge infrastructure.

If a record fits both, choose the track where the next editorial output would be most useful. Mention the secondary track in notes instead of duplicating the item.

## How To Read `editorial_triage`

- `recommendation: suggest-collect`: likely worth keeping. Still verify source quality.
- `recommendation: suggest-review`: read manually before deciding.
- `recommendation: suggest-skip`: usually do not spend time unless the user has a personal reason.
- `content_kind: small-news`: do fact-check and concise summary; do not force a long article.
- `content_kind: featured-article`: run the writing/review chain before PR.
- `view_reasons`: use these as starting hypotheses, not final claims.
- `deletion_pattern_fit.signals`: use these to explain why an item may be rejected.
- `prior_collection_fit.signals`: use these to explain why an item resembles past useful material.

## Small-News PR Output

For direct PR small news, create concise entries:

```markdown
- Title:
  Source:
  URL:
  Date:
  Fact-check result:
  Why it matters:
  Database/brief change:
```

Do not over-write. The goal is a trustworthy record, not a full essay.

## Featured-Article Skill Pass

For selected articles, produce:

- One-sentence reason to collect.
- Three possible angles.
- Required source checks.
- Suggested format: short summary, internal brief, issue tracker, or external article.
- Reader risk: what a reader may misunderstand.
- Fact-check checklist.
- Suggested next GitHub change.

If `personal_notes.body` exists, treat it as the user's editorial brief. Explicitly say how the notes changed the angle or priority.

## Rejection Notes

When rejecting, write one short reason that can become a future button:

- 和兩條主線關聯太弱。
- 內容偏活動公告或宣傳。
- 來源重複，已有其他資料。
- 資訊過舊或缺少可查證來源。
- 只是短訊，不足以形成文章。

Prefer the user's own wording when they provided a reason.

## GitHub Boundary

Only open GitHub issues or PRs after local triage says the item is worth managing online. GitHub is for review, traceability, and merge decisions; the local web UI is for fast reading, rejecting, and routing.
