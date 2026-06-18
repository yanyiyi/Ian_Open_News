# 本機網頁收件箱

本機網頁讓你不用直接編輯 JSONL，也能做兩件事：

- 看到不錯的網頁時，加入 `database/items.jsonl` 的 `inbox`。
- 看到不錯的 RSS/Atom 時，加入或編輯 `database/sources.jsonl`。

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

## 加 RSS

打開 `http://127.0.0.1:8765/sources/new`，填：

- 主線
- 名稱
- 來源群組
- source type
- feed URL
- site URL
- status

每日抓取只會處理：

- `status: active`
- `track` 是兩條主線之一
- `source_type` 是 `rss`、`google-alert`、`youtube`、`podcast`

如果來源暫時不想抓，設成 `paused`。如果確定不用，設成 `archived`。

## 手動抓 RSS

首頁有「現在抓取」按鈕，會執行：

```bash
python3 scripts/fetch_rss.py --report .cache/rss-fetch-report.md
```

抓到的新資料會 append 到 `database/items.jsonl`，之後用 Git diff 或 PR 審。

## 本機指令按鈕

首頁的「本機指令」區塊目前有這些 allowlist 按鈕：

- 抓 RSS：`python3 scripts/fetch_rss.py`
- 驗證資料庫：`python3 scripts/validate_database.py`
- 匯出 SQLite：`python3 scripts/export_sqlite.py --output .cache/knowledge.sqlite`
- 看 git status：`git status --short`
- 看 diff stat：`git diff --stat`

網頁服務不接受任意指令，只能跑這些固定 allowlist。
