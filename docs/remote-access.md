# 遠端存取：手機分流、遠端看稿、遠端改稿

主線是 **Tailscale 直連本機 local_web**：零程式改動、寫回路徑不必重建、
不開 `--host 0.0.0.0`、不加 auth（tailnet 的裝置身分就是 auth）。
Google Sheets / Notion 不當工作介面（避免第二個寫 DB 入口）；
私人 Sheet 只能當單向唯讀鏡像（見 `scripts/export_mirror_sheet.py`，選配）。

## 一次性設定（Mac 端）

1. 安裝並登入 Tailscale：

   ```bash
   brew install --cask tailscale-app
   open -a Tailscale   # 登入你的帳號（Google/GitHub/Apple 皆可）
   ```

2. 把 local_web 發佈進 tailnet（只有你登入的裝置看得到，自帶 HTTPS）：

   ```bash
   tailscale serve --bg --https=443 http://127.0.0.1:8766
   tailscale serve status   # 會顯示 https://<機器名>.<tailnet>.ts.net
   ```

3. Mac 防睡眠（launchd 抓取本來就有此前提，非新成本）：
   系統設定 → 能源 → 接電時「防止自動進入睡眠」；
   或臨時用 `caffeinate -s`。

## 手機端（一次性）

1. 裝 Tailscale app、登入同一帳號。
2. Safari 開 `https://<機器名>.<tailnet>.ts.net/items`。
3. 「分享 → 加入主畫面」做成捷徑——之後通勤分流就是點這顆圖示。

## 各場景對應

| 場景 | 路徑 | Mac 睡著時的備援 |
| --- | --- | --- |
| 手機分流候選（最高頻） | tailnet → `/items`，用既有批次按鈕 | 無（等 Mac 醒；候選不會消失） |
| 看已收內容 / brief | tailnet → `/reader` | GitHub Pages reader（注意是公開站） |
| 改稿 / 寫 brief | tailnet → 文章編輯器 | github.dev / Codespaces 改 `knowledge/`，走既有 PR 流程 |
| 協作者投稿 | GitHub Issue Form（見 workflow 文件），`scripts/import_submissions.py` 匯入候選佇列 | 同左（不依賴你的 Mac） |

## 安全邊界

- local_web 仍只綁 `127.0.0.1:8766`；`tailscale serve` 是唯一入口，
  只有你 tailnet 內的裝置連得到。
- 不要改用 `--host 0.0.0.0`、不要用 Tailscale Funnel（那會公開到整個網際網路）。
- 手機上的分流動作與在 Mac 上按完全等價：同一套端點、同一把 DB 寫入鎖。

## 疑難排解

- 手機連不上：先確認兩端 Tailscale 都是連線狀態（app 顯示 Connected）。
- `tailscale serve` 掉了：重跑步驟 2 的指令（`--bg` 會常駐，重開機後仍在）。
- local_web 沒回應：Mac 端 `launchctl list | grep opennews` 確認 LaunchAgent 活著。
