# Markdown 閱讀版相容規則

本機單篇閱讀頁與 `docs/reader` 公開閱讀版共用 `scripts/local_web.py` 的
`markdown_to_html()`。遇到目錄、標題錨點或表格顯示差異時，應先修共用 renderer，
不要只改單一產出頁或重寫文章內容。

## 目錄與標題錨點

新整理的長文建議為目錄目標使用穩定的英文 ID：

```markdown
- [公部門 AI 採用](#public-sector-ai-adoption)

## 公部門 AI 採用 {#public-sector-ai-adoption}
```

- ID 必須以英文字母開頭，後續可用英數字、`-`、`_`、`.`、`:`。
- 同一篇文章內的明確 ID 不可重複。
- `{#...}` 只設定 HTML `id`，不會顯示在標題文字裡。
- 舊文章若沒有明確 ID，renderer 會使用保留中文的 GitHub 風格 slug，例如
  `## 1. 引言` 會得到 `id="1-引言"`。新文章仍以明確英文 ID 為優先，避免不同
  Markdown 工具對中文、全形標點與斜線的 slug 規則不一致。

## Pipe table

閱讀版支援標準 pipe table：

```markdown
| 欄位 | 內容 |
|---|---|
| 關鍵詞 | 開源<br>數位主權 |
```

儲存格可使用粗體、連結、code span 與 `<br>`；文字中的 pipe 請寫成 `\|`。
本機與公開版都應使用 `.pdf-table-scroll`／`.pdf-layout-table`，寬表格以橫向捲動
呈現，不壓縮成難讀的固定欄寬。

## 驗證

```bash
python3 -m unittest scripts.test_markdown_rendering.MarkdownRenderingTest.test_toc_fragment_links_match_unicode_heading_fallback_ids
python3 -m unittest scripts.test_markdown_rendering.MarkdownRenderingTest.test_explicit_english_heading_id_is_stable_and_hidden_from_title
python3 -m unittest scripts.test_markdown_rendering.MarkdownRenderingTest.test_public_reader_includes_local_table_layout_styles
python3 scripts/render_ghpages_reader.py --output /tmp/ian-open-news-reader/index.html
```

產出後至少確認：目錄具有 `href="#..."`、對應標題具有相同 `id`，以及公開頁含
`.pdf-table-scroll` 與 `.pdf-layout-table` 的樣式。
