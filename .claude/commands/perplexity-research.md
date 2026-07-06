# /perplexity-research — 收回 Perplexity 查證結果並整理

把 Ian 在 Perplexity Pro 上查好的結果收回本機歸檔、列出引用清單讓他挑選。
**人在場的半自動**：不做無人值守抓取、不自動寫 database。

## 輸入

`$ARGUMENTS` 可以是：
- 一個 Perplexity 分享連結（`https://www.perplexity.ai/search/...`）
- 空白：改用瀏覽器模式收回目前開著的 Perplexity 分頁

## 流程

### A. 分享連結模式（注意：多半會被擋）

**Perplexity 用 Cloudflare 擋所有機器抓取（實測回 403「Just a moment...」殼頁），
WebFetch 大概率拿不到內文。** 先試一次，被擋就直接走 B 或 C，不要重試硬抓。

1. 用 WebFetch 抓分享頁；若回來的是 JS 驗證殼頁或空殼，改走 B/C。
2. 成功才寫入 `.cache/perplexity-research/<slug>-<UTC時間戳>.md`，YAML frontmatter 含
   `share_url`、`fetched_at`、`citations`（引用 URL 陣列）。
3. 向 Ian 條列引用清單（標題＋網址＋一句它支持了什麼），問他哪些要收。
4. 他挑了才動作：走 local_web 的「新增到入庫建檔區」同款欄位（POST /items，
   `source_name: 查證來源`），或把重點寫進 `knowledge/` 筆記。**沒挑的不動。**

提醒 Ian：查核 session 頁的「送回 Ian Open News」書籤鈕是最穩路徑——
用他已登入的瀏覽器直送，完全不經伺服器抓取。

### B. 瀏覽器模式（分頁還開著、還沒按 Share 時）

1. 用 claude-in-chrome 的 `tabs_context_mcp` 找到 perplexity.ai 分頁。
2. 用 `get_page_text` 輪詢到內容穩定（連續兩次抓取相同才算生成完）。
3. 之後同 A 的 2-4 步。

### C. degraded path（上面都失敗時）

請 Ian 直接全選複製 Perplexity 的回答貼進對話，你負責整理成同格式歸檔檔案，
並照樣列引用清單讓他挑。

## 底線

- 一律保留出處：引用 URL、查詢時間、原始 thread 連結都寫進 frontmatter。
- Perplexity 的答案是**線索不是定論**：要進 brief 的宣稱，仍走
  `knowledge-fact-checker` 的查核流程核對一手來源。
- 尊重服務條款：只收 Ian 自己帳號、自己觸發的查詢結果，不批次爬取。
