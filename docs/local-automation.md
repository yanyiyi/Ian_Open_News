# 本機排程

如果 repo 已經推到 GitHub，`.github/workflows/daily-rss-fetch.yml` 會在 GitHub-hosted runner 上跑，不需要你的電腦開著。

如果你想完全在本機跑，可以用 macOS `launchd`。本 repo 提供範本：

```text
templates/launchd/com.ian.opennews.rss-fetch.plist
```

它設定每天 10:00 與 18:00 執行：

```bash
python3 scripts/fetch_rss.py --report .cache/rss-fetch-report.md
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

本機排程只會修改本機檔案，不會自動 commit 或 push。抓取後請用 `git diff` 檢查，確認後再 commit。
