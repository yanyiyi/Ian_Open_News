# 施工計畫：線上閱讀版改由 GitHub Actions 建置部署（產物不入 git）

狀態：步驟 1–4 已完成（2026-07-06 施工）：workflow 上線並驗證綠燈、Pages 來源已切到 GitHub Actions（`build_type: workflow`，網域與憑證保留）、794 個 HTML 產物已移出版控、local_web 按鈕改為純本機預覽。剩驗收觀察期（步驟 5）。

## 為什麼要改

現況是本機按「更新線上閱讀版」→ `render_ghpages_reader.py` 全量重產 `docs/reader/`（33 MB、850+ 檔）→ commit 進 main → GitHub Pages 從 `main:/docs` 對外服務。三個代價：

1. **repo 膨脹**：每次全量重產把 25 MB 的 HTML 重新寫進 git 歷史，.git 已達 5.1 GB，只會越滾越大。
2. **線上版永遠慢半拍**：靠人記得回首頁按按鈕；忘了按，資料庫更新就不會反映到公開站。
3. **conflict 副本**：`docs/reader/articles/* [0-9].html` 這類 iCloud/merge 副本需要 cleanup 特判。

改法：**正本（`database/*.jsonl`）照舊進 git；HTML 產物改由 GitHub Actions 在 push 時重建並直接部署，不再 commit。**

## 目標架構

```
push 到 main（database/** 有變動）
  └─ GitHub Actions
       ├─ checkout
       ├─ python3 scripts/render_ghpages_reader.py   ← 純標準函式庫，免裝依賴
       ├─ upload-pages-artifact（docs/）
       └─ deploy-pages → technews.ospo.tw
```

切分原則：

- **移出 git**：`docs/reader/*.html`、`articles/`、`features/`、`tags/`、`sources/` 等所有 render 產物。
- **留在 git**：`docs/CNAME`、`docs/index.html`（手寫入口頁）、`docs/reader/assets/`（含 `cache_reader_images.py` 抓回的圖片快取 7.1 MB——CI 每次向外站重抓不可靠，快取仍走本機更新後 commit）。

## 施工步驟

### 步驟 1：新增 workflow（不影響現況，可先並行驗證）

`.github/workflows/deploy-reader.yml`：

- 觸發：`push` 到 main 且 paths 含 `database/**`、`scripts/render_ghpages_reader.py`、`scripts/local_web.py`、`docs/reader/assets/**`、`docs/index.html`；加 `workflow_dispatch` 手動觸發。
- 步驟：checkout → setup-python 3.12+ → 跑 render → `actions/upload-pages-artifact`（path: `docs`）→ `actions/deploy-pages`。
- 權限：`pages: write`、`id-token: write`；concurrency group 設 `pages` 避免並發部署互踩。
- 注意：render 腳本 `from local_web import ...`，CI 的 cwd/`PYTHONPATH` 要讓 `scripts/` 可匯入（比照本機執行方式跑 `python3 scripts/render_ghpages_reader.py` 即可）。

### 步驟 2：切換 Pages 來源（一次性設定，主要風險點）

- GitHub repo Settings → Pages → Source 從「Deploy from a branch（main /docs）」改成「GitHub Actions」。
- 自訂網域 technews.ospo.tw 與 HTTPS 憑證在切換後重新驗證一次（artifact 內保留 CNAME 檔）。
- 切換前先用 `workflow_dispatch` 手動跑一次步驟 1 的 workflow，確認 artifact 建置成功再切。

### 步驟 3：產物移出 git

- `.gitignore` 加：`docs/reader/*.html`、`docs/reader/articles/`、`docs/reader/features/`、`docs/reader/tags/`、`docs/reader/sources/`（保留 `docs/reader/assets/`）。
- `git rm -r --cached` 對應路徑，單獨一個 commit（訊息註明「產物改由 Actions 建置」）。
- 這步之後 repo 每日增量只剩 JSONL 差異，不再有 25 MB 級的 HTML 重寫。

### 步驟 4：調整 local_web

- 「更新線上閱讀版」按鈕改語意：只做**本機重產＋預覽**，不再 git commit（拿掉「產出 … 線上版」commit 流程，`local_web.py` 行 2525–2566 一帶）。
- 按鈕說明文字改成「線上版由 GitHub Actions 於 push 後自動部署；此按鈕僅重產本機預覽」。
- `docs/local-web.md` 的「更新線上閱讀版」一節同步改寫。

### 步驟 5：驗收與觀察一週

- 驗收清單：
  - [ ] 改一筆 item、push 後 Actions 綠燈，technews.ospo.tw 在數分鐘內反映。
  - [ ] 專文 `status: published` 後 push，features 頁出現該篇。
  - [ ] 單篇材料頁、標籤頁、來源頁路徑不變（外部既有連結不斷）。
  - [ ] bookmarklet「線上閱讀跳離線」仍可從線上頁跳回本機。
  - [ ] `git log --stat` 不再出現 docs/reader HTML 大量變動。
- 觀察期若 Actions 建置失敗率高，回滾方式見下。

## 回滾方案

任一步驟出問題都可退回：Settings → Pages 改回「Deploy from a branch（main /docs）」，本機重按「更新線上閱讀版」補一個產物 commit，即回到現行模式。步驟 3 的 `git rm --cached` 不刪工作區檔案，回滾時直接 `git add` 回來即可。

## 相關但獨立的後續（不在本次範圍）

- **歷史瘦身（選配、破壞性）**：用 `git filter-repo` 把歷史中的 `docs/reader/articles/` 洗掉，可大幅縮小 5.1 GB 的 .git；會重寫全歷史、所有 clone 需重拉，需另行拍板。
- **資料 commit 聚合**：「閱讀資料庫自訂紀錄」逐筆 commit 改 batch/debounce，屬第三階段。
