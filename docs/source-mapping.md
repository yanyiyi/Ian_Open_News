# 舊來源到新流程的對應

## 既有來源

### Inoreader export 20260618

- `subscriptions.xml`：RSS、Google Alert、Facebook、YouTube、Podcast 等訂閱來源。
- `starred.json`：過去已收藏或標星的資料，是早期知識判斷的樣本。
- `README.txt`：Inoreader 匯出的時間與說明。

新流程對應：

- `subscriptions.xml` 匯入 `database/sources.jsonl`。
- `starred.json` 匯入 `database/items.jsonl`，預設狀態為 `inbox`。
- Inoreader label 會轉成 `tags`，並協助判斷兩大主線。

### Make AIRTable API 版本.blueprint.json

舊流程的主要邏輯：

1. RSS trigger 抓新資料。
2. HTML to text 清掉文章 HTML。
3. Regex parser 抽取正文或連結。
4. GPT 以 300 字內摘要，包含行文者情緒、發文者屬性、文章重點、資料/文獻來源。
5. 寫入 Airtable `相關資料來源`。
6. LINE 通知。

新流程對應：

- HTML 清理與欄位正規化放進 `scripts/import_reference_data.py`。
- Airtable 欄位映射到 `database/items.jsonl`。
- LINE 通知改為 GitHub Issue / PR 通知。
- GPT 摘要提示保留為 `summary` 與 `review` 工作的一部分，不在匯入時自動覆寫人工摘要。

### [開放科技] 研究、議題與新聞跟追表.xlsx

舊 Excel 主要保存：

- 新聞活動週更新。
- 常見非慣用語與台灣用語。
- 關鍵字、定義、相關觀念。
- 開放資料知識、平台、法規、會議參與追蹤。

新流程對應：

- 各 sheet 轉成 `database/items.jsonl` 的歷史資料，預設主線為 `open-tech-open-industry`。
- Sheet 名稱保留在 `tags`。
- 原始欄位保留在 `reference.raw_columns`，避免舊資料語意流失。

## Airtable 欄位對照

| 舊 Airtable 欄位 | 新資料庫欄位 |
| --- | --- |
| 文章標題 | `title` |
| 內容 | `summary` 或 `excerpt` |
| 網址 | `url` |
| 來源 | `source_name` / `source_id` |
| 作者（原始資料） | `author` |
| 發布日期 | `published_at` |
| 發布月份 | `reference.raw_columns.發布月份` |
| 備註 | `notes` / `review.notes` |
| GPTContent | `summary` 或 `review.ai_summary` |

## 分類初判規則

匯入 script 只做初判，真正分類仍以 PR review 為準。

- 來源群組或 label 含 `記憶庫`、`文資`、`文化局`、`博物`、`地方`、`民眾書寫`：偏向 `digital-humanities-local-knowledge`。
- 來源群組或 label 含 `OpenTech`、`開放資料`、`開放原始碼`、`COSCUP`、`SITCON`、`OCF`、`數位人權`、`資料治理`：偏向 `open-tech-open-industry`。
- 無法判斷則保留 `unclassified`，由 Issue triage 決定。
