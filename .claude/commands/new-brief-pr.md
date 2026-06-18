---
description: 篩完關鍵字後，從一筆收下的 item 一路跑到開好 PR（branch、brief、資料庫更新、gh pr create）
---

針對「$ARGUMENTS」（可給 item id、原始 url 或題目），把它從「已收下的候選」一路帶到「開好 PR」。整條只有挑切角與拍板採納哪些意見需要我點頭，其餘照流程跑。

開始前先確認：目前在 git repo、`gh` 已登入、工作區乾淨（有未提交變更先提醒我）。

## 0. 認出這筆 item 與主線

1. 在 `database/items.jsonl` 找到對應 item（先比對 url，再比對 id，最後比對標題關鍵字）。找不到就停下來問我，或請我確認要不要新增一筆。
2. 讀它的 `track`。若是 `unclassified` 或無法判斷，列出兩條主線讓我選：
   - `digital-humanities-local-knowledge`（數位人文與在地知識建構）
   - `open-tech-open-industry`（開放科技與開放產業發展）
3. 記下這筆的 `id`、`title`、`url`、`source_name`，以及（若有）對應的 GitHub issue 編號——可用 `gh issue list --search "<標題關鍵字>"` 找，找不到就當作沒有 issue。

## 1. 開 branch

從 `main` 開新 branch：`brief/<track 簡碼>-<slug>`。

- track 簡碼：`dh` 或 `opentech`。
- slug：用標題做的英數小寫短字串。

```bash
git switch -c brief/<track 簡碼>-<slug>
```

## 2. 切角（停下來讓我選）

用 `knowledge-angle-strategist` 給 3-4 個切角與在地 hook，**停下來讓我挑**。不要替我拍板。

## 3. 備料

我選定後，用 `knowledge-source-research` 補一手來源與 repo 內可交叉連結的舊資料。
- 數位人文：原始公告、文化機構文件、地方資料、舊 brief。
- 開放科技：一手文件、法規、標準、授權、GitHub repo、舊 brief。

## 4. 起草

依 `CLAUDE.md` 的寫作風格規則，套 `source-research` 的料，照 `templates/knowledge-brief.md` 起草到：

```
knowledge/<track>/briefs/YYYY-MM-DD-<slug>.md
```

frontmatter 帶上 `item_id`、`track`、`title`、`url`、`source_name`、`status: drafting`。

## 5. 三審（平行）

把 `knowledge-structure-editor`、`knowledge-line-editor`、`knowledge-target-reader` **平行**派出去，整合成一份修訂清單（標出大改、順句、補背景、可不採納）。**停下來讓我拍板採納哪些**。

我拍板後改寫一版；大改先做、順句後做。

## 6. 查核

結構與文字穩定後，用 `knowledge-fact-checker` 查可驗證的宣稱（數字、日期、組織、法規、標準、授權、技術描述、案例）。把結果寫進 brief 的「查核紀錄」段落。內容若還會大改，先別跑查核。

## 7. 更新資料庫

1. 更新這筆 item 在 `database/items.jsonl` 的：
   - `status`：通常推進到 `reviewing` 或 `fact-checking`（看跑到哪）。
   - `review.*`：把對應步驟標起來（`structure_review`、`line_review`、`target_reader_review`、`fact_check`、`angle`、`research_status`）。
   - 只改該動的欄位，保持一筆一行，不要動到其他行。
2. （可選）追加事件到 `database/review-events.jsonl`。
3. 跑驗證，必須通過才繼續：

```bash
python3 scripts/validate_database.py
```

## 8. 提交並開 PR

```bash
git add knowledge/<track>/briefs/ database/items.jsonl database/review-events.jsonl
git commit -m "brief: <標題短描述>"
git push -u origin HEAD
```

用 `gh pr create` 開 PR，套用 `.github/pull_request_template.md`：

- 標題：`[<主線中文>] <brief 標題>`。
- body 以 PR template 為骨架，把**實際做完**的審查鏈項目打勾（沒做的留空，別亂勾）。
- 「這次處理」寫一句這篇在做什麼。
- 若有對應 issue，body 結尾用 `Closes #<issue 編號>`。

```bash
gh pr create --title "..." --body "..." --base main
```

開完把 PR 連結回報給我。**先不要合併**；合併後我再把 item 的 `status` 更新成 `ready` 或 `published`。

## 收尾回報

回報：branch 名、brief 路徑、改了哪些 item、查核軟化/標記了哪幾條、PR 連結。
