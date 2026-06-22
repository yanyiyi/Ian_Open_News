# Ian Open News — 常駐寫作規則

這份檔案是本專案的常駐寫作規則：每次 session 都會自動載入，不必另外叫 agent。流程靈感與 skill 觀念汲取自同事 toomore 於 OCF 六月內部知識分享的 agents writing pipeline 簡報；本 repo 不保存原始簡報檔，只保留依其流程觀念發展出的本地 rules 與 `.claude/agents/` 角色。它規定「該怎麼寫、底線在哪」；要動腦跑一輪的事（找題、切角、審稿、查核）交給 `.claude/agents/` 的角色。Agents 操作版見 [docs/agents-pipeline.md](docs/agents-pipeline.md)，日常工作流見 [docs/workflow.md](docs/workflow.md)。

## 這個 repo 在做什麼

把分散在 Inoreader、Make、Airtable、Excel 的知識整理流程，搬到 GitHub 上可審核、可版本化。兩條主線：

- `digital-humanities-local-knowledge`：數位人文與在地知識建構。
- `open-tech-open-industry`：開放科技與開放產業發展。

正本是 `database/*.jsonl`（一筆一行，方便 PR 逐行 review）。SQLite 只是查詢輸出，不提交。

## 寫作風格（起草與改稿時一律遵守）

由主 session 起草，沒有專門 agent。起草與改稿時：

1. **忠於來源**：不把「我們的解讀」寫成「來源的主張」。摘要要分清楚「原文說什麼」與「我們的觀察」。
2. **三段分明**：原文重點、我們的觀察、後續建議，三者不混在一起。
3. **台灣用語**：用台灣慣用說法，避免不自然的中國慣用語；外文引用不超譯。
4. **語氣一致**：清楚、準確、不浮誇，不堆積形容詞，不替樂觀敘事背書。
5. **可查證優先**：數字、日期、組織、法規、標準、授權名稱一律保留來源；不確定就標「需要出處」，別硬寫。
6. **保留出處**：來源、作者、組織、地點、時間、原始 URL 一定保留。

### 兩條主線的額外底線

- 數位人文：不把地方、族群、社區敘事扁平化或只當成可抽取素材；涉及敏感族群、地方衝突、身分資料時，在 `review.notes` 標風險。
- 開放科技：不把廠商新聞稿或 marketing language 當成已證實事實；產業機會要附限制、風險與來源；明確區分新聞事實、推論、建議。

## 起草與資料庫慣例

- brief 寫到 `knowledge/<track>/briefs/YYYY-MM-DD-slug.md`，骨架用 [templates/knowledge-brief.md](templates/knowledge-brief.md)。
- 改 `database/items.jsonl` 時，沿用既有欄位，只改該動的（通常是 `status`、`summary`、`review.*`）。一筆一行，不要重排其他行。
- `status` 取值見 `database/taxonomy.json`：`inbox → triaged → researching → drafting → reviewing → fact-checking → ready → published`（或 `archived`）。
- 審稿與查核事件可追加到 `database/review-events.jsonl`。
- 動完資料庫跑 `python3 scripts/validate_database.py` 確認沒破壞格式。

## 角色與指令對照（pipeline 全景）

| 階段 | 角色 / 指令 | 做什麼 |
| --- | --- | --- |
| 找題 | `dh-news-scout`、`opentech-news-scout` | 掃來源與 beat，列出候選，不拍板 |
| 切角 | `knowledge-angle-strategist` | 給 3-4 個切角，不替你選 |
| 備料 | `knowledge-source-research` | 補一手來源與站內舊資料 |
| 起草 | 主 session（套這份規則） | 依 brief 骨架起草 |
| 三審（平行） | `knowledge-structure-editor`、`knowledge-line-editor`、`knowledge-target-reader` | 結構 / 文字 / 讀者，只審不改 |
| 查核 | `knowledge-fact-checker` | 結構穩定後才查可驗證的宣稱 |
| 串接指令 | `/new-dh-brief`、`/new-opentech-brief`、`/review-knowledge-brief`、`/new-brief-pr` | 把整條包成一句 |

## 不要做的事

- 不替使用者拍板挑題或選切角；攤出選項，讓他決定。
- 結構還會大改時不要跑最終查核（查了白查）。
- 不直接提交 SQLite 或 `.cache/` 內的候選清單。
- 不把候選清單當正式資料庫；候選只在 `.cache/rss-candidates.jsonl`，按「收下」後才進 `database/items.jsonl`。
