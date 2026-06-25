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
- `tags`：來源 label、sheet 名稱、自動關鍵字之外的人工概念標籤；本機閱讀區與卡片會把非雜訊 tag 顯示出來，也可用來篩選。
- `tag_metadata`：單篇頁更新 tag 時留下的來源、更新時間與前一版 tag，方便追蹤人工補標。
- `origin`：`inoreader-starred`、`rss-fetch`、`manual-web`、`manual-pdf`、`pdf-split`、`xlsx:<sheet>` 或 `manual`。
- `reference`：原始檔案、原始 record id、舊欄位等。PDF 上傳會記錄 `.cache/uploads/` 相對路徑、`pdf_meta`、來源狀態與人工關係確認結果；PDF 本體不進版控。
- `review`：審查狀態、切角、查核與備註。
- `triage`：關鍵字第一層判斷，標示建議收、建議不要看、命中與排除關鍵字。
- `editorial_triage`：本機規則初篩欄位，綜合關鍵字、過去不收紀錄、過去收錄類型，產生「為什麼建議看」與下一步建議；若有 `codex_review`，代表由 Codex 另行閱讀主文後生成的閱讀建議。
- `personal_notes`：閱讀區的「我的關鍵紀錄」，用來讓重送 skill 時依個人觀點重新檢視文章。
- `reader_flags`：閱讀區的人工旗標，例如 `current_reading`、`share_intent`、`started_at`；標記 2 天以上的文章在未指定項目時會優先進入 skill 候選排序。
- `reading_metadata`：按「閱讀更多」或批次補資料時，從原始網址抓回的 `og:image`、title、description、canonical URL、摘錄、`article_text` 原始主文與 `article_markdown` Markdown 閱讀版。批次補資料會在 `reader_enrichment` 記錄最後嘗試時間、完成狀態、仍缺欄位與錯誤，避免無圖或抓取失敗的網址反覆占住同一批次。

PDF 材料與拆出的子篇仍是 item，不是 article。材料間的 `full-source`、`subset`、`related`、`split-from` 關係寫在 `database/material-links.jsonl`；只有編輯台產出的稿件才稱為 article。

## Source 欄位

- `id`：穩定 ID。
- `track`：初判主線。
- `name`：來源名稱。
- `source_group`：Inoreader 群組、Excel sheet 或人工群組。
- `source_type`：`rss`、`facebook`、`google-alert`、`youtube`、`podcast`、`spreadsheet`、`manual`、`inoreader-monitor`。
- `fetch_frequency`：抓取節奏，支援 `hourly`、`six-hourly`、`daily`、`weekly`、`monthly`、`on-update`、`paused`；`on-update` 只在首頁或單一來源手動更新時抓。
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

預設一般來源只抓近 7 天；還沒有成功抓取紀錄的新來源，第一次會先用近 90 天作為回補窗口。抓取會依 `fetch_frequency` 判斷是否到期；若要包含 `on-update` 來源，請加 `--include-on-update` 或從本機網頁首頁手動按更新。

排程使用的完整本機流程會在抓完 RSS 後補 Codex 建議與摘要：

```bash
python3 scripts/local_rss_daily.py
```

首頁手動更新會使用：

```bash
python3 scripts/local_rss_daily.py --manual
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
