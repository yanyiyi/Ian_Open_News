# RSSHub 自架範本

RSSHub 把沒有 RSS 的網站（PTT、Dcard、巴哈姆特、噗浪等）轉成 feed。
本目錄提供兩條跑法，擇一即可；跑起來之後把 route URL 當一般 `rss` 來源加進
`database/sources.jsonl`，並加上出身欄位：

```jsonc
{
  "feed_url": "http://127.0.0.1:1200/ptt/hot",
  "source_type": "rss",            // 抓取路徑完全沿用既有 fetch_rss.py
  "served_via": "rsshub@local",    // 標記這條靠哪個 bridge
  "bridge": "ptt/hot",             // route 名，換主機時重組 feed_url 用
  "site_url": "https://www.ptt.cc/bbs/"
}
```

bridge 離線時 `fetch_rss.py` 會整組跳過並記 `bridge-unreachable`（不是逐筆
failed），`analyze_source_health.py` 會彙整成一行「bridge 整組離線」警報。
搬主機時用 `python3 scripts/rebuild_bridge_feeds.py --served-via rsshub@local
--base <新位址> --dry-run` 批次重組，不必手改。

## 路線 A：Docker（機器上有 Docker Desktop / OrbStack 時）

```bash
docker compose -f templates/rsshub/docker-compose.yml up -d
curl -s http://127.0.0.1:1200/healthz   # 應回 ok
```

## 路線 B：Node 源碼直跑（機器只有 Node、不想裝 Docker 時）

```bash
# 1. 取源碼（放在 repo 外，避免 node_modules 進版本庫；也避開 ~/Documents 的 TCC 限制）
git clone --depth 1 https://github.com/DIYgod/RSSHub.git ~/Apps/rsshub
cd ~/Apps/rsshub
npm i -g pnpm            # RSSHub 用 pnpm 管依賴
pnpm install --frozen-lockfile

# 2. 啟動（預設 port 1200；RSSHub 預設綁所有介面，務必用 LISTEN_INADDR_ANY=0 限制）
LISTEN_INADDR_ANY=0 PORT=1200 pnpm start

# 3. 驗證
curl -s http://127.0.0.1:1200/healthz
```

開機自動啟動：把 `com.ian-open-news.rsshub.plist` 複製到
`~/Library/LaunchAgents/` 並 `launchctl load`。plist 的 log 一律放
`~/Library/Logs/`——放 `~/Documents` 會被 macOS TCC 擋成 EX_CONFIG 78。

## 快取

Docker 路線已含 redis 快取。Node 直跑預設記憶體快取即可；來源多了再考慮
本機 redis（`CACHE_TYPE=redis REDIS_URL=redis://localhost:6379/`）。

## 注意

- 只綁 127.0.0.1：feed 只給本機 `fetch_rss.py` 抓，遠端一律走 Tailscale。
- Facebook route 需要 cookie 且常壞，不建議常駐依賴；FB 追蹤主線是找原站
  RSS 或 Google Alert（見 docs/facebook-inoreader-alternatives.md）。
