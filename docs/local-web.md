# 本機網頁收件箱

本機網頁讓你不用直接編輯 JSONL，也能做三件事：

- 看到不錯的網頁時，加入 `database/items.jsonl` 的 `inbox`。
- 看到不錯的 RSS/Atom 時，加入或編輯 `database/sources.jsonl`。
- 依「開放科技與開放產業發展」和「數位人文與在地知識建構」兩條主線查看 RSS 待整理項目與來源。
- 在同一個「RSS 待整理」入口處理 RSS 新進與已入庫 inbox。
- 在閱讀區看已確認收下的文章/小消息，並留下「我的關鍵紀錄」。

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

## RSS 待整理

日常 RSS 抓取會先寫到：

```text
.cache/rss-candidates.jsonl
```

這不是正式資料庫，而是背景緩衝。打開 `http://127.0.0.1:8765/items` 後，會在同一個「RSS 待整理」頁看到兩種卡片：

- `RSS 新進`：還在 `.cache/rss-candidates.jsonl`，尚未入庫。
- `已入庫待分流`：已經在 `database/items.jsonl`，狀態仍是 `inbox`。

每張卡片都可以直接做三種決定：

- 確認收，準備跑 skill：RSS 新進會先寫進 `database/items.jsonl`，再改成 `triaged`，移到候選清單的「待跑 skill」。
- 直接送 PR（小消息）：RSS 新進會先寫進 `database/items.jsonl`，再改成 `ready`，不跑 skill。
- 不收原因：已入庫項目會改成 `archived`；RSS 新進會從緩衝清單移除並寫入 `.cache/rss-dismissed.jsonl`，下一次抓取不會重複出現。

RSS 待整理會依 `database/triage-keywords.json` 標示：

- 建議收：命中該主線的保留關鍵字。
- 建議不要看：命中排除關鍵字，或沒有命中任何保留關鍵字。

你仍然可以手動收下「建議不要看」的項目，系統只做第一層提示。

## 候選清單

打開 `http://127.0.0.1:8765/candidates`，只會看到已經在 RSS 待整理按過「確認收，準備跑 skill」的資料。這裡不再混入 RSS 新進。

候選清單是下一站：跑 skill 做摘要、切角與文章編修，整理好後再送 GitHub PR。

## 閱讀區

打開 `http://127.0.0.1:8765/reader`，可以閱讀已確認收下的精選文章與小消息。閱讀區會盡量使用資料中的 `image`、`image_url`、`thumbnail`、`og_image` 或摘要內圖片 URL 來產生文章卡片；沒有圖片時會用主線色塊。

每篇文章點進單篇頁後可以做兩件事：

- 我的關鍵紀錄：寫下你自己的判斷、疑問、想補的台灣/OCF 脈絡或後續角度，會存進 `personal_notes`。
- 用我的觀點重新送 skill：把文章狀態放回 `triaged`，並在 `skill_requests` 與 `review-events.jsonl` 留下紀錄。後續跑撰稿 skill 時，應該把 `personal_notes` 當成新的檢視角度。
- 閱讀更多：連到原始網址抓 `og:image`、標題、描述、canonical URL、段落摘錄、`article_text` 原始主文與 `article_markdown` Markdown 閱讀版，寫進 `reading_metadata`。如果抓到封面圖，閱讀卡片會使用它；如果抓到主文，單篇頁會以 Markdown 排版顯示成比較好讀的文章版。

閱讀區不會自動開 PR，也不會自動發布。它是「看完覺得更值得處理」時，把資料送回整理流程的入口。

## RSS 待整理的篩選與批次

打開 `http://127.0.0.1:8765/items`，可以同時查看 RSS 新進與已經收進 `database/items.jsonl`、狀態仍是 `inbox` 的資料。這裡會顯示「RSS 新進」「已入庫待分流」「建議收」「建議不要看」「未判斷」的數量，也可以依主線、系統建議與關鍵字篩選。

例如重新跑關鍵字後看到的 `696` 筆建議收與 `44` 筆建議不要看，就是在這個頁面查看。

每筆待整理項目都有人工決定按鈕：

- 確認收，準備跑 skill：把已入庫項目從 `inbox` 改成 `triaged`；RSS 新進會先入庫再改成 `triaged`。處理後會從 RSS 待整理消失，移到候選清單的「已確認收，待跑 skill」。
- 直接送 PR（小消息）：把純事實、很短的小消息改成 `ready`，留下「直接送 PR」紀錄，不進候選清單，也不跑 skill。
- 不收原因小按鈕：在同一張卡片上直接按預設原因。已入庫項目會改成 `archived`；RSS 新進會進入 `.cache/rss-dismissed.jsonl`。
- 其他原因：展開「其他原因」，寫一句原因後送出。

篩選區不用按套用。改主線、系統建議，或勾選關鍵字後，下面列表會自動更新。

RSS 待整理上方也有批次處理：

- 勾選多則後，可以按「批次確認收，準備跑 skill」。
- 勾選多則後，可以批次直接送 PR，或按其中一個批次不收原因。

不管單筆或批次，處理過的項目都會離開 RSS 待整理，避免代辦永遠清不完。

在 RSS 待整理送出單筆或批次處理後，頁面會留在原本的篩選條件，只讓處理完成的卡片淡出消失。

卡片上的標題會進入本機單篇整理頁；「開原文」才會打開外部網站。單篇頁會分開顯示 Codex 生成閱讀建議、原始主文、本機規則判斷、個人紀錄與重送 skill 按鈕。

## Codex 生成與本機規則初篩

`triage` 是第一層關鍵字判斷；`editorial_triage` 是更接近你日常判斷的欄位。它會綜合：

- 關鍵字匹配程度。
- 過去不收文章的來源、標籤、原因與低價值訊號。
- 過去已收錄、舊新聞表或已確認項目的來源與標籤。
- 文章像「純事實新聞 / 小消息」還是「值得收錄的精選文章」。

如果 `editorial_triage.recommendation` 是 `suggest-collect` 或 `suggest-review`，畫面會列出「為什麼建議看」三個理由。如果是 `suggest-skip`，畫面只列出不要看的主要線索，避免花時間替明顯不收的文章寫理由。

## 關鍵字設定

打開 `http://127.0.0.1:8765/keywords`，可以分別設定兩條主線的：

- 建議收的關鍵字。
- 建議不要看的關鍵字。

一行一個關鍵字。儲存後會寫進 `database/triage-keywords.json`，下一次抓 RSS 候選時套用。

如果想立刻套用到目前 RSS 新進與 `database/items.jsonl` 裡的 `inbox` 項目，關鍵字頁下方有「重新跑本機規則/關鍵字初篩」按鈕。

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

首頁有「抓到 RSS 待整理」按鈕，會執行：

```bash
python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl --dismissed .cache/rss-dismissed.jsonl --report .cache/rss-fetch-report.md
```

抓到的新資料會先 append 到 `.cache/rss-candidates.jsonl`，並顯示在「RSS 待整理」的 `RSS 新進` 卡片。你按確認收或直接送 PR 時，系統才會把它寫進 `database/items.jsonl` 並套用決定。

## 本機指令按鈕

首頁的「本機指令」區塊目前有這些 allowlist 按鈕，每個按鈕旁都有白話說明：

- 立刻抓 RSS 候選：`python3 scripts/fetch_rss.py --candidate-output .cache/rss-candidates.jsonl`
- 重新跑本機規則/關鍵字初篩：`python3 scripts/apply_triage_keywords.py`
- 驗證資料庫：`python3 scripts/validate_database.py`
- 匯出 SQLite：`python3 scripts/export_sqlite.py --output .cache/knowledge.sqlite`
- 補閱讀卡圖片、描述與主文：`python3 scripts/enrich_reading_metadata.py --reader-only --only-missing-image --limit 40`
- 查看檔案變更：`git status --short`
- 查看變更摘要：`git diff --stat`

網頁服務不接受任意指令，只能跑這些固定 allowlist。
