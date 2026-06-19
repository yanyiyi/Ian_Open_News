---
item_id: item-20d84fe2a6e07343
track: open-tech-open-industry
status: fact-checking
title: 誰定義 AI agent 的「身分」，誰就收下一層基礎設施的租金
url: https://www.opensourceforu.com/2026/06/why-decentralised-identity-is-the-security-bedrock-for-agentic-ai/
source_name: Open Source For You
author: Bala Kalavala
published_at: 2026-06-18
captured_at: 2026-06-18
review_chain:
  - knowledge-angle-strategist
  - knowledge-source-research
  - knowledge-structure-editor
  - knowledge-line-editor
  - knowledge-target-reader
  - knowledge-fact-checker
---

# 誰定義 AI agent 的「身分」，誰就收下一層基礎設施的租金

## 為什麼值得追

- 當 AI agent 開始代表企業簽約、動用資金，「怎麼驗證這個 agent 是誰、誰為它的行為負責」就成了基礎建設問題。原文主張用去中心化身分（DID）作為解方，但真正值得追的是它背後的產業張力：**agent 的身分層由開放標準定義，還是被各雲端大廠的自有體系綁定。**
- 這和站內既有議題互文：誰掌握身分層，誰就掌握下一層的「基礎設施租金」。

## 原文重點

> 原文（Open Source For You，2026-06-18，作者 Bala Kalavala）為**倡議型觀點文章，無外部數據或引用**。以下區分「原文主張」與「可獨立查證事實」。

原文主張（屬作者觀點）：

- 自主 AI agent 需要去中心化身分；傳統 IAM 不足以應對。
- 原話：**「不要建立在按『每個 agent』收費的封閉身分孤島上，成本會指數成長。」**
- 建議用開源 DID 堆疊（點名 **Hyperledger Aries / Indy**），主張可從 10 個擴到 10,000 個 agent 而「零邊際授權成本」。
- 點名工具：Hyperledger Aries、Indy、LangGraph、Open Policy Agent、Model Context Protocol。

## 原文的事實落差（查核重點）

- 原文推薦的 **Hyperledger Aries 品牌已於 2025 年 4 月封存**——但這是組織層的標記，主力框架（ACA-Py、Credo-TS、Bifold 等）已轉移至 OpenWallet Foundation 繼續維護，DIDComm RFC 轉至 DIF；屬「品牌退場、生態存活」，不是技術廢棄。**Indy 方面，Sovrin 基金會已於 2025 年 5 月解散，主網降為唯讀封存狀態（由 Trinsic 單節點維持），已非生產網路**。原文點名的兩個招牌都已大幅變動，引用時必須更新且措辭精確。
- 「per-agent 收費會指數成長」是**假設性憂慮**，不是對現有廠商收費的描述：目前 Microsoft、AWS、Google 的 agent 方案都按用量（token、API 呼叫）計費，**未見 per-agent 固定收費**。

## 切角候選

<details>
<summary>四個切角（採「開放 vs 專有身分孤島」為主線）</summary>

1. 標準成熟度盤點：DID/VC 是否接得住 agent 簽約轉帳。
2. 究責機制：誰為 agent 行為負責（技術可驗證 ≠ 法律可歸責）。
3. **開放 vs 專有身分孤島**（採用）：產業張力，可與站內互文。
4. 從人類身分到非人實體身分：工程轉變，在地性弱。
</details>

## 來源與證據

- 原始來源：<https://www.opensourceforu.com/2026/06/why-decentralised-identity-is-the-security-bedrock-for-agentic-ai/>
- 標準現況（一手）：
  - W3C DID Core v1.0：W3C Recommendation，2022-07-19，<https://www.w3.org/TR/did-core/>
  - W3C Verifiable Credentials 2.0 family：W3C Recommendation，2025-05-15，<https://www.w3.org/news/2025/the-verifiable-credentials-2-0-family-of-specifications-is-now-a-w3c-recommendation/>
  - Hyperledger Aries 封存、轉 OpenWallet Foundation：<https://www.lfdecentralizedtrust.org/blog/hyperledger-aries-an-epicenter-for-decentralized-digital-identity-collaboration-and-innovation>
  - SPIFFE/SPIRE（CNCF Graduated，既有 workload identity）：<https://github.com/spiffe/spire>
- 廠商方案（一手文件，證明「身分層仍是自有體系」）：
  - Microsoft Entra Agent ID：<https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity>
  - AWS Bedrock AgentCore Identity（2025-10 GA）：<https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity.html>
  - Google A2A（2025-04 發布，已移交 Linux Foundation，Apache 2.0）：<https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/>
  - 觀察：**通訊協定層（A2A、MCP）正走向開放**，但**身分主權層仍鎖在各廠商自有 IAM**，尚無跨廠商的 W3C DID 整合。（註：Microsoft 的 Entra Agent ID 本身不採 W3C DID；另一產品線 Entra Verified ID 雖支援 did:web，兩者不同產品，勿混。AWS AgentCore Identity 2025-10-13 GA。）
- 相關舊資料：item-ddb9a7788fcd799f（Fox 併 Roku：第一方資料即家戶身分）、item-b588b05f11e64219（AWS Context 之於 agent 推理）——同屬「agentic 基礎設施的爭奪點」。
- 台灣 hook（延伸）：數位部「數位憑證皮夾」採 DID+VC，2025-03 試驗沙盒、2025-11-06 國際論壇，但處理的是**「人的身分」**；agent 機器身分在台灣**無對應試點**，hook 須明標為延伸。<https://moda.gov.tw/press/press-releases/17810>

## 文章預定主線

1. 破題：agent 要簽約、要動錢，身分驗證變成基礎建設問題。
2. 點出原文主張與其立場（倡議型、作者背景偏顧問），並更新其過時的工具推薦（Aries/Indy 現況）。
3. 拉到產業張力：通訊層開放、身分層各自為政——「身分孤島」的真實風險在哪。
4. 台灣對照：數位皮夾建了 DID/VC 底座，但 agent 身分是另一個尚未開始的場景。
5. 收在「開放標準 vs 平台鎖定」的長期課題，不替任一方案背書。

## 編輯審查

- 結構審：主線有力，但「原文事實落差」段混了糾錯與我方觀察，建議拆為「查核紀錄」與「我們的觀察」；「身分層仍鎖在各廠商」是最重要論點卻埋在來源清單，宜獨立成段；台灣 hook 位置錯置，應移到觀察或後續。
- 文字審：標題「租金」比喻原文未用，須在內文標為我方觀察框架；原文主張段宜加「作者主張」對齊；「零邊際授權成本」正面宣稱本身亦未經驗證，查核表已補。
- 讀者審：DID/VC/IAM/SPIFFE/OPA/MCP 術語堆疊需分層說明（舊問題／新解法／爭議選項）；「agent 代表企業簽約動錢」需一個已發生的具體場景；Aries 停運這個最該帶走的事實應更早更顯眼；台灣 hook 有名無實，宜點出制度缺口或監理單位是否在追。

## 查核紀錄

| 宣稱 | 判定 | 來源 | 處理 |
| --- | --- | --- | --- |
| W3C DID Core 為 Recommendation（2022-07-19） | ✅ | w3.org/TR/did-core | 保留 |
| VC 2.0 family 2025-05-15 升 Recommendation | ✅ | w3.org news | 可補充原文未提 |
| Hyperledger Aries 2025-04 封存 | ✏️ 已修正 | LF Decentralized Trust | 改為「品牌封存、框架轉 OWF 續存」 |
| Indy Sovrin「停止運作」 | ✏️ 已修正 | sovrin.org | 改為「基金會 2025-05 解散、主網轉唯讀」 |
| 原文「per-agent 收費」 | ⚠️ 假設性 | 三大廠均按用量計費 | 標為原文憂慮，非現況 |
| 三大廠身分層為自有體系、非 W3C DID | ✅（MS 需腳注） | MS/AWS/Google 文件 | 加 Entra Verified ID did:web 腳注 |
| AWS AgentCore Identity 2025-10-13 GA | ✅ | AWS 公告 | 補日期 |
| 作者 Bala Kalavala 背景 | ⚠️ 待核 | Bain 履歷 vs「天使投資人」說法不一 | 定稿前確認 |
| 台灣數位皮夾用 DID/VC、2025-11-06 論壇 | ✅ | moda.gov.tw | 標「人身分，非 agent」 |

## 後續行動

- 確認作者背景與立場揭露（顧問／天使投資人）。
- 若深入技術層，補 OPA、MCP 身分驗證規格現況、Credo-TS 企業採用案例。
- 轉對外文章時清除內部標記，並把「Aries/Indy 已變動」寫成讀者看得懂的提醒。
