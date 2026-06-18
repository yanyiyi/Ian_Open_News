# GitHub-native 知識管理工作流

## 目標

把舊流程中的「RSS / Facebook / Google 快訊 / Inoreader 收藏 -> Make 摘要 -> Airtable 紀錄 -> LINE 通知」改成 GitHub 上可審核的流程：

1. 來源與候選資料進 `database/`。
2. 篩選與切角在 Issue 討論。
3. 摘要、研究札記、對外文章或內部 brief 走 PR。
4. 審查鏈與查核結果留在 GitHub。

每日抓 RSS 的自動化由 `.github/workflows/daily-rss-fetch.yml` 負責。它讀取 `database/sources.jsonl` 裡 `status: active` 的 RSS/Atom 來源，新增近 3 天的資料到 `database/items.jsonl`，再自動開 PR 讓人審。排程是台灣時間 10:00 與 18:00。

## 兩條主線

### 數位人文與在地知識建構

適合收錄：

- 國家文化記憶庫、地方記憶、博物館、檔案、典藏、文化資產。
- 在地媒體、地方文化局、社區組織、地方知識平台。
- 數位典藏、數位策展、社群共筆、民眾書寫、地方資料庫。

審查重點：

- 是否尊重地方脈絡與知識生產者。
- 是否保留來源、作者、社群、地點與時間資訊。
- 是否避免把地方知識只當成可抽取素材。
- 是否能說明「這和數位人文或在地知識建構有什麼關係」。

### 開放科技與開放產業發展

適合收錄：

- 開源、開放資料、資料治理、開放標準、授權、供應鏈與資安。
- Civic tech、公共數位基礎設施、AI governance、數位政策。
- 產業案例、國際組織、政府資料平台、開放科技社群。

審查重點：

- 技術、授權、標準、法規與產業描述是否準確。
- 是否有一手來源或可查證的政策/技術文件。
- 是否說明和台灣、OCF、公共利益或開放生態系的關聯。
- 是否區分新聞事件、政策趨勢、產業機會與可行動建議。

## 狀態流

- `inbox`：新匯入或新提案，尚未判斷是否值得追。
- `triaged`：已分到主線，知道為什麼值得追。
- `researching`：正在補來源、背景、舊資料、相關人物/組織。
- `drafting`：正在寫 brief、摘要、議題卡或文章草稿。
- `reviewing`：進入結構、文字、讀者三審。
- `fact-checking`：結構穩定後，查核數字、日期、案例、技術與法規宣稱。
- `ready`：已可發布或內部使用。
- `published`：已發布或納入正式知識庫。
- `archived`：保留但暫不處理。

## 依 agents-writing-pipeline.html 改寫的鏈條

### 1. 動筆前：找題與備料

- `news-scout`：掃來源與 beat，列出事件、關聯、急迫性。
- `angle-strategist`：給 3-4 個可能切角，不替人拍板。
- `source-research`：補一手來源、過往紀錄、相關舊文或資料集。

GitHub 對應：

- 新題目開 Issue。
- 來源補在 Issue comment 或 `knowledge/<track>/research/`。
- 確定要處理後開 branch / PR。

### 2. 起草：主 session

主 session 依固定格式起草，不另外交給專門 agent。輸出可放在：

- `knowledge/<track>/briefs/YYYY-MM-DD-slug.md`
- 或更新 `database/items.jsonl` 的 `summary`、`status`、`review` 欄位。

### 3. 寫完後：三審平行

- `structure-editor`：論證主線、段落順序、哪些可刪。
- `line-editor`：語句、用詞、語氣一致。
- `target-reader`：讀者是否看得懂、是否被說服。

GitHub 對應：

- 三者可以變成 PR review comment。
- 主 session 整理採納清單，再改稿。
- 大改先做，順句後做。

### 4. 定稿後：fact-checker

只在結構大致穩定後執行，檢查：

- 數字、日期、組織名稱、法規名稱。
- 技術描述、授權描述、政策宣稱。
- 來源是否支持文章實際說法。

查核結果放在 PR comment 或 brief 的「查核紀錄」段落。

## 資料庫原則

`database/*.jsonl` 是正本，因為它可以在 PR 裡逐行 review。SQLite 只作為查詢輸出，由 `scripts/export_sqlite.py` 產生，不直接提交。

每筆 item 至少要有：

- `track`
- `status`
- `title`
- `source_id`
- `source_name`
- `origin`
- `reference`
- `review`

每筆 source 至少要有：

- `track`
- `name`
- `source_group`
- `source_type`
- `status`

`scripts/fetch_rss.py` 只會自動抓：

- `status: active`
- `track` 為 `digital-humanities-local-knowledge` 或 `open-tech-open-industry`
- `source_type` 為 `rss`、`google-alert`、`youtube`、`podcast`
- `feed_url` 是可直接讀取的 RSS/Atom URL

Facebook 頁面、Inoreader keyword monitoring id、純網站頁面可能無法解析；這些會出現在 fetch report 的 skipped 或 failed sources 裡。

完整欄位見 [database/README.md](../database/README.md)。
