# 本機網頁收件箱

本機網頁讓你不用直接編輯 JSONL，也能做三件事：

- 看到不錯的網頁時，加入 `database/items.jsonl` 的 `inbox`。
- 看到不錯的 RSS/Atom 時，加入或編輯 `database/sources.jsonl`。
- 依「開放科技與開放產業發展」和「數位人文與在地知識建構」兩條主線查看待整理項目與來源。
- 先審 RSS 候選清單，真的值得追再收進資料庫或開 GitHub issue。

啟動：

```bash
python3 scripts/local_web.py
```

預設網址：

```text
http://127.0.0.1:8765
```

如果 `8765` 已經被其他服務占用，程式會自動往後找下一個可用 port，例如 `8766`、`8767`，並在終端機印出實際網址。

## 加收藏

打開 `http://127.0.0.1:8765/items/new`，填標題、網址、主線、摘要與備註。送出後會新增：

- `origin: manual-web`
- `status: inbox`
- `source_type: manual`

首頁也有 bookmarklet。把它拖到瀏覽器書籤列後，看到想收的頁面時點一下，會自動把目前頁面的 title 和 URL 帶進表單。

也可以從主線入口進入：

- `http://127.0.0.1:8765/track/open-tech-open-industry`
- `http://127.0.0.1:8765/track/digital-humanities-local-knowledge`

從主線入口按「幫這條主線加收藏」時，表單會自動預選該主線。

## RSS 候選清單

日常 RSS 抓取會先寫到：

```text
.cache/rss-candidates.jsonl
```

這不是正式資料庫。打開 `http://127.0.0.1:8765/candidates` 後，你可以做三件事：

- 收下到資料庫：把這筆候選寫進 `database/items.jsonl`。
- 收下並開 GitHub issue：先寫進資料庫，再用 `gh issue create` 開線上整理 issue。
- 不要看，以後略過：從候選清單移除，並寫入 `.cache/rss-dismissed.jsonl`，下一次抓取不會重複出現。

候選清單會依 `database/triage-keywords.json` 標示：

- 建議收：命中該主線的保留關鍵字。
- 建議不要看：命中排除關鍵字，或沒有命中任何保留關鍵字。

你仍然可以手動收下「建議不要看」的項目，系統只做第一層提示。

## 關鍵字設定

打開 `http://127.0.0.1:8765/keywords`，可以分別設定兩條主線的：

- 建議收的關鍵字。
- 建議不要看的關鍵字。

一行一個關鍵字。儲存後會寫進 `database/triage-keywords.json`，下一次抓 RSS 候選時套用。

如果想立刻套用到目前候選清單與 `database/items.jsonl` 裡的 `inbox` 項目，關鍵字頁下方有「重新跑關鍵字判斷」按鈕。

## 加 RSS 與管理來源

打開 `http://127.0.0.1:8765/sources/new`，填：

- 主線
- 名稱
- 來源群組
- 來源類型
- feed URL
- site URL
- 狀態

每日抓取只會處理：

- `status: active`
- `track` 是兩條主線之一
- `source_type` 是 `rss`、`google-alert`、`youtube`、`podcast`

如果來源暫時不想抓，設成 `paused`。如果確定不用，設成 `archived`。

來源列表在 `http://127.0.0.1:8765/sources`。畫面會依主線和來源群組分類呈現，也可以用篩選器切換：

- 主線：全部、開放科技、人文與在地知識、未分類。
- 來源類型：RSS / 網站、Google 快訊、YouTube、Podcast、Facebook、Inoreader 關鍵字、既有表格、手動加入。
- 狀態：啟用＋暫停、只看啟用、只看暫停、只看封存、全部狀態。

長網址會在表格中自動換行，不會把頁面撐破。

## 主線入口

首頁是共通入口，提供兩個主線工作台：

- 開放科技與開放產業發展：使用 OCF 紫色識別。
- 數位人文與在地知識建構：使用深藍色識別。

每個主線工作台會顯示全部項目、待整理項目、來源數、會自動抓的來源數，並提供三個常用按鈕：

- 幫這條主線加收藏：新增單篇文章或頁面。
- 幫這條主線加 RSS：新增長期追蹤來源。
- 看這條主線的來源：檢查或編輯這條主線的 RSS/來源清單。

## 手動抓 RSS

首頁有「抓到候選清單」按鈕，會執行：

```bash
python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl --dismissed .cache/rss-dismissed.jsonl --report .cache/rss-fetch-report.md
```

抓到的新資料會先 append 到 `.cache/rss-candidates.jsonl`。只有你在候選清單按「收下」後，才會進 `database/items.jsonl`。

## 本機指令按鈕

首頁的「本機指令」區塊目前有這些 allowlist 按鈕，每個按鈕旁都有白話說明：

- 立刻抓 RSS 候選：`python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl`
- 重新跑關鍵字判斷：`python3 scripts/apply_triage_keywords.py`
- 驗證資料庫：`python3 scripts/validate_database.py`
- 匯出 SQLite：`python3 scripts/export_sqlite.py --output .cache/knowledge.sqlite`
- 查看檔案變更：`git status --short`
- 查看變更摘要：`git diff --stat`

網頁服務不接受任意指令，只能跑這些固定 allowlist。
