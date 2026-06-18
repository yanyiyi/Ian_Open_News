# Ian Open News 知識管理流程

這個 repo 把過去分散在 Inoreader、Make、Airtable、Excel 裡的知識整理流程，改成可以在 GitHub 上審核、追蹤、版本化的工作流。

兩條主線：

- `digital-humanities-local-knowledge`：數位人文與在地知識建構
- `open-tech-open-industry`：開放科技與開放產業發展

核心設計沿用 `reference/agents-writing-pipeline.html` 的邏輯：先找題與備料，再由主 session 起草，最後用平行審稿與查核收尾。差別是這裡把 Airtable 資料表換成 repo 內的文字資料庫，讓新增資料、分類、審核狀態與摘要都能透過 Issue / PR / GitHub Actions 管理。

## Repo 結構

- `reference/`：原始參考檔，不直接編輯。
- `database/`：GitHub-native database，JSONL 是正本，SQLite 可由 script 產生。
- `knowledge/`：兩條知識主線的工作區與說明。
- `docs/`：流程、來源對應、審查鏈說明。
- `.github/`：Issue 表單、PR checklist、資料驗證 workflow。
- `.claude/`：依簡報邏輯整理的 agent 與 slash command 範本。
- `scripts/`：匯入、驗證、匯出 SQLite 的工具。

## 常用指令

從既有 reference 重新產生資料庫：

```bash
python3 scripts/import_reference_data.py
```

驗證資料庫欄位、分類、來源關聯：

```bash
python3 scripts/validate_database.py
```

產生本機查詢用 SQLite：

```bash
python3 scripts/export_sqlite.py --output .cache/knowledge.sqlite
```

## GitHub 工作流

1. 新資料先開 `Knowledge item intake` issue。
2. 分流到兩條主線之一，補來源、摘要、切角與處理建議。
3. 用 PR 修改 `database/items.jsonl` 或新增 `knowledge/<track>/briefs/` 內容。
4. PR 內跑結構審、文字審、讀者審，定稿後再查核。
5. GitHub Actions 驗證資料庫格式，產生 SQLite artifact 供查詢。

細節見 [docs/workflow.md](docs/workflow.md)。
