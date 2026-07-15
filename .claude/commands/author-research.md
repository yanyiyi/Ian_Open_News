# /author-research — 收回作者查證結果並回填作者庫

Ian 把 Perplexity 的作者查證回覆貼給你（`$ARGUMENTS` 可能是檔案路徑、batch 編號，或直接是整段回覆文字）時，照下面流程做。這條流程的機械部分全在本地 script，你只處理例外。

## 流程

1. **拿到結果**：
   - 若 `$ARGUMENTS` 是檔案路徑（`.cache/author-research/batch-NN-result.json` 之類）直接用。
   - 若是貼上的整段回覆，先 Write 存成 `.cache/author-research/batch-NN-result.md`（batch 編號問脈絡；單一作者存 `single-<slug>-<UTC時間戳>.md`）。
2. **回填**：`python3 scripts/import_author_research.py --input <檔案>`（單一作者加 `--method perplexity-single`）。解析容錯（```json 區塊、trailing comma）都在 script 裡，不要自己手改 JSON。
3. **驗證**：`python3 scripts/validate_database.py`。
4. **回報 Ian**，條列：
   - 更新了幾筆、新建了哪些組織。
   - `對不回作者庫` 的名字（通常是 Perplexity 改寫了署名——對照 `database/authors.jsonl` 的 `byline_names` 找出正主，改 result 檔的 `name` 再重跑，或請 Ian 在 `/authors` 頁人工併入）。
   - `待人工複核`（confidence low / unknown）的名單，附 Perplexity 的 note，讓 Ian 在 `/authors?status=needs-review` 逐筆確認。

## 底線

- Perplexity 的介紹是**線索不是定論**：`verification.status` 停在 `ai-suggested`，只有 Ian 本人確認過才改 `verified`（在作者單頁改，或改 jsonl）。
- 禁止替查不到的人編介紹；`unknown` 就讓它留白等人工。
- 不要動 `database/items.jsonl` 的 byline 欄位；作者↔文章是讀取時比對，不用回寫。
- 原始回覆一律留檔在 `.cache/author-research/`（不進 git），`verification.evidence` 會指回去。

## 相關檔案

- 批次 prompt 產生：`python3 scripts/build_author_registry.py`（會跳過已有 intro 或已標 noise 的實體，可重跑）
- 比對規則正本：`scripts/author_registry.py`（split/normalize 是唯一的一把尺）
- 網頁端：`/authors`（索引＋未整理署名 triage）、`/authors/view?id=`（單頁編輯＋查此作者）
