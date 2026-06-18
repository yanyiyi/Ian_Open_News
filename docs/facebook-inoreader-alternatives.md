# Facebook 與 Inoreader Monitor 替代方案

目前 `database/sources.jsonl` 內有兩類來源不能在棄用 Inoreader 後直接抓：

- `facebook`：43 個。多數是 Facebook page URL，不是 RSS/Atom。
- `inoreader-monitor`：9 個。這是 Inoreader 的 `keyword-monitoring-*` pseudo-feed，不是公開可抓的 RSS URL。

`scripts/fetch_rss.py` 預設不抓這兩類，以免每天產生大量失敗紀錄。

## 建議替代順序

### 1. 優先找網站原生 RSS

很多 Facebook page 背後其實有正式網站、Medium、YouTube、Podcast、活動頁或新聞稿頁。若有 RSS/Atom，請改用那個 URL。

在本機網頁新增：

```bash
python3 scripts/local_web.py
```

打開：

```text
http://127.0.0.1:8765/sources/new
```

填入：

- `source_type: rss`
- `status: active`
- `track`: 兩條主線之一

### 2. Inoreader keyword monitoring 改成 Google Alert RSS

如果原本是追關鍵字，例如「國家文化記憶庫」、「Open Source」、「數位人權」，比較接近的替代是 Google Alerts 的 RSS feed。

新增方式：

- 建立 Google Alert。
- Delivery 選 RSS。
- 把 RSS URL 加到本機網頁的 RSS 來源。
- `source_type` 設為 `google-alert`。

### 3. RSSHub / 自架轉換器

RSSHub 是開源的 RSS 生成器，可以替不提供 RSS 的網站建立 feed。它適合做「沒有原生 RSS，但頁面結構可抓」的來源。

落地方式：

- 若已有可用 route：把 route URL 當 `feed_url` 加入 sources。
- 若 route 不穩：自架 RSSHub，或只針對最重要來源寫小型轉換器。
- Facebook 類來源請逐一測試，不建議假設每個 page 都能穩定抓。

參考：

- RSSHub repo: https://github.com/DIYgod/RSSHub
- RSSHub docs: https://docs.rsshub.app/

### 4. Meta 官方 API

Meta Graph API 對公開 Page 內容有權限、審核與 token 限制，不適合直接替代一般 RSS reader。若你是 Page 管理者或有研究資料取用資格，可以另外評估官方 API；否則不建議把它當成日常知識收件箱主線。

參考：

- Page Public Content Access: https://developers.facebook.com/docs/features-reference/page-public-content-access/
- Graph API Pages: https://developers.facebook.com/docs/pages/

### 5. 本機人工收藏補洞

對 Facebook 或沒有 RSS 的頁面，最穩的低成本補法是本機收藏：

```bash
python3 scripts/local_web.py
```

首頁有 bookmarklet。看到值得收的頁面時點一下，會把目前頁面的 title 與 URL 帶進 `items/new` 表單，存成：

- `origin: manual-web`
- `status: inbox`

## 建議處理策略

短期：

- 每天自動抓標準 RSS/Atom。
- Facebook 與 Inoreader monitor 保留在來源庫，但不自動抓。
- 用本機 bookmarklet 補重要 Facebook 貼文或非 RSS 頁面。

中期：

- 把重要 Facebook source 逐一找出替代網站 RSS。
- 把重要 keyword-monitoring 改成 Google Alert RSS。
- 把仍沒有 RSS 的來源評估 RSSHub 或自架轉換器。

長期：

- `facebook` / `inoreader-monitor` 來源若已有替代，將舊 source 設為 `archived`，在 notes 填替代 source id。
