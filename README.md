# Ian Open News 知識管理流程

這個 repo 把過去分散在 Inoreader、Make、Airtable、Excel 裡的知識整理流程，改成可以在 GitHub 上審核、追蹤、版本化的工作流。

兩條主線：

- `digital-humanities-local-knowledge`：數位人文與在地知識建構
- `open-tech-open-industry`：開放科技與開放產業發展

核心設計沿用 `reference/agents-writing-pipeline.html` 的邏輯：先找題與備料，再由主 session 起草，最後用平行審稿與查核收尾。差別是這裡把 Airtable 資料表換成 repo 內的文字資料庫，讓新增資料、分類、審核狀態與摘要都能透過 Issue / PR / GitHub Actions 管理。

## Repo 結構

- `reference/`：原始參考檔，不直接編輯。
- `database/`：GitHub-native database，JSONL 是正本，SQLite 可由 script 產生。
- `knowledge/`：兩條知識主線的工作區與說明。
- `docs/`：流程、來源對應、審查鏈、本機操作說明。
- `.github/`：Issue 表單、PR checklist、資料驗證 workflow。
- `.claude/`：依簡報邏輯整理的 agent 與 slash command 範本。
- `CLAUDE.md`：常駐寫作規則，每次 session 自動載入（簡報裡 rules 那半邊）。
- `scripts/`：匯入、抓 RSS、驗證、匯出 SQLite、本機網頁工具。

## Agents 寫作生產線

把每次發文都會漏的「寫作風格、查證、觀點」交給固定角色顧。完整教學（七個角色、三種叫法、平行 vs 串接、rules vs agents）見 **[docs/agents-pipeline.md](docs/agents-pipeline.md)**。

- 常駐寫作風格與底線 → [CLAUDE.md](CLAUDE.md)（自動套，不必叫）。
- 審稿/查核/研究角色 → [.claude/agents/](.claude/agents/)（按需呼叫）。
- 一句帶起整條：
  - `/new-dh-brief <題目>`、`/new-opentech-brief <題目>`：跑到 brief + 審稿查核。
  - `/review-knowledge-brief <brief 路徑>`：對既有 brief 跑三審 + 查核。
  - `/new-brief-pr <item id / url / 題目>`：上面整條 **再加上** 開 branch、更新資料庫、`gh pr create`。

## 常用指令

從既有 reference 重新產生資料庫：

```bash
python3 scripts/import_reference_data.py
```

從 `database/sources.jsonl` 抓 RSS/Atom，新增到 `database/items.jsonl`：

```bash
python3 scripts/fetch_rss.py
```

如果是日常使用，建議先抓到本機候選清單，不要直接進正式資料庫：

```bash
python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl --dismissed .cache/rss-dismissed.jsonl --report .cache/rss-fetch-report.md
```

啟動本機網頁，用表單加收藏或 RSS：

```bash
python3 scripts/local_web.py
```

預設開在 `http://127.0.0.1:8765`。

驗證資料庫欄位、分類、來源關聯：

```bash
python3 scripts/validate_database.py
```

產生本機查詢用 SQLite：

```bash
python3 scripts/export_sqlite.py --output .cache/knowledge.sqlite
```

## 每天怎麼開始

1. 開本機網頁：`python3 scripts/local_web.py`。
2. 到「候選清單」，先看 RSS 自動抓到的新資料。
3. 系統會依 `database/triage-keywords.json` 標「建議收」或「建議不要看」。
4. 真的值得追的，按「收下到資料庫」。
5. 如果要進入線上審查管理，按「收下並開 GitHub issue」。
6. 不值得的，按「不要看，以後略過」，之後同一筆不會再進候選清單。

候選清單只存在 `.cache/rss-candidates.jsonl`，不算正式資料庫。按「收下」後才會寫進 `database/items.jsonl`。

## GitHub 工作流是第二階段

GitHub 不再是 RSS 抓取的第一站，而是「本機已經覺得值得追」之後的審查管理區。

1. 本機候選清單按「收下並開 GitHub issue」。
2. Issue 裡補主線、來源、摘要、切角與處理建議。
3. 確定要整理成正式內容時，用 `/new-brief-pr <item id / url / 題目>` 一句帶起：開 branch、跑切角/備料/起草/三審/查核、更新 `database/items.jsonl`、`gh pr create`（並 `Closes` 對應 issue）。
4. PR 內跑結構審、文字審、讀者審，定稿後再查核。
5. GitHub Actions 驗證資料庫格式，產生 SQLite artifact 供查詢。

從關鍵字篩選一路到開 PR 的完整流程圖見 [docs/agents-pipeline.md](docs/agents-pipeline.md#整體流程篩完關鍵字--開-pr)。

## 每日 RSS 自動化

日常自動抓取建議用本機 `launchd`，每天台灣時間 12:00、18:00、23:00 跑一次。因為候選清單需要你在本機先看過，所以 GitHub Actions 不再每天自動開 PR。每次 RSS 抓完後，本機流程會接著呼叫 Codex CLI，替 RSS 候選補「給 Ian 的一句話推薦」、三個閱讀理由、中文標題與中文摘要。

本機排程會呼叫：

```bash
python3 scripts/local_rss_daily.py
```

只補 Codex 建議與摘要：

```bash
python3 scripts/codex_enrich_reviews.py --target both --workflow-scope --limit 18
```

它會抓 RSS 候選、更新 `.cache/rss-candidates.jsonl`，補上 Codex review，並用 macOS 通知提醒你回本機網頁處理。

流程：

1. 讀 `database/sources.jsonl`。
2. 抓 `status: active` 且 `source_type` 為 `rss`、`google-alert`、`youtube`、`podcast` 的來源。
3. 預設只處理兩條主線，不抓 `unclassified` 來源。
4. 把近 7 天的新項目新增到 `.cache/rss-candidates.jsonl`。
5. 用 `database/triage-keywords.json` 標示「建議收」或「建議不要看」。
6. 用 Codex CLI 補閱讀建議與摘要。
7. 你在本機網頁按「收下」後，才會寫進 `database/items.jsonl`。

要指定/停止來源，直接改 `database/sources.jsonl` 或用本機網頁：

- 要抓：`status` 設為 `active`，`track` 設為兩條主線之一。
- 暫停：`status` 設為 `paused`。
- 不再使用：`status` 設為 `archived`。
- Facebook 頁面與 Inoreader `keyword-monitoring-*` 不是公開 RSS，預設不會抓；替代方案見 [docs/facebook-inoreader-alternatives.md](docs/facebook-inoreader-alternatives.md)。

細節見 [docs/workflow.md](docs/workflow.md)。
