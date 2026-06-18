# Database

這裡是 repo 內的知識資料庫。正本使用 JSONL，原因是每筆資料一行，適合 GitHub PR review。SQLite 由 script 產生，用於查詢或後續接工具。

## Files

- `taxonomy.json`：兩大主線、狀態、優先順序、來源類型。
- `triage-keywords.json`：本機 RSS 候選清單使用的保留/排除關鍵字。
- `sources.jsonl`：來源資料庫，由 Inoreader OPML 與其他來源匯入。
- `items.jsonl`：知識項目資料庫，由 Inoreader starred、Excel、人工收下的 RSS 候選與人工 PR 更新。
- `review-events.jsonl`：審稿與查核事件，可人工追加。
- `schema.sql`：SQLite 輸出 schema。

## Item 欄位

- `id`：穩定 ID，由 URL 或來源資訊產生。
- `track`：`digital-humanities-local-knowledge`、`open-tech-open-industry` 或 `unclassified`。
- `status`：`inbox`、`triaged`、`researching`、`drafting`、`reviewing`、`fact-checking`、`ready`、`published`、`archived`。
- `priority`：`low`、`normal`、`high`、`urgent`。
- `title`：資料標題。
- `url`：原始網址。
- `source_id`：對應 `sources.jsonl`。
- `source_name`：人可讀來源名稱。
- `author`：原始作者或發文者。
- `published_at`：原始發布日期，格式盡量使用 `YYYY-MM-DD`。
- `captured_at`：被 Inoreader、Excel 或 repo 收錄的日期。
- `summary`：摘要或舊資料描述。
- `tags`：來源 label、sheet 名稱或人工標籤。
- `origin`：`inoreader-starred`、`rss-fetch`、`manual-web`、`xlsx:<sheet>` 或 `manual`。
- `reference`：原始檔案、原始 record id、舊欄位等。
- `review`：審查狀態、切角、查核與備註。

## Source 欄位

- `id`：穩定 ID。
- `track`：初判主線。
- `name`：來源名稱。
- `source_group`：Inoreader 群組、Excel sheet 或人工群組。
- `source_type`：`rss`、`facebook`、`google-alert`、`youtube`、`podcast`、`spreadsheet`、`manual`、`inoreader-monitor`。
- `feed_url`：RSS / Atom / Inoreader feed URL。
- `site_url`：來源網站。
- `status`：`active`、`paused`、`archived`。
- `notes`：補充說明。

## 更新方式

重新從 reference 匯入：

```bash
python3 scripts/import_reference_data.py
```

每日/手動抓 RSS 到本機候選清單：

```bash
python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl --dismissed .cache/rss-dismissed.jsonl --report .cache/rss-fetch-report.md
```

候選清單不是正式資料庫。請在本機網頁 `/candidates` 按「收下」後，才寫入 `items.jsonl`。

直接抓 RSS 到正式資料庫：

```bash
python3 scripts/fetch_rss.py
```

預設抓 `status: active`、兩條主線內、`source_type` 為 `rss`、`google-alert`、`youtube`、`podcast` 的來源。沒有加 `--candidate-output` 時，抓到的新項目會以 `origin: rss-fetch`、`status: inbox` append 到 `items.jsonl`。

驗證：

```bash
python3 scripts/validate_database.py
```

匯出 SQLite：

```bash
python3 scripts/export_sqlite.py --output .cache/knowledge.sqlite
```
