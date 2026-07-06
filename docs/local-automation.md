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

## Slack / Telegram 推播（選配）

若要在有新完成內容時推播到 Slack 或 Telegram，使用：

```bash
python3 scripts/notify_ready_items.py --dry-run
```

這支腳本會掃兩種資料：

1. `database/articles.jsonl` 裡 `status: published` 的專文：通知文案使用 `【新專文】`，後面接文章摘要、`summary`、`dek` 或正文第一段。
2. `database/items.jsonl` 裡已有中文翻譯與 AI 閱讀建議的資料池文章：小消息使用 `【新消息】`，材料庫／議題型內容使用 `【新議題】`；通知文案使用 `editorial_triage.*_review.one_line_recommendation` 與前三個 `reasons`，不把 AI 摘要當主通知文案。

去重狀態會寫在：

```text
.cache/notified-events.jsonl
```

自動推播會以 `.cache/notify-auto-start.txt` 或 `ION_NOTIFY_AUTO_START_AT` 作為起算時間。起算前已存在的未發內容會保留在通知頁的「舊未發」，不會被背景排程掃出去；起算後新產出的內容會先待滿 15 分鐘再送。

### Slack Incoming Webhook

在 Slack 建立 app 後開啟 `Incoming Webhooks`，把 webhook URL 放在環境變數：

```bash
export ION_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
```

只送 Slack：

```bash
python3 scripts/notify_ready_items.py --channel slack
```

### Telegram Bot

用 `@BotFather` 建 bot，將 bot 加到群組或頻道後設定：

```bash
export ION_TELEGRAM_BOT_TOKEN="123456:abc..."
export ION_TELEGRAM_CHAT_ID="-1001234567890"
```

只送 Telegram：

```bash
python3 scripts/notify_ready_items.py --channel telegram
```

### 第一次上線

第一次設定時建議先看會送什麼：

```bash
python3 scripts/notify_ready_items.py --dry-run
```

如果不想把舊文章一次全部送出，先把目前符合條件的內容標記為已處理：

```bash
python3 scripts/notify_ready_items.py --mark-existing
```

之後新內容才會真的推播：

```bash
python3 scripts/notify_ready_items.py
```

若要讓本機每 5 分鐘自動巡一次，安裝 launchd 範本：

```bash
cp templates/launchd/com.ian.opennews.notify.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ian.opennews.notify.plist
```

關掉自動巡檢：

```bash
launchctl unload ~/Library/LaunchAgents/com.ian.opennews.notify.plist
```

常用選項：

```bash
python3 scripts/notify_ready_items.py --kind articles
python3 scripts/notify_ready_items.py --kind items
python3 scripts/notify_ready_items.py --id item-xxxxxxxx
python3 scripts/notify_ready_items.py --force --id art-xxxxxxxx
```

預設公開網址是 `https://technews.ospo.tw/reader`。若測試站或分支站不同，可改：

```bash
ION_PUBLIC_BASE_URL="https://example.test/reader" python3 scripts/notify_ready_items.py --dry-run
```

## RSSHub（非 RSS 來源的 bridge，選配）

沒有原生 RSS 的站（PTT、Dcard、巴哈等）可自架 RSSHub 轉成 feed，
兩條跑法（Docker 或 Node 直跑）與 launchd 範本見
[templates/rsshub/README.md](../templates/rsshub/README.md)。
來源紀錄加 `served_via`/`bridge` 出身欄位後，bridge 離線時
`fetch_rss.py` 會整組跳過記 `bridge-unreachable`（不會整批誤報 failed），
`analyze_source_health.py` 也會把整組失敗彙整成一行警報。
換主機用 `python3 scripts/rebuild_bridge_feeds.py --served-via rsshub@local --base <新位址> --dry-run`。

注意：launchd plist 的 log 一律指到 `~/Library/Logs/`，
放 `~/Documents` 可能被 macOS TCC 擋成 EX_CONFIG 78。

### 表情與回覆回流（閉環）

推播出去的內容收到的 emoji 表情與回覆，用收集腳本拉回來：

```bash
python3 scripts/collect_notification_reactions.py
```

（本機網頁通知頁的「收集表情與回覆」按鈕跑的就是這支。）除了更新 `.cache/notification-reactions.json` 彙整檔，**有變化的事件會同步追加一筆快照到 `database/notification-feedback.jsonl` 正本**（append-only，同狀態不重複追加），之後決策學習迴圈與洞察分析就能把讀者回饋當訊號用。只想更新快取不寫回資料庫時加 `--no-db-sync`。

限制照舊：Slack 需要 bot 模式（`ION_SLACK_BOT_TOKEN`，webhook 送出的訊息追不到）；Telegram 群組表情需要 bot 是管理員。
