# 把這個範本客製化成你自己的知識整理流程

這份 repo 是一個**可 fork 的範本**：一套「RSS 找題 → 本機分流 → AI 協作起草 → 平行審稿 → 查核 → 開 PR」的知識整理流程，資料正本是 GitHub 上可逐行 review 的 JSONL。

範本只保留**少量範例資料**（4 個範例 RSS 來源、5 筆範例 item、1 筆範例拒收、1 份範例 brief），讓你看得懂結構、又不會被別人的資料卡住。整套程式、agent、slash command、文件都保留可用。

下面照順序做完，就會變成你自己的流程。

---

## 0. 先決條件

- Python 3.10+（`python3 --version` 確認）。
- 安裝相依套件：`python3 -m pip install feedparser requests flask`（抓 RSS、本機網頁會用到）。
- 想用 `/new-brief-pr` 自動開 PR，要先裝並登入 [GitHub CLI](https://cli.github.com/)：`gh auth login`。
- 想用 AI 協作審稿/起草：用 [Claude Code](https://claude.com/claude-code)（讀 `.claude/`）或 Codex CLI（讀 `.codex/`）。沒有也能純手動跑流程。

---

## 1. Fork、改名、清掉範例的痕跡

1. 在 GitHub 上 **Fork** 這個 repo（或用它當 *Template* 建新 repo），再 `git clone` 下來。
2. 改 [README.md](../README.md) 開頭的專案名稱與介紹，換成你的。
3. 全域搜尋還殘留的舊名稱／網域並替換：
   ```bash
   grep -rn "Ian Open News\|tectnews.ospo.tw\|com.ian.opennews" . --exclude-dir=.git
   ```

---

## 2. 設定你的兩條（或多條）主線

主線（track）是整套分類的骨架。改 [database/taxonomy.json](../database/taxonomy.json)：

- `tracks`：把 `digital-humanities-local-knowledge`、`open-tech-open-industry` 改成你的主題。**key 是英文 slug**（會出現在資料、資料夾、branch 名稱裡），`name_zh`、`description`、`beats`（子題）改成你的。
- 保留 `unclassified` 當「還沒分流」的暫存區。
- `statuses` / `priorities` / `source_types` / `review_steps` 通常不用動，除非你要改流程階段。

> ⚠️ track 的 slug 一旦改名，要連帶改：`knowledge/<slug>/` 資料夾、`database/triage-keywords.json`、`database/*.jsonl` 裡的 `track` 欄位、以及 `.claude/` 與 `.codex/` 裡綁主線的 agent / command（見第 6 步）。建議**在還沒累積資料時就先定好主線**。

對應地把內容資料夾改名：

```bash
git mv knowledge/digital-humanities-local-knowledge knowledge/<你的-slug-1>
git mv knowledge/open-tech-open-industry          knowledge/<你的-slug-2>
```

每個 track 資料夾底下保留 `briefs/`、`research/`、`published/` 三個子資料夾與 `README.md`（改成你的收錄判斷與審查底線）。

---

## 3. 設定你的 RSS / 來源

來源正本是 [database/sources.jsonl](../database/sources.jsonl)，一筆一行。範本附了 4 個範例來源（兩條主線各 2 個），**請換成你自己追蹤的**：

- `feed_url`：RSS / Atom 網址。
- `source_type`：`rss`、`google-alert`、`youtube`、`podcast` 會被每日抓取；其餘（`facebook`、`manual`…）不會自動抓。
- `status`：`active` 才會被抓；`paused`、`archived` 不抓。
- `track`：設成你某條主線的 slug（每日抓取預設**不**抓 `unclassified`）。
- `id`：唯一即可；自己加來源用 `src-` 開頭隨意命名。

改完驗證一下：`python3 scripts/validate_database.py`。

---

## 4. 設定分流關鍵字

[database/triage-keywords.json](../database/triage-keywords.json) 決定 RSS 抓進來後，哪些「建議收」、哪些「建議略過」。把每條 track 底下的 `keep_keywords` / `skip_keywords` 換成你領域的詞。track 的 key 要和 taxonomy 的 slug 一致。

---

## 5. 清掉範例資料、放進你的第一筆

範例資料都用 `*-sample-*` 命名、`origin: "sample"`，很好認。準備好後可清空（保留檔案、清掉內容）：

```bash
: > database/items.jsonl
: > database/rejected-items.jsonl
# review-events.jsonl 至少保留 review-seed 那一行，validator 允許它
```

也刪掉範例 brief：`knowledge/digital-humanities-local-knowledge/published/2026-04-16-sample-*.md`。

之後第一筆真實資料，建議走流程產生（見第 7 步）而不是手寫。每次動完資料庫都跑：

```bash
python3 scripts/validate_database.py
```

---

## 6. （選用）調整 AI agent 與 slash command 的口吻

如果你用 Claude Code / Codex：

- [CLAUDE.md](../CLAUDE.md)：常駐寫作規則（忠於來源、台灣用語、可查證優先…）。換成你的寫作底線與主線。
- `.claude/agents/`、`.codex/agents/`：找題、切角、備料、三審、查核的角色。其中 `dh-news-scout`、`opentech-news-scout` 是**綁主線**的，改名或改內容對應你的 track。
- `.claude/commands/`：`/new-dh-brief`、`/new-opentech-brief`、`/review-knowledge-brief`、`/new-brief-pr` 等串接指令，依你的主線改。
- 沒有要用 AI，可整個刪掉 `.claude/`、`.codex/`，流程照樣能手動跑。

---

## 7. 跑跑看：每天的流程

1. **抓 RSS 到待整理區**（不直接進正式資料庫）：
   ```bash
   python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl \
     --dismissed .cache/rss-dismissed.jsonl --report .cache/rss-fetch-report.md
   ```
2. **開本機網頁**做分流（確認收 / 直接送 PR 小消息 / 不收）：
   ```bash
   python3 scripts/local_web.py    # 預設 http://127.0.0.1:8765
   ```
3. **整理成正式內容**：手動套 [templates/knowledge-brief.md](../templates/knowledge-brief.md) 寫到 `knowledge/<track>/briefs/`，或用 `/new-brief-pr` 一句帶起（開 branch → 切角/備料/起草/三審/查核 → 更新資料庫 → `gh pr create`）。
4. **驗證 + 匯出查詢用 SQLite**：
   ```bash
   python3 scripts/validate_database.py
   python3 scripts/export_sqlite.py --output .cache/knowledge.sqlite
   ```

完整流程說明見 [docs/workflow.md](workflow.md) 與 [docs/agents-pipeline.md](agents-pipeline.md)。

---

## 8. （選用）每天自動抓 RSS（macOS launchd）

範本附了 [templates/launchd/com.ian.opennews.rss-fetch.plist](../templates/launchd/com.ian.opennews.rss-fetch.plist)：

1. 把裡面 4 處 `/ABSOLUTE/PATH/TO/your-repo` 換成你 repo 的絕對路徑。
2. 視需要改 `Label`（建議換成你自己的反向網域）。
3. 複製到 `~/Library/LaunchAgents/` 並載入：
   ```bash
   cp templates/launchd/com.ian.opennews.rss-fetch.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.ian.opennews.rss-fetch.plist
   ```

GitHub Actions（[.github/workflows/](../.github/workflows/)）會在 PR / push 時自動驗證資料庫格式。

---

## 不在範本裡的東西（刻意拿掉的）

為了能公開分享，原作者的私人資料已從範本移除，**這些不是 bug**：

- `reference/` 只留 `agents-writing-pipeline.html`（流程設計理念）。原本的 Inoreader 匯出、Make/Airtable blueprint、Excel 跟追表都已拿掉——所以 `scripts/import_reference_data.py` 在範本上無法直接跑（它依賴那份 Excel），請改用 `fetch_rss.py` 或本機網頁建立你自己的資料。
- 已發布的 reader 靜態網站（`docs/reader/`、`docs/index.html`）與自訂網域（`docs/CNAME`）已移除。要產生你自己的 reader 網站，用 `scripts/render_ghpages_reader.py`。

---

## 速查表

| 想做的事 | 改哪裡 |
| --- | --- |
| 改主題分線 | `database/taxonomy.json` 的 `tracks` + `knowledge/<slug>/` 資料夾 |
| 改追蹤的 RSS | `database/sources.jsonl` |
| 改分流關鍵字 | `database/triage-keywords.json` |
| 改寫作規則 / AI 口吻 | `CLAUDE.md`、`.claude/`、`.codex/` |
| 改 brief 骨架 | `templates/knowledge-brief.md` |
| 改每日排程 | `templates/launchd/*.plist` |
| 驗證資料沒壞 | `python3 scripts/validate_database.py` |
