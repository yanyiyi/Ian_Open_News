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

---

## 深入評估：轉換器引擎選型與介面銜接（2026-06 更新）

這節把上面第 3、5 點展開，補上引擎選型、台灣情境、連線限制與 `/sources/new` 介面設計。核心原則不變：**bridge 產出的 feed 仍是 `source_type: rss`，`fetch_rss.py` 完全不動，深度整合只靠新增的「來源出身」中繼欄位。**

### 引擎選型：RSS-Bridge vs RSSHub

兩者授權都夠寬鬆（RSS-Bridge 是 Unlicense 公有領域、RSSHub 是 MIT），輸出都是 Atom/RSS XML，都相容 `parse_feed_entries`（它只吃 XML，不吃 JSON Feed）。差別在運維與覆蓋：

| 維度 | RSS-Bridge | RSSHub |
| --- | --- | --- |
| 基礎設施 | PHP、無 DB、單容器、解壓即跑 | Node、部分路由需 redis/puppeteer，較重 |
| feed URL | query string，較醜 | 乾淨路徑，PR diff 好讀 |
| 偵測接點 | `?action=detect&url=...` | RSSHub Radar 擴充 + route 規則 |
| 路由覆蓋 | 約 400+，歐美站為主 | 5000+，**台灣社群站（PTT/Dcard/巴哈/噗浪）覆蓋較好** |
| 通用抓取 | `CssSelectorBridge`／`XPathBridge`，填選擇器即可，免寫程式 | 通用轉換路由 |

**本專案決策（兩個獨立訊號都偏向 RSSHub）：**

1. 既有環境已有 Node、沒有 PHP；若不走 Docker 而原生跑，RSSHub 沿用現有工具鏈，不必多裝 PHP。
2. 台灣情境下真正需要 bridge 的是 PTT/Dcard/巴哈/噗浪這類沒原生 RSS 的社群站，RSSHub 覆蓋明顯較好。

→ **預設選 RSSHub**；除非決定走 Docker 且追求最小足跡，才考慮 RSS-Bridge。注意：`效能` 不是選型依據——bridge 工作是網路 I/O bound，PHP 與 Node 執行速度在此無感，差別只在運維足跡。

### 台灣情境：多數內容其實有原生 RSS

不要因為「可能連不上」就放大投資 bridge。台灣八成想追的內容有原生 feed：

- 新聞媒體（中央社、公視、報導者、關鍵評論網、INSIDE、iThome、數位時代）多為 WordPress/CMS，有原生 RSS。
- 部落格平台（痞客邦、方格子 vocus、Matters、Medium）多有 per-blog feed。
- **真正需要 bridge 的只有論壇/社群**（PTT、Dcard、巴哈、噗浪）與 Facebook。

「RSSHub 社群以中國大陸（簡中）為主」只影響文件語言與路由優先級，不影響它對台灣社群站的覆蓋優勢。

### 連線限制：bridge 不翻牆，先分「牆的種類」

bridge 只是把抓取動作搬到伺服器執行，能不能連到取決於 bridge 主機能不能連到目標：

| 牆的種類 | 例子 | self-host 能解嗎 |
| --- | --- | --- |
| 沒牆、只是沒 feed | PTT、Dcard、一般台灣站 | ✅ 完全能解 |
| 公開 instance 限流/不穩 | 公家 `rsshub.app` | ✅ **自架就解決**，不再看別人伺服器死活 |
| 需要登入/cookie | 微博、部分知乎 | ⚠️ 要自己餵 cookie，會過期需顧 |
| 地理封鎖/反爬 | 部分中國平台對境外 IP | ❌ 搬到台灣機器照樣被擋 |

→ **自架是你能掌握的最大改善**（移除公開 instance 風險）；登入/地封牆 self-host 解不了，這類來源標為「次級、會壞」，靠 `analyze_source_health.py` 監控，別當主力。

### 自建食譜的三個等級

- **① 填選擇器（免寫程式）**：`CssSelectorBridge`／RSSHub 通用轉換，在介面填 CSS 選擇器即可。適合靜態 HTML 的部落格、新聞站。
- **② 寫食譜（要寫小爬蟲）**：RSS-Bridge 寫 PHP class／RSSHub 寫 JS 檔。適合結構複雜的站。
- **③ 貢獻上游**：PR 回專案，由社群幫你維護。

**重點**：微博/B 站/知乎/公眾號這類**防爬平台「能自建但別自建」**——它們要登入、簽章、JS 渲染、規則常改，自建等於扛下沒完沒了的維護。直接吃 RSSHub 現成路由，把髒活外包給社群。友善的站隨便 DIY；有敵意的站，借社群的力。

### Facebook：別走 Graph API 自動化

- 自己管理的「**社團 Group**」：Groups API 已大幅廢止，**程式上抓不回來**。
- 自己管理的「**粉專 Page**」：Pages API 技術上可讀自己 Page 的貼文，但要建 app、過審核、顧 token 過期；而且「手動轉貼→再抓回」是繞圈，只在「多人協作投稿」時才划算。
- **建議**：要行動一鍵捕捉，用 iOS 捷徑／bookmarklet POST 到既有手動收件入口（已存在的 `manual-web` bookmarklet），不碰 Meta API。

### `/sources/new` 介面銜接設計（探測階梯）

把探測階梯做成 UI，使用者體驗永遠是「貼一個網址，其餘自動」。`feed_url` 欄位旁加「🔍 偵測 feed」按鈕，按下後後端跑階梯並回結果面板，標清「出身」：

| 階梯 | 偵測方式 | 自動填入 |
| --- | --- | --- |
| ① 原生 feed | 探 `/feed/ /rss /atom.xml /index.xml` + `<link rel=alternate>` | `feed_url`, `source_type=rss` |
| ② Bridge | 打 RSSHub Radar 規則 / RSS-Bridge `?action=detect` | `feed_url`, `served_via`, `bridge` |
| ③ 通用選擇器 | `CssSelectorBridge`／RSSHub 通用轉換 | 展開 CSS 選擇器輸入區 |
| ④ 退路 | 都失敗 | 「Google Alerts 預填 `site:網域`」「手動收進來」捷徑 |

現況 `discover_feed_url_from_html`（`fetch_rss.py:478`）只在「抓到 HTML 卻 parse 失敗」時掃 `<link rel=alternate>`，**不會主動猜常見路徑、也不在 `/sources/new` 加來源當下觸發**——這就是階段 1 要補的優化。

### 來源出身欄位（深度整合的關鍵）

新增三個選用欄位，不破壞既有行：

```jsonc
{
  "feed_url": "http://localhost:1200/redmonk/...",
  "source_type": "rss",              // 不變，沿用既有抓取路徑
  "served_via": "rsshub@local",      // 新增：標記靠哪個 bridge
  "bridge": "redmonk/sogrady",       // 新增：route / bridge 名
  "site_url": "https://redmonk.com/sogrady/"  // 保留原站，供重建 URL/換 host
}
```

換來三項管理能力：

1. **health 依賴彙整**：`analyze_source_health.py` 加 rollup——同一 `served_via` 在同一時段全部 failed，只報一則「bridge 掛了」，而非 N 則各自 danger。
2. **換 host/換引擎不必手改 N 行**：靠 `served_via` + `site_url` 寫腳本批次重生 `feed_url`。
3. **PR diff 與來源清單一眼看出出身**（原生/Bridge/快訊/手動）。

### 執行階段 checklist

- [ ] **階段 0（零程式）**：RedMonk 直接用 `https://redmonk.com/sogrady/feed/` 加成 `rss` 來源；沒原生 feed 的站先用 Google Alerts（查詢 `site:網域`，遞送選 RSS，頻率設「隨時」才會出現 RSS 選項）加成 `google-alert`。
- [ ] **階段 1（小改 local_web）**：`/sources/new` 主動探測常見 feed 路徑與 `<link rel=alternate>`，探到自動填；探不到給退路捷徑。**注意：避開會 autosave 的 `/articles/edit`。**
- [ ] **階段 2（已大致存在）**：手動捕捉走既有 `manual-web` bookmarklet；可再補 iOS 捷徑一鍵 POST。
- [ ] **階段 3（選配）**：撞到沒 feed 的台灣社群站才自架 RSSHub（優先），落地為 `source_type: rss` + `served_via`/`bridge`/`site_url`，並加 health rollup。

參考：

- RSSHub Public Instances（限流/建議自架）: https://docs.rsshub.app/guide/instances
- RSS-Bridge: https://github.com/RSS-Bridge/rss-bridge
