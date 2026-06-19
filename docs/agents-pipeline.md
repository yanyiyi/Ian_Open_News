# Agents 寫作生產線：怎麼用

這份是 [`reference/agents-writing-pipeline.html`](../reference/agents-writing-pipeline.html) 那場簡報的操作版。簡報講「為什麼」，這裡講「怎麼按」。

一句話：**把每次發文都會漏的「寫作風格、查證、觀點」交給固定角色顧，自己只做判斷。**

---

## 先懂一個觀念，免得期待錯

subagent **不會互相對話**。不是幾個 agent 開會辯論出結論。

- 每個 agent 跑在自己獨立的 context，做完把結果交回**主 session**。
- 由主 session 當協調者，把意見收齊、統整，再決定下一步。
- 「討論」發生在主 session 的統整層，agent 之間不互相喊話。

所以流程永遠是：**主 session 派工 → 角色各自跑 → 主 session 收齊 → 你拍板 → 主 session 改稿。**

---

## 兩個半邊：rules vs agents

| | Rules（常駐規則） | Agents（角色） |
| --- | --- | --- |
| 在哪 | [`CLAUDE.md`](../CLAUDE.md) | [`.claude/agents/`](../.claude/agents/) |
| 怎麼運作 | 每次自動套，不必叫 | 按需呼叫，做完才回報 |
| 性質 | 被動約束「該怎麼寫」 | 主動去審、去查、去找 |
| 適合 | 一致的風格、底線 | 一次性的審查、查證、研究 |
| 成本 | 幾乎零額外 token | 每位回報都吃 context |
| 會不會漏 | 永遠都在 | 要記得叫，沒叫就不跑 |

「每次都要、不能漏」的（風格、底線）已經寫進 `CLAUDE.md`，自動套。「要動腦、要跑一輪」的（查證、切角、審稿）用 agents。

---

## 七個角色，一條生產線

對照 repo 內實際檔名（角色定義在 [`.claude/agents/`](../.claude/agents/)）：

### ① 動筆前 · 上游

| 角色 | 檔名 | 什麼時候叫 | 做什麼 |
| --- | --- | --- | --- |
| 議題雷達 | `dh-news-scout` / `opentech-news-scout` | 想找題目 | 掃 beat 與 `database/`，列候選，不拍板 |
| 切角顧問 | `knowledge-angle-strategist` | 題目選好、還沒動筆 | 給 3-4 個切角與在地 hook，不替你選 |
| 來源蒐集 | `knowledge-source-research` | 切角定了、要備料 | 撈一手來源、找站內該交叉連結的舊資料 |

兩條主線各有一個 scout，因為找題標準不同。切角、備料、審稿、查核共用同一組。

### ② 起草

**這一步沒有專門 agent。** 由主 session 起草：把 `CLAUDE.md` 的寫作風格規則，加上 `source-research` 備好的料，依 [`templates/knowledge-brief.md`](../templates/knowledge-brief.md) 寫到 `knowledge/<track>/briefs/`。

### ③ 寫完後 · 審稿（三位平行）

| 角色 | 檔名 | 顧的點 |
| --- | --- | --- |
| 結構審查 | `knowledge-structure-editor` | 主線清不清楚、段落順序、哪些可刪 |
| 文字潤稿 | `knowledge-line-editor` | 順句、用詞、語氣一致、台灣用語 |
| 讀者代言人 | `knowledge-target-reader` | 哪裡看不懂、哪個論點不買單 |

三個互不依賴，**同時派出去**，各跑各的 context。主 session 收齊 → 你拍板採納哪些 → 改寫 → 再丟一次 `line-editor` 收尾。

### ③ 寫完後 · 查證

| 角色 | 檔名 | 時機 |
| --- | --- | --- |
| 事實查核 | `knowledge-fact-checker` | 結構與文字大致定稿後才查 |

逐一判定數字、日期、組織、法規、標準、授權、技術描述、案例「站不站得住」。**結構還會大改就先別查，查了白查。**

---

## 怎麼叫它們：三種力道

| 力道 | 怎麼打 | 效果 | 何時用 |
| --- | --- | --- | --- |
| 最輕（最常用） | `用 knowledge-fact-checker 查 xxx.md` | 句子裡講出名字，Claude 自己決定派不派 | 日常 |
| 中（保證執行） | `@agent-knowledge-line-editor` | 從選單挑，那位一定跑 | 只想要特定一位審 |
| 重（整個 session） | `claude --agent opentech-news-scout` | 整個 session 變那個角色 | 開專門巡題的 session |

**平行 vs 串接**：獨立工作（三審）平行同時跑；有先後（先 structure 改大結構、再 line 順句）就串接。

**一個雷**：手寫檔放進 `.claude/agents/` 要**重開 session** 才吃得到。用 `/agents` 介面建的立即生效。改 `CLAUDE.md` 也要重開 session 才會重新載入。

---

## 包成一句話：slash commands

不必每次重打一長串。指令定義在 [`.claude/commands/`](../.claude/commands/)：

| 指令 | 做什麼 | 到哪為止 |
| --- | --- | --- |
| `/new-dh-brief <題目>` | 數位人文：scout → 切角 → 備料 → 起草 → 三審 → 查核 | 出 brief + 修訂清單 |
| `/new-opentech-brief <題目>` | 開放科技：同上，查核含授權/標準/政策 | 出 brief + 修訂清單 |
| `/review-knowledge-brief <brief 路徑>` | 對既有 brief 跑三審 + 查核 | 出採納清單 |
| `/new-brief-pr <item id / url / 題目>` | 上面整條 **再加上** 開 branch、更新資料庫、開 PR | PR 開好 |

前三個停在 fact-check（內容做完）；`/new-brief-pr` 多做 GitHub 那一段（見下節）。

---

## 整體流程：篩完關鍵字 → 開 PR

這條把本機 triage 接到 GitHub PR。詳細的單一指令是 `/new-brief-pr`，下面是它背後的全貌。

```
RSS 自動抓 ──► .cache/rss-candidates.jsonl ──► 本機網頁 /items「RSS 待整理」
                                                      │
                            triage-keywords.json 標「建議收 / 建議不要看」
                                                      │
       ┌──────────────────────────────────────────────┼────────────────────────────┐
   「不收原因」                           「確認收，準備跑 skill」        「直接送 PR（小消息）」
 寫進 rejected-items + dismissed         寫進 items.jsonl + triaged       寫進 items.jsonl + ready
                                              │
                                              ▼
                                /candidates 候選清單待跑 skill
                                              │
                                              ▼
   /new-brief-pr ─► 開 branch ─► 切角 ─► 備料 ─► 起草 ─► 三審 ─► 查核 ─► 更新 items.jsonl ─► gh pr create
                                                          │
                                              PR 內逐行 review、跑審查鏈
                                                          │
                                                       合併後更新 status
```

### 第一階段：本機篩關鍵字（你已經會的部分）

1. `python3 scripts/local_web.py` 開本機網頁（預設 `http://127.0.0.1:8765`）。
2. 進「RSS 待整理」`/items`，看 RSS 抓到的新資料與既有 inbox。系統用 [`database/triage-keywords.json`](../database/triage-keywords.json) 標「建議收」或「建議不要看」。
3. 真的值得追的按「**確認收，準備跑 skill**」（RSS 新進會先寫進 `database/items.jsonl`，再改成 `triaged`）。
4. 純小消息按「**直接送 PR（小消息）**」；不值得的按不收原因，資料會寫進 `database/rejected-items.jsonl`，RSS 新進也會寫進 `.cache/rss-dismissed.jsonl`，下次不再出現。

關鍵字本身不夠用時，直接編 `database/triage-keywords.json` 的 `keep_keywords` / `skip_keywords`，再回 RSS 待整理重看一輪。

### 第二階段：開 PR（新的部分）

挑好一筆收下的 item 後，一句：

```
/new-brief-pr <item id 或 url 或題目>
```

它會：

1. 從 `database/items.jsonl` 找到那筆 item，認出 `track`（認不出就問你）。
2. 開 branch：`brief/<track 簡碼>-<slug>`。
3. 跑該主線的 pipeline：切角（停下讓你選）→ 備料 → 起草到 `knowledge/<track>/briefs/` → 三審平行 → 你拍板 → 改稿 → 查核。
4. 更新那筆 item 的 `status` 與 `review.*`，必要時追加 `database/review-events.jsonl`。
5. `python3 scripts/validate_database.py` 驗證格式。
6. `gh pr create` 套 [PR template](../.github/pull_request_template.md)，把實際做完的審查鏈勾項打勾，並 `Closes #<issue>`（如果這筆有對應 issue）。

PR 開好後，審查鏈意見可以變成 PR review comment；合併後再把 item 的 `status` 更新成 `ready` 或 `published`。

---

## 仍然是你的事

agent 把功課做好攤出來，**判斷還是你做**：

- 挑哪個題目。
- 選哪個切角。
- 三審意見採納哪些、不採納哪些（衝突時在 PR 留言寫理由）。
- 什麼時候算定稿、可以合併。

角色不是越多越好——每位回報都吃 context，加到夠用就停。

---

## 相關文件

- [`CLAUDE.md`](../CLAUDE.md)：常駐寫作規則（rules 那半邊）。
- [docs/workflow.md](workflow.md)：GitHub-native 工作流全貌。
- [docs/review-chains.md](review-chains.md)：兩條主線的審查標準差異。
- [docs/local-web.md](local-web.md)：本機網頁操作。
- [database/README.md](../database/README.md)：資料庫欄位與更新方式。
