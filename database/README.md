# Database

這裡是 repo 內的知識資料庫。正本使用 JSONL，原因是每筆資料一行，適合 GitHub PR review。SQLite 由 script 產生，用於查詢或後續接工具。

## Files

- `taxonomy.json`：兩大主線、狀態、優先順序、來源類型。
- `triage-keywords.json`：本機 RSS 候選清單使用的保留/排除關鍵字。
- `sources.jsonl`：來源資料庫，由 Inoreader OPML 與其他來源匯入。
- `items.jsonl`：活躍知識項目資料庫，由 Inoreader starred、Excel、人工收下的 RSS 候選與人工 PR 更新；已不收的資料不留在這裡。
- `rejected-items.jsonl`：不收學習檔，存放從 `items.jsonl` 移出的拒收資料與 RSS 新進拒收資料，供後續分析拒收原因、去重與本機規則初篩使用。
- `review-events.jsonl`：審稿與查核事件，可人工追加。
- `schema.sql`：SQLite 輸出 schema。

## Item 欄位

- `id`：穩定 ID，由 URL 或來源資訊產生。
- `track`：`digital-humanities-local-knowledge`、`open-tech-open-industry` 或 `unclassified`。
- `status`：`inbox`、`triaged`、`researching`、`drafting`、`reviewing`、`fact-checking`、`ready`、`published`、`archived`。一般 UI 不應把已不收資料留在 `items.jsonl`；拒收資料會移到 `rejected-items.jsonl`。
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
- `triage`：關鍵字第一層判斷，標示建議收、建議不要看、命中與排除關鍵字。
- `editorial_triage`：本機規則初篩欄位，綜合關鍵字、過去不收紀錄、過去收錄類型，產生「為什麼建議看」與下一步建議；若有 `codex_review`，代表由 Codex 另行閱讀主文後生成的閱讀建議。
- `personal_notes`：閱讀區的「我的關鍵紀錄」，用來讓重送 skill 時依個人觀點重新檢視文章。
- `reading_metadata`：按「閱讀更多」或批次補資料時，從原始網址抓回的 `og:image`、title、description、canonical URL、摘錄、`article_text` 原始主文與 `article_markdown` Markdown 閱讀版。

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

每日/手動抓 RSS 到 RSS 待整理：

```bash
python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl --dismissed .cache/rss-dismissed.jsonl --report .cache/rss-fetch-report.md
```

排程使用的完整本機流程會在抓完 RSS 後補 Codex 建議與摘要：

```bash
python3 scripts/local_rss_daily.py
```

只補 Codex 建議與摘要：

```bash
python3 scripts/codex_enrich_reviews.py --target both --workflow-scope --limit 18
```

`.cache/rss-candidates.jsonl` 不是正式資料庫。請在本機網頁 `/items` 的「RSS 待整理」按確認收或直接送 PR 後，才寫入 `items.jsonl` 並套用決定。

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
