# 本機排程

日常建議用本機 `launchd` 跑 RSS，因為新資料會先進「RSS 待整理」，等你看過後才進正式資料庫或 GitHub issue。

本 repo 提供 macOS `launchd` 範本：

```text
templates/launchd/com.ian.opennews.rss-fetch.plist
```

它設定每天 12:00、18:00、23:00 執行：

```bash
python3 scripts/local_rss_daily.py
```

`scripts/local_rss_daily.py` 會執行 RSS 候選抓取，依 `database/sources.jsonl` 裡每個來源的 `fetch_frequency` 判斷是否到期，寫入 `.cache/rss-candidates.jsonl`，接著呼叫 `scripts/codex_enrich_reviews.py`，替新的 RSS 候選補上 Codex 版閱讀建議、中文標題、三個閱讀理由與中文摘要，最後再用 macOS 通知提醒你打開本機網頁的「RSS 待整理」。它不會直接修改 `database/items.jsonl`。電腦在排程時間開著時就會跑；如果當下睡眠或關機，就等下一次排程。

本機網頁首頁的「抓到 RSS 待整理」會用手動模式呼叫：

```bash
python3 scripts/local_rss_daily.py --manual
```

手動模式會額外包含 `fetch_frequency: on-update` 的來源；排程模式則略過這類只想按更新時才抓的來源。

如果某天你只想抓 RSS、不想自動呼叫 Codex，可以在執行前設定：

```bash
IAN_OPEN_NEWS_AUTO_CODEX=0 python3 scripts/local_rss_daily.py
```

手動補 Codex 建議：

```bash
python3 scripts/codex_enrich_reviews.py --target both --workflow-scope --limit 18
```

安裝方式：

```bash
cp templates/launchd/com.ian.opennews.rss-fetch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ian.opennews.rss-fetch.plist
```

停用：

```bash
launchctl unload ~/Library/LaunchAgents/com.ian.opennews.rss-fetch.plist
```

本機排程只會修改本機 `.cache/` 候選檔，不會自動 commit 或 push。Codex 補寫只會寫入候選資料的 `editorial_triage.codex_review` 欄位。每天開機後建議：

1. 執行 `python3 scripts/local_web.py`。
2. 打開本機網頁的「RSS 待整理」。
3. 先按「不要看」清掉不相關項目。
4. 值得追的按「確認收，準備跑 skill」。
5. 純小消息按「直接送 PR（小消息）」。

GitHub Actions 的 `.github/workflows/daily-rss-fetch.yml` 現在只保留手動執行，用來在 GitHub 上產生候選 artifact 或 SQLite 查詢檔，不再每天自動開 PR。
