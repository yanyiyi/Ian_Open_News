---
item_id: item-7c9b8ff73de68096
track: open-tech-open-industry
status: fact-checking
title: 「AI 沒壞，是你的資料壞了」——把資料治理從一則新創新聞稿裡抽出來
url: https://thenewstack.io/clario-data-enterprise-ai-rot/
source_name: The New Stack
author: Darryl K. Taft
published_at: 2026-06-17
captured_at: 2026-06-18
review_chain:
  - knowledge-angle-strategist
  - knowledge-source-research
  - knowledge-structure-editor
  - knowledge-line-editor
  - knowledge-target-reader
  - knowledge-fact-checker
---

# 「AI 沒壞，是你的資料壞了」——把資料治理從一則新創新聞稿裡抽出來

## 為什麼值得追

- 「企業砸大錢做 AI 卻拿到垃圾結果，根因常在資料而非模型」是個真議題。但這次的載體是一則新創（Clario）新聞稿，被多家媒體幾乎原文轉載——正好示範如何把**可長期累積的議題（資料治理）**從**一次性的廠商新聞**裡抽出來，不替產品背書。

## 原文重點

> The New Stack（2026-06-17）這篇與多家財經媒體的「報導」，實為同一份 Business Wire 新聞稿的轉載／改寫。以下區分可查證事實與待考宣稱。

**可查證事實（公司面）：**

- Clario 於 2026-06-17 公開亮相，宣布**600 萬美元種子輪**，Preface Ventures 領投。
- 共同創辦人：CEO Yousuf Khan（曾任 Pure Storage、Moveworks 的 CIO）、CTO Madhu Vohra（曾任 Oracle、NetApp、Nutanix、VMware）。
- 產品定位：清除企業 **ROT 資料**（redundant, obsolete, trivial）。

**待考宣稱（新聞稿用「保守業界估計」，未指名研究）：**

- 「78% 企業資料為非結構化」：**找不到精確給出 78% 的研究**；業界常引的是 80–90% 區間（多為 Gartner 二手引用，原報告在付費牆後）。
- 「逾三分之一為 ROT」：方向有據，最接近的具名出處是 **Veritas《Global Databerg Report》（2016）** 的 33%，但**已是十年前、且由儲存廠商委託**，新聞稿未交代年代與出處。

## 我們的觀察與可引用的第三方證據

把焦點從 Clario 移開，「資料品質拖累 AI」這件事有更扎實的具名來源：

- Gartner（2025-02-26）：63% 組織沒有或不確定有無適當的 AI 資料管理實務；預測**截至 2026 年（through 2026）將放棄 60% 缺 AI-ready data 的專案**。
- Gartner（2024-07-29）：預測**2025 年底前 30% 生成式 AI 專案在 PoC 後被放棄**，主因含資料品質差。
- Gartner（2026-04-16）：AI 落地成效較好的組織，在資料與分析基礎設施上的投資高達成效較差者的四倍。
- 台灣面：Google Cloud 委託、**AIF（人工智慧科技基金會）**執行的《2024 台灣企業 AI 準備度調查》。⚠️「已導入 AI 業者約 80% 面臨數據挑戰」這個數字無法從公開摘要核實（疑在付費／登入版報告或天下解讀文中），須人工確認原文與描述對象，否則標「需出處」。

並提醒：ROT 治理／資訊生命週期管理（ILM）**早有成熟市場**（Veritas、Commvault、OpenText、SAP ILM 等），Clario 的差異化主張（AI 自動分類）目前**仍是廠商說法、無獨立評測**。

## 切角候選

<details>
<summary>三個切角（採 A 去廠商化議題拆解為主線）</summary>

1. **A 資料品質才是 AI 落地瓶頸**（採用）：去廠商化，可長期累積。
2. B 一份新聞稿如何變成多家報導：資訊生態／媒體識讀，本 repo 方法論自我示範。
3. C 創辦人履歷與投資人陣容的訊號辨讀：易滑向背書，僅作觀察。
</details>

## 來源與證據

- 原始來源：<https://thenewstack.io/clario-data-enterprise-ai-rot/>
- 新聞稿原稿：<https://www.businesswire.com/news/home/20260617473639/en/Clario-Launches-with-%246M-Seed-Funding-to-Rid-Enterprises-of-Garbage-Data>
- 第三方研究：
  - Gartner（AI-ready data）：<https://www.gartner.com/en/newsroom/press-releases/2025-02-26-lack-of-ai-ready-data-puts-ai-projects-at-risk>
  - Gartner（30% GenAI 放棄）：<https://www.gartner.com/en/newsroom/press-releases/2024-07-29-gartner-predicts-30-percent-of-generative-ai-projects-will-be-abandoned-after-proof-of-concept-by-end-of-2025>
  - Veritas Global Databerg Report（2016，33% ROT）：<https://www.veritas.com/news-releases/2016-03-15-veritas-global-databerg-report-finds-85-percent-of-stored-data>
  - 台灣：天下解讀 Google Cloud／AITA 調查 <https://www.cw.com.tw/article/5131665>
- 相關舊資料：item-0fa69507cd927200（Anthropic 開源 MCP 解資料孤島）、item-32024883903a6253（資料治理到 AI 落地的一體化平台，同日同主題）、item-37a15dedf79bb378（數位部「政府資料品質提升機制運作指引」）。

## 文章預定主線

1. 破題用真議題：AI 結果差，常是資料的問題。
2. 點明這次的載體是新聞稿、被多家轉載——明確區分「議題」與「這家公司」。
3. 用 Gartner 等具名研究撐起議題，取代新聞稿那兩個來源不明的數字。
4. 台灣對照：台灣企業約 8 成有數據挑戰、政府有開放資料品質指引但 AI 資料治理仍在發展。
5. 收在「資料治理是 AI 的前置工程」，不替 Clario 解法背書。

## 編輯審查

- 結構審：主線清楚，但「我們的觀察與第三方證據」一段做了兩件事（觀察判斷＋備料決策），宜拆開；Veritas 非原文所引（是我方查到的最近出處），須避免讀者誤會原文引用 Veritas；「為什麼值得追」帶入切角 B 暗示會混淆方向，建議標明 B 僅備查。
- 文字審：標題引號句出處不明，宜標（原文）或改陳述句；ROT 第二次出現補「ROT 資料」並白話翻譯（重複、過時、無用）；「投資高達他人四倍」已補比較基準。
- 讀者審：ROT 是廠商術語、需白話並點明是廠商視角；Gartner 三個數字（63%/60%/30%）層次不同，須說清不是同一件事；結論後缺台灣「下一步」（哪個單位在推、法規依據、是技術還是組織問題）；切角 B（新聞稿如何變多家報導）對關心資訊生態的讀者更有立即感，被埋可惜。

## 查核紀錄

| 宣稱 | 判定 | 來源 | 處理 |
| --- | --- | --- | --- |
| Clario 600 萬美元種子輪、Preface 領投 | ✅ | Business Wire | 保留 |
| 創辦人經歷 | ✅（公司自述） | Business Wire | 標「公司自述」 |
| 78% 非結構化資料 | ⚠️ 無法溯源 | 新聞稿「業界估計」 | 不引此數，改用 80–90% 並標二手 |
| 逾三分之一 ROT | ⚠️ | Veritas 2016（廠商、十年前） | 引用須標年代與委託方 |
| 截至 2026 年放棄 60% 缺 AI-ready data 專案 | ✅（措辭已校） | Gartner 2025-02 | 用「截至 2026」對應 through 2026 |
| 30% GenAI 專案 PoC 後放棄 | ✅ | Gartner 2024-07 | 採為佐證 |
| 台灣約 80% 企業面臨數據挑戰 | ⚠️ 待核 | 執行單位為 AIF 非 AITA；80% 數字未能溯源 | 改 AIF；數字待人工確認否則標需出處 |
| CTO Vohra 四家公司經歷 | ⚠️ | 僅 Business Wire 自述、無獨立旁證 | 標「公司自述」 |
| Clario 產品有效性 | ⚠️ 未證實 | 無獨立評測 | 不背書 |

## 後續行動

- 補 Gartner「80–90% 非結構化」原報告名稱與年份（目前付費牆，標二手）。
- 若採切角 B，補三個轉載版本的重疊比對佐證「同源」。
- 轉對外文章時清除內部標記，並務必保留「議題 ≠ 這家公司」的界線。
