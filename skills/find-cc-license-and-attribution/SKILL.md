---
name: find-cc-license-and-attribution
description: Find and normalize Creative Commons license and attribution evidence for web pages, works, images, data, code, logos, or whole pages, then produce a Traditional Chinese attribution table. Use when deciding what CC license applies, what attribution should be displayed, or whether the page is not clearly CC licensed.
---

# Find CC License And Attribution

## Core Rule

Do not guess. Treat a work as `未明確標示` unless the page, linked license text, footer, metadata, or surrounding repository/documentation explicitly supports a normalized license name.

## Output Contract

Return a Traditional Chinese table with exactly these columns. Multiple rows are allowed when text, image, data, code, logo, or whole-page rights differ.

| 使用對象 | Attribution / 應標示對象 | CC 授權名稱 |
|---|---|---|
| 文字 / 圖像 / 資料 / 程式碼 / logo / 整頁 | rights holder or source evidence | normalized license name |

When evidence is unclear, write `未明確標示` in the license column and describe what was checked.

## Normalized Names

Use only these Creative Commons names unless explicitly marking a non-CC result with the prefix `非 CC：`.

- `CC BY 4.0`
- `CC BY-SA 4.0`
- `CC BY-NC 4.0`
- `CC BY-NC-SA 4.0`
- `CC BY-ND 4.0`
- `CC BY-NC-ND 4.0`
- `CC BY 3.0 TW`
- `CC BY-SA 3.0 TW`
- `CC BY-NC 3.0 TW`
- `CC BY-NC-SA 3.0 TW`
- `CC BY-ND 3.0 TW`
- `CC BY-NC-ND 3.0 TW`
- `CC0 1.0`
- `Public Domain Mark 1.0`
- `非 CC：...`
- `未明確標示`

## Workflow

1. Identify the work and scope: text, image, data, code, logo, or whole page.
2. Collect evidence: page footer, license link URL, metadata, repository files, document footer, nearby image captions, or explicit attribution blocks.
3. Split scopes when a page mixes rights, for example CC page text plus copyrighted logo or third-party images.
4. Normalize license names using the list above. Preserve jurisdiction and version only when explicitly stated.
5. If the wording says Creative Commons but not the exact license/version, use `未明確標示`.
6. Include evidence notes after the table: source URL, page title, license link, rights holder, and access date when available.

## Ian Open News Mapping

For this project, the table maps to a top-level `license` object on both `database/items.jsonl` and `database/articles.jsonl`.

```json
{
  "license": {
    "name": "CC BY 4.0",
    "uncertain": false,
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "evidence": {
      "source_url": "https://example.org/page",
      "page_title": "Example",
      "rights_holder": "Example Org",
      "license_link_url": "https://creativecommons.org/licenses/by/4.0/",
      "access_date": "2026-06-28"
    },
    "attribution_table": [
      {"scope": "文字", "attribution": "Example Org", "license_name": "CC BY 4.0"}
    ],
    "provenance": {
      "method": "manual",
      "determined_at": "2026-06-28T00:00:00+00:00",
      "confidence": "high",
      "source_field": "備註"
    }
  }
}
```

`reading_metadata.original_license` remains a legacy free-text note. `license.name` is the authoritative value for filtering. Use `scripts/backfill_licenses.py` for bulk backfill from cached metadata; use this skill for manual review or ambiguous cases.

