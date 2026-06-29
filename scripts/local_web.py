#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import html
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import functools
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, unquote, urljoin, urlparse
import hashlib
from zoneinfo import ZoneInfo

from editorial_triage import build_editorial_context, evaluate_editorial_triage
from fetch_rss import evaluate_triage
from page_metadata import (
    attrs_from_tag,
    complete_item_metadata,
    enrich_item_metadata,
    fetch_page_metadata,
    infer_language_from_text,
    published_date_from_url,
    text_to_markdown,
    unwrap_google_alert_url,
)
from pdf_materials import (
    download_pdf as download_remote_pdf,
    extract_pdf_markdown,
    relationship_candidates as pdf_relationship_candidates,
    slugify as pdf_slugify,
)


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
SOURCES = DATABASE / "sources.jsonl"
ITEMS = DATABASE / "items.jsonl"
REJECTED_ITEMS = DATABASE / "rejected-items.jsonl"
REVIEW_EVENTS = DATABASE / "review-events.jsonl"
PUBLISHED_PAGES = DATABASE / "published-pages.jsonl"
TRIAGE_KEYWORDS = DATABASE / "triage-keywords.json"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
DISMISSED = ROOT / ".cache" / "rss-dismissed.jsonl"
RSS_FETCH_STATUS = ROOT / ".cache" / "rss-fetch-status.json"
DATA_COMMIT_STATUS = ROOT / ".cache" / "data-autocommit-status.json"
COMMAND_STATUS = ROOT / ".cache" / "command-status.json"
VIEWPOINTS = DATABASE / "viewpoints.jsonl"
MATERIAL_LINKS = DATABASE / "material-links.jsonl"
ARTICLES = DATABASE / "articles.jsonl"
EDITOR_SESSIONS = ROOT / ".cache" / "editor-sessions.jsonl"
EDITOR_STATUS = ROOT / ".cache" / "editor-status.json"
DECISION_DIVERGENCES = DATABASE / "decision-divergences.jsonl"
INSIGHT_REPORTS = DATABASE / "insight-reports.jsonl"
SYSTEM_CHANGE_PROPOSALS = DATABASE / "system-change-proposals.jsonl"
TASTE_PROFILE = DATABASE / "taste-profile.json"
CACHE_DIR = ROOT / ".cache"
INSIGHT_STATUS = ROOT / ".cache" / "insight-status.json"
PDF_SPLIT_STATUS = ROOT / ".cache" / "pdf-split-status.json"
TRANSLATE_STATUS = ROOT / ".cache" / "translate-status.json"
PDF_UPLOADS = ROOT / ".cache" / "uploads"
EDITOR_TASK_LABELS = {
    "theme-check": "選法檢查",
    "compose-thematic": "主題式撰稿",
    "compose-digest": "彙報式撰稿",
    "factcheck": "查核找原文",
    "extract-viewpoints": "萃取觀點",
    "newsletter-extract": "彙整萃取報告",
}
EDITOR_CHOICE_LABELS = {"thematic": "主題式", "digest": "彙報式"}
# 專文（article）＝只有編輯台產出、再經編修台順稿的稿件。狀態為 taxonomy.statuses 的子集。
ARTICLE_STATUSES = ("draft", "ready", "published")
ARTICLE_STATUS_LABELS = {"draft": "草稿", "ready": "待發布", "published": "已發布"}
DATA_AUTOCOMMIT_INTERVAL_SECONDS = 30 * 60
TAG_SUGGESTION_LIMIT = 12
CURRENT_READING_PRIORITY_DAYS = 2
AI_PROVIDER_META = {
    "codex": {
        "label": "Codex",
        "short": "Codex",
        "review_key": "codex_review",
        "translation_markdown_key": "codex_translated_article_markdown_zh",
        "translation_title_key": "codex_translated_zh_title",
        "translation_source_key": "codex_translation_source",
        "translation_generated_key": "codex_translation_generated_at",
        "translation_note_key": "codex_translation_note",
    },
    "claude": {
        "label": "Claude Code",
        "short": "Claude",
        "review_key": "claude_review",
        "translation_markdown_key": "claude_translated_article_markdown_zh",
        "translation_title_key": "claude_translated_zh_title",
        "translation_source_key": "claude_translation_source",
        "translation_generated_key": "claude_translation_generated_at",
        "translation_note_key": "claude_translation_note",
    },
    "gemini": {
        "label": "Gemini",
        "short": "Gemini",
        "review_key": "gemini_review",
        "translation_markdown_key": "gemini_translated_article_markdown_zh",
        "translation_title_key": "gemini_translated_zh_title",
        "translation_source_key": "gemini_translation_source",
        "translation_generated_key": "gemini_translation_generated_at",
        "translation_note_key": "gemini_translation_note",
    },
    "ollama": {
        "label": "Ollama CLI",
        "short": "Ollama",
        "review_key": "ollama_review",
        "translation_markdown_key": "ollama_translated_article_markdown_zh",
        "translation_title_key": "ollama_translated_zh_title",
        "translation_source_key": "ollama_translation_source",
        "translation_generated_key": "ollama_translation_generated_at",
        "translation_note_key": "ollama_translation_note",
    },
    "ollama-gemma4": {
        "label": "Ollama gemma4:12b MLX",
        "short": "Ollama gemma4",
        "review_key": "ollama_gemma4_review",
        "translation_markdown_key": "ollama_gemma4_translated_article_markdown_zh",
        "translation_title_key": "ollama_gemma4_translated_zh_title",
        "translation_source_key": "ollama_gemma4_translation_source",
        "translation_generated_key": "ollama_gemma4_translation_generated_at",
        "translation_note_key": "ollama_gemma4_translation_note",
        "model": "gemma4:12b-mlx",
    },
    "ollama-twinkle": {
        "label": "TwinkleAI:Gemma-3-4B-T1-IT",
        "short": "TwinkleAI:Gemma-3",
        "review_key": "ollama_twinkle_review",
        "translation_markdown_key": "ollama_twinkle_translated_article_markdown_zh",
        "translation_title_key": "ollama_twinkle_translated_zh_title",
        "translation_source_key": "ollama_twinkle_translation_source",
        "translation_generated_key": "ollama_twinkle_translation_generated_at",
        "translation_note_key": "ollama_twinkle_translation_note",
        "model": "TwinkleAI/gemma-3-4B-T1-it",
    },
}
AI_PROVIDER_ORDER = ["codex", "claude", "gemini", "ollama-gemma4", "ollama-twinkle"]
DEFAULT_OLLAMA_MODEL = "TwinkleAI/gemma-3-4B-T1-it"
OLLAMA_MODELS = {
    "ollama": DEFAULT_OLLAMA_MODEL,
    "ollama-gemma4": "gemma4:12b-mlx",
    "ollama-twinkle": "TwinkleAI/gemma-3-4B-T1-it",
}
# 標籤 taxonomy：每組 = (正式名, [可輸入的同義/別名])。
# 分面（facet）由 TAG_FACETS 標示；同一面下的每個 group 就是一個子類。
# 輸入任一別名都會正規化到正式名，且別名可被搜尋找到（help 找標籤）。
TAG_SYNONYM_GROUPS = [
    # —— 主題 · 開源核心 ——
    ("開放原始碼", ["開放原始碼", "開源", "OS", "open source", "opensource", "Open Source", "FOSS", "free software", "software freedom", "自由軟體"]),
    ("開源治理 / OSPO", ["開源治理", "OSPO", "開源政策", "open source policy", "open source program office", "開源專案辦公室"]),
    ("開放授權", ["開放授權", "開源授權", "授權", "license", "licence", "licensing", "CC", "Creative Commons", "創用CC"]),
    # —— 主題 · AI 系列 ——
    ("開源 AI / OSAID", ["開源 AI", "開源 AI 發展", "OSAID", "open source AI", "open-source AI", "AI 開放性", "開放模型", "open weights", "AI"]),
    ("AI Agents", ["AI Agents", "AI agent", "agentic"]),
    # —— 主題 · 開放資料／政府 ——
    ("開放資料", ["開放資料", "開放數據", "OD", "open data", "data portal", "資料開放", "開放資料知識"]),
    ("開放政府", ["開放政府", "OG", "open government", "civic tech", "公民科技"]),
    ("資料治理", ["資料治理", "數據治理", "data governance", "資料保護", "data protection", "DR"]),
    # —— 主題 · 數位權利 ——
    ("數位人權", ["數位人權", "digital rights", "human rights", "言論自由"]),
    ("數位隱私", ["數位隱私", "隱私", "隱私權", "privacy", "個資", "個人資料"]),
    ("資安 / 供應鏈", ["資安", "cybersecurity", "security", "供應鏈安全", "software supply chain", "supply chain", "SBOM"]),
    # —— 主題 · 公共數位基建／科技 ——
    ("公共程式 / 數位基建", ["公共程式", "public code", "public digital infrastructure", "公共數位基礎建設", "DPI"]),
    ("開放科技", ["開放科技", "open technology", "open tech", "開放標準", "open standard", "open standards"]),
    ("法規政策", ["法規政策", "臺灣法規", "法規", "行政規則", "法制化", "政策", "regulation", "policy", "compliance", "標準"]),
    # —— 主題 · 數位人文／在地 ——
    ("數位人文", ["數位人文", "digital humanities", "文化記憶", "cultural memory", "數位典藏", "digital archive", "記憶庫"]),
    ("在地知識 / 地方", ["在地知識", "地方知識", "地方", "社區", "鐵道"]),
    # —— 組織 ——
    ("OCF / 開放文化基金會", ["OCF", "開放文化基金會", "open culture foundation"]),
    ("FSF", ["FSF", "free software foundation"]),
    # —— 社群 / 活動 ——
    ("COSCUP", ["COSCUP"]),
    ("SITCON", ["SITCON"]),
]
# 分面：哪些 group 正式名屬於哪個分面（給建議分群用；其餘歸「其他」）。
TAG_FACETS = [
    ("主題", [
        "開放原始碼", "開源治理 / OSPO", "開放授權",
        "開源 AI / OSAID", "AI Agents",
        "開放資料", "開放政府", "資料治理",
        "數位人權", "數位隱私", "資安 / 供應鏈",
        "公共程式 / 數位基建", "開放科技", "法規政策",
        "數位人文", "在地知識 / 地方",
    ]),
    ("組織", ["OCF / 開放文化基金會", "FSF"]),
    ("社群 / 活動", ["COSCUP", "SITCON"]),
]

TRACKS = [
    ("digital-humanities-local-knowledge", "數位人文與在地知識建構"),
    ("open-tech-open-industry", "開放科技與開放產業發展"),
    ("unclassified", "未分類"),
]
TRACK_META = {
    "digital-humanities-local-knowledge": {
        "label": "數位人文與在地知識建構",
        "short": "人文與在地知識",
        "class": "humanities",
        "description": "地方知識、文化記憶、數位典藏、博物館、檔案與社群共筆。",
        "entry": "進入人文工作台",
    },
    "open-tech-open-industry": {
        "label": "開放科技與開放產業發展",
        "short": "開放科技",
        "class": "opentech",
        "description": "開源、開放資料、資料治理、標準、授權、公共數位基礎建設與開放產業。",
        "entry": "進入開放科技工作台",
    },
    "unclassified": {
        "label": "未分類",
        "short": "未分類",
        "class": "neutral",
        "description": "還沒決定要放進哪一條主線的來源與項目。",
        "entry": "查看未分類",
    },
}
TRACK_ORDER = ["open-tech-open-industry", "digital-humanities-local-knowledge", "unclassified"]
ONLINE_READER_BASE_URL = "https://technews.ospo.tw/reader"
LICENSE_UNSPECIFIED = "未明確標示"
LICENSE_NON_CC_PREFIX = "非 CC："
LICENSE_URLS = {
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-NC 4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
    "CC BY-NC-SA 4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "CC BY-ND 4.0": "https://creativecommons.org/licenses/by-nd/4.0/",
    "CC BY-NC-ND 4.0": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "CC BY 3.0 TW": "https://creativecommons.org/licenses/by/3.0/tw/",
    "CC BY-SA 3.0 TW": "https://creativecommons.org/licenses/by-sa/3.0/tw/",
    "CC BY-NC 3.0 TW": "https://creativecommons.org/licenses/by-nc/3.0/tw/",
    "CC BY-NC-SA 3.0 TW": "https://creativecommons.org/licenses/by-nc-sa/3.0/tw/",
    "CC BY-ND 3.0 TW": "https://creativecommons.org/licenses/by-nd/3.0/tw/",
    "CC BY-NC-ND 3.0 TW": "https://creativecommons.org/licenses/by-nc-nd/3.0/tw/",
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public Domain Mark 1.0": "https://creativecommons.org/publicdomain/mark/1.0/",
}
LOCAL_TIMEZONE = ZoneInfo("Asia/Taipei")
SOURCE_TYPES = ["rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor", "spreadsheet", "manual"]
SOURCE_STATUSES = ["active", "paused", "archived"]
FETCH_FREQUENCIES = ["hourly", "six-hourly", "daily", "weekly", "monthly", "on-update", "paused"]
NEW_SOURCE_GROUP_VALUE = "__new_source_group__"
SOURCE_TYPE_LABELS = {
    "rss": "RSS / 網站",
    "google-alert": "Google 快訊",
    "youtube": "YouTube",
    "podcast": "Podcast",
    "facebook": "Facebook",
    "inoreader-monitor": "Inoreader 關鍵字",
    "spreadsheet": "既有表格",
    "manual": "手動加入",
}
SOURCE_TYPE_HELP = {
    "rss": "一般網站或部落格 feed，可由本機或 GitHub Actions 自動抓。",
    "google-alert": "Google Alert 匯出的 feed，適合追關鍵字。",
    "youtube": "YouTube 頻道 feed，適合追影片發布。",
    "podcast": "Podcast feed，適合追音訊節目。",
    "facebook": "從 Inoreader 或舊流程留下的 Facebook 來源，通常不直接由 GitHub 抓。",
    "inoreader-monitor": "Inoreader 關鍵字監測來源，保留作為舊流程對照。",
    "spreadsheet": "從既有 Excel 跟追表匯入的來源。",
    "manual": "在本機網頁手動加入的來源。",
}
SOURCE_STATUS_LABELS = {
    "active": "啟用",
    "paused": "暫停",
    "archived": "封存",
}
FETCH_FREQUENCY_LABELS = {
    "hourly": "每 1 小時抓",
    "six-hourly": "每 6 小時抓",
    "daily": "每天抓",
    "weekly": "每週抓",
    "monthly": "每月抓",
    "on-update": "按更新時抓",
    "paused": "暫停抓取",
}
FETCH_FREQUENCY_ALIASES = {
    "1h": "hourly",
    "1-hour": "hourly",
    "hour": "hourly",
    "hourly": "hourly",
    "6h": "six-hourly",
    "6-hour": "six-hourly",
    "6-hourly": "six-hourly",
    "six-hour": "six-hourly",
    "six-hourly": "six-hourly",
    "six_hourly": "six-hourly",
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
    "manual": "on-update",
    "on-demand": "on-update",
    "on-update": "on-update",
    "on_update": "on-update",
    "paused": "paused",
}
COMMAND_ICONS = {
    "fetch_rss": "rss",
    "validate": "check-circle",
    "apply_triage_keywords": "filter",
    "analyze_source_health": "pulse",
    "export_sqlite": "database",
    "render_ghpages_reader": "publish",
    "enrich_reader_metadata": "image",
    "enrich_article_summaries": "text-lines",
    "codex_enrich_reviews": "sparkle",
    "git_status": "branch",
    "git_diff_stat": "chart",
    "commit_database_state": "save",
}
COMMAND_SHORTCUTS = {
    "fetch_rss": "R",
    "validate": "V",
    "apply_triage_keywords": "F",
    "analyze_source_health": "H",
    "export_sqlite": "D",
    "render_ghpages_reader": "P",
    "enrich_reader_metadata": "T",
    "enrich_article_summaries": "S",
    "codex_enrich_reviews": "C",
    "git_status": "G",
    "git_diff_stat": "I",
    "commit_database_state": "K",
}
DATA_AUTOCOMMIT_FILES = [
    ITEMS,
    REVIEW_EVENTS,
    SOURCES,
    PUBLISHED_PAGES,
    DECISION_DIVERGENCES,
    INSIGHT_REPORTS,
    SYSTEM_CHANGE_PROPOSALS,
    TASTE_PROFILE,
]
DATA_AUTOCOMMIT_LOCK = threading.Lock()
# 序列化資料庫的「讀取→修改→整檔覆寫」交易。ThreadingHTTPServer 會並發處理請求，
# 沒有這把鎖時，批次或快速連點的收件/分流會 lost-update：item 被另一執行緒的舊
# 快照覆寫掉，但 review-event 是 append 故倖存，留下對不到 item 的孤兒事件。
DB_WRITE_LOCK = threading.RLock()


def with_db_write_lock(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with DB_WRITE_LOCK:
            return func(*args, **kwargs)

    return wrapper
REJECTION_REASON_CATEGORIES = [
    "活動公告/宣傳",
    "純紀錄型資料",
    "資料太舊",
    "主線關聯弱",
    "社群內部消息",
    "重複/已涵蓋",
    "地緣脈絡非台資訊",
]
DEFAULT_REJECTION_REASONS = list(REJECTION_REASON_CATEGORIES)
MIN_REJECTION_REASON_OPTION_COUNT = 3
SOURCE_KEYWORD_EXCLUSION_REASON = "單一 RSS 專屬關鍵字排除"
GENERIC_NEWSLETTER_LINK_LABELS = {
    "read more",
    "learn more",
    "more",
    "here",
    "link",
    "source",
    "published",
    "report",
    "paper",
    "recent report",
    "閱讀更多",
    "更多",
}
NEWSLETTER_FUNCTIONAL_LINK_RE = re.compile(
    r"\b("
    r"subscribe|unsubscribe|preference|preferences|manage|opt[ -]?out|privacy|terms|login|sign[ -]?in|"
    r"register|registration|ticket|tickets|eventbrite|calendar|pretalx|cfp|call for proposals|submit|"
    r"application|applications are open|apply|vacancy|job|jobs|program manager|ambassador program|"
    r"course|training|academy|info session|symposium|conference"
    r")\b|訂閱|取消訂閱|偏好設定|報名|投稿|職缺|課程|訓練",
    re.I,
)
NEWSLETTER_ARTICLE_LINK_RE = re.compile(
    r"/("
    r"20\d{2}|news|blog|post|article|articles|publication|publications|press|press-releases|"
    r"research|report|reports|brief|paper|papers|study|studies|abs|pdf|"
    r"chapter|chapters|books|book"
    r")\b|\.pdf(?:$|[?#])|arxiv\.org/(?:abs|pdf)/|doi\.org/",
    re.I,
)
NEWSLETTER_ARTICLE_TITLE_RE = re.compile(
    r"\b(report|research|paper|study|brief|statement|news|article|launch|announc|governance|policy|"
    r"funding|security|open source|digital public infrastructure|commons|AI|DPI)\b"
    r"|^\d+[\.\)]\s+\S"  # numbered chapter: "3. The Internet..." or "10) Something"
    r"|^(Introduction|Conclusion|Preface|Foreword|Afterword|Epilogue)[:\s]",
    re.I | re.MULTILINE,
)
NOISY_TAG_VALUES = {
    "",
    "rss",
    "google-alert",
    "youtube",
    "podcast",
    "facebook",
    "spreadsheet",
    "manual",
    "inoreader-monitor",
    "manual rss",
    "manual web bookmark",
    "opentech rss",
    "monitoring feeds",
    "news",
    "featured",
    "site feedback",
    "support and help",
    "triage report",
    "rss / 網站",
    "admin",
    "blog",
    "collection",
    "data",
    "headlines",
    "home what's new",
    "people",
    "projects",
    "official statistics blog",
    "data value and use blog",
    "data financing blog",
    "guest posts",
    "partners and collaboration",
    "inside the library",
    "job announcements",
    "announcements",
    "editors' choice",
    "outreach and events",
    "publications and resources",
    "cfps & conferences",
    "dariah news slides",
    "new on loc.gov",
    "opentech rss",
    "coscup media",
    "coscup 年會",
    "coscup 開源人年會",
    "ocf 開放文化基金會",
    "新聞活動 (週更新)",
    "關鍵字（有就更新）",
    "開放資料知識  (有就更新)",
    "法規規範標準 (每月有特殊事件更新)",
    "中央機關二級機關平臺 相關公告（月更新）",
    "縣市政府文化局",
    "記憶庫過往執行單位",
    "既有單位",
    "記憶庫追蹤",
    "os",
    "od",
    "og",
    "dr",
    "api",
    "ai",
}
REJECTION_REASON_ALIASES = {
    "內容偏活動公告或宣傳，暫不整理。": "活動公告/宣傳",
    "活動公告": "活動公告/宣傳",
    "宣傳": "活動公告/宣傳",
    "記憶庫純紀錄型資料": "純紀錄型資料",
    "只是短訊或碎片，不足以形成文章。": "純紀錄型資料",
    "其他類型文章": "純紀錄型資料",
    "資料太舊": "資料太舊",
    "資訊過舊或缺少可查證來源。": "資料太舊",
    "已經是建議不要看": "主線關聯弱",
    "和兩條主線關聯太弱。": "主線關聯弱",
    "和 OCF 關心的開放科技議題發展關係不大": "主線關聯弱",
    "和 ocf 關心的開放科技議題發展關係不大": "主線關聯弱",
    SOURCE_KEYWORD_EXCLUSION_REASON: "主線關聯弱",
    "社群內部消息，無關": "社群內部消息",
    "社群內部消息": "社群內部消息",
    "來源重複，已由其他資料涵蓋。": "重複/已涵蓋",
    "重複": "重複/已涵蓋",
    "已涵蓋": "重複/已涵蓋",
    "廣告": "活動公告/宣傳",
    "廣告宣傳": "活動公告/宣傳",
    "促銷廣告": "活動公告/宣傳",
    "徵才文": "活動公告/宣傳",
    "中國訊息": "地緣脈絡非台資訊",
    "中國資料": "地緣脈絡非台資訊",
    "地緣脈絡非台資訊": "地緣脈絡非台資訊",
}

COMMANDS = {
    "fetch_rss": {
        "label": "立刻抓 RSS 候選",
        "description": "先抓到入庫建檔區，不直接寫進正式資料庫；手動按鈕也會包含「按更新時抓」的來源，抓完接著隨機用 Codex、Claude Code、Gemini 或 Ollama 補閱讀建議、三個理由與中文摘要。",
        "button": "抓到入庫建檔區",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "local_rss_daily.py"),
            "--manual",
        ],
    },
    "validate": {
        "label": "驗證資料庫",
        "description": "檢查 JSONL 欄位、主線分類、來源關聯是否正確。送 PR 前先按這個。",
        "button": "檢查資料有沒有壞",
        "command": [sys.executable, str(ROOT / "scripts" / "validate_database.py")],
    },
    "apply_triage_keywords": {
        "label": "重新跑本機規則/關鍵字初篩",
        "description": "把目前入庫建檔區重新套用關鍵字、過去不收紀錄與過去收錄類型。這是本機規則判斷，不是 Codex 生成摘要。",
        "button": "更新初篩建議",
        "command": [sys.executable, str(ROOT / "scripts" / "apply_triage_keywords.py")],
    },
    "analyze_source_health": {
        "label": "更新 RSS 來源健康評估",
        "description": "彙整近期收下、不收、候選與 RSS 抓取結果，替每個來源建議抓取頻率、是否暫停或重設個別關鍵字。適合兩週跑一次。",
        "button": "更新來源健康評估",
        "command": [sys.executable, str(ROOT / "scripts" / "analyze_source_health.py")],
    },
    "export_sqlite": {
        "label": "匯出 SQLite",
        "description": "把 JSONL 正本轉成 .cache/knowledge.sqlite，方便用資料庫工具查詢。",
        "button": "做一份查詢用資料庫",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "export_sqlite.py"),
            "--output",
            str(ROOT / ".cache" / "knowledge.sqlite"),
        ],
    },
    "render_ghpages_reader": {
        "label": "產生 GitHub Pages 閱讀版",
        "description": "輸出 docs/reader/index.html（開放科技主線的精選文章、小消息與觀點文章），以及狀態為「已發布」的專文（features.html）；完成後會直接送一個線上版 commit。",
        "button": "更新線上閱讀版",
        "command": [sys.executable, str(ROOT / "scripts" / "render_ghpages_reader.py")],
    },
    "enrich_reader_metadata": {
        "label": "補閱讀卡圖片、描述與主文",
        "description": "連到閱讀區文章的原始網址，補齊缺少的封面圖、描述與可抽取主文；優先處理從未抓過與最久未抓的項目，失敗或仍缺資料時 7 天後才重試。",
        "button": "補閱讀區資料",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "enrich_reading_metadata.py"),
            "--reader-only",
            "--only-missing-reader-data",
            "--retry-after-days",
            "7",
            "--limit",
            "40",
            "--status-file",
            str(COMMAND_STATUS),
        ],
    },
    "enrich_article_summaries": {
        "label": "用本機規則重抓待整理摘要",
        "description": "連到待整理中建議收的原始網址，抓正文後用本機規則重寫摘要與 3 點閱讀理由。這不是 Codex 生成；真正 Codex 生成會在單篇中標為「來源：Codex」。",
        "button": "用規則重寫摘要",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "enrich_article_summaries.py"),
            "--status",
            "inbox",
            "--recommendation",
            "suggest-keep",
            "--workers",
            "8",
            "--timeout",
            "8",
        ],
    },
    "codex_enrich_reviews": {
        "label": "隨機補 AI 閱讀建議與摘要",
        "description": "針對入庫建檔區與閱讀區中還沒有任何模型 review 的項目，逐筆加權隨機挑一個 CLI 產生給 Ian 的一句話推薦、三個閱讀理由、中文標題與中文摘要；右下角會顯示目前做到第幾筆與項目標題。",
        "button": "隨機補 AI 建議",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "codex_enrich_reviews.py"),
            "--provider",
            "random",
            "--target",
            "both",
            "--workflow-scope",
            "--limit",
            "18",
            "--batch-size",
            "1",
            "--status-file",
            str(COMMAND_STATUS),
            "--status-command",
            "codex_enrich_reviews",
        ],
        "timeout": 3600,
    },
    "commit_database_state": {
        "label": "送 commit 儲存資料庫狀態",
        "description": "只把 database/items.jsonl、database/review-events.jsonl、database/sources.jsonl 目前變更送成一個自訂紀錄 commit；背景每 30 分鐘也會自動檢查一次。",
        "button": "送 commit 儲存狀態",
        "internal": "commit_database_state",
    },
    "git_status": {
        "label": "查看檔案變更",
        "description": "列出目前哪些檔案被新增或修改，方便確認接下來要不要開 PR。",
        "button": "看有哪些檔案變了",
        "command": ["git", "status", "--short"],
    },
    "git_diff_stat": {
        "label": "查看變更摘要",
        "description": "只看每個檔案改了多少行，不展開完整內容。",
        "button": "看每個檔案改多少",
        "command": ["git", "diff", "--stat"],
    },
}


def stable_id(prefix: str, *parts: object) -> str:
    raw = "||".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def clean_text(value: object, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def clean_markdown_text(value: object, limit: int | None = None) -> str:
    """Normalize stored Markdown without collapsing user-authored line breaks."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold() if "}" in tag else tag.casefold()


def fetchable_http_url(value: object) -> str:
    url = clean_text(value)
    return url if url.startswith(("http://", "https://")) else ""


def host_label(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    return host or url


def source_add_href(feed_url: str, track: str, name: str = "", site_url: str = "") -> str:
    params = {
        "track": track if track in TRACK_META else "digital-humanities-local-knowledge",
        "source_type": "rss",
        "source_group": "Manual RSS",
        "feed_url": feed_url,
        "site_url": site_url,
        "name": name or host_label(feed_url),
    }
    return "/sources/new?" + urlencode(params)


def read_preview_document(url: str, timeout: int = 8, max_bytes: int = 900_000) -> tuple[str, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "IanOpenNewsBot/1.0 preview (+local web form)",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml,application/atom+xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
        raw = response.read(max_bytes)
    return final_url, content_type, raw


def decode_preview_text(raw: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([\w.-]+)", content_type, flags=re.I)
    charset = charset_match.group(1) if charset_match else "utf-8"
    return raw.decode(charset, errors="replace")


def feed_metadata_from_xml(raw: bytes, final_url: str) -> dict:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    root_name = local_name(root.tag)
    if root_name == "rss":
        channel = next((child for child in list(root) if local_name(child.tag) == "channel"), None)
        if channel is None:
            return {}
        title = clean_text(next((child.text for child in list(channel) if local_name(child.tag) == "title"), ""), 220)
        site_url = clean_text(next((child.text for child in list(channel) if local_name(child.tag) == "link"), ""))
        description = clean_text(next((child.text for child in list(channel) if local_name(child.tag) == "description"), ""), 500)
        entry_count = sum(1 for child in list(channel) if local_name(child.tag) == "item")
        return {
            "is_feed": True,
            "feed_type": "RSS",
            "feed_title": title,
            "site_url": site_url,
            "description": description,
            "entry_count": entry_count,
            "final_url": final_url,
        }
    if root_name == "feed":
        title = clean_text(next((child.text for child in list(root) if local_name(child.tag) == "title"), ""), 220)
        site_url = ""
        for child in list(root):
            if local_name(child.tag) != "link":
                continue
            attrs = {str(key).casefold(): str(value) for key, value in child.attrib.items()}
            rel = attrs.get("rel", "alternate").casefold()
            if rel == "alternate" and attrs.get("href"):
                site_url = urljoin(final_url, attrs["href"])
                break
        entry_count = sum(1 for child in list(root) if local_name(child.tag) == "entry")
        return {
            "is_feed": True,
            "feed_type": "Atom",
            "feed_title": title,
            "site_url": site_url,
            "description": "",
            "entry_count": entry_count,
            "final_url": final_url,
        }
    return {}


def discover_feed_links(html_text: str, final_url: str) -> list[dict]:
    feeds: list[dict] = []
    seen: set[str] = set()

    def add_feed(href: str, title: str, source: str, feed_type: str = "") -> None:
        feed_url = urljoin(final_url, html.unescape(href).strip())
        if not feed_url.startswith(("http://", "https://")):
            return
        key = feed_url.rstrip("/")
        if key in seen:
            return
        seen.add(key)
        feeds.append(
            {
                "url": feed_url,
                "title": clean_text(title, 160) or "RSS / Atom feed",
                "type": clean_text(feed_type, 60) or "RSS / Atom",
                "source": source,
            }
        )

    for match in re.finditer(r"<link\b[^>]*>", html_text, flags=re.I | re.S):
        attrs = attrs_from_tag(match.group(0))
        rel = attrs.get("rel", "").casefold()
        feed_type = attrs.get("type", "")
        feed_type_lower = feed_type.casefold()
        title = attrs.get("title") or attrs.get("href") or "RSS / Atom feed"
        if "alternate" not in rel.split() or not attrs.get("href"):
            continue
        if any(token in feed_type_lower for token in ["rss", "atom", "xml"]) or re.search(r"\b(rss|atom|feed)\b", title, flags=re.I):
            add_feed(attrs["href"], title, "page-link", feed_type)

    for match in re.finditer(r"(?is)<a\b([^>]*)>(.*?)</a>", html_text):
        attrs = attrs_from_tag(match.group(1))
        href = attrs.get("href", "")
        label = clean_text(match.group(2), 160)
        if not href or not re.search(r"\b(rss|atom|feed)\b|訂閱|摘要", f"{href} {label}", flags=re.I):
            continue
        add_feed(href, label or href, "page-anchor")
        if len(feeds) >= 8:
            break
    return feeds[:8]


TRACK_AUTOFILL_CANDIDATES = ["open-tech-open-industry", "digital-humanities-local-knowledge"]


def metadata_source_name(metadata: dict, url: str) -> str:
    site_name = clean_text(metadata.get("site_name"), 160).lstrip("@")
    return site_name or host_label(clean_text(metadata.get("final_url") or metadata.get("canonical_url") or url))


def metadata_site_url(metadata: dict, url: str) -> str:
    candidate = clean_text(metadata.get("canonical_url") or metadata.get("final_url") or url)
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return candidate


def manual_track_score(triage: dict, editorial: dict) -> int:
    score = {
        "suggest-keep": 6,
        "suggest-ask": 4,
        "suggest-skip": 0,
    }.get(clean_text(triage.get("recommendation")), 0)
    score += len(triage.get("matched_keywords") or []) * 2
    score += len(triage.get("mechanism_keywords") or [])
    score -= len(triage.get("skip_keywords") or []) * 3
    score += {
        "suggest-collect": 8,
        "suggest-review": 6,
        "suggest-ask": 5,
        "suggest-skip": 0,
    }.get(clean_text(editorial.get("recommendation")), 0)
    for key in ["keyword_fit", "prior_collection_fit", "taste_fit"]:
        fit = editorial.get(key) if isinstance(editorial.get(key), dict) else {}
        score += int(fit.get("score") or 0)
    deletion = editorial.get("deletion_pattern_fit") if isinstance(editorial.get("deletion_pattern_fit"), dict) else {}
    score -= int(deletion.get("score") or 0)
    return score


def infer_manual_item_track(
    record: dict,
    keyword_config: dict,
    editorial_context: dict,
    fallback_track: str,
) -> tuple[str, str, list[dict]]:
    fallback_track = fallback_track if fallback_track in TRACK_META else "unclassified"
    choices = []
    for track in TRACK_AUTOFILL_CANDIDATES:
        candidate = {**record, "track": track}
        triage = evaluate_triage(candidate, keyword_config)
        candidate["triage"] = triage
        editorial = evaluate_editorial_triage(candidate, keyword_config, editorial_context)
        choices.append(
            {
                "track": track,
                "score": manual_track_score(triage, editorial),
                "triage": triage,
                "editorial_triage": editorial,
            }
        )
    if not choices:
        return fallback_track, "", []
    best = max(choices, key=lambda choice: (choice["score"], -TRACK_AUTOFILL_CANDIDATES.index(choice["track"])))
    fallback_choice = next((choice for choice in choices if choice["track"] == fallback_track), None)
    fallback_score = int(fallback_choice.get("score") or 0) if fallback_choice else 0
    suggested = best["track"] if best["score"] > 0 and best["score"] > fallback_score else fallback_track
    suggested_choice = next((choice for choice in choices if choice["track"] == suggested), best)
    triage = suggested_choice.get("triage") or {}
    editorial = suggested_choice.get("editorial_triage") or {}
    matched = [clean_text(keyword) for keyword in triage.get("matched_keywords") or [] if clean_text(keyword)]
    taste = editorial.get("taste_fit") if isinstance(editorial.get("taste_fit"), dict) else {}
    taste_signals = [clean_text(signal) for signal in taste.get("signals") or [] if clean_text(signal)]
    reason = "、".join(matched[:4]) or (taste_signals[0] if taste_signals else "")
    return suggested, reason, choices


def manual_item_published_date(metadata: dict, url: str) -> tuple[str, str, str]:
    """Return date, source, confidence without inventing dates from capture time."""
    metadata = metadata if isinstance(metadata, dict) else {}
    published = clean_text(metadata.get("published_at"), 40)
    source = clean_text(metadata.get("published_at_source"), 80)
    if published:
        confidence = "medium" if source.casefold() == "url path" else "high"
        return published, source or "metadata", confidence
    url_date = published_date_from_url(url)
    if url_date:
        return url_date, "URL path", "medium"
    return "", "", ""


CONTEXT_SKIP_PATTERNS = (
    "accept cookies",
    "cookie policy",
    "sign up",
    "subscribe",
    "all rights reserved",
    "newsletter",
)


def context_excerpt(value: object, limit: int = 520) -> str:
    text = clean_text(value, 2400)
    if not text:
        return ""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    chunks = []
    for chunk in re.split(r"\n{2,}", text):
        chunk = clean_text(chunk.strip(" -*>\t"), 900)
        if len(chunk) < 32:
            continue
        lower = chunk.casefold()
        if any(pattern in lower for pattern in CONTEXT_SKIP_PATTERNS):
            continue
        chunks.append(chunk)
    if not chunks:
        chunks = [clean_text(text, 900)]
    sentences = re.split(r"(?<=[。！？.!?])\s+", chunks[0])
    excerpt = " ".join(sentence.strip() for sentence in sentences[:2] if sentence.strip())
    return clean_text(excerpt or chunks[0], limit)


def manual_item_summary(record: dict, metadata: dict) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    candidates = [
        record.get("summary"),
        metadata.get("description"),
        metadata.get("excerpt"),
        metadata.get("og_description"),
        metadata.get("twitter_description"),
    ]
    for candidate in candidates:
        excerpt = context_excerpt(candidate)
        if excerpt and not looks_like_triage_placeholder(excerpt):
            return excerpt
    for candidate in [metadata.get("article_markdown"), metadata.get("article_text")]:
        excerpt = context_excerpt(candidate)
        if excerpt and not looks_like_triage_placeholder(excerpt):
            return excerpt
    title = clean_text(record.get("title"), 300)
    source_name = clean_text(record.get("source_name"), 120)
    if title and source_name:
        return clean_text(f"{source_name} 這篇提到：{title}", 520)
    if title:
        return clean_text(f"標題線索：{title}", 520)
    return ""


def manual_item_notes(record: dict) -> str:
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    existing = clean_text(review.get("notes"), 1000)
    if existing:
        return existing
    triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    lines: list[str] = []

    summary_reason = workflow_display_text(editorial.get("summary_reason"), 240)
    if summary_reason:
        lines.append(f"初步值得追：{summary_reason}")
    content_kind = clean_text(editorial.get("content_kind_label"), 80)
    if content_kind:
        lines.append(f"可能形式：{content_kind}")
    matched = [
        clean_text(keyword, 60)
        for keyword in [*(triage.get("matched_keywords") or []), *(triage.get("mechanism_keywords") or [])]
        if clean_text(keyword)
    ]
    if matched:
        lines.append("命中線索：" + "、".join(matched[:5]))
    view_reasons = [
        workflow_display_text(reason, 220)
        for reason in editorial.get("view_reasons") or []
        if workflow_display_text(reason, 220)
    ]
    for reason in view_reasons[:2]:
        if reason not in lines:
            lines.append(f"判斷理由：{reason}")
    next_step = workflow_display_text(editorial.get("next_step_hint"), 180)
    if next_step:
        lines.append(f"下一步：{next_step}")
    if not lines and clean_text(record.get("title")):
        lines.append(f"先收著觀察：{clean_text(record.get('title'), 220)}")
    return clean_text("\n".join(lines), 1000)


def apply_manual_item_autofill(
    record: dict,
    metadata: dict,
    existing_items: list[dict],
    keyword_config: dict,
    editorial_context: dict,
    *,
    metadata_error: str = "",
    add_tags: bool = True,
) -> dict:
    updated = dict(record)
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    reference = dict(updated.get("reference") if isinstance(updated.get("reference"), dict) else {})
    reference.setdefault("created_by", "local_web")
    reference.setdefault("created_from", "manual-url")
    if metadata_error:
        reference["metadata_fetch_error"] = clean_text(metadata_error, 500)
    updated["reference"] = reference

    title = clean_text(updated.get("title"), 300)
    url = clean_text(updated.get("url"))
    page_title = clean_text(metadata.get("title") or metadata.get("original_site_title"), 300)
    if page_title and (not title or title == url):
        updated["title"] = page_title
    if not clean_text(updated.get("summary")):
        updated["summary"] = manual_item_summary(updated, metadata)
    published_at, published_at_source, published_at_confidence = manual_item_published_date(metadata, url)
    if not clean_text(updated.get("published_at")) and published_at:
        updated["published_at"] = published_at
    if published_at_source:
        reference["published_at_source"] = published_at_source
        reference["published_at_confidence"] = published_at_confidence
    if metadata.get("image_url") and not clean_text(updated.get("image_url")):
        updated["image_url"] = clean_text(metadata.get("image_url"))
    source_name = clean_text(updated.get("source_name"), 160)
    if not source_name or source_name == "Manual bookmark":
        updated["source_name"] = metadata_source_name(metadata, url) or "Manual bookmark"
    author = clean_text(updated.get("author"), 240)
    if not author or author == "Manual bookmark":
        updated["author"] = clean_text(metadata.get("original_author"), 240) or clean_text(updated.get("source_name"), 240)

    updated["triage"] = evaluate_triage(updated, keyword_config)
    updated["editorial_triage"] = evaluate_editorial_triage(updated, keyword_config, editorial_context)
    review = dict(updated.get("review") if isinstance(updated.get("review"), dict) else default_review())
    if not clean_text(review.get("notes")):
        note = manual_item_notes(updated)
        if note:
            review["notes"] = note
    updated["review"] = review
    if add_tags and not item_tags(updated):
        suggested_tags = suggested_item_tags(updated, existing_items, limit=8)
        if suggested_tags:
            updated["tags"] = suggested_tags
            tag_metadata = dict(updated.get("tag_metadata") if isinstance(updated.get("tag_metadata"), dict) else {})
            updated["tag_metadata"] = {
                **tag_metadata,
                "source": "local_web",
                "autofill_source": "manual-url",
                "updated_at": clean_text(updated.get("captured_at")) or now_iso(),
            }
    elif item_tags(updated):
        tag_metadata = dict(updated.get("tag_metadata") if isinstance(updated.get("tag_metadata"), dict) else {})
        updated["tag_metadata"] = {**tag_metadata, "source": "local_web", "updated_at": clean_text(updated.get("captured_at")) or now_iso()}
    return updated


def build_url_preview(url: str, track: str, title: str = "") -> dict:
    original_url = clean_text(url)
    url = fetchable_http_url(unwrap_google_alert_url(original_url))
    if not url:
        return {"ok": False, "error": "請填入 http 或 https 開頭的網址。"}

    sources = load_jsonl(SOURCES)
    existing_feeds = {clean_text(source.get("feed_url")).rstrip("/") for source in sources if source.get("feed_url")}
    metadata: dict = {}
    metadata_error = ""
    try:
        metadata = fetch_page_metadata(url, timeout=8)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
        metadata_error = str(exc)

    final_url = clean_text(metadata.get("final_url") or url)
    content_type = ""
    raw = b""
    document_error = ""
    try:
        final_url, content_type, raw = read_preview_document(url, timeout=8)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
        document_error = str(exc)

    feed_info = feed_metadata_from_xml(raw, final_url) if raw else {}
    html_text = decode_preview_text(raw, content_type) if raw else ""
    feed_suggestions = [] if feed_info else discover_feed_links(html_text, final_url)
    if feed_info:
        title = feed_info.get("feed_title") or metadata.get("title") or host_label(final_url)
        feed_suggestions = [
            {
                "url": final_url,
                "title": title,
                "type": feed_info.get("feed_type") or "RSS / Atom",
                "source": "current-url",
            }
        ]

    enriched_feeds = []
    for feed in feed_suggestions:
        feed_url = clean_text(feed.get("url"))
        key = feed_url.rstrip("/")
        feed_title = clean_text(feed.get("title"), 160) or clean_text(metadata.get("title"), 160) or host_label(feed_url)
        site_url = clean_text(feed_info.get("site_url") if feed_info else final_url)
        enriched_feeds.append(
            {
                **feed,
                "url": feed_url,
                "title": feed_title,
                "exists": key in existing_feeds,
                "add_url": source_add_href(feed_url, track, feed_title, site_url),
            }
        )

    title = clean_text(metadata.get("title") or feed_info.get("feed_title") or title, 300)
    description = clean_text(metadata.get("description") or feed_info.get("description") or metadata.get("excerpt"), 900)
    canonical = clean_text(metadata.get("canonical_url"))
    site_url = clean_text(feed_info.get("site_url") or canonical or final_url)
    published_at, published_at_source, published_at_confidence = manual_item_published_date(metadata, final_url or url)
    keyword_config = load_json(TRIAGE_KEYWORDS) or {"version": 1, "tracks": {}}
    existing_items = load_jsonl(ITEMS)
    editorial_context = build_editorial_context([*existing_items, *load_jsonl(REJECTED_ITEMS)], keyword_config)
    seed_record = {
        "title": title or clean_text(title, 300) or host_label(final_url),
        "url": url,
        "source_name": metadata_source_name(metadata, final_url),
        "author": clean_text(metadata.get("original_author"), 240),
        "published_at": published_at,
        "summary": description,
        "tags": [],
        "origin": "manual-web",
    }
    suggested_track, track_reason, track_choices = infer_manual_item_track(seed_record, keyword_config, editorial_context, track)
    preview_record = {
        **seed_record,
        "track": suggested_track if suggested_track in TRACK_META else track,
        "status": "inbox",
        "priority": "normal",
        "captured_at": now_iso(),
        "reference": {"created_by": "local_web", "created_from": "manual-url-preview"},
    }
    preview_record = apply_manual_item_autofill(
        preview_record,
        metadata,
        existing_items,
        keyword_config,
        editorial_context,
        metadata_error=metadata_error,
    )
    return {
        "ok": True,
        "url": url,
        "original_url": original_url,
        "unwrapped_url": url if url != original_url else "",
        "final_url": final_url,
        "content_type": content_type or metadata.get("content_type", ""),
        "title": title,
        "description": description,
        "excerpt": clean_text(metadata.get("excerpt"), 900),
        "image_url": clean_text(metadata.get("image_url")),
        "canonical_url": canonical,
        "source_name": metadata_source_name(metadata, final_url),
        "site_name": clean_text(metadata.get("site_name"), 160),
        "author": clean_text(metadata.get("original_author"), 240),
        "published_at": clean_text(preview_record.get("published_at") or published_at, 40),
        "published_at_source": published_at_source,
        "published_at_confidence": published_at_confidence,
        "original_language": clean_text(metadata.get("original_language"), 80),
        "is_feed": bool(feed_info),
        "feed_title": clean_text(feed_info.get("feed_title"), 220),
        "feed_type": clean_text(feed_info.get("feed_type")),
        "entry_count": feed_info.get("entry_count", 0),
        "site_url": site_url,
        "feed_suggestions": enriched_feeds,
        "suggested_track": suggested_track,
        "suggested_track_label": track_meta(suggested_track)["short"] if suggested_track in TRACK_META else "",
        "track_reason": track_reason,
        "track_choices": [
            {"track": choice["track"], "score": choice["score"], "label": track_meta(choice["track"])["short"]}
            for choice in track_choices
            if choice["track"] in TRACK_META
        ],
        "suggested_summary": clean_text(preview_record.get("summary"), 900),
        "suggested_notes": clean_text((preview_record.get("review") or {}).get("notes"), 1000),
        "suggested_tags": item_tags(preview_record)[:8],
        "triage": preview_record.get("triage") or {},
        "editorial_triage": preview_record.get("editorial_triage") or {},
        "metadata_error": metadata_error,
        "document_error": document_error,
    }


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"warning: skip invalid JSONL {path}:{line_number}: {exc}", file=sys.stderr)
    return records


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_status_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    with DB_WRITE_LOCK:  # 避免並發寫入交錯把檔案寫壞
        path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with DB_WRITE_LOCK:  # 避免並發 append 與整檔覆寫交錯
        needs_newline = path.exists() and path.stat().st_size > 0
        if needs_newline:
            with path.open("rb") as handle:
                handle.seek(-1, 2)
                needs_newline = handle.read(1) != b"\n"
        with path.open("a", encoding="utf-8") as handle:
            if needs_newline:
                handle.write("\n")
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def upsert_jsonl(path: Path, record: dict) -> None:
    record_id = record.get("id")
    if not record_id:
        append_jsonl(path, record)
        return
    records = load_jsonl(path)
    updated = []
    replaced = False
    for existing in records:
        if existing.get("id") == record_id:
            updated.append(record)
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(record)
    write_jsonl(path, updated)


def remove_jsonl_ids(path: Path, record_ids: set[str]) -> int:
    if not record_ids or not path.exists():
        return 0
    records = load_jsonl(path)
    kept_records = [record for record in records if str(record.get("id") or "") not in record_ids]
    removed = len(records) - len(kept_records)
    if removed:
        write_jsonl(path, kept_records)
    return removed


def database_integrity_report() -> dict:
    """掃出 validate_database.py 會擋下、且能在本機一鍵決斷的兩類問題：
    1) 同一筆 id 同時在可用材料區(items)與已退件(rejected) 2) 指向不存在項目的孤兒審查事件。"""
    items = load_jsonl(ITEMS)
    rejected = load_jsonl(REJECTED_ITEMS)
    reviews = load_jsonl(REVIEW_EVENTS)
    item_by_id = {clean_text(r.get("id")): r for r in items if r.get("id")}
    rejected_by_id = {clean_text(r.get("id")): r for r in rejected if r.get("id")}
    item_ids = set(item_by_id)
    rejected_ids = set(rejected_by_id)

    issues: list[dict] = []
    for item_id in sorted(item_ids & rejected_ids):
        active = item_by_id.get(item_id, {})
        archived = rejected_by_id.get(item_id, {})
        decision = archived.get("local_decision") if isinstance(archived.get("local_decision"), dict) else {}
        issues.append(
            {
                "type": "duplicate_item",
                "id": item_id,
                "title": clean_text(active.get("title") or archived.get("title")) or item_id,
                "track": track_label(clean_text(active.get("track") or archived.get("track"))),
                "detail": "這筆同時出現在『可用材料區』和『已退件』，資料庫不允許同一筆 id 兩邊都在。",
                "rejected_reason": clean_text(decision.get("reason")),
                "rejected_at": clean_text(decision.get("decided_at")),
                # 已有明確退件決定 → 預設尊重退件；否則預設留為可用材料。
                "recommended": "keep_rejected" if decision.get("action") == "rejected" else "keep_active",
            }
        )

    for review in reviews:
        referenced = clean_text(review.get("item_id"))
        if not referenced or referenced == "manual-seed":
            continue
        if referenced in item_ids or referenced in rejected_ids:
            continue
        issues.append(
            {
                "type": "orphan_review",
                "id": clean_text(review.get("id")),
                "item_id": referenced,
                "step": clean_text(review.get("step")),
                "reviewer": clean_text(review.get("reviewer")),
                "created_at": clean_text(review.get("created_at")),
                "notes": clean_text(review.get("notes"), 120),
                "detail": f"這筆審查事件指向的項目 {referenced} 已經不在資料庫（可能被刪或改過 id），形成孤兒紀錄。",
                "recommended": "drop_event",
            }
        )

    return {"ok": not issues, "issues": issues, "count": len(issues)}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_time_label(dt: datetime | None = None) -> str:
    current = dt.astimezone(LOCAL_TIMEZONE) if dt else datetime.now(LOCAL_TIMEZONE)
    return f"{current.month:02d} 月 {current.day:02d} 日 {current.hour:02d} 時 {current.minute:02d} 分 {current.second:02d} 秒"


def data_commit_message(dt: datetime | None = None) -> str:
    return f"閱讀資料庫自訂紀錄 {local_time_label(dt)} 的更新"


# ------------------------------------------------------------------ #
# 決策分歧洞察（/insights）
# ------------------------------------------------------------------ #

def _divergence_id() -> str:
    import secrets
    return "div-" + secrets.token_hex(4)


def _report_id() -> str:
    import secrets
    return "rpt-" + secrets.token_hex(4)


def _ai_suggestion_from_item(item: dict) -> dict | None:
    """從 item 萃取 AI 建議；優先用 editorial_triage，次用 triage；兩者皆無回 None。"""
    et = item.get("editorial_triage")
    if isinstance(et, dict) and et.get("recommendation"):
        return {
            "source": "editorial_triage",
            "recommendation": et.get("recommendation", ""),
            "content_kind": et.get("content_kind", ""),
            "confidence": et.get("confidence", ""),
        }
    triage = item.get("triage")
    if isinstance(triage, dict) and triage.get("recommendation"):
        return {
            "source": "triage",
            "recommendation": triage.get("recommendation", ""),
            "content_kind": "",
            "confidence": "",
        }
    return None


def _user_action_from_item(item: dict) -> str:
    decision = item.get("local_decision")
    if isinstance(decision, dict):
        return decision.get("action", "")
    return ""


def _is_collect_action(action: str) -> bool:
    return action in {"accepted-for-editing", "direct-pr-small-news", "want-to-read", "accepted-current-reading"}


def _is_reject_action(action: str) -> bool:
    return action in {"rejected"}


def _detect_divergence_type(ai_rec: str, user_action: str) -> str | None:
    """回傳分歧類型字串，或 None 表示沒有分歧。"""
    if ai_rec in {"suggest-skip", "suggest-reject"} and _is_collect_action(user_action):
        return "under-collected"
    if ai_rec in {"suggest-collect", "suggest-keep"} and _is_reject_action(user_action):
        return "over-rejected"
    return None


def _existing_divergence_item_ids() -> set[str]:
    existing = load_jsonl(DECISION_DIVERGENCES)
    ids: set[str] = set()
    for div in existing:
        for iid in (div.get("item_ids") or []):
            ids.add(iid)
    return ids


def _divergence_record_from_item(item: dict, div_type: str, ai_sug: dict, user_action: str) -> dict:
    return {
        "id": _divergence_id(),
        "divergence_type": div_type,
        "item_ids": [item.get("id", "")],
        "item_titles": [item.get("title", "（無標題）")],
        "track": item.get("track", ""),
        "logged_at": now_iso(),
        "ai_suggestion": ai_sug,
        "user_action": user_action,
        "cluster_size": 1,
        "user_explanation": "",
        "dismissed": False,
        "included_in_analysis_at": None,
    }


def sample_divergences_into_cue(limit: int = 5) -> int:
    """從 items + rejected-items 中找出尚未記錄的分歧，隨機抽 limit 筆寫入待填清單。回傳新增筆數。"""
    import random
    existing_item_ids = _existing_divergence_item_ids()
    pool: list[dict] = []
    for item in load_jsonl(ITEMS) + load_jsonl(REJECTED_ITEMS):
        item_id = item.get("id", "")
        if not item_id or item_id in existing_item_ids:
            continue
        ai_sug = _ai_suggestion_from_item(item)
        if ai_sug is None:
            continue
        user_action = _user_action_from_item(item)
        if not user_action:
            continue
        div_type = _detect_divergence_type(ai_sug["recommendation"], user_action)
        if div_type is None:
            continue
        pool.append(_divergence_record_from_item(item, div_type, ai_sug, user_action))

    random.shuffle(pool)
    chosen = pool[:limit]
    for record in chosen:
        append_jsonl(DECISION_DIVERGENCES, record)
    return len(chosen)


def detect_and_log_divergence(item: dict) -> None:
    """在 accept/reject 後呼叫，若有新分歧即寫入（單筆，under/over 皆可）。"""
    item_id = item.get("id", "")
    if not item_id:
        return
    if item_id in _existing_divergence_item_ids():
        return

    ai_sug = _ai_suggestion_from_item(item)
    if ai_sug is None:
        return
    user_action = _user_action_from_item(item)
    if not user_action:
        return
    div_type = _detect_divergence_type(ai_sug["recommendation"], user_action)
    if div_type is None:
        return

    append_jsonl(DECISION_DIVERGENCES, _divergence_record_from_item(item, div_type, ai_sug, user_action))


def _patch_divergence(div_id: str, **kwargs: object) -> bool:
    """更新 decision-divergences.jsonl 中指定 id 的欄位。"""
    records = load_jsonl(DECISION_DIVERGENCES)
    found = False
    updated = []
    for rec in records:
        if rec.get("id") == div_id:
            rec = dict(rec)
            rec.update(kwargs)
            found = True
        updated.append(rec)
    if found:
        write_jsonl(DECISION_DIVERGENCES, updated)
    return found


_BEAT_RE = re.compile(
    r"beat|關注|追蹤|長期追|會關心|我關心|追的|持續關注|想追|想要追|這是我的|我的關鍵|我追的",
    re.IGNORECASE,
)


def _maybe_add_personal_beat(div_id: str, explanation: str) -> None:
    """若說明包含 beat/追蹤類詞語，把說明萃取成個人 beat 加進 taste-profile.json。"""
    if not explanation or not _BEAT_RE.search(explanation):
        return
    beat_text = explanation.strip()
    profile = load_taste_profile()
    beats = profile.setdefault("personal_beats", [])
    if any(b.get("beat") == beat_text for b in beats):
        return
    beats.append({"beat": beat_text, "source_div": div_id, "added_at": now_iso()})
    profile["updated_at"] = now_iso()
    write_json(TASTE_PROFILE, profile)


def _patch_report(rpt_id: str, **kwargs: object) -> bool:
    """更新 insight-reports.jsonl 中指定 id 的欄位。"""
    records = load_jsonl(INSIGHT_REPORTS)
    found = False
    updated = []
    for rec in records:
        if rec.get("id") == rpt_id:
            rec = dict(rec)
            rec.update(kwargs)
            found = True
        updated.append(rec)
    if found:
        write_jsonl(INSIGHT_REPORTS, updated)
    return found


def _has_pending_proposals_for_divergence(div_id: str, reports: list[dict], proposals: list[dict]) -> bool:
    """一筆 divergence 是否有尚未結案（pending/evaluating）的關聯提案。"""
    rpt_ids = {r["id"] for r in reports if div_id in r.get("divergence_ids", [])}
    if not rpt_ids:
        return False
    return any(
        p.get("status") in ("pending", "evaluating")
        for p in proposals if p.get("source_report") in rpt_ids
    )


def _prior_decisions_brief(max_signals: int = 12, max_kw_sample: int = 15, max_props: int = 20) -> str:
    """精簡彙整既有決策（品味主題、最近訊號、關鍵字現況、既有提案），供分析/套用 prompt 比對，
    避免重複或牴觸。控制量避免 prompt 過肥。"""
    lines = [
        "## 既有決策（請勿重複、勿牴觸）",
        "下面是系統已內化的偏好與已提的建議。產生新建議時：",
        "- 不要重複已存在的關鍵字、主題、訊號或提案；",
        "- 若新建議與既有決策衝突，請明講衝突點與你建議的取捨，不要悄悄覆蓋。",
        "",
    ]
    taste = load_taste_profile()
    g = taste.get("global") or {}
    if g.get("emphasize"):
        lines.append("全域強調：" + "、".join(g["emphasize"]))
    if g.get("de_emphasize"):
        lines.append("全域淡化：" + "、".join(g["de_emphasize"]))
    for track, info in (taste.get("tracks") or {}).items():
        short = track_meta(track)["short"]
        if info.get("priority_themes"):
            lines.append(f"{short} 偏好主題：" + "、".join(info["priority_themes"]))
        if info.get("avoid_themes"):
            lines.append(f"{short} 避開主題：" + "、".join(info["avoid_themes"]))
    sigs = taste.get("learned_signals") or []
    if sigs:
        lines.append("")
        lines.append(f"最近學到的訊號（共 {len(sigs)} 條，列最近 {min(len(sigs), max_signals)} 條）：")
        for s in sigs[-max_signals:]:
            lines.append(f"- {clean_text(s.get('signal'))}")
    kw = load_json(TRIAGE_KEYWORDS)
    lines.append("")
    for track, meta in (kw.get("tracks") or {}).items():
        short = track_meta(track)["short"]
        keep = meta.get("keep_keywords") or []
        skip = meta.get("skip_keywords") or []
        mech = meta.get("mechanism_keywords") or []
        lines.append(
            f"{short} 關鍵字現況：keep {len(keep)}、skip {len(skip)}、mechanism {len(mech)} 條。"
            f" keep 最近樣本：{'、'.join(keep[-max_kw_sample:])}"
        )
    props = load_jsonl(SYSTEM_CHANGE_PROPOSALS)
    if props:
        lines.append("")
        lines.append(f"既有程式調整提案（共 {len(props)} 筆，勿重複；列最近 {min(len(props), max_props)} 筆）：")
        for p in props[-max_props:]:
            lines.append(f"- [{p.get('status','pending')}] {clean_text(p.get('title'))}")
    return "\n".join(lines)


def _build_analysis_prompt(divergences: list[dict]) -> str:
    lines = ["你是台灣數位人文與開放科技媒體 Ian Open News 的 AI 建議顧問。",
             "以下是使用者最近做出的、和系統建議相反的決策，請分析並給出條列式的洞察報告。",
             "",
             "## 分歧清單",
             ""]
    for i, div in enumerate(divergences, 1):
        titles = "、".join(div.get("item_titles") or ["（未知）"])
        ai_rec = (div.get("ai_suggestion") or {}).get("recommendation", "未知")
        user_act = div.get("user_action", "未知")
        exp = div.get("user_explanation", "")
        dt = div.get("divergence_type", "")
        lines.append(f"{i}. [{dt}] 《{titles}》")
        lines.append(f"   AI 建議：{ai_rec} → 使用者選擇：{user_act}")
        if exp:
            lines.append(f"   使用者說明：{exp}")
        lines.append("")
    lines.append(_prior_decisions_brief())
    lines.append("")
    lines += [
        "## 請回傳（繁體中文，條列式）",
        "",
        "### 我沒掌握到的決策模式",
        "（每條附具體例子，說明你為何推薦那樣但使用者不這樣選）",
        "",
        "### over-rejected 分析",
        "（這些 AI 強推但使用者拒收的項目，有什麼共通特徵？下次應改為『先問使用者』而非直接推薦？）",
        "",
        "### 使用者偏好關鍵字",
        "（從使用者說明透露出的偏好，列 3-6 個關鍵詞）",
        "",
        "### 建議系統調整",
        "（具體說：遇到 X 情境時，AI 建議邏輯應調整為 Y）",
    ]
    return "\n".join(lines)


def _insights_nav_badge() -> str:
    divs = load_jsonl(DECISION_DIVERGENCES)
    pending = [d for d in divs if not d.get("dismissed") and not d.get("user_explanation")]
    count = len(pending)
    if count == 0:
        return ""
    cls = " style='background:#e53e3e'" if count >= 10 else ""
    return f" <span style='display:inline-block;background:#6450dc;color:#fff;border-radius:9px;padding:0 6px;font-size:0.75em;line-height:1.5;vertical-align:middle'{cls}>{count}</span>"


def insight_status(state: str, message: str, **extra: object) -> None:
    """寫入 /insights 的進度狀態檔，供右下角狀態列輪詢。"""
    write_status_json(INSIGHT_STATUS, {
        "state": state, "message": message, "updated_at": now_iso(), **extra,
    })


def _insight_cli_run(engine: str, prompt: str, status_label: str, timeout: int = 600,
                     allow_write: bool = False) -> tuple[str, str]:
    """呼叫指定 CLI，邊跑邊更新狀態列的「已等待 N 秒」。回傳 (text, error)。
    allow_write=False 用唯讀沙箱（分析）；True 允許寫檔（目前僅 codex 支援沙箱寫）。"""
    import subprocess
    import threading as _th

    cli = editor_cli_path("agy" if engine == "gemini" else engine)
    if not cli:
        return "", f"找不到 {engine} CLI（未安裝或不在 PATH）"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if engine == "codex":
        out_path = CACHE_DIR / "insight-codex-out.txt"
        sandbox = "workspace-write" if allow_write else "read-only"
        cmd = [cli, "-a", "never", "exec", "--ephemeral", "--cd", str(ROOT),
               "--sandbox", sandbox, "--color", "never",
               "--output-last-message", str(out_path), "-"]
        stdin_data = prompt
    elif engine == "claude":
        cmd = [cli, "-p", prompt, "--output-format", "json"]
        stdin_data = None
    elif engine.startswith("ollama"):
        cmd = [cli, "run", ollama_model(engine), "--nowordwrap", "--hidethinking"]
        stdin_data = prompt
    else:  # gemini → agy
        cmd = [cli, "--print", prompt]
        stdin_data = None

    started = now_iso()
    proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE if stdin_data else None,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    done = {"flag": False}

    def ticker() -> None:
        n = 0
        while not done["flag"]:
            insight_status("running", f"{status_label}…（已等待 {n} 秒）", started_at=started, engine=engine)
            n += 2
            _wait_event(2)

    t = _th.Thread(target=ticker, daemon=True)
    t.start()
    try:
        stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        done["flag"] = True
        return "", "CLI 執行逾時"
    finally:
        done["flag"] = True

    if proc.returncode != 0:
        return "", (stderr or stdout or f"exit {proc.returncode}")[-2000:]

    if engine == "codex":
        out_path = CACHE_DIR / "insight-codex-out.txt"
        text = out_path.read_text(encoding="utf-8") if out_path.exists() else stdout
        return text.strip(), ""
    if engine == "claude":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout.strip(), ""
        if payload.get("is_error"):
            return "", str(payload.get("result", "claude error"))
        return str(payload.get("result") or "").strip(), ""
    return stdout.strip(), ""


def _wait_event(seconds: float) -> None:
    import time
    time.sleep(seconds)


def run_analysis_job(divergences: list[dict], mode: str, engine: str = "claude") -> dict:
    """背景執行：請 CLI 分析分歧，邊跑邊更新狀態列，寫入報告。回傳 report dict。"""
    import time

    engine_label = ai_provider_label(engine)
    div_ids = [d.get("id", "") for d in divergences]
    insight_status("running", f"正在整理 {len(divergences)} 筆分歧資料…", engine=engine)
    prompt = _build_analysis_prompt(divergences)

    report_text, err = _insight_cli_run(engine, prompt, f"正在請 {engine_label} 分析你的決策模式", timeout=300)
    if err and not report_text:
        report_text = f"（{engine_label} 分析失敗：{err}）"

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    report_file = CACHE_DIR / f"divergence-analysis-{timestamp}.txt"
    report_file.write_text(report_text, encoding="utf-8")
    summary = "\n".join(report_text.splitlines()[:2])

    rpt = {
        "id": _report_id(),
        "generated_at": now_iso(),
        "mode": mode,
        "engine": engine,
        "divergence_ids": div_ids,
        "report_file": str(report_file.relative_to(ROOT)),
        "report_summary": summary,
        "implementation_status": "pending",
        "implemented_at": None,
        "implementation_notes": "",
        "report_text": report_text,
    }
    append_jsonl(INSIGHT_REPORTS, rpt)

    ts = now_iso()
    for div_id in div_ids:
        _patch_divergence(div_id, included_in_analysis_at=ts)

    if err and not report_text.strip().strip("（）"):
        insight_status("failed", f"分析失敗：{err}", report_id=rpt["id"])
    else:
        insight_status("done", f"分析完成（{engine_label}）。", report_id=rpt["id"], redirect="/insights")
    return rpt


# ------------------------------------------------------------------ #
# 個人品味設定檔
# ------------------------------------------------------------------ #

def _default_taste_profile() -> dict:
    return {"version": 1, "global": {}, "tracks": {}, "learned_signals": []}


def load_taste_profile() -> dict:
    """讀 taste-profile.json，缺檔回安全預設（不影響計分）。"""
    if not TASTE_PROFILE.exists():
        return _default_taste_profile()
    data = load_json(TASTE_PROFILE)
    if not isinstance(data, dict):
        return _default_taste_profile()
    data.setdefault("global", {})
    data.setdefault("tracks", {})
    data.setdefault("learned_signals", [])
    return data


def taste_profile_summary_lines() -> list[str]:
    """供 prompt 注入與畫面摘要共用的條列。"""
    profile = load_taste_profile()
    lines: list[str] = []
    g = profile.get("global") or {}
    if g.get("emphasize"):
        lines.append("優先重視：" + "、".join(g["emphasize"]))
    if g.get("de_emphasize"):
        lines.append("要警惕/淡化：" + "、".join(g["de_emphasize"]))
    if g.get("taiwan_context_required"):
        lines.append("台灣切角為必要條件")
    for track, meta in (profile.get("tracks") or {}).items():
        prio = (meta or {}).get("priority_themes") or []
        avoid = (meta or {}).get("avoid_themes") or []
        if prio:
            lines.append(f"[{track}] 偏好主題：" + "、".join(prio))
        if avoid:
            lines.append(f"[{track}] 避開主題：" + "、".join(avoid))
    for sig in (profile.get("learned_signals") or []):
        if isinstance(sig, dict) and sig.get("signal"):
            lines.append("已學到：" + sig["signal"])
    return lines


# ------------------------------------------------------------------ #
# 程式調整提案
# ------------------------------------------------------------------ #

def _proposal_id() -> str:
    import secrets
    return "prop-" + secrets.token_hex(4)


# CLI 輸出中標記「需要改程式本體」的固定段落標題
CODE_PROPOSAL_HEADING = "需要改程式本體（後續評估）"


def extract_code_proposals(report_text: str, source_report: str) -> list[dict]:
    """從 CLI 輸出擷取固定段落下的條列，轉成提案 record。擷取不到回空清單。"""
    if CODE_PROPOSAL_HEADING not in report_text:
        return []
    section = report_text.split(CODE_PROPOSAL_HEADING, 1)[1]
    proposals: list[dict] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 遇到下一個 markdown 標題就停
        if line.startswith("#"):
            break
        # 接受 -、*、數字. 開頭的條列
        cleaned = re.sub(r"^([-*]|\d+[.)])\s+", "", line)
        if cleaned == line and not line.startswith(("-", "*")):
            continue
        if not cleaned:
            continue
        proposals.append({
            "id": _proposal_id(),
            "proposed_at": now_iso(),
            "source_report": source_report,
            "title": cleaned[:200],
            "rationale": "",
            "target_area": "",
            "status": "pending",
            "notes": "",
        })
    return proposals


INSIGHT_REPO_CONTEXT = (
    "## 專案背景（Ian Open News，本機 repo）\n"
    "- 收件 triage 判斷在 `scripts/editorial_triage.py`：`evaluate_editorial_triage()` 算 "
    "keyword_fit / prior_collection_fit / deletion_pattern_fit / taste_fit 四個分數，決定 "
    "suggest-collect / suggest-review / suggest-skip。\n"
    "- 全域保留/排除關鍵字在 `database/triage-keywords.json`；個人品味在 `database/taste-profile.json`。\n"
    "- RSS 抓取與初判在 `scripts/fetch_rss.py`；本機網頁在 `scripts/local_web.py`。\n"
    "- 正本是 `database/*.jsonl`（一筆一行）。改完請跑 `python3 scripts/validate_database.py` 確認格式。\n"
)


def divergence_cases_for_report(rpt: dict) -> list[dict]:
    """依報告 divergence_ids 的順序，取出當時分析的分歧案例（含使用者解釋）。
    順序與報告內「案例 N」編號一致，方便 rationale 的『案例3』對得回來。"""
    ids = rpt.get("divergence_ids") or []
    by_id = {d.get("id"): d for d in load_jsonl(DECISION_DIVERGENCES)}
    cases = []
    for div_id in ids:
        d = by_id.get(div_id)
        if not d:
            continue
        ai = d.get("ai_suggestion") or {}
        cases.append({
            "titles": d.get("item_titles") or [],
            "type": d.get("divergence_type", ""),
            "ai": ai.get("recommendation", ""),
            "user_action": d.get("user_action", ""),
            "confidence": ai.get("confidence", ""),
            "explanation": d.get("user_explanation", ""),
        })
    return cases


def _format_cases_block(cases: list[dict]) -> str:
    if not cases:
        return ""
    lines = ["## 觸發這次調整的實際分歧案例（編號對應報告中的「案例 N」）\n"]
    for i, c in enumerate(cases, 1):
        title = "；".join(c.get("titles") or []) or "（無標題）"
        lines.append(f"案例 {i}：《{title}》")
        lines.append(f"  AI 判斷：{c.get('ai','')} → 你實際：{c.get('user_action','')}"
                     + (f"（信心度 {c.get('confidence')}）" if c.get("confidence") else ""))
        if c.get("explanation"):
            lines.append(f"  你的理由：{c['explanation']}")
    return "\n".join(lines) + "\n"


def build_proposal_prompt(prop: dict) -> str:
    """生成可貼進 AI CLI 的提案 prompt。格式：卡片摘要 + 案例 + 背景 + 指示。"""
    cases = prop.get("source_divergences") or []
    title = prop.get("title", "")
    target = prop.get("target_area", "") or "（待確認）"
    rationale = prop.get("rationale", "") or "（無說明）"
    engine = prop.get("source_engine", "") or "手動"
    at = (prop.get("proposed_at", "") or "")[:16]
    rpt_id = prop.get("source_report", "") or ""

    lines = [
        f"提案：{title}",
        f"目標：{target}",
        f"紀錄：{engine} · {at} · 來源報告 {rpt_id}",
        f"理由：{rationale}",
        "",
    ]
    if cases:
        lines.append(f"對應的 {len(cases)} 筆分歧案例")
        lines.append("")
        for i, c in enumerate(cases, 1):
            t = "；".join(c.get("titles") or []) or "（無標題）"
            conf = f"（信心度 {c['confidence']}）" if c.get("confidence") else ""
            lines.append(f"案例 {i}：《{t}》")
            lines.append(f"AI: {c.get('ai','')} → 你: {c.get('user_action','')}{conf}")
            if c.get("explanation"):
                lines.append(f"你的理由：{c['explanation']}")
            lines.append("")
    lines += [
        "---",
        "【Ian Open News 專案背景】",
        "- 收件 triage：scripts/editorial_triage.py，evaluate_editorial_triage() 算四個分數，決定 suggest-collect/review/skip。",
        "- 全域關鍵字：database/triage-keywords.json；品味設定：database/taste-profile.json。",
        "- 正本是 database/*.jsonl（一筆一行）。",
        "",
        "【實作指示】",
        "1. 先讀相關檔案，對照上面的案例，提出最小、可回退的改動方案。",
        "2. 實作後說明改了什麼、附 diff，並說明上面案例下次會如何被正確處理。",
        "3. 確保 `python3 scripts/validate_database.py` 通過，避免影響既有 triage 行為。",
    ]
    return "\n".join(lines)


def render_apply_change_details(details: list) -> str:
    """把 apply_runs 的結構化明細渲染成可點列點，連到 /keywords#track-X、/sources#source-Y、品味檔。"""
    if not details:
        return ""
    rows = []
    for d in details or []:
        t = d.get("type")
        scope = h(d.get("scope", ""))
        added = d.get("added") or []
        removed = d.get("removed") or []
        if t == "proposal":
            body = f"新增提案：{h(d.get('title',''))}" + (f"（{h(d.get('target_area',''))}）" if d.get("target_area") else "")
            rows.append(f"<li>{body}</li>")
            continue
        if t == "keyword":
            link = f'<a href="/keywords#track-{quote(clean_text(d.get("track")))}" target="_blank">調整這條 ↗</a>'
        elif t == "source":
            link = f'<a href="/sources#source-{quote(clean_text(d.get("source_id")))}" target="_blank">看這個來源 ↗</a>'
        elif t in ("taste", "signal"):
            link = '<a href="/insights/edit-taste-profile" target="_blank">看品味檔 ↗</a>'
        else:
            link = ""
        if t == "source":
            sets = d.get("set") or {}
            setstr = "、".join(f"{h(k)}→{h(str(v))}" for k, v in sets.items())
            rows.append(f"<li><strong>{scope}</strong>：{setstr} {link}</li>")
            continue
        parts = []
        if added:
            parts.append("＋ " + "、".join(h(x) for x in added))
        if removed:
            parts.append("－ " + "、".join(h(x) for x in removed))
        rows.append(f"<li><strong>{scope}</strong>：{' ／ '.join(parts)} {link}</li>")
    return ('<div class="apply-details"><div class="apply-details-title">本次具體調整（非程式部分）</div><ul>'
            + "".join(rows) + "</ul></div>")


def build_report_prompt(rpt: dict) -> str:
    return (
        "你正在 Ian Open News 專案。下面是一份「決策分歧分析報告」，請依其中建議調整系統，"
        "讓收件 triage 更貼近我的實際取捨（重點是減少誤刪）。\n\n"
        f"{INSIGHT_REPO_CONTEXT}\n"
        "## 請這樣做\n"
        "1. 能用設定表達的（關鍵字、品味主題）改 `database/triage-keywords.json` 或 `database/taste-profile.json`。\n"
        "2. 需要改判斷邏輯的，動 `scripts/editorial_triage.py`，提出最小改動。\n"
        "3. 說明改了什麼、附 diff，並跑 `python3 scripts/validate_database.py`。\n\n"
        "## 分析報告全文\n\n"
        f"{rpt.get('report_text','')}\n"
    )


def _patch_proposal(prop_id: str, **kwargs: object) -> bool:
    records = load_jsonl(SYSTEM_CHANGE_PROPOSALS)
    found = False
    updated = []
    for rec in records:
        if rec.get("id") == prop_id:
            rec = dict(rec)
            rec.update(kwargs)
            found = True
        updated.append(rec)
    if found:
        write_jsonl(SYSTEM_CHANGE_PROPOSALS, updated)
    return found


# 套用時可被結構化 patch 直接編輯的資料庫檔（其餘需改程式的進提案）
APPLY_EDITABLE_FILES = [TASTE_PROFILE, TRIAGE_KEYWORDS, SOURCES]


def _build_apply_prompt(report: dict) -> str:
    report_text = report.get("report_text", "")
    rpt_id = report.get("id", "")
    taste = load_taste_profile()
    keywords = load_json(TRIAGE_KEYWORDS)
    # 給 CLI 精簡的來源清單（名稱/track/狀態/頻率），方便它指名要調整哪個 RSS
    sources_brief = [
        {"id": s.get("id", ""), "name": s.get("name", ""), "track": s.get("track", ""),
         "status": s.get("status", ""), "fetch_frequency": s.get("fetch_frequency", "")}
        for s in load_jsonl(SOURCES)
    ]
    context = {
        "taste_profile": taste,
        "triage_keywords": {t: {"keep_keywords": (m or {}).get("keep_keywords", []),
                                "skip_keywords": (m or {}).get("skip_keywords", [])}
                            for t, m in (keywords.get("tracks") or {}).items()},
        "sources": sources_brief,
    }
    return (
        "你是 Ian Open News 本機系統的設定維護助理。下面有一份「決策分歧分析報告」與目前的設定狀態。\n"
        "請判斷該如何調整系統設定，讓系統下次更貼近使用者的實際取捨，特別是減少誤刪。\n\n"
        "你可以直接調整的「結構化設定」（請用回傳 JSON 表達，不要自己改檔）：\n"
        "1. taste_profile：個人品味（偏好/避開主題、強調/淡化、學到的訊號）。\n"
        "2. triage_keywords：每條 track 的全域保留關鍵字 keep 與排除關鍵字 skip。\n"
        "3. sources：單一 RSS 來源的 status / fetch_frequency / track / notes 調整。\n\n"
        f"凡是上述三者都表達不了、真的要改程式邏輯（計分公式、流程、新欄位）的，放進 code_proposals。\n\n"
        "## 只回傳這個 JSON（不要多餘文字、不要 markdown 圍欄）\n"
        "{\n"
        '  "summary": "一句話說明你做了哪些調整與理由",\n'
        '  "taste_profile": {"global": {"emphasize_add": [], "emphasize_remove": [], "de_emphasize_add": [], "de_emphasize_remove": []},\n'
        '                     "tracks": {"<track>": {"priority_add": [], "priority_remove": [], "avoid_add": [], "avoid_remove": []}},\n'
        '                     "learned_signals_add": ["..."]},\n'
        '  "triage_keywords": {"<track>": {"keep_add": [], "keep_remove": [], "skip_add": [], "skip_remove": []}},\n'
        '  "sources": [{"match": "<來源 id 或名稱關鍵字>", "set": {"status": "paused", "fetch_frequency": "daily", "notes": "..."}}],\n'
        '  "code_proposals": [{"title": "...", "target_area": "scripts/xxx.py", "rationale": "..."}]\n'
        "}\n"
        "空的欄位給空陣列即可。track 名稱請用既有的（open-tech-open-industry / digital-humanities-local-knowledge）。\n\n"
        f"## 報告 id\n{rpt_id}\n\n"
        "## 目前設定狀態（JSON）\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        f"{_prior_decisions_brief()}\n\n"
        "## 分析報告全文\n\n"
        f"{report_text}\n"
    )


def _extract_json_object(text: str) -> dict | None:
    """從 CLI 文字輸出中盡量取出第一個 JSON 物件。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _apply_list_patch(current: list, add: list, remove: list) -> list:
    """add 不重複地接在後面，remove 從清單移除。回傳新清單。"""
    result = list(current)
    remove_set = {str(x) for x in (remove or [])}
    result = [x for x in result if str(x) not in remove_set]
    for x in (add or []):
        if x not in result:
            result.append(x)
    return result


def apply_structured_patch(patch: dict, report: dict, engine: str = "") -> dict:
    """把 CLI 回傳的結構化 patch 套用到 taste-profile / triage-keywords / sources。
    回傳套用摘要 dict。"""
    source_report = report.get("id", "")
    cases = divergence_cases_for_report(report)
    # details：逐條人類可讀的具體調整，供 /insights 報告列點 + 深連到 /keywords#track-X、/sources#source-Y
    details: list[dict] = []
    changes: dict[str, object] = {"taste": False, "keywords": 0, "sources": 0, "proposals": 0, "details": details}

    def _delta(old: list, new: list) -> tuple[list, list]:
        old_set, new_set = set(old or []), set(new or [])
        return [x for x in new if x not in old_set], [x for x in old if x not in new_set]

    # 1. taste-profile
    tp = patch.get("taste_profile") or {}
    if tp:
        profile = load_taste_profile()
        g = profile.setdefault("global", {})
        gp = tp.get("global") or {}
        old_emph, old_de = list(g.get("emphasize", [])), list(g.get("de_emphasize", []))
        g["emphasize"] = _apply_list_patch(g.get("emphasize", []), gp.get("emphasize_add"), gp.get("emphasize_remove"))
        g["de_emphasize"] = _apply_list_patch(g.get("de_emphasize", []), gp.get("de_emphasize_add"), gp.get("de_emphasize_remove"))
        e_add, e_rm = _delta(old_emph, g["emphasize"])
        d_add, d_rm = _delta(old_de, g["de_emphasize"])
        if e_add or e_rm:
            details.append({"type": "taste", "scope": "全域 · 強調", "added": e_add, "removed": e_rm})
        if d_add or d_rm:
            details.append({"type": "taste", "scope": "全域 · 淡化", "added": d_add, "removed": d_rm})
        for track, tmeta in (tp.get("tracks") or {}).items():
            tracks = profile.setdefault("tracks", {})
            tinfo = tracks.setdefault(track, {})
            old_pri, old_avoid = list(tinfo.get("priority_themes", [])), list(tinfo.get("avoid_themes", []))
            tinfo["priority_themes"] = _apply_list_patch(tinfo.get("priority_themes", []), tmeta.get("priority_add"), tmeta.get("priority_remove"))
            tinfo["avoid_themes"] = _apply_list_patch(tinfo.get("avoid_themes", []), tmeta.get("avoid_add"), tmeta.get("avoid_remove"))
            p_add, p_rm = _delta(old_pri, tinfo["priority_themes"])
            a_add, a_rm = _delta(old_avoid, tinfo["avoid_themes"])
            if p_add or p_rm:
                details.append({"type": "taste", "scope": f"{track_meta(track)['short']} · 偏好主題", "added": p_add, "removed": p_rm})
            if a_add or a_rm:
                details.append({"type": "taste", "scope": f"{track_meta(track)['short']} · 避開主題", "added": a_add, "removed": a_rm})
        sig_add = [s for s in (tp.get("learned_signals_add") or []) if s]
        for sig in sig_add:
            profile.setdefault("learned_signals", []).append(
                {"signal": sig, "source_report": source_report, "added_at": now_iso()})
        if sig_add:
            details.append({"type": "signal", "scope": "學到的訊號", "added": sig_add, "removed": []})
        profile["updated_at"] = now_iso()
        write_json(TASTE_PROFILE, profile)
        changes["taste"] = True

    # 2. triage-keywords
    kw_patch = patch.get("triage_keywords") or {}
    if kw_patch:
        keywords = load_json(TRIAGE_KEYWORDS)
        tracks = keywords.setdefault("tracks", {})
        touched = 0
        for track, kp in kw_patch.items():
            meta = tracks.get(track)
            if not isinstance(meta, dict):
                continue
            old_keep, old_skip = list(meta.get("keep_keywords", [])), list(meta.get("skip_keywords", []))
            new_keep = _apply_list_patch(meta.get("keep_keywords", []), kp.get("keep_add"), kp.get("keep_remove"))
            new_skip = _apply_list_patch(meta.get("skip_keywords", []), kp.get("skip_add"), kp.get("skip_remove"))
            if new_keep != old_keep or new_skip != old_skip:
                meta["keep_keywords"] = new_keep
                meta["skip_keywords"] = new_skip
                touched += 1
                k_add, k_rm = _delta(old_keep, new_keep)
                s_add, s_rm = _delta(old_skip, new_skip)
                if k_add or k_rm:
                    details.append({"type": "keyword", "track": track, "scope": f"{track_meta(track)['short']} · 收錄關鍵字(keep)", "added": k_add, "removed": k_rm})
                if s_add or s_rm:
                    details.append({"type": "keyword", "track": track, "scope": f"{track_meta(track)['short']} · 排除關鍵字(skip)", "added": s_add, "removed": s_rm})
        if touched:
            write_json(TRIAGE_KEYWORDS, keywords)
        changes["keywords"] = touched

    # 3. sources（白名單欄位）
    src_patches = patch.get("sources") or []
    if src_patches:
        sources = load_jsonl(SOURCES)
        allowed = {"status", "fetch_frequency", "track", "notes"}
        touched = 0
        for sp in src_patches:
            match = str(sp.get("match", "")).strip()
            sets = {k: v for k, v in (sp.get("set") or {}).items() if k in allowed}
            if not match or not sets:
                continue
            for s in sources:
                if s.get("id") == match or (match and match in str(s.get("name", ""))):
                    s.update(sets)
                    touched += 1
                    details.append({"type": "source", "source_id": clean_text(s.get("id")),
                                    "scope": f"來源《{clean_text(s.get('name')) or clean_text(s.get('id'))}》",
                                    "set": sets})
                    break
        if touched:
            write_jsonl(SOURCES, sources)
        changes["sources"] = touched

    # 4. code_proposals
    for prop in (patch.get("code_proposals") or []):
        if not prop.get("title"):
            continue
        new_pid = _proposal_id()
        append_jsonl(SYSTEM_CHANGE_PROPOSALS, {
            "id": new_pid,
            "proposed_at": now_iso(),
            "source_report": source_report,
            "source_engine": engine,
            "source_divergences": cases,
            "title": str(prop.get("title", ""))[:200],
            "rationale": str(prop.get("rationale", "")),
            "target_area": str(prop.get("target_area", "")),
            "status": "pending",
            "notes": "",
        })
        changes["proposals"] = int(changes["proposals"]) + 1
        details.append({"type": "proposal", "proposal_id": new_pid,
                        "scope": "新增程式調整提案", "title": str(prop.get("title", ""))[:200],
                        "target_area": str(prop.get("target_area", ""))})

    return changes


def run_apply_job(report: dict, engine: str) -> None:
    """背景執行：請 CLI 產生結構化 patch、套用、算 diff、更新報告與狀態列。"""
    import subprocess

    rpt_id = report.get("id", "")
    engine_label = ai_provider_label(engine)
    insight_status("running", f"正在請 {engine_label} 研究報告並產生設定調整…", engine=engine, report_id=rpt_id)
    prompt = _build_apply_prompt(report)

    raw, err = _insight_cli_run(engine, prompt, f"正在請 {engine_label} 研究報告並產生設定調整", timeout=600)
    if err and not raw:
        insight_status("failed", f"{engine_label} 執行失敗：{err}", report_id=rpt_id)
        return

    patch = _extract_json_object(raw)
    if patch is None:
        # 無法解析成 JSON：把整段輸出當建議顯示，不動任何檔
        _record_apply_run(rpt_id, engine, raw, "", {}, note="CLI 未回傳可解析的 JSON，未自動套用，請參考下方輸出手動處理。")
        insight_status("done", f"{engine_label} 已回覆，但格式無法自動套用，請看輸出手動處理。", report_id=rpt_id, redirect="/insights")
        return

    insight_status("running", "正在套用設定調整並計算 diff…", engine=engine, report_id=rpt_id)
    changes = apply_structured_patch(patch, report, engine)

    # 算被編輯檔的合併 diff
    labels = [str(p.relative_to(ROOT)) for p in APPLY_EDITABLE_FILES]
    try:
        diff_result = subprocess.run(["git", "diff", "--", *labels], cwd=ROOT, capture_output=True, text=True, timeout=20)
        diff_text = diff_result.stdout.strip()
    except Exception:
        diff_text = ""

    summary = str(patch.get("summary", "")).strip()
    _record_apply_run(rpt_id, engine, raw, diff_text, changes, summary=summary)

    msg = (f"{engine_label} 完成：品味{'有改' if changes['taste'] else '未改'}、"
           f"關鍵字 {changes['keywords']} 條 track、來源 {changes['sources']} 個、提案 {changes['proposals']} 筆。")
    insight_status("done", msg, report_id=rpt_id, redirect="/insights")


def _record_apply_run(rpt_id: str, engine: str, output: str, diff_text: str, changes: dict, summary: str = "", note: str = "") -> None:
    reports = load_jsonl(INSIGHT_REPORTS)
    for rec in reports:
        if rec.get("id") == rpt_id:
            runs = rec.get("apply_runs") or []
            runs.append({
                "engine": engine, "ran_at": now_iso(), "output": output,
                "diff": diff_text, "changes": changes, "summary": summary, "note": note,
            })
            rec["apply_runs"] = runs
            rec["implementation_status"] = "attempted"
            break
    write_jsonl(INSIGHT_REPORTS, reports)


def online_reader_commit_message(dt: datetime | None = None) -> str:
    current = dt.astimezone(LOCAL_TIMEZONE) if dt else datetime.now(LOCAL_TIMEZONE)
    return f"產出 {current.month} 月 {current.day} 日 {current.hour}時{current.minute}分{current.second}秒 線上版"


def data_autocommit_file_labels() -> list[str]:
    return [str(path.relative_to(ROOT)) for path in DATA_AUTOCOMMIT_FILES]


def online_reader_file_labels() -> list[str]:
    return ["docs/reader"]


def data_autocommit_status(state: str, message: str = "", **extra: object) -> dict:
    previous = load_json(DATA_COMMIT_STATUS)
    status = {
        "state": state,
        "message": message,
        "updated_at": datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
        **extra,
    }
    if "next_run_at" not in status and previous.get("next_run_at"):
        status["next_run_at"] = previous.get("next_run_at")
    if "interval_seconds" not in status and previous.get("interval_seconds"):
        status["interval_seconds"] = previous.get("interval_seconds")
    write_status_json(DATA_COMMIT_STATUS, status)
    return status


def data_files_dirty() -> tuple[bool, str]:
    command = ["git", "status", "--porcelain", "--", *data_autocommit_file_labels()]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git status failed")
    return bool(result.stdout.strip()), result.stdout.strip()


def commit_database_state(trigger: str = "manual") -> dict:
    with DATA_AUTOCOMMIT_LOCK:
        started_at = datetime.now(LOCAL_TIMEZONE)
        data_autocommit_status(
            "running",
            "正在檢查閱讀資料庫是否需要 commit。",
            trigger=trigger,
            files=data_autocommit_file_labels(),
        )
        try:
            dirty, status_output = data_files_dirty()
            if not dirty:
                return data_autocommit_status(
                    "no-changes",
                    "閱讀資料庫目前沒有需要 commit 的變更。",
                    trigger=trigger,
                    files=data_autocommit_file_labels(),
                )

            labels = data_autocommit_file_labels()
            subprocess.run(["git", "add", "--", *labels], cwd=ROOT, check=True, text=True, capture_output=True, timeout=30)
            message = data_commit_message(started_at)
            commit = subprocess.run(
                ["git", "commit", "-m", message, "--", *labels],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=120,
            )
            output = commit.stdout + ("\nSTDERR:\n" + commit.stderr if commit.stderr else "")
            if commit.returncode != 0:
                return data_autocommit_status(
                    "failed",
                    "閱讀資料庫 commit 沒有成功。",
                    trigger=trigger,
                    files=labels,
                    git_status=status_output,
                    output=output,
                    returncode=commit.returncode,
                )
            rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, capture_output=True, timeout=20)
            commit_id = clean_text(rev.stdout)
            return data_autocommit_status(
                "committed",
                f"已送出閱讀資料庫自訂紀錄 commit {commit_id}。",
                trigger=trigger,
                files=labels,
                commit=commit_id,
                commit_message=message,
                git_status=status_output,
                output=output,
                returncode=0,
            )
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            return data_autocommit_status(
                "failed",
                f"閱讀資料庫 commit 發生錯誤：{exc}",
                trigger=trigger,
                files=data_autocommit_file_labels(),
            )


def commit_online_reader_output() -> dict:
    labels = online_reader_file_labels()
    started_at = datetime.now(LOCAL_TIMEZONE)
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *labels],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
        )
        if status.returncode != 0:
            return {
                "state": "failed",
                "message": "線上版 commit 前檢查 git 狀態失敗。",
                "files": labels,
                "output": status.stderr.strip() or status.stdout.strip(),
                "returncode": status.returncode,
            }
        if not status.stdout.strip():
            return {
                "state": "no-changes",
                "message": "線上版沒有需要 commit 的變更。",
                "files": labels,
                "returncode": 0,
            }

        add = subprocess.run(
            ["git", "add", "--", *labels],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if add.returncode != 0:
            return {
                "state": "failed",
                "message": "線上版 git add 沒有成功。",
                "files": labels,
                "output": add.stdout + ("\nSTDERR:\n" + add.stderr if add.stderr else ""),
                "returncode": add.returncode,
            }

        message = online_reader_commit_message(started_at)
        commit = subprocess.run(
            ["git", "commit", "-m", message, "--", *labels],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
        output = commit.stdout + ("\nSTDERR:\n" + commit.stderr if commit.stderr else "")
        if commit.returncode != 0:
            return {
                "state": "failed",
                "message": "線上版 commit 沒有成功。",
                "files": labels,
                "commit_message": message,
                "output": output,
                "returncode": commit.returncode,
            }
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, capture_output=True, timeout=20)
        commit_id = clean_text(rev.stdout)
        return {
            "state": "committed",
            "message": f"已送出線上版 commit {commit_id}。",
            "files": labels,
            "commit": commit_id,
            "commit_message": message,
            "output": output,
            "returncode": 0,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "state": "failed",
            "message": f"線上版 commit 發生錯誤：{exc}",
            "files": labels,
            "returncode": 1,
        }


def start_data_autocommit_worker() -> None:
    def worker() -> None:
        while True:
            next_run = datetime.now(LOCAL_TIMEZONE) + timedelta(seconds=DATA_AUTOCOMMIT_INTERVAL_SECONDS)
            current = load_json(DATA_COMMIT_STATUS)
            if (current.get("state") or "") not in {"running", "committed", "failed", "no-changes"}:
                current = {}
            data_autocommit_status(
                current.get("state") or "idle",
                current.get("message") or "閱讀資料庫自動 commit 排程已啟動。",
                next_run_at=next_run.isoformat(timespec="seconds"),
                interval_seconds=DATA_AUTOCOMMIT_INTERVAL_SECONDS,
                files=data_autocommit_file_labels(),
            )
            time.sleep(DATA_AUTOCOMMIT_INTERVAL_SECONDS)
            commit_database_state("auto")

    threading.Thread(target=worker, name="data-autocommit", daemon=True).start()


def default_review(notes: str = "") -> dict:
    return {
        "angle": "",
        "research_status": "not-started",
        "structure_review": "pending",
        "line_review": "pending",
        "target_reader_review": "pending",
        "fact_check": "pending",
        "notes": notes,
    }


def form_value(data: dict[str, list[str]], key: str, default: str = "") -> str:
    return clean_text((data.get(key) or [default])[0])


def selected(value: str, current: str) -> str:
    return " selected" if value == current else ""


def option_list(options: list[tuple[str, str]] | list[str], current: str) -> str:
    rows = []
    for option in options:
        value, label = option if isinstance(option, tuple) else (option, option)
        rows.append(f'<option value="{h(value)}"{selected(value, current)}>{h(label)}</option>')
    return "\n".join(rows)


def track_meta(track: str) -> dict:
    return TRACK_META.get(track) or TRACK_META["unclassified"]


def track_label(track: str) -> str:
    return track_meta(track)["label"]


def track_class(track: str) -> str:
    return track_meta(track)["class"]


def source_type_label(source_type: str) -> str:
    return SOURCE_TYPE_LABELS.get(source_type, source_type or "未標示")


def source_status_label(status: str) -> str:
    return SOURCE_STATUS_LABELS.get(status, status or "未標示")


def source_type_options(current: str) -> str:
    return option_list([(value, SOURCE_TYPE_LABELS.get(value, value)) for value in SOURCE_TYPES], current)


def source_status_options(current: str) -> str:
    return option_list([(value, SOURCE_STATUS_LABELS.get(value, value)) for value in SOURCE_STATUSES], current)


def normalize_fetch_frequency(frequency: str) -> str:
    key = clean_text(frequency or "daily").casefold()
    return FETCH_FREQUENCY_ALIASES.get(key, "daily")


def source_frequency_label(frequency: str) -> str:
    normalized = normalize_fetch_frequency(frequency)
    return FETCH_FREQUENCY_LABELS.get(normalized, normalized)


def source_frequency_options(current: str) -> str:
    return option_list(
        [(value, FETCH_FREQUENCY_LABELS.get(value, value)) for value in FETCH_FREQUENCIES],
        normalize_fetch_frequency(current),
    )


def source_group_values(sources: list[dict]) -> list[str]:
    groups = []
    seen = set()
    orders: dict[str, int] = {}
    for default_group in ["Manual RSS"]:
        seen.add(default_group.casefold())
        groups.append(default_group)
    for source in sources:
        group = clean_text(source.get("source_group"))
        key = group.casefold()
        if group and key not in seen:
            seen.add(key)
            groups.append(group)
        if group:
            order = source_group_order_value(source)
            if order is not None:
                orders[group] = min(orders.get(group, order), order)
    return sorted(groups, key=lambda value: (orders.get(value, 1_000_000), value.casefold()))


def source_group_order_value(source: dict) -> int | None:
    try:
        return int(source.get("source_group_order"))
    except (TypeError, ValueError):
        return None


def source_group_order_for(sources: list[dict], track: str, group: str) -> int | None:
    orders = [
        order
        for source in sources
        if source.get("track") == track and source.get("source_group") == group
        for order in [source_group_order_value(source)]
        if order is not None
    ]
    return min(orders) if orders else None


def next_source_group_order(sources: list[dict], track: str) -> int:
    orders = [
        order
        for source in sources
        if source.get("track") == track
        for order in [source_group_order_value(source)]
        if order is not None
    ]
    return (max(orders) + 1) if orders else 0


def source_group_sort_key(group: str, group_sources: list[dict]) -> tuple[int, str]:
    orders = [
        order
        for source in group_sources
        for order in [source_group_order_value(source)]
        if order is not None
    ]
    order = min(orders) if orders else 1_000_000
    return (order, group.casefold())


def source_group_options(sources: list[dict], current: str) -> str:
    groups = source_group_values(sources)
    current_choice = current if current in groups else NEW_SOURCE_GROUP_VALUE
    options = [(group, group) for group in groups]
    options.append((NEW_SOURCE_GROUP_VALUE, "新增分類..."))
    return option_list(options, current_choice)


def source_group_from_form(data: dict[str, list[str]]) -> str:
    choice = form_value(data, "source_group_choice")
    if choice == NEW_SOURCE_GROUP_VALUE:
        return form_value(data, "source_group_new", "Manual RSS") or "Manual RSS"
    return choice or form_value(data, "source_group", "Manual RSS") or "Manual RSS"


def form_lines(value: object) -> list[str]:
    if isinstance(value, list):
        raw_lines = [str(line) for line in value]
    else:
        raw_lines = re.split(r"[\n,，]", str(value or ""))
    return [line.strip() for line in raw_lines if line.strip()]


def source_keywords_text(source: dict, key: str) -> str:
    return "\n".join(form_lines(source.get(key)))


def source_keyword_signature(source: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(form_lines(source.get("required_keywords"))),
        tuple(form_lines(source.get("excluded_keywords"))),
    )


def source_keyword_haystack(record: dict) -> str:
    parts: list[str] = []
    for key in ["title", "summary", "url", "source_name", "author", "published_at", "captured_at"]:
        parts.append(clean_text(record.get(key)))
    for value in [record.get("tags"), record.get("keywords")]:
        if isinstance(value, list):
            parts.extend(clean_text(item) for item in value)
        else:
            parts.append(clean_text(value))
    for section_key in ["reference", "triage", "editorial_triage", "reading_metadata"]:
        section = record.get(section_key)
        if not isinstance(section, dict):
            continue
        for key in ["title", "summary", "description", "recommendation", "content_kind", "url", "site_name"]:
            parts.append(clean_text(section.get(key)))
    return "\n".join(part for part in parts if part).casefold()


def source_keyword_matches(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if clean_text(keyword).casefold() in text]


def source_record_passes_keywords(record: dict, source: dict) -> bool:
    required = form_lines(source.get("required_keywords"))
    excluded = form_lines(source.get("excluded_keywords"))
    if not required and not excluded:
        return True
    haystack = source_keyword_haystack(record)
    if source_keyword_matches(haystack, excluded):
        return False
    if required and not source_keyword_matches(haystack, required):
        return False
    return True


def is_fetchable_source(source: dict) -> bool:
    return (
        source.get("status") == "active"
        and normalize_fetch_frequency(source.get("fetch_frequency", "daily")) != "paused"
        and source.get("track") in {"digital-humanities-local-knowledge", "open-tech-open-industry"}
        and source.get("source_type") in {"rss", "google-alert", "youtube", "podcast"}
    )


def count_items(items: list[dict], track: str, status: str | None = None) -> int:
    return sum(1 for item in items if item.get("track") == track and (status is None or item.get("status") == status))


def count_sources(sources: list[dict], track: str, active_only: bool = False) -> int:
    return sum(
        1
        for source in sources
        if source.get("track") == track
        and source.get("status") != "archived"
        and (not active_only or is_fetchable_source(source))
    )


def safe_redirect_path(value: object, default: str = "/sources") -> str:
    path = clean_text(value)
    if not path or not path.startswith("/") or path.startswith("//"):
        return default
    return path


def source_name_link(item: dict) -> str:
    name = h(item.get("source_name") or item.get("author") or "未標示來源")
    source_id = clean_text(item.get("source_id"))
    if not source_id:
        return name
    return f'<a href="/sources/view?id={quote(source_id)}">{name}</a>'


def parse_loose_date(value: object) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        number = float(text)
        if 20000 <= number <= 60000:
            return datetime.fromordinal((datetime(1899, 12, 30).toordinal() + int(number))).replace(tzinfo=timezone.utc)
    normalized = text.replace("Z", "+00:00").replace("/", "-")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    match = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", normalized)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def latest_record_date(records: list[dict]) -> str:
    dates = [
        parsed
        for record in records
        for parsed in [parse_loose_date(record.get("dismissed_at") or record.get("captured_at") or record.get("published_at"))]
        if parsed
    ]
    if not dates:
        return ""
    return max(dates).date().isoformat()


def item_datetime(item: dict, *keys: str) -> datetime | None:
    for key in keys or ("published_at", "captured_at", "dismissed_at"):
        parsed = parse_loose_date(item.get(key))
        if parsed:
            return parsed
    return None


def format_datetime(value: object, fallback: str = "未標示時間") -> str:
    parsed = parse_loose_date(value)
    if not parsed:
        text = clean_text(value)
        return text or fallback
    local = parsed.astimezone()
    if local.hour == 0 and local.minute == 0 and local.second == 0:
        return local.strftime("%Y-%m-%d")
    return local.strftime("%Y-%m-%d %H:%M")


def item_display_time(item: dict, *keys: str) -> str:
    for key in keys or ("published_at", "captured_at", "dismissed_at"):
        text = clean_text(item.get(key))
        if text:
            return format_datetime(text)
    return "未標示時間"


def item_sort_time(item: dict) -> str:
    parsed = item_datetime(item, "published_at", "captured_at", "dismissed_at")
    return parsed.isoformat() if parsed else ""


def parse_local_date_input(value: str, *, end: bool = False) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        date_value = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    parsed = datetime(date_value.year, date_value.month, date_value.day, tzinfo=LOCAL_TIMEZONE)
    return parsed + timedelta(days=1) if end else parsed


def reader_time_bounds(time_filter: str, start_value: str = "", end_value: str = "") -> tuple[datetime | None, datetime | None]:
    now = datetime.now(LOCAL_TIMEZONE)
    if time_filter == "three-days":
        return now - timedelta(days=3), None
    if time_filter == "week":
        return now - timedelta(days=7), None
    if time_filter == "month":
        return now - timedelta(days=30), None
    if time_filter == "quarter":
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        return datetime(now.year, quarter_month, 1, tzinfo=LOCAL_TIMEZONE), None
    if time_filter == "year":
        return datetime(now.year, 1, 1, tzinfo=LOCAL_TIMEZONE), None
    if time_filter == "custom":
        return parse_local_date_input(start_value), parse_local_date_input(end_value, end=True)
    return None, None


def item_matches_time_filter(item: dict, start: datetime | None, end: datetime | None) -> bool:
    if not start and not end:
        return True
    parsed = item_datetime(item, "published_at", "captured_at", "dismissed_at")
    if not parsed:
        return False
    return (not start or parsed >= start) and (not end or parsed < end)


def reader_time_summary(time_filter: str, start_value: str = "", end_value: str = "") -> str:
    labels = dict(READER_TIME_FILTERS)
    if time_filter == "custom":
        start_text = clean_text(start_value) or "不限開始"
        end_text = clean_text(end_value) or "不限結束"
        return f"自定時間範圍：{start_text} 至 {end_text}"
    return labels.get(time_filter, labels["all"])


def item_local_datetime(item: dict) -> datetime | None:
    parsed = item_datetime(item, "published_at", "captured_at", "dismissed_at")
    return parsed.astimezone(LOCAL_TIMEZONE) if parsed else None


def reader_month_key(item: dict) -> str:
    parsed = item_local_datetime(item)
    return parsed.strftime("%Y-%m") if parsed else "undated"


def reader_period_label(item: dict) -> str:
    parsed = item_local_datetime(item)
    if not parsed:
        return "未標示時間"
    week_number = ((parsed.day - 1) // 7) + 1
    return f"{parsed.year} 年 {parsed.month} 月 Week {week_number}"


def reader_period_key(item: dict) -> str:
    label = reader_period_label(item)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", label).strip("-") or "undated"


def source_health_summary(source: dict, items: list[dict], rejected: list[dict], candidates: list[dict], dismissed: list[dict]) -> dict:
    source_id = source.get("id")
    source_items = [item for item in items if item.get("source_id") == source_id]
    source_rejected = [item for item in rejected if item.get("source_id") == source_id]
    source_candidates = [item for item in candidates if item.get("source_id") == source_id]
    source_dismissed = [item for item in dismissed if item.get("source_id") == source_id]
    accepted = sum(1 for item in source_items if is_reader_item(item) or item.get("status") in {"triaged", "ready", "published"})
    inbox = sum(1 for item in source_items if item.get("status") == "inbox")
    rejected_count = len(source_rejected) + len(source_dismissed)
    candidate_count = len(source_candidates)
    rss_health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
    saved_assessment = source.get("health_assessment") if isinstance(source.get("health_assessment"), dict) else {}
    keyword_skips = int(rss_health.get("skipped_source_keywords") or 0)
    duplicate_skips = int(rss_health.get("skipped_duplicate_recent") or 0)
    last_status = clean_text(rss_health.get("last_fetch_status"))
    recommendation = clean_text(saved_assessment.get("recommendation"))
    if source.get("status") == "archived":
        level = "archived"
        label = "已封存"
        reason = "這個來源目前不在日常追蹤清單。"
    elif last_status == "failed":
        level = "danger"
        label = "抓取失敗"
        reason = clean_text(rss_health.get("last_error"), 120) or "最近一次 RSS 抓取沒有成功。"
    elif recommendation:
        level = clean_text(saved_assessment.get("level")) or "watch"
        label = recommendation
        reason = clean_text(saved_assessment.get("reason"), 180)
    elif rejected_count >= 5 and rejected_count >= max(accepted * 2, 3):
        level = "danger"
        label = "建議暫停或重設篩選"
        reason = f"已不收 {rejected_count} 次，明顯高於收下 {accepted} 次。"
    elif keyword_skips >= 10 and keyword_skips >= max(int(rss_health.get("new_items") or 0) * 3, 10):
        level = "watch"
        label = "個別關鍵字偏嚴"
        reason = f"最近抓取有 {keyword_skips} 則被來源關鍵字擋下。"
    elif duplicate_skips >= 10:
        level = "watch"
        label = "重複偏多"
        reason = f"最近抓取有 {duplicate_skips} 則是近 7 天已看過的網址。"
    elif accepted >= 3 and accepted >= rejected_count:
        level = "healthy"
        label = "健康"
        reason = f"已收下 {accepted} 則，和目前不收比例相比仍值得追。"
    elif accepted == 0 and rejected_count == 0 and candidate_count == 0 and inbox == 0:
        level = "new"
        label = "新來源 / 待觀察"
        reason = "目前還沒有足夠的收錄或不收紀錄。"
    else:
        level = "watch"
        label = "觀察中"
        reason = f"收下 {accepted}，待整理 {inbox + candidate_count}，不收 {rejected_count}。"
    return {
        "level": level,
        "label": label,
        "reason": reason,
        "accepted": accepted,
        "inbox": inbox,
        "candidates": candidate_count,
        "rejected": rejected_count,
        "keyword_skips": keyword_skips,
        "duplicate_skips": duplicate_skips,
        "last_seen": latest_record_date([*source_items, *source_rejected, *source_candidates, *source_dismissed]),
        "last_checked_at": clean_text(rss_health.get("last_checked_at") or saved_assessment.get("generated_at")),
    }


def source_health_badge(summary: dict) -> str:
    level_class = {
        "healthy": "suggest-keep",
        "watch": "neutral",
        "new": "neutral",
        "danger": "suggest-skip",
        "archived": "archived",
    }.get(summary.get("level"), "neutral")
    return badge(summary.get("label") or "觀察中", level_class)


def badge(label: str, class_name: str = "neutral") -> str:
    return f'<span class="badge badge--{h(class_name)}">{h(label)}</span>'


def taxonomy_license_names() -> list[str]:
    taxonomy = load_json(DATABASE / "taxonomy.json") or {}
    names = taxonomy.get("licenses") if isinstance(taxonomy.get("licenses"), list) else []
    return [clean_text(name, 120) for name in names if clean_text(name, 120)]


def license_name_is_valid(name: str, known_names: set[str] | None = None) -> bool:
    name = clean_text(name, 120)
    if not name:
        return False
    known = known_names if known_names is not None else set(taxonomy_license_names())
    return name in known or name.startswith(LICENSE_NON_CC_PREFIX)


def item_license_name(record: dict) -> str:
    license_data = record.get("license") if isinstance(record.get("license"), dict) else {}
    return clean_text(license_data.get("name"), 120)


def license_label(record: dict) -> str:
    name = item_license_name(record)
    if not name:
        return ""
    license_data = record.get("license") if isinstance(record.get("license"), dict) else {}
    if license_data.get("uncertain") and name != LICENSE_UNSPECIFIED:
        return f"{name}（待確認）"
    return name


def license_badge_html(record: dict) -> str:
    label = license_label(record)
    return badge(label, "neutral") if label else ""


def license_filter_options(records: list[dict] | None = None, default_label: str = "全部授權") -> list[tuple[str, str]]:
    known = taxonomy_license_names()
    options: list[tuple[str, str]] = [("all", default_label)] + [(name, name) for name in known]
    if records:
        known_set = set(known)
        extra = sorted(
            {
                name
                for name in (item_license_name(record) for record in records)
                if name and name not in known_set
            }
        )
        options.extend((name, name) for name in extra)
    return options


def sanitize_attribution_table(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    rows = []
    for row in value:
        if not isinstance(row, dict):
            continue
        cleaned = {
            "scope": clean_text(row.get("scope"), 80),
            "attribution": clean_text(row.get("attribution"), 320),
            "license_name": clean_text(row.get("license_name"), 120),
        }
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def sanitize_license_record(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    name = clean_text(value.get("name"), 120)
    if not name:
        return {}
    record: dict = {
        "name": name,
        "uncertain": bool(value.get("uncertain")) or name == LICENSE_UNSPECIFIED,
    }
    license_url = clean_text(value.get("license_url"), 500) or LICENSE_URLS.get(name, "")
    if license_url:
        record["license_url"] = license_url
    evidence = value.get("evidence")
    if isinstance(evidence, dict):
        cleaned_evidence = {
            key: clean_text(evidence.get(key), 1000)
            for key in ["source_url", "page_title", "rights_holder", "license_link_url", "access_date"]
            if clean_text(evidence.get(key), 1000)
        }
        if cleaned_evidence:
            record["evidence"] = cleaned_evidence
    table = sanitize_attribution_table(value.get("attribution_table"))
    if table:
        record["attribution_table"] = table
    provenance = value.get("provenance")
    if isinstance(provenance, dict):
        cleaned_provenance = {
            key: clean_text(provenance.get(key), 500)
            for key in ["method", "determined_at", "confidence", "source_field"]
            if clean_text(provenance.get(key), 500)
        }
        if cleaned_provenance:
            record["provenance"] = cleaned_provenance
    return record


def manual_license_record(name: str, existing: object = None, raw_json: str = "") -> dict:
    existing_record = sanitize_license_record(existing)
    json_record: dict = {}
    if raw_json.strip():
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            parsed = {}
        json_record = sanitize_license_record(parsed)
    name = clean_text(name or json_record.get("name") or existing_record.get("name"), 120)
    if not name:
        return {}
    if existing_record and item_license_name({"license": existing_record}) == name and not json_record:
        return existing_record
    record = {**json_record, "name": name, "uncertain": name == LICENSE_UNSPECIFIED or bool(json_record.get("uncertain"))}
    if name in LICENSE_URLS and not record.get("license_url"):
        record["license_url"] = LICENSE_URLS[name]
    provenance = dict(record.get("provenance") or {})
    provenance.update({"method": "manual", "determined_at": now_iso(), "confidence": "high"})
    record["provenance"] = provenance
    return sanitize_license_record(record)


def license_attribution_table_html(record: dict) -> str:
    license_data = record.get("license") if isinstance(record.get("license"), dict) else {}
    rows = sanitize_attribution_table(license_data.get("attribution_table"))
    if not rows:
        return ""
    body = "".join(
        "<tr>"
        f"<td>{h(row.get('scope'))}</td>"
        f"<td>{h(row.get('attribution'))}</td>"
        f"<td>{h(row.get('license_name'))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
<table class="metadata-table license-table">
  <thead><tr><th>使用對象</th><th>Attribution / 應標示對象</th><th>CC 授權名稱</th></tr></thead>
  <tbody>{body}</tbody>
</table>
"""


def href_with_query(path: str, params: list[tuple[str, str]]) -> str:
    clean_params = [(key, value) for key, value in params if value]
    if not clean_params:
        return path
    return path + "?" + urlencode(clean_params)


def metric_card(value: object, label: str, href: str = "", hint: str = "", class_name: str = "") -> str:
    classes = "card metric-card"
    if class_name:
        classes += f" {class_name}"
    hint_html = f'<span class="metric-link-label">{h(hint)}</span>' if hint else ""
    value_html = h(str(value)) if value is not None else ""
    content = f'<div class="metric">{value_html}</div><div class="metric-label">{h(label)}</div>{hint_html}'
    if href:
        return f'<a class="{h(classes)}" href="{h(href)}">{content}</a>'
    return f'<div class="{h(classes)}">{content}</div>'


def metric_tile(value: object, label: str, href: str = "", hint: str = "", class_name: str = "") -> str:
    classes = "metric-tile"
    if class_name:
        classes += f" {class_name}"
    hint_html = f'<span class="metric-link-label">{h(hint)}</span>' if hint else ""
    value_html = h(str(value)) if value is not None else ""
    content = f'<div class="metric">{value_html}</div><div class="metric-label">{h(label)}</div>{hint_html}'
    if href:
        return f'<a class="{h(classes)}" href="{h(href)}">{content}</a>'
    return f'<div class="{h(classes)}">{content}</div>'


def command_card(name: str, config: dict) -> str:
    icon = COMMAND_ICONS.get(name, "read")
    shortcut = COMMAND_SHORTCUTS.get(name, "")
    supports_provider = "--provider" in (config.get("command") or [])
    if supports_provider:
        engine_buttons = "".join(
            f"<button type='button' class='secondary' data-engine-job "
            f"data-command='{h(name)}' data-engine='{eng}' data-label='{h(config['label'])}'>{h(label)}</button>"
            for eng, label in (("random", "隨機"), *[(provider, AI_PROVIDER_META[provider]["short"]) for provider in AI_PROVIDER_ORDER])
        )
        controls = (
            "<div class='command-engine-buttons'>"
            f"{engine_buttons}"
            "</div>"
            "<p class='help'>選引擎跑；隨機失敗會自動換其他可用 CLI，指定引擎失敗只提醒不自動換。</p>"
        )
    else:
        controls = (
            "<form method='post' action='/commands/run' data-command-form>"
            f"<input type='hidden' name='command' value='{h(name)}'>"
            f"<button type='submit' class='secondary'>{button_content(config['button'], icon, shortcut)}</button>"
            "</form>"
        )
    return (
        "<div class='card command-card'>"
        f"<strong>{icon_span(icon, shortcut)}{h(config['label'])}</strong>"
        f"<p class='muted'>{h(config['description'])}</p>"
        f"{controls}"
        "</div>"
    )


def render_integrity_issue(issue: dict) -> str:
    target_id = h(issue.get("id"))
    issue_type = issue.get("type")
    if issue_type == "duplicate_item":
        recommended = issue.get("recommended")

        def fix_button(action: str, label: str) -> str:
            is_rec = action == recommended
            cls_attr = "" if is_rec else " class='secondary'"
            suffix = "（建議）" if is_rec else ""
            return (
                "<form method='post' action='/integrity/fix' style='display:inline'>"
                "<input type='hidden' name='issue_type' value='duplicate_item'>"
                f"<input type='hidden' name='target_id' value='{target_id}'>"
                f"<input type='hidden' name='action' value='{h(action)}'>"
                f"<button type='submit'{cls_attr}>{h(label)}{suffix}</button>"
                "</form>"
            )

        meta_bits = []
        if issue.get("rejected_reason"):
            meta_bits.append(f"退件原因：{h(issue['rejected_reason'])}")
        if issue.get("rejected_at"):
            meta_bits.append(f"退件時間：{h(issue['rejected_at'])}")
        meta = f"<p class='help'>{'　'.join(meta_bits)}</p>" if meta_bits else ""
        return (
            "<div class='card'>"
            f"<strong>重複項目：{h(issue.get('title'))}</strong>"
            f"<p class='muted'>{h(issue.get('detail'))}</p>"
            f"<p class='help'>id：<code>{target_id}</code>　主線：{h(issue.get('track'))}</p>"
            f"{meta}"
            f"<div class='button-row'>{fix_button('keep_active', '保留為可用材料')}{fix_button('keep_rejected', '確定退件')}</div>"
            "<p class='help'>「保留為可用材料」會從已退件移除這筆；「確定退件」會從可用材料區移除，並保留退件學習檔。</p>"
            "</div>"
        )
    if issue_type == "orphan_review":
        extra = ""
        if issue.get("step"):
            extra += f"　階段：{h(issue.get('step'))}"
        if issue.get("notes"):
            extra += f"<br>備註：{h(issue.get('notes'))}"
        return (
            "<div class='card'>"
            "<strong>孤兒審查事件</strong>"
            f"<p class='muted'>{h(issue.get('detail'))}</p>"
            f"<p class='help'>事件 id：<code>{target_id}</code>　指向項目：<code>{h(issue.get('item_id'))}</code>{extra}</p>"
            "<form method='post' action='/integrity/fix' style='display:inline'>"
            "<input type='hidden' name='issue_type' value='orphan_review'>"
            f"<input type='hidden' name='target_id' value='{target_id}'>"
            "<input type='hidden' name='action' value='drop_event'>"
            "<button type='submit'>移除這筆審查事件（建議）</button>"
            "</form>"
            "<p class='help'>若項目只是被誤刪，可先去『已退件』找回再回來重檢；否則移除孤兒事件即可。</p>"
            "</div>"
        )
    return ""


def remove_local_candidate_fields(record: dict) -> dict:
    item = dict(record)
    item.pop("candidate_status", None)
    return item


def record_codex_review(record: dict) -> dict:
    return record_model_review(record, "codex")


def normalize_ai_provider(provider: object, allow_random: bool = False) -> str:
    text = clean_text(provider).casefold()
    if allow_random and text == "random":
        return "random"
    return text if text in AI_PROVIDER_META else "codex"


def ai_provider_label(provider: object) -> str:
    normalized = normalize_ai_provider(provider, allow_random=True)
    if normalized == "random":
        return "隨機 CLI"
    return AI_PROVIDER_META[normalized]["label"]


def record_model_review(record: dict, provider: str) -> dict:
    editorial = record.get("editorial_triage") or {}
    if not isinstance(editorial, dict):
        return {}
    key = AI_PROVIDER_META[normalize_ai_provider(provider)]["review_key"]
    review = editorial.get(key)
    return review if isinstance(review, dict) else {}


def record_model_reviews(record: dict) -> list[tuple[str, dict]]:
    reviews: list[tuple[str, dict]] = []
    for provider in AI_PROVIDER_ORDER:
        review = record_model_review(record, provider)
        if review:
            reviews.append((provider, review))
    reviews.sort(
        key=lambda entry: (
            clean_text(entry[1].get("generated_at") or entry[1].get("created_at") or "9999-12-31T23:59:59"),
            AI_PROVIDER_ORDER.index(entry[0]) if entry[0] in AI_PROVIDER_ORDER else len(AI_PROVIDER_ORDER),
        )
    )
    return reviews


def record_preferred_review(record: dict) -> dict:
    reviews = record_model_reviews(record)
    return reviews[0][1] if reviews else {}


def candidate_recommendation(candidate: dict) -> str:
    model_review = record_preferred_review(candidate)
    if model_review:
        model_recommendation = clean_text(model_review.get("recommendation")).casefold()
        if model_recommendation == "recommend-skip":
            return "suggest-skip"
        return "suggest-keep"
    return (candidate.get("triage") or {}).get("recommendation", "unknown")


def is_skill_candidate(item: dict) -> bool:
    decision = item.get("local_decision") or {}
    return item.get("status") == "triaged" and (
        decision.get("action") == "accepted-for-editing"
        or decision.get("next_step") == "run-writing-skill-before-pr"
    )


def is_direct_pr_item(item: dict) -> bool:
    decision = item.get("local_decision") or {}
    return item.get("status") == "ready" and decision.get("action") == "direct-pr-small-news"


def item_display_kind(item: dict) -> str:
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    explicit_kind = clean_text(item.get("content_kind") or editorial.get("content_kind"))
    tags = {clean_text(tag) for tag in item.get("tags", []) if clean_text(tag)}
    if explicit_kind in {"opinion", "opinion-article"} or "觀點文章" in tags:
        return "opinion-article"
    if is_skill_candidate(item):
        return "featured-article"
    if is_direct_pr_item(item) or item.get("status") == "ready":
        return "small-news"
    editorial = item.get("editorial_triage") or {}
    if isinstance(editorial, dict) and editorial.get("content_kind") == "small-news":
        return "small-news"
    return "needs-review"


def item_triage_keywords(item: dict) -> set[str]:
    triage = item.get("triage") or {}
    keywords = {canonical_tag_label(keyword) for keyword in triage.get("matched_keywords") or []}
    keywords.update(canonical_tag_label(keyword) for keyword in triage.get("skip_keywords") or [])
    keywords.update(normalized_item_tags(item))
    return {str(keyword) for keyword in keywords if str(keyword).strip()}


def item_matches_tag(item: dict, tag: object) -> bool:
    target_key = tag_key(tag)
    target_group_key = tag_group_key(tag)
    if not target_key:
        return False
    for item_tag in item_triage_keywords(item):
        if tag_key(item_tag) == target_key or tag_group_key(item_tag) == target_group_key:
            return True
    return False


def tag_key(tag: object) -> str:
    return clean_text(tag, 120).casefold()


@lru_cache(maxsize=1)
def taxonomy_alias_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for group, aliases in TAG_SYNONYM_GROUPS:
        formal = clean_text(group, 80)
        for alias in [formal, *aliases]:
            key = tag_key(alias)
            if key:
                labels.setdefault(key, formal)
    return labels


@lru_cache(maxsize=1)
def taxonomy_formal_tag_keys() -> set[str]:
    return {tag_key(group) for group, _aliases in TAG_SYNONYM_GROUPS if tag_key(group)}


def tag_group_key(tag: object) -> str:
    key = re.sub(r"[\s/_-]+", "", tag_key(tag))
    if not key:
        return ""
    for group, labels in TAG_SYNONYM_GROUPS:
        if key == re.sub(r"[\s/_-]+", "", tag_key(group)):
            return re.sub(r"[\s/_-]+", "", tag_key(group))
        for label in labels:
            if key == re.sub(r"[\s/_-]+", "", tag_key(label)):
                return re.sub(r"[\s/_-]+", "", tag_key(group))
    return key


def tag_group_label(tag: object) -> str:
    group_key = tag_group_key(tag)
    for group, labels in TAG_SYNONYM_GROUPS:
        if group_key == re.sub(r"[\s/_-]+", "", tag_key(group)):
            return group
        for label in labels:
            if group_key == re.sub(r"[\s/_-]+", "", tag_key(label)):
                return group
    return canonical_tag_label(tag)


def tag_facet_rank(group_label: str) -> tuple[int, int]:
    """依 TAG_FACETS 給組別一個排序權重；未列入者排最後。"""
    for facet_index, (_facet, labels) in enumerate(TAG_FACETS):
        if group_label in labels:
            return (facet_index, labels.index(group_label))
    return (len(TAG_FACETS), 0)


def grouped_tags(tags: list[str]) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    index_by_key: dict[str, int] = {}
    for tag in tags:
        key = tag_group_key(tag)
        if not key:
            continue
        if key not in index_by_key:
            index_by_key[key] = len(groups)
            groups.append((tag_group_label(tag), []))
        label, values = groups[index_by_key[key]]
        if tag_key(tag) not in {tag_key(value) for value in values}:
            values.append(tag)
        groups[index_by_key[key]] = (label, values)
    # 依分面（主題 → 組織 → 社群/活動 → 其他）排序，讓建議更有邏輯
    groups.sort(key=lambda g: tag_facet_rank(g[0]))
    return groups


def taxonomy_primary_tags() -> list[str]:
    """每個 taxonomy 組別的代表標籤（第一個別名 = 正式名），給新表單當分面建議。"""
    return [aliases[0] for _label, aliases in TAG_SYNONYM_GROUPS if aliases]


def taxonomy_alias_options() -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for group, aliases in TAG_SYNONYM_GROUPS:
        label = clean_text(group, 80)
        for alias in [label, *aliases]:
            key = tag_key(alias)
            if not key or key in seen:
                continue
            options.append({"alias": clean_text(alias, 80), "label": label})
            seen.add(key)
    return options


def tag_href(tag: object) -> str:
    return href_with_query("/tags", [("tag", clean_text(tag, 120))])


@lru_cache(maxsize=1)
def configured_keep_keyword_labels() -> dict[str, str]:
    config = load_json(TRIAGE_KEYWORDS)
    tracks = config.get("tracks") if isinstance(config.get("tracks"), dict) else {}
    labels: dict[str, str] = {}
    for track_config in tracks.values():
        if not isinstance(track_config, dict):
            continue
        for keyword in track_config.get("keep_keywords") or []:
            label = clean_text(keyword, 80)
            key = tag_key(label)
            if key and not key.isdigit():
                labels.setdefault(key, label)
    return labels


def canonical_tag_label(tag: object) -> str:
    text = clean_text(tag, 80)
    key = tag_key(text)
    return taxonomy_alias_labels().get(key) or configured_keep_keyword_labels().get(key, text)


def is_known_tag_label(tag: object) -> bool:
    key = tag_key(tag)
    return key in taxonomy_formal_tag_keys() or key in configured_keep_keyword_labels()


def item_tags(item: dict) -> list[str]:
    tags = form_lines(item.get("tags"))
    output: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        tag = canonical_tag_label(tag)
        key = tag_key(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(tag)
    return output


def is_noisy_tag(tag: object) -> bool:
    key = tag_key(tag)
    if not key:
        return True
    if key in NOISY_TAG_VALUES:
        return True
    if not any(char.isalnum() for char in key):
        return True
    if key.isdigit():
        return True
    if key in configured_keep_keyword_labels():
        return False
    if key.startswith("keyword-monitoring-"):
        return True
    if key.startswith("[archived]"):
        return True
    if key.startswith("http://") or key.startswith("https://"):
        return True
    if "週更新" in key or "月更新" in key or "有就更新" in key:
        return True
    if key.endswith(" rss") or key.endswith(" blog") or key.endswith(" news"):
        return True
    return False


def source_like_tag_keys(item: dict) -> set[str]:
    keys: set[str] = set()
    for value in [
        item.get("source_name"),
        item.get("author"),
        item.get("source_group"),
        item.get("site_name"),
        (item.get("reference") or {}).get("site_name") if isinstance(item.get("reference"), dict) else "",
        (item.get("reading_metadata") or {}).get("site_name") if isinstance(item.get("reading_metadata"), dict) else "",
    ]:
        text = clean_text(value, 160)
        if not text:
            continue
        variants = {text}
        for prefix in ["Excel:", "[Archived]"]:
            if text.casefold().startswith(prefix.casefold()):
                variants.add(text[len(prefix) :].strip())
        keys.update(tag_key(variant) for variant in variants if tag_key(variant))
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    url = clean_text(item.get("url") or reference.get("url"))
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    if host:
        keys.add(host)
        keys.add(host.split(":")[0])
        keys.add(host.split(".")[0])
    return keys


def is_source_like_tag(tag: object, item: dict | None = None) -> bool:
    key = tag_key(tag)
    if not key or key in configured_keep_keyword_labels():
        return False
    if item and key in source_like_tag_keys(item):
        return True
    return False


def append_unique_tag(tags: list[str], seen: set[str], tag: object) -> None:
    text = canonical_tag_label(tag)
    key = tag_key(text)
    if not text or not key or key in seen or is_noisy_tag(text):
        return
    tags.append(text)
    seen.add(key)


def append_item_tag(tags: list[str], seen: set[str], item: dict, tag: object) -> None:
    text = canonical_tag_label(tag)
    if is_source_like_tag(text, item):
        return
    append_unique_tag(tags, seen, text)


def item_has_manual_tags(item: dict) -> bool:
    metadata = item.get("tag_metadata") if isinstance(item.get("tag_metadata"), dict) else {}
    return metadata.get("source") == "local_web"


def normalized_item_tags(item: dict, limit: int | None = None) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    manual_tags = item_has_manual_tags(item)
    for keyword in triage.get("matched_keywords") or []:
        append_item_tag(tags, seen, item, keyword)
    for tag in item_tags(item):
        if not is_known_tag_label(tag) and not manual_tags:
            continue
        append_item_tag(tags, seen, item, tag)
    return tags[:limit] if limit is not None else tags


def item_visible_tags(item: dict, limit: int = 7) -> list[str]:
    tags = normalized_item_tags(item, limit=limit)
    return tags[:limit]


def tag_chips_html(tags: list[str], class_name: str = "tag-chip-list") -> str:
    if not tags:
        return ""
    chips = "".join(
        f'<a class="tag-chip" href="{h(tag_href(tag))}">{icon_span("tag", "", "tag-chip-icon")}{h(tag)}</a>'
        for tag in tags
    )
    return f'<div class="{h(class_name)}">{chips}</div>'


def tag_picker_controls_html(
    current_tags: list[str],
    suggestions: list[str],
    options: list[str],
    *,
    placeholder: str = "搜尋或新增 tag",
    aria_label: str = "搜尋或新增 tag",
    collapse_suggestions: bool = False,
) -> str:
    option_payload: list[str] = []
    option_seen: set[str] = set()
    for tag in [*current_tags, *suggestions, *options]:
        append_unique_tag(option_payload, option_seen, tag)

    current_html = "".join(
        f"""<button type="button" class="tag-pill" data-tag-value="{h(tag)}" data-remove-tag>
  {icon_span("tag", "", "tag-chip-icon")}<span>{h(tag)}</span><span class="tag-pill-remove" aria-hidden="true">x</span>
</button>"""
        for tag in current_tags
    )
    hidden_inputs = "".join(f'<input type="hidden" name="tags" value="{h(tag)}">' for tag in current_tags)
    suggested_groups_html = []
    for group_label, group_tags in grouped_tags(suggestions):
        suggestions_html = "".join(
            f"""<button type="button" class="tag-suggestion" data-tag-suggestion="{h(tag)}">
  {icon_span("tag", "", "tag-chip-icon")}<span>{h(tag)}</span>
</button>"""
            for tag in group_tags
        )
        suggested_groups_html.append(
            f"""
<div class="tag-suggestion-group">
  <div class="tag-suggestion-group-label">{h(group_label)}</div>
  <div class="tag-suggestion-strip">{suggestions_html}</div>
</div>
"""
        )
    suggested_html = "".join(suggested_groups_html)
    options_json = json.dumps(option_payload, ensure_ascii=False).replace("<", "\\u003c")
    suggestions_block = f'<div class="tag-suggestion-groups" data-tag-suggestions>{suggested_html}</div>'
    if collapse_suggestions and suggested_html.strip():
        suggestions_block = (
            '<details class="tag-suggestion-collapse">'
            '<summary>瀏覽建議標籤（依分面）</summary>'
            f'{suggestions_block}</details>'
        )
    return f"""
    <div class="tag-picker-current" data-tag-current>{current_html}</div>
    <div class="tag-search-wrap">
      <input name="new_tags" data-tag-input autocomplete="off" placeholder="{h(placeholder)}" aria-label="{h(aria_label)}">
      <div class="tag-menu" data-tag-menu hidden></div>
    </div>
    {suggestions_block}
    <div data-tag-hidden>{hidden_inputs}</div>
    <script type="application/json" data-tag-options>{options_json}</script>
"""


def form_tags(data: dict[str, list[str]], key: str = "tags") -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in data.get(key) or []:
        for tag in re.split(r"[\n,，]+", str(value)):
            append_unique_tag(tags, seen, tag)
    return tags


def item_tag_text_haystack(item: dict) -> str:
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    metadata = item_reading_metadata(item)
    parts: list[object] = [
        item.get("title"),
        item.get("summary"),
        metadata.get("title"),
        metadata.get("description"),
        metadata.get("article_text"),
        metadata.get("article_markdown"),
        " ".join(triage.get("matched_keywords") or []),
    ]
    return "\n".join(clean_text(part, 3000) for part in parts if part).casefold()


def item_workflow_search_haystack(item: dict) -> str:
    metadata = item_reading_metadata(item)
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    model_parts: list[object] = []
    for provider, review in record_model_reviews(item):
        model_parts.extend([
            ai_provider_label(provider),
            review.get("one_line_recommendation"),
            review.get("summary"),
            model_recommendation_label(review),
            " ".join(clean_text(reason, 240) for reason in (review.get("reasons") or [])),
        ])
    parts: list[object] = [
        item.get("id"),
        item_display_title(item),
        item_original_title(item),
        item_zh_summary(item, 800),
        item.get("title"),
        item.get("summary"),
        item.get("source_name"),
        item.get("source_id"),
        item.get("author"),
        item.get("url"),
        item.get("published_at"),
        item.get("captured_at"),
        item_license_name(item),
        metadata.get("title"),
        metadata.get("description"),
        metadata.get("original_site_title"),
        metadata.get("translated_zh_title"),
        metadata.get("original_author"),
        metadata.get("site_name"),
        metadata.get("final_url"),
        metadata.get("canonical_url"),
        " ".join(item_visible_tags(item, 20)),
        " ".join(triage.get("matched_keywords") or []),
        " ".join(triage.get("skip_keywords") or []),
        triage.get("reason"),
        editorial.get("summary_reason"),
        editorial.get("next_step_hint"),
        editorial.get("zh_summary"),
        editorial.get("content_kind_label"),
        *model_parts,
    ]
    return "\n".join(clean_text(part, 1000) for part in parts if part).casefold()


def item_matches_text_filter(item: dict, query: object) -> bool:
    terms = [
        clean_text(term, 80).casefold()
        for term in re.split(r"[\s,，]+", clean_text(query, 180))
        if clean_text(term, 80)
    ]
    if not terms:
        return True
    haystack = item_workflow_search_haystack(item)
    return all(term in haystack for term in terms)


def taxonomy_beats(track: str) -> list[str]:
    taxonomy = load_json(DATABASE / "taxonomy.json")
    tracks = taxonomy.get("tracks") if isinstance(taxonomy.get("tracks"), dict) else {}
    meta = tracks.get(track) if isinstance(tracks.get(track), dict) else {}
    beats = meta.get("beats") if isinstance(meta.get("beats"), list) else []
    return [clean_text(beat, 80) for beat in beats if clean_text(beat)]


def tag_counts_for(records: list[dict], *, track: str = "", source_id: str = "") -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        if track and record.get("track") != track:
            continue
        if source_id and record.get("source_id") != source_id:
            continue
        for tag in item_tags(record):
            key = tag_key(tag)
            if (
                not is_noisy_tag(tag)
                and not is_source_like_tag(tag, record)
                and (is_known_tag_label(tag) or item_has_manual_tags(record))
            ):
                counts[tag] += 1
    return counts


def tag_search_keys(tag: object) -> list[str]:
    text = clean_text(tag, 80)
    canonical = canonical_tag_label(text)
    canonical_key = tag_key(canonical)
    keys: list[str] = []
    seen: set[str] = set()
    for key, label in taxonomy_alias_labels().items():
        if tag_key(label) == canonical_key and key not in seen:
            keys.append(key)
            seen.add(key)
    direct_key = tag_key(text)
    if direct_key and direct_key not in seen:
        keys.append(direct_key)
        seen.add(direct_key)
    return keys


def tag_matches_haystack(tag: object, haystack: str) -> bool:
    for key in tag_search_keys(tag):
        if key in configured_keep_keyword_labels():
            if key in haystack:
                return True
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9 &./+-]{0,2}", key):
            continue
        if key in haystack:
            return True
    return False


def suggested_item_tags(item: dict, records: list[dict], limit: int = TAG_SUGGESTION_LIMIT) -> list[str]:
    current_keys = {tag_key(tag) for tag in item_tags(item)}
    suggestions: list[str] = []
    seen: set[str] = set(current_keys)
    haystack = item_tag_text_haystack(item)
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}

    for keyword in [*(triage.get("matched_keywords") or []), *(triage.get("mechanism_keywords") or [])]:
        append_item_tag(suggestions, seen, item, keyword)
    for tag in taxonomy_primary_tags():
        if tag_matches_haystack(tag, haystack):
            append_item_tag(suggestions, seen, item, tag)
    for beat in taxonomy_beats(clean_text(item.get("track"))):
        if tag_matches_haystack(beat, haystack):
            append_item_tag(suggestions, seen, item, beat)

    peers = [record for record in records if record.get("id") != item.get("id")]
    for tag, _count in tag_counts_for(peers, track=clean_text(item.get("track"))).most_common(80):
        key = tag_key(tag)
        if key and tag_matches_haystack(tag, haystack):
            append_item_tag(suggestions, seen, item, tag)
        if len(suggestions) >= limit:
            break

    return suggestions[:limit]


def all_tag_options(records: list[dict], limit: int = 120) -> list[str]:
    counts = tag_counts_for(records)
    return [tag for tag, _count in counts.most_common(limit)]


def item_reader_flags(item: dict) -> dict:
    flags = item.get("reader_flags")
    return flags if isinstance(flags, dict) else {}


def current_reading_flags(item: dict, updated_at: str) -> dict:
    flags = dict(item_reader_flags(item))
    flags.update(
        {
            "current_reading": True,
            "share_intent": True,
            "started_at": flags.get("started_at") or updated_at,
            "updated_at": updated_at,
            "source": "local_web",
            "skill_priority_after_days": CURRENT_READING_PRIORITY_DAYS,
        }
    )
    return flags


def item_is_current_reading(item: dict) -> bool:
    flags = item_reader_flags(item)
    return bool(flags.get("current_reading") or flags.get("share_intent"))


def item_current_reading_started_at(item: dict) -> str:
    flags = item_reader_flags(item)
    return clean_text(flags.get("started_at") or flags.get("flagged_at"))


def item_current_reading_age_days(item: dict) -> int:
    started = parse_loose_date(item_current_reading_started_at(item))
    if not started:
        return 0
    return max(0, (datetime.now(timezone.utc) - started).days)


def item_has_mature_current_reading_flag(item: dict) -> bool:
    return item_is_current_reading(item) and item_current_reading_age_days(item) >= CURRENT_READING_PRIORITY_DAYS


def item_skill_priority_tuple(item: dict) -> tuple[int, str, str]:
    if item_has_mature_current_reading_flag(item):
        return (0, item_current_reading_started_at(item), item_sort_time(item))
    if item_is_current_reading(item):
        return (1, item_current_reading_started_at(item), item_sort_time(item))
    return (2, (item.get("local_decision") or {}).get("decided_at", ""), item_sort_time(item))


def reader_flag_badges(item: dict) -> str:
    if not item_is_current_reading(item):
        return ""
    age = item_current_reading_age_days(item)
    labels = ["優先正在閱讀", "想分享"]
    if age >= CURRENT_READING_PRIORITY_DAYS:
        labels.append(f"已標記 {age} 天")
    return "".join(badge(label, "reading") for label in labels)


def tag_editor_html(item: dict, records: list[dict], redirect_to: str, autosave: bool = False) -> str:
    item_id = clean_text(item.get("id"))
    current_tags = normalized_item_tags(item)
    suggestions = suggested_item_tags(item, records)
    suggestion_keys = {tag_key(tag) for tag in suggestions}
    current_keys = {tag_key(tag) for tag in current_tags}
    options = [tag for tag in all_tag_options(records) if tag_key(tag) not in current_keys | suggestion_keys][:80]
    controls_html = tag_picker_controls_html(current_tags, suggestions, options)
    autosave_attr = " data-tag-autosave" if autosave else ""
    autosave_status = '<p class="help tag-autosave-status" data-tag-autosave-status>變更會自動儲存</p>' if autosave else ""
    submit_button = "" if autosave else f'<button type="submit">{button_content("儲存 tag", "tag", "T")}</button>'
    return f"""
<div class="card" id="tag-panel">
  <h2>概念標籤</h2>
  <form method="post" action="/items/update-tags" class="tag-picker" data-tag-picker{autosave_attr}>
    <input type="hidden" name="id" value="{h(item_id)}">
    <input type="hidden" name="redirect" value="{h(redirect_to)}">
    {controls_html}
    {autosave_status}
    {submit_button}
  </form>
</div>
"""


def reading_priority_form(item: dict, redirect_to: str, compact: bool = False) -> str:
    item_id = clean_text(item.get("id"))
    active = item_is_current_reading(item)
    action = "clear" if active else "mark"
    label = "取消優先正在閱讀" if active else "標記近期正在讀 / 想分享"
    button_class = "quiet" if active else "secondary"
    button_content_html = button_content(label, "bookmark", "B")
    extra_class = " reader-action-button" if compact else ""
    if compact:
        button_content_html = f'{icon_span("bookmark", "B", "icon reader-action-icon")}{action_label(label)}'
    return f"""
<form method="post" action="/items/toggle-reading-priority">
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="action" value="{h(action)}">
  <input type="hidden" name="redirect" value="{h(redirect_to)}">
  <button type="submit" class="{h(button_class + extra_class)}" aria-label="{h(label)}" title="{h(label)}">{button_content_html}</button>
</form>
"""


def recommendation_label(recommendation: str) -> str:
    if recommendation == "suggest-keep":
        return "建議收"
    if recommendation == "suggest-skip":
        return "建議不要看"
    if recommendation == "suggest-ask":
        return "機制吻合，先問你"
    return "未判斷"


def editorial_recommendation_label(recommendation: str) -> str:
    if recommendation == "suggest-collect":
        return "建議收錄"
    if recommendation == "suggest-review":
        return "建議人工看過"
    if recommendation == "suggest-skip":
        return "建議不要看"
    if recommendation == "suggest-ask":
        return "建議先問你（命中個人 beat 或底層機制）"
    return "尚未初篩"


def content_kind_label(kind: str) -> str:
    if kind in {"opinion", "opinion-article"}:
        return "觀點文章"
    if kind == "featured-article":
        return "可用材料 / 可進編輯台"
    if kind == "small-news":
        return "純新聞 / 小消息"
    return "人工判斷"


def status_label(status: str) -> str:
    labels = {
        "inbox": "入庫建檔中",
        "triaged": "可進編輯台",
        "researching": "補來源中",
        "drafting": "撰稿中",
        "reviewing": "審稿中",
        "fact-checking": "查核中",
        "ready": "可送 PR / 可讀",
        "published": "已發布",
        "archived": "封存",
    }
    return labels.get(status, status or "未標示")


def workflow_display_text(value: object, limit: int | None = None) -> str:
    text = clean_text(value, limit)
    replacements = [
        ("批次確認收，準備跑 skill", "批次確認收，放入可用材料區"),
        ("確認收，準備跑 skill", "確認收，放入可用材料區"),
        ("RSS 待整理", "入庫建檔區"),
        ("候選清單", "可用材料區"),
        ("待跑 skill", "可進編輯台"),
        ("skill 候選", "編輯台候選"),
        ("重新送 skill", "送回編輯台"),
        ("重送 skill", "編輯台回流"),
        ("送 skill 做切角、摘要與文章編修", "送進編輯台做切角、摘要與 article 草稿"),
        ("跑 skill 做摘要、切角與文章編修", "進編輯台做摘要、切角與 article 草稿"),
        ("跑 skill", "進編輯台"),
        ("送 skill", "送進編輯台"),
        ("加收藏", "手動入庫"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def editorial_badge_class(recommendation: str) -> str:
    if recommendation == "suggest-collect":
        return "suggest-keep"
    if recommendation == "suggest-review":
        return "neutral"
    if recommendation == "suggest-skip":
        return "suggest-skip"
    if recommendation == "suggest-ask":
        return "suggest-ask"
    return "neutral"


def clamp_score(value: float, low: float = 0, high: float = 10) -> float:
    return max(low, min(high, value))


def raw_number(value: object, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def scale_score(value: object, low: float, high: float, invert: bool = False) -> float:
    number = clamp_score(raw_number(value), low, high)
    if high == low:
        score = 0.0
    else:
        score = ((number - low) / (high - low)) * 10
    if invert:
        score = 10 - score
    return clamp_score(score)


def confidence_score_10(value: object) -> float:
    label = clean_text(value).casefold()
    if label == "high":
        return 10
    if label == "medium":
        return 6
    if label == "low":
        return 3
    return 0


def recommendation_score_10(value: object) -> float:
    recommendation = clean_text(value).casefold()
    if recommendation in {"recommend-collect", "suggest-collect"}:
        return 10
    if recommendation in {"recommend-review", "suggest-review"}:
        return 6.5
    if recommendation in {"suggest-keep", "recommend-keep"}:
        return 8
    if recommendation in {"recommend-skip", "suggest-skip"}:
        return 1.5
    return 4


def local_rule_score_10(item: dict) -> float:
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    scores: list[tuple[float, float]] = []
    if isinstance(editorial, dict) and editorial:
        keyword = editorial.get("keyword_fit") if isinstance(editorial.get("keyword_fit"), dict) else {}
        prior = editorial.get("prior_collection_fit") if isinstance(editorial.get("prior_collection_fit"), dict) else {}
        deletion = editorial.get("deletion_pattern_fit") if isinstance(editorial.get("deletion_pattern_fit"), dict) else {}
        if keyword:
            scores.append((scale_score(keyword.get("score"), -6, 6), 0.32))
        if prior:
            scores.append((scale_score(prior.get("score"), 0, 5), 0.22))
        if deletion:
            scores.append((scale_score(deletion.get("score"), 0, 6, invert=True), 0.26))
        if editorial.get("recommendation"):
            scores.append((recommendation_score_10(editorial.get("recommendation")), 0.20))
    if not scores and triage:
        scores.append((recommendation_score_10(triage.get("recommendation")), 1.0))
    if not scores:
        return 4
    weight = sum(score_weight for _, score_weight in scores) or 1
    return clamp_score(sum(score * score_weight for score, score_weight in scores) / weight)


def collection_fit_score_10(item: dict) -> float:
    model_review = record_preferred_review(item)
    if model_review:
        return recommendation_score_10(model_review.get("recommendation"))
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    if editorial and editorial.get("recommendation"):
        return recommendation_score_10(editorial.get("recommendation"))
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    return recommendation_score_10(triage.get("recommendation"))


def item_confidence_score_10(item: dict) -> float:
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    if editorial and editorial.get("confidence"):
        return confidence_score_10(editorial.get("confidence"))
    model_review = record_preferred_review(item)
    if model_review and model_review.get("confidence"):
        return confidence_score_10(model_review.get("confidence"))
    return 0


def candidate_priority_scores(item: dict) -> dict[str, float]:
    rule_score = local_rule_score_10(item)
    collect_score = collection_fit_score_10(item)
    confidence_score = item_confidence_score_10(item)
    overall = (rule_score * 0.45) + (collect_score * 0.40) + (confidence_score * 0.15)
    return {
        "overall": clamp_score(overall),
        "rule": rule_score,
        "collect": collect_score,
        "confidence": confidence_score,
    }


def score_label(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def candidate_sort_key(entry: tuple[str, dict]) -> tuple[float, float, float, float, str, str, str]:
    item = entry[1]
    scores = candidate_priority_scores(item)
    return (
        scores["overall"],
        scores["collect"],
        scores["confidence"],
        scores["rule"],
        item.get("captured_at", ""),
        item.get("published_at", ""),
        item_display_title(item),
    )


def model_recommendation_label(review: dict) -> str:
    recommendation = clean_text(review.get("recommendation")).casefold()
    if recommendation == "recommend-collect":
        return "建議收"
    if recommendation == "recommend-review":
        return "建議人工看過"
    if recommendation == "recommend-skip":
        return "建議不要看"
    return "未判斷"


def model_recommendation_badge_class(review: dict) -> str:
    recommendation = clean_text(review.get("recommendation")).casefold()
    if recommendation == "recommend-skip":
        return "suggest-skip"
    if recommendation == "recommend-collect":
        return "suggest-keep"
    return "neutral"


def score_summary_html(item: dict) -> str:
    scores = candidate_priority_scores(item)
    labels = [
        ("綜合排序", scores["overall"]),
        ("自動規則", scores["rule"]),
        ("建議收程度", scores["collect"]),
        ("信心度", scores["confidence"]),
    ]
    return "<div class='score-grid'>" + "".join(
        f"<span class='score-pill'><b>{h(score_label(value))}</b><small>/10 {h(label)}</small></span>"
        for label, value in labels
    ) + "</div>"


def rule_stage_scores_html(item: dict) -> str:
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    if not editorial:
        return ""
    rows: list[tuple[str, float, str]] = []
    keyword = editorial.get("keyword_fit") if isinstance(editorial.get("keyword_fit"), dict) else {}
    prior = editorial.get("prior_collection_fit") if isinstance(editorial.get("prior_collection_fit"), dict) else {}
    deletion = editorial.get("deletion_pattern_fit") if isinstance(editorial.get("deletion_pattern_fit"), dict) else {}
    if keyword:
        rows.append(("關鍵字", scale_score(keyword.get("score"), -6, 6), "越高越符合主線"))
    if prior:
        rows.append(("過去收錄", scale_score(prior.get("score"), 0, 5), "越高越像已收材料"))
    if deletion:
        rows.append(("不收風險", scale_score(deletion.get("score"), 0, 6, invert=True), "越高越不像不收紀錄"))
    if not rows:
        return ""
    return "<div class='score-grid score-grid--stages'>" + "".join(
        f"<span class='score-pill score-pill--soft'><b>{h(score_label(value))}</b><small>/10 {h(label)}</small><em>{h(hint)}</em></span>"
        for label, value, hint in rows
    ) + "</div>"


def model_judgement_summary_html(item: dict) -> str:
    parts = []
    for provider, review in record_model_reviews(item):
        parts.append(f"{ai_provider_label(provider)} 最後判斷：{model_recommendation_label(review)}")
    if not parts:
        return "<p class='help'>Codex 最後判斷：尚未生成。</p>"
    return f"<p class='help'>{h('；'.join(parts))}</p>"


def item_detail_href(item: dict) -> str:
    return f"/items/view?id={quote(str(item.get('id', '')))}"


RECYCLE_ORIGIN_LABELS = {
    "rejected": "已入庫後不收",
    "dismissed": "RSS 新進略過",
}


def recycle_record_reason(record: dict, limit: int = 140) -> str:
    decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
    reason = clean_text(decision.get("reason"), limit) or clean_text(record.get("reason"), limit)
    if not reason:
        notes = clean_text(record.get("notes"), 260)
        match = re.search(r"原因[：:]\s*([^。；;\n]+)", notes)
        if match:
            reason = clean_text(match.group(1), limit)
        elif notes:
            reason = clean_text(notes, limit)
    if not reason:
        editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
        reason = clean_text(editorial.get("summary_reason"), limit)
    return alias_rejection_reason(reason) or rejection_reason_base(reason)


def recycle_record_decided_at(record: dict) -> str:
    decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
    archive = record.get("archive") if isinstance(record.get("archive"), dict) else {}
    return clean_text(
        decision.get("decided_at")
        or archive.get("moved_at")
        or record.get("dismissed_at")
        or record.get("captured_at")
        or record.get("published_at")
    )


def recycle_record_sort_time(record: dict) -> str:
    parsed = parse_loose_date(recycle_record_decided_at(record))
    if not parsed:
        parsed = item_datetime(record, "published_at", "captured_at", "dismissed_at")
    return parsed.isoformat() if parsed else ""


def recycle_record_origin_label(record: dict) -> str:
    origins = record.get("_recycle_origins") if isinstance(record.get("_recycle_origins"), list) else []
    labels = [RECYCLE_ORIGIN_LABELS.get(origin, origin) for origin in origins if origin]
    if labels:
        return " / ".join(labels)
    return RECYCLE_ORIGIN_LABELS.get(clean_text(record.get("_recycle_origin")), "不收紀錄")


def recycle_records() -> list[dict]:
    merged: dict[str, dict] = {}
    for origin, path in [("rejected", REJECTED_ITEMS), ("dismissed", DISMISSED)]:
        for index, record in enumerate(load_jsonl(path)):
            item = dict(record)
            item["_recycle_origin"] = origin
            item["_recycle_origins"] = [origin]
            item["_recycle_index"] = index
            item_id = clean_text(item.get("id"))
            url = clean_text(item.get("url"))
            key = item_id or (f"url:{url}" if url else stable_id("recycle", origin, index, item.get("title")))
            existing = merged.get(key)
            if not existing:
                merged[key] = item
                continue
            origins = list(existing.get("_recycle_origins") or [])
            if origin not in origins:
                origins.append(origin)
            old_quality = (1 if existing.get("_recycle_origin") == "rejected" else 0, len(json.dumps(existing, ensure_ascii=False)))
            new_quality = (1 if origin == "rejected" else 0, len(json.dumps(item, ensure_ascii=False)))
            if new_quality > old_quality:
                item["_recycle_origins"] = origins
                merged[key] = item
            else:
                existing["_recycle_origins"] = origins
    return sorted(merged.values(), key=lambda record: (recycle_record_sort_time(record), item_display_title(record)), reverse=True)


def clean_restored_recycle_record(record: dict, decided_at: str, source_label: str) -> dict:
    restored = {key: value for key, value in record.items() if not key.startswith("_recycle_")}
    for key in ["archive", "dismissed_at", "candidate_status", "reason"]:
        restored.pop(key, None)
    restored["status"] = "inbox"
    restored["priority"] = "normal"
    restored["local_decision"] = {
        "action": "restored",
        "decided_at": decided_at,
        "reason": source_label,
        "source": "local_web",
        "next_step": "review-in-rss-inbox",
    }
    return restored


def public_reader_article_filename(item: dict) -> str:
    item_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_text(item.get("id")) or "item").strip("-")
    return f"{item_id}.html"


def public_reader_article_url(item: dict) -> str:
    return f"{ONLINE_READER_BASE_URL}/articles/{public_reader_article_filename(item)}"


def public_reader_feature_url(article: dict) -> str:
    """專文的公開線上版 URL（狀態為 published、跑過更新線上閱讀版後才存在）。"""
    article_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_text(article.get("id")) or "article").strip("-")
    return f"{ONLINE_READER_BASE_URL}/features/{article_id}.html"


def source_public_slug(source_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_text(source_id) or "source").strip("-") or "source"


def page_public_url(page_type: str, slug: str) -> str:
    folder = "tags" if page_type == "tag" else "sources"
    return f"{ONLINE_READER_BASE_URL}/{folder}/{slug}.html"


def published_page_id(page_type: str, key: str) -> str:
    if page_type == "tag":
        slug = pdf_slugify(canonical_tag_label(key), fallback=stable_id("tag", key), limit=64)
        return f"pubpage-tag-{slug}"
    return f"pubpage-source-{source_public_slug(key)}"


def published_page_slug(page_type: str, key: str, title: str, existing_pages: list[dict] | None = None) -> str:
    if page_type == "source":
        return source_public_slug(key)
    base = pdf_slugify(canonical_tag_label(title or key), fallback="tag", limit=64)
    existing_pages = existing_pages if existing_pages is not None else load_jsonl(PUBLISHED_PAGES)
    collision = next(
        (
            page
            for page in existing_pages
            if clean_text(page.get("type")) == page_type
            and clean_text(page.get("slug")) == base
            and clean_text(page.get("key")) != clean_text(key)
        ),
        None,
    )
    if collision:
        return f"{base}-{stable_id('tag', key).removeprefix('tag-')[:8]}"
    return base


def published_page_for(page_type: str, key: str) -> dict:
    page_id = published_page_id(page_type, key)
    return next((page for page in load_jsonl(PUBLISHED_PAGES) if clean_text(page.get("id")) == page_id), {})


def publish_page_card(page_type: str, key: str, title: str, blurb: str = "") -> str:
    existing = published_page_for(page_type, key)
    slug = clean_text(existing.get("slug")) or published_page_slug(page_type, key, title)
    published = bool(existing.get("published"))
    current_blurb = clean_text(existing.get("blurb"), 1000) or clean_text(blurb, 1000)
    action = "unpublish" if published else "publish"
    button_label = "取消公開頁" if published else "產生可分享公開頁"
    toggle_text = "已公開" if published else "未公開"
    active_class = " is-on" if published else ""
    public_url = page_public_url(page_type, slug)
    url_panel = (
        f'<p class="help">下次更新線上閱讀版後生效：<a href="{h(public_url)}" target="_blank" rel="noopener" data-publish-url>{h(public_url)}</a></p>'
        f'<button type="button" class="button button-small quiet" data-copy-publish-url="{h(public_url)}">複製網址</button>'
        if published
        else '<p class="help" data-publish-url>公開後，這裡會顯示可分享網址；下次更新線上閱讀版後才會正式存在。</p>'
    )
    return f"""
<section class="card publish-page-card" data-publish-card>
  <div class="section-kicker">發布</div>
  <h2>分享這一頁</h2>
  <form method="post" action="/pages/toggle-publish" data-page-publish-form>
    <input type="hidden" name="type" value="{h(page_type)}">
    <input type="hidden" name="key" value="{h(key)}">
    <input type="hidden" name="title" value="{h(title)}">
    <input type="hidden" name="action" value="{h(action)}" data-page-publish-action>
    <input type="hidden" name="redirect" value="{h('/tags?tag=' + quote(key) if page_type == 'tag' else '/sources/view?id=' + quote(key))}">
    <label>公開頁導言</label>
    <textarea name="blurb" rows="3" placeholder="這個議題或來源適合分享給外部讀者的簡短說明。">{h(current_blurb)}</textarea>
    <div class="button-row">
      <button type="submit" class="source-toggle{active_class}" data-page-publish-button aria-label="{h(button_label)}"><span class="toggle-dot"></span><span data-page-publish-label>{h(toggle_text)}</span></button>
      <span class="muted" data-page-publish-message>{h(button_label)}</span>
    </div>
  </form>
  <div data-page-publish-output>{url_panel}</div>
</section>
"""


def resolve_final_url(url: str, timeout: int = 12) -> tuple[str, str]:
    url = unwrap_google_alert_url(clean_text(url))
    if not url:
        return "", "網址是空的。"
    headers = {"User-Agent": "IanOpenNewsBot/1.0 (+https://github.com/)"}
    for method in ["HEAD", "GET"]:
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.geturl(), ""
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in {403, 405, 501}:
                continue
            return "", str(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if method == "HEAD":
                continue
            return "", str(exc)
    return "", "無法解析跳轉網址。"


def personal_note_text(item: dict) -> str:
    notes = item.get("personal_notes")
    if isinstance(notes, dict):
        return clean_text(notes.get("body"))
    return clean_text(notes)


def looks_like_triage_placeholder(text: str) -> bool:
    normalized = clean_text(text, 1200)
    if not normalized:
        return False
    if "中文標題：" in normalized and "中文摘要：" in normalized:
        return True
    if normalized.startswith("這是一篇英文資料，主題可能和"):
        return True
    return False


PLACEHOLDER_ZH_TITLE_RE = re.compile(r"^關於[^：:\n]{1,120}的(?:英文|外文|外語|非中文)?資料[：:]\s*(?P<title>.+)$")


def clean_placeholder_zh_title(text: object, limit: int = 320) -> str:
    title = clean_text(text, limit)
    match = PLACEHOLDER_ZH_TITLE_RE.match(title)
    if match:
        return clean_text(match.group("title"), limit)
    return title


def usable_zh_title(text: object, limit: int = 320) -> str:
    title = clean_text(text, limit)
    if PLACEHOLDER_ZH_TITLE_RE.match(title):
        return ""
    return title


def item_original_summary(item: dict, limit: int = 420) -> str:
    metadata = item_reading_metadata(item)
    candidates = [
        item.get("summary"),
        metadata.get("description"),
        metadata.get("excerpt"),
        metadata.get("og_description"),
        metadata.get("twitter_description"),
    ]
    for candidate in candidates:
        text = clean_text(candidate, limit)
        if text and not looks_like_triage_placeholder(text):
            return text
    editorial = item.get("editorial_triage") or {}
    if isinstance(editorial, dict):
        text = workflow_display_text(editorial.get("zh_summary"), limit)
        if text and not looks_like_triage_placeholder(text):
            return text
    return ""


def item_zh_summary(item: dict, limit: int = 420) -> str:
    model_review = record_preferred_review(item)
    if model_review:
        text = clean_text(model_review.get("summary")) or clean_text(model_review.get("one_line_recommendation"))
        if text:
            return workflow_display_text(text, limit)
    return item_original_summary(item, limit)


def item_codex_review(item: dict) -> dict:
    return record_codex_review(item)


def item_reading_metadata(item: dict) -> dict:
    metadata = item.get("reading_metadata")
    return metadata if isinstance(metadata, dict) else {}


def item_codex_zh_title(item: dict) -> str:
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    model_review = record_preferred_review(item)
    for candidate in [model_review.get("zh_title"), editorial.get("zh_title"), editorial.get("codex_zh_title")]:
        title = usable_zh_title(candidate, 300)
        if title:
            return title
    return ""


def item_display_title(item: dict) -> str:
    metadata = item_reading_metadata(item)
    return (
        clean_text(item.get("editorial_title"), 320)
        or clean_text(metadata.get("editorial_title"), 320)
        or item_codex_zh_title(item)
        or usable_zh_title(metadata.get("translated_zh_title"), 320)
        or clean_text(item.get("title"), 320)
        or clean_text(item.get("url"), 320)
        or "未命名項目"
    )


def item_original_title(item: dict) -> str:
    metadata = item_reading_metadata(item)
    return clean_text(metadata.get("original_site_title") or metadata.get("title") or item.get("title"), 360)


def language_label(language: object) -> str:
    code = clean_text(language, 80)
    labels = {
        "zh": "中文",
        "zh-Hant": "繁體中文",
        "zh-Hans": "簡體中文",
        "en": "英文",
        "ja": "日文",
        "ko": "韓文",
        "fr": "法文",
        "de": "德文",
        "es": "西班牙文",
        "pt": "葡萄牙文",
    }
    return labels.get(code, code or "未知")


def metadata_source_label(metadata: dict, field: str) -> str:
    source = clean_text(metadata.get(f"{field}_source"), 120)
    if not source:
        return ""
    return f"（{source}）"


def item_original_language(item: dict) -> str:
    metadata = item_reading_metadata(item)
    language = clean_text(metadata.get("original_language"))
    if language:
        return language
    text = "\n".join(
        part
        for part in [
            item_article_text(item),
            clean_text(metadata.get("article_markdown"), 3000),
            clean_text(item.get("summary"), 1200),
            clean_text(item.get("title"), 300),
        ]
        if part
    )
    return infer_language_from_text(text)


def is_foreign_language_item(item: dict) -> bool:
    language = item_original_language(item)
    if not language or language in {"unknown", "und"}:
        return False
    return not language.startswith("zh")


def item_provider_translation_markdown(item: dict, provider: str) -> str:
    metadata = item_reading_metadata(item)
    provider = normalize_ai_provider(provider)
    if provider == "codex":
        return clean_markdown_text(
            metadata.get("codex_translated_article_markdown_zh")
            or metadata.get("translated_article_markdown_zh")
        )
    return clean_markdown_text(metadata.get(AI_PROVIDER_META[provider]["translation_markdown_key"]))


def item_translation_entries(item: dict) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen_markdown: set[str] = set()
    for provider in AI_PROVIDER_ORDER:
        markdown = item_provider_translation_markdown(item, provider)
        if markdown and markdown not in seen_markdown:
            entries.append((provider, markdown))
            seen_markdown.add(markdown)
    return entries


def item_translated_markdown(item: dict) -> str:
    entries = item_translation_entries(item)
    return entries[0][1] if entries else ""


def item_edited_markdown(item: dict) -> str:
    """使用者線上手動修正後的「全文」覆寫層（修排版、補截斷）。優先於自動翻譯與原文。"""
    return clean_markdown_text(item_reading_metadata(item).get("edited_markdown"))


def item_primary_markdown(item: dict) -> str:
    """目前要當主全文顯示／取用的版本：手動編輯版 > 中文翻譯 > 原始全文。
    單篇頁、線上線下閱讀版共用，確保編輯過的內容會真的取代顯示。"""
    return item_edited_markdown(item) or item_translated_markdown(item) or item_article_markdown(item)


def translation_meta_value(metadata: dict, provider: str, key: str) -> str:
    provider = normalize_ai_provider(provider)
    meta_key = AI_PROVIDER_META[provider][key]
    value = clean_text(metadata.get(meta_key))
    if value:
        return value
    if provider == "codex":
        legacy_map = {
            "translation_source_key": "translation_source",
            "translation_generated_key": "translation_generated_at",
            "translation_note_key": "translation_note",
            "translation_title_key": "translated_zh_title",
        }
        legacy_key = legacy_map.get(key)
        if legacy_key:
            return clean_text(metadata.get(legacy_key))
    return ""


def translation_actions_html(item: dict, item_id: str, redirect_to: str) -> str:
    if not (item_article_markdown(item) or item_article_text(item)):
        return ""
    if not is_foreign_language_item(item):
        return ""
    missing = [provider for provider in AI_PROVIDER_ORDER if not item_provider_translation_markdown(item, provider)]
    if not missing:
        return ""
    forms = []
    for provider in missing:
        label = ai_provider_label(provider)
        button_class = "" if provider == "codex" else "secondary"
        shortcut = "T" if provider == "codex" else "L"
        forms.append(
            "<form method='post' action='/items/translate-zh' data-translate-form>"
            f"<input type='hidden' name='id' value='{h(item_id)}'>"
            f"<input type='hidden' name='redirect' value='{h(redirect_to)}'>"
            f"<input type='hidden' name='provider' value='{h(provider)}'>"
            f"<button type='submit' class='{h(button_class)}'>{button_content(label + ' 翻譯中文', 'translate', shortcut)}</button>"
            "</form>"
        )
    metadata = item_reading_metadata(item)
    return (
        f"<div class='button-row'>{''.join(forms)}</div>"
        f"<p class='help'>偵測原文語言：{h(language_label(item_original_language(item)))}{h(metadata_source_label(metadata, 'original_language'))}。會用台灣習慣用語翻成繁體中文，並依 provider 存回本機資料庫。</p>"
    )


def translation_panels_html(item: dict, collapsed: bool = False) -> str:
    metadata = item_reading_metadata(item)
    panels = []
    for provider, markdown in item_translation_entries(item):
        label = ai_provider_label(provider)
        generated_at = translation_meta_value(metadata, provider, "translation_generated_key")
        source = translation_meta_value(metadata, provider, "translation_source_key") or label
        note = translation_meta_value(metadata, provider, "translation_note_key")
        note_html = f"<p class='help'>備註：{h(note)}</p>" if note else ""
        if collapsed:
            # 已有手動編輯版時，自動翻譯收合起來供比對（point 2）
            panels.append(
                f"""
<details class="card fulltext-panel source-card source-card--source original-fulltext-collapsible" id="translation-panel-{h(provider)}">
  <summary><div class="section-kicker">{h(label)} 自動翻譯（原始版本）</div></summary>
  <p class="help">翻譯來源：{h(source)} · {h(generated_at)}</p>
  {note_html}
  <div class="article-text article-markdown">{markdown_to_html(markdown)}</div>
</details>
"""
            )
        else:
            panels.append(
                f"""
<section class="card fulltext-panel source-card source-card--source" id="translation-panel-{h(provider)}">
  <div class="section-kicker">{h(label)} 中文翻譯</div>
  <p class="help">翻譯來源：{h(source)} · {h(generated_at)}</p>
  {note_html}
  <div class="article-text article-markdown">{markdown_to_html(markdown)}</div>
</section>
"""
            )
    return "".join(panels)


def item_article_text(item: dict) -> str:
    return clean_text(item_reading_metadata(item).get("article_text"))


def item_article_markdown(item: dict) -> str:
    metadata = item_reading_metadata(item)
    markdown = clean_markdown_text(metadata.get("article_markdown"))
    if markdown:
        return markdown
    article_text = clean_text(metadata.get("article_text"))
    if article_text:
        return text_to_markdown(article_text, title=metadata.get("title") or item.get("title") or "")
    return ""


def inline_markdown_html(text: str) -> str:
    def format_segment(segment: str) -> str:
        escaped = h(segment)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
        return escaped

    parts: list[str] = []
    position = 0
    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text):
        parts.append(format_segment(text[position : match.start()]))
        label = format_segment(match.group(1))
        url = h(match.group(2))
        parts.append(f'<a href="{url}" target="_blank" rel="noreferrer">{label}</a>')
        position = match.end()
    parts.append(format_segment(text[position:]))
    return "".join(parts)


ENGLISH_POSSESSIVE_APOSTROPHE_RE = re.compile(r"(?<=[A-Za-z])[\u2018\u2019]\s*([sS])\b")


def normalize_markdown_heading_text(text: object) -> str:
    return ENGLISH_POSSESSIVE_APOSTROPHE_RE.sub(r"'\1", str(text or ""))


def normalized_title_key(text: object) -> str:
    value = clean_text(text, 500)
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[#*_`~]+", "", value)
    value = re.sub(r"[\s\u3000]+", "", value)
    value = re.sub(r"[：:，,。．.、;；!?！？「」『』《》〈〉()（）\[\]{}\"'“”‘’—–\-_/\\|]+", "", value)
    return value.casefold()


def strip_duplicate_leading_heading(markdown: str, title: object) -> str:
    title_key = normalized_title_key(title)
    if not title_key:
        return markdown
    lines = str(markdown or "").splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        return markdown
    heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", lines[index])
    if not heading or normalized_title_key(heading.group(1)) != title_key:
        return markdown
    end = index + 1
    while end < len(lines) and not lines[end].strip():
        end += 1
    return "\n".join([*lines[:index], *lines[end:]]).lstrip()


def markdown_to_html(markdown: str, preserve_soft_breaks: bool = False) -> str:
    raw = html.unescape(str(markdown or ""))
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t\f\v]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    lines = raw.split("\n")
    parts: list[str] = []
    paragraph: list[str] = []
    code_block: list[str] = []
    list_tag = ""
    code_fence = ""

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            parts.append(f"</{list_tag}>")
            list_tag = ""

    def flush_paragraph() -> None:
        if paragraph:
            separator = "<br>\n" if preserve_soft_breaks else " "
            parts.append(f"<p>{separator.join(inline_markdown_html(line) for line in paragraph)}</p>")
            paragraph.clear()

    def flush_code_block() -> None:
        if code_fence:
            parts.append(f"<pre><code>{h(chr(10).join(code_block))}</code></pre>")
            code_block.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if code_fence:
            if re.match(rf"^{re.escape(code_fence)}\s*$", line):
                flush_code_block()
                code_fence = ""
            else:
                code_block.append(raw_line)
            continue
        if not line:
            flush_paragraph()
            close_list()
            continue
        fence = re.match(r"^(```+|~~~+)(?:\S+)?\s*$", line)
        if fence:
            flush_paragraph()
            close_list()
            code_fence = fence.group(1)
            code_block.clear()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = min(len(heading.group(1)), 5)
            heading_text = normalize_markdown_heading_text(heading.group(2))
            parts.append(f"<h{level}>{inline_markdown_html(heading_text)}</h{level}>")
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):
            flush_paragraph()
            close_list()
            parts.append("<hr>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            close_list()
            parts.append(f"<blockquote>{inline_markdown_html(line[2:])}</blockquote>")
            continue
        unordered = re.match(r"^[-*]\s+(.+)$", line)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            target_tag = "ul" if unordered else "ol"
            if list_tag != target_tag:
                close_list()
                parts.append(f"<{target_tag}>")
                list_tag = target_tag
            item_text = (unordered or ordered).group(1)
            parts.append(f"<li>{inline_markdown_html(item_text)}</li>")
            continue
        close_list()
        paragraph.append(line)

    flush_code_block()
    flush_paragraph()
    close_list()
    return "\n".join(parts) or "<p>這次沒有抓到可顯示的主文。</p>"


def item_article_html(item: dict) -> str:
    return markdown_to_html(item_article_markdown(item))


def ensure_article_markdown(item: dict) -> tuple[dict, bool]:
    metadata = item_reading_metadata(item)
    if metadata.get("article_markdown") or not metadata.get("article_text"):
        return item, False
    markdown = text_to_markdown(metadata.get("article_text"), title=metadata.get("title") or item.get("title") or "")
    if not markdown:
        return item, False
    updated = dict(item)
    updated_metadata = dict(metadata)
    updated_metadata.update(
        {
            "article_markdown": markdown,
            "article_markdown_chars": len(markdown),
            "article_markdown_method": f"{metadata.get('article_text_method', 'text')}.markdown",
            "article_markdown_status": "ok" if len(markdown) >= 280 else "short",
            "article_markdown_label": "Markdown 閱讀版",
        }
    )
    updated["reading_metadata"] = updated_metadata
    return updated, True


def markdown_source_text(item: dict) -> str:
    return item_article_markdown(item) or item_article_text(item) or clean_text(item.get("summary"))


def strip_markdown_syntax(value: object, limit: int | None = None) -> str:
    text = str(value or "")
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[#>\s-]+", "", text)
    text = re.sub(r"[*_`~]+", "", text)
    return clean_text(text, limit)


def canonical_item_url(value: object) -> str:
    url = unwrap_google_alert_url(clean_text(value, 2000))
    if not url.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(url)
    query_pairs = [
        (key, val)
        for key, val in parse_qs(parsed.query, keep_blank_values=True).items()
        if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    query = urlencode([(key, item) for key, values in query_pairs for item in values])
    normalized = parsed._replace(query=query, fragment="").geturl()
    return normalized.rstrip("/")


def item_url_keys(item: dict) -> set[str]:
    metadata = item_reading_metadata(item)
    urls = [
        item.get("url"),
        metadata.get("source_url"),
        metadata.get("final_url"),
        metadata.get("canonical_url"),
    ]
    return {key for key in (canonical_item_url(url) for url in urls) if key}


def title_from_url_path(url: str) -> str:
    path = unquote(urlparse(url).path)
    leaf = path.rsplit("/", 1)[-1]
    leaf = re.sub(r"\.(?:html?|php|aspx?|pdf|xml)$", "", leaf, flags=re.I)
    title = clean_text(re.sub(r"[-_]+", " ", leaf), 220)
    return title if len(title) >= 8 and not title.casefold().startswith("index") else ""


def markdown_link_title(markdown: str, start: int, label: str, url: str) -> str:
    clean_label = strip_markdown_syntax(label, 260)
    if clean_label.casefold() not in GENERIC_NEWSLETTER_LINK_LABELS:
        return clean_label
    context = markdown[max(0, start - 900) : start]
    same_line = context.rsplit("\n", 1)[-1]
    for pattern in [r"\*\*([^*\n]{8,260})\*\*", r"###?\s+([^\n]{8,260})"]:
        matches = re.findall(pattern, same_line)
        if matches:
            return strip_markdown_syntax(matches[-1], 260)
    for line in reversed(context.splitlines()[-10:]):
        heading = re.match(r"\s*#{2,5}\s+(.+)$", line)
        if heading:
            return strip_markdown_syntax(heading.group(1), 260)
        bold = re.findall(r"\*\*([^*\n]{8,260})\*\*", line)
        if bold:
            return strip_markdown_syntax(bold[-1], 260)
    path_title = title_from_url_path(url)
    if path_title:
        return path_title
    return host_label(url)


def markdown_link_context(markdown: str, start: int, end: int) -> str:
    before = markdown[max(0, start - 520) : start]
    after = markdown[end : min(len(markdown), end + 220)]
    return strip_markdown_syntax(f"{before} {after}", 700)


def extract_markdown_links(markdown: str, base_url: str = "") -> list[dict]:
    links: list[dict] = []
    seen: set[str] = set()
    pattern = re.compile(r"\[([^\]]{1,500})\]\((https?://[^)\s]+)\)")
    for index, match in enumerate(pattern.finditer(markdown)):
        url = canonical_item_url(urljoin(base_url, html.unescape(match.group(2))))
        if not url or url in seen:
            continue
        seen.add(url)
        label = strip_markdown_syntax(match.group(1), 220)
        title = markdown_link_title(markdown, match.start(), label, url)
        links.append(
            {
                "index": index,
                "url": url,
                "label": label,
                "title": title,
                "context": markdown_link_context(markdown, match.start(), match.end()),
            }
        )
    return links


def classify_newsletter_link(item: dict, link: dict) -> tuple[bool, str]:
    url = canonical_item_url(link.get("url"))
    if not url:
        return False, "不是可抓取網址"
    if url in item_url_keys(item):
        return False, "和電子報本身相同"
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    label = clean_text(link.get("label"), 220)
    title = clean_text(link.get("title"), 300)
    context = clean_text(link.get("context"), 800)
    haystack = f"{label}\n{title}\n{url}\n{context}"
    functional_haystack = f"{label}\n{title}\n{url}"
    if any(domain in host for domain in ["mailerlite", "mailchimp", "list-manage.com", "linkedin.com", "x.com", "twitter.com", "facebook.com"]):
        return False, "功能性或社群連結"
    if re.search(r"/(?:series|categor(?:y|ies)|tags?|authors?|contributors?)(?:/|$)", parsed.path, re.I):
        return False, "系列、分類或作者索引頁"
    if NEWSLETTER_FUNCTIONAL_LINK_RE.search(functional_haystack):
        return False, "功能性 / 機會型連結"
    if label.casefold() in GENERIC_NEWSLETTER_LINK_LABELS and len(title) >= 8:
        return True, "電子報 Read more 連結"
    if NEWSLETTER_ARTICLE_LINK_RE.search(url):
        return True, "網址型態像文章、報告或 PDF"
    if NEWSLETTER_ARTICLE_TITLE_RE.search(title) and len(title) >= 18:
        return True, "標題型態像文章或報告"
    return False, "不像獨立文章"


def newsletter_link_candidates(item: dict) -> tuple[list[dict], list[dict]]:
    markdown = markdown_source_text(item)
    if not markdown:
        return [], []
    candidates: list[dict] = []
    skipped: list[dict] = []
    for link in extract_markdown_links(markdown, clean_text(item.get("url"))):
        keep, reason = classify_newsletter_link(item, link)
        record = {**link, "reason": reason}
        if keep:
            candidates.append(record)
        else:
            skipped.append(record)
    return candidates, skipped


def ensure_derived_source(sources: list[dict], track: str, source_name: str, site_url: str = "") -> tuple[str, bool]:
    clean_name = source_name or host_label(site_url) or "Newsletter link"
    source_id = stable_id("src", "newsletter-link", clean_name)
    if any(clean_text(source.get("id")) == source_id for source in sources):
        return source_id, False
    sources.append(
        {
            "id": source_id,
            "track": track,
            "name": clean_name,
            "source_group": "Newsletter links",
            "source_type": "manual",
            "fetch_frequency": "daily",
            "feed_url": "",
            "site_url": site_url,
            "status": "active",
            "required_keywords": [],
            "excluded_keywords": [],
            "notes": "由彙整式電子報拆出的子文章來源。",
        }
    )
    return source_id, True


def build_newsletter_child_item(parent: dict, link: dict, captured_at: str, keyword_config: dict, editorial_context: dict) -> tuple[dict, dict]:
    url = canonical_item_url(link.get("url"))
    title = clean_text(link.get("title"), 300) or host_label(url)
    summary = clean_text(link.get("context"), 1200)
    track = clean_text(parent.get("track")) or "unclassified"
    record = {
        "id": stable_id("item", "newsletter-link", url, title),
        "track": track,
        "status": "inbox",
        "priority": "normal",
        "title": title,
        "url": url,
        "source_id": "",
        "source_name": host_label(url),
        "author": "",
        "published_at": "",
        "captured_at": captured_at,
        "summary": summary,
        "tags": item_visible_tags(parent, 8),
        "origin": "newsletter-link",
        "reference": {
            "created_by": "local_web",
            "created_from": "newsletter-link-extractor",
            "parent_item_id": clean_text(parent.get("id")),
            "parent_title": item_display_title(parent),
            "parent_url": clean_text(parent.get("url")),
            "link_label": clean_text(link.get("label")),
            "link_reason": clean_text(link.get("reason")),
        },
        "review": default_review("從彙整式電子報拆出的子文章；需照一般入庫建檔流程判斷是否收錄。"),
    }
    enriched, _did_change, error = enrich_item_metadata(record)
    metadata = item_reading_metadata(enriched)
    if metadata.get("title") and (title == host_label(url) or clean_text(link.get("label")).casefold() in GENERIC_NEWSLETTER_LINK_LABELS):
        enriched["title"] = clean_text(metadata.get("title"), 300)
    if metadata.get("description") or metadata.get("excerpt"):
        enriched["summary"] = clean_text(metadata.get("description") or metadata.get("excerpt"), 1200)
    final_url = canonical_item_url(metadata.get("final_url") or enriched.get("url"))
    site_url = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}" if final_url else url
    source_name = clean_text(metadata.get("original_author"), 160) or host_label(final_url or url)
    enriched["source_name"] = source_name
    enriched["author"] = source_name
    enriched["triage"] = evaluate_triage(enriched, keyword_config)
    enriched["editorial_triage"] = evaluate_editorial_triage(enriched, keyword_config, editorial_context)
    if error:
        reference = enriched.get("reference") if isinstance(enriched.get("reference"), dict) else {}
        enriched["reference"] = {**reference, "metadata_fetch_error": clean_text(error, 500)}
    return enriched, {"source_name": source_name, "site_url": site_url}


def update_newsletter_extraction_metadata(parent: dict, stats: dict) -> dict:
    updated = dict(parent)
    metadata = dict(item_reading_metadata(updated))
    metadata["newsletter_link_extraction"] = stats
    updated["reading_metadata"] = metadata
    updated["review"] = append_review_note(
        updated.get("review") or {},
        f"{stats.get('extracted_at')} 彙整式電子報拆 link：新增 {stats.get('imported_count', 0)} 筆，重複 {stats.get('duplicate_count', 0)} 筆，略過 {stats.get('skipped_count', 0)} 筆。",
    )
    return updated


def _split_paragraph_by_sentence(text: str, max_chars: int) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+", text) if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current:
            separator = " " if re.search(r"[A-Za-z0-9,)\]\"']$", current) else ""
            candidate = current + separator + sentence
        else:
            candidate = sentence
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text.strip()]


def soften_long_paragraphs(markdown: str, max_chars: int = 520) -> str:
    """把過長的散文段落依句界切成多段，方便閱讀；跳過表格、標題、清單與程式碼。"""
    if not markdown:
        return markdown
    out: list[str] = []
    for block in re.split(r"\n\s*\n", markdown):
        stripped = block.strip()
        if not stripped:
            continue
        skip = (
            len(stripped) <= max_chars
            or stripped.startswith("#")
            or "|" in stripped
            or "```" in stripped
            or bool(re.match(r"^\s*(?:[-*+>]|\d+\.)\s", stripped))
        )
        if skip:
            out.append(stripped)
            continue
        out.extend(_split_paragraph_by_sentence(stripped, max_chars))
    return "\n\n".join(out)


def item_markdown_needs_paragraphs(item: dict) -> bool:
    """判斷全文是否缺乏段落結構（適合用 AI 重新分段）。"""
    markdown = str(item_reading_metadata(item).get("article_markdown") or "")
    if len(markdown) < 1200:
        return False
    paragraphs = [p for p in re.split(r"\n\s*\n", markdown) if p.strip()]
    if not paragraphs:
        return True
    longest = max(len(p) for p in paragraphs)
    return longest > 1500 or (len(markdown) / max(1, len(paragraphs))) > 1100


def normalize_pdf_markdown_item(item: dict) -> tuple[dict, bool, str]:
    metadata = dict(item_reading_metadata(item))
    raw_markdown = str(metadata.get("article_markdown") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    raw = raw_markdown or clean_text(metadata.get("article_text")) or clean_text(item.get("summary"))
    if len(raw) < 240:
        return item, False, "沒有足夠文字可轉成 PDF Markdown 全文。"
    title = item_original_title(item) or item_display_title(item)
    markdown_like = bool(raw_markdown or re.search(r"(?m)^#{1,6}\s+\S|\[[^\]]+\]\(https?://|^\s*[-*]\s+", raw))
    markdown = raw if markdown_like else text_to_markdown(raw, title=title)
    markdown = soften_long_paragraphs(markdown)
    updated = dict(item)
    metadata.update(
        {
            "article_text": raw,
            "article_text_chars": len(raw),
            "article_text_method": metadata.get("article_text_method") or "pdf-markitdown-summary",
            "article_text_status": "ok" if len(raw) >= 280 else "short",
            "article_text_label": "PDF MarkItDown 文字",
            "article_markdown": markdown,
            "article_markdown_chars": len(markdown),
            "article_markdown_method": "pdf-markitdown",
            "article_markdown_status": "ok" if len(markdown) >= 280 else "short",
            "article_markdown_label": "PDF MarkItDown 全文",
            "pdf_markdown_normalized_at": now_iso(),
        }
    )
    if not clean_text(metadata.get("content_type")):
        metadata["content_type"] = "application/pdf"
    language = infer_language_from_text(raw)
    if language and not clean_text(metadata.get("original_language")):
        metadata["original_language"] = language
        metadata["original_language_source"] = "PDF 文字推斷"
    updated["reading_metadata"] = metadata
    reference = updated.get("reference") if isinstance(updated.get("reference"), dict) else {}
    updated["reference"] = {**reference, "pdf_markdown_normalized_at": metadata["pdf_markdown_normalized_at"]}
    updated["review"] = append_review_note(
        updated.get("review") or {},
        f"{metadata['pdf_markdown_normalized_at']} 已將 PDF / MarkItDown 文字補成 reading_metadata.article_markdown，後續模型建議與編輯台會以全文為優先。",
    )
    updated, _changed = complete_item_metadata(updated)
    return updated, updated != item, ""


def item_is_pdf_like(item: dict) -> bool:
    metadata = item_reading_metadata(item)
    content_type = clean_text(metadata.get("content_type")).casefold()
    url = clean_text(item.get("url")).casefold()
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    file_path = clean_text(reference.get("file")).casefold()
    return (
        item.get("origin") == "manual-pdf"
        or item.get("source_type") == "pdf-upload"
        or "pdf" in content_type
        or url.endswith(".pdf")
        or ".pdf?" in url
        or file_path.endswith(".pdf")
    )


FULLTEXT_SIGNAL_RE = re.compile(
    r"(?:全文|閱讀全文|完整報告|完整論文|read\s+the\s+full|full\s+text|full\s+paper|full\s+report)",
    re.I,
)


def item_has_fulltext_signal(item: dict) -> bool:
    metadata = item_reading_metadata(item)
    if clean_text(metadata.get("needs_fulltext")).casefold() in {"1", "true", "yes"}:
        return True
    if clean_text(metadata.get("preferred_fulltext_url") or metadata.get("fulltext_source_url")):
        return True
    if clean_text(metadata.get("access_issue")):
        return True
    if clean_text(metadata.get("fulltext_status")) in {"blocked", "needs-manual"}:
        return True
    haystack = "\n".join(
        [
            clean_text(item.get("title"), 800),
            clean_text(item.get("summary"), 2400),
            clean_text(metadata.get("description"), 1600),
            clean_text(metadata.get("excerpt"), 2400),
            clean_text(metadata.get("article_text"), 6000),
        ]
    )
    return bool(FULLTEXT_SIGNAL_RE.search(haystack))


def ensure_pdf_upload_source(sources: list[dict], track: str) -> tuple[str, bool]:
    source_id = stable_id("src", "local-pdf-uploads", track)
    if any(clean_text(source.get("id")) == source_id for source in sources):
        return source_id, False
    sources.append(
        {
            "id": source_id,
            "track": track,
            "name": "本機 PDF 上傳",
            "source_group": "Manual PDF upload",
            "source_type": "manual",
            "fetch_frequency": "on-update",
            "feed_url": "",
            "site_url": "",
            "status": "active",
            "required_keywords": [],
            "excluded_keywords": [],
            "notes": "由本機網頁上傳；PDF 本體只存於 gitignored 的 .cache/uploads/。",
        }
    )
    return source_id, True


def material_link_exists(item_id: str, ref: str, relation: str) -> bool:
    return any(
        clean_text(link.get("item_id")) == item_id
        and clean_text(link.get("ref")) == ref
        and clean_text(link.get("relation")) == relation
        for link in load_jsonl(MATERIAL_LINKS)
    )


def append_material_link(item_id: str, ref: str, title: str, relation: str, *, direction: str = "") -> None:
    if not item_id or not ref or material_link_exists(item_id, ref, relation):
        return
    append_jsonl(
        MATERIAL_LINKS,
        {
            "id": stable_id("link", item_id, ref, relation),
            "item_id": item_id,
            "ref": ref,
            "ref_kind": "item",
            "title": title or ref,
            "relation": relation,
            "direction": direction,
            "created_at": now_iso(),
        },
    )


def link_materials(left: dict, right: dict, relation: str) -> None:
    left_id = clean_text(left.get("id"))
    right_id = clean_text(right.get("id"))
    append_material_link(left_id, right_id, item_display_title(right), relation, direction="outbound")
    append_material_link(right_id, left_id, item_display_title(left), relation, direction="inbound")


def pdf_relation_label(relation: str) -> str:
    return {
        "full-source": "全文來源",
        "subset": "節錄 / 子集",
        "related": "主題相關",
        "same-source": "同一來源",
        "split-from": "由 PDF 拆出",
    }.get(relation, relation or "相關")


def pdf_split_source_markdown(item: dict) -> str:
    translated = item_translated_markdown(item)
    if translated:
        return translated
    metadata = item_reading_metadata(item)
    return str(metadata.get("article_markdown") or metadata.get("article_text") or item.get("summary") or "").strip()


def slice_markdown_by_markers(markdown: str, start_marker: str, end_marker: str, start_at: int = 0) -> tuple[str, int, str]:
    start = markdown.find(start_marker, start_at)
    if start < 0:
        return "", start_at, f"找不到起始標記：{clean_text(start_marker, 120)}"
    end_start = markdown.find(end_marker, start + len(start_marker))
    if end_start < 0:
        return "", start_at, f"找不到結束標記：{clean_text(end_marker, 120)}"
    end = end_start + len(end_marker)
    return markdown[start:end].strip(), end, ""


def _loose_marker_span(haystack: str, marker: str, start_at: int = 0) -> tuple[int, int] | None:
    """寬鬆定位標記：先精確找，找不到再忽略大小寫與空白差異。回傳 (起, 訖) 絕對位置。"""
    marker = (marker or "").strip()
    if not marker:
        return None
    idx = haystack.find(marker, start_at)
    if idx >= 0:
        return idx, idx + len(marker)
    collapsed = re.sub(r"\s+", " ", marker)
    pattern = re.escape(collapsed).replace("\\ ", r"\s+")
    match = re.search(pattern, haystack[start_at:], re.I | re.S)
    if match:
        return start_at + match.start(), start_at + match.end()
    return None


def slice_markdown_loose(markdown: str, start_marker: str, end_marker: str) -> tuple[str, bool, bool, str]:
    """回傳 (內文, 起始是否定位, 結束是否定位, 錯誤訊息)。整篇搜尋、彼此獨立，方便部分成功。"""
    start_span = _loose_marker_span(markdown, start_marker)
    if not start_span:
        return "", False, False, f"找不到起始標記：{clean_text(start_marker, 120)}"
    end_span = _loose_marker_span(markdown, end_marker, start_span[1])
    if not end_span:
        return "", True, False, f"找不到結束標記：{clean_text(end_marker, 120)}"
    return markdown[start_span[0] : end_span[1]].strip(), True, True, ""


def item_cached_image_url(item: dict) -> str:
    metadata = item_reading_metadata(item)
    cache = metadata.get("image_cache")
    if not isinstance(cache, dict):
        return ""
    local_path = clean_text(cache.get("path"))
    reader_url = clean_text(cache.get("reader_url"))
    if local_path and (ROOT / local_path).exists():
        if reader_url:
            return "/" + reader_url.lstrip("/")
        if local_path.startswith("docs/reader/"):
            return "/" + local_path.removeprefix("docs/").lstrip("/")
    return ""


def item_image_url(item: dict) -> str:
    cached = item_cached_image_url(item)
    if cached:
        return cached
    candidates = [
        item.get("image"),
        item.get("image_url"),
        item.get("thumbnail"),
    ]
    reference = item.get("reference") or {}
    reading_metadata = item.get("reading_metadata") or {}
    if isinstance(reading_metadata, dict):
        candidates.extend(
            [
                reading_metadata.get("image_url"),
                reading_metadata.get("og_image"),
                reading_metadata.get("twitter_image"),
            ]
        )
    if isinstance(reference, dict):
        candidates.extend(
            [
                reference.get("image"),
                reference.get("image_url"),
                reference.get("thumbnail"),
                reference.get("og_image"),
            ]
        )
        raw_columns = reference.get("raw_columns")
        if isinstance(raw_columns, dict):
            candidates.extend(
                [
                    raw_columns.get("image"),
                    raw_columns.get("Image"),
                    raw_columns.get("圖片"),
                    raw_columns.get("封面"),
                ]
            )
    summary = str(item.get("summary") or "")
    candidates.extend(re.findall(r"""<img[^>]+src=["']([^"']+)["']""", summary, flags=re.I))
    candidates.extend(re.findall(r"""https?://[^\s"'<>]+?\.(?:png|jpe?g|webp)(?:\?[^\s"'<>]*)?""", summary, flags=re.I))
    for candidate in candidates:
        value = clean_text(candidate)
        if value.startswith(("http://", "https://")):
            return value
    return ""


def feature_hero_image(article: dict, lookup: dict) -> tuple[str, str]:
    """專文題圖：依引用順序取第一個有圖的引用材料，回傳 (image_url, 來源材料標題)。
    沒有任何引用材料帶圖時回傳 ("", "")。online/offline 共用。"""
    for item_id in article.get("item_ids") or []:
        rec = lookup.get(clean_text(item_id))
        if not rec:
            continue
        url = item_image_url(rec)
        if url:
            return url, item_display_title(rec)
    return "", ""


LAYOUT_MODES = ["card", "list", "compact"]
READER_TIME_FILTERS = [
    ("three-days", "這三天（-3 天）"),
    ("week", "這一週"),
    ("month", "這一個月（-30 天）"),
    ("quarter", "這一季"),
    ("year", "這一年"),
    ("custom", "自定時間範圍"),
    ("all", "全部"),
]


def layout_icon(mode: str) -> str:
    icons = {
        "card": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="7" height="7" rx="1.5"></rect><rect x="13" y="4" width="7" height="7" rx="1.5"></rect><rect x="4" y="13" width="7" height="7" rx="1.5"></rect><rect x="13" y="13" width="7" height="7" rx="1.5"></rect></svg>',
        "list": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="5" rx="1.5"></rect><rect x="4" y="14" width="16" height="5" rx="1.5"></rect></svg>',
        "compact": '<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="8" y1="6" x2="20" y2="6"></line><line x1="8" y1="12" x2="20" y2="12"></line><line x1="8" y1="18" x2="20" y2="18"></line><circle cx="4" cy="6" r="1.5"></circle><circle cx="4" cy="12" r="1.5"></circle><circle cx="4" cy="18" r="1.5"></circle></svg>',
    }
    return icons.get(mode, icons["list"])


def layout_label(mode: str) -> str:
    return {"card": "卡片", "list": "列表", "compact": "清單"}.get(mode, "列表")


def action_icon(action: str) -> str:
    icons = {
        "read": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"></path><path d="M8 7h8"></path><path d="M8 11h7"></path></svg>',
        "expand": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5"></path><path d="M3 3l7 7"></path><path d="M16 21h5v-5"></path><path d="M21 21l-7-7"></path></svg>',
        "external": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7"></path><path d="M21 3l-9 9"></path><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"></path></svg>',
        "wand": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 4V2"></path><path d="M15 16v-2"></path><path d="M8 9H6"></path><path d="M20 9h-2"></path><path d="M17.8 6.2l1.4-1.4"></path><path d="M10.8 13.2l-7 7a1.5 1.5 0 0 0 2.1 2.1l7-7"></path><path d="M12 8l4 4"></path></svg>',
        "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11l9-8 9 8"></path><path d="M5 10v10h14V10"></path><path d="M9 20v-6h6v6"></path></svg>',
        "globe": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18"></path><path d="M12 3a14 14 0 0 1 0 18"></path><path d="M12 3a14 14 0 0 0 0 18"></path></svg>',
        "archive": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M6 7v13h12V7"></path><path d="M4 4h16v3H4z"></path><path d="M9 11h6"></path></svg>',
        "workspace": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="14" rx="2"></rect><path d="M8 20h8"></path><path d="M12 18v2"></path><path d="M7 8h5"></path><path d="M7 12h10"></path></svg>',
        "rss": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5a14 14 0 0 1 14 14"></path><path d="M5 11a8 8 0 0 1 8 8"></path><circle cx="6" cy="18" r="1.5"></circle></svg>',
        "inbox": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13l2-7h12l2 7"></path><path d="M4 13v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5h-5a3 3 0 0 1-6 0z"></path></svg>',
        "plus": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>',
        "settings": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"></path><path d="M4 12h2"></path><path d="M18 12h2"></path><path d="M12 4v2"></path><path d="M12 18v2"></path><path d="M6.3 6.3l1.4 1.4"></path><path d="M16.3 16.3l1.4 1.4"></path><path d="M17.7 6.3l-1.4 1.4"></path><path d="M7.7 16.3l-1.4 1.4"></path></svg>',
        "filter": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16"></path><path d="M7 12h10"></path><path d="M10 19h4"></path></svg>',
        "source": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13"></path><path d="M8 12h13"></path><path d="M8 18h13"></path><circle cx="4" cy="6" r="1.5"></circle><circle cx="4" cy="12" r="1.5"></circle><circle cx="4" cy="18" r="1.5"></circle></svg>',
        "check-circle": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M8 12l2.5 2.5L16 9"></path></svg>',
        "pulse": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 13h4l2-7 4 14 2-7h6"></path></svg>',
        "database": '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"></ellipse><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5"></path><path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"></path></svg>',
        "publish": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4"></path><path d="M7 9l5-5 5 5"></path><path d="M5 20h14"></path></svg>',
        "image": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"></rect><circle cx="8" cy="10" r="1.5"></circle><path d="M21 16l-5-5-4 4-2-2-5 5"></path></svg>',
        "text-lines": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14"></path><path d="M5 10h14"></path><path d="M5 14h10"></path><path d="M5 18h12"></path></svg>',
        "sparkle": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"></path><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"></path></svg>',
        "branch": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="6" r="2"></circle><circle cx="18" cy="6" r="2"></circle><circle cx="12" cy="18" r="2"></circle><path d="M8 6h8"></path><path d="M6 8v2a8 8 0 0 0 6 7.7"></path><path d="M18 8v2a8 8 0 0 1-6 7.7"></path></svg>',
        "chart": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V5"></path><path d="M4 19h16"></path><rect x="7" y="11" width="3" height="5"></rect><rect x="12" y="8" width="3" height="8"></rect><rect x="17" y="6" width="3" height="10"></rect></svg>',
        "save": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h12l2 2v14H5z"></path><path d="M8 4v6h8V4"></path><path d="M8 20v-6h8v6"></path></svg>',
        "accept": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l4 4L19 6"></path><path d="M5 20h14"></path></svg>',
        "small-news": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2"></rect><path d="M8 9h8"></path><path d="M8 13h5"></path><path d="M8 17h8"></path></svg>',
        "reject": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M8 8l8 8"></path><path d="M16 8l-8 8"></path></svg>',
        "select": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"></rect><path d="M8 12l3 3 5-6"></path></svg>',
        "clear": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12"></path><path d="M18 6L6 18"></path></svg>',
        "preview": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
        "refresh": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5"></path><path d="M4 18v-5h5"></path><path d="M19 11a7 7 0 0 0-12-4"></path><path d="M5 13a7 7 0 0 0 12 4"></path></svg>',
        "edit": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11a2.5 2.5 0 0 0-4-4L4 16z"></path><path d="M13 6l5 5"></path></svg>',
        "share": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"></path><path d="M7 8l5-5 5 5"></path><path d="M5 12v7h14v-7"></path></svg>',
        "copy": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>',
        "translate": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h10"></path><path d="M9 5v14"></path><path d="M4 19h10"></path><path d="M16 10h4l-2 8"></path><path d="M15 18h6"></path></svg>',
        "note": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5z"></path><path d="M8 8h8"></path><path d="M8 12h8"></path><path d="M8 16h5"></path></svg>',
        "tag": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 13.5l-7 7a2 2 0 0 1-2.8 0L3 12.8V4h8.8l8.7 8.7a2 2 0 0 1 0 2.8z"></path><circle cx="7.5" cy="8" r="1.5"></circle></svg>',
        "bookmark": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h12v17l-6-4-6 4z"></path></svg>',
        "sidebar": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"></rect><path d="M15 4v16"></path><path d="M18 9l-2 3 2 3"></path></svg>',
        "search": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M16.5 16.5L21 21"></path></svg>',
        "back": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 18l-6-6 6-6"></path><path d="M9 12h12"></path></svg>',
        "previous": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 18l-6-6 6-6"></path></svg>',
        "next": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18l6-6-6-6"></path></svg>',
    }
    return icons.get(action, icons["read"])


def icon_span(action: str, shortcut: str = "", class_name: str = "icon") -> str:
    shortcut = clean_text(shortcut, 8).upper()
    shortcut_html = f'<span class="shortcut-hint">⌥{h(shortcut)}</span>' if shortcut else ""
    shortcut_attr = f' data-shortcut="{h(shortcut)}"' if shortcut else ""
    return f'<span class="{h(class_name)}" aria-hidden="true"{shortcut_attr}>{action_icon(action)}{shortcut_html}</span>'


def button_content(label: str, action: str, shortcut: str = "") -> str:
    return f'{icon_span(action, shortcut)}<span>{h(label)}</span>'


def back_nav_html(href: str, label: str = "上一頁") -> str:
    """全站統一的「上一頁」返回列，比照單篇材料頁樣式。"""
    return (
        '<nav class="article-top-nav" aria-label="返回">'
        f'<a class="button article-back-button" href="{h(href or "/")}">{icon_span("back", "", "icon")}{h(label)}</a>'
        "</nav>"
    )


def action_label(label: str) -> str:
    return f'<span class="reader-action-label">{h(label)}</span>'


def help_dot(text: str) -> str:
    text = clean_text(text, 500)
    return f'<span class="help-dot" title="{h(text)}">?</span>' if text else ""


def workspace_sidebar_toggle(layout_id: str, sidebar_id: str, storage_key: str, label: str = "工具欄") -> str:
    return (
        f'<button type="button" class="workspace-sidebar-toggle quiet" '
        f'data-workspace-toggle data-workspace-target="{h(layout_id)}" '
        f'data-sidebar-target="{h(sidebar_id)}" data-sidebar-storage-key="{h(storage_key)}" '
        f'aria-controls="{h(sidebar_id)}" aria-expanded="true" title="顯示或隱藏{h(label)}">'
        f'{icon_span("sidebar", "", "icon")}<span data-sidebar-toggle-label>隱藏{h(label)}</span></button>'
    )


def layout_toggle(section_id: str, current: str = "list") -> str:
    current = current if current in LAYOUT_MODES else "list"
    buttons = []
    for mode in LAYOUT_MODES:
        active = " is-active" if mode == current else ""
        buttons.append(
            f"""
<button type="button" class="layout-toggle-button{active}" data-layout-target="{h(section_id)}" data-layout-mode="{h(mode)}" aria-pressed="{str(mode == current).lower()}" title="{h(layout_label(mode))}">
  {layout_icon(mode)}
  <span>{h(layout_label(mode))}</span>
</button>
"""
        )
    return f'<div class="layout-toggle" role="group" aria-label="顯示模式">{"".join(buttons)}</div>'


def material_layout_toggle(target_id: str, current: str = "list") -> str:
    """材料頁 2-mode 顯示切換（列表式詳細卡 / 清單式精簡列）；沿用 .layout-toggle 樣式與切換 JS。"""
    modes = [("list", "列表式", "list"), ("compact", "清單式", "compact")]
    buttons = []
    for mode, label, icon in modes:
        active = " is-active" if mode == current else ""
        buttons.append(
            f'<button type="button" class="layout-toggle-button{active}" '
            f'data-layout-target="{h(target_id)}" data-layout-mode="{h(mode)}" '
            f'aria-pressed="{str(mode == current).lower()}" title="{h(label)}">'
            f"{layout_icon(icon)}<span>{h(label)}</span></button>"
        )
    return f'<div class="layout-toggle" role="group" aria-label="顯示模式">{"".join(buttons)}</div>'


def is_reader_item(item: dict) -> bool:
    if item.get("status") in {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}:
        return True
    decision = item.get("local_decision") or {}
    return isinstance(decision, dict) and decision.get("action") in {"accepted-for-editing", "direct-pr-small-news"}


def item_detail_panel_id(item: dict) -> str:
    raw_id = clean_text(item.get("id"), 160)
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", raw_id).strip("-")
    if not safe_id:
        safe_id = stable_id("item-panel", item.get("title", ""), item.get("url", ""))
    return f"candidate-detail-{safe_id}"


def model_review_card_html(provider: str, review: dict, compact: bool = False) -> str:
    label = ai_provider_label(provider)
    one_line = workflow_display_text(review.get("one_line_recommendation"), 420)
    summary = workflow_display_text(review.get("summary"), 900)
    reasons = review.get("reasons") or []
    reason_rows = "<ol class='reason-list'>" + "".join(f"<li>{h(workflow_display_text(reason))}</li>" for reason in reasons[:3]) + "</ol>" if reasons and not compact else ""
    summary_html = f"<p class='zh-summary'>{h(summary)}</p>" if summary and not compact else ""
    confidence = confidence_score_10(review.get("confidence"))
    confidence_badge = badge(f"信心 {score_label(confidence)}/10", "neutral") if confidence else ""
    generated_badge = badge(str(review.get("generated_at", "")), "neutral") if review.get("generated_at") and not compact else ""
    basis_badge = badge("需要補全文" if review.get("needs_fulltext") else "依可讀資料判斷", "neutral")
    return (
        "<div class='source-card source-card--model'>"
        f"<div class='section-kicker'>{h(label)} 生成</div>"
        "<h3>給 Ian 的閱讀建議</h3>"
        f"{badge('來源：' + label, 'suggest-keep')}"
        f"{badge(model_recommendation_label(review), model_recommendation_badge_class(review))}"
        f"{confidence_badge}"
        f"{basis_badge}"
        f"{generated_badge}"
        f"<p class='recommendation-line'>{h(one_line)}</p>"
        f"{reason_rows}"
        f"{summary_html}"
        "</div>"
    )


def item_compact_row(item: dict) -> str:
    """材料「清單式」精簡列：軌道｜旗標｜建議｜分數｜標題 + 時間靠右，下一行 AI 一句話。≤3 行。
    與詳細卡共用同一張 .candidate-card 的 checkbox，只是切換顯示的 body。"""
    css_class = track_class(item.get("track", "unclassified"))
    recommendation = candidate_recommendation(item)
    scores = candidate_priority_scores(item)
    overall_label = score_label(scores["overall"])
    confidence_label = score_label(scores["confidence"])
    reviews = record_model_reviews(item)
    ai_line = ""
    if reviews:
        provider, review = reviews[-1]  # 取最新一筆 review
        bits = [f"{ai_provider_label(provider)} 生成"]
        head = "閱讀建議 " + " · ".join(bits)
        one_line = workflow_display_text(review.get("one_line_recommendation"), 140)
        ai_line = f'<p class="compact-rec">{h(head)}{("：" + h(one_line)) if one_line else ""}</p>'
    badges = (
        f'{badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}'
        f'{reader_flag_badges(item)}'
        f'{badge(recommendation_label(recommendation), recommendation)}'
        f'{badge(f"綜合 {overall_label}/10", "neutral")}'
        f'{badge(f"信心 {confidence_label}/10", "neutral")}'
    )
    detail_id = item_detail_panel_id(item)
    return (
        '<div class="candidate-compact">'
        '<div class="compact-head">'
        f'<button type="button" class="candidate-expand-toggle" data-item-expand aria-controls="{h(detail_id)}" '
        f'aria-expanded="false" aria-label="展開這則材料" title="展開這則材料"><span class="candidate-expand-triangle" aria-hidden="true"></span></button>'
        f'<span class="compact-badges">{badges}</span>'
        f'<span class="compact-time">{h(item_display_time(item, "published_at", "captured_at"))}</span>'
        "</div>"
        f'<a class="compact-title" href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a>'
        f"{ai_line}"
        "</div>"
    )


def model_review_actions_html(item: dict, compact: bool = False) -> str:
    if compact:
        return ""
    missing_providers = [provider for provider in AI_PROVIDER_ORDER if not record_model_review(item, provider)]
    if not missing_providers:
        return ""
    has_article_text = bool(item_article_markdown(item) or item_article_text(item))
    forms = []
    for provider in missing_providers:
        label = ai_provider_label(provider)
        button_label = f"{label} 生成建議" if has_article_text else f"抓全文並用 {label} 生成建議"
        button_class = "" if provider == "codex" else "secondary"
        forms.append(
            "<form method='post' action='/items/codex-review' data-codex-review-form>"
            f"<input type='hidden' name='id' value='{h(item.get('id'))}'>"
            f"<input type='hidden' name='redirect' value='{h(item_detail_href(item))}'>"
            "<input type='hidden' name='with_fulltext' value='1'>"
            f"<input type='hidden' name='provider' value='{h(provider)}'>"
            f"<button type='submit' class='{h(button_class)}'>{button_content(button_label, 'sparkle', 'C' if provider == 'codex' else 'L')}</button>"
            "</form>"
        )
    return (
        "<div class='source-card source-card--model source-card--empty'>"
        "<div class='section-kicker'>模型建議</div>"
        "<h3>生成閱讀建議</h3>"
        "<p class='help'>有哪個模型先生成，就先顯示哪張卡；需要交叉比較時，可再補其他模型。多個模型都有生成時會各自顯示成一張卡。</p>"
        f"<div class='button-row'>{''.join(forms)}</div>"
        "</div>"
    )


def editorial_triage_html(item: dict, compact: bool = False, reject_action: str = "/items/reject") -> str:
    editorial = item.get("editorial_triage") or {}
    if not isinstance(editorial, dict):
        editorial = {}
    recommendation = editorial.get("recommendation", "")
    confidence = editorial.get("confidence", "")
    if not editorial:
        return "<p class='help'>自動規則判斷：尚未重跑。可到首頁或關鍵字頁按「重新跑本機規則/關鍵字初篩」。</p>"
    display_kind = item_display_kind(item)
    model_html = "".join(model_review_card_html(provider, review, compact=compact) for provider, review in record_model_reviews(item))
    model_html += model_review_actions_html(item, compact=compact)

    article_text = item_article_text(item)
    metadata = item_reading_metadata(item)
    source_text = article_text or clean_text(metadata.get("excerpt"), 900) or clean_text(item.get("summary"), 900)
    source_label = "原始主文" if article_text else "RSS/頁面摘要"
    source_html = ""
    if not compact:
        source_html = (
            "<div class='source-card source-card--source'>"
            f"<div class='section-kicker'>{h(source_label)}</div>"
            "<h3>本來文章的內容</h3>"
            f"{badge('已抓主文' if article_text else '尚未抓全文', 'neutral')}"
            f"{badge(str(metadata.get('article_text_method', 'metadata')), 'neutral') if metadata else ''}"
            f"<p class='source-excerpt'>{h(clean_text(source_text, 900))}</p>"
            "</div>"
        )

    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    matched = "、".join(triage.get("matched_keywords") or []) or "無"
    skipped = "、".join(triage.get("skip_keywords") or []) or "無"
    keyword_html = (
        f"<p class='help'>關鍵字第一層判斷：建議：{h(recommendation_label(triage.get('recommendation', 'unknown')))}<br>"
        f"理由：{h(workflow_display_text(triage.get('reason', '未標示')))}<br>"
        f"命中：{h(matched)}<br>排除：{h(skipped)}</p>"
        if triage
        else ""
    )
    reasons = editorial.get("view_reasons") or []
    reason_rows = ""
    if reasons and not compact:
        reason_rows = "<ol class='reason-list'>" + "".join(f"<li>{h(reason)}</li>" for reason in reasons[:3]) + "</ol>"
    deletion = editorial.get("deletion_pattern_fit") or {}
    deletion_signals = deletion.get("signals") or []
    deletion_html = ""
    if recommendation == "suggest-skip" and deletion_signals and not compact:
        deletion_html = f"<p class='help'>不要看的線索：{h('；'.join(deletion_signals[:3]))}</p>"
    reject_reason_html = ""
    suggested_reasons = suggested_rejection_reasons(item)
    if suggested_reasons and not compact:
        reject_reason_html = (
            "<p class='help'>建議不收分類</p>"
            f"<div class='reason-presets'>{inline_reject_buttons(clean_text(item.get('id')), suggested_reasons, limit=4, action=reject_action)}</div>"
        )
    zh_summary = workflow_display_text(editorial.get("zh_summary"), 620)
    has_model_review = bool(record_model_reviews(item))
    zh_summary_html = f"<p class='zh-summary'>{h(zh_summary)}</p>" if zh_summary and not compact and not has_model_review else ""
    confidence_html = f"{score_label(confidence_score_10(confidence))}/10" if confidence else ""
    rule_html = (
        "<div class='source-card source-card--rules'>"
        "<div class='section-kicker'>自動規則判斷</div>"
        "<h3>本機規則與關鍵字階段判斷</h3>"
        f"{badge(editorial_recommendation_label(recommendation), editorial_badge_class(recommendation))}"
        f"{badge(content_kind_label(display_kind), 'neutral')}"
        f"{badge('信心 ' + confidence_html, 'neutral') if confidence_html else ''}"
        f"{score_summary_html(item)}"
        f"{rule_stage_scores_html(item)}"
        f"{model_judgement_summary_html(item)}"
        f"{zh_summary_html}"
        f"<p class='help'>初步判斷：{h(workflow_display_text(editorial.get('summary_reason', '未標示')))}<br>"
        f"下一步：{h(workflow_display_text(editorial.get('next_step_hint', '人工判斷下一步。')))}</p>"
        f"{keyword_html}"
        f"{reason_rows}{deletion_html}{reject_reason_html}"
        "</div>"
    )
    return f"<div class='source-stack'>{model_html}{source_html}{rule_html}</div>"


def append_review_note(review: dict, note: str) -> dict:
    updated = dict(review or default_review())
    current_notes = clean_text(updated.get("notes"))
    updated["notes"] = f"{current_notes}\n{note}".strip() if current_notes else note
    return updated


def local_decision_action(record: dict) -> str:
    decision = record.get("local_decision")
    if not isinstance(decision, dict):
        return ""
    return clean_text(decision.get("action"))


def rejected_archive_record(record: dict, decided_at: str, reason: str = "", moved_from: str = "database/items.jsonl") -> dict:
    item = remove_local_candidate_fields(record)
    item["status"] = "archived"
    item["priority"] = "low"
    decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
    previous_action = clean_text(decision.get("action"))
    item["local_decision"] = {
        **decision,
        "action": "rejected",
        "decided_at": decision.get("decided_at") if previous_action == "rejected" and decision.get("decided_at") else decided_at,
        "reason": decision.get("reason") if previous_action == "rejected" and decision.get("reason") else reason,
        "source": decision.get("source") or "local_web",
    }
    archive_meta = item.get("archive") if isinstance(item.get("archive"), dict) else {}
    item["archive"] = {
        **archive_meta,
        "moved_from": moved_from,
        "moved_to": "database/rejected-items.jsonl",
        "moved_at": decided_at,
        "purpose": "learning-rejection-patterns",
    }
    return item


def rejection_reason_base(reason: object) -> str:
    text = clean_text(reason, 140)
    return re.sub(r"（\d{4}-\d{2}-\d{2}，自動批次處理）$", "", text).strip()


def rejection_reason_suffix(reason: object) -> str:
    match = re.search(r"（\d{4}-\d{2}-\d{2}，自動批次處理）$", clean_text(reason, 160))
    return match.group(0) if match else ""


def alias_rejection_reason(reason: object) -> str:
    base = rejection_reason_base(reason)
    if base in REJECTION_REASON_CATEGORIES:
        return base
    lowered = base.casefold()
    for old_reason, category in REJECTION_REASON_ALIASES.items():
        if clean_text(old_reason).casefold() in lowered:
            return category
    return ""


def rejection_record_text(item: dict, current_reason: object = "") -> str:
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    deletion = editorial.get("deletion_pattern_fit") if isinstance(editorial.get("deletion_pattern_fit"), dict) else {}
    decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    metadata = item_reading_metadata(item)
    review = item.get("review") if isinstance(item.get("review"), dict) else {}
    codex_review = record_codex_review(item)
    parts: list[object] = [
        current_reason,
        decision.get("reason"),
        item.get("reason"),
        item.get("notes"),
        review.get("notes"),
        item.get("title"),
        item.get("summary"),
        item.get("url"),
        item.get("source_name"),
        item.get("source_id"),
        item.get("published_at"),
        item.get("captured_at"),
        metadata.get("title"),
        metadata.get("description"),
        metadata.get("final_url"),
        metadata.get("source_url"),
        reference.get("file"),
        reference.get("stream_id"),
        editorial.get("summary_reason"),
        editorial.get("zh_summary"),
        editorial.get("content_kind_label"),
        codex_review.get("one_line_recommendation"),
        codex_review.get("summary"),
        " ".join(item.get("tags") or []),
        " ".join(triage.get("matched_keywords") or []),
        " ".join(triage.get("skip_keywords") or []),
        " ".join(str(signal) for signal in deletion.get("signals") or []),
    ]
    return " ".join(clean_text(part, 500) for part in parts if part).casefold()


def infer_rejection_reason(item: dict, current_reason: object = "") -> str:
    suffix = rejection_reason_suffix(current_reason)
    alias = alias_rejection_reason(current_reason)
    if alias:
        return f"{alias}{suffix}"

    text = rejection_record_text(item, current_reason)
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    matched_keywords = [clean_text(keyword) for keyword in triage.get("matched_keywords") or [] if clean_text(keyword)]
    skip_keywords = [clean_text(keyword) for keyword in triage.get("skip_keywords") or [] if clean_text(keyword)]

    if re.search(r"重複|已收|已涵蓋|重刊|duplicate|similar|same story", text, flags=re.I):
        return f"重複/已涵蓋{suffix}"
    published = parse_loose_date(item.get("published_at") or item.get("captured_at"))
    if published and (datetime.now(timezone.utc) - published).days >= 730:
        return f"資料太舊{suffix}"
    if re.search(r"社群內部|內部消息|會務|社群例會|籌備|organizer|maintainer update|minutes", text, flags=re.I):
        return f"社群內部消息{suffix}"
    if re.search(r"活動|報名|徵件|徵稿|招生|議程|研討會|講座|工作坊|論壇|招商|贊助|press release|webinar|conference|event|call for|cfp|sponsor", text, flags=re.I):
        return f"活動公告/宣傳{suffix}"
    if re.search(r"抽獎|贈獎|優惠|折扣|促銷|廣告|導購|特價|限時|prime day|\bdeals?\b|coupon|sale|discount|promo code|sponsored|advertorial|gift card|all-time low|lowest price|best .* deals|up to \d+% off|% off|職缺|招聘|hiring|job", text, flags=re.I):
        return f"活動公告/宣傳{suffix}"
    if re.search(r"中國|中国|大陸|大陆|香港|澳門|澳门|央行|銀保監|证监|證監|國務院|国务院|people\.com\.cn|gov\.cn|xinhuanet|cfi\.cn|hkex|moomoo|aastocks", text, flags=re.I):
        return f"地緣脈絡非台資訊{suffix}"
    if re.search(r"股價|買超|賣超|自營商|投信|營收|財報|公告|年報|季報|法人|籌碼|個股|pdf|會議紀錄|逐字稿|transcript|minutes|record only|log", text, flags=re.I):
        return f"純紀錄型資料{suffix}"
    if len(clean_text(item.get("summary"))) < 180 and not item_article_text(item):
        return f"純紀錄型資料{suffix}"
    if skip_keywords or (candidate_recommendation(item) == "suggest-skip" and not matched_keywords):
        return f"主線關聯弱{suffix}"
    return f"主線關聯弱{suffix}"


def automatic_batch_rejection_reason(item: dict) -> str:
    base = rejection_reason_base(infer_rejection_reason(item)) or "主線關聯弱"
    today = datetime.now(LOCAL_TIMEZONE).date().isoformat()
    return f"{base}（{today}，自動批次處理）"


def automatic_low_pr_rejection_reason(item: dict, threshold: float = 65) -> str:
    score = candidate_priority_scores(item)["overall"] * 10
    today = datetime.now(LOCAL_TIMEZONE).date().isoformat()
    return (
        f"PR 未達門檻（{score_label(score)}/100，低於或等於 {score_label(threshold)}/100）："
        f"本輪建議收魔術棒剔除，先不收並保留原因。"
        f"（{today}，自動批次處理）"
    )


def latest_source_fetch_stats(source_id: str) -> dict:
    status = load_json(RSS_FETCH_STATUS)
    stats = status.get("source_stats") if isinstance(status.get("source_stats"), dict) else {}
    source_stats = stats.get(source_id) if isinstance(stats.get(source_id), dict) else {}
    return source_stats


def source_fetch_counts(stats: dict) -> dict[str, int]:
    skipped_old = int(stats.get("skipped_old") or 0)
    skipped_duplicate = int(stats.get("skipped_duplicate_recent") or 0)
    skipped_keywords = int(stats.get("skipped_source_keywords") or 0)
    return {
        "entries_seen": int(stats.get("entries_seen") or 0),
        "new_items": int(stats.get("new_items") or 0),
        "skipped_old": skipped_old,
        "skipped_duplicate_recent": skipped_duplicate,
        "skipped_source_keywords": skipped_keywords,
        "excluded_items": skipped_old + skipped_duplicate + skipped_keywords,
    }


def source_fetch_summary_from_counts(counts: dict[str, int]) -> str:
    return (
        f"重新抓 {counts.get('entries_seen', 0)} 則；"
        f"新增 {counts.get('new_items', 0)} 則；"
        f"列入排除 {counts.get('excluded_items', 0)} 則"
        f"（近 7 天重複 {counts.get('skipped_duplicate_recent', 0)}、過舊 {counts.get('skipped_old', 0)}、來源關鍵字排除 {counts.get('skipped_source_keywords', 0)}）。"
    )


def source_fetch_summary_from_query(query: dict[str, list[str]]) -> str:
    counts = {
        "entries_seen": int(form_value(query, "entries_seen", "0") or 0),
        "new_items": int(form_value(query, "new_items", "0") or 0),
        "excluded_items": int(form_value(query, "excluded_items", "0") or 0),
        "skipped_duplicate_recent": int(form_value(query, "skipped_duplicate_recent", "0") or 0),
        "skipped_old": int(form_value(query, "skipped_old", "0") or 0),
        "skipped_source_keywords": int(form_value(query, "skipped_source_keywords", "0") or 0),
    }
    return source_fetch_summary_from_counts(counts)


def rejection_reason_options(items: list[dict]) -> list[str]:
    counts: Counter[str] = Counter()
    for item in [*items, *load_jsonl(REJECTED_ITEMS), *load_jsonl(DISMISSED)]:
        decision = item.get("local_decision") or {}
        reason = ""
        if isinstance(decision, dict) and decision.get("action") == "rejected":
            reason = clean_text(decision.get("reason"), 90)
        if not reason:
            reason = clean_text(item.get("reason"), 90)
        reason = alias_rejection_reason(reason) or rejection_reason_base(reason)
        reason = re.sub(r"\s+", " ", reason).strip()
        if reason:
            counts[reason] += 1
    options = [
        reason
        for reason, count in counts.most_common(12)
        if count >= MIN_REJECTION_REASON_OPTION_COUNT or reason in REJECTION_REASON_CATEGORIES
    ]
    for reason, count in counts.most_common(12):
        if count < MIN_REJECTION_REASON_OPTION_COUNT and reason not in REJECTION_REASON_CATEGORIES:
            continue
        if reason and reason not in options:
            options.append(reason)
    for reason in DEFAULT_REJECTION_REASONS:
        if reason and reason not in options:
            options.append(reason)
    return options


def unique_reasons(reasons: list[str], limit: int | None = None) -> list[str]:
    output = []
    for reason in reasons:
        reason = clean_text(reason, 120)
        if reason and reason not in output:
            output.append(reason)
        if limit and len(output) >= limit:
            break
    return output


def suggested_rejection_reasons(item: dict) -> list[str]:
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    text = rejection_record_text(item)
    reasons: list[str] = [rejection_reason_base(infer_rejection_reason(item))]
    skip_keywords = [clean_text(keyword) for keyword in triage.get("skip_keywords") or [] if clean_text(keyword)]
    matched_keywords = [clean_text(keyword) for keyword in triage.get("matched_keywords") or [] if clean_text(keyword)]
    recommendation = candidate_recommendation(item)

    published = parse_loose_date(item.get("published_at") or item.get("captured_at"))
    if published:
        age_days = (datetime.now(timezone.utc) - published).days
        if age_days >= 730:
            reasons.append("資料太舊")
    if re.search(r"活動|報名|徵件|徵稿|招生|研討會|講座|工作坊|webinar|conference|event|call for|cfp", text, flags=re.I):
        reasons.append("活動公告/宣傳")
    if re.search(r"抽獎|贈獎|優惠|折扣|促銷|廣告|導購|特價|限時|prime day|\bdeals?\b|coupon|sale|discount|promo code|sponsored|advertorial|gift card|all-time low|lowest price|best .* deals|up to \d+% off|% off|職缺|招聘|hiring|job", text, flags=re.I):
        reasons.append("活動公告/宣傳")
    if re.search(r"社群內部|內部消息|會務|社群例會|籌備|organizer|maintainer update", text, flags=re.I):
        reasons.append("社群內部消息")
    if re.search(r"重複|已收|涵蓋|duplicate|similar", text, flags=re.I):
        reasons.append("重複/已涵蓋")
    if re.search(r"中國|中国|大陸|大陆|香港|澳門|澳门|銀保監|國務院|people\.com\.cn|gov\.cn|hkex|moomoo", text, flags=re.I):
        reasons.append("地緣脈絡非台資訊")
    if re.search(r"股價|買超|賣超|自營商|投信|營收|財報|公告|年報|季報|法人|籌碼|個股|會議紀錄|逐字稿|transcript|minutes", text, flags=re.I):
        reasons.append("純紀錄型資料")
    if len(clean_text(item.get("summary"))) < 180 and not item_article_text(item):
        reasons.append("純紀錄型資料")
    if not fetchable_http_url(item.get("url")):
        reasons.append("純紀錄型資料")
    if skip_keywords or (recommendation == "suggest-skip" and not matched_keywords):
        reasons.append("主線關聯弱")
    return unique_reasons(reasons, limit=5)


def prioritized_rejection_reasons(item: dict, reasons: list[str], limit: int | None = None) -> list[str]:
    return unique_reasons([*suggested_rejection_reasons(item), *reasons], limit=limit)


def review_event(item: dict, status: str, notes: str) -> dict:
    created_at = now_iso()
    return {
        "id": stable_id("review", item.get("id"), status, created_at),
        "item_id": item.get("id"),
        "track": item.get("track", "unclassified"),
        "step": "news-scout",
        "status": status,
        "reviewer": "local-web",
        "created_at": created_at,
        "notes": notes,
        "evidence": [{"type": "url", "url": item.get("url", "")}],
    }


def inline_reject_buttons(item_id: str, reasons: list[str], limit: int = 7, action: str = "/items/reject", redirect_to: str = "") -> str:
    buttons = []
    for reason in reasons[:limit]:
        redirect_input = f'<input type="hidden" name="redirect" value="{h(redirect_to)}">' if redirect_to else ""
        buttons.append(
            f"""
<form class="chip-form" method="post" action="{h(action)}" data-decision-form>
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="reason" value="{h(reason)}">
  {redirect_input}
  <button type="submit" class="reason-chip reason-chip--danger">{h(reason)}</button>
</form>
"""
        )
    return "\n".join(buttons)


def batch_reason_buttons(reasons: list[str], limit: int = 7) -> str:
    return "\n".join(
        f'<button type="submit" name="action" value="reject" class="reason-chip reason-chip--danger" data-batch-reason="{h(reason)}">{h(reason)}</button>'
        for reason in reasons[:limit]
    )


def candidate_issue_body(item: dict) -> str:
    triage = item.get("triage") or {}
    matched = ", ".join(triage.get("matched_keywords") or []) or "無"
    skipped = ", ".join(triage.get("skip_keywords") or []) or "無"
    return "\n".join(
        [
            "## 主線",
            track_label(item.get("track", "unclassified")),
            "",
            "## 原始網址",
            item.get("url", ""),
            "",
            "## 來源 / 網站 / 作者",
            item.get("source_name", ""),
            "",
            "## 發布日期",
            item.get("published_at", ""),
            "",
            "## 原文重點",
            clean_text(item.get("summary"), 1200),
            "",
            "## 本機關鍵字判斷",
            f"- 建議：{triage.get('recommendation', '未標示')}",
            f"- 理由：{workflow_display_text(triage.get('reason', '未標示'))}",
            f"- 命中關鍵字：{matched}",
            f"- 排除關鍵字：{skipped}",
            "",
            "## 為什麼值得追",
            "本機已收下，待補切角、處理建議與審查。",
            "",
            "## 下一步",
            "- [ ] 補來源與摘要",
            "- [ ] 補切角與處理建議",
            "- [ ] 判斷是否開 PR 寫 brief 或更新 database/items.jsonl",
        ]
    )


def create_github_issue(item: dict) -> tuple[int, str]:
    title = clean_text(item.get("title"), 160) or "未命名知識候選"
    command = [
        "gh",
        "issue",
        "create",
        "--title",
        f"[知識候選] {title}",
        "--body",
        candidate_issue_body(item),
    ]
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
    except FileNotFoundError:
        return 127, "找不到 gh 指令。請先安裝 GitHub CLI，或先只收進資料庫。"
    return result.returncode, result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")


def page(title: str, body: str) -> bytes:
    html_doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)} - Ian Open News</title>
  <style>
    @import url("https://fonts.googleapis.com/css2?family=Noto+Serif:wght@260;400;550;600;700&family=Noto+Serif+TC:wght@260;400;550;600;700&display=swap");
    :root {{
      --ocf-primary: #6450dc;
      --ocf-light: #d7dcf0;
      --ocf-dark: #0f1923;
      --ocf-white: #ffffff;
      --ocf-cyan: #0091da;
      --ocf-magenda: #ce0058;
      --link: #193f8f;
      --bg: #f5f6fb;
      --ink: var(--ocf-dark);
      --muted: #5f6877;
      --line: #c9d0e5;
      --panel: var(--ocf-white);
      --soft: #eef1fb;
      --accent: var(--ocf-primary);
      --humanities: var(--ocf-dark);
      --danger: #9f2525;
      --article-serif: "Noto Serif", "Noto Serif Traditional Chinese", "Noto Serif TC", "Noto Serif CJK TC", "Source Han Serif TC", "PingFang TC", serif;
      --article-heading: "LINE Seed TW", "LINE Seed Sans TW", "Noto Sans TC", "PingFang TC", sans-serif;
      --paper: #fffdf7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
      line-height: 1.55;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 16px;
      padding: 16px 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.94);
      position: sticky;
      top: 0;
      z-index: 40;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    nav a, .nav-menu summary {{
      color: var(--ocf-dark);
      text-decoration: none;
      font-weight: 750;
      padding: 7px 10px;
      border-radius: 6px;
      transition: background .16s ease, color .16s ease, transform .16s ease;
    }}
    nav a:hover, .nav-menu summary:hover {{ background: var(--soft); color: var(--ocf-dark); transform: translateY(-1px); }}
    .nav-menu {{ position: relative; }}
    .nav-menu summary {{ list-style: none; cursor: pointer; }}
    .nav-menu summary::-webkit-details-marker {{ display: none; }}
    .nav-menu summary::after {{ content: " v"; font-size: 11px; color: var(--muted); }}
    .nav-menu[open] summary {{ background: var(--soft); color: var(--ocf-dark); }}
    .nav-menu-links {{
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      min-width: 210px;
      display: grid;
      gap: 4px;
      padding: 8px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 12px 30px rgba(15,25,35,.16);
      max-width: calc(100vw - 24px);
      max-height: calc(100vh - 76px);
      overflow: auto;
      overscroll-behavior: contain;
      z-index: 50;
    }}
    .nav-menu-links a {{ display: flex; align-items: center; gap: 8px; }}
    h1 {{ font-size: 28px; margin: 0 0 12px; }}
    h2 {{ font-size: 20px; margin: 30px 0 12px; }}
    /* 標題本身已有底線時，緊接著的 --- 分隔線是多餘的第二條，藏起來只留一條 */
    h1 + hr, h2 + hr, h3 + hr, h4 + hr, h5 + hr {{ display: none; }}
    h3 {{ font-size: 16px; margin: 0 0 8px; }}
    .article-title-block {{
      display: grid;
      gap: 6px;
      min-width: 0;
    }}
    .article-title-heading {{
      display: flex;
      align-items: flex-start;
      gap: 8px;
      min-width: 0;
    }}
    .article-title-heading h1 {{
      flex: 1 1 auto;
      min-width: 0;
      margin: 0;
      color: var(--ocf-dark);
      overflow-wrap: anywhere;
    }}
    .article-title-tools {{
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding-top: 2px;
    }}
    .article-title-menu {{
      position: relative;
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .article-title-menu summary {{
      cursor: pointer;
      list-style: none;
    }}
    .article-title-menu summary::-webkit-details-marker {{ display: none; }}
    .title-icon-button {{
      width: 34px;
      height: 34px;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ocf-dark);
      display: inline-grid;
      place-items: center;
      box-shadow: 0 1px 2px rgba(15,25,35,.05);
    }}
    .title-icon-button:hover,
    .article-title-menu[open] .title-icon-button {{
      border-color: var(--ocf-cyan);
      background: #eefcff;
      color: #00699f;
      text-decoration: none;
      transform: none;
    }}
    .title-icon-button svg {{
      width: 18px;
      height: 18px;
    }}
    .title-popover {{
      position: absolute;
      right: 0;
      top: calc(100% + 8px);
      z-index: 80;
      width: min(720px, calc(100vw - 56px));
      max-width: calc(100vw - 24px);
      max-height: calc(100vh - 24px);
      overflow: auto;
      overscroll-behavior: contain;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 14px 34px rgba(15,25,35,.16);
    }}
    .title-editor form {{
      max-width: none;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
    }}
    .title-editor-fields {{
      display: grid;
      gap: 12px;
    }}
    .share-panel {{
      width: min(360px, calc(100vw - 56px));
    }}
    .original-fulltext-collapsible > summary {{
      cursor: pointer;
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .original-fulltext-collapsible > summary::-webkit-details-marker {{ display: none; }}
    .original-fulltext-collapsible > summary .section-kicker {{ flex: 1 1 auto; }}
    .original-fulltext-collapsible > summary::after {{
      content: "展開原文";
      flex: 0 0 auto;
      color: var(--ocf-primary);
      font-size: 13px;
      font-weight: 800;
    }}
    .original-fulltext-collapsible[open] > summary {{ margin-bottom: 12px; }}
    .original-fulltext-collapsible[open] > summary::after {{ content: "收起原文"; }}
    .share-url-field {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      color: var(--ocf-dark);
      background: #f8fafc;
    }}
    .copy-status {{
      min-height: 1.2em;
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }}
    p {{ margin: 8px 0; }}
    a {{ color: var(--link); text-decoration-thickness: 1px; text-underline-offset: 2px; }}
    a:not(.button):hover {{ color: var(--ocf-primary); }}
    .masthead nav a:hover {{ color: var(--ocf-dark); }}
    a, code, .url-cell, .url, .break-anywhere {{ overflow-wrap: anywhere; word-break: break-word; }}
    .brand {{ font-weight: 850; color: var(--ocf-primary); text-decoration: none; }}
    .brand:hover {{ color: var(--ocf-dark); }}
    .lede {{ max-width: 760px; color: var(--muted); margin: 0 0 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
    .track-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 16px; }}
    .two-column {{ display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(280px, .75fr); gap: 16px; align-items: start; }}
    .card, .form-panel, table, .source-group, .filter-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(15,25,35,.05);
    }}
    .card {{ padding: 18px; }}
    .track-card {{
      --track-color: var(--ocf-primary);
      border-top: 6px solid var(--track-color);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .track-card--opentech {{ --track-color: var(--ocf-primary); }}
    .track-card--humanities {{ --track-color: var(--humanities); }}
    .track-card--neutral {{ --track-color: var(--ocf-cyan); }}
    .metric-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(78px, 1fr)); gap: 8px; }}
    .metric-tile {{
      min-width: 0;
      padding: 8px;
      border-radius: 6px;
      color: var(--ink);
      text-decoration: none;
      transition: background .16s ease, transform .16s ease, box-shadow .16s ease;
    }}
    a.metric-tile:hover {{
      color: var(--ink);
      background: rgba(255,255,255,.68);
      transform: translateY(-1px);
      box-shadow: 0 5px 12px rgba(15,25,35,.10);
    }}
    .metric {{
      font-size: 24px;
      font-weight: 850;
      color: var(--track-color, var(--accent));
      line-height: 1.1;
      overflow-wrap: anywhere;
    }}
    .metric-label {{ color: var(--muted); font-size: 12px; line-height: 1.2; }}
    .metric-card {{
      display: block;
      color: var(--ink);
      text-decoration: none;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    a.metric-card:hover {{
      color: var(--ink);
      transform: translateY(-1px);
      border-color: var(--link);
      box-shadow: 0 8px 18px rgba(15,25,35,.12);
    }}
    a.metric-card:hover .metric-label {{ color: var(--muted); }}
    .metric-link-label {{
      display: inline-flex;
      margin-top: 8px;
      color: var(--link);
      font-size: 12px;
      font-weight: 800;
      line-height: 1.2;
    }}
    a.metric-card:hover .metric-link-label, a.metric-tile:hover .metric-link-label {{ color: var(--link); text-decoration: underline; }}
    .metric-card.is-active {{
      border-color: var(--link);
      box-shadow: 0 0 0 2px rgba(25,63,143,.08);
    }}
    .muted {{ color: var(--muted); }}
    .help {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}
    form {{ margin: 0; }}
    .form-panel, .filter-panel {{ padding: 18px; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .date-range-fields {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .date-range-fields[hidden] {{ display: none; }}
    label {{ display: block; font-weight: 750; margin: 13px 0 5px; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }}
    textarea {{ min-height: 120px; resize: vertical; }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 800;
      text-decoration: none;
      cursor: pointer;
      margin-top: 12px;
      max-width: 100%;
      white-space: normal;
      text-align: center;
      transition: transform .16s ease, box-shadow .16s ease, filter .16s ease, background .16s ease;
    }}
    button:hover, .button:hover {{
      color: #fff;
      transform: translateY(-1px);
      box-shadow: 0 6px 14px rgba(15,25,35,.16);
      filter: brightness(1.03);
    }}
    button svg, .button svg {{
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
      flex: 0 0 auto;
    }}
    button:active, .button:active {{ transform: translateY(0); box-shadow: 0 2px 6px rgba(15,25,35,.14); }}
    button:disabled, .button:disabled, button[disabled], .button[disabled] {{
      background: #e2e8f0;
      color: #94a3b8;
      cursor: not-allowed;
      box-shadow: none;
      filter: none;
      opacity: 1;
    }}
    button:disabled:hover, .button:disabled:hover, button[disabled]:hover, .button[disabled]:hover {{
      background: #e2e8f0;
      color: #94a3b8;
      transform: none;
      box-shadow: none;
      filter: none;
    }}
    .button-row {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start; }}
    .button-row .button, .button-row button {{ margin-top: 0; }}
    .button-opentech {{ background: var(--ocf-primary); }}
    .button-humanities {{ background: var(--humanities); }}
    .secondary {{ background: var(--ocf-cyan); }}
    .reading-button {{ background: var(--ocf-magenda); }}
    .quiet {{ background: var(--ocf-dark); }}
    .icon {{
      display: inline-grid;
      place-items: center;
      width: 22px;
      height: 20px;
      border-radius: 5px;
      background: rgba(255,255,255,.24);
      color: currentColor;
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
      flex: 0 0 auto;
    }}
    .icon svg {{
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .shortcut-hint {{ display: none; white-space: nowrap; }}
    body.show-shortcuts .icon[data-shortcut] {{
      width: auto;
      min-width: 30px;
      padding: 0 4px;
      font-size: 11px;
      letter-spacing: 0;
    }}
    body.show-shortcuts .icon[data-shortcut] svg {{ display: none; }}
    body.show-shortcuts .icon[data-shortcut] .shortcut-hint {{ display: inline; }}
    .card > strong .icon, nav .icon {{
      background: var(--soft);
      color: var(--ocf-primary);
      margin-right: 6px;
    }}
    input[type="checkbox"] {{ width: auto; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; table-layout: fixed; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ background: var(--soft); color: var(--muted); font-size: 13px; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef1fb; padding: 2px 5px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; background: #162024; color: #eaf1ec; padding: 16px; border-radius: 8px; overflow: auto; }}
    .notice {{ border-left: 4px solid var(--ocf-primary); padding: 10px 14px; background: #eef1fb; border-radius: 6px; margin-bottom: 18px; }}
    .notice--warn {{ border-left-color: #e67e22; background: #fef9f0; }}
    .notice--info {{ border-left-color: #2980b9; background: #eaf4fb; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 6px;
      padding: 3px 7px;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.2;
      background: var(--soft);
      color: var(--ocf-dark);
      margin: 0 4px 4px 0;
    }}
    .badge--opentech {{ background: #ece8ff; color: var(--ocf-primary); }}
    .badge--humanities {{ background: #e6ebf5; color: var(--ocf-dark); }}
    .badge--neutral {{ background: #e7f5fc; color: #00699f; }}
    .badge--active, .badge--rss, .badge--google-alert, .badge--youtube, .badge--podcast {{ background: #e7f5fc; color: #00699f; }}
    .badge--paused {{ background: #fff0f6; color: var(--ocf-magenda); }}
    .badge--archived {{ background: #eceff5; color: #667085; }}
    .badge--suggest-keep {{ background: #ece8ff; color: var(--ocf-primary); }}
    .badge--suggest-skip {{ background: #fff0f6; color: var(--ocf-magenda); }}
    .badge--suggest-ask {{ background: #fff7e6; color: #b7791f; }}
    .badge--reading {{ background: #fff8db; color: #7a5a00; }}
    .tag-chip-list {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }}
    .tag-chip {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 7px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ocf-dark);
      font-size: 12px;
      font-weight: 800;
      line-height: 1.25;
      text-decoration: none;
      transition: background .12s ease, border-color .12s ease, color .12s ease;
    }}
    .tag-chip:hover {{
      border-color: var(--ocf-cyan);
      background: #eefcff;
      color: #00699f;
      text-decoration: none;
    }}
    .tag-chip-icon {{
      display: inline-grid;
      place-items: center;
      width: 15px;
      height: 15px;
      color: var(--muted);
      flex: 0 0 auto;
    }}
    .tag-chip-icon svg {{
      width: 14px;
      height: 14px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .tag-editor-grid {{ display: grid; gap: 8px; }}
    .tag-check-list {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 2px; }}
    .tag-check {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ocf-dark);
      font-size: 12px;
      font-weight: 800;
    }}
    .tag-check--suggested {{ background: #eefcff; border-color: #b7e7f4; color: #00699f; }}
    .tag-check input {{ width: auto; }}
    .tag-picker {{ display: grid; gap: 10px; }}
    .tag-picker-current, .tag-suggestion-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      min-height: 32px;
    }}
    .tag-suggestion-strip:empty {{ display: none; }}
    .tag-suggestion-collapse {{ margin-top: 6px; }}
    .tag-suggestion-collapse > summary {{ cursor: pointer; color: var(--ocf-primary, #6450dc); font-size: 13px; list-style: none; padding: 4px 0; }}
    .tag-suggestion-collapse > summary::-webkit-details-marker {{ display: none; }}
    .tag-suggestion-collapse > summary::before {{ content: "▸ "; }}
    .tag-suggestion-collapse[open] > summary::before {{ content: "▾ "; }}
    .tag-suggestion-groups {{
      display: grid;
      gap: 8px;
    }}
    .tag-suggestion-groups:empty {{ display: none; }}
    .tag-suggestion-group {{
      display: grid;
      grid-template-columns: minmax(120px, .24fr) minmax(0, 1fr);
      gap: 8px;
      align-items: start;
    }}
    .tag-suggestion-group-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      line-height: 1.35;
      padding-top: 7px;
    }}
    .tag-pill, .tag-suggestion, .tag-menu-option {{
      display: inline-flex;
      align-items: center;
      justify-content: flex-start;
      gap: 6px;
      width: auto;
      min-height: 32px;
      margin: 0;
      padding: 6px 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ocf-dark);
      font-size: 13px;
      font-weight: 800;
      line-height: 1.2;
      box-shadow: none;
    }}
    .tag-pill:hover, .tag-suggestion:hover, .tag-menu-option:hover {{
      color: #00699f;
      border-color: #78cde5;
      background: #eefcff;
      box-shadow: none;
      transform: translateY(-1px);
    }}
    .tag-suggestion {{
      border-color: #b7e7f4;
      background: #eefcff;
      color: #00699f;
    }}
    .tag-pill-remove {{
      display: inline-grid;
      place-items: center;
      width: 16px;
      height: 16px;
      border-radius: 999px;
      background: #eef1fb;
      color: var(--muted);
      font-size: 11px;
      line-height: 1;
      opacity: 0;
      transition: opacity .12s ease, background .12s ease, color .12s ease;
    }}
    .tag-pill:hover .tag-pill-remove, .tag-pill:focus-visible .tag-pill-remove {{
      opacity: 1;
      background: #fff0f6;
      color: var(--ocf-magenda);
    }}
    .tag-autosave-status {{
      margin: 0;
      min-height: 18px;
      font-size: 12px;
    }}
    .tag-search-wrap {{ position: relative; }}
    .tag-search-wrap input {{ padding-right: 34px; }}
    .tag-menu {{
      position: absolute;
      left: 0;
      right: 0;
      top: calc(100% + 4px);
      display: grid;
      gap: 4px;
      max-height: 260px;
      overflow: auto;
      padding: 6px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 12px 30px rgba(15,25,35,.16);
      z-index: 30;
    }}
    .tag-menu[hidden] {{ display: none; }}
    .tag-menu-option {{
      width: 100%;
      border-color: transparent;
      border-radius: 6px;
    }}
    .tag-menu-option.is-create {{ color: #00699f; background: #eefcff; }}
    .source-group {{ margin-bottom: 14px; overflow: hidden; }}
    .source-group.is-drop-target summary.source-group-summary {{
      background: #fff;
      outline: 2px solid rgba(0, 159, 227, .35);
      outline-offset: -2px;
    }}
    .source-group summary.source-group-summary {{
      cursor: pointer;
      padding: 13px 14px;
      font-weight: 850;
      background: var(--soft);
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 52px;
    }}
    .source-group summary.source-group-summary::marker {{ content: ""; }}
    .source-group summary.source-group-summary::-webkit-details-marker {{ display: none; }}
    .source-group-heading {{ min-width: 0; flex: 0 1 auto; }}
    .source-row-grip {{
      display: grid;
      grid-template-columns: repeat(2, 4px);
      grid-auto-rows: 4px;
      gap: 3px;
      align-content: center;
      justify-content: center;
      width: 26px;
      height: 28px;
      padding: 5px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      cursor: grab;
      flex: 0 0 auto;
      margin: 0;
    }}
    .source-row-grip span {{
      width: 4px;
      height: 4px;
      border-radius: 999px;
      background: currentColor;
    }}
    .source-row-grip:hover {{
      background: var(--soft);
      color: var(--ocf-primary);
      box-shadow: none;
      transform: none;
      filter: none;
    }}
    .source-row-grip:active {{ cursor: grabbing; }}
    .source-row.is-dragging {{ opacity: .5; }}
    .source-drag-cell {{ width: 34px; padding-right: 0; }}
    .source-group-name-button {{
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--ocf-dark);
      font: inherit;
      font-weight: 850;
      justify-content: flex-start;
      text-align: left;
      box-shadow: none;
      max-width: 100%;
    }}
    .source-group-name-button:hover {{
      color: var(--link);
      background: transparent;
      box-shadow: none;
      transform: none;
      filter: none;
      text-decoration: underline;
    }}
    .source-group-rename-form {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      max-width: 680px;
    }}
    .source-group-rename-form[hidden] {{ display: none; }}
    .source-group-rename-form input {{
      width: min(360px, 60vw);
      padding: 7px 9px;
      font-weight: 650;
    }}
    .source-group-status {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
      margin-left: auto;
    }}
    .source-group-status.is-error {{ color: var(--ocf-magenda); }}
    .source-group table {{ border: 0; border-radius: 0; box-shadow: none; }}
    .list {{ display: grid; gap: 10px; }}
    .list-item {{ border-left: 4px solid var(--ocf-cyan); padding: 10px 12px; background: #fff; border-radius: 6px; }}
    .list-item--opentech {{ border-left-color: var(--ocf-primary); }}
    .list-item--humanities {{ border-left-color: var(--humanities); }}
    .candidate-card {{ display: grid; gap: 10px; }}
    .candidate-card--suggest-skip {{ border-color: #f1bfd3; }}
    .candidate-card.is-removing {{
      pointer-events: none;
      overflow: hidden;
      animation: item-remove 180ms ease forwards;
    }}
    @keyframes item-remove {{
      from {{ opacity: 1; transform: translateY(0); max-height: 900px; }}
      to {{ opacity: 0; transform: translateY(-4px); max-height: 0; padding-top: 0; padding-bottom: 0; margin: 0; border-width: 0; }}
    }}
    /* 材料頁「清單式」精簡列：列表式=詳細卡(.candidate-detailed)，清單式=精簡列(.candidate-compact)。
       兩者都預先 render，靠 .list[data-layout] 切換顯示；checkbox 共用、兩 mode 都能批次勾選。 */
    .candidate-compact {{ display: none; }}
    .list[data-layout="compact"] .candidate-detailed {{ display: none; }}
    .list[data-layout="compact"] .candidate-compact {{ display: contents; }}
    .list[data-layout="compact"] .candidate-card.is-expanded .candidate-detailed {{
      display: grid;
      grid-column: 1 / -1;
      order: 3;
      gap: 10px;
      padding-top: 10px;
      margin-top: 2px;
      border-top: 1px solid var(--line);
    }}
    .list[data-layout="compact"] .candidate-card.is-expanded .candidate-detailed-heading {{ display: none; }}
    .list[data-layout="compact"] .candidate-card {{
      grid-template-columns: auto minmax(0, 1fr);
      gap: 6px 8px;
      padding: 10px 14px;
    }}
    .list[data-layout="compact"] .candidate-card.is-expanded {{ border-color: #d7dcf0; }}
    .list[data-layout="compact"] .select-item {{
      grid-column: 1;
      grid-row: 1;
      align-self: center;
      justify-self: center;
      min-height: 26px;
      margin: 0;
    }}
    .list[data-layout="compact"] .select-item-text {{ display: none; }}
    .compact-head {{
      grid-column: 2;
      grid-row: 1;
      order: 0;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px 8px;
      min-width: 0;
    }}
    .candidate-expand-toggle {{
      display: inline-grid;
      place-items: center;
      flex: 0 0 auto;
      width: 26px;
      height: 26px;
      margin: 0;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      box-shadow: none;
    }}
    .candidate-expand-toggle:hover {{
      background: var(--soft);
      color: var(--link);
      box-shadow: none;
      transform: none;
      filter: none;
    }}
    .candidate-expand-triangle {{
      width: 0;
      height: 0;
      border-top: 5px solid transparent;
      border-bottom: 5px solid transparent;
      border-left: 7px solid currentColor;
      transform: translateX(1px);
      transition: transform .16s ease;
    }}
    .candidate-card.is-expanded .candidate-expand-triangle {{ transform: rotate(90deg) translateX(1px); }}
    .compact-badges {{ display: inline-flex; flex-wrap: wrap; gap: 4px; }}
    .compact-title {{
      grid-column: 1 / -1;
      order: 1;
      display: block;
      min-width: 0;
      font-weight: 700;
      line-height: 1.42;
      color: var(--ocf-dark);
      text-decoration: none;
    }}
    .compact-title:hover {{ text-decoration: underline; }}
    .compact-time {{ margin-left: auto; color: var(--muted, #64748b); font-size: 12px; white-space: nowrap; }}
    .compact-rec {{ grid-column: 1 / -1; order: 2; margin: 2px 0 0; color: var(--muted, #475569); font-size: 13px; line-height: 1.5; }}
    .decision-panel {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .reason-presets {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }}
    .reason-presets button {{ margin-top: 0; }}
    .flow-line {{ margin: 4px 0; color: var(--muted, #64748b); }}
    .flow-line--change {{ margin-top: 10px; }}
    .flow-current {{ display: inline-block; padding: 2px 12px; border-radius: 999px; background: var(--soft, #eef6ff); color: var(--ocf-dark, #14304a); font-weight: 700; }}
    /* 「目前為」標籤色 = 下方對應分流按鈕的 hover 色，讓狀態與動作視覺一致 */
    .flow-current--small-news {{ background: var(--ocf-cyan); color: #fff; }}
    .flow-current--reading {{ background: var(--ocf-magenda); color: #fff; }}
    .flow-current--accept {{ background: var(--ocf-primary); color: #fff; }}
    .flow-current--reject {{ background: var(--danger); color: #fff; }}
    /* 入庫建檔區：完全用原生語彙色，與列表頁(/items)一致 —— 收=紫(預設)、閱讀=洋紅(.reading-button)、
       新聞=藍(.secondary)、不收=淡粉 chip(.reason-chip--danger)。不另外覆寫。 */
    /* 可用材料區（重新檢視已判斷）：三顆實心動作鈕白底，hover 才回原生語彙色；不收原因維持原生淡色 chip。 */
    .button-row.flow-options--review button {{ background: #fff; color: var(--ocf-dark); border: 1px solid var(--line); box-shadow: none; transition: background .14s ease, color .14s ease, border-color .14s ease; }}
    .button-row.flow-options--review button:hover {{ background: var(--ocf-primary); color: #fff; border-color: transparent; }}
    .button-row.flow-options--review .secondary:hover {{ background: var(--ocf-cyan); color: #fff; border-color: transparent; }}
    .button-row.flow-options--review .reading-button:hover {{ background: var(--ocf-magenda); color: #fff; border-color: transparent; }}
    .batch-panel {{ border-left: 4px solid var(--ocf-cyan); }}
    .auto-batch-panel {{
      border-left: 4px solid var(--ocf-primary);
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin: 14px 0;
    }}
    .auto-batch-panel button {{ margin-top: 0; }}
    .auto-batch-panel .help {{ margin: 0; flex: 1 1 280px; }}
    .workspace-toolbar {{
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 10px;
      margin: 14px 0 10px;
    }}
    /* 材料頁顯示切換放工具列最左、與「顯示工具列」同一列 */
    .workspace-toolbar .layout-toggle {{ margin-right: auto; }}
    .workspace-sidebar-toggle {{
      margin: 0;
      padding: 8px 10px;
      font-size: 13px;
      box-shadow: none;
    }}
    .workspace-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 360px);
      gap: 18px;
      align-items: start;
      transition: grid-template-columns .28s ease, gap .28s ease;
    }}
    .workspace-layout.is-filtering .workspace-main {{
      opacity: .58;
      transition: opacity .12s ease;
    }}
    .workspace-layout.is-filtering .filter-panel {{
      cursor: progress;
    }}
    .workspace-layout.is-filtering .filter-panel input,
    .workspace-layout.is-filtering .filter-panel select {{
      cursor: progress;
    }}
    .workspace-layout.is-sidebar-hidden {{
      grid-template-columns: minmax(0, 1fr) minmax(0, 0px);
      gap: 0;
    }}
    .workspace-main {{
      min-width: 0;
    }}
    .workspace-main > :first-child,
    .workspace-sidebar > :first-child {{
      margin-top: 0;
    }}
    .workspace-sidebar {{
      position: sticky;
      top: 78px;
      display: grid;
      gap: 12px;
      min-width: 0;
      max-height: calc(100vh - 96px);
      overflow: auto;
      overscroll-behavior: contain;
      align-self: start;
      transition: transform .28s ease, opacity .28s ease;
    }}
    .workspace-layout.is-sidebar-hidden .workspace-sidebar {{
      overflow: hidden;
      transform: translateX(24px);
      opacity: 0;
      pointer-events: none;
    }}
    .workspace-sidebar-section {{
      display: grid;
      gap: 10px;
    }}
    .workspace-sidebar-section > h2 {{
      margin: 0;
      font-size: 18px;
    }}
    .workspace-sidebar .filter-panel,
    .workspace-sidebar .batch-panel,
    .workspace-sidebar .auto-batch-panel,
    .workspace-sidebar .workspace-tool-panel {{
      margin: 0;
      padding: 14px;
    }}
    .workspace-sidebar .filter-panel {{
      display: grid;
      gap: 8px;
    }}
    .sidebar-field-group {{
      display: grid;
      gap: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--line);
    }}
    .sidebar-field-group:first-child {{
      padding-top: 0;
      border-top: 0;
    }}
    .sidebar-field-group > h3 {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0;
    }}
    .workspace-sidebar .form-grid {{
      grid-template-columns: 1fr;
      gap: 8px;
    }}
    .workspace-sidebar label,
    .article-action-dock label {{
      margin: 6px 0 3px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
    }}
    .workspace-sidebar input,
    .workspace-sidebar select,
    .article-action-dock input,
    .article-action-dock select {{
      padding: 7px 9px;
      font-size: 13px;
      line-height: 1.25;
    }}
    .workspace-sidebar .auto-batch-panel {{
      align-items: stretch;
    }}
    .workspace-sidebar .button-row {{
      gap: 6px;
    }}
    .workspace-sidebar .button-row > form,
    .article-action-dock .button-row > form {{
      display: inline-flex;
      margin: 0;
    }}
    .workspace-sidebar .button-row .button,
    .workspace-sidebar .button-row button,
    .workspace-sidebar .auto-batch-panel button,
    .article-action-dock .button-row .button,
    .article-action-dock .button-row button,
    .article-action-dock .card > form > button,
    .article-action-dock .metadata-dock form > button {{
      min-height: 30px;
      padding: 6px 8px;
      gap: 6px;
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.2;
      box-shadow: none;
    }}
    .workspace-sidebar button svg,
    .workspace-sidebar .button svg,
    .article-action-dock button svg,
    .article-action-dock .button svg {{
      width: 14px;
      height: 14px;
    }}
    .workspace-sidebar .icon,
    .article-action-dock .icon {{
      width: 19px;
      height: 18px;
      border-radius: 4px;
      font-size: 10px;
    }}
    .batch-panel {{
      display: grid;
      gap: 10px;
    }}
    .batch-selection-line {{
      display: grid;
      gap: 2px;
    }}
    .batch-panel > p,
    .batch-selection-line > p,
    .batch-ai-review p {{
      margin: 0;
    }}
    #items-batch-form,
    .batch-ai-review {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}
    .batch-panel .button-row > button,
    .batch-panel .button-row > .button,
    .batch-panel .button-row > form {{
      flex: 0 1 auto;
    }}
    .batch-panel .button-row > form > button {{
      width: 100%;
    }}
    .workspace-tool-panel {{
      display: grid;
      gap: 8px;
    }}
    .batch-ai-review .button-row {{
      align-items: center;
    }}
    .batch-ai-review select {{
      flex: 1 1 120px;
      min-height: 30px;
      padding: 6px 28px 6px 8px;
      font-size: 12px;
    }}
    .button-row .reason-chip,
    .workspace-sidebar .button-row .reason-chip,
    .article-action-dock .button-row .reason-chip {{
      min-height: 28px;
      padding: 5px 7px;
      font-size: 12px;
    }}
    .keyword-filters {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
    .keyword-option {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 6px;
      border: 1px solid #dce3f1;
      border-radius: 5px;
      background: #f8fafc;
      color: #647084;
      font-size: 11px;
      font-weight: 700;
    }}
    .select-item {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
      margin: 0 0 4px;
    }}
    .chip-form {{ display: inline-flex; margin: 0; }}
    .reason-chip {{
      margin-top: 0;
      padding: 6px 8px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ocf-dark);
      font-size: 12px;
      font-weight: 800;
    }}
    .reason-chip:hover {{
      background: #fff;
      color: var(--ocf-dark);
      box-shadow: 0 4px 10px rgba(15,25,35,.12);
      transform: none;
      filter: none;
    }}
    .reason-chip--danger {{
      border-color: #f1bfd3;
      background: #fff0f6;
      color: var(--ocf-magenda);
    }}
    .reason-chip--danger:hover {{
      border-color: #f1bfd3;
      background: #fff0f6;
      color: var(--ocf-magenda);
    }}
    .inline-select-form {{ display: inline-flex; margin: 0; }}
    .inline-select-form select {{
      width: auto;
      min-width: 112px;
      margin: 0;
      padding: 6px 28px 6px 8px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.2;
      background-color: #fff;
    }}
    .source-action-row {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .source-action-row .button, .source-action-row button {{ margin-top: 0; padding: 6px 8px; font-size: 12px; }}
    .source-toggle-form {{ display: inline-flex; margin: 0; }}
    .source-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 74px;
      min-height: 30px;
      margin: 0;
      padding: 4px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff0f6;
      color: var(--ocf-magenda);
      box-shadow: none;
      font-size: 12px;
      font-weight: 850;
      transition: background-color .18s ease, color .18s ease, border-color .18s ease;
    }}
    .source-toggle .toggle-dot {{
      flex: 0 0 auto;
      width: 18px;
      height: 18px;
      border-radius: 999px;
      background: currentColor;
      transition: transform .18s ease;
    }}
    .source-toggle.is-on {{
      background: #e7f5fc;
      color: #00699f;
    }}
    .source-toggle:hover {{
      box-shadow: none;
      transform: none;
      filter: none;
      border-color: currentColor;
    }}
    .source-toggle--archived {{
      min-width: auto;
      background: #eceff5;
      color: #667085;
    }}
    .inline-reason summary {{
      cursor: pointer;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }}
    .inline-reason .button-row {{ margin-top: 8px; }}
    .danger {{ background: var(--ocf-magenda); }}
    .command-card form {{ margin-top: 8px; }}
    .command-engine-buttons {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    .command-engine-buttons button {{ flex: 0 0 auto; }}
    .command-output {{ margin-top: 16px; }}
    .preview-panel {{
      border: 1px solid var(--line);
      border-left: 4px solid var(--ocf-cyan);
      background: #f7fbfe;
      border-radius: 8px;
      padding: 10px 12px;
      margin: 10px 0;
    }}
    .preview-status {{ color: var(--muted); font-size: 13px; font-weight: 750; }}
    .preview-result {{ display: grid; gap: 8px; margin-top: 8px; }}
    .preview-result h3 {{ font-size: 16px; margin: 0; }}
    .feed-suggestions {{ display: grid; gap: 8px; margin-top: 6px; }}
    .feed-suggestion {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 6px;
      padding: 9px 10px;
    }}
    .feed-suggestion .button {{ margin-top: 6px; padding: 7px 10px; font-size: 13px; }}
    .ai-box, .source-card {{
      border: 1px solid var(--line);
      border-left: 4px solid var(--ocf-primary);
      background: #fbfcff;
      border-radius: 8px;
      padding: 10px 12px;
    }}
    .source-stack {{ display: grid; gap: 10px; }}
    .source-card--model {{ border-left-color: var(--ocf-primary); background: #fbfaff; }}
    .source-card--source {{ border-left-color: var(--ocf-cyan); background: #f7fbfe; }}
    .source-card--rules {{ border-left-color: #7b8495; background: #fbfcff; }}
    .source-card--empty {{ opacity: .82; }}
    .score-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 8px; margin: 10px 0; }}
    .score-grid--stages {{ grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); margin-top: 8px; }}
    .score-pill {{ border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 8px 10px; display: grid; gap: 2px; min-height: 58px; }}
    .score-pill b {{ font-size: 22px; line-height: 1; color: var(--ocf-dark); }}
    .score-pill small {{ color: var(--muted); font-size: 12px; line-height: 1.2; }}
    .score-pill em {{ color: var(--muted); font-size: 11px; font-style: normal; line-height: 1.25; }}
    .score-pill--soft {{ background: #f8fafc; }}
    .section-kicker {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      letter-spacing: 0;
      text-transform: none;
      margin-bottom: 2px;
    }}
    .recommendation-line {{
      font-weight: 800;
      color: var(--ocf-dark);
      margin: 10px 0;
    }}
    .source-excerpt {{
      white-space: pre-wrap;
      color: var(--ink);
      margin: 10px 0 0;
    }}
    .zh-summary {{
      white-space: pre-wrap;
      margin: 8px 0;
      color: var(--ink);
      font-weight: 650;
    }}
    .reason-list {{ margin: 8px 0 0 20px; padding: 0; color: var(--ink); }}
    .reason-list li {{ margin: 4px 0; }}
    .layout-bar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin: 8px 0 12px; }}
    .layout-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    .layout-toggle-button {{
      margin: 0;
      padding: 7px 9px;
      background: transparent;
      color: var(--ocf-dark);
      border-radius: 6px;
      box-shadow: none;
      gap: 6px;
      font-size: 13px;
    }}
    .layout-toggle-button:hover {{ background: var(--soft); color: var(--ocf-dark); box-shadow: none; transform: none; }}
    .layout-toggle-button.is-active:hover {{ color: var(--link); }}
    .layout-toggle-button.is-active {{ background: #eef1fb; color: var(--link); }}
    .layout-toggle-button svg {{
      width: 20px;
      height: 20px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .reader-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .reader-list {{ display: grid; gap: 10px; }}
    .reader-list-card {{
      border: 1px solid var(--line);
      border-left: 4px solid var(--link);
      border-radius: 8px;
      background: #fff;
      padding: 16px 18px;
      box-shadow: 0 1px 2px rgba(15,25,35,.04);
    }}
    .reader-list-card h3 {{
      margin: 8px 0 10px;
      font-size: 19px;
      line-height: 1.34;
    }}
    .reader-list-card h3 a {{ color: #4f3ed2; font-weight: 850; }}
    .reader-list-card .zh-summary {{
      margin: 0;
      font-size: 16px;
      line-height: 1.68;
      font-weight: 550;
    }}
    .reader-list-meta {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .reader-inbox-row {{
      display: grid;
      grid-template-columns: 11px minmax(140px, 220px) minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 11px 14px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    .reader-inbox-row:last-child {{ border-bottom: 0; }}
    .reader-inbox-row:hover {{ background: #fafbff; }}
    .reader-dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--link); }}
    .reader-row-source {{ min-width: 0; color: var(--muted); font-weight: 750; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .reader-row-main {{ min-width: 0; display: flex; gap: 8px; align-items: baseline; }}
    .reader-row-main h3 {{ flex: 0 1 auto; min-width: 28%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }}
    .reader-row-summary {{ flex: 1 1 auto; min-width: 0; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .reader-row-time {{ color: var(--muted); white-space: nowrap; font-weight: 750; }}
    .reader-row-tools {{ display: inline-flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: flex-end; }}
    .reader-compact-list {{ display: grid; gap: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fff; }}
    .reader-compact-row {{
      display: grid;
      grid-template-columns: 11px minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 9px 12px;
      border-bottom: 1px solid var(--line);
    }}
    .reader-compact-row:last-child {{ border-bottom: 0; }}
    .reader-compact-row h3 {{ margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }}
    .reader-layout-section[data-layout="card"] .reader-list,
    .reader-layout-section[data-layout="card"] .reader-compact-list {{ display: none; }}
    .reader-layout-section[data-layout="list"] .reader-grid,
    .reader-layout-section[data-layout="list"] .reader-compact-list {{ display: none; }}
    .reader-layout-section[data-layout="compact"] .reader-grid,
    .reader-layout-section[data-layout="compact"] .reader-list {{ display: none; }}
    .reader-category {{
      display: grid;
      gap: 12px;
      margin: 22px 0 30px;
    }}
    .reader-category > h2 {{
      margin-bottom: 0;
    }}
    .reader-period-details {{
      display: grid;
      gap: 10px;
      margin: 4px 0 18px;
    }}
    .reader-period-details > summary {{
      cursor: pointer;
      list-style: none;
    }}
    .reader-period-details > summary::-webkit-details-marker {{ display: none; }}
    .reader-period-heading {{
      position: relative;
      display: grid;
      place-items: center;
      gap: 2px;
      margin: 22px 0 2px;
      color: #a3abb8;
      font-size: 20px;
      font-weight: 900;
      letter-spacing: 0;
      text-align: center;
      text-shadow: 0 1px 0 #fff, 0 -1px 0 rgba(15,25,35,.08);
    }}
    .reader-period-heading::before {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      top: 50%;
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--line), transparent);
      z-index: 0;
    }}
    .reader-period-heading-label {{
      position: relative;
      z-index: 1;
      padding: 0 14px;
      background: var(--bg);
    }}
    .reader-period-count {{
      position: relative;
      z-index: 1;
      padding: 0 10px;
      background: var(--bg);
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-shadow: none;
    }}
    .reader-period-heading-label::after {{
      content: "收合";
      margin-left: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .reader-period-details:not([open]) .reader-period-heading-label::after {{
      content: "展開";
    }}
    .reader-more-row {{
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 8px;
      margin: 8px 0 30px;
    }}
    .reader-card {{
      display: grid;
      grid-template-rows: 160px auto;
      overflow: hidden;
      padding: 0;
    }}
    .reader-thumb {{
      min-height: 160px;
      background: linear-gradient(135deg, var(--ocf-primary), var(--ocf-cyan));
      color: #fff;
      display: flex;
      align-items: flex-end;
      padding: 14px;
      font-weight: 850;
    }}
    .reader-thumb--humanities {{ background: linear-gradient(135deg, var(--humanities), #2f6fb0); }}
    .reader-thumb--neutral {{ background: linear-gradient(135deg, #566172, var(--ocf-cyan)); }}
    .reader-thumb img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .reader-body {{ padding: 16px; display: grid; gap: 8px; }}
    .reader-card h3 {{ line-height: 1.35; }}
    .reader-card-actions {{
      gap: 5px;
      margin-top: 0;
      justify-content: flex-end;
      align-items: center;
    }}
    .reader-card-actions .reader-action-button {{
      width: 30px;
      height: 30px;
      min-width: 30px;
      padding: 0;
      border-radius: 6px;
      gap: 0;
      font-size: 0;
      line-height: 1;
    }}
    .reader-card-actions form {{ display: inline-flex; }}
    .reader-card-actions svg {{
      width: 15px;
      height: 15px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .reader-action-label {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
      border: 0;
    }}
    .article-top-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-start;
      margin: 0 0 14px;
    }}
    .article-top-nav .button {{ margin-top: 0; }}
    .article-top-nav .workspace-sidebar-toggle {{ margin-left: auto; }}
    .article-back-button {{
      color: var(--ocf-dark);
      background: #fff;
      border: 1px solid var(--line);
      box-shadow: none;
    }}
    .article-back-button:hover {{
      color: #00699f;
      background: #eefcff;
      border-color: #78cde5;
      box-shadow: none;
      transform: translateX(-1px);
    }}
    .article-detail-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 350px);
      gap: 18px;
      align-items: start;
      transition: grid-template-columns .28s ease, gap .28s ease;
    }}
    .article-detail-main {{
      display: grid;
      gap: 16px;
      min-width: 0;
    }}
    .article-detail-main > * {{ margin-top: 0; margin-bottom: 0; }}
    .article-detail-stack {{ display: grid; gap: 12px; }}
    .article-detail-stack > h2 {{ margin: 4px 0 0; }}
    .article-action-dock {{
      position: sticky;
      top: 78px;
      display: grid;
      gap: 12px;
      min-width: 0;
      max-height: calc(100vh - 96px);
      overflow: auto;
      align-self: start;
      z-index: 12;
      transition: transform .28s ease, opacity .28s ease;
    }}
    .article-detail-layout.is-sidebar-hidden {{
      grid-template-columns: minmax(0, 1fr) minmax(0, 0px);
      gap: 0;
    }}
    .article-detail-layout.is-sidebar-hidden .article-action-dock {{
      overflow: hidden;
      transform: translateX(24px);
      opacity: 0;
      pointer-events: none;
    }}
    .article-action-dock .card {{
      padding: 12px;
      display: grid;
      gap: 10px;
    }}
    .article-tool-section {{
      display: grid;
      gap: 8px;
    }}
    .article-tool-section-title {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      line-height: 1.25;
    }}
    .article-action-dock h2 {{
      font-size: 17px;
      margin: 0;
    }}
    .article-action-dock .button-row {{
      gap: 8px;
    }}
    .article-action-dock .button-row .button,
    .article-action-dock .button-row button,
    .article-action-dock form > button {{
      min-height: 30px;
      padding: 6px 8px;
      gap: 6px;
      font-size: 12px;
      line-height: 1.2;
    }}
    .article-action-dock textarea {{
      min-height: 88px;
    }}
    .article-action-dock details.card summary {{
      cursor: pointer;
      list-style: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .article-action-dock details.card summary::-webkit-details-marker {{ display: none; }}
    .article-action-dock details.card summary::after {{
      content: "+";
      color: var(--muted);
      font-weight: 900;
    }}
    .article-action-dock details.card[open] summary::after {{ content: "-"; }}
    .help-dot {{
      display: inline-grid;
      place-items: center;
      width: 18px;
      height: 18px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      font-weight: 900;
    }}
    .article-dock-actions form {{ display: inline-flex; margin: 0; }}
    .article-sequence-nav {{
      position: fixed;
      left: 18px;
      right: 18px;
      bottom: 18px;
      z-index: 60;
      pointer-events: none;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }}
    .article-sequence-link {{
      pointer-events: auto;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 42px;
      padding: 9px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ocf-dark);
      font-weight: 850;
      text-decoration: none;
      box-shadow: 0 8px 22px rgba(15,25,35,.14);
    }}
    .article-sequence-link:hover {{
      border-color: var(--ocf-cyan);
      color: #00699f;
      background: #eefcff;
      text-decoration: none;
    }}
    .item-hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
      gap: 18px;
      align-items: start;
    }}
    .article-title-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(180px, 260px);
      gap: 16px;
      align-items: start;
    }}
    .item-image {{
      min-height: 220px;
      border-radius: 8px;
      overflow: hidden;
      background: linear-gradient(135deg, var(--ocf-primary), var(--ocf-cyan));
      color: #fff;
      display: flex;
      align-items: flex-end;
      padding: 16px;
      font-weight: 850;
    }}
    .item-image--compact {{
      min-height: 0;
      height: 170px;
      padding: 12px;
      align-items: flex-end;
    }}
    .item-image img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .note-box {{
      border-left: 4px solid var(--ocf-cyan);
      background: #f7fbfe;
      padding: 10px 12px;
      border-radius: 8px;
    }}
    .fulltext-panel[hidden] {{ display: none; }}
    .article-text {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: clamp(18px, 4vw, 34px);
      background: var(--paper);
      max-width: 820px;
      margin: 0 auto;
      color: #17212f;
      font-size: 16px;
      font-family: var(--article-serif);
      font-weight: 260;
      line-height: 2.05;
      letter-spacing: 0;
      font-kerning: normal;
      font-variant-ligatures: common-ligatures contextual;
      box-shadow: 0 14px 34px rgba(58, 45, 18, .10), 0 1px 0 rgba(255,255,255,.85) inset;
    }}
    .reader-card .fulltext-panel .article-text {{
      max-height: 54vh;
      overflow: auto;
      padding: 16px;
      font-size: 15px;
    }}
    .article-markdown h1,
    .article-markdown h2,
    .article-markdown h3,
    .article-markdown h4,
    .article-markdown h5 {{
      font-family: var(--article-heading);
      font-weight: 850;
      line-height: 1.35;
      margin: 1.55em 0 .68em;
      letter-spacing: 0;
    }}
    .article-markdown h1 {{ color: var(--ocf-primary); font-size: 28px; margin-top: 0; }}
    .article-markdown h2 {{
      color: var(--ocf-primary);
      font-size: 22px;
      padding-bottom: 7px;
      border-bottom: 1px solid rgba(100,80,220,.24);
    }}
    .article-markdown h3 {{
      color: var(--ocf-primary);
      font-size: 19px;
      padding-left: 12px;
      border-left: 3px solid var(--ocf-primary);
    }}
    .article-markdown h4 {{
      color: var(--ocf-dark);
      font-size: 17px;
      padding-bottom: 4px;
      border-bottom: 1px dashed rgba(15,25,35,.22);
    }}
    .article-markdown h5 {{
      color: var(--ocf-dark);
      font-size: 15px;
      text-transform: none;
    }}
    .article-markdown p {{ margin: 0 0 1.25em; }}
    .article-markdown ul,
    .article-markdown ol {{ margin: 0 0 1.25em 1.4em; padding: 0; }}
    .article-markdown li {{ margin: .45em 0; }}
    .article-markdown blockquote {{
      margin: 1.1em 0;
      padding: .75em 1em;
      border-left: 4px solid var(--ocf-cyan);
      background: #f7fbfe;
      color: #30445f;
    }}
    .article-markdown pre {{
      margin: 1.1em 0;
      padding: 12px 14px;
      overflow: auto;
      white-space: pre-wrap;
      background: #f6f8fa;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: #263441;
    }}
    .article-markdown pre code {{
      display: block;
      background: transparent;
      border: 0;
      padding: 0;
      font-size: .95em;
      line-height: 1.65;
    }}
    .article-markdown strong,
    .article-markdown b,
    .article-markdown a {{
      font-weight: 550;
    }}
    .article-markdown a {{ overflow-wrap: anywhere; }}
    .article-markdown code {{
      background: #f2f5f8;
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 1px 4px;
      font-size: .92em;
    }}
    .loading-overlay {{
      position: fixed;
      inset: 0;
      display: none;
      place-items: center;
      background: rgba(15, 25, 35, .28);
      z-index: 100;
      padding: 20px;
    }}
    .loading-overlay.is-visible {{ display: grid; }}
    .loading-card {{
      width: min(420px, 100%);
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 14px 40px rgba(15,25,35,.22);
      padding: 18px;
    }}
    .loading-dots span {{
      display: inline-block;
      width: 6px;
      height: 6px;
      margin-right: 4px;
      border-radius: 50%;
      background: var(--ocf-primary);
      animation: loading-dot 900ms infinite ease-in-out;
    }}
    .loading-dots span:nth-child(2) {{ animation-delay: 120ms; }}
    .loading-dots span:nth-child(3) {{ animation-delay: 240ms; }}
    @keyframes loading-dot {{
      0%, 80%, 100% {{ transform: translateY(0); opacity: .45; }}
      40% {{ transform: translateY(-5px); opacity: 1; }}
    }}
    .command-window {{
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 120;
      width: min(680px, calc(100vw - 28px));
      max-height: min(76vh, 680px);
      display: none;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 48px rgba(15,25,35,.24);
      overflow: hidden;
    }}
    .command-window.is-visible {{ display: grid; grid-template-rows: auto minmax(0, 1fr); }}
    .command-window header {{
      position: static;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--soft);
    }}
    .command-window-body {{ padding: 14px; overflow: auto; }}
    .command-window pre {{ max-height: 44vh; }}
    .pdf-relation-dialog {{
      width: min(1040px, calc(100vw - 28px));
      max-height: calc(100vh - 40px);
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 24px 80px rgba(21, 24, 31, .28);
    }}
    .pdf-relation-dialog::backdrop {{ background: rgba(28, 31, 38, .52); }}
    .dialog-close-row {{ display: flex; justify-content: flex-end; }}
    /* 拆連結勾選視窗 */
    .nl-dialog {{ width: min(720px, calc(100vw - 28px)); }}
    /* 蓋掉 .article-dock-actions form 的 inline-flex（dialog 是 dock 的子節點） */
    .nl-dialog form {{ display: block; margin: 0; }}
    .nl-cand-list {{ display: grid; gap: 4px; max-height: 52vh; overflow: auto; margin: 10px 0; padding-right: 4px; }}
    .nl-cand {{ display: flex; align-items: baseline; gap: 8px; padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .nl-cand input {{ flex: 0 0 auto; }}
    .nl-cand-title {{ flex: 1 1 auto; min-width: 0; font-weight: 600; word-break: break-word; }}
    .nl-cand-host {{ flex: 0 0 auto; color: var(--muted, #64748b); font-size: 12px; }}
    .nl-skip {{ margin-top: 6px; }}
    .nl-skip ul {{ margin: 6px 0 0; padding-left: 18px; color: var(--muted, #64748b); font-size: 13px; }}
    .nl-cand--skip {{ background: var(--surface-2, #f8fafc); opacity: 0.85; }}
    .nl-cand--skip .nl-cand-title {{ font-weight: 500; }}
    .pdf-relation-grid, .pdf-split-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .pdf-relation-card {{ border: 1px solid var(--line); border-radius: 14px; padding: 14px; background: var(--panel); }}
    .pdf-relation-actions form, .pdf-cli-confirm-form {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; }}
    .pdf-split-results {{ margin-top: 24px; }}
    .pdf-split-proposal {{ align-self: start; }}
    .pdf-split-section {{ border: 1px solid var(--line); border-radius: 12px; padding: 12px; margin: 12px 0; }}
    .pdf-split-section legend {{ font-weight: 800; padding: 0 6px; }}
    .pdf-split-section textarea {{ min-height: 72px; }}
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; padding: 14px 18px; }}
      main {{ padding: 20px 16px; }}
      .two-column {{ grid-template-columns: 1fr; }}
      .article-detail-layout, .article-detail-layout.is-sidebar-hidden {{ grid-template-columns: 1fr; gap: 18px; }}
      .article-action-dock {{ position: static; max-height: none; order: -1; }}
      .article-detail-layout.is-sidebar-hidden .article-action-dock {{ display: none; }}
      .workspace-layout, .workspace-layout.is-sidebar-hidden {{ grid-template-columns: 1fr; gap: 18px; }}
      .workspace-sidebar {{ position: static; max-height: none; order: -1; }}
      .workspace-layout.is-sidebar-hidden .workspace-sidebar {{ display: none; }}
      .pdf-relation-grid, .pdf-split-grid {{ grid-template-columns: 1fr; }}
      .article-sequence-nav {{ left: 10px; right: 10px; bottom: 10px; }}
      .article-sequence-link span {{ display: none; }}
      .item-hero {{ grid-template-columns: 1fr; }}
      .article-title-grid {{ grid-template-columns: 1fr; }}
      .article-title-heading {{ display: grid; gap: 8px; }}
      .article-title-tools {{ padding-top: 0; }}
      .title-popover {{
        left: 0;
        right: auto;
        width: min(720px, calc(100vw - 32px));
        max-width: calc(100vw - 32px);
      }}
      .item-image--compact {{ height: 180px; }}
      .metric-row {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .layout-toggle {{ width: 100%; justify-content: space-between; }}
      .layout-toggle-button {{ flex: 1 1 0; }}
      .reader-inbox-row {{ grid-template-columns: 9px minmax(0, 1fr) auto; gap: 9px; }}
      .reader-row-source {{ display: none; }}
      .reader-row-main {{ display: block; }}
      .reader-row-main h3, .reader-row-summary {{ display: block; min-width: 0; }}
      th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header>
    <a class="brand" href="/">Ian Open News</a>
    <nav>
      <details class="nav-menu">
        <summary>{icon_span("home", "H")}共通入口</summary>
        <div class="nav-menu-links">
          <a href="/">{icon_span("home", "H")}總覽</a>
          <a href="/track/open-tech-open-industry">{icon_span("globe", "O")}開放科技</a>
          <a href="/track/digital-humanities-local-knowledge">{icon_span("archive", "L")}人文知識</a>
        </div>
      </details>
      <details class="nav-menu">
        <summary>{icon_span("workspace", "W")}材料區</summary>
        <div class="nav-menu-links">
          <a href="/items">{icon_span("rss", "R")}入庫建檔區</a>
          <a href="/recycle-bin">{icon_span("archive", "T")}資源回收區</a>
          <a href="/candidates">{icon_span("inbox", "C")}可用材料區</a>
          <a href="/reader">{icon_span("read", "B")}閱讀區</a>
        </div>
      </details>
      <details class="nav-menu">
        <summary>{icon_span("edit", "E")}編輯台</summary>
        <div class="nav-menu-links">
          <a href="/editor">{icon_span("edit", "E")}編輯台</a>
          <a href="/editor/viewpoints">{icon_span("note", "V")}觀點庫</a>
          <a href="/articles">{icon_span("text-lines", "A")}專文</a>
        </div>
      </details>
      <details class="nav-menu">
        <summary>{icon_span("plus", "N")}新增</summary>
        <div class="nav-menu-links">
          <a href="/items/new">{icon_span("plus", "N")}手動入庫</a>
          <a href="/items/upload-pdf">{icon_span("text-lines", "P")}上傳 PDF</a>
          <a href="/sources/new">{icon_span("rss", "R")}加 RSS</a>
        </div>
      </details>
      <details class="nav-menu">
        <summary>{icon_span("settings", "M")}管理</summary>
        <div class="nav-menu-links">
          <a href="/keywords">{icon_span("filter", "F")}關鍵字</a>
          <a href="/sources">{icon_span("source", "S")}RSS 來源</a>
          <a href="/insights">{icon_span("note", "I")}決策洞察{_insights_nav_badge()}</a>
        </div>
      </details>
    </nav>
    <form class="omnibar" action="/search" method="get" role="search" autocomplete="off">
      {icon_span("search", "", "omnibar-search-icon")}
      <input type="search" name="q" id="omnibar-input" placeholder="搜尋標籤 / 材料 / 觀點 / 編輯歷程 / RSS / 專文" aria-label="全站搜尋" aria-expanded="false" aria-controls="omnibar-suggest" data-omnibar-input data-omnibar-box="omnibar-suggest">
      <div class="omnibar-suggest" id="omnibar-suggest" role="listbox" hidden></div>
    </form>
  </header>
  <main>{body}</main>{OMNIBAR_CSS}{OMNIBAR_JS}
  <section class="command-window" id="command-window" aria-live="polite" aria-hidden="true">
    <header>
      <strong id="command-title">本機指令</strong>
      <button type="button" class="quiet" id="command-close">關閉</button>
    </header>
    <div class="command-window-body">
      <p class="muted" id="command-status">等待執行。</p>
      <div class="loading-dots" id="command-loading" hidden><span></span><span></span><span></span></div>
      <pre id="command-output" hidden></pre>
    </div>
  </section>
  <script>
  const setShortcutMode = (active) => {{
    document.body.classList.toggle("show-shortcuts", Boolean(active));
  }};
  window.addEventListener("keydown", (event) => {{
    if (event.altKey) setShortcutMode(true);
  }});
  window.addEventListener("keyup", (event) => {{
    if (!event.altKey) setShortcutMode(false);
  }});
  window.addEventListener("blur", () => setShortcutMode(false));

  document.querySelectorAll(".nav-menu").forEach((menu) => {{
    const positionMenu = () => {{
      if (!menu.open) return;
      const panel = menu.querySelector(".nav-menu-links");
      if (!panel) return;
      panel.style.transform = "";
      const margin = 12;
      const rect = panel.getBoundingClientRect();
      let shift = 0;
      if (rect.left < margin) shift += margin - rect.left;
      if (rect.right + shift > window.innerWidth - margin) {{
        shift -= rect.right + shift - (window.innerWidth - margin);
      }}
      panel.style.transform = `translateX(${{Math.round(shift)}}px)`;
    }};
    menu.addEventListener("toggle", () => {{
      if (!menu.open) return;
      document.querySelectorAll(".nav-menu").forEach((other) => {{
        if (other !== menu) other.open = false;
      }});
      window.requestAnimationFrame(positionMenu);
    }});
    window.addEventListener("resize", positionMenu);
  }});

  const syncLayoutButtons = (targetId, mode) => {{
    document.querySelectorAll(`.layout-toggle-button[data-layout-target="${{targetId}}"]`).forEach((peer) => {{
      const active = peer.dataset.layoutMode === mode;
      peer.classList.toggle("is-active", active);
      peer.setAttribute("aria-pressed", active ? "true" : "false");
    }});
  }};
  const setupLayoutControls = (root = document) => {{
    root.querySelectorAll(".layout-toggle-button").forEach((button) => {{
      if (button.dataset.layoutBound === "1") return;
      button.dataset.layoutBound = "1";
      button.addEventListener("click", () => {{
        const target = document.getElementById(button.dataset.layoutTarget);
        if (!target) return;
        const mode = button.dataset.layoutMode;
        target.dataset.layout = mode;
        syncLayoutButtons(button.dataset.layoutTarget, mode);
        if (target.hasAttribute("data-layout-persist")) {{
          try {{ window.localStorage.setItem(`ian-open-news-layout:${{button.dataset.layoutTarget}}`, mode); }} catch (_error) {{}}
        }}
      }});
    }});
    // 還原有 data-layout-persist 的容器先前選的顯示模式
    root.querySelectorAll("[data-layout-persist]").forEach((target) => {{
      let saved = null;
      try {{ saved = window.localStorage.getItem(`ian-open-news-layout:${{target.id}}`); }} catch (_error) {{ saved = null; }}
      if (!saved) return;
      target.dataset.layout = saved;
      syncLayoutButtons(target.id, saved);
    }});
  }};

  const setCandidateExpanded = (button, expanded) => {{
    const card = button.closest(".candidate-card");
    if (!card) return;
    card.classList.toggle("is-expanded", expanded);
    button.setAttribute("aria-expanded", expanded ? "true" : "false");
    const label = expanded ? "收合這則材料" : "展開這則材料";
    button.setAttribute("aria-label", label);
    button.title = label;
  }};
  const setupCandidateExpandControls = (root = document) => {{
    root.querySelectorAll("[data-item-expand]").forEach((button) => {{
      if (button.dataset.expandBound === "1") return;
      button.dataset.expandBound = "1";
      button.addEventListener("click", (event) => {{
        event.preventDefault();
        const card = button.closest(".candidate-card");
        setCandidateExpanded(button, !card?.classList.contains("is-expanded"));
      }});
    }});
  }};

  const setupWorkspaceToggleControls = (root = document) => {{
    root.querySelectorAll("[data-workspace-toggle]").forEach((button) => {{
      const layout = document.getElementById(button.dataset.workspaceTarget || "");
      const sidebar = document.getElementById(button.dataset.sidebarTarget || "");
      if (!layout || !sidebar) return;
      const storageKey = `ian-open-news-sidebar:${{button.dataset.sidebarStorageKey || button.dataset.sidebarTarget || "default"}}`;
      const label = button.querySelector("[data-sidebar-toggle-label]");
      const applyState = (hidden) => {{
        layout.classList.toggle("is-sidebar-hidden", hidden);
        sidebar.setAttribute("aria-hidden", hidden ? "true" : "false");
        button.setAttribute("aria-expanded", hidden ? "false" : "true");
        if (label) label.textContent = hidden ? "顯示工具欄" : "隱藏工具欄";
        button.title = hidden ? "顯示工具欄" : "隱藏工具欄";
      }};
      let hidden = false;
      try {{
        hidden = window.localStorage.getItem(storageKey) === "hidden";
      }} catch (_error) {{
        hidden = false;
      }}
      applyState(hidden);
      if (button.dataset.workspaceToggleBound === "1") return;
      button.dataset.workspaceToggleBound = "1";
      button.addEventListener("click", () => {{
        hidden = !layout.classList.contains("is-sidebar-hidden");
        applyState(hidden);
        try {{
          window.localStorage.setItem(storageKey, hidden ? "hidden" : "visible");
        }} catch (_error) {{
          // The layout still works when browser storage is unavailable.
        }}
      }});
    }});
  }};

  const instantFilterSelectors = (form) => (form.dataset.instantFilterTargets || "main")
    .split(",")
    .map((selector) => selector.trim())
    .filter(Boolean);
  let instantFilterAbort = null;
  let instantFilterSequence = 0;
  const instantFilterUrl = (form) => {{
    const data = new FormData(form);
    const url = new URL(form.getAttribute("action") || location.pathname, location.href);
    const params = new URLSearchParams();
    data.forEach((value, key) => {{
      const text = String(value);
      if (!text || text === "all" || text === "auto") return;
      params.append(key, text);
    }});
    url.search = params.toString();
    return url;
  }};
  const activeFilterField = (form) => {{
    const active = document.activeElement;
    if (!active || !form.contains(active) || !active.name) return null;
    return {{
      formId: form.id || "",
      name: active.name,
      value: active.value || "",
      type: (active.type || "").toLowerCase(),
    }};
  }};
  const restoreFilterFocus = (info) => {{
    if (!info || !info.formId) return;
    const form = document.getElementById(info.formId);
    if (!form) return;
    let field = null;
    if (info.type === "checkbox" || info.type === "radio") {{
      field = Array.from(form.querySelectorAll(`[name="${{CSS.escape(info.name)}}"]`))
        .find((candidate) => candidate.value === info.value);
    }} else {{
      field = form.querySelector(`[name="${{CSS.escape(info.name)}}"]`);
    }}
    if (field && typeof field.focus === "function") field.focus({{preventScroll: true}});
  }};
  const setInstantFilterBusy = (form, active) => {{
    const layout = form.closest(".workspace-layout");
    if (layout) layout.classList.toggle("is-filtering", active);
    form.setAttribute("aria-busy", active ? "true" : "false");
  }};
  const rebindPageAfterPartialUpdate = () => {{
    setupLocalWebDynamicControls(document);
    if (typeof window.initItemsPage === "function") window.initItemsPage();
    if (typeof window.initReaderPage === "function") window.initReaderPage();
    window.dispatchEvent(new CustomEvent("localweb:partial-update"));
  }};
  const loadInstantFilter = async (url, form, options = {{}}) => {{
    if (!window.fetch || !window.DOMParser) {{
      location.href = url.toString();
      return;
    }}
    if (instantFilterAbort) instantFilterAbort.abort();
    const controller = new AbortController();
    instantFilterAbort = controller;
    const sequence = ++instantFilterSequence;
    const focusInfo = activeFilterField(form);
    setInstantFilterBusy(form, true);
    try {{
      const response = await fetch(url.toString(), {{
        method: "GET",
        credentials: "same-origin",
        signal: controller.signal,
        headers: {{"X-Requested-With": "local-web-filter"}},
      }});
      if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
      const text = await response.text();
      if (sequence !== instantFilterSequence) return;
      const doc = new DOMParser().parseFromString(text, "text/html");
      instantFilterSelectors(form).forEach((selector) => {{
        const fresh = doc.querySelector(selector);
        const current = document.querySelector(selector);
        if (fresh && current) current.replaceWith(fresh);
      }});
      if (doc.title) document.title = doc.title;
      if (options.history !== false) {{
        history.pushState({{instantFilter: true}}, "", url.toString());
      }}
      rebindPageAfterPartialUpdate();
      restoreFilterFocus(focusInfo);
    }} catch (error) {{
      if (error && error.name === "AbortError") return;
      location.href = url.toString();
    }} finally {{
      if (sequence === instantFilterSequence) {{
        const currentForm = document.getElementById(form.id) || form;
        setInstantFilterBusy(currentForm, false);
        instantFilterAbort = null;
      }}
    }}
  }};
  const submitInstantFilter = (form) => loadInstantFilter(instantFilterUrl(form), form);
  const setupInstantFilterForms = (root = document) => {{
    root.querySelectorAll("form[data-instant-filter]").forEach((form) => {{
      if (form.dataset.instantFilterBound !== "1") {{
        form.dataset.instantFilterBound = "1";
        form.addEventListener("submit", (event) => {{
          event.preventDefault();
          submitInstantFilter(form);
        }});
      }}
      form.querySelectorAll(".auto-filter, input[type='checkbox'], input[type='date']").forEach((field) => {{
        if (field.dataset.instantFieldBound === "1") return;
        field.dataset.instantFieldBound = "1";
        if (field.matches("input[type='search']")) {{
          let searchTimer = 0;
          field.addEventListener("input", () => {{
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(() => submitInstantFilter(form), 320);
          }});
        }}
        field.addEventListener("change", () => {{
          if (form.id === "reader-filter-form" && field.id === "reader-time-filter") {{
            if (typeof window.syncReaderTimeFields === "function") window.syncReaderTimeFields();
            if (field.value === "custom") {{
              const hasDate = Array.from(form.querySelectorAll("[data-time-custom-fields] input"))
                .some((input) => input.value);
              if (!hasDate) return;
            }}
          }}
          submitInstantFilter(form);
        }});
      }});
    }});
  }};
  document.addEventListener("click", (event) => {{
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target || link.hasAttribute("download") || !link.closest("main")) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || url.pathname !== location.pathname) return;
    const form = document.querySelector(`form[data-instant-filter][action="${{url.pathname}}"]`)
      || document.querySelector("form[data-instant-filter]");
    if (!form) return;
    event.preventDefault();
    loadInstantFilter(url, form);
  }});
  window.addEventListener("popstate", () => {{
    const form = document.querySelector("form[data-instant-filter]");
    if (!form) {{
      location.reload();
      return;
    }}
    loadInstantFilter(new URL(location.href), form, {{history: false}});
  }});
  const setupLocalWebDynamicControls = (root = document) => {{
    setupLayoutControls(root);
    setupCandidateExpandControls(root);
    setupWorkspaceToggleControls(root);
    setupInstantFilterForms(root);
  }};
  setupLocalWebDynamicControls(document);

  document.querySelectorAll(".article-title-menu").forEach((menu) => {{
    const positionPopover = () => {{
      if (!menu.open) return;
      const panel = menu.querySelector(".title-popover");
      if (!panel) return;
      panel.style.transform = "";
      panel.style.maxHeight = "";
      const margin = 12;
      const rect = panel.getBoundingClientRect();
      let shift = 0;
      if (rect.left < margin) shift += margin - rect.left;
      if (rect.right + shift > window.innerWidth - margin) {{
        shift -= rect.right + shift - (window.innerWidth - margin);
      }}
      panel.style.transform = `translateX(${{Math.round(shift)}}px)`;
      const shiftedRect = panel.getBoundingClientRect();
      const availableHeight = Math.max(180, window.innerHeight - Math.max(margin, shiftedRect.top) - margin);
      panel.style.maxHeight = `${{Math.floor(availableHeight)}}px`;
    }};
    menu.addEventListener("toggle", () => {{
      if (!menu.open) return;
      document.querySelectorAll(".article-title-menu").forEach((other) => {{
        if (other !== menu) other.open = false;
      }});
      window.requestAnimationFrame(positionPopover);
    }});
    window.addEventListener("resize", positionPopover);
  }});

  document.querySelectorAll("[data-copy-share-url]").forEach((button) => {{
    button.addEventListener("click", async () => {{
      const url = button.dataset.copyShareUrl || "";
      const panel = button.closest(".share-panel");
      const input = panel?.querySelector("[data-share-url-field]");
      const status = panel?.querySelector("[data-copy-share-status]");
      let ok = false;
      try {{
        if (navigator.clipboard?.writeText) {{
          await navigator.clipboard.writeText(url);
          ok = true;
        }}
      }} catch (_error) {{
        ok = false;
      }}
      if (!ok && input) {{
        input.focus();
        input.select();
        try {{
          ok = document.execCommand("copy");
        }} catch (_error) {{
          ok = false;
        }}
      }}
      if (status) status.textContent = ok ? "已複製線上版網址" : "已選取網址，可以手動複製";
    }});
  }});

  const commandWindow = document.getElementById("command-window");
  const commandTitle = document.getElementById("command-title");
  const commandStatus = document.getElementById("command-status");
  const commandOutput = document.getElementById("command-output");
  const commandLoading = document.getElementById("command-loading");
  document.getElementById("command-close")?.addEventListener("click", () => {{
    commandWindow?.classList.remove("is-visible");
    commandWindow?.setAttribute("aria-hidden", "true");
  }});

  const openCommandWindow = (label, status = "已送出，正在執行固定指令...") => {{
    commandTitle.textContent = label || "本機指令";
    commandStatus.textContent = status;
    commandOutput.hidden = true;
    commandOutput.textContent = "";
    commandLoading.hidden = false;
    commandWindow.classList.add("is-visible");
    commandWindow.setAttribute("aria-hidden", "false");
  }};

  const startElapsedStatus = () => {{
    const startedAt = Date.now();
    return window.setInterval(() => {{
      const seconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      commandStatus.textContent = `執行中，已等待 ${{seconds}} 秒。`;
    }}, 1000);
  }};

  const rssStatusLine = (payload) => {{
    const message = payload?.message || "正在抓取 RSS。";
    const index = payload?.source_index && payload?.selected_sources ? `（${{payload.source_index}}/${{payload.selected_sources}}）` : "";
    const total = payload?.new_items !== undefined ? `新增 ${{payload.new_items}} 則` : "";
    const excluded = payload?.excluded_items !== undefined ? `，排除 ${{payload.excluded_items}} 則` : "";
    const suffix = total ? `；${{total}}${{excluded}}` : "";
    return `${{message}}${{index}}${{suffix}}`;
  }};

  const commandStatusLine = (payload) => {{
    if (!payload || !payload.message) return "執行中。";
    let index = "";
    if (payload.index && payload.total) {{
      index = payload.end_index && payload.end_index !== payload.index
        ? `（${{payload.index}}-${{payload.end_index}}/${{payload.total}}）`
        : `（${{payload.index}}/${{payload.total}}）`;
    }}
    const title = payload.item_title ? `：${{payload.item_title}}` : "";
    return `${{payload.message}}${{index}}${{title}}`;
  }};

  const startRssStatusPolling = () => {{
    const poll = async () => {{
      try {{
        const response = await fetch("/api/rss-status", {{headers: {{"X-Requested-With": "local-web-fetch"}}}});
        if (!response.ok) return;
        const payload = await response.json();
        commandStatus.textContent = rssStatusLine(payload);
      }} catch (_error) {{
        // Keep the command window alive; the command response will still show the final output.
      }}
    }};
    poll();
    return window.setInterval(poll, 1200);
  }};

  const startCommandStatusPolling = (commandName) => {{
    const poll = async () => {{
      try {{
        const response = await fetch(`/api/command-status?command=${{encodeURIComponent(commandName)}}`, {{headers: {{"X-Requested-With": "local-web-fetch"}}}});
        if (!response.ok) return;
        const payload = await response.json();
        if (payload?.command === commandName && payload?.state === "running") {{
          commandStatus.textContent = commandStatusLine(payload);
        }}
      }} catch (_error) {{
        // The final command response still carries stdout/stderr if polling is unavailable.
      }}
    }};
    poll();
    return window.setInterval(poll, 1200);
  }};

  const startJsonStatusPolling = (url) => {{
    const poll = async () => {{
      try {{
        const response = await fetch(url, {{headers: {{"X-Requested-With": "local-web-fetch"}}}});
        if (!response.ok) return;
        const payload = await response.json();
        if (payload?.message) commandStatus.textContent = commandStatusLine(payload);
      }} catch (_error) {{
        // Keep the elapsed/final result path available when polling is interrupted.
      }}
    }};
    poll();
    return window.setInterval(poll, 1200);
  }};

  const commandTimerFor = (commandName) => {{
    if (commandName === "fetch_rss") return startRssStatusPolling();
    if (commandName === "enrich_reader_metadata" || commandName === "codex_enrich_reviews" || commandName === "codex_review_batch") return startCommandStatusPolling(commandName);
    return startElapsedStatus();
  }};

  let pendingJobs = 0;
  const markJobStart = () => {{ pendingJobs += 1; }};
  const markJobEnd = () => {{ pendingJobs = Math.max(0, pendingJobs - 1); }};
  window.addEventListener("beforeunload", (event) => {{
    if (pendingJobs > 0) {{
      event.preventDefault();
      event.returnValue = "還有 AI 或抓取工作在進行，確定要離開或切換頁面嗎？";
      return event.returnValue;
    }}
  }});

  const ENGINE_LABELS = {json.dumps({provider: AI_PROVIDER_META[provider]["label"] for provider in AI_PROVIDER_ORDER}, ensure_ascii=False)};
  const ALL_ENGINES = {json.dumps(AI_PROVIDER_ORDER, ensure_ascii=False)};

  // 共用 AI 工作執行器：隨機→失敗自動換其他 CLI（每次跳視窗）；指定引擎→只提醒、不自動換。
  window.runEngineJob = async ({{ label, url, baseBody, engine, onSuccess, statusUrl }}) => {{
    let order;
    if (engine === "random") {{
      order = ALL_ENGINES.slice();
      for (let i = order.length - 1; i > 0; i--) {{
        const j = Math.floor(Math.random() * (i + 1));
        const t = order[i]; order[i] = order[j]; order[j] = t;
      }}
    }} else {{
      order = [engine];
    }}
    const allowFallback = engine === "random";
    markJobStart();
    let timer = null;
    try {{
      for (let i = 0; i < order.length; i++) {{
        const eng = order[i];
        openCommandWindow(label, `使用 ${{ENGINE_LABELS[eng] || eng}} 執行中...`);
        commandLoading.hidden = false;
        if (timer) window.clearInterval(timer);
        timer = statusUrl ? startJsonStatusPolling(statusUrl) : startElapsedStatus();
        let payload;
        try {{
          const data = new URLSearchParams(baseBody);
          data.set("format", "json");
          data.set("provider", eng);
          data.set("engine", eng);
          const response = await fetch(url, {{
            method: "POST",
            headers: {{ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With": "local-web-fetch" }},
            body: data
          }});
          payload = await response.json();
        }} catch (error) {{
          payload = {{ ok: false, error: String(error) }};
        }}
        if (timer) {{ window.clearInterval(timer); timer = null; }}
        const ok = payload && payload.ok !== false && (payload.returncode === undefined || payload.returncode === 0);
        if (ok) {{
          commandLoading.hidden = true;
          commandStatus.textContent = `✓ ${{ENGINE_LABELS[eng] || eng}} 完成。`;
          if (payload.output) {{ commandOutput.hidden = false; commandOutput.textContent = payload.output; }}
          if (onSuccess) onSuccess(payload, eng);
          return true;
        }}
        const errMsg = (payload && (payload.error || payload.summary)) || `exit ${{payload ? payload.returncode : "?"}}`;
        const others = ALL_ENGINES.filter((e) => e !== eng).map((e) => ENGINE_LABELS[e]).join(" 或 ");
        if (allowFallback && i < order.length - 1) {{
          commandLoading.hidden = true;
          commandStatus.textContent = `✗ ${{ENGINE_LABELS[eng]}} 失敗，改用 ${{ENGINE_LABELS[order[i + 1]]}} 重試…`;
          window.alert(`${{label}}\n${{ENGINE_LABELS[eng]}} 失敗：${{errMsg}}\n改用 ${{ENGINE_LABELS[order[i + 1]]}} 重試。`);
          continue;
        }}
        commandLoading.hidden = true;
        commandStatus.textContent = `✗ ${{ENGINE_LABELS[eng] || eng}} 失敗：${{errMsg}}`;
        commandOutput.hidden = false;
        commandOutput.textContent = errMsg;
        if (allowFallback) {{
          window.alert(`${{label}}\n所有可用 AI CLI 都失敗了，請稍後再試或檢查登入狀態。`);
        }} else {{
          window.alert(`${{label}}\n${{ENGINE_LABELS[eng] || eng}} 失敗：${{errMsg}}\n可改用 ${{others}} 再跑一次。`);
        }}
        return false;
      }}
    }} finally {{
      if (timer) window.clearInterval(timer);
      markJobEnd();
    }}
    return false;
  }};

  window.runFetchJob = async ({{ label, url, baseBody, statusUrl, onSuccess, onError }}) => {{
    markJobStart();
    let timer = null;
    try {{
      openCommandWindow(label, "執行中…");
      commandLoading.hidden = false;
      timer = statusUrl ? startJsonStatusPolling(statusUrl) : startElapsedStatus();
      let payload;
      try {{
        const data = new URLSearchParams(baseBody);
        data.set("format", "json");
        const response = await fetch(url, {{
          method: "POST",
          headers: {{ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With": "local-web-fetch" }},
          body: data
        }});
        payload = await response.json();
      }} catch (error) {{
        payload = {{ ok: false, error: String(error) }};
      }}
      if (timer) {{ window.clearInterval(timer); timer = null; }}
      const ok = payload && payload.ok !== false;
      if (ok) {{
        commandLoading.hidden = true;
        commandStatus.textContent = payload.message || "✓ 完成。";
        if (payload.output) {{ commandOutput.hidden = false; commandOutput.textContent = payload.output; }}
        if (onSuccess) onSuccess(payload);
        return true;
      }}
      commandLoading.hidden = true;
      const errMsg = (payload && (payload.error || payload.message)) || "執行失敗";
      commandStatus.textContent = "✗ " + errMsg;
      if (onError) onError(payload);
      return false;
    }} finally {{
      if (timer) window.clearInterval(timer);
      markJobEnd();
    }}
  }};

  window.runTwoEngineJob = async ({{ label, url, baseBody, engines, onSuccess, statusUrl }}) => {{
    let order = Array.isArray(engines) && engines.length
      ? engines.slice()
      : ALL_ENGINES.slice().sort(() => Math.random() - 0.5);
    order = Array.from(new Set(order.filter((engine) => ALL_ENGINES.includes(engine))));
    const completed = [];
    for (const engine of order) {{
      const ok = await window.runEngineJob({{
        label: `${{label}}（${{completed.length + 1}}/2）`,
        url,
        baseBody,
        engine,
        statusUrl,
        onSuccess: (payload, usedEngine) => {{
          completed.push(usedEngine);
          if (onSuccess) onSuccess(payload, usedEngine, completed.slice());
        }}
      }});
      if (completed.length >= 2) return completed;
      if (!ok && Array.isArray(engines) && engines.length) return completed;
    }}
    if (completed.length < 2) {{
      window.alert(`${{label}}\n目前沒有湊到兩個成功的不同 CLI 提案。`);
    }}
    return completed;
  }};

  document.querySelectorAll("[data-pdf-split-random]").forEach((button) => {{
    button.addEventListener("click", async () => {{
      const itemId = button.getAttribute("data-item-id") || "";
      const completed = await window.runTwoEngineJob({{
        label: "產生 PDF 拆分草案",
        url: "/items/pdf-split-suggest",
        baseBody: {{id: itemId}},
        statusUrl: "/api/pdf-split-status",
      }});
      if (completed.length >= 2) location.reload();
    }});
  }});

  document.querySelectorAll("[data-pdf-split-specified]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const data = new FormData(form);
      const engines = [String(data.get("engine_a") || ""), String(data.get("engine_b") || "")];
      if (!engines[0] || !engines[1] || engines[0] === engines[1]) {{
        window.alert("請選兩個不同的 CLI。");
        return;
      }}
      const completed = await window.runTwoEngineJob({{
        label: "產生 PDF 拆分草案",
        url: "/items/pdf-split-suggest",
        baseBody: {{id: String(data.get("id") || "")}},
        engines,
        statusUrl: "/api/pdf-split-status",
      }});
      if (completed.length >= 2) location.reload();
    }});
  }});

  document.querySelectorAll("[data-pdf-relation-confirm]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const data = new FormData(form);
      const engine = String(data.get("engine") || "random");
      await window.runEngineJob({{
        label: "用 CLI 確認 PDF 關係",
        url: "/items/pdf-relation-confirm",
        baseBody: {{
          id: String(data.get("id") || ""),
          candidate_id: String(data.get("candidate_id") || ""),
        }},
        engine,
        onSuccess: () => location.reload(),
      }});
    }});
  }});

  document.querySelectorAll("[data-pdf-relation-dialog]").forEach((dialog) => {{
    if (dialog.getAttribute("data-auto-open") === "1" && typeof dialog.showModal === "function") {{
      dialog.showModal();
    }}
  }});

  document.querySelectorAll("form[data-command-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const button = event.submitter || form.querySelector("button");
      const label = form.closest(".command-card")?.querySelector("strong")?.textContent?.trim()
        || form.closest(".card")?.querySelector("h3")?.textContent?.trim()
        || "本機指令";
      openCommandWindow(label);
      markJobStart();
      if (button) button.disabled = true;
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      const timer = commandTimerFor(data.get("command") || "");
      try {{
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        commandStatus.textContent = payload.summary || `完成，exit code ${{payload.returncode}}。`;
        commandOutput.hidden = false;
        commandOutput.textContent = payload.output || "(沒有輸出)";
      }} catch (error) {{
        commandStatus.textContent = "指令沒有順利回傳，請看終端機或稍後再試。";
        commandOutput.hidden = false;
        commandOutput.textContent = String(error);
      }} finally {{
        if (timer) window.clearInterval(timer);
        commandLoading.hidden = true;
        markJobEnd();
        if (button) button.disabled = false;
      }}
    }});
  }});

  document.querySelectorAll("[data-engine-job]").forEach((btn) => {{
    btn.addEventListener("click", () => {{
      if (!window.runEngineJob) return;
      window.runEngineJob({{
        label: btn.dataset.label || "AI 工作",
        url: "/commands/run",
        baseBody: {{ command: btn.dataset.command }},
        engine: btn.dataset.engine,
      }});
    }});
  }});

  document.querySelectorAll("form[data-source-fetch-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const button = event.submitter || form.querySelector("button");
      const sourceName = form.closest("tr")?.querySelector("strong")?.textContent?.trim()
        || document.querySelector("h1")?.textContent?.trim()
        || "RSS";
      openCommandWindow(`手動更新 RSS：${{sourceName}}`, "已送出，正在抓取這個 RSS...");
      markJobStart();
      if (button) button.disabled = true;
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      const timer = startRssStatusPolling();
      try {{
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        commandStatus.textContent = payload.summary || `完成，exit code ${{payload.returncode}}。`;
        commandOutput.hidden = false;
        commandOutput.textContent = payload.output || payload.summary || "(沒有輸出)";
      }} catch (error) {{
        commandStatus.textContent = "手動更新 RSS 沒有順利回傳，請看終端機或稍後再試。";
        commandOutput.hidden = false;
        commandOutput.textContent = String(error);
      }} finally {{
        if (timer) window.clearInterval(timer);
        commandLoading.hidden = true;
        markJobEnd();
        if (button) button.disabled = false;
      }}
    }});
  }});

  document.querySelectorAll("form[data-source-toggle-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const button = form.querySelector("[data-source-toggle-button]");
      const valueInput = form.querySelector("[data-source-toggle-value]");
      const nextStatus = valueInput?.value || "";
      if (!button || !valueInput || !nextStatus) return;
      const previousHTML = button.innerHTML;
      button.disabled = true;
      try {{
        const data = new URLSearchParams(new FormData(form));
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const isActive = nextStatus === "active";
        button.classList.toggle("is-on", isActive);
        button.innerHTML = `<span></span>${{isActive ? "啟用" : "暫停"}}`;
        const nextValue = isActive ? "paused" : "active";
        const hint = isActive ? "點一下暫停抓取" : "點一下恢復啟用";
        valueInput.value = nextValue;
        button.title = hint;
        button.setAttribute("aria-label", hint);
      }} catch (_error) {{
        button.innerHTML = previousHTML;
      }} finally {{
        button.disabled = false;
      }}
    }});
  }});

  const escapeHTML = (value) => String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const setupPublishCopyButtons = (root = document) => {{
    root.querySelectorAll("[data-copy-publish-url]").forEach((button) => {{
      if (button.dataset.copyPublishBound === "1") return;
      button.dataset.copyPublishBound = "1";
      button.addEventListener("click", async () => {{
        const url = button.dataset.copyPublishUrl || "";
        let ok = false;
        try {{
          if (navigator.clipboard?.writeText) {{
            await navigator.clipboard.writeText(url);
            ok = true;
          }}
        }} catch (_error) {{
          ok = false;
        }}
        button.textContent = ok ? "已複製" : "請手動複製網址";
      }});
    }});
  }};

  document.querySelectorAll("form[data-page-publish-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const button = form.querySelector("[data-page-publish-button]");
      const label = form.querySelector("[data-page-publish-label]");
      const actionInput = form.querySelector("[data-page-publish-action]");
      const message = form.querySelector("[data-page-publish-message]");
      const output = form.closest("[data-publish-card]")?.querySelector("[data-page-publish-output]");
      if (button) button.disabled = true;
      try {{
        const data = new URLSearchParams(new FormData(form));
        data.set("format", "json");
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "發布切換失敗");
        const published = Boolean(payload.published);
        if (button) button.classList.toggle("is-on", published);
        if (label) label.textContent = published ? "已公開" : "未公開";
        if (actionInput) actionInput.value = published ? "unpublish" : "publish";
        if (message) message.textContent = published ? "下次更新線上閱讀版後生效。" : "已取消公開；下次更新線上閱讀版後會清掉頁面。";
        if (output) {{
          if (published) {{
            const url = payload.public_url || "";
            output.innerHTML = '<p class="help">下次更新線上閱讀版後生效：<a href="' + escapeHTML(url) + '" target="_blank" rel="noopener" data-publish-url>' + escapeHTML(url) + '</a></p><button type="button" class="button button-small quiet" data-copy-publish-url="' + escapeHTML(url) + '">複製網址</button>';
            setupPublishCopyButtons(output);
          }} else {{
            output.innerHTML = '<p class="help" data-publish-url>公開已關閉；下次更新線上閱讀版後會清掉對應 HTML。</p>';
          }}
        }}
      }} catch (error) {{
        if (message) message.textContent = String(error);
      }} finally {{
        if (button) button.disabled = false;
      }}
    }});
  }});
  setupPublishCopyButtons(document);

  const setIfEmpty = (element, value) => {{
    if (!element || !value || element.value.trim()) return;
    element.value = value;
  }};

  const setValue = (element, value) => {{
    if (!element || !value) return;
    element.value = value;
  }};

  const splitTagInput = (value) => String(value || "")
    .split(/[\\n,，]/)
    .map((tag) => tag.trim().replace(/\\s+/g, " "))
    .filter(Boolean);

  const tagKeyClient = (value) => String(value || "").trim().toLocaleLowerCase();
  const tagAliasOptions = {json.dumps(taxonomy_alias_options(), ensure_ascii=False).replace("<", "\\u003c")};
  const tagAliasMap = new Map(tagAliasOptions.map((option) => [tagKeyClient(option.alias), option.label]));
  const canonicalTagClient = (value) => {{
    const text = String(value || "").trim().replace(/\\s+/g, " ");
    return tagAliasMap.get(tagKeyClient(text)) || text;
  }};
  const tagIconHTML = `{action_icon("tag")}`;

  const setupTagPicker = (form) => {{
    const current = form.querySelector("[data-tag-current]");
    const input = form.querySelector("[data-tag-input]");
    const menu = form.querySelector("[data-tag-menu]");
    const hidden = form.querySelector("[data-tag-hidden]");
    const suggestionStrip = form.querySelector("[data-tag-suggestions]");
    const optionsScript = form.querySelector("[data-tag-options]");
    const autosave = form.hasAttribute("data-tag-autosave");
    const autosaveStatus = form.querySelector("[data-tag-autosave-status]");
    if (!current || !input || !menu || !hidden) return;

    let selected = Array.from(current.querySelectorAll("[data-tag-value]"))
      .map((button) => button.dataset.tagValue || button.textContent || "")
      .flatMap(splitTagInput);
    let autosaveReady = false;
    let autosaveTimer = 0;
    const allOptions = [];
    const addOption = (tag) => {{
      const label = canonicalTagClient(splitTagInput(tag)[0] || "");
      if (!label) return;
      const key = tagKeyClient(label);
      if (!key || allOptions.some((option) => tagKeyClient(option) === key)) return;
      allOptions.push(label);
    }};

    try {{
      JSON.parse(optionsScript?.textContent || "[]").forEach(addOption);
    }} catch (_error) {{
      // Keep manual tag entry usable even if an old browser extension alters the JSON block.
    }}
    selected.forEach(addOption);

    const selectedKeys = () => new Set(selected.map(tagKeyClient));

    const setAutosaveStatus = (message) => {{
      if (autosaveStatus) autosaveStatus.textContent = message;
    }};

    const syncHidden = () => {{
      hidden.innerHTML = selected
        .map((tag) => `<input type="hidden" name="tags" value="${{escapeHTML(tag)}}">`)
        .join("");
    }};

    const saveAutosavedTags = async () => {{
      if (!autosave) return;
      setAutosaveStatus("正在儲存 tag...");
      const data = new URLSearchParams(new FormData(form));
      try {{
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        setAutosaveStatus("tag 已自動儲存");
      }} catch (error) {{
        setAutosaveStatus("tag 儲存失敗，請稍後再試");
      }}
    }};

    const scheduleAutosave = () => {{
      if (!autosave || !autosaveReady) return;
      window.clearTimeout(autosaveTimer);
      autosaveTimer = window.setTimeout(saveAutosavedTags, 260);
    }};

    const renderSelected = () => {{
      current.innerHTML = selected
        .map((tag) => `<button type="button" class="tag-pill" data-tag-value="${{escapeHTML(tag)}}" data-remove-tag>
          <span class="tag-chip-icon" aria-hidden="true">${{tagIconHTML}}</span><span>${{escapeHTML(tag)}}</span><span class="tag-pill-remove" aria-hidden="true">x</span>
        </button>`)
        .join("");
      syncHidden();
      const keys = selectedKeys();
      suggestionStrip?.querySelectorAll("[data-tag-suggestion]").forEach((button) => {{
        button.hidden = keys.has(tagKeyClient(button.dataset.tagSuggestion || ""));
      }});
      scheduleAutosave();
    }};

    const addTag = (value) => {{
      let changed = false;
      splitTagInput(value).forEach((tag) => {{
        const label = canonicalTagClient(tag);
        const key = tagKeyClient(label);
        if (!key || selected.some((existing) => tagKeyClient(existing) === key)) return;
        selected.push(label);
        addOption(label);
        changed = true;
      }});
      if (changed) renderSelected();
      input.value = "";
      menu.hidden = true;
    }};
    // 暴露給其他 widget（例如觀點頁選材料時，把材料既有標籤預先放進來）
    form.tagPickerAddTag = addTag;

    const removeTag = (value) => {{
      const key = tagKeyClient(value);
      selected = selected.filter((tag) => tagKeyClient(tag) !== key);
      renderSelected();
      renderMenu();
    }};

    const matchingOptions = () => {{
      const query = input.value.trim();
      const queryKey = tagKeyClient(query);
      const keys = selectedKeys();
      const matches = [];
      const seenMatches = new Set();
      const pushMatch = (tag, label = tag, create = false) => {{
        const key = tagKeyClient(tag);
        if (!key || keys.has(key) || seenMatches.has(key)) return;
        matches.push({{tag, label, create}});
        seenMatches.add(key);
      }};
      allOptions
        .filter((tag) => !queryKey || tagKeyClient(tag).includes(queryKey))
        .forEach((tag) => pushMatch(tag));
      if (queryKey) {{
        tagAliasOptions
          .filter((option) => tagKeyClient(option.alias).includes(queryKey) || tagKeyClient(option.label).includes(queryKey))
          .forEach((option) => pushMatch(option.label));
      }}
      const canonicalQuery = canonicalTagClient(query);
      if (queryKey && !keys.has(tagKeyClient(canonicalQuery)) && !allOptions.some((tag) => tagKeyClient(tag) === tagKeyClient(canonicalQuery))) {{
        matches.unshift({{tag: canonicalQuery, label: `新增「${{canonicalQuery}}」`, create: true}});
      }}
      return matches.slice(0, 8);
    }};

    const renderMenu = () => {{
      const matches = matchingOptions();
      if (!matches.length || document.activeElement !== input) {{
        menu.hidden = true;
        return;
      }}
      menu.innerHTML = matches
        .map((option, index) => `<button type="button" class="tag-menu-option${{option.create ? " is-create" : ""}}" data-tag-option="${{escapeHTML(option.tag)}}"${{index === 0 ? " data-primary-tag-option" : ""}}>
          <span>${{escapeHTML(option.label)}}</span>
        </button>`)
        .join("");
      menu.hidden = false;
    }};

    current.addEventListener("click", (event) => {{
      const button = event.target.closest("[data-remove-tag]");
      if (!button) return;
      removeTag(button.dataset.tagValue || "");
    }});

    suggestionStrip?.addEventListener("click", (event) => {{
      const button = event.target.closest("[data-tag-suggestion]");
      if (!button) return;
      addTag(button.dataset.tagSuggestion || "");
      input.focus();
    }});

    menu.addEventListener("mousedown", (event) => event.preventDefault());
    menu.addEventListener("click", (event) => {{
      const button = event.target.closest("[data-tag-option]");
      if (!button) return;
      addTag(button.dataset.tagOption || "");
      input.focus();
    }});

    input.addEventListener("input", renderMenu);
    input.addEventListener("focus", renderMenu);
    input.addEventListener("keydown", (event) => {{
      if (event.key === "Enter") {{
        event.preventDefault();
        const primary = menu.querySelector("[data-primary-tag-option]");
        addTag(primary?.dataset.tagOption || input.value);
      }} else if (event.key === "Tab") {{
        const primary = menu.querySelector("[data-primary-tag-option]");
        if (input.value.trim() || primary) {{
          event.preventDefault();
          addTag(primary?.dataset.tagOption || input.value);
        }}
      }} else if (event.key === "Escape") {{
        menu.hidden = true;
      }} else if (event.key === "Backspace" && !input.value && selected.length) {{
        removeTag(selected[selected.length - 1]);
      }}
    }});

    form.addEventListener("submit", (event) => {{
      if (input.value.trim()) addTag(input.value);
      input.value = "";
      syncHidden();
      if (autosave) {{
        event.preventDefault();
        scheduleAutosave();
      }}
    }});

    document.addEventListener("click", (event) => {{
      if (!form.contains(event.target)) menu.hidden = true;
    }});

    renderSelected();
    autosaveReady = true;
  }};

  document.querySelectorAll("form[data-tag-picker]").forEach(setupTagPicker);

  document.addEventListener("submit", (event) => {{
    const form = event.target.closest("form[data-translate-form]");
    if (!form) return;
    event.preventDefault();
    const id = (form.querySelector("input[name='id']") || {{}}).value || "";
    const redirect = (form.querySelector("input[name='redirect']") || {{}}).value || (window.location.pathname + window.location.search);
    const provider = (form.querySelector("input[name='provider']") || {{}}).value || "codex";
    if (!window.runEngineJob) {{ form.submit(); return; }}
    window.runEngineJob({{
      label: "全文翻譯",
      url: form.getAttribute("action") || "/items/translate-zh",
      baseBody: {{ id: id, redirect: redirect }},
      engine: provider,
      statusUrl: "/api/translate-status?id=" + encodeURIComponent(id),
      onSuccess: (payload) => {{ window.location.href = (payload && payload.redirect) || redirect; }}
    }});
  }});

  document.querySelectorAll("[data-source-group-field]").forEach((field) => {{
    const select = field.querySelector("[data-source-group-select]");
    const input = field.querySelector("[data-source-group-new]");
    const sync = (focus = false) => {{
      const isNew = select?.value === "{NEW_SOURCE_GROUP_VALUE}";
      if (input) {{
        input.hidden = !isNew;
        input.required = isNew;
        if (isNew && focus) input.focus();
      }}
    }};
    select?.addEventListener("change", () => sync(true));
    sync();
  }});

  const sourceGroupStatus = (group, message, isError = false) => {{
    const status = group?.querySelector("[data-source-group-status]");
    if (!status) return;
    status.textContent = message || "";
    status.classList.toggle("is-error", Boolean(isError));
  }};

  const updateSourceGroupCounts = () => {{
    document.querySelectorAll("[data-source-group]").forEach((group) => {{
      const count = group.querySelectorAll("[data-source-row]").length;
      const label = group.querySelector("[data-source-group-count]");
      if (label) label.textContent = `(${{count}})`;
    }});
  }};

  const saveSourceGroupMove = async (row, group, origin) => {{
    if (!row || !group) return;
    const targetTrack = group.dataset.track || "";
    const targetGroup = group.dataset.group || "";
    if (!targetTrack || !targetGroup) return;
    sourceGroupStatus(group, "移動來源中...");
    const data = new URLSearchParams();
    data.set("id", row.dataset.sourceId || "");
    data.set("track", targetTrack);
    data.set("source_group", targetGroup);
    data.set("format", "json");
    data.set("redirect", window.location.pathname + window.location.search);
    try {{
      const response = await fetch("/sources/move-source-group", {{
        method: "POST",
        headers: {{
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Requested-With": "local-web-fetch"
        }},
        body: data
      }});
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "來源分類沒有儲存");
      row.dataset.track = payload.track || targetTrack;
      row.dataset.sourceGroup = payload.source_group || targetGroup;
      updateSourceGroupCounts();
      sourceGroupStatus(group, "已移動來源");
      window.setTimeout(() => sourceGroupStatus(group, ""), 1600);
    }} catch (error) {{
      if (origin?.parent) {{
        origin.parent.insertBefore(row, origin.nextSibling || null);
        updateSourceGroupCounts();
      }}
      sourceGroupStatus(group, String(error), true);
    }}
  }};

  let draggedSourceRow = null;
  let sourceDragOrigin = null;
  document.querySelectorAll("[data-source-drag]").forEach((handle) => {{
    handle.addEventListener("click", (event) => {{
      event.preventDefault();
      event.stopPropagation();
    }});
    handle.addEventListener("dragstart", (event) => {{
      draggedSourceRow = handle.closest("[data-source-row]");
      if (!draggedSourceRow) return;
      sourceDragOrigin = {{
        parent: draggedSourceRow.parentElement,
        nextSibling: draggedSourceRow.nextElementSibling,
      }};
      draggedSourceRow.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", draggedSourceRow.dataset.sourceId || "");
    }});
    handle.addEventListener("dragend", () => {{
      if (draggedSourceRow) draggedSourceRow.classList.remove("is-dragging");
      document.querySelectorAll("[data-source-group].is-drop-target").forEach((group) => group.classList.remove("is-drop-target"));
      draggedSourceRow = null;
      sourceDragOrigin = null;
    }});
  }});

  document.querySelectorAll("[data-source-group]").forEach((group) => {{
    group.addEventListener("dragover", (event) => {{
      if (!draggedSourceRow) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      group.classList.add("is-drop-target");
    }});
    group.addEventListener("dragleave", (event) => {{
      const nextTarget = event.relatedTarget instanceof Node ? event.relatedTarget : null;
      if (!nextTarget || !group.contains(nextTarget)) group.classList.remove("is-drop-target");
    }});
    group.addEventListener("drop", (event) => {{
      if (!draggedSourceRow) return;
      event.preventDefault();
      group.classList.remove("is-drop-target");
      const targetTrack = group.dataset.track || "";
      const targetGroup = group.dataset.group || "";
      const alreadyThere = draggedSourceRow.dataset.track === targetTrack && draggedSourceRow.dataset.sourceGroup === targetGroup;
      if (alreadyThere) return;
      const tbody = group.querySelector("tbody");
      if (!tbody) return;
      tbody.appendChild(draggedSourceRow);
      updateSourceGroupCounts();
      saveSourceGroupMove(draggedSourceRow, group, sourceDragOrigin);
    }});
  }});

  document.querySelectorAll("[data-source-group-edit]").forEach((button) => {{
    button.addEventListener("click", (event) => {{
      event.preventDefault();
      event.stopPropagation();
      const group = button.closest("[data-source-group]");
      const form = group?.querySelector("[data-source-group-rename]");
      const input = form?.querySelector("input[name='new_group']");
      if (!form || !input) return;
      button.hidden = true;
      form.hidden = false;
      input.value = group.dataset.group || button.textContent.trim();
      input.focus();
      input.select();
    }});
  }});

  document.querySelectorAll("[data-source-group-cancel]").forEach((button) => {{
    button.addEventListener("click", (event) => {{
      event.preventDefault();
      event.stopPropagation();
      const form = button.closest("[data-source-group-rename]");
      const group = button.closest("[data-source-group]");
      const editButton = group?.querySelector("[data-source-group-edit]");
      if (form) form.hidden = true;
      if (editButton) editButton.hidden = false;
      sourceGroupStatus(group, "");
    }});
  }});

  document.querySelectorAll("[data-source-group-rename]").forEach((form) => {{
    form.addEventListener("click", (event) => event.stopPropagation());
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      event.stopPropagation();
      const group = form.closest("[data-source-group]");
      const editButton = group?.querySelector("[data-source-group-edit]");
      const input = form.querySelector("input[name='new_group']");
      const oldInput = form.querySelector("input[name='old_group']");
      const nextName = input?.value?.trim();
      if (!group || !editButton || !input || !oldInput || !nextName) return;
      sourceGroupStatus(group, "儲存名稱中...");
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      try {{
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "分類名稱沒有儲存");
        group.dataset.group = payload.new_group || nextName;
        oldInput.value = group.dataset.group;
        input.value = group.dataset.group;
        editButton.textContent = group.dataset.group;
        form.hidden = true;
        editButton.hidden = false;
        sourceGroupStatus(group, "已儲存名稱");
        window.setTimeout(() => sourceGroupStatus(group, ""), 1600);
      }} catch (error) {{
        sourceGroupStatus(group, String(error), true);
      }}
    }});
  }});

  const previewInputValue = (form) => {{
    const kind = form.getAttribute("data-preview-kind") || "item";
    if (kind === "source") {{
      const feed = form.querySelector("[data-preview-feed-url]")?.value?.trim();
      const site = form.querySelector("[data-preview-site-url]")?.value?.trim();
      return feed || site || "";
    }}
    return form.querySelector("[data-preview-url]")?.value?.trim() || "";
  }};

  const feedSuggestionHTML = (feeds) => {{
    if (!feeds?.length) return "<p class='help'>沒有在這頁偵測到 RSS / Atom feed。</p>";
    return `<div class="feed-suggestions">${{feeds.map((feed) => {{
      const status = feed.exists ? "<span class='badge badge--neutral'>已追蹤</span>" : "<span class='badge badge--rss'>可新增 RSS</span>";
      const action = feed.exists
        ? ""
        : `<a class="button secondary" href="${{escapeHTML(feed.add_url)}}">新增這個 RSS</a>`;
      return `<div class="feed-suggestion">
        <strong>${{escapeHTML(feed.title || feed.url)}}</strong> ${{status}}
        <p class="help break-anywhere">${{escapeHTML(feed.type || "RSS / Atom")}} · ${{escapeHTML(feed.url)}}</p>
        ${{action}}
      </div>`;
    }}).join("")}}</div>`;
  }};

  const renderPreview = (form, payload) => {{
    const kind = form.getAttribute("data-preview-kind") || "item";
    const result = form.querySelector("[data-preview-result]");
    const status = form.querySelector("[data-preview-status]");
    const title = payload.feed_title || payload.title || payload.source_name || payload.final_url || payload.url;
    const description = payload.description || payload.excerpt || "";
    const suggestedSummary = payload.suggested_summary || description;
    const suggestedNotes = payload.suggested_notes || "";
    if (status) {{
      const parts = [];
      if (payload.is_feed) parts.push(`${{payload.feed_type || "RSS"}}，${{payload.entry_count || 0}} 則`);
      if (payload.final_url && payload.final_url !== payload.url) parts.push("已帶入跳轉後網址");
      if (kind === "item" && payload.suggested_track_label) parts.push(`主線：${{payload.suggested_track_label}}`);
      if (kind === "item" && payload.published_at) parts.push(`日期：${{payload.published_at}}`);
      if (kind === "item" && suggestedSummary) parts.push("摘要已建議");
      if (kind === "item" && suggestedNotes) parts.push("備註已建議");
      if (kind === "item" && payload.suggested_tags?.length) parts.push(`標籤：${{payload.suggested_tags.length}} 個`);
      status.textContent = parts.length ? `抓到了：${{parts.join("；")}}。` : "已抓到頁面資訊。";
    }}
    if (result) {{
      const dateSource = payload.published_at
        ? `<p class="help">發布日期：${{escapeHTML(payload.published_at)}}${{payload.published_at_source ? `（${{escapeHTML(payload.published_at_source)}}）` : ""}}</p>`
        : "";
      const tagHTML = (payload.suggested_tags || [])
        .map((tag) => `<span class="badge badge--neutral">${{escapeHTML(tag)}}</span>`)
        .join("");
      const itemHints = kind === "item"
        ? `<div>
            <strong>準備帶入</strong>
            ${{dateSource}}
            ${{suggestedSummary ? `<p>${{escapeHTML(suggestedSummary)}}</p>` : ""}}
            ${{tagHTML ? `<p>${{tagHTML}}</p>` : ""}}
            ${{suggestedNotes ? `<p class="help">${{escapeHTML(suggestedNotes)}}</p>` : ""}}
          </div>`
        : "";
      result.innerHTML = `
        <div>
          <h3>${{escapeHTML(title)}}</h3>
          <p class="help break-anywhere">${{escapeHTML(payload.final_url || payload.url || "")}}</p>
          ${{description ? `<p>${{escapeHTML(description)}}</p>` : ""}}
        </div>
        ${{itemHints}}
        <div>
          <strong>RSS 建議</strong>
          ${{feedSuggestionHTML(payload.feed_suggestions || [])}}
        </div>
      `;
    }}

    if (kind === "item") {{
      const urlInput = form.querySelector("[data-preview-url]");
      if (urlInput && payload.unwrapped_url) urlInput.value = payload.unwrapped_url;
      const trackSelect = form.querySelector("[data-preview-track]");
      if (
        trackSelect &&
        form.dataset.previewTrackAutofill === "1" &&
        payload.suggested_track &&
        Array.from(trackSelect.options).some((option) => option.value === payload.suggested_track)
      ) {{
        trackSelect.value = payload.suggested_track;
      }}
      setIfEmpty(form.querySelector("[data-preview-title]"), payload.title || payload.feed_title);
      setIfEmpty(form.querySelector("[data-preview-source-name]"), payload.source_name);
      setIfEmpty(form.querySelector("[data-preview-summary]"), suggestedSummary);
      setIfEmpty(form.querySelector("[data-preview-notes]"), suggestedNotes);
      setIfEmpty(form.querySelector("[data-preview-published-at]"), payload.published_at);
      setValue(form.querySelector("[data-preview-author]"), payload.author);
      setValue(form.querySelector("[data-preview-image-url]"), payload.image_url);
      setValue(form.querySelector("[data-preview-canonical-url]"), payload.canonical_url);
      setValue(form.querySelector("[data-preview-final-url]"), payload.final_url);
      setValue(form.querySelector("[data-preview-site-name]"), payload.site_name);
      if (form.tagPickerAddTag && Array.isArray(payload.suggested_tags)) {{
        payload.suggested_tags.forEach((tag) => form.tagPickerAddTag(tag));
      }}
    }} else {{
      const feedInput = form.querySelector("[data-preview-feed-url]");
      const siteInput = form.querySelector("[data-preview-site-url]");
      const nameInput = form.querySelector("[data-preview-title]");
      const typeInput = form.querySelector("[data-preview-source-type]");
      const firstFeed = (payload.feed_suggestions || [])[0];
      setIfEmpty(nameInput, payload.feed_title || payload.title || payload.source_name);
      setIfEmpty(siteInput, payload.site_url || (!payload.is_feed ? payload.final_url : ""));
      if (payload.is_feed) {{
        setIfEmpty(feedInput, payload.final_url || payload.url);
      }} else if (firstFeed && (!feedInput?.value?.trim() || feedInput.value.trim() === payload.url)) {{
        feedInput.value = firstFeed.url;
      }}
      if (typeInput && !typeInput.value) typeInput.value = "rss";
    }}
  }};

  const runUrlPreview = async (form, force = false) => {{
    const url = previewInputValue(form);
    const panel = form.querySelector("[data-preview-panel]");
    const status = form.querySelector("[data-preview-status]");
    const button = form.querySelector("[data-preview-button]");
    if (!url || !url.startsWith("http")) return;
    if (!force && form.dataset.previewLast === url) return;
    form.dataset.previewLast = url;
    if (panel) panel.hidden = false;
    if (status) status.textContent = "正在抓取頁面與 RSS 資訊...";
    if (button) button.disabled = true;
    const data = new URLSearchParams();
    data.set("url", url);
    data.set("track", form.querySelector("[data-preview-track]")?.value || "digital-humanities-local-knowledge");
    data.set("title", form.querySelector("[data-preview-title]")?.value || "");
    try {{
      const response = await fetch("/preview-url", {{
        method: "POST",
        headers: {{
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Requested-With": "local-web-fetch"
        }},
        body: data
      }});
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || "preview failed");
      renderPreview(form, payload);
    }} catch (error) {{
      if (status) status.textContent = `這次沒有抓到頁面資訊：${{String(error)}}`;
    }} finally {{
      if (button) button.disabled = false;
    }}
  }};

  document.querySelectorAll("form[data-url-preview-form]").forEach((form) => {{
    let timer = 0;
    const schedule = () => {{
      window.clearTimeout(timer);
      timer = window.setTimeout(() => runUrlPreview(form), 850);
    }};
    form.querySelector("[data-preview-button]")?.addEventListener("click", () => runUrlPreview(form, true));
    form.querySelectorAll("[data-preview-url], [data-preview-site-url]").forEach((input) => {{
      input.addEventListener("change", () => runUrlPreview(form, true));
      input.addEventListener("blur", () => runUrlPreview(form, true));
      input.addEventListener("input", schedule);
    }});
    if (previewInputValue(form)) window.setTimeout(() => runUrlPreview(form), 250);
  }});

  document.querySelectorAll("form[data-read-more-form]").forEach((form) => {{
    form.addEventListener("submit", (event) => {{
      if (!window.fetch || !window.runFetchJob) return;
      event.preventDefault();
      const data = new URLSearchParams(new FormData(form));
      const targetSelector = form.getAttribute("data-target") || "#fulltext-panel";
      const redirect = (form.querySelector("input[name='redirect']") || {{}}).value || (window.location.pathname + window.location.search);
      window.runFetchJob({{
        label: "展開全文",
        url: form.getAttribute("action") || form.action,
        baseBody: data,
        onSuccess: (payload) => {{
          const panel = document.querySelector(targetSelector);
          if (panel) {{
            panel.hidden = false;
            if (panel instanceof HTMLDetailsElement) panel.open = true;
            const body = panel.querySelector("[data-fulltext-body]");
            const meta = panel.querySelector("[data-fulltext-meta]");
            if (body) {{
              if (payload.article_html) {{ body.innerHTML = payload.article_html; }}
              else {{ body.textContent = payload.article_text || "這次沒有抓到可顯示的主文。"; }}
            }}
            if (meta) meta.textContent = payload.message || "";
            const translationActions = panel.querySelector("[data-translation-actions]");
            if (translationActions) {{
              if (payload.translation_actions_html) {{
                translationActions.innerHTML = payload.translation_actions_html;
                translationActions.hidden = false;
              }} else {{
                translationActions.innerHTML = "";
                translationActions.hidden = true;
              }}
            }}
            panel.scrollIntoView({{ behavior: "smooth", block: "start" }});
          }} else if (payload.redirect) {{
            window.location.href = payload.redirect;
          }}
        }},
        onError: () => {{
          const separator = redirect.includes("?") ? "&" : "?";
          window.location.href = redirect + separator + "error=read_more";
        }}
      }});
    }});
  }});

  document.querySelectorAll("form[data-codex-review-form]").forEach((form) => {{
    form.addEventListener("submit", (event) => {{
      if (!window.fetch || !window.runEngineJob) return;
      event.preventDefault();
      const id = (form.querySelector("input[name='id']") || {{}}).value || "";
      const redirect = (form.querySelector("input[name='redirect']") || {{}}).value || (window.location.pathname + window.location.search);
      const provider = (form.querySelector("input[name='provider']") || {{}}).value || "codex";
      const formBody = new URLSearchParams(new FormData(form));
      formBody.set("id", id);
      formBody.set("redirect", redirect);
      if (!formBody.get("with_fulltext")) formBody.set("with_fulltext", "1");
      window.runEngineJob({{
        label: "生成閱讀建議",
        url: form.getAttribute("action") || "/items/codex-review",
        baseBody: formBody,
        engine: provider,
        onSuccess: (payload) => {{ window.location.href = (payload && payload.redirect) || redirect; }}
      }});
    }});
  }});
  </script>
</body>
</html>"""
    return html_doc.encode("utf-8")


# --------------------------------------------------------------------------- #
# 編輯台（Editor Console）helper
# --------------------------------------------------------------------------- #
EDITOR_TASK_HINTS = {
    "theme-check": "先檢查所選材料適合主題式還是彙報式，並參考你的觀點筆記給貼法建議。",
    "compose-thematic": "把幾篇相關材料收斂成一篇帶觀點的 article 草稿（三段分明）。",
    "compose-digest": "把多主題、不一定相關的材料整理成彙報式 article 草稿。",
    "factcheck": "實際上網把原文／正式文件／系列下篇找出來並附真實連結，不把輸入材料當推薦。",
    "extract-viewpoints": "從所選材料抽出 2-5 條可存進觀點庫的觀點。",
    "newsletter-extract": "針對彙整式電子報或 roundup 產出外部萃取報告，分清文章/報告 link 與功能性連結。",
}
# 撰稿生產線（決定下一步建議）：選法檢查→查核找原文→萃取觀點→撰稿。
# compose-* 是末端二選一（彼此不建議）；newsletter-extract 外於生產線、不建議下一步。
EDITOR_PIPELINE_TASKS = ["theme-check", "factcheck", "extract-viewpoints", "compose-digest", "compose-thematic"]
EDITOR_PIPELINE_NEXT = {
    "theme-check": "factcheck",
    "factcheck": "extract-viewpoints",
    "extract-viewpoints": "compose-thematic",  # 萃取完→撰稿（彙報式／主題式二選一，預設主題式）
}


def next_pipeline_task(task_type: str) -> str:
    """沿生產線推下一步任務 key；末端（compose-*）與電子報（newsletter-extract）回空字串。"""
    return EDITOR_PIPELINE_NEXT.get(clean_text(task_type), "")


def editor_task_options_html(selected_key: str = "") -> str:
    """任務下拉：彙整萃取報告獨立成「電子報專用」群組放最前，其餘為「撰稿生產線」群組。"""
    selected_key = clean_text(selected_key)

    def opt(key: str) -> str:
        sel = " selected" if key == selected_key else ""
        return f'<option value="{h(key)}"{sel}>{h(EDITOR_TASK_LABELS.get(key, key))}</option>'

    pipeline = "".join(opt(key) for key in EDITOR_PIPELINE_TASKS)
    return (
        f'<optgroup label="電子報專用（外於生產線）">{opt("newsletter-extract")}</optgroup>'
        f'<optgroup label="撰稿生產線">{pipeline}</optgroup>'
    )


WRITING_STYLES_DIR = ROOT / "knowledge" / "writing-styles"


def load_writing_styles() -> list[dict]:
    """掃 knowledge/writing-styles/*.md，回傳 [{name,title,description}]；default 置頂、其餘依檔名。"""
    out: list[dict] = []
    if WRITING_STYLES_DIR.exists():
        for path in sorted(WRITING_STYLES_DIR.glob("*.md")):
            name = path.stem
            title, description = name, ""
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) == 3:
                    for line in parts[1].splitlines():
                        key, sep, value = line.partition(":")
                        if not sep:
                            continue
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key == "name" and value:
                            title = value
                        elif key == "description" and value:
                            description = value
            out.append({"name": name, "title": title, "description": description})
    out.sort(key=lambda s: (s["name"] != "default", s["name"]))
    return out


def writing_style_names() -> set[str]:
    return {s["name"] for s in load_writing_styles()}


def writing_style_options_html(selected: str = "") -> str:
    selected = clean_text(selected)
    opts = ['<option value="">（不套用特定風格）</option>']
    for style in load_writing_styles():
        sel = " selected" if style["name"] == selected else ""
        opts.append(f'<option value="{h(style["name"])}"{sel}>{h(style["title"])}</option>')
    return "".join(opts)


def editor_cli_path(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in (
        str(Path.home() / ".local" / "bin" / name),
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def ollama_model(engine: str = "ollama") -> str:
    default = OLLAMA_MODELS.get(engine, DEFAULT_OLLAMA_MODEL)
    model = (os.environ.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_CLI_MODEL") or default).strip()
    return model or DEFAULT_OLLAMA_MODEL


def editor_engine_status() -> dict[str, bool]:
    return {
        "claude": bool(editor_cli_path("claude")),
        "codex": bool(editor_cli_path("codex")),
        "gemini": bool(editor_cli_path("agy")),
        "ollama": bool(editor_cli_path("ollama")),
        "ollama-gemma4": bool(editor_cli_path("ollama")),
        "ollama-twinkle": bool(editor_cli_path("ollama")),
    }


def new_editor_id(prefix: str) -> str:
    seed = f"{time.time()}-{prefix}".encode("utf-8")
    return f"{prefix}-{hashlib.sha1(seed).hexdigest()[:12]}"


def load_articles() -> list[dict]:
    """讀取專文正本 database/articles.jsonl。"""
    return load_jsonl(ARTICLES)


def article_lookup() -> dict[str, dict]:
    """id → 專文記錄，方便單篇查找。"""
    return {clean_text(record.get("id")): record for record in load_articles() if clean_text(record.get("id"))}


def articles_citing_item(item_id: str, articles: list[dict] | None = None) -> list[dict]:
    """回傳引用了某材料 item 的所有專文（供材料頁雙向連結）。"""
    target = clean_text(item_id)
    if not target:
        return []
    pool = articles if articles is not None else load_articles()
    return [a for a in pool if target in {clean_text(i) for i in (a.get("item_ids") or [])}]


def articles_with_viewpoint(viewpoint_id: str, articles: list[dict] | None = None) -> list[dict]:
    """回傳關聯了某觀點的所有專文（供觀點頁雙向連結）。"""
    target = clean_text(viewpoint_id)
    if not target:
        return []
    pool = articles if articles is not None else load_articles()
    return [a for a in pool if target in {clean_text(v) for v in (a.get("viewpoint_ids") or [])}]


def normalize_article_record(record: dict) -> dict:
    """把一筆專文補齊欄位、正規化型別，存檔前統一走這裡（P2/P3 共用）。"""
    article_id = clean_text(record.get("id")) or new_editor_id("art")
    status = clean_text(record.get("status")) or "draft"
    if status not in ARTICLE_STATUSES:
        status = "draft"
    created_at = clean_text(record.get("created_at")) or now_iso()
    return {
        "id": article_id,
        "title": clean_text(record.get("title")) or "（未命名專文）",
        "slug": clean_text(record.get("slug")),
        "track": clean_text(record.get("track")) or "unclassified",
        "status": status,
        "body_markdown": record.get("body_markdown") or "",
        "tags": [t for t in (record.get("tags") or []) if clean_text(t)],
        "item_ids": [clean_text(i) for i in (record.get("item_ids") or []) if clean_text(i)],
        "viewpoint_ids": [clean_text(v) for v in (record.get("viewpoint_ids") or []) if clean_text(v)],
        "source_session_id": clean_text(record.get("source_session_id")),
        "license": sanitize_license_record(record.get("license")),
        "factcheck": record.get("factcheck") if isinstance(record.get("factcheck"), dict) else {},
        "created_at": created_at,
        "updated_at": now_iso(),
    }


def editor_item_lookup() -> dict[str, dict]:
    pool: dict[str, dict] = {}
    for record in load_jsonl(ITEMS):
        pool[clean_text(record.get("id"))] = record
    for record in load_jsonl(CANDIDATES):
        pool.setdefault(clean_text(record.get("id")), record)
    return pool


def editor_item_title(record: dict) -> str:
    return clean_text(item_display_title(record), 200) or clean_text(record.get("id"), 200)


def editor_item_has_translation(record: dict) -> bool:
    return bool(item_translated_markdown(record))


def editor_available_materials() -> list[dict]:
    records = [record for record in load_jsonl(ITEMS) if is_skill_candidate(record)]
    records.sort(
        key=lambda record: ((record.get("local_decision") or {}).get("decided_at", ""), record.get("captured_at", "")),
        reverse=True,
    )
    return records


def editor_search_items() -> list[dict]:
    records = [record for record in load_jsonl(ITEMS) if is_skill_candidate(record) or is_direct_pr_item(record)]
    records.sort(
        key=lambda record: ((record.get("local_decision") or {}).get("decided_at", ""), item_sort_time(record)),
        reverse=True,
    )
    return records


def editor_item_pool_type(record: dict) -> tuple[str, str]:
    if is_direct_pr_item(record):
        return "small-news", "新聞小消息"
    return "material", "可用材料"


def editor_material_payload(record: dict) -> dict:
    type_key, type_label = editor_item_pool_type(record)
    return {
        "id": clean_text(record.get("id")),
        "title": editor_item_title(record),
        "summary": item_zh_summary(record, 260),
        "source": clean_text(record.get("source_name"), 80),
        "track": clean_text(record.get("track")),
        "trackLabel": track_meta(record.get("track", "unclassified"))["short"],
        "type": type_key,
        "typeLabel": type_label,
        "tags": item_visible_tags(record, 6),
        "url": clean_text(record.get("url")),
        "hasTranslation": editor_item_has_translation(record),
        "decidedAt": clean_text((record.get("local_decision") or {}).get("decided_at")),
    }


def editor_material_chip(record: dict) -> str:
    payload = editor_material_payload(record)
    badges = f'<span class="tag-pill editor-kind-pill editor-kind--{h(payload["type"])}">{h(payload["typeLabel"])}</span>'
    badges += f'<span class="tag-pill">{h(payload["trackLabel"])}</span>'
    if payload["hasTranslation"]:
        badges += '<span class="tag-pill">有翻譯全文</span>'
    return (
        f'<span>{h(payload["title"])}</span>'
        f'<code>{h(payload["id"])}</code>'
        f"{badges}"
    )


def article_title_from_markdown(markdown: str) -> str:
    """從 markdown 抓標題：優先第一個 # 標題，否則第一行非空文字。"""
    for line in (markdown or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("#"):
            return clean_text(text.lstrip("#").strip(), 160)
        return clean_text(text, 160)
    return ""


def viewpoint_payload(viewpoint: dict) -> dict:
    return {
        "id": clean_text(viewpoint.get("id")),
        "title": clean_text(viewpoint.get("title"), 120) or "（未命名觀點）",
        "body": clean_text(viewpoint.get("body"), 200),
        "tags": [clean_text(t) for t in (viewpoint.get("tags") or [])[:4] if clean_text(t)],
    }


def viewpoints_for_items(item_ids: list[str], viewpoints: list[dict] | None = None) -> list[str]:
    """找出 related_item_ids 與本組材料有交集的觀點 id（建專文時自動帶上）。"""
    targets = {clean_text(i) for i in item_ids if clean_text(i)}
    if not targets:
        return []
    pool = viewpoints if viewpoints is not None else load_jsonl(VIEWPOINTS)
    matched: list[str] = []
    for vp in pool:
        vp_id = clean_text(vp.get("id"))
        related = {clean_text(i) for i in (vp.get("related_item_ids") or [])}
        if vp_id and related & targets:
            matched.append(vp_id)
    return matched


def latest_factcheck_for_items(item_ids: list[str], sessions: list[dict] | None = None) -> dict | None:
    """挑出涵蓋這組材料、最近一次的查核 session（重疊最多者優先，再比時間）。"""
    targets = {clean_text(i) for i in item_ids if clean_text(i)}
    if not targets:
        return None
    pool = sessions if sessions is not None else load_jsonl(EDITOR_SESSIONS)
    best: dict | None = None
    best_key: tuple[int, str] = (0, "")
    for session in pool:
        if clean_text(session.get("task_type")) != "factcheck":
            continue
        session_items = {clean_text(i) for i in (session.get("item_ids") or [])}
        overlap = len(session_items & targets)
        if not overlap:
            continue
        key = (overlap, clean_text(session.get("created_at")))
        if key > best_key:
            best_key = key
            best = session
    return best


def factcheck_snapshot_from_session(session: dict | None) -> dict:
    """把查核 session 的 claims/結論收成專文用的快照。"""
    if not session:
        return {}
    data = session.get("output_data") if isinstance(session.get("output_data"), dict) else {}
    claims = data.get("claims") if isinstance(data.get("claims"), list) else []
    return {
        "source_session_id": clean_text(session.get("id")),
        "captured_at": now_iso(),
        "session_created_at": clean_text(session.get("created_at")),
        "claims": claims,
        "overall_note": clean_text(data.get("overall_note")),
    }


def build_article_from_session(session: dict, articles: list[dict] | None = None) -> dict:
    """從一次編輯台 session 產生一筆專文草稿（帶入正文、材料、觀點、查核快照）。"""
    item_ids = [clean_text(i) for i in (session.get("item_ids") or []) if clean_text(i)]
    body = clean_text(session.get("output_markdown")) or ""
    title = article_title_from_markdown(body) or clean_text(session.get("task_label")) or "（未命名專文）"
    lookup = editor_item_lookup()
    track = "unclassified"
    for item_id in item_ids:
        rec = lookup.get(item_id)
        if rec and clean_text(rec.get("track")):
            track = clean_text(rec.get("track"))
            break
    factcheck = factcheck_snapshot_from_session(latest_factcheck_for_items(item_ids))
    return normalize_article_record(
        {
            "title": title,
            "track": track,
            "status": "draft",
            "body_markdown": session.get("output_markdown") or "",
            "item_ids": item_ids,
            "viewpoint_ids": viewpoints_for_items(item_ids),
            "source_session_id": clean_text(session.get("id")),
            "factcheck": factcheck,
        }
    )


def factcheck_status_label(status: str) -> tuple[str, str]:
    """查核 claim 狀態 → (中文標籤, badge class)。ok=紫、需做事=黑、負面=紅。
    回傳的 class 走 badge--xxx 慣例，對應 .article-claim .badge--fc-* 的語意顏色。"""
    mapping = {
        "supported": ("有來源支持", "badge--fc-ok"),
        "unclear": ("尚不明確", "badge--fc-mid"),
        "needs-source": ("需要出處", "badge--fc-bad"),
    }
    return mapping.get(clean_text(status), (clean_text(status) or "未標記", "badge--fc-mid"))


# ------------------------------------------------------------------ #
# 全站搜尋：標籤 / 材料 / 觀點 / 編輯歷程 / RSS / 專文
# ------------------------------------------------------------------ #
# icon 用全站既有的 SVG action 名（icon_span），不要用 emoji，風格才一致
SEARCH_TYPE_META = {
    "article": {"icon": "text-lines", "label": "專文"},
    "item": {"icon": "file", "label": "材料 / 消息"},
    "viewpoint": {"icon": "note", "label": "觀點"},
    "tag": {"icon": "tag", "label": "標籤"},
    "session": {"icon": "edit", "label": "編輯歷程"},
    "source": {"icon": "rss", "label": "RSS 來源"},
}
SEARCH_TYPE_ORDER = ["article", "item", "viewpoint", "tag", "session", "source"]
SEARCH_TIME_FILTERS = [
    ("all", "全部時間"),
    ("three-days", "這三天"),
    ("week", "這一週"),
    ("month", "這一個月"),
    ("quarter", "這一季"),
    ("year", "這一年"),
    ("custom", "自定範圍"),
]


def _search_dt_within(value: object, start: datetime | None, end: datetime | None) -> bool:
    """有日期的搜尋結果是否落在時間範圍內；沒設範圍一律通過、有範圍但無法解析則排除。"""
    if not start and not end:
        return True
    raw = clean_text(value)
    if not raw:
        return False
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (not start or parsed >= start) and (not end or parsed < end)


def collect_search_results(
    query: str, per_type: int | None = None, start: datetime | None = None, end: datetime | None = None
) -> dict[str, list[dict]]:
    """全站搜尋。回傳 {type: [ {title, subtitle, href, icon(SVG), badges:[(label,cls)]} ]}。
    預設排除已退件 items；有時間範圍時，有日期的類型（專文/材料/觀點/編輯歷程）才套用篩選，
    標籤與 RSS 來源不受時間影響。"""
    qn = clean_text(query).lower()
    out: dict[str, list[dict]] = {t: [] for t in SEARCH_TYPE_ORDER}
    if not qn:
        return out

    def add(type_key: str, title: str, href: str, subtitle: str = "", badges: list[tuple[str, str]] | None = None) -> None:
        out[type_key].append(
            {
                "type": type_key,
                "icon": icon_span(SEARCH_TYPE_META[type_key]["icon"]),
                "title": title or "(未命名)",
                "subtitle": subtitle,
                "href": href,
                "badges": badges or [],
            }
        )

    for art in load_articles():
        art_id = clean_text(art.get("id"))
        title = clean_text(art.get("title"))
        hay = " ".join([title, art.get("body_markdown") or "", " ".join(art.get("tags") or [])]).lower()
        if art_id and qn in hay and _search_dt_within(art.get("updated_at"), start, end):
            track = clean_text(art.get("track")) or "unclassified"
            add(
                "article",
                title,
                f"/articles/view?id={quote(art_id)}",
                "",
                [(ARTICLE_STATUS_LABELS.get(clean_text(art.get("status")), ""), "neutral"), (track_meta(track)["short"], track_class(track))],
            )

    items = load_jsonl(ITEMS)
    for it in items:
        item_id = clean_text(it.get("id"))
        title = item_display_title(it)
        hay = " ".join(
            [title, item_zh_summary(it, 200), clean_text(it.get("source_name")), clean_text(it.get("author")), " ".join(it.get("tags") or [])]
        ).lower()
        if item_id and qn in hay and item_matches_time_filter(it, start, end):
            track = clean_text(it.get("track")) or "unclassified"
            add("item", title, f"/items/view?id={quote(item_id)}", clean_text(it.get("source_name"), 60), [(track_meta(track)["short"], track_class(track))])

    for vp in load_jsonl(VIEWPOINTS):
        vp_id = clean_text(vp.get("id"))
        title = clean_text(vp.get("title")) or "（未命名觀點）"
        hay = " ".join([title, clean_text(vp.get("body")), " ".join(vp.get("tags") or [])]).lower()
        if vp_id and qn in hay and _search_dt_within(vp.get("updated_at") or vp.get("created_at"), start, end):
            add("viewpoint", title, f"/editor/viewpoints?focus={quote(vp_id)}", clean_text(vp.get("body"), 80))

    tag_counts: dict[str, int] = {}
    for it in items:
        for tag in it.get("tags") or []:
            tk = clean_text(tag)
            if tk:
                tag_counts[tk] = tag_counts.get(tk, 0) + 1
    for tag, count in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
        if qn in tag.lower():
            add("tag", tag, f"/tags?tag={quote(tag)}", f"{count} 篇材料")

    for s in load_jsonl(EDITOR_SESSIONS):
        sid = clean_text(s.get("id"))
        title = clean_text(s.get("task_label")) or clean_text(s.get("task_type"))
        titles = "、".join(clean_text(t) for t in (s.get("item_titles") or [])[:3])
        hay = " ".join([title, clean_text(s.get("task_type")), titles]).lower()
        if sid and qn in hay and _search_dt_within(s.get("created_at"), start, end):
            add("session", title, f"/editor/session?id={quote(sid)}", clean_text(titles, 80), [(clean_text(s.get("engine")), "neutral")])

    for src in load_jsonl(SOURCES):
        src_id = clean_text(src.get("id"))
        name = clean_text(src.get("name"))
        hay = " ".join([name, clean_text(src.get("site_url")), clean_text(src.get("feed_url")), clean_text(src.get("source_group"))]).lower()
        if src_id and qn in hay:
            track = clean_text(src.get("track")) or "unclassified"
            add("source", name, f"/sources/view?id={quote(src_id)}", clean_text(src.get("source_group"), 60), [(track_meta(track)["short"], track_class(track))])

    # 標題命中優先排序
    for type_key, rows in out.items():
        rows.sort(key=lambda r: 0 if qn in r["title"].lower() else 1)
        if per_type is not None:
            out[type_key] = rows[:per_type]
    return out


def search_result_card(res: dict) -> str:
    badges = "".join(badge(label, cls) for label, cls in (res.get("badges") or []) if clean_text(label))
    subtitle = f'<span class="search-card-sub">{h(res["subtitle"])}</span>' if res.get("subtitle") else ""
    return (
        f'<a class="search-card" href="{h(res["href"])}">'
        f'<span class="search-card-icon">{res["icon"]}</span>'
        f'<span class="search-card-main"><span class="search-card-title">{h(res["title"])}</span>{subtitle}'
        f'<span class="search-card-badges">{badges}</span></span></a>'
    )


OMNIBAR_CSS = """
<style>
  .omnibar { position:relative; margin-left:auto; flex:0 1 340px; min-width:200px; }
  .omnibar-search-icon { position:absolute; left:13px; top:50%; z-index:1; display:grid; place-items:center; width:16px; height:16px; color:#a7afbc; background:transparent; pointer-events:none; transform:translateY(-50%); }
  .omnibar-search-icon svg { width:16px; height:16px; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
  .omnibar input { width:100%; box-sizing:border-box; padding:8px 34px 8px 37px; border-radius:999px; border:1px solid var(--border,#cbd5e1); background:#fff; color:var(--ocf-dark); font:inherit; }
  .omnibar input::placeholder { color:#a7afbc; font-size:12px; font-weight:500; opacity:1; transition:opacity .12s ease; }
  .omnibar input:focus::placeholder { opacity:0; }
  .omnibar input:focus { border-color:var(--ocf-primary,#6450dc); outline:none; box-shadow:0 0 0 3px rgba(100,80,220,0.15); }
  .omnibar-suggest { position:absolute; top:calc(100% + 6px); right:0; left:0; background:#fff; color:var(--ocf-dark); border:1px solid var(--line,#e2e8f0); border-radius:12px; box-shadow:0 12px 30px rgba(15,25,35,0.18); max-height:70vh; overflow:auto; z-index:60; padding:6px; }
  .omnibar-group-label { display:flex; align-items:center; gap:5px; font-size:12px; color:var(--muted,#64748b); padding:6px 10px 2px; }
  .omnibar-group-label .icon { width:16px; height:16px; background:transparent; }
  .omnibar-option { display:flex; gap:8px; align-items:center; padding:7px 10px; border-radius:8px; text-decoration:none; color:inherit; cursor:pointer; }
  .omnibar-option:hover, .omnibar-option.is-active { background:var(--soft,#eef1fb); }
  .omnibar-option-icon { display:inline-flex; flex:0 0 auto; }
  .omnibar-option-icon .icon { width:20px; height:20px; background:transparent; }
  .omnibar-option-main { display:flex; flex-direction:column; min-width:0; }
  .omnibar-option-title { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .omnibar-option-sub { font-size:12px; color:var(--muted,#64748b); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  @media (max-width:760px) { .omnibar { flex-basis:100%; order:3; margin:8px 0 0; } }
</style>
"""

OMNIBAR_JS = """
<script>
(function(){
  function esc(t){ return String(t==null?"":t).replace(/[&<>\\"']/g, function(c){ return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"})[c]; }); }
  function attach(input, box){
    var timer = null, items = [], active = -1;
    function hide(){ box.hidden = true; box.innerHTML = ""; items = []; active = -1; input.setAttribute("aria-expanded","false"); }
    function render(groups){
      items = [];
      if (!groups || !groups.length){ hide(); return; }
      var html = "";
      groups.forEach(function(g){
        html += '<div class="omnibar-group-label">' + g.icon + ' ' + esc(g.label) + '</div>';
        g.results.forEach(function(r){
          var idx = items.length; items.push(r);
          html += '<a class="omnibar-option" data-idx="' + idx + '" href="' + esc(r.href) + '"><span class="omnibar-option-icon">' + r.icon + '</span><span class="omnibar-option-main"><span class="omnibar-option-title">' + esc(r.title) + '</span>' + (r.subtitle ? '<span class="omnibar-option-sub">' + esc(r.subtitle) + '</span>' : '') + '</span></a>';
        });
      });
      box.innerHTML = html; box.hidden = false; active = -1; input.setAttribute("aria-expanded","true");
    }
    function fetchSuggest(q){
      fetch("/api/search/suggest?q=" + encodeURIComponent(q), { headers:{ "X-Requested-With":"local-web-fetch" } })
        .then(function(r){ return r.json(); })
        .then(function(p){ if ((input.value||"").trim() === q) render(p.groups || []); })
        .catch(function(){ hide(); });
    }
    input.addEventListener("input", function(){
      var q = (input.value||"").trim();
      if (timer) clearTimeout(timer);
      if (q.length < 1){ hide(); return; }
      timer = setTimeout(function(){ fetchSuggest(q); }, 180);
    });
    function setActive(n){
      var opts = box.querySelectorAll(".omnibar-option");
      if (!opts.length) return;
      active = (n + opts.length) % opts.length;
      opts.forEach(function(o,i){ o.classList.toggle("is-active", i === active); });
      opts[active].scrollIntoView({ block:"nearest" });
    }
    input.addEventListener("keydown", function(e){
      if (box.hidden) return;
      if (e.key === "ArrowDown"){ e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp"){ e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Enter"){ if (active >= 0 && items[active]){ e.preventDefault(); window.location = items[active].href; } }
      else if (e.key === "Escape"){ hide(); }
    });
    box.addEventListener("mousedown", function(e){
      var opt = e.target.closest(".omnibar-option");
      if (opt){ e.preventDefault(); window.location = opt.getAttribute("href"); }
    });
    document.addEventListener("click", function(e){ if (input.parentElement && !input.parentElement.contains(e.target)) hide(); });
  }
  document.querySelectorAll("input[data-omnibar-input]").forEach(function(input){
    var box = document.getElementById(input.getAttribute("data-omnibar-box"));
    if (box) attach(input, box);
  });
})();
</script>
"""


ARTICLE_EDITOR_CSS = """
<style>
  .article-editor { display:grid; grid-template-columns:minmax(0,1fr) minmax(300px,380px); gap:16px; align-items:start; }
  .article-main, .article-sidebar { display:grid; gap:14px; }
  .article-title-input { width:100%; font-size:20px; font-weight:700; padding:10px 12px; border:1px solid var(--border,#cbd5e1); border-radius:10px; box-sizing:border-box; }
  .article-saved { font-size:13px; color:var(--muted,#64748b); min-height:18px; }
  .article-sidebar .card { padding:14px; }
  .article-pick-list, .article-search-results { display:grid; gap:8px; }
  .article-search-results { max-height:40vh; overflow:auto; padding-right:2px; }
  .article-pick-card { border:1px solid var(--line,#e2e8f0); border-radius:8px; padding:8px 10px; background:#fff; display:grid; gap:6px; }
  .article-pick-title { font-weight:600; }
  .article-pick-summary { font-size:13px; color:var(--muted,#64748b); margin:0; }
  .article-pick-meta { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
  .article-search-row { margin-bottom:8px; }
  .article-search-row input { width:100%; box-sizing:border-box; padding:8px; border-radius:8px; border:1px solid var(--border,#cbd5e1); font:inherit; }
  .article-claim { border:1px solid var(--line,#e2e8f0); border-radius:8px; padding:8px 10px; margin-bottom:8px; }
  .article-claim p { margin:6px 0 0; font-size:13px; color:var(--muted,#475569); }
  .article-claim .badge { border:0; color:#fff; }
  .article-claim .badge--fc-ok { background:var(--ocf-primary,#6450dc); color:#fff; }
  .article-claim .badge--fc-mid { background:#1f2937; color:#fff; }
  .article-claim .badge--fc-bad { background:#dc2626; color:#fff; }
  .article-field { display:block; font-size:14px; font-weight:600; margin:0 0 4px; }
  .article-field select { width:100%; padding:8px; border-radius:8px; border:1px solid var(--border,#cbd5e1); font:inherit; }
  @media (max-width:900px) { .article-editor { grid-template-columns:1fr; } .article-search-results { max-height:none; } }
</style>
"""

# EasyMDE 離線無 FontAwesome：用全站一致的 SVG 圖示 + 中文文字標籤取代工具列圖示。
# scope 在 .easymde-host，可被編修台與全文編輯共用。圖示由 EASYMDE_TOOLBAR_ICON_JS 注入。
EASYMDE_TOOLBAR_CSS = """
<style>
  /* 離線無 FontAwesome：藏掉按鈕內的空圖示，改用注入的 SVG + 中文文字標籤；分隔線保留 */
  .easymde-host .editor-toolbar button i { display:none !important; }
  .easymde-host .editor-toolbar button {
    width:auto !important; min-width:0; height:auto; padding:5px 9px;
    display:inline-flex; align-items:center; gap:5px;
    font-size:13px; line-height:1.4; color:var(--ocf-dark);
  }
  .easymde-host .editor-toolbar button .md-ico {
    display:inline-grid; place-items:center; width:16px; height:16px; flex:0 0 auto;
  }
  .easymde-host .editor-toolbar button .md-ico svg {
    width:16px; height:16px; fill:none; stroke:currentColor; stroke-width:2;
    stroke-linecap:round; stroke-linejoin:round;
  }
  .easymde-host .editor-toolbar button::after { font-weight:700; }
  .easymde-host .editor-toolbar .bold::after { content:"粗"; }
  .easymde-host .editor-toolbar .italic::after { content:"斜"; }
  .easymde-host .editor-toolbar .heading::after { content:"標題"; }
  .easymde-host .editor-toolbar .quote::after { content:"引用"; }
  .easymde-host .editor-toolbar .unordered-list::after { content:"清單"; }
  .easymde-host .editor-toolbar .ordered-list::after { content:"編號"; }
  .easymde-host .editor-toolbar .link::after { content:"連結"; }
  .easymde-host .editor-toolbar .table::after { content:"表格"; }
  .easymde-host .editor-toolbar .code::after { content:"程式碼"; }
  .easymde-host .editor-toolbar .preview::after { content:"預覽"; }
  .easymde-host .editor-toolbar .side-by-side::after { content:"並排"; }
  .easymde-host .editor-toolbar .fullscreen::after { content:"全螢幕"; }
  .easymde-host .editor-toolbar .guide::after { content:"說明"; }
</style>
"""

# 把排版用 SVG 圖示注入 EasyMDE 工具列按鈕（icon + 文字一起顯示）。風格比照全站 action_icon
# 的 stroke SVG。用 MutationObserver 接住非同步建立的工具列，兩個 easymde-host 都能共用。
EASYMDE_TOOLBAR_ICON_JS = """
<script>
(function() {
  var ICONS = {
    "bold": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h6a3.3 3.3 0 0 1 0 6.6H7z"></path><path d="M7 11.6h7a3.4 3.4 0 0 1 0 6.8H7z"></path></svg>',
    "italic": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5"></path><path d="M5 19h5"></path><path d="M14.5 5L9.5 19"></path></svg>',
    "heading": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14"></path><path d="M16 5v14"></path><path d="M6 12h10"></path></svg>',
    "quote": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7h4v4a4 4 0 0 1-4 4"></path><path d="M14 7h4v4a4 4 0 0 1-4 4"></path></svg>',
    "unordered-list": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="7" r="1"></circle><circle cx="5" cy="12" r="1"></circle><circle cx="5" cy="17" r="1"></circle><path d="M10 7h9"></path><path d="M10 12h9"></path><path d="M10 17h9"></path></svg>',
    "ordered-list": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 7h9"></path><path d="M10 12h9"></path><path d="M10 17h9"></path><path d="M4 5.5l1.3-.5V9"></path><path d="M3.8 14.2h2.2l-2.2 3h2.4"></path></svg>',
    "link": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 15l6-6"></path><path d="M11.5 6.5l1-1a3.5 3.5 0 0 1 5 5l-1 1"></path><path d="M12.5 17.5l-1 1a3.5 3.5 0 0 1-5-5l1-1"></path></svg>',
    "table": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="1"></rect><path d="M3 10h18"></path><path d="M3 14.5h18"></path><path d="M9 5v14"></path><path d="M15 5v14"></path></svg>',
    "code": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 8l-4 4 4 4"></path><path d="M15 8l4 4-4 4"></path></svg>',
    "preview": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
    "side-by-side": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="1"></rect><path d="M12 5v14"></path></svg>',
    "fullscreen": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5"></path><path d="M20 9V4h-5"></path><path d="M4 15v5h5"></path><path d="M20 15v5h-5"></path></svg>',
    "guide": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M9.5 9.7a2.5 2.5 0 0 1 4 1.8c0 1.7-2.5 2-2.5 3.5"></path><circle cx="12" cy="17.5" r="0.6"></circle></svg>'
  };
  function decorate(root) {
    var buttons = (root || document).querySelectorAll(".easymde-host .editor-toolbar button");
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      if (btn.dataset.mdIcon) continue;
      var svg = null;
      for (var key in ICONS) {
        if (Object.prototype.hasOwnProperty.call(ICONS, key) && btn.classList.contains(key)) { svg = ICONS[key]; break; }
      }
      if (!svg) continue;
      btn.dataset.mdIcon = "1";
      var span = document.createElement("span");
      span.className = "md-ico";
      span.setAttribute("aria-hidden", "true");
      span.innerHTML = svg;
      btn.insertBefore(span, btn.firstChild);
    }
  }
  function boot() {
    decorate(document);
    var obs = new MutationObserver(function(muts) {
      for (var i = 0; i < muts.length; i++) {
        if (muts[i].addedNodes && muts[i].addedNodes.length) { decorate(document); break; }
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
</script>
"""

ARTICLE_EDITOR_JS = """
<script>
(function() {
  var stateEl = document.getElementById("article-state");
  if (!stateEl) return;
  var state = JSON.parse(stateEl.textContent || "{}");
  function blob(id){ var el = document.getElementById(id); try { return JSON.parse((el && el.textContent) || "[]"); } catch (e) { return []; } }
  var availableMaterials = blob("article-available-materials");
  var selectedMaterials = new Map();
  blob("article-selected-materials").forEach(function(m){ if (m && m.id) selectedMaterials.set(m.id, m); });
  var allViewpoints = blob("article-viewpoints-all");
  var selectedViewpoints = new Map();
  blob("article-selected-viewpoints").forEach(function(v){ if (v && v.id) selectedViewpoints.set(v.id, v); });

  function escapeHtml(t){ return String(t==null?"":t).replace(/[&<>\\"']/g, function(c){ return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"})[c]; }); }

  var titleInput = document.getElementById("article-title");
  var statusSel = document.getElementById("article-status");
  var trackSel = document.getElementById("article-track");
  var licenseSel = document.getElementById("article-license");
  var bodyArea = document.getElementById("article-body");
  var savedLabel = document.getElementById("article-saved-label");
  var tagsForm = document.querySelector("[data-article-tags]");

  var easymde = null;
  if (window.EasyMDE && bodyArea) {
    easymde = new EasyMDE({
      element: bodyArea,
      autoDownloadFontAwesome: false,
      spellChecker: false,
      status: ["lines", "words"],
      placeholder: "在這裡順稿。右側「事實查核守則」對照有沒有寫翻原本查核過的地方。",
      toolbar: ["bold","italic","heading","|","quote","unordered-list","ordered-list","|","link","table","code","|","preview","side-by-side","fullscreen","|","guide"]
    });
    easymde.codemirror.on("change", function(){ markDirty(); });
  }

  function currentTags(){
    if (!tagsForm) return state.tags || [];
    return Array.from(tagsForm.querySelectorAll('input[name="tags"]')).map(function(i){ return i.value; }).filter(Boolean);
  }
  function itemIds(){ return Array.from(selectedMaterials.keys()); }
  function viewpointIds(){ return Array.from(selectedViewpoints.keys()); }

  var saveTimer = null, dirty = false;
  function markDirty(){ dirty = true; if (savedLabel) savedLabel.textContent = "編輯中…"; if (saveTimer) clearTimeout(saveTimer); saveTimer = setTimeout(save, 900); }
  function save(){
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    var body = new URLSearchParams();
    body.set("id", state.id);
    body.set("title", titleInput ? titleInput.value : (state.title || ""));
    body.set("body_markdown", easymde ? easymde.value() : (bodyArea ? bodyArea.value : ""));
    body.set("track", trackSel ? trackSel.value : (state.track || ""));
    body.set("status", statusSel ? statusSel.value : (state.status || "draft"));
    body.set("license", licenseSel ? licenseSel.value : (state.license || ""));
    body.set("item_ids", itemIds().join(","));
    body.set("viewpoint_ids", viewpointIds().join(","));
    currentTags().forEach(function(t){ body.append("tags", t); });
    if (savedLabel) savedLabel.textContent = "儲存中…";
    fetch("/articles/save", { method:"POST", headers:{ "Content-Type":"application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With":"local-web-fetch" }, body: body })
      .then(function(r){ return r.json(); })
      .then(function(p){ if (p && p.ok) { dirty = false; if (savedLabel) savedLabel.textContent = "已儲存 " + (p.saved_label || ""); } else { if (savedLabel) savedLabel.textContent = "儲存失敗：" + ((p && p.error) || "未知錯誤"); } })
      .catch(function(e){ if (savedLabel) savedLabel.textContent = "儲存失敗：" + e; });
  }

  var matSearch = document.getElementById("article-material-search");
  var matResults = document.getElementById("article-material-results");
  var matList = document.getElementById("article-material-list");
  function materialBadges(m){
    var b = [];
    if (m.typeLabel) b.push('<span class="tag-pill">' + escapeHtml(m.typeLabel) + '</span>');
    b.push('<span class="tag-pill">' + escapeHtml(m.trackLabel || "未分類") + '</span>');
    return b.join("");
  }
  function renderMaterials(){
    if (!matList) return;
    var ids = itemIds();
    matList.innerHTML = ids.length ? ids.map(function(id){
      var m = selectedMaterials.get(id) || { id:id, title:id };
      return '<div class="article-pick-card"><div class="article-pick-title">' + escapeHtml(m.title || id) + '</div>' +
        '<div class="article-pick-meta"><code>' + escapeHtml(id) + '</code>' + materialBadges(m) + '</div>' +
        '<div class="button-row"><a class="button button-small secondary" target="_blank" href="/items/view?id=' + encodeURIComponent(id) + '">打開</a>' +
        '<button type="button" class="button button-small quiet" data-remove-mat="' + escapeHtml(id) + '">移除</button></div></div>';
    }).join("") : '<p class="muted">尚未引用任何材料。</p>';
  }
  function renderMatResults(){
    if (!matResults) return;
    var q = (matSearch.value || "").trim().toLowerCase();
    if (!q) { matResults.innerHTML = '<p class="muted">輸入關鍵字搜尋材料。</p>'; return; }
    var rows = availableMaterials.filter(function(m){
      return [m.id, m.title, m.summary, m.source, m.trackLabel].concat(m.tags || []).join(" ").toLowerCase().indexOf(q) !== -1;
    }).slice(0, 30);
    matResults.innerHTML = rows.length ? rows.map(function(m){
      var added = selectedMaterials.has(m.id);
      return '<div class="article-pick-card"><div class="article-pick-title">' + escapeHtml(m.title) + '</div>' +
        '<div class="article-pick-meta">' + materialBadges(m) + '</div>' +
        '<button type="button" class="button button-small" data-add-mat="' + escapeHtml(m.id) + '"' + (added ? " disabled" : "") + '>' + (added ? "已加入" : "加入引用") + '</button></div>';
    }).join("") : '<p class="muted">沒有符合的材料。</p>';
  }

  var vpSearch = document.getElementById("article-viewpoint-search");
  var vpResults = document.getElementById("article-viewpoint-results");
  var vpList = document.getElementById("article-viewpoint-list");
  function moveViewpoint(id, dir){
    var ids = viewpointIds();
    var i = ids.indexOf(id);
    if (i < 0) return;
    var j = dir === "up" ? i - 1 : i + 1;
    if (j < 0 || j >= ids.length) return;
    ids.splice(j, 0, ids.splice(i, 1)[0]);
    var next = new Map();
    ids.forEach(function(k){ next.set(k, selectedViewpoints.get(k)); });
    selectedViewpoints = next;
    renderViewpoints(); markDirty();
  }
  function renderViewpoints(){
    if (!vpList) return;
    var ids = viewpointIds();
    // 已關聯觀點只顯示標題（細節在 hover），用 ↑↓ 排序＝專文裡的觀點順序
    vpList.innerHTML = ids.length ? ids.map(function(id, idx){
      var v = selectedViewpoints.get(id) || { id:id, title:id };
      return '<div class="article-pick-card article-vp-picked"><div class="article-pick-title" title="' + escapeHtml(v.body || "") + '">' + escapeHtml(v.title || id) + '</div>' +
        '<div class="button-row">' +
        '<button type="button" class="button button-small quiet" data-move-vp="' + escapeHtml(id) + '" data-dir="up"' + (idx === 0 ? " disabled" : "") + ' aria-label="上移">↑</button>' +
        '<button type="button" class="button button-small quiet" data-move-vp="' + escapeHtml(id) + '" data-dir="down"' + (idx === ids.length - 1 ? " disabled" : "") + ' aria-label="下移">↓</button>' +
        '<a class="button button-small secondary" target="_blank" href="/editor/viewpoints?focus=' + encodeURIComponent(id) + '">打開</a>' +
        '<button type="button" class="button button-small quiet" data-remove-vp="' + escapeHtml(id) + '">移除</button></div></div>';
    }).join("") : '<p class="muted">尚未關聯觀點。加入後可用 ↑↓ 調整在專文裡的排序。</p>';
  }
  function renderVpResults(){
    if (!vpResults) return;
    var q = (vpSearch.value || "").trim().toLowerCase();
    if (!q) { vpResults.innerHTML = '<p class="muted">輸入關鍵字搜尋觀點。</p>'; return; }
    var rows = allViewpoints.filter(function(v){
      return [v.id, v.title, v.body].concat(v.tags || []).join(" ").toLowerCase().indexOf(q) !== -1;
    }).slice(0, 20);
    vpResults.innerHTML = rows.length ? rows.map(function(v){
      var added = selectedViewpoints.has(v.id);
      return '<div class="article-pick-card"><div class="article-pick-title">' + escapeHtml(v.title) + '</div>' +
        (v.body ? '<p class="article-pick-summary">' + escapeHtml(v.body) + '</p>' : '') +
        '<button type="button" class="button button-small" data-add-vp="' + escapeHtml(v.id) + '"' + (added ? " disabled" : "") + '>' + (added ? "已關聯" : "關聯觀點") + '</button></div>';
    }).join("") : '<p class="muted">沒有符合的觀點。</p>';
  }

  document.addEventListener("click", function(e){
    var t = e.target;
    if (!t || !t.dataset) return;
    if (t.dataset.addMat) { var m = availableMaterials.find(function(x){ return x.id === t.dataset.addMat; }); if (m) { selectedMaterials.set(m.id, m); renderMaterials(); renderMatResults(); markDirty(); } }
    else if (t.dataset.removeMat) { selectedMaterials.delete(t.dataset.removeMat); renderMaterials(); renderMatResults(); markDirty(); }
    else if (t.dataset.addVp) { var v = allViewpoints.find(function(x){ return x.id === t.dataset.addVp; }); if (v) { selectedViewpoints.set(v.id, v); renderViewpoints(); renderVpResults(); markDirty(); } }
    else if (t.dataset.removeVp) { selectedViewpoints.delete(t.dataset.removeVp); renderViewpoints(); renderVpResults(); markDirty(); }
    else if (t.dataset.moveVp) { moveViewpoint(t.dataset.moveVp, t.dataset.dir); }
  });
  if (matSearch) matSearch.addEventListener("input", renderMatResults);
  if (vpSearch) vpSearch.addEventListener("input", renderVpResults);
  if (titleInput) titleInput.addEventListener("input", markDirty);
  if (statusSel) statusSel.addEventListener("change", markDirty);
  if (trackSel) trackSel.addEventListener("change", markDirty);
  if (licenseSel) licenseSel.addEventListener("change", markDirty);
  if (tagsForm) {
    tagsForm.addEventListener("click", function(){ setTimeout(markDirty, 60); });
    tagsForm.addEventListener("keydown", function(e){ if (e.key === "Enter") setTimeout(markDirty, 60); });
  }

  var recheckBtn = document.getElementById("article-recheck");
  if (recheckBtn) recheckBtn.addEventListener("click", function(){
    if (!window.runEngineJob) { window.alert("頁面尚未就緒，請重新整理。"); return; }
    var ids = itemIds();
    if (!ids.length) { window.alert("這篇沒有引用材料，無法查核。請先在右側加入引用材料。"); return; }
    window.runEngineJob({
      label: "重新查核：" + (state.title || "專文"),
      url: "/editor/run",
      baseBody: { task_type: "factcheck", items: ids.join(",") },
      engine: recheckBtn.dataset.engine || "random",
      statusUrl: "/api/editor/status",
      onSuccess: function(){
        var rb = new URLSearchParams(); rb.set("id", state.id);
        fetch("/articles/refresh-factcheck", { method:"POST", headers:{ "Content-Type":"application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With":"local-web-fetch" }, body: rb })
          .then(function(){ window.location.reload(); });
      }
    });
  });

  window.addEventListener("beforeunload", function(e){ if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  renderMaterials(); renderViewpoints();
})();
</script>
"""


def material_article_links_by_item() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for link in load_jsonl(MATERIAL_LINKS):
        item_id = clean_text(link.get("item_id"))
        if item_id:
            grouped[item_id].append(link)
    return grouped


def article_link_html(link: dict) -> str:
    ref = clean_text(link.get("ref"))
    title = clean_text(link.get("title")) or ref
    if clean_text(link.get("ref_kind")) == "item" or ref.startswith("item-"):
        return f'<a href="/items/view?id={quote(ref)}">{h(title)}</a>'
    if ref.startswith(("http://", "https://")):
        return f'<a href="{h(ref)}" target="_blank" rel="noopener">{h(title)} ↗</a>'
    return h(title)


def pdf_relation_candidates(item: dict) -> list[dict]:
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    candidates = reference.get("pdf_relation_candidates")
    if not isinstance(candidates, list):
        return []
    ignored = set(reference.get("pdf_relation_ignored_ids") or [])
    resolved = set(reference.get("pdf_relation_resolved_ids") or [])
    return [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and clean_text(candidate.get("item_id"))
        and clean_text(candidate.get("item_id")) not in ignored
        and clean_text(candidate.get("item_id")) not in resolved
    ]


def pdf_relation_modal_html(item: dict, auto_open: bool = False) -> str:
    candidates = pdf_relation_candidates(item)
    if not candidates:
        return ""
    item_id = clean_text(item.get("id"))
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    confirmations = reference.get("pdf_relation_confirmations") if isinstance(reference.get("pdf_relation_confirmations"), dict) else {}
    rows = []
    for candidate in candidates:
        candidate_id = clean_text(candidate.get("item_id"))
        title = clean_text(candidate.get("title")) or candidate_id
        kind = clean_text(candidate.get("candidate_kind"))
        relation = clean_text(candidate.get("relation")) or "related"
        score_bits = []
        if candidate.get("title_similarity") is not None:
            score_bits.append(f"標題相似 {float(candidate.get('title_similarity') or 0) * 100:.0f}%")
        if candidate.get("existing_covered_by_pdf") is not None:
            score_bits.append(f"既有材料被 PDF 涵蓋 {float(candidate.get('existing_covered_by_pdf') or 0) * 100:.0f}%")
        if candidate.get("pdf_covered_by_existing") is not None:
            score_bits.append(f"PDF 被既有材料涵蓋 {float(candidate.get('pdf_covered_by_existing') or 0) * 100:.0f}%")
        if candidate.get("jaccard") is not None:
            score_bits.append(f"Jaccard {float(candidate.get('jaccard') or 0) * 100:.0f}%")
        source_url = clean_text(candidate.get("url"))
        source_line = f'<a href="{h(source_url)}" target="_blank" rel="noopener">開候選原文 ↗</a>' if source_url else "候選也沒有原始網址"
        confirmation_rows = []
        candidate_confirmations = confirmations.get(candidate_id) if isinstance(confirmations.get(candidate_id), dict) else {}
        for provider in AI_PROVIDER_ORDER:
            result = candidate_confirmations.get(provider)
            if not isinstance(result, dict):
                continue
            confirmation_rows.append(
                f"<li><strong>{h(ai_provider_label(provider))}</strong>：{h(pdf_relation_label(clean_text(result.get('relation'))))}，"
                f"{h(result.get('confidence'))}；{h(clean_text(result.get('explanation'), 360))}</li>"
            )
        confirmation_html = f"<ul class='help'>{''.join(confirmation_rows)}</ul>" if confirmation_rows else ""
        if kind == "title-source":
            actions = f"""
<form method="post" action="/items/pdf-relation-action">
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="candidate_id" value="{h(candidate_id)}">
  <button name="action" value="source-match" type="submit">{button_content("就是這個來源", "accept")}</button>
  <button name="action" value="related" type="submit" class="secondary">{button_content("相關但不是同一篇", "source")}</button>
  <button name="action" value="ignore" type="submit" class="quiet">忽略這筆</button>
</form>
"""
            kind_label = "源頭比對"
        else:
            actions = f"""
<form method="post" action="/items/pdf-relation-action">
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="candidate_id" value="{h(candidate_id)}">
  <input type="hidden" name="relation" value="{h(relation)}">
  <button name="action" value="establish" type="submit">{button_content("建立關聯", "plus")}</button>
  <button name="action" value="fulltext" type="submit" class="secondary">{button_content("設為這篇材料的全文", "text-lines")}</button>
  <button name="action" value="ignore" type="submit" class="quiet">忽略</button>
</form>
<form class="pdf-cli-confirm-form" data-pdf-relation-confirm>
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="candidate_id" value="{h(candidate_id)}">
  <select name="engine" aria-label="確認關係引擎">{option_list([("random", "隨機 CLI"), *[(provider, AI_PROVIDER_META[provider]["label"]) for provider in AI_PROVIDER_ORDER]], "random")}</select>
  <button type="submit" class="button button-small quiet">{button_content("用 CLI 再確認關係", "sparkle")}</button>
</form>
"""
            kind_label = f"內容關係：{pdf_relation_label(relation)}（{h(candidate.get('confidence') or '低')}信心）"
        rows.append(
            f"""
<article class="pdf-relation-card">
  <div class="reader-list-meta">{badge(kind_label, "neutral")}</div>
  <h3><a href="/items/view?id={quote(candidate_id)}">{h(title)}</a></h3>
  <p class="muted">{h("；".join(score_bits) or "本機規則找到相似材料。")}</p>
  <p class="help">{source_line}</p>
  {confirmation_html}
  <div class="pdf-relation-actions">{actions}</div>
</article>
"""
        )
    return f"""
<dialog class="pdf-relation-dialog" data-pdf-relation-dialog data-auto-open="{'1' if auto_open else '0'}">
  <form method="dialog" class="dialog-close-row"><button class="button quiet" value="close">先關閉</button></form>
  <h2>確認 PDF 和既有材料的關係</h2>
  <p class="lede">這些只是本機標題與文字涵蓋率提示。請人工決定，不會自動覆蓋來源或合併材料。</p>
  <div class="pdf-relation-grid">{''.join(rows)}</div>
  <form method="post" action="/items/pdf-relation-action">
    <input type="hidden" name="id" value="{h(item_id)}">
    <button name="action" value="new-source" type="submit" class="secondary">都不是，當全新來源</button>
  </form>
</dialog>
"""


def pdf_split_proposals_html(item: dict) -> str:
    metadata = item_reading_metadata(item)
    proposals = metadata.get("pdf_split_proposals")
    if not isinstance(proposals, dict) or not proposals:
        return ""
    item_id = clean_text(item.get("id"))
    cards = []
    for provider in AI_PROVIDER_ORDER:
        proposal = proposals.get(provider)
        if not isinstance(proposal, dict):
            continue
        sections = proposal.get("sections") if isinstance(proposal.get("sections"), list) else []
        fields = []
        for index, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                continue
            marker_state = "起訖都已定位" if section.get("start_found") and section.get("end_found") else "有標記尚未在全文定位，請先修改"
            error_note = f'<p class="help" style="color:var(--danger,#b00)">上次沒定位到：{h(section.get("error"))}</p>' if clean_text(section.get("error")) else ""
            fields.append(
                f"""
<fieldset class="pdf-split-section">
  <legend>第 {index} 篇</legend>
  <label>標題<input name="section_title" value="{h(section.get('title'))}" required></label>
  <label>起始標記<textarea name="start_marker" required>{h(section.get('start_marker'))}</textarea></label>
  <label>結束標記<textarea name="end_marker" required>{h(section.get('end_marker'))}</textarea></label>
  <label>備註<textarea name="section_notes">{h(section.get('notes'))}</textarea></label>
  <p class="help">{h(marker_state)}</p>
  {error_note}
</fieldset>
"""
            )
        cards.append(
            f"""
<article class="card pdf-split-proposal">
  <h3>{h(ai_provider_label(provider))} 提案</h3>
  <p>{h(proposal.get('summary'))}</p>
  <form method="post" action="/items/pdf-split-apply">
    <input type="hidden" name="id" value="{h(item_id)}">
    <input type="hidden" name="provider" value="{h(provider)}">
    {''.join(fields)}
    <button type="submit">{button_content("採用這份提案並拆成材料", "accept")}</button>
    <p class="help">送出前可直接修改標題與起訖標記；拆出的每篇都只會進入入庫建檔區。</p>
  </form>
</article>
"""
        )
    if not cards:
        return ""
    return f"""
<section class="pdf-split-results">
  <h2>兩個拆分草案</h2>
  <div class="pdf-split-grid">{''.join(cards)}</div>
</section>
"""


def editor_relative_time(value: str) -> str:
    return clean_text(value).replace("T", " ").replace("+00:00", " UTC")


def editor_year_label(value: object) -> str:
    text = clean_text(value)
    match = re.search(r"(20\d{2}|19\d{2})", text)
    return f"{match.group(1)} 年" if match else "未標年份"


def editor_timeline_html(
    entries: list[dict],
    render_entry,
    *,
    empty_html: str,
    initial_count: int = 8,
    batch_size: int = 8,
    class_name: str = "editor-timeline",
) -> str:
    if not entries:
        return empty_html
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        grouped[editor_year_label(entry.get("_timeline_at") or entry.get("updated_at") or entry.get("created_at"))].append(entry)
    year_labels = sorted(grouped, reverse=True)
    sections = []
    for year_label in year_labels:
        rows = []
        for index, entry in enumerate(grouped[year_label]):
            hidden_class = " is-timeline-hidden" if index >= initial_count else ""
            rows.append(
                f'<div class="editor-timeline-item{hidden_class}" data-timeline-item data-year="{h(year_label)}">'
                f'{render_entry(entry)}'
                "</div>"
            )
        hidden_count = max(0, len(grouped[year_label]) - initial_count)
        more = ""
        if hidden_count:
            more = (
                '<div class="editor-timeline-more" data-timeline-sentinel>'
                f'<button type="button" class="button secondary button-small" data-timeline-more data-year="{h(year_label)}" data-batch="{batch_size}">'
                f'再載入 {min(batch_size, hidden_count)} 筆</button>'
                f'<span class="muted">尚有 {hidden_count} 筆</span>'
                '</div>'
            )
        sections.append(
            f"""
<details class="{h(class_name)}-year reader-period-details" open>
  <summary class="reader-period-heading">
    <span class="reader-period-heading-label">{h(year_label)}</span>
    <span class="reader-period-count">{len(grouped[year_label])} 筆</span>
  </summary>
  <div class="{h(class_name)}-items" data-timeline-year="{h(year_label)}">
    {''.join(rows)}
    {more}
  </div>
</details>
"""
        )
    return f'<div class="{h(class_name)}" data-editor-timeline>{"".join(sections)}</div>'


EDITOR_TIMELINE_ASSETS = """
<style>
  [data-editor-timeline] { display:grid; gap:12px; }
  .editor-timeline-item { animation: editor-fade-in 180ms ease both; }
  .editor-timeline-item.is-timeline-hidden { display:none; }
  .editor-timeline-item.is-fading-in { animation: editor-fade-in 220ms ease both; }
  .editor-timeline-more { display:flex; gap:10px; align-items:center; margin-top:10px; }
  @keyframes editor-fade-in {
    from { opacity:0; transform:translateY(6px); }
    to { opacity:1; transform:translateY(0); }
  }
</style>
<script>
(function() {
  function refreshButton(button) {
    var year = button.getAttribute("data-year");
    var hidden = document.querySelectorAll('[data-timeline-item][data-year="' + CSS.escape(year) + '"].is-timeline-hidden');
    var row = button.closest("[data-timeline-sentinel]");
    if (!hidden.length) {
      if (row) row.hidden = true;
      return;
    }
    var batch = Math.max(1, parseInt(button.getAttribute("data-batch") || "8", 10));
    button.textContent = "再載入 " + Math.min(batch, hidden.length) + " 筆";
    var counter = row ? row.querySelector(".muted") : null;
    if (counter) counter.textContent = "尚有 " + hidden.length + " 筆";
  }
  function reveal(button) {
    var year = button.getAttribute("data-year");
    var batch = Math.max(1, parseInt(button.getAttribute("data-batch") || "8", 10));
    var hidden = Array.from(document.querySelectorAll('[data-timeline-item][data-year="' + CSS.escape(year) + '"].is-timeline-hidden')).slice(0, batch);
    hidden.forEach(function(item) {
      item.classList.remove("is-timeline-hidden");
      item.classList.add("is-fading-in");
    });
    refreshButton(button);
  }
  document.querySelectorAll("[data-timeline-more]").forEach(function(button) {
    refreshButton(button);
    button.addEventListener("click", function() { reveal(button); });
  });
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (!entry.isIntersecting) return;
        var button = entry.target.querySelector("[data-timeline-more]");
        if (button && !button.closest("[data-timeline-sentinel]").hidden) reveal(button);
      });
    }, { rootMargin: "160px" });
    document.querySelectorAll("[data-timeline-sentinel]").forEach(function(row) { observer.observe(row); });
  }
})();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "IanOpenNewsLocal/1.0"

    def send_html(self, title: str, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_reader_asset(self, path: str) -> None:
        relative = path.removeprefix("/reader/assets/").lstrip("/")
        asset_root = ROOT / "docs" / "reader" / "assets"
        target = (asset_root / relative).resolve()
        try:
            target.relative_to(asset_root.resolve())
        except ValueError:
            self.send_html("找不到", "<h1>找不到檔案</h1>", HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_html("找不到", "<h1>找不到檔案</h1>", HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, path: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
        self.end_headers()

    def is_async_request(self) -> bool:
        return self.headers.get("X-Requested-With") == "local-web-fetch"

    def same_origin_referer_path(self, fallback: str) -> str:
        referer = clean_text(self.headers.get("Referer", ""))
        if not referer:
            return fallback
        parsed = urlparse(referer)
        current_host = clean_text(self.headers.get("Host", ""))
        if parsed.netloc and parsed.netloc != current_host:
            return fallback
        path = parsed.path or "/"
        if path == "/items/view":
            return fallback
        query = f"?{parsed.query}" if parsed.query else ""
        return safe_redirect_path(f"{path}{query}", fallback)

    def send_no_content(self, status: HTTPStatus = HTTPStatus.NO_CONTENT) -> None:
        self.send_response(status)
        self.end_headers()

    def read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return parse_qs(raw)

    def read_multipart_form(self, max_bytes: int = 80 * 1024 * 1024) -> tuple[dict[str, list[str]], dict[str, list[dict]]]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_bytes:
            raise ValueError("上傳內容為空，或超過 80 MB 上限。")
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("這個表單需要 multipart/form-data。")
        raw = self.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
        )
        fields: dict[str, list[str]] = defaultdict(list)
        files: dict[str, list[dict]] = defaultdict(list)
        for part in message.iter_parts():
            name = clean_text(part.get_param("name", header="content-disposition"))
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            filename = clean_text(part.get_filename())
            if filename:
                files[name].append(
                    {
                        "filename": Path(filename).name,
                        "content_type": clean_text(part.get_content_type()),
                        "content": payload,
                    }
                )
                continue
            charset = part.get_content_charset() or "utf-8"
            fields[name].append(payload.decode(charset, errors="replace"))
        return dict(fields), dict(files)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            self.show_home(query)
        elif parsed.path.startswith("/reader/assets/"):
            self.send_reader_asset(parsed.path)
        elif parsed.path.startswith("/track/"):
            self.show_track(parsed.path.removeprefix("/track/"))
        elif parsed.path == "/candidates":
            self.show_candidates(query)
        elif parsed.path == "/reader":
            self.show_reader(query)
        elif parsed.path == "/tags":
            self.show_tag_view(query)
        elif parsed.path == "/rss-candidates":
            suffix = f"?{parsed.query}" if parsed.query else ""
            self.redirect(f"/items{suffix}")
        elif parsed.path == "/keywords":
            self.show_keywords()
        elif parsed.path == "/integrity":
            self.show_integrity(query)
        elif parsed.path == "/items":
            self.show_items(query)
        elif parsed.path == "/recycle":
            suffix = f"?{parsed.query}" if parsed.query else ""
            self.redirect(f"/recycle-bin{suffix}")
        elif parsed.path == "/recycle-bin":
            self.show_recycle_bin(query)
        elif parsed.path == "/items/view":
            self.show_item_detail(query)
        elif parsed.path == "/items/reject":
            self.show_item_reject_form(query)
        elif parsed.path == "/items/new":
            self.show_item_form(query)
        elif parsed.path == "/items/upload-pdf":
            self.show_pdf_upload_form(query)
        elif parsed.path == "/items/edit-fulltext":
            self.show_fulltext_editor(query)
        elif parsed.path == "/sources":
            self.show_sources(query)
        elif parsed.path == "/manual-items":
            self.show_manual_items(query)
        elif parsed.path == "/sources/view":
            self.show_source_view(query)
        elif parsed.path == "/sources/new":
            self.show_source_form(
                {
                    "track": (query.get("track") or ["digital-humanities-local-knowledge"])[0],
                    "source_type": (query.get("source_type") or ["rss"])[0],
                    "source_group": clean_text(unquote((query.get("source_group") or ["Manual RSS"])[0])),
                    "name": clean_text(unquote((query.get("name") or [""])[0])),
                    "feed_url": clean_text(unquote((query.get("feed_url") or [""])[0])),
                    "site_url": clean_text(unquote((query.get("site_url") or [""])[0])),
                }
            )
        elif parsed.path == "/sources/edit":
            self.show_source_edit(query)
        elif parsed.path == "/api/rss-status":
            self.send_json(load_json(RSS_FETCH_STATUS))
        elif parsed.path == "/api/data-commit-status":
            self.send_json(load_json(DATA_COMMIT_STATUS))
        elif parsed.path == "/api/command-status":
            status = load_json(COMMAND_STATUS)
            requested_command = clean_text((query.get("command") or [""])[0])
            if requested_command and clean_text(status.get("command")) != requested_command:
                status = {"state": "idle", "command": requested_command}
            self.send_json(status)
        elif parsed.path == "/editor":
            self.show_editor_console(query)
        elif parsed.path == "/editor/session":
            self.show_editor_session(query)
        elif parsed.path == "/editor/viewpoints":
            self.show_viewpoints(query)
        elif parsed.path == "/writing-styles":
            self.show_writing_styles(query)
        elif parsed.path == "/articles/edit":
            self.show_article_editor(query)
        elif parsed.path == "/articles/view":
            self.show_article_view(query)
        elif parsed.path == "/articles":
            self.show_articles_index(query)
        elif parsed.path == "/search":
            self.show_search(query)
        elif parsed.path == "/api/search/suggest":
            self.search_suggest(query)
        elif parsed.path == "/api/editor/status":
            status = load_json(EDITOR_STATUS)
            requested = clean_text((query.get("session") or [""])[0])
            if requested and clean_text(status.get("session_id")) != requested:
                status = {"state": "idle", "session_id": requested}
            self.send_json(status)
        elif parsed.path == "/insights":
            self.show_insights(query)
        elif parsed.path == "/insights/edit-taste-profile":
            self.show_taste_profile_editor(query)
        elif parsed.path == "/api/insight-status":
            self.send_json(load_json(INSIGHT_STATUS))
        elif parsed.path == "/api/pdf-split-status":
            self.send_json(load_json(PDF_SPLIT_STATUS))
        elif parsed.path == "/api/translate-status":
            status = load_json(TRANSLATE_STATUS)
            requested = clean_text((query.get("id") or [""])[0])
            if requested and clean_text(status.get("item_id")) and clean_text(status.get("item_id")) != requested:
                status = {"state": "running", "message": "翻譯啟動中…"}
            self.send_json(status)
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/items":
            self.save_item(self.read_form())
        elif parsed.path == "/items/upload-pdf":
            try:
                fields, files = self.read_multipart_form()
            except ValueError as exc:
                self.send_html("PDF 上傳失敗", f"<h1>PDF 上傳失敗</h1><p>{h(exc)}</p><p><a class='button' href='/items/upload-pdf'>回上傳表單</a></p>", HTTPStatus.BAD_REQUEST)
                return
            self.save_pdf_upload(fields, files)
        elif parsed.path == "/items/accept":
            self.accept_item(self.read_form())
        elif parsed.path == "/items/direct-pr":
            self.direct_pr_item(self.read_form())
        elif parsed.path == "/items/reject":
            self.reject_item(self.read_form())
        elif parsed.path == "/items/batch":
            self.batch_items(self.read_form())
        elif parsed.path == "/items/auto-batch-skip":
            self.auto_batch_skip_items(self.read_form())
        elif parsed.path == "/items/auto-batch-keep":
            self.auto_batch_keep_items(self.read_form())
        elif parsed.path == "/items/personal-note":
            self.save_personal_note(self.read_form())
        elif parsed.path == "/items/update-tags":
            self.update_item_tags(self.read_form())
        elif parsed.path == "/items/toggle-reading-priority":
            self.toggle_reading_priority(self.read_form())
        elif parsed.path == "/pages/toggle-publish":
            self.toggle_page_publish(self.read_form())
        elif parsed.path == "/items/requeue-skill":
            self.requeue_skill_item(self.read_form())
        elif parsed.path == "/items/read-more":
            self.read_more_item(self.read_form())
        elif parsed.path == "/items/extract-newsletter-links":
            self.extract_newsletter_links_item(self.read_form())
        elif parsed.path == "/items/pdf-markdown":
            self.normalize_pdf_markdown(self.read_form())
        elif parsed.path == "/items/save-fulltext":
            self.save_fulltext_edit(self.read_form())
        elif parsed.path == "/items/repaginate-fulltext":
            self.repaginate_fulltext(self.read_form())
        elif parsed.path == "/items/fulltext-link":
            self.save_fulltext_link(self.read_form())
        elif parsed.path == "/items/fulltext-text":
            self.save_fulltext_text(self.read_form())
        elif parsed.path == "/items/pdf-relation-action":
            self.pdf_relation_action(self.read_form())
        elif parsed.path == "/items/pdf-relation-confirm":
            self.pdf_relation_confirm(self.read_form())
        elif parsed.path == "/items/pdf-split-suggest":
            self.pdf_split_suggest(self.read_form())
        elif parsed.path == "/items/pdf-split-apply":
            self.pdf_split_apply(self.read_form())
        elif parsed.path == "/items/codex-review":
            self.codex_review_item(self.read_form())
        elif parsed.path == "/items/codex-review-batch":
            self.codex_review_batch(self.read_form())
        elif parsed.path == "/items/update-url":
            self.update_item_url(self.read_form())
        elif parsed.path == "/items/update-title":
            self.update_item_title(self.read_form())
        elif parsed.path == "/items/update-metadata":
            self.update_item_metadata(self.read_form())
        elif parsed.path == "/items/translate-zh":
            self.translate_item_zh(self.read_form())
        elif parsed.path == "/recycle-bin/restore":
            self.restore_recycle_item(self.read_form())
        elif parsed.path == "/preview-url":
            self.preview_url(self.read_form())
        elif parsed.path == "/candidates/accept":
            self.accept_candidate(self.read_form())
        elif parsed.path == "/candidates/dismiss":
            self.dismiss_candidate(self.read_form())
        elif parsed.path == "/keywords":
            self.save_keywords(self.read_form())
        elif parsed.path == "/sources":
            self.save_source(self.read_form())
        elif parsed.path == "/sources/quick-update":
            self.quick_update_source(self.read_form())
        elif parsed.path == "/sources/move-source-group":
            self.move_source_group(self.read_form())
        elif parsed.path == "/sources/reorder-groups":
            self.reorder_source_groups(self.read_form())
        elif parsed.path == "/sources/rename-group":
            self.rename_source_group(self.read_form())
        elif parsed.path == "/sources/fetch":
            self.fetch_source_now_post(self.read_form())
        elif parsed.path == "/sources/restore-item":
            self.restore_source_item(self.read_form())
        elif parsed.path == "/commands/run":
            self.run_command(self.read_form())
        elif parsed.path == "/integrity/fix":
            self.apply_integrity_fix_request(self.read_form())
        elif parsed.path == "/editor/run":
            self.run_editor_task(self.read_form())
        elif parsed.path == "/editor/viewpoints/save":
            self.save_viewpoint(self.read_form())
        elif parsed.path == "/editor/viewpoints/delete":
            self.delete_viewpoint(self.read_form())
        elif parsed.path == "/editor/link-article":
            self.link_article(self.read_form())
        elif parsed.path == "/editor/unlink-article":
            self.unlink_article(self.read_form())
        elif parsed.path == "/articles/create-from-session":
            self.create_article_from_session(self.read_form())
        elif parsed.path == "/articles/save":
            self.save_article(self.read_form())
        elif parsed.path == "/articles/refresh-factcheck":
            self.refresh_article_factcheck(self.read_form())
        elif parsed.path == "/insights/explain":
            self.save_divergence_explanation(self.read_form())
        elif parsed.path == "/insights/dismiss":
            self.dismiss_divergence(self.read_form())
        elif parsed.path == "/insights/sample-into-cue":
            self.sample_into_cue(self.read_form())
        elif parsed.path == "/insights/generate-report":
            self.generate_divergence_report(self.read_form(), mode="explained")
        elif parsed.path == "/insights/mark-implemented":
            self.mark_report_implemented(self.read_form())
        elif parsed.path == "/insights/apply-report":
            self.apply_report_with_cli(self.read_form())
        elif parsed.path == "/insights/proposal-add":
            self.proposal_add(self.read_form())
        elif parsed.path == "/insights/proposal-status":
            self.proposal_status(self.read_form())
        elif parsed.path == "/insights/close-analyzed":
            self.close_analyzed_divergence(self.read_form())
        elif parsed.path == "/insights/close-all-resolved":
            self.close_all_resolved_divergences(self.read_form())
        elif parsed.path == "/insights/save-taste-profile":
            self.save_taste_profile_edit(self.read_form())
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------ #
    # 編輯台
    # ------------------------------------------------------------------ #
    def show_editor_console(self, query: dict[str, list[str]]) -> None:
        engines = editor_engine_status()
        prefill_ids = [clean_text(x) for x in (query.get("items") or []) if clean_text(x)]
        if len(prefill_ids) == 1 and ("," in prefill_ids[0] or "\n" in prefill_ids[0]):
            prefill_ids = re.split(r"[\s,]+", prefill_ids[0])
        prefill_ids = list(dict.fromkeys(x for x in prefill_ids if x))
        default_task = clean_text((query.get("task") or ["theme-check"])[0]) or "theme-check"

        lookup = editor_item_lookup()
        available_records = editor_search_items()
        available_payload = [editor_material_payload(record) for record in available_records[:350]]
        selected_payload = [editor_material_payload(lookup[item_id]) for item_id in prefill_ids if lookup.get(item_id)]
        available_json = json.dumps(available_payload, ensure_ascii=False).replace("<", "\\u003c")
        selected_json = json.dumps(selected_payload, ensure_ascii=False).replace("<", "\\u003c")

        engine_default = "random"

        def engine_option(name: str, label: str) -> str:
            available = engines.get(name)
            selected = " selected" if name == engine_default and available else ""
            disabled = "" if available else " disabled"
            suffix = "" if available else "（未安裝）"
            return f'<option value="{name}"{selected}{disabled}>{h(label + suffix)}</option>'

        task_options = editor_task_options_html(default_task)

        session_entries = list(reversed(load_jsonl(EDITOR_SESSIONS)))
        for session in session_entries:
            session["_timeline_at"] = clean_text(session.get("created_at"))

        def session_row(s: dict) -> str:
            titles = "、".join(h(t) for t in (s.get("item_titles") or [])[:3])
            extra = "…" if len(s.get("item_titles") or []) > 3 else ""
            return (
                '<a class="editor-session-row" href="/editor/session?id=' + quote(clean_text(s.get("id"))) + '">'
                f'<strong>{h(s.get("task_label") or s.get("task_type"))}</strong>'
                f'<span class="tag-pill">{h(s.get("engine"))}</span>'
                + (f'<span class="tag-pill">{h(EDITOR_CHOICE_LABELS.get(s.get("choice"), ""))}</span>' if s.get("choice") else "")
                + f'<span class="editor-session-titles">{titles}{extra}</span>'
                f'<span class="muted">{h(editor_relative_time(s.get("created_at")))}</span>'
                "</a>"
            )

        session_rows = editor_timeline_html(
            session_entries,
            session_row,
            empty_html='<p class="muted">還沒有編輯紀錄。挑幾篇材料、選引擎與任務後按「開始」。</p>',
            initial_count=8,
            batch_size=8,
            class_name="editor-session-timeline",
        )

        viewpoints = load_jsonl(VIEWPOINTS)
        material_count = sum(1 for record in available_records if is_skill_candidate(record))
        small_news_count = sum(1 for record in available_records if is_direct_pr_item(record))

        hints = "".join(
            f'<p data-task-hint="{k}" class="editor-hint"{"" if k == default_task else " hidden"}>{h(v)}</p>'
            for k, v in EDITOR_TASK_HINTS.items()
        )

        body = f"""
{back_nav_html(self.same_origin_referer_path("/"))}
<section class="editor-hero">
  <h1>{icon_span("edit")}編輯台</h1>
  <p class="lede">從材料池挑可用材料或新聞小消息，拖進草稿庫後再選模型、寫文模式與任務。只有這裡產出的稿件才稱為 article。</p>
  <div class="button-row">
    <a class="button secondary" href="/candidates">{button_content('回可用材料區', 'inbox')}</a>
    <a class="button quiet" href="/editor/viewpoints">{button_content(f'觀點庫（{len(viewpoints)}）', 'note')}</a>
  </div>
</section>

<section class="editor-workbench">
  <div class="card editor-card">
    <h2>草稿庫</h2>
    <p class="help">把這次要一起判斷、撰稿或補脈絡的材料放在這裡。可從右側搜尋後拖入，或從單篇頁直接送進來。</p>
    <div class="editor-draft-bin" data-editor-dropzone>
      <div class="editor-draft-empty" data-draft-empty>搜尋材料後拖進來，或按「加入草稿庫」。</div>
      <div class="editor-draft-list" data-draft-list></div>
    </div>
  <form id="editor-run-form" method="post" action="/editor/run">
    <input type="hidden" name="items" data-selected-items>
    <div class="editor-control-grid">
      <label class="editor-label">模型
        <select name="engine" class="editor-select"><option value="random" selected>隨機（失敗自動換其他可用 CLI）</option>{''.join(engine_option(provider, AI_PROVIDER_META[provider]['label']) for provider in AI_PROVIDER_ORDER)}</select>
      </label>
      <label class="editor-label">任務
        <select name="task_type" id="editor-task-type" class="editor-select">{task_options}</select>
      </label>
      <label class="editor-label">寫文模式
        <select name="choice" class="editor-select">
          <option value="thematic">主題式</option>
          <option value="digest">彙報式</option>
        </select>
      </label>
    </div>
    {hints}
    <label class="editor-label">撰文風格 <a class="editor-style-link" href="/writing-styles" target="_blank">（管理 / 看風格檔）</a>
      <select name="writing_style" class="editor-select">{writing_style_options_html()}</select>
    </label>
    <label class="editor-label">額外指示（可留空）
      <textarea name="instructions" rows="2" placeholder="例如：聚焦台灣讀者、強調公共政策意涵"></textarea>
    </label>
    <button type="submit" class="button">{button_content('開始', 'wand')}</button>
    <span class="muted" id="editor-run-status"></span>
  </form>
  </div>

  <aside class="card editor-search-card">
    <h2>搜尋材料</h2>
    <p class="help">來源包含可用材料與新聞小消息。搜尋標題、摘要、來源或 tag，拖進左側草稿庫。</p>
    <div class="editor-search-row">
      <input type="search" id="editor-material-search" placeholder="搜尋材料">
      <button type="button" class="secondary" id="editor-material-search-button">{button_content('搜尋', 'filter')}</button>
    </div>
    <p class="muted">材料池：{len(available_records)} 筆（可用材料 {material_count} / 新聞小消息 {small_news_count}）</p>
    <div class="editor-search-results" data-material-results>
      <p class="muted">輸入關鍵字後按搜尋。</p>
    </div>
  </aside>
</section>

<section class="card">
  <h2>最近編輯歷程</h2>
  <div class="editor-session-list">{session_rows}</div>
</section>

<div class="loading-overlay" id="editor-loading">
  <div class="loading-card">
    <strong>編輯台執行中</strong>
    <p id="editor-loading-text">正在呼叫 CLI，材料若有翻譯全文會優先使用以省 token。</p>
    <div class="loading-dots"><span></span><span></span><span></span></div>
  </div>
</div>

<style>
  .editor-hero {{ margin-bottom:16px; }}
  .editor-hero h1 {{ display:flex; align-items:center; gap:8px; margin-bottom:6px; }}
  .editor-workbench {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(300px,380px); gap:16px; align-items:start; }}
  .editor-card, .editor-search-card {{ display:grid; gap:12px; }}
  .editor-control-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }}
  .editor-label {{ display:block; margin:12px 0; font-size:14px; }}
  .editor-label textarea, .editor-select, .editor-search-row input {{ width:100%; margin-top:6px; box-sizing:border-box; padding:8px; border-radius:8px; border:1px solid var(--border,#cbd5e1); font:inherit; }}
  .editor-hint {{ font-size:13px; color:var(--muted,#64748b); margin:8px 0 0; }}
  .editor-style-link {{ font-weight:400; font-size:12px; color:var(--muted,#64748b); }}
  .editor-draft-bin {{ min-height:220px; border:1px dashed var(--line); border-radius:8px; background:#fbfdfc; padding:10px; display:grid; align-content:start; gap:8px; transition:border-color .16s ease, background .16s ease; }}
  .editor-draft-bin.is-over {{ border-color:#1a8ca8; background:#eefcff; }}
  .editor-draft-empty {{ color:var(--muted); font-size:14px; padding:18px; text-align:center; }}
  .editor-draft-list {{ display:grid; gap:8px; }}
  .editor-material-card, .editor-draft-item {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fff; display:grid; gap:6px; }}
  .editor-material-card {{ cursor:grab; }}
  .editor-material-card:active {{ cursor:grabbing; }}
  .editor-material-title {{ font-weight:700; color:var(--ocf-dark); }}
  .editor-material-summary {{ color:var(--muted); font-size:13px; margin:0; }}
  .editor-material-meta, .editor-draft-meta {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
  .editor-kind-pill {{ font-weight:800; }}
  .editor-kind--material {{ background:#ece8ff; color:var(--ocf-primary); }}
  .editor-kind--small-news {{ background:#fff8db; color:#7a5a00; }}
  .editor-search-row {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:end; }}
  .editor-search-results {{ display:grid; gap:8px; max-height:62vh; overflow:auto; padding-right:2px; }}
  .editor-session-list {{ display:flex; flex-direction:column; gap:8px; }}
  .editor-session-row {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:10px 12px; border:1px solid var(--border,#e2e8f0); border-radius:10px; text-decoration:none; color:inherit; }}
  .editor-session-row:hover {{ background:var(--soft,#f1f5f9); }}
  .editor-session-titles {{ flex:1; min-width:160px; }}
  @media (max-width: 900px) {{
    .editor-workbench, .editor-control-grid {{ grid-template-columns:1fr; }}
    .editor-search-results {{ max-height:none; }}
  }}
</style>
{EDITOR_TIMELINE_ASSETS}
<script type="application/json" id="editor-available-materials">{available_json}</script>
<script type="application/json" id="editor-selected-materials">{selected_json}</script>
<script>
(function() {{
  var form = document.getElementById("editor-run-form");
  if (!form) return;
  var available = JSON.parse(document.getElementById("editor-available-materials").textContent || "[]");
  var selectedInput = form.querySelector("[data-selected-items]");
  var draftList = document.querySelector("[data-draft-list]");
  var draftEmpty = document.querySelector("[data-draft-empty]");
  var dropzone = document.querySelector("[data-editor-dropzone]");
  var results = document.querySelector("[data-material-results]");
  var searchInput = document.getElementById("editor-material-search");
  var searchButton = document.getElementById("editor-material-search-button");
  var selected = new Map();
  function materialBadges(item) {{
    var tags = [`<span class="tag-pill editor-kind-pill editor-kind--${{escapeHtml(item.type || "material")}}">${{escapeHtml(item.typeLabel || "可用材料")}}</span>`];
    tags.push(`<span class="tag-pill">${{escapeHtml(item.trackLabel || "未分類")}}</span>`);
    if (item.hasTranslation) tags.push('<span class="tag-pill">有翻譯全文</span>');
    (item.tags || []).slice(0, 3).forEach(function(tag) {{
      tags.push(`<span class="tag-pill">${{escapeHtml(tag)}}</span>`);
    }});
    return tags.join("");
  }}
  function escapeHtml(text) {{
    return String(text || "").replace(/[&<>"']/g, function(ch) {{
      return ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}})[ch];
    }});
  }}
  function addMaterial(item) {{
    if (!item || !item.id) return;
    selected.set(item.id, item);
    renderDraft();
  }}
  function removeMaterial(id) {{
    selected.delete(id);
    renderDraft();
  }}
  function renderDraft() {{
    var ids = Array.from(selected.keys());
    selectedInput.value = ids.join(",");
    draftEmpty.hidden = ids.length > 0;
    draftList.innerHTML = ids.map(function(id) {{
      var item = selected.get(id);
      return `<div class="editor-draft-item" data-draft-id="${{escapeHtml(id)}}">
        <div class="editor-material-title">${{escapeHtml(item.title)}}</div>
        <div class="editor-draft-meta"><code>${{escapeHtml(id)}}</code>${{materialBadges(item)}}</div>
        <div class="button-row">
          <a class="button button-small secondary" href="/items/view?id=${{encodeURIComponent(id)}}" target="_blank">打開材料</a>
          <button type="button" class="button button-small quiet" data-remove-draft="${{escapeHtml(id)}}">移除</button>
        </div>
      </div>`;
    }}).join("");
  }}
  function matches(item, query) {{
    if (!query) return true;
    var haystack = [item.id, item.title, item.summary, item.source, item.trackLabel].concat(item.tags || []).join(" ").toLowerCase();
    return haystack.indexOf(query.toLowerCase()) !== -1;
  }}
  function renderResults(force) {{
    var query = (searchInput.value || "").trim();
    if (!force && !query) return;
    var rows = available.filter(function(item) {{ return matches(item, query); }}).slice(0, 40);
    if (!rows.length) {{
      results.innerHTML = '<p class="muted">沒有找到符合的材料。</p>';
      return;
    }}
    results.innerHTML = rows.map(function(item) {{
      var added = selected.has(item.id);
      return `<article class="editor-material-card" draggable="true" data-material-id="${{escapeHtml(item.id)}}">
        <div class="editor-material-title">${{escapeHtml(item.title)}}</div>
        <p class="editor-material-summary">${{escapeHtml(item.summary || "沒有摘要。")}}</p>
        <div class="editor-material-meta"><code>${{escapeHtml(item.id)}}</code>${{materialBadges(item)}}</div>
        <div class="button-row">
          <button type="button" class="button button-small" data-add-material="${{escapeHtml(item.id)}}"${{added ? " disabled" : ""}}>${{added ? "已在草稿庫" : "加入草稿庫"}}</button>
          <a class="button button-small quiet" href="/items/view?id=${{encodeURIComponent(item.id)}}" target="_blank">打開</a>
        </div>
      </article>`;
    }}).join("");
  }}
  function findMaterial(id) {{
    return available.find(function(item) {{ return item.id === id; }}) || selected.get(id);
  }}
  JSON.parse(document.getElementById("editor-selected-materials").textContent || "[]").forEach(addMaterial);
  renderDraft();
  searchButton.addEventListener("click", function() {{ renderResults(true); }});
  searchInput.addEventListener("keydown", function(event) {{
    if (event.key === "Enter") {{
      event.preventDefault();
      renderResults(true);
    }}
  }});
  results.addEventListener("click", function(event) {{
    var btn = event.target.closest("[data-add-material]");
    if (!btn) return;
    addMaterial(findMaterial(btn.getAttribute("data-add-material")));
    renderResults(true);
  }});
  results.addEventListener("dragstart", function(event) {{
    var card = event.target.closest("[data-material-id]");
    if (!card) return;
    event.dataTransfer.setData("text/plain", card.getAttribute("data-material-id"));
    event.dataTransfer.effectAllowed = "copy";
  }});
  draftList.addEventListener("click", function(event) {{
    var btn = event.target.closest("[data-remove-draft]");
    if (!btn) return;
    removeMaterial(btn.getAttribute("data-remove-draft"));
    renderResults(true);
  }});
  dropzone.addEventListener("dragover", function(event) {{
    event.preventDefault();
    dropzone.classList.add("is-over");
  }});
  dropzone.addEventListener("dragleave", function() {{ dropzone.classList.remove("is-over"); }});
  dropzone.addEventListener("drop", function(event) {{
    event.preventDefault();
    dropzone.classList.remove("is-over");
    addMaterial(findMaterial(event.dataTransfer.getData("text/plain")));
    renderResults(true);
  }});
  var taskType = document.getElementById("editor-task-type");
  var hints = form.querySelectorAll("[data-task-hint]");
  function syncHints() {{
    hints.forEach(function(el) {{ el.hidden = (el.getAttribute("data-task-hint") !== taskType.value); }});
  }}
  if (taskType) taskType.addEventListener("change", syncHints);
  var statusEl = document.getElementById("editor-run-status");
  form.addEventListener("submit", function(event) {{
    event.preventDefault();
    var ids = (selectedInput.value || "").trim();
    if (!ids) {{ statusEl.textContent = "請先把至少一篇材料放進草稿庫。"; return; }}
    var engineSel = form.querySelector("[name=engine]");
    var engine = engineSel ? engineSel.value : "";
    if (!engine) {{ statusEl.textContent = "請選一個模型。"; return; }}
    if (!window.runEngineJob) {{ statusEl.textContent = "頁面尚未就緒，請重新整理。"; return; }}
    var taskLabel = (taskType && taskType.options[taskType.selectedIndex]) ? taskType.options[taskType.selectedIndex].text : "任務";
    var body = {{}};
    new FormData(form).forEach(function(value, key) {{ body[key] = value; }});
    statusEl.textContent = "已送出，請看右下角狀態。";
    window.runEngineJob({{
      label: "編輯台：" + taskLabel,
      url: "/editor/run",
      baseBody: body,
      engine: engine,
      onSuccess: function(payload) {{ if (payload && payload.redirect) window.location = payload.redirect; }}
    }});
  }});
}})();
</script>
"""
        self.send_html("編輯台", body)

    def run_editor_task(self, data: dict[str, list[str]]) -> None:
        engine = form_value(data, "engine", "claude")
        task_type = form_value(data, "task_type", "theme-check")
        choice = form_value(data, "choice")
        items_raw = form_value(data, "items")
        instructions = form_value(data, "instructions")
        writing_style = form_value(data, "writing_style")
        rerun_of = form_value(data, "rerun_of")
        viewpoint_ids = form_value(data, "viewpoint_ids")
        vp_explicit = form_value(data, "vp_explicit") == "1"
        toolbox_state = form_value(data, "toolbox_state")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"

        ids = [x for x in re.split(r"[\s,]+", items_raw) if x]
        engines = editor_engine_status()
        if engine not in set(AI_PROVIDER_ORDER) or not engines.get(engine):
            msg = f"引擎 {engine} 目前不可用。"
            if wants_json:
                self.send_json({"ok": False, "error": msg}, HTTPStatus.BAD_REQUEST)
            else:
                self.send_html("編輯台", f"<h1>{h(msg)}</h1><p><a href='/editor'>回編輯台</a></p>", HTTPStatus.BAD_REQUEST)
            return
        if not ids:
            msg = "請先把至少一篇材料放進草稿庫。"
            if wants_json:
                self.send_json({"ok": False, "error": msg}, HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/editor")
            return

        session_id = new_editor_id("sess")
        command = [
            sys.executable,
            str(ROOT / "scripts" / "editor_task.py"),
            "--engine", engine,
            "--task-type", task_type,
            "--items", ",".join(ids),
            "--session-id", session_id,
        ]
        if choice in {"thematic", "digest"}:
            command += ["--choice", choice]
        if instructions:
            command += ["--instructions", instructions]
        if writing_style and writing_style in writing_style_names():
            command += ["--writing-style", writing_style]
        if rerun_of:
            command += ["--rerun-of", rerun_of]
        if vp_explicit:
            command += ["--viewpoint-ids", viewpoint_ids, "--vp-explicit"]
        if toolbox_state:
            command += ["--toolbox-state", toolbox_state]
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=1800)
            ok = result.returncode == 0
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        except subprocess.TimeoutExpired as exc:
            ok = False
            output = (exc.stdout or "") + "\n編輯台任務逾時。"
        if not ok:
            print(output, file=sys.stderr)
        redirect_to = f"/editor/session?id={quote(session_id)}"
        if wants_json:
            if ok:
                self.send_json({"ok": True, "session_id": session_id, "redirect": redirect_to})
            else:
                tail = clean_text(output, 400)
                self.send_json({"ok": False, "error": f"執行失敗：{tail}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        else:
            self.redirect(redirect_to if ok else "/editor")

    def show_writing_styles(self, query: dict[str, list[str]]) -> None:
        cards = ""
        for style in load_writing_styles():
            path = WRITING_STYLES_DIR / f'{style["name"]}.md'
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) == 3:
                    text = parts[2].strip()
            desc = f'<p class="muted">{h(style["description"])}</p>' if style["description"] else ""
            cards += (
                '<section class="card">'
                f'<div class="section-kicker">{h(style["name"])}.md</div>'
                f'<h2>{h(style["title"])}</h2>{desc}'
                f'<div class="article-text article-markdown">{markdown_to_html(text)}</div>'
                "</section>"
            )
        if not cards:
            cards = '<p class="empty">還沒有風格檔。在 <code>knowledge/writing-styles/</code> 放 .md（frontmatter 設 name / description）即可。</p>'
        body = f"""
{back_nav_html(self.same_origin_referer_path("/editor"))}
<h1>撰文風格</h1>
<p class="lede">編輯台「撰文風格」下拉會列出這裡的每個 .md；選了之後，該風格內容會在撰稿時餵給 AI（在 CLAUDE.md 寫作守則之上加套）。檔案放在 <code>knowledge/writing-styles/</code>。</p>
{cards}
"""
        self.send_html("撰文風格", body)

    def show_editor_session(self, query: dict[str, list[str]]) -> None:
        session_id = clean_text((query.get("id") or [""])[0])
        editor_sessions = load_jsonl(EDITOR_SESSIONS)
        session = next((s for s in editor_sessions if clean_text(s.get("id")) == session_id), None)
        if not session:
            self.send_html("找不到", "<h1>找不到這次編輯紀錄</h1><p><a href='/editor'>回編輯台</a></p>", HTTPStatus.NOT_FOUND)
            return

        lookup = editor_item_lookup()
        material_rows = ""
        for item_id in session.get("item_ids") or []:
            rec = lookup.get(item_id)
            title = editor_item_title(rec) if rec else item_id
            tr = '<span class="tag-pill">用了翻譯全文</span>' if item_id in (session.get("used_translation") or []) else ""
            link = f'<a href="/items/view?id={quote(item_id)}">{h(title)}</a>' if rec else h(title)
            material_rows += f'<li>{link} <code>{h(item_id)}</code> {tr}</li>'

        output_html = markdown_to_html(clean_text(session.get("output_markdown")) or "（沒有輸出）")

        # factcheck 來源 → 一鍵走既有「手動入庫」流程（存進入庫建檔區）
        favorites_block = ""
        data = session.get("output_data") if isinstance(session.get("output_data"), dict) else {}
        sources = data.get("recommended_sources") if isinstance(data, dict) else None
        if sources:
            default_track = ""
            for item_id in session.get("item_ids") or []:
                rec = lookup.get(item_id)
                if rec and clean_text(rec.get("track")):
                    default_track = clean_text(rec.get("track"))
                    break
            rows = ""
            for src in sources:
                url = clean_text(src.get("url"))
                title = clean_text(src.get("title")) or url or "(未命名)"
                why = clean_text(src.get("why"))
                disabled = "" if url else " disabled"
                rows += (
                    '<form class="editor-fav-form" method="post" action="/items" data-async-collect>'
                    f'<input type="hidden" name="url" value="{h(url)}">'
                    f'<input type="hidden" name="title" value="{h(title)}">'
                    f'<input type="hidden" name="summary" value="{h(why)}">'
                    f'<input type="hidden" name="source_name" value="查證來源">'
                    f'<input type="hidden" name="track" value="{h(default_track or "unclassified")}">'
                    f'<input type="hidden" name="format" value="json">'
                    f'<span>{h(title)}</span>'
                    + (f' <a href="{h(url)}" target="_blank" rel="noopener">↗</a>' if url else "")
                    + f'<button type="submit" class="button button-small"{disabled}>+ 新增到入庫建檔區</button></form>'
                )
            favorites_block = (
                '<section class="card"><h2>推薦收藏材料</h2>'
                '<p class="muted">這裡只顯示編輯台過程中搜尋或查核長出的外部來源。按下後會送進入庫建檔區，後續照單篇材料審核流程處理。</p>'
                f'{rows}</section>'
            )

        vp_block = ""
        if session.get("suggested_viewpoint_id"):
            vp_block = (
                '<p class="muted">這次因為沒有相關觀點筆記，已自動記一筆待補觀點到 '
                '<a href="/editor/viewpoints">觀點庫</a>。</p>'
            )

        # 可加入觀點庫：把這次浮現的觀點一鍵串聯（自動帶上本次材料）
        related_csv = ",".join(clean_text(i) for i in (session.get("item_ids") or []))
        n_items = len(session.get("item_ids") or [])
        task_type = clean_text(session.get("task_type"))
        candidates: list[tuple[str, str]] = []
        if task_type == "theme-check":
            for angle in data.get("angle_suggestions") or []:
                text = clean_text(angle)
                if text:
                    candidates.append((text[:48], text))
            if clean_text(data.get("suggested_viewpoint_body")):
                candidates.append((clean_text(data.get("suggested_viewpoint_title"), 60) or "（待補觀點）",
                                   clean_text(data.get("suggested_viewpoint_body"))))
        elif task_type in {"extract-viewpoints", "newsletter-extract"}:
            for cand in data.get("viewpoint_candidates") or []:
                title_c = clean_text(cand.get("title"), 60)
                body_c = clean_text(cand.get("body"))
                if body_c:
                    candidates.append((title_c or body_c[:48], body_c))
        candidate_rows = ""
        for title_c, body_c in candidates:
            candidate_rows += (
                '<form class="editor-vp-candidate" method="post" action="/editor/viewpoints/save" data-async-viewpoint>'
                f'<input type="hidden" name="title" value="{h(title_c)}">'
                f'<input type="hidden" name="body" value="{h(body_c)}">'
                f'<input type="hidden" name="related_item_ids" value="{h(related_csv)}">'
                f'<span class="editor-vp-cand-title" title="{h(body_c)}">{h(title_c)}</span>'
                '<button type="submit" class="button button-small">+ 串聯加入觀點庫</button></form>'
            )
        extract_button = ""
        if task_type in {"compose-thematic", "compose-digest", "factcheck"} and related_csv:
            src_text = clean_text(session.get("output_markdown"), 6000)
            extract_button = (
                '<form class="editor-vp-extract" method="post" action="/editor/run" data-extract-viewpoints>'
                f'<input type="hidden" name="engine" value="{h(session.get("engine") or "claude")}">'
                '<input type="hidden" name="task_type" value="extract-viewpoints">'
                f'<input type="hidden" name="items" value="{h(related_csv)}">'
                f'<input type="hidden" name="instructions" value="{h(src_text)}">'
                '<input type="hidden" name="format" value="json">'
                '<button type="submit" class="button button-small">✨ 萃取可存觀點</button>'
                '<span class="muted editor-vp-extract-status"></span></form>'
            )
        viewpoint_panel = ""
        if related_csv:
            inner = ""
            if candidate_rows:
                inner += f'<div class="editor-vp-candidates">{candidate_rows}</div>'
            inner += f"""
  <form class="editor-vp-quickform" method="post" action="/editor/viewpoints/save" data-async-viewpoint>
    <input type="hidden" name="related_item_ids" value="{h(related_csv)}">
    <input type="text" name="title" placeholder="觀點標題（可留空）">
    <textarea name="body" rows="2" placeholder="把這次想到的立場寫下來，會自動串連本次 {n_items} 篇材料" required></textarea>
    <button type="submit" class="button button-small">加入觀點庫（連結本次 {n_items} 篇材料）</button>
  </form>"""
            viewpoint_panel = f"""
<section class="card">
  <h2>可加入觀點庫</h2>
  <p class="muted">把這次浮現的觀點一鍵存進觀點庫，會自動帶上本次的 {n_items} 篇材料（同一觀點可關聯多篇）。{('' if candidate_rows else '若想讓系統幫忙從這次內容抽出觀點，按下方「萃取可存觀點」。')}</p>
  {extract_button}
  {inner}
</section>"""

        choice_label = EDITOR_CHOICE_LABELS.get(session.get("choice"), "")
        meta = (
            f'<span class="tag-pill">{h(session.get("engine"))}</span>'
            f'<span class="tag-pill">{h(session.get("model") or "")}</span>'
            + (f'<span class="tag-pill">{h(choice_label)}</span>' if choice_label else "")
            + f'<span class="muted">{h(editor_relative_time(session.get("created_at")))}</span>'
        )
        engines = editor_engine_status()

        def toolbox_engine_option(name: str, label: str) -> str:
            available = engines.get(name)
            disabled = "" if available else " disabled"
            suffix = "" if available else "（未安裝）"
            return f'<option value="{name}"{disabled}>{h(label + suffix)}</option>'

        # C8：沿生產線建議下一步（compose-* 與 newsletter-extract 不建議）
        suggested_next = next_pipeline_task(task_type)
        toolbox_default_task = suggested_next or task_type
        if suggested_next:
            next_hint = (
                f'<p class="editor-hint editor-next-hint">建議下一步：<strong>{h(EDITOR_TASK_LABELS.get(suggested_next, suggested_next))}</strong>　'
                f'{h(EDITOR_TASK_HINTS.get(suggested_next, ""))}</p>'
            )
        elif task_type in {"compose-thematic", "compose-digest"}:
            next_hint = '<p class="editor-hint editor-next-hint">這篇已到「撰稿」生產線末端（彙報式／主題式二選一）。需要的話可回頭做查核或萃取觀點。</p>'
        elif task_type == "newsletter-extract":
            next_hint = '<p class="editor-hint editor-next-hint">彙整萃取報告外於撰稿生產線，沒有建議的下一步。</p>'
        else:
            next_hint = ""
        toolbox_task_options = editor_task_options_html(toolbox_default_task)
        toolbox_hints = "".join(
            f'<p data-toolbox-hint="{h(k)}" class="editor-hint"{"" if k == toolbox_default_task else " hidden"}>{h(v)}</p>'
            for k, v in EDITOR_TASK_HINTS.items()
        )
        # C6 + 記憶：材料與觀點都可「取消勾選、↑↓、:: 拖曳」排序；上一輪的勾選與順序
        # 記在 session.toolbox_state，這一輪原樣帶回來（含沒選的列出但不勾）。
        grip_btn = (
            '<button type="button" class="toolbox-grip" draggable="true" data-drag-handle '
            'title="拖曳排序" aria-label="拖曳排序">' + ("<span></span>" * 6) + "</button>"
        )
        move_btns = (
            '<span class="toolbox-move">'
            '<button type="button" class="button button-small quiet" data-move-row="up" aria-label="上移">↑</button>'
            '<button type="button" class="button button-small quiet" data-move-row="down" aria-label="下移">↓</button>'
            "</span>"
        )

        def toolbox_row(box_class: str, rid: str, title: str, body: str, checked: bool) -> str:
            title_attr = f' title="{h(body)}"' if body else ""
            chk = " checked" if checked else ""
            return (
                f'<div class="toolbox-mat" data-id="{h(rid)}" data-title="{h(title)}">{grip_btn}{move_btns}'
                f'<label><input type="checkbox" class="{box_class}" value="{h(rid)}"{chk}> '
                f"<span{title_attr}>{h(title)}</span></label></div>"
            )

        state = session.get("toolbox_state") if isinstance(session.get("toolbox_state"), dict) else {}
        session_item_ids = [clean_text(i) for i in (session.get("item_ids") or []) if clean_text(i)]
        session_titles = session.get("item_titles") or []
        _seen_session_ids = set(session_item_ids)
        _all_vps = load_jsonl(VIEWPOINTS)
        vp_lookup = {clean_text(v.get("id")): v for v in _all_vps}
        _suggested_vp = clean_text(session.get("suggested_viewpoint_id"))
        relevant_vp_ids = [
            clean_text(v.get("id"))
            for v in _all_vps
            if ({clean_text(x) for x in (v.get("related_item_ids") or [])} & _seen_session_ids)
            or clean_text(v.get("id")) == _suggested_vp
        ]

        # 材料 entries：優先 toolbox_state（含沒選的＋順序），否則 session.item_ids（全選）
        mat_entries = []  # (id, title, checked)
        if isinstance(state.get("materials"), list) and state["materials"]:
            for m in state["materials"]:
                mid = clean_text(m.get("id"))
                if mid:
                    mat_entries.append((mid, clean_text(m.get("title")) or mid, bool(m.get("checked", True))))
        else:
            for idx, mid in enumerate(session_item_ids):
                title = clean_text(session_titles[idx]) if idx < len(session_titles) else mid
                mat_entries.append((mid, title, True))
        toolbox_mat_rows = "".join(toolbox_row("toolbox-mat-box", mid, t, "", c) for mid, t, c in mat_entries)
        if not toolbox_mat_rows:
            toolbox_mat_rows = '<p class="muted">這個 session 沒有記錄材料；用下方搜尋加入。</p>'

        # 觀點 entries：優先 toolbox_state；否則 session.viewpoint_ids（選取＋順序）＋其餘相關觀點不勾
        vp_entries = []  # (id, title, body, checked)
        used_vids: set[str] = set()
        if isinstance(state.get("viewpoints"), list) and state["viewpoints"]:
            for v in state["viewpoints"]:
                vid = clean_text(v.get("id"))
                if not vid or vid in used_vids:
                    continue
                used_vids.add(vid)
                vp = vp_lookup.get(vid, {})
                title = clean_text(v.get("title")) or clean_text(vp.get("title")) or vid
                vp_entries.append((vid, title, clean_text(vp.get("body"), 240), bool(v.get("checked", True))))
        else:
            selected_vids = [clean_text(x) for x in (session.get("viewpoint_ids") or []) if clean_text(x)]
            default_checked = not selected_vids  # 舊 session 沒存過 → 全選
            for vid in selected_vids:
                if vid in used_vids:
                    continue
                used_vids.add(vid)
                vp = vp_lookup.get(vid, {})
                vp_entries.append((vid, clean_text(vp.get("title")) or vid, clean_text(vp.get("body"), 240), True))
            for vid in relevant_vp_ids:
                if vid in used_vids:
                    continue
                used_vids.add(vid)
                vp = vp_lookup.get(vid, {})
                vp_entries.append((vid, clean_text(vp.get("title")) or vid, clean_text(vp.get("body"), 240), default_checked))
        # 補上 state 未涵蓋、但現在相關的新觀點（列出、不勾）
        if state.get("viewpoints"):
            for vid in relevant_vp_ids:
                if vid in used_vids:
                    continue
                used_vids.add(vid)
                vp = vp_lookup.get(vid, {})
                vp_entries.append((vid, clean_text(vp.get("title")) or vid, clean_text(vp.get("body"), 240), False))
        toolbox_vp_rows = "".join(toolbox_row("toolbox-vp-box", vid, t, b, c) for vid, t, b, c in vp_entries)
        if not toolbox_vp_rows:
            toolbox_vp_rows = '<p class="muted">這組材料目前沒有相關觀點。可在下方「可加入觀點庫」先建立。</p>'

        toolbox_mat_pool = [
            {"id": clean_text(r.get("id")), "title": editor_item_title(r)}
            for r in load_jsonl(ITEMS)
            if is_skill_candidate(r) and clean_text(r.get("id")) not in {e[0] for e in mat_entries}
        ]
        toolbox_mat_pool_json = json.dumps(toolbox_mat_pool[:400], ensure_ascii=False).replace("<", "\\u003c")
        toolbox_panel = f"""
<details class="card editor-session-toolbox" open>
  <summary><h2>工具箱</h2><span class="help-dot" title="用同一組材料改跑其他寫法、其他任務，或換另一個 AI。可取消勾選排除材料、搜尋加入新材料。">?</span></summary>
  {next_hint}
  <form method="post" action="/editor/run" class="editor-session-toolbox-form" data-toolbox-form>
    <input type="hidden" name="items" value="{h(related_csv)}">
    <input type="hidden" name="rerun_of" value="{h(session_id)}">
    <div class="editor-control-grid">
      <label class="editor-label">模型
        <select name="engine" class="editor-select"><option value="random" selected>隨機（失敗自動換其他可用 CLI）</option>{''.join(toolbox_engine_option(provider, AI_PROVIDER_META[provider]['label']) for provider in AI_PROVIDER_ORDER)}</select>
      </label>
      <label class="editor-label">任務
        <select name="task_type" class="editor-select" data-toolbox-task>{toolbox_task_options}</select>
      </label>
      <label class="editor-label">寫文模式
        <select name="choice" class="editor-select">
          <option value="thematic"{' selected' if session.get('choice') == 'thematic' else ''}>主題式</option>
          <option value="digest"{' selected' if session.get('choice') == 'digest' else ''}>彙報式</option>
        </select>
      </label>
    </div>
    {toolbox_hints}
    <label class="editor-label">撰文風格 <a class="editor-style-link" href="/writing-styles" target="_blank">（管理 / 看風格檔）</a>
      <select name="writing_style" class="editor-select">{writing_style_options_html(clean_text(session.get("writing_style")))}</select>
    </label>
    <div class="editor-label">材料（取消勾選＝這次不用；↑↓ 排順序＝撰稿取材順序；搜尋可加入）</div>
    <div class="toolbox-materials" id="toolbox-materials">{toolbox_mat_rows}</div>
    <div class="article-search-row"><input type="search" id="toolbox-mat-search" placeholder="搜尋可用材料標題加入這次"></div>
    <div class="toolbox-mat-results" id="toolbox-mat-results"></div>
    <div class="editor-label">觀點（取消勾選＝這次不帶；↑↓ 排順序＝撰稿時觀點段落順序）</div>
    <input type="hidden" name="vp_explicit" value="1">
    <input type="hidden" name="viewpoint_ids" value="">
    <input type="hidden" name="toolbox_state" value="">
    <div class="toolbox-materials" id="toolbox-viewpoints">{toolbox_vp_rows}</div>
    <label class="editor-label">這次額外指示
      <textarea name="instructions" rows="2" placeholder="例如：換成較短的彙報式，或改用另一個觀點切入"></textarea>
    </label>
    <button type="submit" class="button">{button_content('用這組材料再跑一次', 'wand')}</button>
  </form>
</details>
<script>
(function() {{
  var form = document.querySelector('[data-toolbox-form]');
  if (!form) return;
  var itemsHidden = form.querySelector('input[name=items]');
  var vpHidden = form.querySelector('input[name=viewpoint_ids]');
  var stateHidden = form.querySelector('input[name=toolbox_state]');
  var matWrap = document.getElementById('toolbox-materials');
  var vpWrap = document.getElementById('toolbox-viewpoints');
  function rowsOf(wrap) {{ return wrap ? Array.prototype.slice.call(wrap.querySelectorAll('.toolbox-mat')) : []; }}
  function checkedIds(wrap, boxClass) {{
    return Array.prototype.slice.call(wrap.querySelectorAll('.' + boxClass))
      .filter(function(b) {{ return b.checked; }}).map(function(b) {{ return b.value; }});
  }}
  function stateOf(wrap, boxClass) {{
    return rowsOf(wrap).map(function(row) {{
      var box = row.querySelector('.' + boxClass);
      return {{ id: row.getAttribute('data-id') || (box ? box.value : ''), title: row.getAttribute('data-title') || '', checked: box ? box.checked : false }};
    }});
  }}
  function sync() {{
    if (matWrap && itemsHidden) itemsHidden.value = checkedIds(matWrap, 'toolbox-mat-box').join(',');
    if (vpWrap && vpHidden) vpHidden.value = checkedIds(vpWrap, 'toolbox-vp-box').join(',');
    if (stateHidden) stateHidden.value = JSON.stringify({{ materials: stateOf(matWrap, 'toolbox-mat-box'), viewpoints: stateOf(vpWrap, 'toolbox-vp-box') }});
  }}
  if (matWrap) matWrap.addEventListener('change', sync);
  if (vpWrap) vpWrap.addEventListener('change', sync);
  // ↑↓ 重排
  form.addEventListener('click', function(e) {{
    var mv = e.target.closest('[data-move-row]'); if (!mv) return;
    e.preventDefault();
    var row = mv.closest('.toolbox-mat'); if (!row) return;
    var wrap = row.parentNode;
    if (mv.getAttribute('data-move-row') === 'up') {{ if (row.previousElementSibling) wrap.insertBefore(row, row.previousElementSibling); }}
    else if (row.nextElementSibling) {{ wrap.insertBefore(row.nextElementSibling, row); }}
    sync();
  }});
  // :: 拖曳重排（grip 為 draggable，容器內排序，像 RSS 管理）
  var dragRow = null;
  function afterElement(wrap, y) {{
    var els = Array.prototype.slice.call(wrap.querySelectorAll('.toolbox-mat:not(.is-dragging)'));
    var best = null, bestOffset = -Infinity;
    els.forEach(function(child) {{
      var box = child.getBoundingClientRect();
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > bestOffset) {{ bestOffset = offset; best = child; }}
    }});
    return best;
  }}
  form.addEventListener('dragstart', function(e) {{
    var handle = e.target.closest('[data-drag-handle]'); if (!handle) return;
    dragRow = handle.closest('.toolbox-mat'); if (!dragRow) return;
    dragRow.classList.add('is-dragging');
    e.dataTransfer.effectAllowed = 'move';
    try {{ e.dataTransfer.setData('text/plain', dragRow.getAttribute('data-id') || ''); }} catch (_e) {{}}
  }});
  [matWrap, vpWrap].forEach(function(wrap) {{
    if (!wrap) return;
    wrap.addEventListener('dragover', function(e) {{
      if (!dragRow || dragRow.parentNode !== wrap) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'move';
      var after = afterElement(wrap, e.clientY);
      if (after == null) wrap.appendChild(dragRow); else wrap.insertBefore(dragRow, after);
    }});
  }});
  form.addEventListener('dragend', function() {{ if (dragRow) {{ dragRow.classList.remove('is-dragging'); dragRow = null; sync(); }} }});
  sync();
  var taskSel = form.querySelector('[data-toolbox-task]');
  if (taskSel) taskSel.addEventListener('change', function() {{
    form.querySelectorAll('[data-toolbox-hint]').forEach(function(p) {{ p.hidden = p.getAttribute('data-toolbox-hint') !== taskSel.value; }});
  }});
  function esc(s) {{ return (s || '').replace(/[&<>\"]/g, function(c) {{ return {{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]; }}); }}
  var gripBtn = '<button type="button" class="toolbox-grip" draggable="true" data-drag-handle title="拖曳排序" aria-label="拖曳排序"><span></span><span></span><span></span><span></span><span></span><span></span></button>';
  var moveBtns = '<span class="toolbox-move"><button type="button" class="button button-small quiet" data-move-row="up" aria-label="上移">↑</button><button type="button" class="button button-small quiet" data-move-row="down" aria-label="下移">↓</button></span>';
  var pool = {toolbox_mat_pool_json};
  var search = document.getElementById('toolbox-mat-search');
  var results = document.getElementById('toolbox-mat-results');
  function present(id) {{ return Array.prototype.some.call(matWrap.querySelectorAll('.toolbox-mat-box'), function(b) {{ return b.value === id; }}); }}
  if (search) search.addEventListener('input', function() {{
    var q = search.value.trim().toLowerCase();
    if (!q) {{ results.innerHTML = ''; return; }}
    var hits = pool.filter(function(m) {{ return !present(m.id) && (m.title || '').toLowerCase().indexOf(q) !== -1; }}).slice(0, 12);
    results.innerHTML = hits.length
      ? hits.map(function(m) {{ return '<button type="button" class="button button-small quiet" data-add-mat="' + esc(m.id) + '">+ ' + esc(m.title) + '</button>'; }}).join('')
      : '<span class="muted">沒有符合的可用材料</span>';
  }});
  if (results) results.addEventListener('click', function(e) {{
    var btn = e.target.closest('[data-add-mat]'); if (!btn) return;
    var id = btn.getAttribute('data-add-mat');
    var m = pool.filter(function(x) {{ return x.id === id; }})[0]; if (!m) return;
    var row = document.createElement('div'); row.className = 'toolbox-mat';
    row.setAttribute('data-id', id); row.setAttribute('data-title', m.title || '');
    row.innerHTML = gripBtn + moveBtns + '<label><input type="checkbox" class="toolbox-mat-box" value="' + esc(id) + '" checked> <span>' + esc(m.title) + '</span></label>';
    matWrap.appendChild(row); sync(); search.value = ''; results.innerHTML = '';
  }});
}})();
</script>
"""

        current_ids = {clean_text(item_id) for item_id in (session.get("item_ids") or []) if clean_text(item_id)}
        current_key = tuple(sorted(current_ids))

        def session_key(entry: dict) -> tuple[str, ...]:
            return tuple(sorted(clean_text(item_id) for item_id in (entry.get("item_ids") or []) if clean_text(item_id)))

        related_exact = [
            entry
            for entry in reversed(editor_sessions)
            if clean_text(entry.get("id")) != session_id and session_key(entry) == current_key
        ]
        related_overlap = [
            entry
            for entry in reversed(editor_sessions)
            if clean_text(entry.get("id")) != session_id
            and session_key(entry) != current_key
            and current_ids.intersection(session_key(entry))
        ]
        related_entries = related_exact or related_overlap[:8]

        def related_session_row(entry: dict) -> str:
            titles = "、".join(h(t) for t in (entry.get("item_titles") or [])[:3])
            extra = "..." if len(entry.get("item_titles") or []) > 3 else ""
            relation = "同組合" if session_key(entry) == current_key else "相關材料"
            choice = EDITOR_CHOICE_LABELS.get(entry.get("choice"), "")
            return (
                '<a class="editor-session-row" href="/editor/session?id=' + quote(clean_text(entry.get("id"))) + '">'
                f'<strong>{h(entry.get("task_label") or entry.get("task_type"))}</strong>'
                f'<span class="tag-pill">{h(relation)}</span>'
                f'<span class="tag-pill">{h(entry.get("engine"))}</span>'
                + (f'<span class="tag-pill">{h(choice)}</span>' if choice else "")
                + f'<span class="editor-session-titles">{titles}{extra}</span>'
                f'<span class="muted">{h(editor_relative_time(entry.get("created_at")))}</span>'
                "</a>"
            )

        related_history = editor_timeline_html(
            related_entries,
            related_session_row,
            empty_html='<p class="muted">目前還沒有同組合的其他編輯紀錄。</p>',
            initial_count=6,
            batch_size=6,
            class_name="editor-session-related-timeline",
        )
        related_panel = f"""
<section class="card">
  <h2>相關編輯台紀錄</h2>
  <div class="editor-session-list">{related_history}</div>
</section>
"""

        # 下一步：把這次產出送進編修台，存成專文
        session_articles = [a for a in load_articles() if clean_text(a.get("source_session_id")) == session_id]
        article_panel = ""
        if clean_text(session.get("output_markdown")):
            existing_rows = ""
            for art in session_articles:
                status_label = ARTICLE_STATUS_LABELS.get(clean_text(art.get("status")), clean_text(art.get("status")))
                existing_rows += (
                    f'<a class="editor-session-row" href="/articles/edit?id={quote(clean_text(art.get("id")))}">'
                    f'<strong>{h(art.get("title"))}</strong>'
                    f'<span class="tag-pill">{h(status_label)}</span></a>'
                )
            existing_block = f'<p class="muted">已編修成專文：</p><div class="editor-session-list">{existing_rows}</div>' if existing_rows else ""
            cta_label = "再開一篇專文" if session_articles else "編修成專文"
            article_panel = f"""
<section class="card">
  <h2>專文（編修台）</h2>
  <p class="help">把這次產出的稿件送進編修台，用直覺編輯器順稿、對照事實查核守則，最後存成可發布的專文。</p>
  {existing_block}
  <form method="post" action="/articles/create-from-session">
    <input type="hidden" name="session" value="{h(session_id)}">
    <button type="submit" class="button">{button_content(cta_label, 'edit')}</button>
  </form>
</section>
"""
        # B3：本次額外指示／風格，沿 rerun_of 串成歷程（同一條工作鏈看得到下過哪些 prompt）
        _sessions_by_id = {clean_text(s.get("id")): s for s in editor_sessions}
        instruction_trail = []
        _cur = session
        _seen_trail: set[str] = set()
        while _cur and clean_text(_cur.get("id")) not in _seen_trail:
            _seen_trail.add(clean_text(_cur.get("id")))
            _instr = clean_text(_cur.get("instructions"))
            _style = clean_text(_cur.get("writing_style"))
            if _instr or _style:
                instruction_trail.append((_cur, _instr, _style))
            _cur = _sessions_by_id.get(clean_text(_cur.get("rerun_of")))
        instructions_panel = ""
        if instruction_trail:
            trail_rows = ""
            for idx, (s, instr, style) in enumerate(instruction_trail):
                tag = "本次" if idx == 0 else editor_relative_time(s.get("created_at"))
                style_pill = f'<span class="tag-pill">風格：{h(style)}</span>' if style else ""
                instr_html = f"<p>{h(instr)}</p>" if instr else '<p class="muted">（這步沒有額外指示，只套了風格）</p>'
                trail_rows += (
                    f'<li><strong>{h(tag)}</strong> '
                    f'<span class="tag-pill">{h(s.get("task_label") or s.get("task_type"))}</span>{style_pill}{instr_html}</li>'
                )
            instructions_panel = (
                '<section class="card"><h2>額外指示歷程 '
                '<span class="help-dot" title="沿著「用這組材料再跑一次」往回追，看得到這條工作鏈當初下過哪些額外指示與撰文風格。">?</span></h2>'
                f'<ul class="editor-instruction-trail">{trail_rows}</ul></section>'
            )

        body = f"""
{back_nav_html(self.same_origin_referer_path("/editor"))}
<section class="card">
  <div class="section-kicker">編輯歷程</div>
  <h1>{h(session.get("task_label") or session.get("task_type"))}</h1>
  <p>{meta}</p>
  {vp_block}
  <h2>材料</h2>
  <ul>{material_rows or '<li class="muted">（無）</li>'}</ul>
</section>
{instructions_panel}
{toolbox_panel}
<section class="card editor-output">{output_html}</section>
{article_panel}
{viewpoint_panel}
{favorites_block}
{related_panel}
<style>
  .editor-session-toolbox summary {{ cursor:pointer; display:flex; align-items:center; gap:8px; }}
  .editor-session-toolbox summary h2 {{ display:inline; margin:0; }}
  .editor-session-toolbox-form .editor-label {{ display:block; margin:0 0 10px; font-weight:600; }}
  /* 再跑工具箱對齊首頁：三欄排版（B9） */
  .editor-session-toolbox-form .editor-control-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }}
  .editor-session-toolbox-form .editor-control-grid select {{ max-width:none; }}
  .editor-next-hint {{ margin:0 0 10px; padding:8px 10px; border-radius:8px; background:var(--soft,#eef6ff); color:var(--ocf-dark,#14304a); }}
  .editor-style-link {{ font-weight:400; font-size:12px; color:var(--muted,#64748b); }}
  .editor-instruction-trail {{ margin:6px 0 0; padding-left:18px; }}
  .editor-instruction-trail li {{ margin:8px 0; }}
  .editor-instruction-trail p {{ margin:4px 0 0; }}
  .toolbox-materials {{ display:grid; gap:4px; max-height:32vh; overflow:auto; margin:4px 0 8px; padding-right:2px; }}
  .toolbox-mat {{ display:flex; gap:8px; align-items:center; font-size:13px; padding:4px 8px; border:1px solid var(--border,#e2e8f0); border-radius:8px; background:#fff; }}
  .toolbox-mat label {{ display:flex; gap:6px; align-items:baseline; min-width:0; flex:1 1 auto; cursor:pointer; margin:0; font-weight:400; }}
  .toolbox-mat span {{ min-width:0; word-break:break-word; }}
  .toolbox-move {{ display:inline-flex; gap:2px; flex:0 0 auto; }}
  .toolbox-move button {{ margin:0; padding:2px 7px; min-width:0; line-height:1.1; }}
  .toolbox-grip {{ display:grid; grid-template-columns:repeat(2,4px); grid-auto-rows:4px; gap:3px; align-content:center; justify-content:center; width:22px; height:26px; padding:4px; margin:0; border:1px solid transparent; border-radius:6px; background:transparent; color:var(--muted,#64748b); cursor:grab; flex:0 0 auto; box-shadow:none; }}
  .toolbox-grip span {{ width:4px; height:4px; border-radius:999px; background:currentColor; }}
  .toolbox-grip:hover {{ background:var(--soft,#eef6ff); color:var(--ocf-primary,#6450dc); box-shadow:none; transform:none; }}
  .toolbox-grip:active {{ cursor:grabbing; }}
  .toolbox-mat.is-dragging {{ opacity:.5; }}
  .toolbox-mat-results {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }}
  .editor-toolbox-grid {{ display:flex; flex-direction:column; gap:0; }}
  .editor-vp-candidates {{ display:flex; flex-direction:column; gap:8px; margin:8px 0; }}
  .editor-vp-candidate {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:8px 10px; border:1px solid var(--border,#e2e8f0); border-radius:10px; }}
  .editor-vp-candidate span {{ flex:1; min-width:160px; }}
  .editor-vp-cand-title {{ font-weight:600; }}
  .editor-vp-quickform, .editor-session-toolbox-form {{ margin-top:10px; }}
  .editor-vp-quickform input, .editor-vp-quickform textarea, .editor-session-toolbox-form textarea, .editor-session-toolbox-form select {{ width:100%; max-width:560px; box-sizing:border-box; padding:8px; border-radius:8px; border:1px solid var(--border,#cbd5e1); font:inherit; margin-bottom:6px; }}
  .editor-vp-extract {{ display:flex; align-items:center; gap:8px; margin-bottom:10px; }}
  @media (max-width: 900px) {{ .editor-toolbox-grid {{ grid-template-columns:1fr; }} .editor-session-toolbox-form .editor-control-grid {{ grid-template-columns:1fr; }} }}
</style>
<script>
document.querySelectorAll("form[data-async-collect]").forEach(function(form) {{
  form.addEventListener("submit", async function(event) {{
    event.preventDefault();
    var btn = form.querySelector("button");
    if (btn) btn.disabled = true;
    try {{
      var res = await fetch(form.action, {{ method: "POST", headers: {{ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With": "local-web-fetch" }}, body: new URLSearchParams(new FormData(form)) }});
      var payload = await res.json();
      if (btn) btn.textContent = payload.duplicate ? "已在入庫建檔區" : "已送入庫建檔";
    }} catch (err) {{
      if (btn) {{ btn.textContent = "失敗，再試"; btn.disabled = false; }}
    }}
  }});
}});
document.querySelectorAll("form[data-async-viewpoint]").forEach(function(form) {{
  form.addEventListener("submit", async function(event) {{
    event.preventDefault();
    var btn = form.querySelector("button");
    if (form.querySelector("[name=body]") && !form.querySelector("[name=body]").value.trim()) return;
    if (btn) btn.disabled = true;
    try {{
      var res = await fetch(form.action, {{ method: "POST", headers: {{ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Requested-With": "local-web-fetch" }}, body: new URLSearchParams(new FormData(form)) }});
      await res.json();
      if (btn) btn.textContent = "✓ 已加入觀點庫";
    }} catch (err) {{
      if (btn) {{ btn.textContent = "失敗，再試"; btn.disabled = false; }}
    }}
  }});
}});
function editorFormBody(form) {{
  var body = {{}};
  new FormData(form).forEach(function(value, key) {{ body[key] = value; }});
  return body;
}}
document.querySelectorAll("form[data-toolbox-form]").forEach(function(form) {{
  form.addEventListener("submit", function(event) {{
    event.preventDefault();
    if (!window.runEngineJob) return;
    var sel = form.querySelector("[name=engine]");
    var engine = sel ? sel.value : "random";
    var taskSel = form.querySelector("[name=task_type]");
    var taskLabel = (taskSel && taskSel.options[taskSel.selectedIndex]) ? taskSel.options[taskSel.selectedIndex].text : "任務";
    window.runEngineJob({{
      label: "編輯台再跑：" + taskLabel,
      url: "/editor/run",
      baseBody: editorFormBody(form),
      engine: engine,
      onSuccess: function(payload) {{ if (payload && payload.redirect) window.location = payload.redirect; }}
    }});
  }});
}});
document.querySelectorAll("form[data-extract-viewpoints]").forEach(function(form) {{
  form.addEventListener("submit", function(event) {{
    event.preventDefault();
    if (!window.runEngineJob) return;
    var sel = form.querySelector("[name=engine]");
    var engine = sel ? sel.value : "claude";
    var status = form.querySelector(".editor-vp-extract-status");
    if (status) status.textContent = "已送出，請看右下角狀態。";
    window.runEngineJob({{
      label: "萃取可存觀點",
      url: "/editor/run",
      baseBody: editorFormBody(form),
      engine: engine,
      onSuccess: function(payload) {{ if (payload && payload.redirect) window.location = payload.redirect; }}
    }});
  }});
}});
</script>
"""
        self.send_html(clean_text(session.get("task_label")) or "編輯紀錄", body)

    def show_viewpoints(self, query: dict[str, list[str]]) -> None:
        all_items = load_jsonl(ITEMS)
        item_lookup = {clean_text(item.get("id")): item for item in all_items}
        links_by_item = material_article_links_by_item()
        searchable_items = editor_search_items()
        viewpoint_materials = [editor_material_payload(record) for record in searchable_items[:350]]
        viewpoint_material_json = json.dumps(viewpoint_materials, ensure_ascii=False).replace("<", "\\u003c")
        available_notes = []
        for item in searchable_items:
            note = personal_note_text(item)
            if not note:
                continue
            item_id = clean_text(item.get("id"))
            type_key, type_label = editor_item_pool_type(item)
            articles = links_by_item.get(item_id) or []
            article_links = "".join(f'<li>{article_link_html(link)}</li>' for link in articles)
            note_html = f"""
<article class="card editor-vp editor-vp--material">
  <p><span class="tag-pill editor-kind-pill editor-kind--{h(type_key)}">{h(type_label)}</span> {badge("材料觀點", "neutral")} {badge(track_meta(item.get("track", "unclassified"))["short"], track_class(item.get("track", "unclassified")))} <span class="muted">{h(editor_relative_time((item.get("personal_notes") or {}).get("updated_at") if isinstance(item.get("personal_notes"), dict) else ""))}</span></p>
  <h3><a href="/items/view?id={quote(item_id)}">{h(editor_item_title(item))}</a></h3>
  <p>{h(note)}</p>
  {tag_chips_html(item_visible_tags(item, 6))}
  {f'<details><summary>相關 article</summary><ul>{article_links}</ul></details>' if article_links else ''}
</article>"""
            note_time = clean_text((item.get("personal_notes") or {}).get("updated_at") if isinstance(item.get("personal_notes"), dict) else "")
            available_notes.append({"_timeline_at": note_time or item_sort_time(item), "_html": note_html})
        material_note_rows = editor_timeline_html(
            available_notes,
            lambda entry: entry["_html"],
            empty_html='<div class="card"><strong>目前材料還沒有個人觀點</strong><p class="muted">到單篇頁的「我的關鍵紀錄」寫下判斷後，這裡會以觀點為主重新呈現。</p></div>',
            initial_count=8,
            batch_size=8,
            class_name="editor-vp-material-timeline",
        )

        viewpoints = list(reversed(load_jsonl(VIEWPOINTS)))
        articles_for_vp = load_articles()
        viewpoint_entries = []
        for vp in viewpoints:
            vp_id = clean_text(vp.get("id"))
            tags = "".join(f'<span class="tag-pill">{h(t)}</span>' for t in (vp.get("tags") or []))
            source = clean_text(vp.get("source"))
            badge_text = "待補" if source == "suggested" else "自寫"
            related_ids = [clean_text(item_id) for item_id in (vp.get("related_item_ids") or []) if clean_text(item_id)]
            cite_articles = articles_with_viewpoint(vp_id, articles_for_vp)
            cite_rows = "".join(
                f'<li><a href="/articles/view?id={quote(clean_text(a.get("id")))}">{h(a.get("title"))}</a></li>'
                for a in cite_articles
            )
            related_rows = ""
            article_rows = ""
            for related_id in related_ids:
                item = item_lookup.get(related_id)
                if item:
                    type_key, type_label = editor_item_pool_type(item)
                    related_rows += f'<li><span class="tag-pill editor-kind-pill editor-kind--{h(type_key)}">{h(type_label)}</span> <a href="/items/view?id={quote(related_id)}">{h(editor_item_title(item))}</a> <code>{h(related_id)}</code></li>'
                else:
                    related_rows += f'<li><code>{h(related_id)}</code></li>'
                for link in links_by_item.get(related_id) or []:
                    article_rows += f'<li>{article_link_html(link)}</li>'
            vp_html = f"""
<article class="card editor-vp" id="vp-card-{h(vp_id)}">
  <p>{badge(badge_text, "neutral")}{tags} <span class="muted">{h(editor_relative_time(vp.get("updated_at") or vp.get("created_at")))}</span></p>
  <h3>{h(vp.get("title") or "（未命名觀點）")}</h3>
  <p>{h(vp.get("body"))}</p>
  {f'<details open><summary>關聯材料</summary><ul>{related_rows}</ul></details>' if related_rows else '<p class="help">這條觀點還沒有關聯材料；建議之後補上材料關聯，選法檢查才知道它從哪裡來。</p>'}
  {f'<details><summary>相關 article</summary><ul>{article_rows}</ul></details>' if article_rows else ''}
  {f'<details open><summary>被專文引用（{len(cite_articles)}）</summary><ul>{cite_rows}</ul></details>' if cite_rows else ''}
  <form method="post" action="/editor/viewpoints/delete" onsubmit="return confirm('刪除這條觀點？');">
    <input type="hidden" name="id" value="{h(vp.get("id"))}">
    <button type="submit" class="button button-small">刪除</button>
  </form>
</article>"""
            viewpoint_entries.append({"_timeline_at": vp.get("updated_at") or vp.get("created_at"), "_html": vp_html})
        rows = editor_timeline_html(
            viewpoint_entries,
            lambda entry: entry["_html"],
            empty_html='<div class="card"><strong>還沒有編輯台觀點</strong><p class="muted">選法檢查如果發現缺少可延伸的立場，會自動在這裡留下待補觀點。</p></div>',
            initial_count=8,
            batch_size=8,
            class_name="editor-vp-timeline",
        )
        viewpoint_tag_options: list[str] = []
        viewpoint_tag_seen: set[str] = set()
        for vp in viewpoints:
            for tag in vp.get("tags") or []:
                append_unique_tag(viewpoint_tag_options, viewpoint_tag_seen, tag)
        for tag in all_tag_options(searchable_items, limit=120):
            append_unique_tag(viewpoint_tag_options, viewpoint_tag_seen, tag)
        viewpoint_tag_picker = tag_picker_controls_html(
            [],
            viewpoint_tag_options[:18],
            viewpoint_tag_options,
            placeholder="搜尋或新增觀點 tag",
            aria_label="搜尋或新增觀點 tag",
        )
        material_count = sum(1 for record in searchable_items if is_skill_candidate(record))
        small_news_count = sum(1 for record in searchable_items if is_direct_pr_item(record))
        body = f"""
{back_nav_html(self.same_origin_referer_path("/editor"))}
<section class="card">
  <h1>{icon_span("note")}觀點庫</h1>
  <p class="muted">這裡以「材料帶出的觀點」為主。單篇材料的個人紀錄、編輯台過程中留下的待補觀點，以及已連結的 article 都會在這裡串起來。</p>
</section>
<section class="editor-workbench editor-vp-workbench">
  <div class="card editor-card">
    <h2>新增觀點</h2>
    <form method="post" action="/editor/viewpoints/save" class="editor-vp-form tag-picker" data-tag-picker>
      <label class="editor-label">標題<input type="text" name="title" placeholder="例如：開放資料的公共價值"></label>
      <input type="hidden" name="related_item_ids" data-vp-related-items>
      <label class="editor-label">觀點關聯池</label>
      <div class="editor-vp-selected editor-vp-dropzone" data-vp-selected data-vp-dropzone>
        <p class="muted">搜尋材料後拖進來，或按「加入觀點關聯」。</p>
      </div>
      <label class="editor-label">概念標籤</label>
      <div class="editor-vp-tag-picker">{viewpoint_tag_picker}</div>
      <p class="help">沿用單篇文章的 tag 邏輯；可搜尋既有 tag，或用 Enter、逗號一次新增多個。</p>
      <label class="editor-label">內容<textarea name="body" rows="3" required></textarea></label>
      <button type="submit" class="button">{button_content('新增觀點', 'plus')}</button>
    </form>
  </div>
  <aside class="card editor-search-card">
    <h2>搜尋材料</h2>
    <p class="help">可把可用材料或新聞小消息關聯到這條觀點。搜尋標題、摘要、來源或 tag 後，按鈕加入或直接拖進關聯池。</p>
    <div class="editor-search-row">
      <input type="search" id="vp-material-search" placeholder="搜尋材料">
      <button type="button" class="secondary" id="vp-material-search-button">{button_content('搜尋', 'filter')}</button>
    </div>
    <p class="muted">材料池：{len(searchable_items)} 筆（可用材料 {material_count} / 新聞小消息 {small_news_count}）</p>
    <div class="editor-search-results editor-vp-results" data-vp-results>
      <p class="muted">輸入關鍵字後按搜尋。</p>
    </div>
  </aside>
</section>
<section>
  <h2>材料裡的觀點</h2>
  <div class="editor-vp-grid">{material_note_rows}</div>
</section>
<section>
  <h2>編輯台留下的觀點</h2>
  <div class="editor-vp-grid">{rows}</div>
</section>
<style>
  .editor-vp-workbench {{ margin:16px 0; }}
  .editor-workbench {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(300px,380px); gap:16px; align-items:start; }}
  .editor-card, .editor-search-card {{ display:grid; gap:12px; }}
  .editor-vp-form input, .editor-vp-form textarea, .editor-search-row input {{ width:100%; box-sizing:border-box; padding:8px; border-radius:8px; border:1px solid var(--border,#cbd5e1); font:inherit; }}
  .editor-vp-form .tag-pill, .editor-vp-form .tag-suggestion, .editor-vp-form .tag-menu-option {{ width:auto; }}
  .editor-label {{ display:block; margin:10px 0; font-size:14px; }}
  .editor-search-row {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:end; }}
  .editor-vp-selected, .editor-vp-results {{ display:grid; gap:8px; }}
  .editor-vp-dropzone {{ min-height:120px; border:1px dashed var(--line); border-radius:8px; padding:10px; background:#f8fafc; align-content:start; }}
  .editor-vp-dropzone.is-drag-over {{ border-color:var(--ocf-primary); background:#eef2ff; }}
  .editor-vp-results {{ max-height:300px; overflow:auto; padding-right:2px; }}
  .editor-vp-material {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fff; display:grid; gap:6px; }}
  .editor-vp-material-title {{ font-weight:700; color:var(--ocf-dark); }}
  .editor-vp-material-meta {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
  .editor-kind-pill {{ font-weight:800; }}
  .editor-kind--material {{ background:#ece8ff; color:var(--ocf-primary); }}
  .editor-kind--small-news {{ background:#fff8db; color:#7a5a00; }}
  .editor-vp-grid {{ display:grid; gap:12px; }}
  .editor-vp details {{ margin-top:8px; }}
  @media (max-width: 900px) {{ .editor-workbench {{ grid-template-columns:1fr; }} .editor-vp-results {{ max-height:none; }} }}
</style>
{EDITOR_TIMELINE_ASSETS}
<script type="application/json" id="vp-materials-json">{viewpoint_material_json}</script>
<script>
(function() {{
  var materialsNode = document.getElementById("vp-materials-json");
  var searchInput = document.getElementById("vp-material-search");
  var searchButton = document.getElementById("vp-material-search-button");
  var results = document.querySelector("[data-vp-results]");
  var selectedBox = document.querySelector("[data-vp-selected]");
  var hidden = document.querySelector("[data-vp-related-items]");
  if (!materialsNode || !searchInput || !searchButton || !results || !selectedBox || !hidden) return;
  var materials = JSON.parse(materialsNode.textContent || "[]");
  var selected = new Map();
  function escapeHtml(text) {{
    return String(text || "").replace(/[&<>"']/g, function(ch) {{
      return ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}})[ch];
    }});
  }}
  function badges(item) {{
    var rows = [`<span class="tag-pill editor-kind-pill editor-kind--${{escapeHtml(item.type || "material")}}">${{escapeHtml(item.typeLabel || "可用材料")}}</span>`];
    rows.push(`<span class="tag-pill">${{escapeHtml(item.trackLabel || "未分類")}}</span>`);
    if (item.hasTranslation) rows.push('<span class="tag-pill">有翻譯全文</span>');
    (item.tags || []).slice(0, 3).forEach(function(tag) {{ rows.push(`<span class="tag-pill">${{escapeHtml(tag)}}</span>`); }});
    return rows.join("");
  }}
  function matches(item, query) {{
    if (!query) return true;
    var haystack = [item.id, item.title, item.summary, item.source, item.trackLabel].concat(item.tags || []).join(" ").toLowerCase();
    return haystack.indexOf(query.toLowerCase()) !== -1;
  }}
  function renderSelected() {{
    var ids = Array.from(selected.keys());
    hidden.value = ids.join(",");
    selectedBox.innerHTML = ids.length ? ids.map(function(id) {{
      var item = selected.get(id);
      return `<article class="editor-vp-material">
        <div class="editor-vp-material-title">${{escapeHtml(item.title)}}</div>
        <div class="editor-vp-material-meta"><code>${{escapeHtml(id)}}</code>${{badges(item)}}</div>
        <button type="button" class="button button-small quiet" data-vp-remove="${{escapeHtml(id)}}">移除關聯</button>
      </article>`;
    }}).join("") : '<p class="muted">搜尋材料後拖進來，或按「加入觀點關聯」。</p>';
  }}
  function renderResults() {{
    var query = (searchInput.value || "").trim();
    if (!query) {{
      results.innerHTML = '<p class="muted">輸入關鍵字後按搜尋。</p>';
      return;
    }}
    var rows = materials.filter(function(item) {{ return matches(item, query); }}).slice(0, 24);
    results.innerHTML = rows.length ? rows.map(function(item) {{
      var added = selected.has(item.id);
      return `<article class="editor-vp-material" draggable="true" data-vp-material-id="${{escapeHtml(item.id)}}">
        <div class="editor-vp-material-title">${{escapeHtml(item.title)}}</div>
        <p class="muted">${{escapeHtml(item.summary || "沒有摘要。")}}</p>
        <div class="editor-vp-material-meta"><code>${{escapeHtml(item.id)}}</code>${{badges(item)}}</div>
        <button type="button" class="button button-small" data-vp-add="${{escapeHtml(item.id)}}"${{added ? " disabled" : ""}}>${{added ? "已關聯" : "加入觀點關聯"}}</button>
      </article>`;
    }}).join("") : '<p class="muted">沒有找到符合的材料。</p>';
  }}
  function findMaterial(id) {{
    return materials.find(function(item) {{ return item.id === id; }});
  }}
  function addSelected(id) {{
    var item = findMaterial(id);
    if (!item) return;
    selected.set(item.id, item);
    renderSelected();
    renderResults();
    // #4：把選中材料的既有標籤先放進觀點的標籤區（你可自行移除）
    var picker = document.querySelector("form[data-tag-picker]");
    if (picker && typeof picker.tagPickerAddTag === "function") {{
      (item.tags || []).forEach(function(tag) {{ picker.tagPickerAddTag(tag); }});
    }}
  }}
  searchButton.addEventListener("click", renderResults);
  searchInput.addEventListener("keydown", function(event) {{
    if (event.key === "Enter") {{
      event.preventDefault();
      renderResults();
    }}
  }});
  results.addEventListener("click", function(event) {{
    var btn = event.target.closest("[data-vp-add]");
    if (!btn) return;
    addSelected(btn.getAttribute("data-vp-add"));
  }});
  results.addEventListener("dragstart", function(event) {{
    var card = event.target.closest("[data-vp-material-id]");
    if (!card || !event.dataTransfer) return;
    event.dataTransfer.setData("text/plain", card.getAttribute("data-vp-material-id"));
    event.dataTransfer.effectAllowed = "copy";
  }});
  selectedBox.addEventListener("dragover", function(event) {{
    event.preventDefault();
    selectedBox.classList.add("is-drag-over");
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  }});
  selectedBox.addEventListener("dragleave", function(event) {{
    if (!selectedBox.contains(event.relatedTarget)) selectedBox.classList.remove("is-drag-over");
  }});
  selectedBox.addEventListener("drop", function(event) {{
    event.preventDefault();
    selectedBox.classList.remove("is-drag-over");
    var id = event.dataTransfer ? event.dataTransfer.getData("text/plain") : "";
    addSelected(id);
  }});
  selectedBox.addEventListener("click", function(event) {{
    var btn = event.target.closest("[data-vp-remove]");
    if (!btn) return;
    selected.delete(btn.getAttribute("data-vp-remove"));
    renderSelected();
    renderResults();
  }});
  renderSelected();
}})();
</script>
<style>
  .editor-vp.is-focused {{ outline:3px solid var(--ocf-primary,#6450dc); outline-offset:2px; box-shadow:0 8px 24px rgba(100,80,220,0.2); }}
</style>
<script>
(function(){{
  var focus = new URLSearchParams(window.location.search).get("focus");
  if (!focus) return;
  var card = document.getElementById("vp-card-" + focus);
  if (!card) return;
  card.scrollIntoView({{ block:"center", behavior:"smooth" }});
  card.classList.add("is-focused");
  setTimeout(function(){{ card.classList.remove("is-focused"); }}, 2600);
}})();
</script>
"""
        self.send_html("觀點庫", body)

    def save_viewpoint(self, data: dict[str, list[str]]) -> None:
        title = form_value(data, "title")
        body = form_value(data, "body")
        tags = form_tags(data)
        related_item_ids = [item_id for item_id in re.split(r"[\s,，]+", form_value(data, "related_item_ids")) if item_id]
        vp_id = form_value(data, "id") or new_editor_id("vp")
        if not body.strip():
            self.redirect("/editor/viewpoints")
            return
        existing = next((v for v in load_jsonl(VIEWPOINTS) if clean_text(v.get("id")) == vp_id), {})
        record = {
            "id": vp_id,
            "title": title or "（未命名觀點）",
            "tags": tags,
            "body": body,
            "source": clean_text(existing.get("source")) or "user",
            "status": "kept",
            "related_item_ids": related_item_ids or existing.get("related_item_ids") or [],
            "created_at": existing.get("created_at") or now_iso(),
            "updated_at": now_iso(),
        }
        upsert_jsonl(VIEWPOINTS, record)
        if self.is_async_request():
            self.send_json({"ok": True, "id": vp_id})
        else:
            self.redirect("/editor/viewpoints")

    def delete_viewpoint(self, data: dict[str, list[str]]) -> None:
        vp_id = form_value(data, "id")
        if vp_id:
            remove_jsonl_ids(VIEWPOINTS, {vp_id})
        if self.is_async_request():
            self.send_json({"ok": True})
        else:
            self.redirect("/editor/viewpoints")

    def link_article(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "item_id")
        ref = form_value(data, "ref")
        if not (item_id and ref):
            if self.is_async_request():
                self.send_json({"ok": False, "error": "需要材料與 article 連結。"}, HTTPStatus.BAD_REQUEST)
            else:
                self.redirect(self.same_origin_referer_path("/editor"))
            return
        record = {
            "id": new_editor_id("link"),
            "item_id": item_id,
            "ref": ref,
            "ref_kind": form_value(data, "ref_kind", "url"),
            "title": form_value(data, "title") or ref,
            "relation": form_value(data, "relation", "article"),
            "created_at": now_iso(),
        }
        append_jsonl(MATERIAL_LINKS, record)
        if self.is_async_request():
            self.send_json({"ok": True, "id": record["id"]})
        else:
            self.redirect(self.same_origin_referer_path(f"/items/view?id={quote(item_id)}"))

    def unlink_article(self, data: dict[str, list[str]]) -> None:
        link_id = form_value(data, "id")
        item_id = form_value(data, "item_id")
        if link_id:
            remove_jsonl_ids(MATERIAL_LINKS, {link_id})
        if self.is_async_request():
            self.send_json({"ok": True})
        else:
            self.redirect(self.same_origin_referer_path(f"/items/view?id={quote(item_id)}" if item_id else "/editor"))

    # ------------------------------------------------------------------ #
    # 專文（article）：編修台
    # ------------------------------------------------------------------ #
    def create_article_from_session(self, data: dict[str, list[str]]) -> None:
        session_id = form_value(data, "session") or form_value(data, "id")
        session = next((s for s in load_jsonl(EDITOR_SESSIONS) if clean_text(s.get("id")) == session_id), None)
        if not session:
            self.send_html("找不到", "<h1>找不到這次編輯紀錄</h1><p><a href='/editor'>回編輯台</a></p>", HTTPStatus.NOT_FOUND)
            return
        article = build_article_from_session(session, load_articles())
        upsert_jsonl(ARTICLES, article)
        self.redirect(f"/articles/edit?id={quote(article['id'])}")

    def save_article(self, data: dict[str, list[str]]) -> None:
        article_id = form_value(data, "id")
        existing = next((a for a in load_articles() if clean_text(a.get("id")) == article_id), None)
        if not existing:
            self.send_json({"ok": False, "error": "找不到專文"}, HTTPStatus.NOT_FOUND)
            return
        # body_markdown 必須讀原始值，不能走 clean_text（會吃掉換行、縮排與標記）
        body_markdown = (data.get("body_markdown") or [""])[0].replace("\r\n", "\n").replace("\r", "\n")
        item_ids = [x for x in re.split(r"[\s,]+", form_value(data, "item_ids")) if x]
        viewpoint_ids = [x for x in re.split(r"[\s,]+", form_value(data, "viewpoint_ids")) if x]
        record = normalize_article_record(
            {
                **existing,
                "id": article_id,
                "title": form_value(data, "title") or existing.get("title"),
                "track": form_value(data, "track") or existing.get("track"),
                "status": form_value(data, "status") or existing.get("status") or "draft",
                "body_markdown": body_markdown,
                "tags": form_tags(data),
                "item_ids": item_ids,
                "viewpoint_ids": viewpoint_ids,
                "created_at": existing.get("created_at"),
                "source_session_id": existing.get("source_session_id"),
                "license": manual_license_record(form_value(data, "license"), existing.get("license")),
                "factcheck": existing.get("factcheck"),
            }
        )
        upsert_jsonl(ARTICLES, record)
        if self.is_async_request() or form_value(data, "format") == "json":
            self.send_json({"ok": True, "id": record["id"], "updated_at": record["updated_at"], "saved_label": local_time_label()})
        else:
            self.redirect(f"/articles/edit?id={quote(record['id'])}")

    def refresh_article_factcheck(self, data: dict[str, list[str]]) -> None:
        article_id = form_value(data, "id")
        existing = next((a for a in load_articles() if clean_text(a.get("id")) == article_id), None)
        if not existing:
            if self.is_async_request():
                self.send_json({"ok": False, "error": "找不到專文"}, HTTPStatus.NOT_FOUND)
            else:
                self.send_html("找不到", "<h1>找不到專文</h1>", HTTPStatus.NOT_FOUND)
            return
        snapshot = factcheck_snapshot_from_session(latest_factcheck_for_items(existing.get("item_ids") or []))
        record = normalize_article_record({**existing, "factcheck": snapshot or existing.get("factcheck") or {}})
        upsert_jsonl(ARTICLES, record)
        if self.is_async_request():
            self.send_json({"ok": True, "id": record["id"], "claims": len((record.get("factcheck") or {}).get("claims") or [])})
        else:
            self.redirect(f"/articles/edit?id={quote(record['id'])}")

    # ------------------------------------------------------------------ #
    # 決策洞察面板 /insights
    # ------------------------------------------------------------------ #

    def show_insights(self, query: dict[str, list[str]]) -> None:
        banner = ""
        if query.get("sampled"):
            n = (query.get("sampled") or ["0"])[0]
            if n == "0":
                banner = '<p class="success-banner">沒有可抽的新分歧了（既有資料中的分歧都已在清單裡）。</p>'
            else:
                banner = f'<p class="success-banner">已抽 {h(n)} 筆分歧進待填清單。</p>'
        elif query.get("error") == "no-explained":
            banner = '<p class="error-banner">沒有「已填說明」的分歧可分析。先在卡片裡填想法再按分析。</p>'
        elif query.get("saved") == "taste":
            banner = '<p class="success-banner">品味檔已儲存。</p>'

        divs = load_jsonl(DECISION_DIVERGENCES)
        reports = load_jsonl(INSIGHT_REPORTS)
        reports.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
        proposals = load_jsonl(SYSTEM_CHANGE_PROPOSALS)

        # 分四類：待填 / 已分析(等待提案) / 已分析(可結案) / 已結案
        active = [d for d in divs if not d.get("dismissed")]
        closed_divs = [d for d in divs if d.get("dismissed")]
        analyzed = [d for d in active if d.get("included_in_analysis_at")]
        analyzed_waiting = [d for d in analyzed if _has_pending_proposals_for_divergence(d["id"], reports, proposals)]
        analyzed_ready   = [d for d in analyzed if not _has_pending_proposals_for_divergence(d["id"], reports, proposals)]

        unfilled = [d for d in active if not d.get("user_explanation") and not d.get("included_in_analysis_at")]
        pending_b = [d for d in unfilled if d.get("divergence_type") == "over-rejected"]
        pending_a = [d for d in unfilled if d.get("divergence_type") == "under-collected"]
        explained = [d for d in active if d.get("user_explanation") and not d.get("included_in_analysis_at")]
        pending_b.sort(key=lambda d: d.get("cluster_size", 1), reverse=True)
        pending_a.sort(key=lambda d: (d.get("ai_suggestion") or {}).get("confidence", ""), reverse=True)

        explained_count = len(explained)
        engines = editor_engine_status()

        # 查找表：分歧只存了原始（多為英文）標題，渲染時即時用 id 查回 live item，
        # 才能顯示「當時翻譯／看到的中文標題」與更多當時脈絡。涵蓋 items + rejected-items。
        _div_item_lookup: dict[str, dict] = {}
        for _row in [*load_jsonl(ITEMS), *load_jsonl(REJECTED_ITEMS)]:
            _rid = clean_text(_row.get("id"))
            if _rid and _rid not in _div_item_lookup:
                _div_item_lookup[_rid] = _row

        _USER_ACTION_LABELS = {
            "accepted-for-editing": "收進可用材料",
            "direct-pr-small-news": "直接送 PR（小消息）",
            "want-to-read": "想讀 / 超想看",
            "accepted-current-reading": "正在閱讀",
            "rejected": "不收",
        }

        def _div_title_links(div: dict) -> str:
            """中文顯示標題（可點）＋原文標題（不同才顯示），即時查 live item。"""
            item_ids = div.get("item_ids") or []
            stored = div.get("item_titles") or []
            n = max(len(item_ids), len(stored))
            parts = []
            for i in range(min(n, 3)):
                iid = item_ids[i] if i < len(item_ids) else ""
                item = _div_item_lookup.get(iid)
                zh = item_display_title(item) if item else (stored[i] if i < len(stored) else "（無標題）")
                orig = item_original_title(item) if item else ""
                head = (f'<a href="/items/view?id={quote(iid)}" class="item-link" target="_blank">{h(zh)} ↗</a>'
                        if iid else h(zh))
                sub = ""
                if orig and clean_text(orig) and clean_text(orig) != clean_text(zh):
                    sub = f'<br><span class="muted div-orig-title">原標題：{h(orig)}</span>'
                parts.append(f"<div class='div-title-row'>{head}{sub}</div>")
            joined = "".join(parts) or "（未知標題）"
            if n > 3:
                joined += f"<div class='muted'>…等共 {n} 筆</div>"
            return joined

        def _div_context_html(div: dict) -> str:
            """當時 AI 建議（含來源/類型/信心）→ 你的決定；加 track 與記錄日期。"""
            ai = div.get("ai_suggestion") or {}
            src = ai.get("source", "")
            rec = ai.get("recommendation", "")
            kind = ai.get("content_kind", "")
            conf = ai.get("confidence", "")
            user_act = div.get("user_action", "")
            track = clean_text(div.get("track"))
            logged = (div.get("logged_at") or "")[:10]
            src_label = {"editorial_triage": "AI 深度判斷", "triage": "關鍵字快篩"}.get(src, src or "")
            rec_label = editorial_recommendation_label(rec) if src == "editorial_triage" else recommendation_label(rec)
            ai_extra = "、".join([x for x in [src_label, (content_kind_label(kind) if kind else ""), (f"信心 {conf}" if conf else "")] if x])
            ai_extra_html = f"（{h(ai_extra)}）" if ai_extra else ""
            act_label = _USER_ACTION_LABELS.get(user_act, user_act or "未知")
            meta_bits = []
            if track:
                meta_bits.append(h(track_meta(track)["short"]))
            if logged:
                meta_bits.append(f"記錄於 {h(logged)}")
            meta_line = f'<div class="muted div-meta">{"　·　".join(meta_bits)}</div>' if meta_bits else ""
            return (
                f'<div class="div-context"><span class="muted">AI 當時：</span>{h(rec_label)}{ai_extra_html}'
                f' <span class="muted">→ 你的決定：</span><strong>{h(act_label)}</strong></div>{meta_line}'
            )

        def _div_detail_block(div: dict) -> str:
            """可展開：當時 AI 理由 + 原文摘要，幫使用者回想為何當初這樣決定。"""
            ai = div.get("ai_suggestion") or {}
            src = ai.get("source", "")
            iid = (div.get("item_ids") or [""])[0]
            item = _div_item_lookup.get(iid) or {}
            reason = ""
            if src == "editorial_triage":
                reason = clean_text((item.get("editorial_triage") or {}).get("summary_reason") or (item.get("editorial_triage") or {}).get("reason"))
            if not reason:
                reason = clean_text((item.get("triage") or {}).get("reason"))
            summary = clean_text(item.get("summary"), 400)
            if not reason and not summary:
                return ""
            inner = ""
            if reason:
                inner += f'<p class="muted" style="margin:4px 0"><strong>當時 AI 理由：</strong>{h(reason)}</p>'
            if summary:
                inner += f'<p class="muted" style="margin:4px 0"><strong>原文摘要：</strong>{h(summary)}</p>'
            return f'<details class="div-detail"><summary class="muted">看當時摘要與 AI 理由</summary>{inner}</details>'

        def div_card(div: dict, state: str = "unfilled") -> str:
            div_id = h(div.get("id", ""))
            dt = div.get("divergence_type", "")
            dt_label = "AI 超推卻拒收" if dt == "over-rejected" else "AI 說不收你卻收"
            dt_class = "badge-red" if dt == "over-rejected" else "badge-blue"
            cluster = div.get("cluster_size", 1)
            cluster_badge = f" × {cluster} 筆" if cluster > 1 else ""
            ai_rec = (div.get("ai_suggestion") or {}).get("recommendation", "")
            confidence = (div.get("ai_suggestion") or {}).get("confidence", "")
            user_act = div.get("user_action", "")
            title_links = _div_title_links(div)
            cluster_label = h(div.get("cluster_label", ""))
            expl = h(div.get("user_explanation", ""))
            conf_label = f'<span class="muted">信心度：{h(confidence)}</span>' if confidence else ""
            state_badge = ('<span class="badge badge-blue">已填說明</span>'
                           if state == "explained" else
                           '<span class="badge badge-gray">待填寫</span>')
            return f"""
<div class="div-card" data-filter-group="cue" data-div-type="{h(dt)}" data-div-state="{h(state)}" data-card-id="{div_id}">
  <div class="div-card-header">
    <span class="badge {dt_class}">{h(dt_label)}{cluster_badge}</span>
    {state_badge}
    {conf_label}
  </div>
  <div class="div-card-body">
    {f'<strong>{cluster_label}</strong>' if cluster_label else ''}
    <div class="div-titles">{title_links}</div>
    {_div_context_html(div)}
    {_div_detail_block(div)}
  </div>
  <form class="div-explain-form" method="post" action="/insights/explain" data-ajax-explain>
    <input type="hidden" name="id" value="{div_id}">
    <input type="text" name="explanation" value="{expl}" placeholder="你的想法（為何這樣選）" class="div-explain-input">
    <button type="submit" class="button small">存</button>
    <span class="explain-ok" hidden>✓ 已存</span>
  </form>
  <form method="post" action="/insights/dismiss" style="display:inline" data-ajax-dismiss>
    <input type="hidden" name="id" value="{div_id}">
    <button type="submit" class="button small secondary">略過</button>
  </form>
</div>"""

        def div_analyzed_card(div: dict, state: str) -> str:
            """已分析分歧的卡片 — state: 'waiting'（等待提案）or 'ready'（可結案）。"""
            div_id = h(div.get("id", ""))
            dt = div.get("divergence_type", "")
            dt_label = "AI 超推卻拒收" if dt == "over-rejected" else "AI 說不收你卻收"
            dt_class = "badge-red" if dt == "over-rejected" else "badge-blue"
            title_links = _div_title_links(div)
            ai_rec = (div.get("ai_suggestion") or {}).get("recommendation", "")
            user_act = div.get("user_action", "")
            analyzed_at = (div.get("included_in_analysis_at") or "")[:10]
            expl = h(div.get("user_explanation", ""))
            if state == "waiting":
                # 計算等待幾個提案
                rpt_ids = {r["id"] for r in reports if div.get("id") in r.get("divergence_ids", [])}
                pending_count = sum(1 for p in proposals if p.get("source_report") in rpt_ids and p.get("status") in ("pending", "evaluating"))
                action_html = f'<span class="muted">等待 {pending_count} 個提案結案後可結案</span>'
                card_class = "div-card div-analyzed-waiting"
            else:
                action_html = f'''<form method="post" action="/insights/close-analyzed" style="display:inline" data-ajax-dismiss>
  <input type="hidden" name="id" value="{div_id}">
  <button type="submit" class="button small">結案</button>
</form>'''
                card_class = "div-card div-analyzed-ready"
            state_badge = ('<span class="badge badge-green">可結案</span>'
                           if state == "ready" else
                           '<span class="badge badge-gray">等待提案</span>')
            return f"""
<div class="{card_class}" data-filter-group="cue" data-div-type="{h(dt)}" data-div-state="analyzed" data-card-id="{div_id}">
  <div class="div-card-header">
    <span class="badge {dt_class}">{h(dt_label)}</span>
    {state_badge}
    <span class="badge badge-gray" style="font-weight:400">已分析 {analyzed_at}</span>
  </div>
  <div class="div-card-body">
    <div class="div-titles">{title_links}</div>
    {_div_context_html(div)}
    {f'<div class="muted">你的理由：{expl}</div>' if expl else ''}
    {_div_detail_block(div)}
  </div>
  {action_html}
</div>"""

        def cli_button(rpt_id: str, engine: str, label: str) -> str:
            available = engines.get(engine)
            disabled = "" if available else " disabled"
            suffix = "" if available else "（未安裝）"
            return f'''<form method="post" action="/insights/apply-report" data-insight-job="用 {label} 依報告調整系統設定" style="display:inline">
  <input type="hidden" name="id" value="{rpt_id}">
  <input type="hidden" name="engine" value="{engine}">
  <button type="submit" class="button small"{disabled}>用 {label} 實作{suffix}</button>
</form>'''

        def report_row(rpt: dict) -> str:
            rpt_id = h(rpt.get("id", ""))
            gen_at = rpt.get("generated_at", "")[:10]
            mode_label = {"full": "完整分析", "sample-5": "隨機 5 筆", "explained": "已填說明"}.get(rpt.get("mode", ""), rpt.get("mode", ""))
            status = rpt.get("implementation_status", "pending")
            status_label = {"pending": "待實作", "attempted": "已跑過 CLI", "implemented": "✓ 已實作", "skipped": "略過"}.get(status, status)
            status_cls = "badge-green" if status == "implemented" else ("badge-blue" if status == "attempted" else "badge-gray")
            summary = h((rpt.get("report_summary") or "")[:120])
            notes_val = h(rpt.get("implementation_notes", ""))
            report_text = h(rpt.get("report_text", ""))

            cli_buttons = "".join(
                cli_button(rpt_id, provider, AI_PROVIDER_META[provider]["short"])
                for provider in AI_PROVIDER_ORDER
            )

            runs_html = ""
            for run in (rpt.get("apply_runs") or []):
                diff = h(run.get("diff", "") or "（設定檔未變更）")
                out = h(run.get("output", ""))
                ch = run.get("changes") or {}
                summary = h(run.get("summary", ""))
                note = h(run.get("note", ""))
                change_line = (f"品味{'有改' if ch.get('taste') else '未改'}、"
                               f"關鍵字 {ch.get('keywords',0)} 條 track、來源 {ch.get('sources',0)} 個、提案 {ch.get('proposals',0)} 筆") if ch else ""
                details_html = render_apply_change_details(ch.get("details") if isinstance(ch, dict) else None)
                runs_html += f"""
<div class="apply-run">
  <div class="muted">{h(run.get('engine',''))} · {h((run.get('ran_at','') or '')[:16])}{(' · ' + change_line) if change_line else ''}</div>
  {f'<div>{summary}</div>' if summary else ''}
  {f'<div class="error-banner" style="margin:6px 0">{note}</div>' if note else ''}
  {details_html}
  <details><summary>設定檔 diff（taste-profile / triage-keywords / sources）</summary><pre class="report-pre">{diff}</pre></details>
  <details><summary>CLI 原始輸出</summary><pre class="report-pre">{out}</pre></details>
</div>"""

            impl_form = f'''<form method="post" action="/insights/mark-implemented" style="display:inline">
  <input type="hidden" name="id" value="{rpt_id}">
  <input type="text" name="notes" value="" placeholder="備註（拿去做了什麼）" style="font-size:0.85em;width:200px">
  <button type="submit" class="button small secondary">標記已實作</button>
</form>'''

            rpt_prompt_id = f"prompt-rpt-{rpt_id}"
            rpt_prompt_text = h(build_report_prompt(rpt))
            return f"""
<details class="report-row" data-filter-group="reports" data-rpt-status="{h(status)}">
  <summary>
    <strong>{gen_at}</strong> {h(mode_label)}
    <span class="badge {status_cls}">{h(status_label)}</span>
    <span class="muted" style="font-size:0.85em">{summary}</span>
  </summary>
  <pre class="report-pre">{report_text}</pre>
  <div class="report-actions">
    <button type="button" class="button small" data-copy="{rpt_prompt_id}">複製整份報告的實作 prompt</button>
    {cli_buttons}{impl_form}
  </div>
  <textarea id="{rpt_prompt_id}" class="copy-src" readonly>{rpt_prompt_text}</textarea>
  {runs_html}
  {f'<p class="muted">實作備註：{notes_val}</p>' if notes_val else ''}
</details>"""

        analyze_disabled = "" if explained_count else " disabled"
        batch_close_disabled = "" if analyzed_ready else " disabled"

        def closed_card(div: dict) -> str:
            div_id = h(div.get("id", ""))
            dt = div.get("divergence_type", "")
            dt_class = "badge-red" if dt == "over-rejected" else "badge-blue"
            dt_label = "AI 超推卻拒收" if dt == "over-rejected" else "AI 說不收你卻收"
            title_links = _div_title_links(div)
            expl = h(div.get("user_explanation", ""))
            return f"""
<div class="div-card div-closed" data-filter-group="cue" data-div-type="{h(dt)}" data-div-state="closed" data-card-id="{div_id}" hidden>
  <div class="div-card-header">
    <span class="badge {dt_class}">{dt_label}</span>
    <span class="badge badge-green">✓ 已結案</span>
  </div>
  <div class="div-card-body">
    <div class="div-titles muted">{title_links}</div>
    {f'<span class="muted">你的理由：{expl}</span>' if expl else ''}
  </div>
</div>"""

        # 待釐清案例：所有 cue 卡片合成一個 section（含已結案，預設隱藏）
        all_cue_cards = (
            ''.join(div_card(d, "unfilled") for d in pending_b)
            + ''.join(div_card(d, "unfilled") for d in pending_a)
            + ''.join(div_card(d, "explained") for d in explained)
            + ''.join(div_analyzed_card(d, "ready") for d in analyzed_ready)
            + ''.join(div_analyzed_card(d, "waiting") for d in analyzed_waiting)
            + ''.join(closed_card(d) for d in closed_divs[:30])
        )
        total_active = len(pending_b) + len(pending_a) + len(explained) + len(analyzed_waiting) + len(analyzed_ready)
        total_closed = len(closed_divs)
        cue_empty = '<p class="muted">待填清單是空的。在右側按「隨機抓 5 筆進待填」抽幾筆來填，或在收件/分流時系統會自動累積。</p>' if not total_active else ""
        cue_section = f"""
<section>
  <div class="section-header" data-filter-section="cue">
    <div class="section-header-left">
      <h2>待釐清案例 <span class="badge badge-gray">{total_active} 筆</span></h2>
      <p class="section-sub">AI 建議與你的收錄決策不一致，填上理由後可送分析。</p>
    </div>
    <div class="section-filters">
      <button class="filter-pill is-active" data-filter-group="cue" data-filter-attr="divState" data-filter-val="unfilled,explained,analyzed">進行中</button>
      <button class="filter-pill" data-filter-group="cue" data-filter-attr="divState" data-filter-val="unfilled">待填</button>
      <button class="filter-pill" data-filter-group="cue" data-filter-attr="divState" data-filter-val="explained">已填說明</button>
      <button class="filter-pill" data-filter-group="cue" data-filter-attr="divState" data-filter-val="analyzed">已分析</button>
      <button class="filter-pill" data-filter-group="cue" data-filter-attr="divState" data-filter-val="closed">已結案（{total_closed}）</button>
      <button class="filter-pill" data-filter-group="cue" data-filter-attr="divType" data-filter-val="over-rejected">AI 超推</button>
      <button class="filter-pill" data-filter-group="cue" data-filter-attr="divType" data-filter-val="under-collected">AI 低估</button>
    </div>
  </div>
  {cue_empty}
  {all_cue_cards}
  <p class="filter-empty muted" data-empty-group="cue" hidden>目前篩選下沒有項目，點上方其他標籤查看。</p>
</section>"""

        # 分析報告
        reports_html = ''.join(report_row(r) for r in reports[:20])
        rpt_count = len(reports)
        reports_section = f"""
<section>
  <div class="section-header" data-filter-section="reports">
    <div class="section-header-left">
      <h2>分析報告 <span class="badge badge-gray">{rpt_count} 份</span></h2>
      <p class="section-sub">每次「分析已填說明」的完整記錄，可用 CLI 把建議套用進系統。</p>
    </div>
    <div class="section-filters">
      <button class="filter-pill is-active" data-filter-group="reports" data-filter-attr="rptStatus" data-filter-val="pending,attempted">進行中</button>
      <button class="filter-pill" data-filter-group="reports" data-filter-attr="rptStatus" data-filter-val="all">全部</button>
      <button class="filter-pill" data-filter-group="reports" data-filter-attr="rptStatus" data-filter-val="pending">待實作</button>
      <button class="filter-pill" data-filter-group="reports" data-filter-attr="rptStatus" data-filter-val="attempted">已跑過 CLI</button>
      <button class="filter-pill" data-filter-group="reports" data-filter-attr="rptStatus" data-filter-val="implemented">✓ 已實作</button>
    </div>
  </div>
  {reports_html or '<p class="muted">尚無報告。填好說明後在右側按「分析」。</p>'}
  <p class="filter-empty muted" data-empty-group="reports" hidden>目前篩選下沒有報告（可能都已實作），點「全部」查看。</p>
</section>"""

        # sidebar
        taste_lines = taste_profile_summary_lines()
        taste_ul = "".join(f"<li>{h(line)}</li>" for line in taste_lines) or "<li class='muted'>尚未設定，分析並用 CLI 實作後會開始累積。</li>"
        if explained_count:
            analyze_hint = ""
        elif unfilled:
            analyze_hint = '<p class="section-sub" style="margin:4px 0 0">先在待填卡片填上「你的想法」再分析</p>'
        elif analyzed:
            analyze_hint = '<p class="section-sub" style="margin:4px 0 0">已填的都分析過了；抽新分歧或填新想法後才有可分析的</p>'
        else:
            analyze_hint = '<p class="section-sub" style="margin:4px 0 0">目前沒有待分析的分歧</p>'
        batch_hint = "" if analyzed_ready else '<p class="section-sub" style="margin:4px 0 0">尚無可結案項目</p>'
        taste_sidebar = f"""
<section class="workspace-sidebar-section">
  <h2>操作</h2>
  <div class="sidebar-actions">
    <form method="post" action="/insights/sample-into-cue" data-ajax-sample>
      <button type="submit" class="button secondary" style="width:100%">隨機抓 5 筆進待填</button>
    </form>
    <span id="sample-result" class="muted" style="font-size:0.85em;display:none"></span>
    <div>
      <form method="post" action="/insights/generate-report" data-insight-job="分析已填說明的分歧">
        <select name="engine" aria-label="分析引擎" style="width:100%;margin-bottom:6px">{option_list([(provider, AI_PROVIDER_META[provider]["label"]) for provider in AI_PROVIDER_ORDER], "claude")}</select>
        <button type="submit" class="button" style="width:100%"{analyze_disabled}>分析已填說明的 {explained_count} 筆</button>
      </form>
      {analyze_hint}
    </div>
    <div>
      <form method="post" action="/insights/close-all-resolved" data-ajax-batch-close>
        <button type="submit" class="button secondary" style="width:100%"{batch_close_disabled}>批次結案（{len(analyzed_ready)} 筆可結案）</button>
      </form>
      {batch_hint}
    </div>
  </div>
</section>
<section class="workspace-sidebar-section">
  <h2>品味設定</h2>
  <ul class="taste-sidebar-list">{taste_ul}</ul>
  <a href="/insights/edit-taste-profile" class="button secondary small" style="margin-top:8px;display:inline-block;width:100%;text-align:center">編輯品味檔 →</a>
</section>
<section class="workspace-sidebar-section">
  <h2>手動新增提案</h2>
  <form method="post" action="/insights/proposal-add" class="prop-add-form" style="flex-direction:column">
    <input type="text" name="title" placeholder="提案標題（要改什麼）" required style="width:100%">
    <input type="text" name="target_area" placeholder="大概動哪個檔" style="width:100%">
    <input type="text" name="rationale" placeholder="理由" style="width:100%">
    <button type="submit" class="button small" style="align-self:flex-start">新增</button>
  </form>
</section>"""

        # 程式調整提案區
        # 顯示全部提案（不再因改狀態而消失）；已完成/不做的排到後面並淡化
        status_order = {"pending": 0, "evaluating": 1, "done": 2, "wontfix": 3}
        proposals_sorted = sorted(proposals, key=lambda p: status_order.get(p.get("status", "pending"), 0))
        prop_status_opts = lambda cur: "".join(
            f'<option value="{s}"{" selected" if s==cur else ""}>{lbl}</option>'
            for s, lbl in [("pending","待評估"),("evaluating","評估中"),("done","已完成"),("wontfix","不做")]
        )
        prop_rows = ""
        for i, p in enumerate(proposals_sorted):
            pid = h(p.get("id", ""))
            done = p.get("status") in {"done", "wontfix"}
            ta_id = f"prompt-prop-{pid}"
            prompt_text = h(build_proposal_prompt(p))
            # 紀錄行
            src_line = ""
            if p.get("source_report"):
                src_line = (f'<div class="muted" style="font-size:0.82em">紀錄：'
                            f'{h(p.get("source_engine","") or "手動")} · {h((p.get("proposed_at","") or "")[:16])} · '
                            f'來源報告 {h(p.get("source_report",""))}</div>')
            # 案例 block
            cases = p.get("source_divergences") or []
            cases_html = ""
            if cases:
                items = ""
                for ci, c in enumerate(cases, 1):
                    title = "；".join(c.get("titles") or []) or "（無標題）"
                    expl = c.get("explanation", "")
                    items += (f'<li>案例 {ci}：《{h(title)}》<br>'
                              f'<span class="muted">AI: {h(c.get("ai",""))} → 你: {h(c.get("user_action",""))}'
                              + (f'（信心度 {h(c.get("confidence"))}）' if c.get("confidence") else "")
                              + '</span>'
                              + (f'<br><span class="muted">你的理由：{h(expl)}</span>' if expl else "")
                              + '</li>')
                cases_html = f'<details class="prop-cases"><summary>對應的 {len(cases)} 筆分歧案例</summary><ul>{items}</ul></details>'
            prop_status_val = h(p.get("status", "pending"))
            prop_rows += f"""
<div class="prop-row{' prop-done' if done else ''}" data-filter-group="proposals" data-prop-status="{prop_status_val}">
  <div><strong>{h(p.get('title',''))}</strong>
    {f"<span class='muted'>· {h(p.get('target_area',''))}</span>" if p.get('target_area') else ''}</div>
  {src_line}
  {f"<div class='muted'>{h(p.get('rationale',''))}</div>" if p.get('rationale') else ''}
  {cases_html}
  <div class="prop-actions">
    <button type="button" class="button small" data-copy="{ta_id}">複製給 AI CLI 的 prompt</button>
    <form method="post" action="/insights/proposal-status" style="display:inline">
      <input type="hidden" name="id" value="{pid}">
      <select name="status" onchange="this.form.submit()">{prop_status_opts(p.get('status','pending'))}</select>
    </form>
  </div>
  <textarea id="{ta_id}" class="copy-src" readonly>{prompt_text}</textarea>
</div>"""
        prop_count = len(proposals_sorted)
        proposals_section = f"""
<section>
  <div class="section-header" data-filter-section="proposals">
    <div class="section-header-left">
      <h2>程式調整提案 <span class="badge badge-gray">{prop_count} 筆</span></h2>
      <p class="section-sub">品味檔接不住的結構性建議，評估後才改程式本體。</p>
    </div>
    <div class="section-filters">
      <button class="filter-pill is-active" data-filter-group="proposals" data-filter-attr="propStatus" data-filter-val="pending,evaluating">進行中</button>
      <button class="filter-pill" data-filter-group="proposals" data-filter-attr="propStatus" data-filter-val="all">全部</button>
      <button class="filter-pill" data-filter-group="proposals" data-filter-attr="propStatus" data-filter-val="pending">待評估</button>
      <button class="filter-pill" data-filter-group="proposals" data-filter-attr="propStatus" data-filter-val="evaluating">評估中</button>
      <button class="filter-pill" data-filter-group="proposals" data-filter-attr="propStatus" data-filter-val="done">✓ 已完成</button>
      <button class="filter-pill" data-filter-group="proposals" data-filter-attr="propStatus" data-filter-val="wontfix">不做</button>
    </div>
  </div>
  {prop_rows or '<p class="muted">目前沒有程式提案。</p>'}
  <p class="filter-empty muted" data-empty-group="proposals" hidden>目前篩選下沒有提案（可能都已完成），點「全部」查看。</p>
</section>"""

        css = """<style>
.div-card{border:1px solid #ddd;border-radius:8px;padding:12px 16px;margin-bottom:12px;background:#fafafa}
.div-card-header{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.div-card-body{margin-bottom:8px;line-height:1.6}
.div-titles{font-weight:500}
.div-title-row{margin:2px 0}
.div-orig-title{font-weight:400;font-size:0.85em}
.div-context{margin:6px 0 2px;line-height:1.6}
.div-meta{font-size:0.82em;margin-bottom:2px}
.div-detail{margin:4px 0}
.div-detail summary{cursor:pointer;font-size:0.85em}
.item-link{color:inherit;text-decoration:underline dotted}
.item-link:hover{text-decoration:underline}
.div-explain-form{display:flex;gap:6px;align-items:center;margin-bottom:4px}
.div-explain-input{flex:1;padding:4px 8px;border:1px solid #ccc;border-radius:4px;font-size:0.9em}
.div-analyzed-waiting{background:#f7f7f7;opacity:0.75;border-color:#e0e0e0}
.div-analyzed-ready{background:#f0faf4;border-color:#b2dfcc}
.div-closed{background:#f8f8f8;opacity:0.6;border-color:#e8e8e8}
.explain-ok{color:#276749;font-size:0.85em;margin-left:4px}
.badge{display:inline-block;border-radius:9px;padding:1px 8px;font-size:0.8em;font-weight:600}
.badge-red{background:#fed7d7;color:#c53030}
.badge-blue{background:#bee3f8;color:#2b6cb0}
.badge-green{background:#c6f6d5;color:#276749}
.badge-gray{background:#e2e8f0;color:#4a5568}
.section-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:12px}
.section-header-left h2{margin:0}
.section-sub{margin:2px 0 0;font-size:0.85em;color:#718096}
.section-filters{display:flex;gap:4px;flex-wrap:wrap;margin-top:2px;flex-shrink:0}
.filter-pill{padding:2px 10px;border-radius:12px;border:1px solid #cbd5e0;background:#fff;color:#4a5568;font-size:0.8em;cursor:pointer;line-height:1.6;font-weight:normal}
.filter-pill:hover{background:#f7fafc;color:#2d3748;border-color:#a0aec0}
.filter-pill.is-active{background:#e9d8fd;border-color:#9f7aea;color:#553c9a;font-weight:600}
.filter-pill.is-active:hover{background:#e9d8fd;color:#553c9a}
.sidebar-actions{display:flex;flex-direction:column;gap:6px}
.report-row{border:1px solid #e2e8f0;border-radius:6px;padding:10px 14px;margin-bottom:8px}
.report-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.report-pre{background:#1e1e2e;color:#e8e8f0;padding:12px;border-radius:4px;white-space:pre-wrap;font-size:0.85em;max-height:420px;overflow-y:auto;line-height:1.55}
.apply-run{border-left:3px solid #6450dc;padding-left:10px;margin:10px 0}
.apply-details{background:#f0fff4;border:1px solid #c6f6d5;border-radius:6px;padding:8px 12px;margin:6px 0}
.apply-details-title{font-weight:600;font-size:0.85em;color:#276749;margin-bottom:4px}
.apply-details ul{margin:0;padding-left:18px;line-height:1.7;font-size:0.88em}
.apply-details a{font-size:0.9em;white-space:nowrap}
.taste-sidebar-list{margin:6px 0 0;padding-left:20px;line-height:1.7;font-size:0.88em}
.prop-row{border:1px solid #e2e8f0;border-radius:6px;padding:8px 12px;margin-bottom:6px;display:flex;flex-direction:column;gap:4px}
.prop-done{opacity:0.5}
.prop-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px}
.copy-src{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}
.prop-add-form{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.prop-add-form input{padding:4px 8px;border:1px solid #ccc;border-radius:4px;font-size:0.9em}
.success-banner{background:#c6f6d5;color:#276749;padding:8px 12px;border-radius:6px;margin-bottom:16px}
.error-banner{background:#fed7d7;color:#c53030;padding:8px 12px;border-radius:6px;margin-bottom:16px}
</style>"""

        apply_poll_js = """<script>
(function(){
  function initInsightPage(){
  // filter-pill 客戶端篩選（僅篩 data-filterable 元素，不篩 pill 本身）
  // 支援多值：data-filter-val="pending,attempted" → 命中集合任一就顯示；"all" → 全顯示。
  function applyFilter(pill){
    var filterGroup = pill.dataset.filterGroup;
    var filterAttr  = pill.dataset.filterAttr;
    var filterVal   = pill.dataset.filterVal;
    var camel = filterAttr.replace(/-([a-z])/g, function(_,c){ return c.toUpperCase(); });
    var allowed = (filterVal==='all') ? null : filterVal.split(',');
    var anyVisible = false;
    document.querySelectorAll('[data-filter-group="'+filterGroup+'"]').forEach(function(el){
      if(el.closest('.section-header')) return;  // 跳過 pill 本身
      el.hidden = (allowed!==null) && (allowed.indexOf(el.dataset[camel]) === -1);
      if(!el.hidden) anyVisible = true;
    });
    var hint = document.querySelector('.filter-empty[data-empty-group="'+filterGroup+'"]');
    if(hint) hint.hidden = anyVisible;
  }
  document.querySelectorAll('.filter-pill').forEach(function(pill){
    pill.addEventListener('click', function(){
      pill.closest('.section-filters').querySelectorAll('.filter-pill')
          .forEach(function(p){ p.classList.toggle('is-active', p===pill); });
      applyFilter(pill);
    });
  });
  // 進頁面即套用每區預設（is-active）篩選，不必先點一下
  document.querySelectorAll('.section-filters').forEach(function(box){
    var active = box.querySelector('.filter-pill.is-active');
    if(active) applyFilter(active);
  });

  // AJAX 動畫：dismiss / close-analyzed / save-explanation / batch-close / sample
  function animateOut(el, then){
    if(!el) return;
    el.style.transition='opacity .3s,max-height .4s,margin .3s,padding .3s';
    el.style.maxHeight=el.scrollHeight+'px';
    requestAnimationFrame(function(){
      el.style.opacity='0'; el.style.maxHeight='0';
      el.style.marginBottom='0'; el.style.paddingTop='0'; el.style.paddingBottom='0';
    });
    setTimeout(function(){ el.remove(); if(then) then(); }, 420);
  }
  function fetchForm(form, opts){
    var btn = form.querySelector('button[type=submit]');
    if(btn && btn.dataset.running==='1') return;
    if(btn){ btn.dataset.running='1'; btn.disabled=true; }
    var body = new URLSearchParams(new FormData(form));
    fetch(form.action, {method:'POST',
      headers:{'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'local-web-fetch'},
      body: body})
    .then(function(r){ return r.json(); })
    .then(function(data){
      if(btn){ btn.dataset.running=''; btn.disabled=false; }
      if(opts && opts.onOk && data && data.ok) opts.onOk(data);
    })
    .catch(function(){ if(btn){ btn.dataset.running=''; btn.disabled=false; } });
  }
  document.querySelectorAll('form[data-ajax-dismiss]').forEach(function(form){
    form.addEventListener('submit', function(ev){
      ev.preventDefault();
      var card = form.closest('[data-card-id]');
      fetchForm(form, {onOk: function(){ animateOut(card); }});
    });
  });
  document.querySelectorAll('form[data-ajax-explain]').forEach(function(form){
    form.addEventListener('submit', function(ev){
      ev.preventDefault();
      var ok = form.querySelector('.explain-ok');
      fetchForm(form, {onOk: function(){
        var badge = form.closest('[data-card-id]').querySelector('.badge-gray,.badge-blue');
        if(badge){ badge.className='badge badge-blue'; badge.textContent='已填說明'; }
        if(ok){ ok.hidden=false; setTimeout(function(){ ok.hidden=true; }, 2000); }
        var card = form.closest('[data-card-id]');
        if(card) card.dataset.divState='explained';
      }});
    });
  });
  document.querySelectorAll('form[data-ajax-sample]').forEach(function(form){
    form.addEventListener('submit', function(ev){
      ev.preventDefault();
      var result = document.getElementById('sample-result');
      fetchForm(form, {onOk: function(data){
        if(result){
          result.style.display='inline';
          result.textContent='已新增 '+data.added+' 筆，重新整理可看到';
        }
        setTimeout(function(){ window.location.reload(); }, 1200);
      }});
    });
  });
  document.querySelectorAll('form[data-ajax-batch-close]').forEach(function(form){
    form.addEventListener('submit', function(ev){
      ev.preventDefault();
      fetchForm(form, {onOk: function(data){
        (data.closed_ids||[]).forEach(function(cid){
          var card = document.querySelector('[data-card-id="'+cid+'"]');
          animateOut(card);
        });
      }});
    });
  });

  var cw = document.getElementById('command-window');
  var ct = document.getElementById('command-title');
  var cs = document.getElementById('command-status');
  var co = document.getElementById('command-output');
  var cl = document.getElementById('command-loading');
  if(!cw) return;
  function openWin(label){
    if(ct) ct.textContent = label || '決策洞察';
    if(cs) cs.textContent = '已送出，正在啟動…';
    if(co){ co.hidden = true; co.textContent=''; }
    if(cl) cl.hidden = false;
    cw.classList.add('is-visible');
    cw.setAttribute('aria-hidden','false');
  }
  var polling = null;
  function startPoll(){
    if(polling) clearInterval(polling);
    polling = setInterval(async function(){
      try{
        var r = await fetch('/api/insight-status', {headers:{'X-Requested-With':'local-web-fetch'}});
        if(!r.ok) return;
        var p = await r.json();
        if(p && p.message && cs) cs.textContent = p.message;
        if(p && (p.state==='done' || p.state==='failed')){
          clearInterval(polling); polling=null;
          if(cl) cl.hidden = true;
          if(p.state==='done'){
            if(cs) cs.textContent = '✓ ' + (p.message||'完成');
            setTimeout(function(){ window.location = p.redirect || '/insights'; }, 1200);
          } else {
            if(cs) cs.textContent = '✗ ' + (p.message||'失敗');
          }
        }
      }catch(e){}
    }, 1200);
  }
  // 複製 prompt 按鈕
  document.querySelectorAll('button[data-copy]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var ta = document.getElementById(btn.getAttribute('data-copy'));
      if(!ta) return;
      var text = ta.value;
      var orig = btn.textContent;
      var ok = function(){ btn.textContent = '✓ 已複製，貼到 AI CLI 即可'; setTimeout(function(){ btn.textContent = orig; }, 2500); };
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(text).then(ok).catch(function(){
          ta.style.position='static'; ta.style.width='100%'; ta.style.height='160px'; ta.style.opacity='1'; ta.select();
          try{ document.execCommand('copy'); ok(); }catch(e){}
        });
      } else {
        ta.style.position='static'; ta.style.width='100%'; ta.style.height='160px'; ta.style.opacity='1'; ta.select();
        try{ document.execCommand('copy'); ok(); }catch(e){}
      }
    });
  });

  document.querySelectorAll('form[data-insight-job]').forEach(function(form){
    form.addEventListener('submit', async function(ev){
      ev.preventDefault();
      var btn = form.querySelector('button');
      if(btn && btn.dataset.running === '1') return;  // 防連點
      var label = form.getAttribute('data-insight-job');
      var origText = btn ? btn.textContent : '';
      if(btn){ btn.dataset.running = '1'; btn.disabled = true; btn.textContent = '執行中…（看右下角進度）'; }
      openWin(label);
      startPoll();
      var restore = function(){ if(btn){ btn.dataset.running=''; btn.disabled=false; btn.textContent=origText; } };
      try{
        var body = new URLSearchParams(new FormData(form));
        body.set('format','json');
        var resp = await fetch(form.action, {method:'POST',
          headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-Requested-With':'local-web-fetch'},
          body: body});
        var data = await resp.json().catch(function(){ return {}; });
        if(data && data.ok === false){
          if(cl) cl.hidden = true;
          if(cs) cs.textContent = '✗ ' + (data.error || '無法啟動');
          if(polling){ clearInterval(polling); polling=null; }
          restore();
        }
        // 成功時不還原按鈕：startPoll 會在 done 後自動重整整頁
      }catch(e){
        if(cl) cl.hidden = true;
        if(cs) cs.textContent = '✗ 送出失敗：' + e;
        if(polling){ clearInterval(polling); polling=null; }
        restore();
      }
    });
  });
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initInsightPage, {once:true});
  } else {
    initInsightPage();
  }
})();
</script>"""

        sidebar_toggle = workspace_sidebar_toggle("insights-workspace", "insights-sidebar", "insights-taste", "品味工具箱")
        body = f"""
{css}
<h1>決策洞察面板</h1>
{banner}
<div class="workspace-toolbar">{sidebar_toggle}</div>
<div class="workspace-layout" id="insights-workspace">
  <section class="workspace-main">
    {cue_section}
    {reports_section}
    {proposals_section}
  </section>
  <aside class="workspace-sidebar" id="insights-sidebar">
    {taste_sidebar}
  </aside>
</div>
{apply_poll_js}
"""
        self.send_html("決策洞察", body)

    def show_taste_profile_editor(self, query: dict) -> None:
        draft_file = ROOT / ".cache" / "taste-edit-draft.txt"
        error_msg = ""
        if (query.get("error") or [None])[0] == "json":
            error_msg = '<div class="error-banner">JSON 格式有誤，請修正後再儲存。</div>'
        draft_val = ""
        if (query.get("draft") or [None])[0] == "1" and draft_file.exists():
            try:
                draft_val = draft_file.read_text(encoding="utf-8")
            except Exception:
                draft_val = ""
        if not draft_val:
            draft_val = json.dumps(load_taste_profile(), ensure_ascii=False, indent=2)
        saved_banner = '<div class="success-banner">✓ 品味檔已儲存。</div>' if (query.get("saved") or [None])[0] == "taste" else ""
        body = f"""
<a href="/insights" style="font-size:0.9em">← 回洞察面板</a>
<h1>編輯品味設定檔</h1>
{saved_banner}
{error_msg}
<p class="muted" style="font-size:0.88em">可修改 <code>global.emphasize</code>、各 track 的 <code>priority_themes</code> / <code>avoid_themes</code>，以及手動 append <code>learned_signals</code>（附 <code>source_report</code>）。</p>
<form method="post" action="/insights/save-taste-profile">
  <textarea name="content" style="width:100%;font-family:monospace;font-size:0.85em;border:1px solid #ccc;border-radius:4px;padding:10px;resize:vertical;background:#fafafa" rows="36" spellcheck="false">{h(draft_val)}</textarea>
  <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
    <button type="submit" class="button">儲存</button>
    <a href="/insights" class="button secondary">取消</a>
  </div>
</form>
"""
        self.send_html("編輯品味檔", body)

    def save_divergence_explanation(self, data: dict[str, list[str]]) -> None:
        div_id = form_value(data, "id")
        explanation = form_value(data, "explanation")
        _patch_divergence(div_id, user_explanation=explanation)
        _maybe_add_personal_beat(div_id, explanation)
        if self.is_async_request():
            self.send_json({"ok": True, "div_id": div_id})
        else:
            self.redirect("/insights")

    def dismiss_divergence(self, data: dict[str, list[str]]) -> None:
        div_id = form_value(data, "id")
        _patch_divergence(div_id, dismissed=True)
        if self.is_async_request():
            self.send_json({"ok": True, "div_id": div_id})
        else:
            self.redirect("/insights")

    def sample_into_cue(self, data: dict[str, list[str]]) -> None:
        added = sample_divergences_into_cue(5)
        if self.is_async_request():
            self.send_json({"ok": True, "added": added})
        else:
            self.redirect(f"/insights?sampled={added}")

    def generate_divergence_report(self, data: dict[str, list[str]], mode: str = "explained") -> None:
        engine = form_value(data, "engine") or "claude"
        if engine not in AI_PROVIDER_META:
            engine = "claude"
        divs = load_jsonl(DECISION_DIVERGENCES)
        # 只分析「已填說明、未略過」的
        candidates = [d for d in divs if not d.get("dismissed") and d.get("user_explanation")]
        if not candidates:
            if self.is_async_request():
                self.send_json({"ok": False, "error": "沒有已填說明的分歧可分析"}, HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/insights?error=no-explained")
            return
        insight_status("running", f"已送出，準備用 {ai_provider_label(engine)} 分析 {len(candidates)} 筆…", engine=engine)
        threading.Thread(target=run_analysis_job, args=(candidates, mode, engine), daemon=True).start()
        if self.is_async_request():
            self.send_json({"ok": True, "message": "分析已開始", "status_url": "/api/insight-status"})
        else:
            self.redirect("/insights")

    def apply_report_with_cli(self, data: dict[str, list[str]]) -> None:
        rpt_id = form_value(data, "id")
        engine = form_value(data, "engine") or "claude"
        if engine not in AI_PROVIDER_META:
            engine = "claude"
        report = next((r for r in load_jsonl(INSIGHT_REPORTS) if r.get("id") == rpt_id), None)
        if not report:
            if self.is_async_request():
                self.send_json({"ok": False, "error": "找不到報告"}, HTTPStatus.NOT_FOUND)
            else:
                self.redirect("/insights?error=no-report")
            return
        insight_status("running", f"已送出，準備用 {ai_provider_label(engine)} 研究報告…", engine=engine, report_id=rpt_id)
        threading.Thread(target=run_apply_job, args=(report, engine), daemon=True).start()
        if self.is_async_request():
            self.send_json({"ok": True, "message": "實作已開始", "status_url": "/api/insight-status"})
        else:
            self.redirect("/insights")

    def mark_report_implemented(self, data: dict[str, list[str]]) -> None:
        rpt_id = form_value(data, "id")
        notes = form_value(data, "notes")
        _patch_report(rpt_id, implementation_status="implemented", implemented_at=now_iso(), implementation_notes=notes)
        self.redirect("/insights")

    def proposal_add(self, data: dict[str, list[str]]) -> None:
        title = form_value(data, "title")
        if not title:
            self.redirect("/insights")
            return
        append_jsonl(SYSTEM_CHANGE_PROPOSALS, {
            "id": _proposal_id(),
            "proposed_at": now_iso(),
            "source_report": form_value(data, "source_report"),
            "title": title,
            "rationale": form_value(data, "rationale"),
            "target_area": form_value(data, "target_area"),
            "status": "pending",
            "notes": "",
        })
        self.redirect("/insights")

    def proposal_status(self, data: dict[str, list[str]]) -> None:
        prop_id = form_value(data, "id")
        status = form_value(data, "status") or "pending"
        _patch_proposal(prop_id, status=status)
        self.redirect("/insights")

    def close_analyzed_divergence(self, data: dict[str, list[str]]) -> None:
        div_id = form_value(data, "id")
        _patch_divergence(div_id, dismissed=True)
        if self.is_async_request():
            self.send_json({"ok": True, "div_id": div_id})
        else:
            self.redirect("/insights")

    def close_all_resolved_divergences(self, _data: dict[str, list[str]]) -> None:
        divs = load_jsonl(DECISION_DIVERGENCES)
        reports = load_jsonl(INSIGHT_REPORTS)
        proposals = load_jsonl(SYSTEM_CHANGE_PROPOSALS)
        closed_ids = []
        for div in divs:
            if div.get("dismissed") or not div.get("included_in_analysis_at"):
                continue
            if not _has_pending_proposals_for_divergence(div["id"], reports, proposals):
                _patch_divergence(div["id"], dismissed=True)
                closed_ids.append(div["id"])
        if self.is_async_request():
            self.send_json({"ok": True, "closed_ids": closed_ids})
        else:
            self.redirect("/insights")

    def save_taste_profile_edit(self, data: dict[str, list[str]]) -> None:
        raw = form_value(data, "content") or ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            draft_file = ROOT / ".cache" / "taste-edit-draft.txt"
            try:
                draft_file.write_text(raw, encoding="utf-8")
            except Exception:
                pass
            self.redirect("/insights/edit-taste-profile?error=json&draft=1")
            return
        TASTE_PROFILE.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        self.redirect("/insights/edit-taste-profile?saved=taste")

    def show_article_editor(self, query: dict[str, list[str]]) -> None:
        article_id = clean_text((query.get("id") or [""])[0])
        article = next((a for a in load_articles() if clean_text(a.get("id")) == article_id), None)
        if not article:
            self.send_html("找不到", "<h1>找不到這篇專文</h1><p><a href='/editor'>回編輯台</a></p>", HTTPStatus.NOT_FOUND)
            return
        article = normalize_article_record(article)  # 不存檔，只為顯示補齊欄位
        item_ids = article.get("item_ids") or []
        viewpoint_ids = article.get("viewpoint_ids") or []
        body = article.get("body_markdown") or ""  # 原始 markdown，不可走 clean_text

        lookup = editor_item_lookup()
        available_payload = [editor_material_payload(record) for record in editor_search_items()[:350]]
        selected_payload = []
        for item_id in item_ids:
            rec = lookup.get(item_id)
            selected_payload.append(
                editor_material_payload(rec) if rec else {"id": item_id, "title": item_id, "trackLabel": "（已不在材料池）", "tags": []}
            )
        viewpoints = load_jsonl(VIEWPOINTS)
        vp_by_id = {clean_text(v.get("id")): v for v in viewpoints}
        vp_all_payload = [viewpoint_payload(v) for v in viewpoints]
        selected_vp_payload = [viewpoint_payload(vp_by_id[i]) for i in viewpoint_ids if i in vp_by_id]

        def js_json(value: object) -> str:
            return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")

        state_json = js_json(
            {
                "id": article["id"],
                "title": article["title"],
                "track": article["track"],
                "status": article["status"],
                "license": item_license_name(article),
                "tags": article["tags"],
                "item_ids": item_ids,
                "viewpoint_ids": viewpoint_ids,
            }
        )

        tracks = (load_json(DATABASE / "taxonomy.json") or {}).get("tracks", {})
        track_options = "".join(
            f'<option value="{h(key)}"{" selected" if key == article["track"] else ""}>{h(meta.get("name_zh", key))}</option>'
            for key, meta in tracks.items()
        )
        status_options = "".join(
            f'<option value="{h(key)}"{" selected" if key == article["status"] else ""}>{h(label)}</option>'
            for key, label in ARTICLE_STATUS_LABELS.items()
        )
        current_license = item_license_name(article)
        license_options = option_list([("", "未設定授權")] + [(name, name) for name in taxonomy_license_names()], current_license)
        all_tags = sorted({clean_text(t) for rec in load_jsonl(ITEMS) for t in (rec.get("tags") or []) if clean_text(t)})
        tag_controls = tag_picker_controls_html(article.get("tags") or [], [], all_tags, placeholder="搜尋或新增 tag")

        factcheck = article.get("factcheck") or {}
        claims = factcheck.get("claims") or []
        claim_rows = ""
        for claim in claims:
            label, cls = factcheck_status_label(claim.get("status"))
            note = clean_text(claim.get("note"))
            claim_rows += (
                f'<div class="article-claim"><span class="badge {h(cls)}">{h(label)}</span> '
                f'{h(clean_text(claim.get("claim")))}'
                + (f'<p>{h(note)}</p>' if note else "")
                + "</div>"
            )
        if not claims:
            claim_rows = '<p class="muted">這篇還沒有查核守則。按「重新查核」用三引擎上網找原文核對後，會把結果整理成檢核清單。</p>'
        overall_note = clean_text(factcheck.get("overall_note"))
        overall_html = f'<p class="muted">查核總結：{h(overall_note)}</p>' if overall_note else ""

        latest = latest_factcheck_for_items(item_ids)
        stored_sid = clean_text(factcheck.get("source_session_id"))
        refresh_banner = ""
        if latest and clean_text(latest.get("id")) != stored_sid:
            refresh_banner = (
                '<form method="post" action="/articles/refresh-factcheck" class="article-refresh-banner">'
                f'<input type="hidden" name="id" value="{h(article["id"])}">'
                '<p class="muted">偵測到更新的查核紀錄。</p>'
                f'<button type="submit" class="button button-small secondary">{button_content("套用最新查核結果", "refresh")}</button></form>'
            )
        factcheck_link = ""
        if stored_sid:
            factcheck_link = f'<p class="muted"><a href="/editor/session?id={quote(stored_sid)}">查看來源查核紀錄 →</a></p>'

        source_session = clean_text(article.get("source_session_id"))
        back_href = f"/editor/session?id={quote(source_session)}" if source_session else "/editor"

        body_html = f"""
{back_nav_html(self.same_origin_referer_path(back_href), "回編輯歷程")}
<section class="article-editor">
  <div class="article-main">
    <div class="card">
      <div class="section-kicker">編修台 · 專文</div>
      <input type="text" id="article-title" class="article-title-input" value="{h(article["title"])}" placeholder="專文標題">
      <p class="article-saved"><span id="article-saved-label">自動儲存：編輯後約 1 秒存檔</span></p>
    </div>
    <div class="card easymde-host">
      <textarea id="article-body">{h(body)}</textarea>
    </div>
  </div>
  <aside class="article-sidebar">
    <div class="card">
      <h2>事實查核守則</h2>
      <p class="help">建立這篇時，已快照同組材料最近一次查核的結論。順稿時對照，別寫翻已經查核過的地方。</p>
      {refresh_banner}
      {overall_html}
      {claim_rows}
      <div class="button-row">
        <button type="button" id="article-recheck" class="button button-small" data-engine="random">{button_content("重新查核這版", "wand")}</button>
      </div>
      {factcheck_link}
    </div>
    <div class="card">
      <h2>引用材料</h2>
      <p class="help">這篇引用哪些材料。搜尋後加入，不用手填 id。</p>
      <div class="article-search-row"><input type="search" id="article-material-search" placeholder="搜尋材料標題、來源或 tag"></div>
      <div class="article-search-results" id="article-material-results"><p class="muted">輸入關鍵字搜尋材料。</p></div>
      <h3>已引用</h3>
      <div class="article-pick-list" id="article-material-list"></div>
    </div>
    <div class="card">
      <h2>關聯觀點</h2>
      <p class="help">把這篇連到觀點庫裡的觀點，方便日後雙向追蹤。</p>
      <div class="article-search-row"><input type="search" id="article-viewpoint-search" placeholder="搜尋觀點"></div>
      <div class="article-search-results" id="article-viewpoint-results"><p class="muted">輸入關鍵字搜尋觀點。</p></div>
      <h3>已關聯</h3>
      <div class="article-pick-list" id="article-viewpoint-list"></div>
    </div>
    <div class="card">
      <h2>分類與狀態</h2>
      <label class="article-field" for="article-track">主線</label>
      <select id="article-track">{track_options}</select>
      <label class="article-field" for="article-status" style="margin-top:10px;">狀態</label>
      <select id="article-status">{status_options}</select>
      <label class="article-field" for="article-license" style="margin-top:10px;">授權</label>
      <select id="article-license">{license_options}</select>
      <p class="help" style="margin-top:6px;">狀態設為「已發布」並按首頁的「更新線上閱讀版」後，會產出公開線上版：<br><a href="{h(public_reader_feature_url(article))}" target="_blank" rel="noopener">{h(public_reader_feature_url(article))}</a></p>
      <h3 style="margin-top:12px;">標籤</h3>
      <form data-tag-picker data-article-tags class="tag-picker" onsubmit="return false">{tag_controls}</form>
    </div>
  </aside>
</section>
<link rel="stylesheet" href="/reader/assets/vendor/easymde.min.css">
<script src="/reader/assets/vendor/easymde.min.js"></script>
{ARTICLE_EDITOR_CSS}
{EASYMDE_TOOLBAR_CSS}
{EASYMDE_TOOLBAR_ICON_JS}
<script type="application/json" id="article-state">{state_json}</script>
<script type="application/json" id="article-available-materials">{js_json(available_payload)}</script>
<script type="application/json" id="article-selected-materials">{js_json(selected_payload)}</script>
<script type="application/json" id="article-viewpoints-all">{js_json(vp_all_payload)}</script>
<script type="application/json" id="article-selected-viewpoints">{js_json(selected_vp_payload)}</script>
{ARTICLE_EDITOR_JS}
"""
        self.send_html("編修台", body_html)

    # ------------------------------------------------------------------ #
    # 專文：展示索引與成果頁
    # ------------------------------------------------------------------ #
    def show_articles_index(self, query: dict[str, list[str]]) -> None:
        articles = load_articles()
        articles.sort(key=lambda a: clean_text(a.get("updated_at")), reverse=True)
        track_filter = clean_text((query.get("track") or ["all"])[0]) or "all"
        status_filter = clean_text((query.get("status") or ["all"])[0]) or "all"
        license_filter = clean_text((query.get("license") or ["all"])[0]) or "all"
        tag_filter = clean_text((query.get("tag") or [""])[0])

        def matches(a: dict) -> bool:
            if track_filter != "all" and clean_text(a.get("track")) != track_filter:
                return False
            if status_filter != "all" and clean_text(a.get("status")) != status_filter:
                return False
            if license_filter != "all" and item_license_name(a) != license_filter:
                return False
            if tag_filter and tag_filter not in [clean_text(t) for t in (a.get("tags") or [])]:
                return False
            return True

        visible = [a for a in articles if matches(a)]
        tracks = (load_json(DATABASE / "taxonomy.json") or {}).get("tracks", {})
        track_opts = '<option value="all">全部主線</option>' + "".join(
            f'<option value="{h(k)}"{" selected" if k == track_filter else ""}>{h(m.get("name_zh", k))}</option>'
            for k, m in tracks.items()
        )
        status_opts = '<option value="all">全部狀態</option>' + "".join(
            f'<option value="{h(k)}"{" selected" if k == status_filter else ""}>{h(v)}</option>'
            for k, v in ARTICLE_STATUS_LABELS.items()
        )
        license_opts = option_list(license_filter_options(articles), license_filter)

        cards = ""
        for a in visible:
            art_id = clean_text(a.get("id"))
            status_label = ARTICLE_STATUS_LABELS.get(clean_text(a.get("status")), clean_text(a.get("status")))
            track_short = track_meta(a.get("track", "unclassified"))["short"]
            tag_html = "".join(f'<span class="tag-pill">{h(t)}</span>' for t in (a.get("tags") or [])[:6])
            summary = clean_text(article_title_from_markdown(a.get("body_markdown") or ""))
            body_preview = clean_text(re.sub(r"[#>*`_\-]+", " ", a.get("body_markdown") or ""), 140)
            cards += f"""
<a class="article-index-card" href="/articles/view?id={quote(art_id)}">
  <div class="article-index-meta">{badge(status_label, "neutral")}{badge(track_short, track_class(a.get("track", "unclassified")))}{license_badge_html(a)}<span class="muted">{h(editor_relative_time(a.get("updated_at")))}</span></div>
  <h3>{h(a.get("title"))}</h3>
  <p class="muted">{h(body_preview)}</p>
  <div class="article-index-tags">{tag_html}</div>
</a>"""
        default_layout = "card" if len(visible) <= 12 else "list"
        if not visible:
            cards = '<p class="muted">還沒有符合條件的專文。到編輯台跑出草稿後，在編輯歷程頁按「編修成專文」。</p>'

        body = f"""
{back_nav_html(self.same_origin_referer_path("/editor"))}
<section class="card">
  <div class="section-kicker">編輯台 · 成果</div>
  <h1>{icon_span("text-lines")}專文</h1>
  <p class="lede">經過編輯台與編修台順稿、查核後的成果文章。每篇都連到引用的材料與關聯觀點。</p>
  <form method="get" action="/articles" class="article-index-filters">
    <select name="track" class="auto-filter" onchange="this.form.submit()">{track_opts}</select>
    <select name="status" class="auto-filter" onchange="this.form.submit()">{status_opts}</select>
    <select name="license" class="auto-filter" onchange="this.form.submit()">{license_opts}</select>
    {f'<input type="hidden" name="tag" value="{h(tag_filter)}">' if tag_filter else ''}
    <span class="muted">共 {len(visible)} 篇{f"・標籤：{h(tag_filter)}" if tag_filter else ""}</span>
    <span style="margin-left:auto;">{layout_toggle("articles-grid", default_layout)}</span>
  </form>
</section>
<div id="articles-grid" data-layout="{default_layout}" class="article-index-grid">{cards}</div>
<style>
  .article-index-filters {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:10px; }}
  .article-index-filters select {{ padding:7px 9px; border-radius:8px; border:1px solid var(--border,#cbd5e1); font:inherit; }}
  .article-index-grid[data-layout="card"] {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:14px; margin-top:16px; }}
  .article-index-grid[data-layout="list"] {{ display:flex; flex-direction:column; gap:10px; margin-top:16px; }}
  .article-index-grid[data-layout="compact"] {{ display:flex; flex-direction:column; gap:4px; margin-top:16px; }}
  .article-index-card {{ display:block; border:1px solid var(--line,#e2e8f0); border-radius:12px; padding:14px 16px; background:#fff; text-decoration:none; color:inherit; }}
  .article-index-card:hover {{ background:var(--soft,#f1f5f9); }}
  .article-index-card h3 {{ margin:8px 0 6px; }}
  .article-index-meta {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
  .article-index-tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
  .article-index-grid[data-layout="compact"] .article-index-card p, .article-index-grid[data-layout="compact"] .article-index-tags {{ display:none; }}
</style>
"""
        self.send_html("專文", body)

    def show_article_view(self, query: dict[str, list[str]]) -> None:
        article_id = clean_text((query.get("id") or [""])[0])
        article = next((a for a in load_articles() if clean_text(a.get("id")) == article_id), None)
        if not article:
            self.send_html("找不到", "<h1>找不到這篇專文</h1><p><a href='/articles'>回專文列表</a></p>", HTTPStatus.NOT_FOUND)
            return
        article = normalize_article_record(article)
        lookup = editor_item_lookup()
        material_rows = ""
        for item_id in article.get("item_ids") or []:
            rec = lookup.get(item_id)
            if rec:
                material_rows += f'<li><a href="/items/view?id={quote(item_id)}">{h(editor_item_title(rec))}</a></li>'
            else:
                material_rows += f'<li><code>{h(item_id)}</code> <span class="muted">（已不在材料池）</span></li>'
        vp_by_id = {clean_text(v.get("id")): v for v in load_jsonl(VIEWPOINTS)}
        viewpoint_rows = ""
        for vp_id in article.get("viewpoint_ids") or []:
            vp = vp_by_id.get(vp_id)
            title = clean_text(vp.get("title")) if vp else vp_id
            viewpoint_rows += f'<li><a href="/editor/viewpoints?focus={quote(vp_id)}">{h(title or vp_id)}</a></li>'
        status_label = ARTICLE_STATUS_LABELS.get(clean_text(article.get("status")), clean_text(article.get("status")))
        track_short = track_meta(article.get("track", "unclassified"))["short"]
        tag_html = "".join(f'<a class="tag-pill" href="/tags?tag={quote(t)}">{h(t)}</a>' for t in (article.get("tags") or []))
        source_session = clean_text(article.get("source_session_id"))
        source_link = f'<a href="/editor/session?id={quote(source_session)}">原始編輯歷程 →</a>' if source_session else ""
        license_table = license_attribution_table_html(article)
        license_side = (
            f'<div class="card"><h2>授權標示</h2><p>{license_badge_html(article)}</p>{license_table}</div>'
            if item_license_name(article)
            else ""
        )
        body_html = markdown_to_html(article.get("body_markdown") or "（尚無內容）")
        hero_url, hero_credit = feature_hero_image(article, lookup)
        hero_html = (
            f'<figure class="article-hero"><img src="{h(hero_url)}" alt="" loading="lazy">'
            f'<figcaption>圖片援引自：{h(hero_credit)}</figcaption></figure>'
            if hero_url
            else ""
        )

        body = f"""
{back_nav_html(self.same_origin_referer_path("/articles"), "回專文列表")}
<section class="article-view">
  <div class="article-view-main">
    <div class="card">
      <div class="article-index-meta">{badge(status_label, "neutral")}{badge(track_short, track_class(article.get("track", "unclassified")))}{license_badge_html(article)}<span class="muted">更新於 {h(editor_relative_time(article.get("updated_at")))}</span></div>
      <h1>{h(article.get("title"))}</h1>
      <div class="article-view-tags">{tag_html}</div>
      <div class="button-row" style="margin-top:10px;">
        <a class="button" href="/articles/edit?id={quote(article_id)}">{button_content("進編修台編輯", "edit")}</a>
        {f'<a class="button secondary" href="{h(public_reader_feature_url(article))}" target="_blank" rel="noopener">{button_content("看線上版", "globe")}</a>' if clean_text(article.get("status")) == "published" else ""}
      </div>
      {'' if clean_text(article.get("status")) == "published" else '<p class="muted">狀態設為「已發布」並更新線上閱讀版後，會有公開線上版。</p>'}
    </div>
    {hero_html}
    <article class="card editor-output article-markdown">{body_html}</article>
  </div>
  <aside class="article-view-side">
    <div class="card">
      <h2>引用材料</h2>
      <ul>{material_rows or '<li class="muted">（無）</li>'}</ul>
    </div>
    <div class="card">
      <h2>關聯觀點</h2>
      <ul>{viewpoint_rows or '<li class="muted">（無）</li>'}</ul>
    </div>
    {license_side}
    {f'<div class="card"><p class="muted">{source_link}</p></div>' if source_link else ''}
  </aside>
</section>
<style>
  .article-view {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(260px,320px); gap:16px; align-items:start; }}
  .article-view-main, .article-view-side {{ display:grid; gap:14px; }}
  .article-hero {{ margin:0; }}
  .article-hero img {{ width:100%; max-height:360px; object-fit:cover; border-radius:10px; display:block; border:1px solid var(--line,#e2e8f0); }}
  .article-hero figcaption {{ margin-top:6px; font-size:12px; color:var(--muted,#64748b); }}
  .article-view-tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
  .article-view-side ul {{ margin:0; padding-left:18px; }}
  .article-view-side li {{ margin:4px 0; }}
  @media (max-width:900px) {{ .article-view {{ grid-template-columns:1fr; }} }}
</style>
"""
        self.send_html(clean_text(article.get("title"), 60) or "專文", body)

    def search_suggest(self, query: dict[str, list[str]]) -> None:
        q = clean_text((query.get("q") or [""])[0])
        results = collect_search_results(q, per_type=5)
        groups = []
        for type_key in SEARCH_TYPE_ORDER:
            rows = results.get(type_key) or []
            if not rows:
                continue
            groups.append(
                {
                    "type": type_key,
                    "icon": icon_span(SEARCH_TYPE_META[type_key]["icon"]),
                    "label": SEARCH_TYPE_META[type_key]["label"],
                    "results": [{"title": r["title"], "subtitle": r["subtitle"], "href": r["href"], "icon": r["icon"]} for r in rows],
                }
            )
        self.send_json({"q": q, "groups": groups})

    def show_search(self, query: dict[str, list[str]]) -> None:
        q = clean_text((query.get("q") or [""])[0])
        time_filter = clean_text((query.get("time") or ["all"])[0]) or "all"
        if time_filter not in {key for key, _ in SEARCH_TIME_FILTERS}:
            time_filter = "all"
        start_value = clean_text((query.get("start") or [""])[0])
        end_value = clean_text((query.get("end") or [""])[0])
        start_dt, end_dt = reader_time_bounds(time_filter, start_value, end_value)
        results = collect_search_results(q, per_type=60, start=start_dt, end=end_dt)
        total = sum(len(v) for v in results.values())
        chips = ""
        sections = ""
        for type_key in SEARCH_TYPE_ORDER:
            rows = results.get(type_key) or []
            if not rows:
                continue
            meta = SEARCH_TYPE_META[type_key]
            icon = icon_span(meta["icon"])
            chips += f'<a class="search-chip" href="#search-sec-{type_key}">{icon}{h(meta["label"])} {len(rows)}</a>'
            default_layout = "card" if len(rows) <= 12 else "list"
            cards = "".join(search_result_card(r) for r in rows)
            sections += f"""
<section class="search-section" id="search-sec-{type_key}">
  <div class="search-section-head">
    <h2>{icon}{h(meta["label"])} <span class="muted">{len(rows)}</span></h2>
    {layout_toggle(f"search-{type_key}", default_layout)}
  </div>
  <div id="search-{type_key}" data-layout="{default_layout}" class="search-results">{cards}</div>
</section>"""
        if not q:
            sections = '<p class="muted">在上方搜尋框輸入關鍵字。</p>'
        elif total == 0:
            sections = f'<p class="muted">找不到符合「{h(q)}」的結果。</p>'

        time_options = "".join(
            f'<option value="{h(key)}"{" selected" if key == time_filter else ""}>{h(label)}</option>'
            for key, label in SEARCH_TIME_FILTERS
        )
        custom_hidden = "" if time_filter == "custom" else " hidden"
        body = f"""
{back_nav_html(self.same_origin_referer_path("/"))}
<section class="card">
  <h1>{icon_span("filter")}搜尋結果</h1>
  <form method="get" action="/search" class="search-page-form" id="search-form" role="search" autocomplete="off">
    <div class="search-input-line">
      <div class="search-input-wrap">
        <input type="search" name="q" id="search-page-input" value="{h(q)}" placeholder="搜尋標籤、材料、觀點、編輯歷程、RSS、專文" aria-label="全站搜尋" data-omnibar-input data-omnibar-box="search-page-suggest" autofocus>
        <div class="omnibar-suggest" id="search-page-suggest" role="listbox" hidden></div>
      </div>
      <button type="submit" class="button">{button_content("搜尋", "filter")}</button>
    </div>
    <div class="search-time-row">
      <label class="search-time-label">時間範圍
        <select name="time" id="search-time-select">{time_options}</select>
      </label>
      <span class="search-custom-range"{custom_hidden}>
        <input type="date" name="start" value="{h(start_value)}" aria-label="起始日期">
        <span>—</span>
        <input type="date" name="end" value="{h(end_value)}" aria-label="結束日期">
      </span>
    </div>
  </form>
  {f'<p class="muted">「{h(q)}」共 {total} 筆結果{("・" + h(reader_time_summary(time_filter, start_value, end_value))) if time_filter != "all" else ""}</p><div class="search-chips">{chips}</div>' if q and total else ''}
</section>
{sections}
<style>
  .search-page-form {{ margin-top:10px; }}
  .search-input-line {{ display:flex; gap:8px; align-items:flex-start; }}
  .search-input-wrap {{ position:relative; flex:1; }}
  .search-input-wrap input {{ width:100%; box-sizing:border-box; padding:9px 12px; border-radius:10px; border:1px solid var(--border,#cbd5e1); font:inherit; }}
  .search-input-wrap input:focus {{ border-color:var(--ocf-primary,#6450dc); outline:none; box-shadow:0 0 0 3px rgba(100,80,220,0.15); }}
  .search-time-row {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:10px; }}
  .search-time-label {{ display:flex; align-items:center; gap:6px; font-size:13px; color:var(--muted,#64748b); }}
  .search-time-row select, .search-custom-range input {{ padding:6px 9px; border-radius:8px; border:1px solid var(--border,#cbd5e1); font:inherit; }}
  .search-custom-range {{ display:inline-flex; align-items:center; gap:6px; }}
  .search-chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
  .search-chip {{ display:inline-flex; align-items:center; gap:5px; text-decoration:none; padding:4px 10px; border-radius:999px; border:1px solid var(--line,#e2e8f0); background:#fff; color:inherit; font-size:13px; }}
  .search-chip:hover {{ background:var(--soft,#f1f5f9); }}
  .search-chip .icon, .search-section-head .icon {{ width:18px; height:18px; background:transparent; }}
  .search-section {{ margin-top:22px; }}
  .search-section-head {{ display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }}
  .search-section-head h2 {{ display:flex; align-items:center; gap:7px; }}
  .search-results[data-layout="card"] {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px; margin-top:12px; }}
  .search-results[data-layout="list"], .search-results[data-layout="compact"] {{ display:flex; flex-direction:column; gap:8px; margin-top:12px; }}
  .search-card {{ display:flex; gap:10px; align-items:flex-start; border:1px solid var(--line,#e2e8f0); border-radius:10px; padding:10px 12px; background:#fff; text-decoration:none; color:inherit; }}
  .search-card:hover {{ background:var(--soft,#f1f5f9); }}
  .search-card-icon {{ display:inline-flex; flex:0 0 auto; }}
  .search-card-icon .icon {{ width:20px; height:20px; background:transparent; }}
  .search-card-main {{ display:flex; flex-direction:column; gap:4px; min-width:0; }}
  .search-card-title {{ font-weight:600; }}
  .search-card-sub {{ font-size:13px; color:var(--muted,#64748b); }}
  .search-card-badges {{ display:flex; flex-wrap:wrap; gap:5px; }}
  .search-results[data-layout="compact"] .search-card-sub, .search-results[data-layout="compact"] .search-card-badges {{ display:none; }}
</style>
<script>
(function() {{
  var form = document.getElementById('search-form');
  var sel = document.getElementById('search-time-select');
  var range = form ? form.querySelector('.search-custom-range') : null;
  if (sel) sel.addEventListener('change', function() {{
    if (sel.value === 'custom') {{ if (range) range.hidden = false; return; }}
    if (form) form.submit();
  }});
  if (form) form.querySelectorAll('.search-custom-range input[type="date"]').forEach(function(inp) {{
    inp.addEventListener('change', function() {{ form.submit(); }});
  }});
}})();
</script>
"""
        self.send_html("搜尋", body)

    def show_home(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        candidates = load_jsonl(CANDIDATES)
        sources = load_jsonl(SOURCES)
        candidates = load_jsonl(CANDIDATES)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        skill_candidates = [item for item in items if is_skill_candidate(item)]
        direct_pr_items = [item for item in items if is_direct_pr_item(item)]
        reader_items = [item for item in items if is_reader_item(item)]
        pending_review_items = [*candidates, *inbox_items]
        pending_counts = Counter(candidate_recommendation(item) for item in pending_review_items)
        recycle_items = recycle_records()
        recycle_type_counts = Counter(item.get("_recycle_origin") for item in recycle_items)
        notice = ""
        if query.get("saved"):
            notice = '<div class="notice">已儲存。</div>'
        data_commit_status = load_json(DATA_COMMIT_STATUS)
        data_commit_message_text = clean_text(data_commit_status.get("message")) or "自動 commit 排程會在 local web 執行期間每 30 分鐘檢查一次。"
        data_commit_next = clean_text(data_commit_status.get("next_run_at")) or "尚未排程"
        data_commit_last = clean_text(data_commit_status.get("updated_at")) or "尚未記錄"
        host = self.headers.get("Host", "127.0.0.1:8765")
        bookmarklet = (
            f"javascript:location.href='http://{host}/items/new?url='"
            "+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)"
        )
        track_cards = []
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge"]:
            meta = track_meta(track)
            css_class = track_class(track)
            total_items = count_items(items, track)
            pending_items = sum(1 for item in pending_review_items if item.get("track") == track)
            source_count = count_sources(sources, track)
            fetchable_count = count_sources(sources, track, active_only=True)
            button_class = f"button-{css_class}" if css_class in {"opentech", "humanities"} else "secondary"
            track_cards.append(
                f"""
  <section class="card track-card track-card--{h(css_class)}">
    <div>
      {badge(meta["short"], css_class)}
      <h2>{h(meta["label"])}</h2>
      <p class="muted">{h(meta["description"])}</p>
    </div>
    <div class="metric-row">
      {metric_tile(total_items, "全部", f"/track/{quote(track)}", "主線")}
      {metric_tile(pending_items, "待整理", href_with_query("/items", [("track", track)]), "篩選")}
      {metric_tile(source_count, "來源", href_with_query("/sources", [("track", track)]), "看來源")}
      {metric_tile(fetchable_count, "自動抓", href_with_query("/sources", [("track", track), ("status", "active")]), "啟用")}
    </div>
    <div class="button-row reader-card-actions">
      <a class="button {h(button_class)}" href="/track/{quote(track)}">{h(meta["entry"])}</a>
      <a class="button secondary" href="/sources?track={quote(track)}">看這類 RSS 來源</a>
    </div>
    <p class="help">第一顆按鈕是看這條主線的待整理資料；第二顆是檢查這條主線目前追蹤哪些網站或 feed。</p>
  </section>
"""
            )
        command_cards = [command_card(name, config) for name, config in COMMANDS.items()]
        integrity_count = database_integrity_report()["count"]
        body = f"""
<h1>共通入口</h1>
<p class="lede">這裡是每天 RSS 自動抓取、手動收藏、資料檢查與兩條知識主線的起點。資料正本仍在 GitHub 裡的 JSONL，網頁只是讓你比較好操作。</p>
{notice}
<div class="track-grid">{''.join(track_cards)}</div>
<h2>共用工具</h2>
<div class="grid">
  <div class="card">
    <h3>看到好頁面</h3>
    <p class="muted">把這顆拖到瀏覽器書籤列。之後看到想記下來的頁面，點書籤就會開出「手動入庫」表單。</p>
    <p><a class="button" href="{h(bookmarklet)}">做成瀏覽器收藏按鈕</a></p>
    <p class="help">這不會直接發布內容，只是先放進入庫建檔區。</p>
  </div>
  <div class="card">
    <h3>入庫建檔區</h3>
    <p class="muted">每天 RSS 新進與手動收藏材料都在這裡分流。</p>
    <div class="metric-row">
      {metric_tile(len(pending_review_items), "全部", "/items", "打開")}
      {metric_tile(pending_counts.get("suggest-keep", 0), "建議收", "/items?recommendation=suggest-keep", "只看")}
      {metric_tile(pending_counts.get("suggest-skip", 0), "不看", "/items?recommendation=suggest-skip", "只看")}
    </div>
    <p><a class="button" href="/items">打開入庫建檔區</a></p>
    <p class="help">確認收會進可用材料區，不收會移出主資料庫並保留到學習檔，純小消息可直接標記送 PR。</p>
  </div>
  <div class="card">
    <h3>資源回收區</h3>
    <p class="muted">集中查看已按過不收或 RSS 階段略過的歷史紀錄。</p>
    <div class="metric-row">
      {metric_tile(len(recycle_items), "全部不收", "/recycle-bin", "打開")}
      {metric_tile(recycle_type_counts.get("dismissed", 0), "RSS 略過", "/recycle-bin?origin=dismissed", "只看")}
    </div>
    <p><a class="button secondary" href="/recycle-bin">打開資源回收區</a></p>
    <p class="help">需要重看時，可從這裡把單篇重新收錄回入庫建檔區。</p>
  </div>
  <div class="card">
    <h3>可用材料區</h3>
    <p class="muted">只放你已確認收下、可丟進編輯台整理成 article 的材料。</p>
    <div class="metric-row">
      {metric_tile(len(skill_candidates), "可進編輯台", "/candidates", "打開")}
      {metric_tile(len(direct_pr_items), "直送 PR", "/reader?kind=small-news&time=all", "小消息")}
    </div>
    <p><a class="button" href="/candidates">打開可用材料區</a></p>
    <p class="help">RSS 新資料與推薦收藏材料請先在入庫建檔區處理；純小消息可在同一頁直接標記送 PR。</p>
  </div>
  <div class="card">
    <h3>閱讀區</h3>
    <p class="muted">閱讀已確認收下的材料與小消息，並補你的個人觀點。</p>
    <div class="metric-row">
      {metric_tile(len(reader_items), "可閱讀", "/reader?time=all", "看全部")}
    </div>
    <p><a class="button" href="/reader">打開閱讀區</a></p>
    <p class="help">在閱讀區可寫「我的關鍵紀錄」，也能把好文章重新送回 skill 依你的觀點改寫。</p>
  </div>
  <div class="card">
    <h3>新增 RSS 來源</h3>
    <p class="muted">看到值得長期追蹤的網站、Google 快訊、YouTube 或 Podcast，就先加到來源資料庫。</p>
    <p><a class="button secondary" href="/sources/new">新增一個 RSS</a></p>
    <p class="help">新增後每天 12:00、18:00、23:00 的流程才會有機會抓到它。</p>
  </div>
  <div class="card">
    <h3>調整關鍵字</h3>
    <p class="muted">兩條主線各有「建議收」與「建議不要看」關鍵字，可隨時改。</p>
    <p><a class="button quiet" href="/keywords">編輯篩選關鍵字</a></p>
    <p class="help">改完後，下一次 RSS 抓取就會套用新的判斷。</p>
  </div>
  <div class="card">
    <h3>全部 RSS 來源</h3>
    <p class="muted">依主線、來源類型、來源群組查看目前追蹤中的網站，也可以進去編輯或暫停。</p>
    <p><a class="button quiet" href="/sources">打開來源列表</a></p>
    <p class="help">長網址會自動換行，不會把表格撐爆。</p>
  </div>
  <div class="card">
    <h3>閱讀資料庫狀態</h3>
    <p class="muted">固定保護本機編輯狀態，只送出 items、review-events、sources 三個資料檔。</p>
    <form method="post" action="/commands/run" data-command-form>
      <input type="hidden" name="command" value="commit_database_state">
      <button type="submit" class="secondary">送 commit 儲存狀態</button>
    </form>
    <p class="help">最近狀態：{h(data_commit_message_text)}<br>最近更新：{h(data_commit_last)}<br>下次自動檢查：{h(data_commit_next)}</p>
  </div>
  <div class="card">
    <h3>資料庫健檢</h3>
    <p class="muted">檢查可用材料區與已退件有沒有重複 id、審查事件有沒有指向不存在的項目，並附建議讓你一鍵修好。</p>
    <div class="metric-row">{metric_tile(integrity_count, "待處理", "/integrity", "去處理")}</div>
    <p><a class="button {'secondary' if integrity_count == 0 else ''}" href="/integrity">打開資料庫健檢</a></p>
    <p class="help">{'目前沒有發現問題。' if integrity_count == 0 else '送 PR 前先把這裡清成 0，避免 CI 擋下。'}</p>
  </div>
</div>
<h2>本機指令</h2>
<p class="lede">這些按鈕只會執行固定 allowlist 指令；每顆按鈕下方都有白話說明，方便你不用記終端機命令。</p>
<div class="grid">{''.join(command_cards)}</div>
"""
        self.send_html("總覽", body)

    def show_items(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        candidates = load_jsonl(CANDIDATES)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        pending_entries = [("rss", candidate) for candidate in candidates] + [("item", item) for item in inbox_items]
        track_filter = (query.get("track") or ["all"])[0]
        recommendation_filter = (query.get("recommendation") or ["all"])[0]
        license_filter = clean_text((query.get("license") or ["all"])[0]) or "all"
        text_filter = clean_text((query.get("q") or [""])[0], 180)
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}
        show_all = (query.get("show") or [""])[0] == "all"

        def matches_basic(record: dict) -> bool:
            if track_filter != "all" and record.get("track") != track_filter:
                return False
            if recommendation_filter != "all" and candidate_recommendation(record) != recommendation_filter:
                return False
            if license_filter != "all" and item_license_name(record) != license_filter:
                return False
            if text_filter and not item_matches_text_filter(record, text_filter):
                return False
            return True

        def matches(record: dict) -> bool:
            if not matches_basic(record):
                return False
            if selected_keywords and not (item_triage_keywords(record) & selected_keywords):
                return False
            return True

        keyword_source_entries = [entry for entry in pending_entries if matches_basic(entry[1])]
        keyword_counts = Counter(keyword for _, record in keyword_source_entries for keyword in item_triage_keywords(record))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)

        filtered = [entry for entry in pending_entries if matches(entry[1])]
        filtered.sort(key=candidate_sort_key, reverse=True)
        visible = filtered if show_all else filtered[:150]
        summary_entries = [
            entry
            for entry in pending_entries
            if (track_filter == "all" or entry[1].get("track") == track_filter)
            and (license_filter == "all" or item_license_name(entry[1]) == license_filter)
            and (not text_filter or item_matches_text_filter(entry[1], text_filter))
            and (not selected_keywords or bool(item_triage_keywords(entry[1]) & selected_keywords))
        ]
        counts = Counter(candidate_recommendation(record) for _, record in summary_entries)
        track_counts = Counter(record.get("track", "unclassified") for _, record in pending_entries)

        def items_metric_href(recommendation: str = "") -> str:
            params = []
            if track_filter != "all":
                params.append(("track", track_filter))
            if recommendation:
                params.append(("recommendation", recommendation))
            if license_filter != "all":
                params.append(("license", license_filter))
            if text_filter:
                params.append(("q", text_filter))
            for keyword in sorted(selected_keywords):
                params.append(("keyword", keyword))
            return href_with_query("/items", params)

        reason_options = rejection_reason_options(items)
        notice = ""
        if (query.get("saved") or [""])[0] == "accepted":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已確認收下 {count} 筆。處理過的項目已離開入庫建檔區，現在可到可用材料區接著丟進編輯台。</div>'
        elif (query.get("saved") or [""])[0] == "accepted_reading":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已確認收下並標記閱讀中 / 超想看 {count} 筆。處理過的項目已離開入庫建檔區，後續可優先進編輯台。</div>'
        elif (query.get("saved") or [""])[0] == "auto_rejected":
            count = h((query.get("count") or ["0"])[0])
            notice = f'<div class="notice">已用自動批次處理標記不收 {count} 筆，並依每則標題、網址與既有理由寫入新版不收分類。</div>'
        elif (query.get("saved") or [""])[0] == "auto_pruned":
            count = h((query.get("count") or ["0"])[0])
            threshold = h((query.get("threshold") or ["65"])[0])
            notice = f'<div class="notice">已剔除 PR 未達 {threshold} 分的建議收候選 {count} 筆，並把分數門檻寫進不收原因。</div>'
        elif (query.get("saved") or [""])[0] == "rejected":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已標記不收 {count} 筆，項目已離開入庫建檔區，原因也已寫進不收學習檔與 review event。</div>'
        elif (query.get("saved") or [""])[0] == "codex_review_batch":
            count = h((query.get("count") or ["0"])[0])
            prov = h(ai_provider_label((query.get("provider") or [""])[0]) or "AI")
            notice = f'<div class="notice">已用 {prov} 批次補上 {count} 筆的 AI 閱讀建議；可進各篇查看判斷與信心度。</div>'
        elif (query.get("error") or [""])[0] == "codex_review":
            notice = '<div class="notice">這次批次補閱讀建議沒有全部成功，可稍後再試或改用其他引擎。</div>'
        elif (query.get("error") or [""])[0] == "empty-selection":
            notice = '<div class="notice">請先勾選至少一則，再做批次處理。</div>'
        elif (query.get("error") or [""])[0] == "reason":
            notice = '<div class="notice">批次不收或自訂不收時，請先填原因。</div>'
        elif (query.get("saved") or [""])[0] == "direct_pr":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已標記 {count} 筆直接送 PR 小消息。它們已離開入庫建檔區，並留下紀錄。</div>'
        elif (query.get("saved") or [""])[0] == "queued":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已收進入庫建檔區 {count} 筆，現在可在同一頁做最後分流。</div>'
        elif (query.get("saved") or [""])[0] == "dismissed":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已略過 RSS 新進 {count} 筆，之後同一筆不會重複出現。</div>'
        rows = []
        for entry_type, item in visible:
            recommendation = candidate_recommendation(item)
            priority_score = score_label(candidate_priority_scores(item)["overall"])
            css_class = track_class(item.get("track", "unclassified"))
            item_id = str(item.get("id") or "")
            detail_panel_id = item_detail_panel_id(item)
            if entry_type == "rss":
                detail_href = item_detail_href(item)
                rows.append(
                    f"""
<article class="card candidate-card candidate-card--{h(recommendation)}" data-item-id="{h(item_id)}">
  <label class="select-item">
    <input type="checkbox" class="item-select" value="{h(item_id)}">
    <span class="select-item-text">選取這則做批次處理</span>
  </label>
  <div class="candidate-detailed" id="{h(detail_panel_id)}">
  <div class="candidate-detailed-heading">
    {badge("RSS 新進", "neutral")}
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge(recommendation_label(recommendation), recommendation)}
    {badge(f"綜合 {priority_score}/10", "neutral")}
    {license_badge_html(item)}
    <strong><a href="{h(detail_href)}">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  {tag_chips_html(item_visible_tags(item))}
  <div class="decision-panel">
    <div class="button-row">
      <form method="post" action="/candidates/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="decision" value="accept">
        <button type="submit">{button_content("確認收，放入可用材料區", "accept", "A")}</button>
      </form>
      <form method="post" action="/candidates/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="decision" value="accept_reading">
        <button type="submit" class="reading-button">{button_content("閱讀中 / 超想看", "bookmark", "B")}</button>
      </form>
      <form method="post" action="/candidates/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="decision" value="direct_pr">
        <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
      </form>
    </div>
    <p class="help">這則還在入庫建檔前。確認收或直接送 PR 時，系統會先寫進 database/items.jsonl，再套用你的決定；不收會寫入不收學習檔與略過清單。</p>
    <p class="help">不收原因</p>
    <div class="reason-presets">{inline_reject_buttons(item_id, prioritized_rejection_reasons(item, reason_options), action="/candidates/dismiss")}</div>
    <details class="inline-reason">
      <summary>其他原因</summary>
      <form method="post" action="/candidates/dismiss" data-decision-form data-require-reason>
        <input type="hidden" name="id" value="{h(item_id)}">
        <div class="button-row">
          <input name="reason" placeholder="寫一句不收原因">
          <button type="submit" class="reason-chip reason-chip--danger">{button_content("記錄不收", "reject", "X")}</button>
        </div>
      </form>
    </details>
  </div>
  {editorial_triage_html(item, compact=True)}
  </div>
  {item_compact_row(item)}
</article>
"""
                )
                continue
            detail_href = item_detail_href(item)
            rows.append(
                f"""
<article class="card candidate-card candidate-card--{h(recommendation)}" data-item-id="{h(item_id)}">
  <label class="select-item">
    <input type="checkbox" class="item-select" value="{h(item_id)}">
    <span class="select-item-text">選取這則做批次處理</span>
  </label>
  <div class="candidate-detailed" id="{h(detail_panel_id)}">
  <div class="candidate-detailed-heading">
    {badge("已入庫待分流", "neutral")}
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge(recommendation_label(recommendation), recommendation)}
    {badge(f"綜合 {priority_score}/10", "neutral")}
    {license_badge_html(item)}
    <strong><a href="{h(detail_href)}">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  {tag_chips_html(item_visible_tags(item))}
  <div class="decision-panel">
    <div class="button-row">
      <form method="post" action="/items/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit">{button_content("確認收，放入可用材料區", "accept", "A")}</button>
      </form>
      <form method="post" action="/items/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="mark_reading" value="1">
        <button type="submit" class="reading-button">{button_content("閱讀中 / 超想看", "bookmark", "B")}</button>
      </form>
      <form method="post" action="/items/direct-pr" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
      </form>
    </div>
    <p class="help">確認收會移到可用材料區，之後可拖進編輯台；純事實小消息可直接記錄為送 PR。</p>
    <p class="help">不收原因</p>
    <div class="reason-presets">{inline_reject_buttons(item_id, prioritized_rejection_reasons(item, reason_options))}</div>
    <details class="inline-reason">
      <summary>其他原因</summary>
      <form method="post" action="/items/reject" data-decision-form data-require-reason>
        <input type="hidden" name="id" value="{h(item_id)}">
        <div class="button-row">
          <input name="reason" placeholder="寫一句不收原因">
          <button type="submit" class="reason-chip reason-chip--danger">{button_content("記錄不收", "reject", "X")}</button>
        </div>
      </form>
    </details>
  </div>
  {editorial_triage_html(item)}
  </div>
  {item_compact_row(item)}
</article>
"""
            )
        if not rows:
            rows.append('<div class="card"><strong>目前沒有符合條件的入庫建檔項目</strong><p class="muted">換一個篩選條件，或先重新跑關鍵字判斷。</p></div>')

        more_link = ""
        if not show_all and len(filtered) > len(visible):
            parts = []
            if track_filter != "all":
                parts.append(f"track={quote(track_filter)}")
            if recommendation_filter != "all":
                parts.append(f"recommendation={quote(recommendation_filter)}")
            if license_filter != "all":
                parts.append(f"license={quote(license_filter)}")
            if text_filter:
                parts.append(f"q={quote(text_filter)}")
            for keyword in sorted(selected_keywords):
                parts.append(f"keyword={quote(keyword)}")
            parts.append("show=all")
            more_link = f'<p><a class="button secondary" href="/items?{"&".join(parts)}">顯示全部 {len(filtered)} 筆</a></p>'

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        recommendation_options = [
            ("all", "全部建議"),
            ("suggest-keep", "只看建議收"),
            ("suggest-skip", "只看建議不要看"),
        ]
        license_options = license_filter_options([record for _, record in pending_entries])
        keyword_filters = []
        for keyword in keyword_options:
            checked = " checked" if keyword in selected_keywords else ""
            count = keyword_counts.get(keyword, 0)
            keyword_filters.append(
                f"""
<label class="keyword-option">
  <input type="checkbox" name="keyword" value="{h(keyword)}"{checked}>
  {h(keyword)} <span class="muted">({count})</span>
</label>
"""
            )
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用關鍵字 / tag。</p>'
        batch_buttons = batch_reason_buttons(reason_options)
        auto_batch_panel = ""
        def auto_batch_hidden_inputs(recommendation: str) -> list[str]:
            hidden_inputs = [
                f'<input type="hidden" name="track" value="{h(track_filter)}">',
                f'<input type="hidden" name="recommendation" value="{h(recommendation)}">',
            ]
            if license_filter != "all":
                hidden_inputs.append(f'<input type="hidden" name="license" value="{h(license_filter)}">')
            if text_filter:
                hidden_inputs.append(f'<input type="hidden" name="q" value="{h(text_filter)}">')
            if show_all:
                hidden_inputs.append('<input type="hidden" name="show" value="all">')
            for keyword in sorted(selected_keywords):
                hidden_inputs.append(f'<input type="hidden" name="keyword" value="{h(keyword)}">')
            return hidden_inputs

        if recommendation_filter == "suggest-skip" and filtered:
            auto_hidden_inputs = auto_batch_hidden_inputs("suggest-skip")
            auto_batch_panel = f"""
<div class="card auto-batch-panel">
  <form method="post" action="/items/auto-batch-skip">
    {''.join(auto_hidden_inputs)}
    <button type="submit" class="secondary">{button_content("自動批次處理", "wand", "W")}</button>
  </form>
  <p class="help">會處理這個 view 下的 {len(filtered)} 筆「建議不要看」，逐筆推估不收分類，並在原因後加上「{datetime.now(LOCAL_TIMEZONE).date().isoformat()}，自動批次處理」。</p>
</div>
"""
        elif recommendation_filter == "suggest-keep" and filtered:
            auto_hidden_inputs = auto_batch_hidden_inputs("suggest-keep")
            low_pr_threshold = 65
            low_pr_count = sum(1 for _, item in filtered if candidate_priority_scores(item)["overall"] * 10 <= low_pr_threshold)
            auto_batch_panel = f"""
<div class="card auto-batch-panel">
  <div class="button-row">
    <form method="post" action="/items/auto-batch-keep">
      {''.join(auto_hidden_inputs)}
      <input type="hidden" name="mode" value="accept_all">
      <button type="submit" class="secondary">{button_content("全部收進可用材料區", "wand", "W")}</button>
    </form>
    <form method="post" action="/items/auto-batch-keep">
      {''.join(auto_hidden_inputs)}
      <input type="hidden" name="mode" value="prune_low_pr">
      <input type="hidden" name="threshold" value="{low_pr_threshold}">
      <button type="submit" class="secondary">{button_content("剔除 PR 未達 65 分", "wand", "P")}</button>
    </form>
  </div>
  <p class="help">第一顆會處理這個 view 下全部 {len(filtered)} 筆「建議收」；第二顆只會把 PR 綜合分數 65/100 以下的 {low_pr_count} 筆標記不收，原因會逐筆寫入分數與門檻。</p>
</div>
"""
        body = f"""
<h1>入庫建檔區</h1>
<p class="lede">這裡是本機材料入口。RSS 新進、手動收藏與編輯台推薦收藏材料會一起出現；確認收後才會變成可用材料，之後才能進編輯台整理成 article。</p>
{notice}
<div class="grid">
  {metric_card(len(summary_entries), "全部待建檔", items_metric_href(), "看全部", "is-active" if recommendation_filter == "all" else "")}
  {metric_card(counts.get("suggest-keep", 0), "建議收", items_metric_href("suggest-keep"), "只看建議收", "is-active" if recommendation_filter == "suggest-keep" else "")}
  {metric_card(counts.get("suggest-skip", 0), "建議不要看", items_metric_href("suggest-skip"), "只看建議不要看", "is-active" if recommendation_filter == "suggest-skip" else "")}
</div>
<div class="workspace-toolbar">
  {material_layout_toggle("items-list")}
  {workspace_sidebar_toggle("items-workspace", "items-sidebar", "items", "篩選與批次工具")}
</div>
<div class="workspace-layout" id="items-workspace">
  <section class="workspace-main">
    <h2>待入庫材料</h2>
    <p class="muted">符合條件：{len(filtered)} 筆。{'' if show_all else f'目前先顯示 {len(visible)} 筆。'}</p>
    {more_link}
    <div class="list" id="items-list" data-layout="list" data-layout-persist>{''.join(rows)}</div>
    {more_link}
  </section>
  <aside class="workspace-sidebar" id="items-sidebar">
    <section class="workspace-sidebar-section">
      <h2>篩選入庫建檔</h2>
      <form class="filter-panel" method="get" action="/items" id="items-filter-form"
        data-instant-filter data-instant-filter-targets=".grid,#items-workspace .workspace-main,#items-sidebar">
        {'<input type="hidden" name="show" value="all">' if show_all else ''}
        <label>搜尋</label>
        <input type="search" name="q" class="auto-filter" value="{h(text_filter)}" placeholder="標題、來源、URL、摘要、tag">
        <div class="form-grid">
          <div>
            <label>主線</label>
            <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
          </div>
          <div>
            <label>系統建議</label>
            <select name="recommendation" class="auto-filter">{option_list(recommendation_options, recommendation_filter)}</select>
          </div>
          <div>
            <label>授權</label>
            <select name="license" class="auto-filter">{option_list(license_options, license_filter)}</select>
          </div>
        </div>
        <label>關鍵字 / tag</label>
        <div class="keyword-filters">{keyword_filter_html}</div>
        <div class="button-row">
          <a class="button secondary" href="/items">清除篩選</a>
          <a class="button quiet" href="/keywords">調整關鍵字</a>
        </div>
        <p class="help">搜尋與篩選會同步套用到左側清單、統計與批次處理。</p>
      </form>
    </section>
    <section class="workspace-sidebar-section">
      <h2>批次處理</h2>
      {auto_batch_panel}
      <div class="card batch-panel">
        <div class="batch-selection-line">
          <strong id="selected-count">已選取 0 則</strong>
          <p class="help" id="batch-selection-help">勾選左側項目，或按「全選目前顯示」。</p>
        </div>
        <div class="button-row">
          <button type="button" class="secondary" id="select-visible">{button_content("全選目前顯示", "select", "A")}</button>
          <button type="button" class="quiet" id="clear-selection">{button_content("清除選取", "clear", "L")}</button>
        </div>
        <form id="items-batch-form" method="post" action="/items/batch" data-batch-form>
          <input type="hidden" id="batch-ids" name="ids">
          <input type="hidden" id="batch-reason" name="reason">
          <div class="button-row">
            <button type="submit" name="action" value="accept">{button_content("批次確認收", "accept", "A")}</button>
            <button type="submit" name="action" value="accept_reading" class="reading-button">{button_content("批次閱讀中", "bookmark", "B")}</button>
            <button type="submit" name="action" value="direct_pr" class="secondary">{button_content("批次小消息", "small-news", "P")}</button>
          </div>
          <p class="help">批次不收原因</p>
          <div class="reason-presets">{batch_buttons}</div>
          <details class="inline-reason">
            <summary>批次其他原因</summary>
            <div class="button-row">
              <input id="batch-custom-reason" name="custom_reason" placeholder="寫一句批次不收原因">
              <button type="submit" name="action" value="reject" class="reason-chip reason-chip--danger" data-custom-reason="1">{button_content("批次不收", "reject", "X")}</button>
            </div>
          </details>
        </form>
        <div class="batch-ai-review">
          <p class="help" style="margin-top:10px">批次補 AI 閱讀建議（不改分流）</p>
          <div class="button-row">
            <select id="batch-ai-engine" aria-label="選擇 AI 引擎">{option_list([(provider, AI_PROVIDER_META[provider]["label"]) for provider in AI_PROVIDER_ORDER], "codex")}</select>
            <button type="button" id="batch-ai-review" class="secondary">{button_content("批次跑 AI 閱讀建議", "wand", "I")}</button>
          </div>
          <p class="help">用選定引擎對勾選項目逐筆生成閱讀建議；進度看右下角狀態列，可能需要數分鐘。</p>
        </div>
        <p class="help">只處理已勾選項目；完成後會離開入庫建檔區。</p>
      </div>
    </section>
  </aside>
</div>
<script>
(() => {{
window.initItemsPage = function initItemsPage() {{
const itemCheckboxes = Array.from(document.querySelectorAll(".item-select"));
const batchIds = document.getElementById("batch-ids");
const batchReason = document.getElementById("batch-reason");
const selectedCount = document.getElementById("selected-count");
const customReason = document.getElementById("batch-custom-reason");
const selectionHelp = document.getElementById("batch-selection-help");
const selectVisibleButton = document.getElementById("select-visible");
const clearSelectionButton = document.getElementById("clear-selection");
const aiBatchBtn = document.getElementById("batch-ai-review");
const aiBatchEngine = document.getElementById("batch-ai-engine");
if (!batchIds || !batchReason || !selectedCount) return;

function liveCheckboxes() {{
  return Array.from(document.querySelectorAll(".item-select"))
    .filter((box) => box.isConnected && !box.closest(".candidate-card")?.classList.contains("is-removing"));
}}

function syncSelection() {{
  const ids = liveCheckboxes().filter((box) => box.checked).map((box) => box.value);
  const visibleCount = liveCheckboxes().length;
  batchIds.value = ids.join(",");
  selectedCount.textContent = `已選取 ${{ids.length}} 則`;
  document.querySelectorAll("#items-batch-form button[type='submit']").forEach((button) => {{
    button.disabled = ids.length === 0;
  }});
  if (selectVisibleButton) selectVisibleButton.disabled = visibleCount === 0;
  if (clearSelectionButton) clearSelectionButton.disabled = ids.length === 0;
  if (aiBatchBtn && aiBatchBtn.dataset.running !== "1") aiBatchBtn.disabled = ids.length === 0;
  if (selectionHelp) {{
    if (visibleCount === 0) {{
      selectionHelp.textContent = "這個篩選沒有可批次處理的項目；可以先調整搜尋或篩選。";
    }} else if (ids.length === 0) {{
      selectionHelp.textContent = `目前有 ${{visibleCount}} 則可處理；勾選左側項目，或按「全選目前顯示」。`;
    }} else {{
      selectionHelp.textContent = `下方動作只會處理這 ${{ids.length}} 則。`;
    }}
  }}
  return ids;
}}

itemCheckboxes.forEach((box) => {{
  if (box.dataset.selectionBound === "1") return;
  box.dataset.selectionBound = "1";
  box.addEventListener("change", syncSelection);
}});
if (selectVisibleButton && selectVisibleButton.dataset.selectionBound !== "1") {{
selectVisibleButton.dataset.selectionBound = "1";
selectVisibleButton.addEventListener("click", () => {{
  liveCheckboxes().forEach((box) => {{ box.checked = true; }});
  syncSelection();
}});
}}
if (clearSelectionButton && clearSelectionButton.dataset.selectionBound !== "1") {{
clearSelectionButton.dataset.selectionBound = "1";
clearSelectionButton.addEventListener("click", () => {{
  liveCheckboxes().forEach((box) => {{ box.checked = false; }});
  syncSelection();
}});
}}

// 批次 AI 閱讀建議：用選定引擎對勾選項目逐筆生成，走右下角狀態列（runEngineJob）。
if (aiBatchBtn && aiBatchBtn.dataset.aiBatchBound !== "1") {{
  aiBatchBtn.dataset.aiBatchBound = "1";
  aiBatchBtn.addEventListener("click", async () => {{
    if (typeof window.runEngineJob !== "function") {{
      window.alert("頁面還沒接上右下角狀態列，請重新整理後再試。");
      return;
    }}
    if (aiBatchBtn.dataset.running === "1") return;  // 防連點
    const ids = syncSelection();
    if (!ids.length) {{ window.alert("請先勾選至少一筆項目，再批次跑 AI 閱讀建議。"); return; }}
    const engine = aiBatchEngine ? aiBatchEngine.value : "codex";
    const origText = aiBatchBtn.textContent;
    aiBatchBtn.dataset.running = "1";
    aiBatchBtn.disabled = true;
    aiBatchBtn.textContent = "執行中…（看右下角）";
    try {{
      await window.runEngineJob({{
        label: `批次 AI 閱讀建議（${{ids.length}} 筆）`,
        url: "/items/codex-review-batch",
        baseBody: "ids=" + encodeURIComponent(ids.join(",")),
        engine: engine,
        statusUrl: "/api/command-status?command=codex_review_batch",
        onSuccess: (payload) => {{
          if (payload && payload.redirect) {{
            setTimeout(() => {{ window.location = payload.redirect; }}, 1000);
          }}
        }},
      }});
    }} finally {{
      aiBatchBtn.dataset.running = "";
      aiBatchBtn.disabled = false;
      aiBatchBtn.textContent = origText;
    }}
  }});
}}

function buildRequestBody(form, submitter) {{
  let data;
  try {{
    data = new FormData(form, submitter);
  }} catch (error) {{
    data = new FormData(form);
    if (submitter?.name) {{
      data.append(submitter.name, submitter.value);
    }}
  }}
  const params = new URLSearchParams();
  data.forEach((value, key) => {{
    params.append(key, value);
  }});
  return params;
}}

function findItemCard(id) {{
  return Array.from(document.querySelectorAll(".candidate-card[data-item-id]")).find((card) => card.dataset.itemId === id);
}}

function removeCards(ids) {{
  const cards = ids
    .map((id) => findItemCard(id))
    .filter((card) => card && !card.classList.contains("is-removing"));
  if (!cards.length) {{
    return;
  }}
  cards.forEach((card) => {{
    card.classList.add("is-removing");
  }});
  window.setTimeout(() => {{
    cards.forEach((card) => {{
      if (card.isConnected) {{
        card.remove();
      }}
    }});
    syncSelection();
  }}, 260);
}}

async function submitWithoutLeaving(form, submitter, idsToRemove) {{
  const body = buildRequestBody(form, submitter);
  const fields = Array.from(form.querySelectorAll("button, input, select, textarea"));
  fields.forEach((field) => {{ field.disabled = true; }});
  let ok = false;
  try {{
    const targetUrl = form.getAttribute("action") || form.action;
    const method = form.getAttribute("method") || form.method || "POST";
    const response = await fetch(targetUrl, {{
      method,
      body,
      credentials: "same-origin",
      redirect: "follow",
      headers: {{ "X-Requested-With": "local-web-fetch" }},
    }});
    if (!response.ok) {{
      throw new Error(`HTTP ${{response.status}}`);
    }}
    if (form.id === "items-batch-form") {{
      idsToRemove.forEach((id) => {{
        const card = findItemCard(id);
        const checkbox = card?.querySelector(".item-select");
        if (checkbox) checkbox.checked = false;
      }});
    }}
    ok = true;
    removeCards(idsToRemove);
  }} catch (error) {{
    alert("剛剛沒有送成功，畫面先保留。可以再按一次。");
  }} finally {{
    fields.forEach((field) => {{ field.disabled = false; }});
    if (ok && form.id === "items-batch-form") syncSelection();
  }}
}}

document.querySelectorAll("form[data-decision-form]").forEach((form) => {{
  if (form.dataset.decisionBound === "1") return;
  form.dataset.decisionBound = "1";
  form.addEventListener("submit", (event) => {{
    event.preventDefault();
    const reasonInput = form.querySelector("[name='reason']");
    if (form.dataset.requireReason !== undefined && !reasonInput?.value.trim()) {{
      alert("請先寫一句不收原因。");
      reasonInput?.focus();
      return;
    }}
    const itemId = form.querySelector("[name='id']")?.value;
    if (!itemId) {{
      return;
    }}
    submitWithoutLeaving(form, event.submitter, [itemId]);
  }});
}});

const itemsBatchForm = document.getElementById("items-batch-form");
if (itemsBatchForm && itemsBatchForm.dataset.batchBound !== "1") {{
itemsBatchForm.dataset.batchBound = "1";
itemsBatchForm.addEventListener("submit", (event) => {{
  event.preventDefault();
  const ids = syncSelection();
  const submitter = event.submitter;
  if (submitter?.dataset.batchReason) {{
    batchReason.value = submitter.dataset.batchReason;
  }} else if (submitter?.dataset.customReason) {{
    batchReason.value = customReason.value.trim();
  }}
  if (!ids.length) {{
    alert("請先勾選要處理的項目。");
    return;
  }}
  if (submitter?.value === "reject" && !batchReason.value.trim()) {{
    alert("請先選一個不收原因，或填寫其他原因。");
    customReason?.focus();
    return;
  }}
  submitWithoutLeaving(event.currentTarget, submitter, ids);
}});
}}
syncSelection();
}}
if (document.readyState === "loading") {{
  document.addEventListener("DOMContentLoaded", window.initItemsPage, {{once: true}});
}} else {{
  window.initItemsPage();
}}
}})();
</script>
"""
        self.send_html("入庫建檔區", body)

    def show_recycle_bin(self, query: dict[str, list[str]]) -> None:
        records = recycle_records()
        track_filter = form_value(query, "track", "all")
        origin_filter = form_value(query, "origin", "all")
        source_filter = form_value(query, "source_id", "all")
        reason_filter = form_value(query, "reason", "all")
        text_filter = form_value(query, "q")
        show_all = form_value(query, "show") == "all"

        def recycle_href(**overrides: str) -> str:
            values = {
                "track": track_filter,
                "origin": origin_filter,
                "source_id": source_filter,
                "reason": reason_filter,
                "q": text_filter,
            }
            values.update(overrides)
            params = []
            for key in ["track", "origin", "source_id", "reason"]:
                value = values.get(key, "all")
                if value and value != "all":
                    params.append((key, value))
            if values.get("q"):
                params.append(("q", values["q"]))
            if overrides.get("show") or show_all:
                params.append(("show", overrides.get("show", "all")))
            return href_with_query("/recycle-bin", params)

        source_names: dict[str, str] = {}
        for record in records:
            source_id = clean_text(record.get("source_id"))
            if source_id and source_id not in source_names:
                source_names[source_id] = clean_text(record.get("source_name") or record.get("author")) or source_id
        source_options = [("all", "全部來源")] + sorted(source_names.items(), key=lambda item: item[1].casefold())

        reason_counts = Counter(recycle_record_reason(record) or "未標示原因" for record in records)
        reason_options = [("all", "全部原因")] + [(reason, f"{reason}（{count}）") for reason, count in reason_counts.most_common(40)]
        if reason_filter != "all" and reason_filter not in {value for value, _label in reason_options}:
            reason_options.insert(1, (reason_filter, reason_filter))

        def matches(record: dict, *, ignore_origin: bool = False) -> bool:
            if track_filter != "all" and record.get("track") != track_filter:
                return False
            if not ignore_origin and origin_filter != "all" and record.get("_recycle_origin") != origin_filter:
                return False
            if source_filter != "all" and record.get("source_id") != source_filter:
                return False
            reason = recycle_record_reason(record) or "未標示原因"
            if reason_filter != "all" and reason != reason_filter:
                return False
            if text_filter:
                haystack = "\n".join(
                    [
                        item_display_title(record),
                        item_original_title(record),
                        clean_text(record.get("url"), 500),
                        clean_text(record.get("source_name") or record.get("author"), 200),
                        item_zh_summary(record, 600),
                        reason,
                        " ".join(item_visible_tags(record, 20)),
                    ]
                ).casefold()
                if text_filter.casefold() not in haystack:
                    return False
            return True

        filtered = [record for record in records if matches(record)]
        filtered.sort(key=lambda record: (recycle_record_sort_time(record), item_display_title(record)), reverse=True)
        visible = filtered if show_all else filtered[:160]
        type_summary_records = [record for record in records if matches(record, ignore_origin=True)]
        type_counts = Counter(record.get("_recycle_origin") for record in type_summary_records)
        current_href = recycle_href(show="all" if show_all else "")

        def restore_form(record: dict) -> str:
            item_id = clean_text(record.get("id"))
            if not item_id:
                return ""
            return f"""
<form class="chip-form" method="post" action="/recycle-bin/restore">
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="redirect" value="{h(current_href)}">
  <button type="submit" class="reason-chip">{button_content("重新收錄", "refresh", "R")}</button>
</form>
"""

        def record_row(record: dict) -> str:
            title = item_display_title(record)
            url = clean_text(record.get("url"))
            title_html = f'<a href="{h(url)}" target="_blank" rel="noreferrer">{h(title)}</a>' if url else h(title)
            reason = recycle_record_reason(record) or "未標示原因"
            css_class = track_class(record.get("track", "unclassified"))
            decision_time = recycle_record_decided_at(record)
            time_label = format_datetime(decision_time) if decision_time else item_display_time(record, "dismissed_at", "captured_at", "published_at")
            summary = item_zh_summary(record, 360) or clean_text(record.get("summary"), 360)
            original_link = (
                f'<a class="button secondary reader-action-button" href="{h(url)}" target="_blank" rel="noreferrer" aria-label="原始連結" title="原始連結">{icon_span("external", "L", "icon reader-action-icon")}{action_label("原始連結")}</a>'
                if url
                else ""
            )
            source_id = clean_text(record.get("source_id"))
            source_link = (
                f'<a class="button quiet reader-action-button" href="/sources/view?id={quote(source_id)}#source-rejected">{icon_span("source", "S", "icon reader-action-icon")}{action_label("看來源")}</a>'
                if source_id
                else ""
            )
            return f"""
<article class="card candidate-card candidate-card--suggest-skip">
  <div class="candidate-detailed">
    <div class="candidate-detailed-heading">
      {badge(recycle_record_origin_label(record), "suggest-skip")}
      {badge(track_meta(record.get("track", "unclassified"))["short"], css_class)}
      {badge(time_label, "neutral")}
      <strong>{title_html}</strong>
    </div>
    <p class="muted break-anywhere">{source_name_link(record)} · {h(url)}</p>
    <p class="help">不收原因：{h(reason)}</p>
    {f'<p>{h(summary)}</p>' if summary else ''}
    {tag_chips_html(item_visible_tags(record))}
    <div class="button-row reader-card-actions">
      {restore_form(record)}
      {original_link}
      {source_link}
    </div>
  </div>
</article>
"""

        rows = [record_row(record) for record in visible]
        if not rows:
            rows.append('<div class="card"><strong>目前沒有符合條件的不收紀錄</strong><p class="muted">換一個篩選條件，或先回入庫建檔區處理新資料。</p></div>')

        more_link = ""
        if not show_all and len(filtered) > len(visible):
            more_link = f'<p><a class="button secondary" href="{h(recycle_href(show="all"))}">顯示全部 {len(filtered)} 筆</a></p>'

        notice = ""
        if form_value(query, "saved") == "restored":
            count = h(form_value(query, "count", "1"))
            notice = f'<div class="notice">已從資源回收區重新收錄 {count} 筆，項目會回到入庫建檔區。</div>'
        elif form_value(query, "error") == "not-found":
            notice = '<div class="notice">找不到這筆不收紀錄，可能已經被重新收錄或資料檔已更新。</div>'

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        origin_options = [("all", "全部紀錄"), ("rejected", "已入庫後不收"), ("dismissed", "RSS 新進略過")]
        body = f"""
<h1>資源回收區</h1>
<p class="lede">這裡統整已經按過不收、略過或移出入庫建檔區的歷史紀錄。需要重新判斷時，可以直接把單篇撈回入庫建檔區。</p>
{notice}
<div class="grid">
  {metric_card(len(records), "全部不收紀錄", "/recycle-bin", "看全部", "is-active" if origin_filter == "all" else "")}
  {metric_card(type_counts.get("rejected", 0), "已入庫後不收", recycle_href(origin="rejected"), "只看", "is-active" if origin_filter == "rejected" else "")}
  {metric_card(type_counts.get("dismissed", 0), "RSS 新進略過", recycle_href(origin="dismissed"), "只看", "is-active" if origin_filter == "dismissed" else "")}
  {metric_card(len(filtered), "目前符合", current_href, "筆")}
</div>
<div class="workspace-toolbar">
  {workspace_sidebar_toggle("recycle-workspace", "recycle-sidebar", "recycle", "篩選回收紀錄")}
</div>
<div class="workspace-layout" id="recycle-workspace">
  <section class="workspace-main">
    <h2>不收歷史</h2>
    <p class="muted">符合條件：{len(filtered)} 筆。{'' if show_all else f'目前先顯示 {len(visible)} 筆。'}</p>
    {more_link}
    <div class="list" id="recycle-list">{''.join(rows)}</div>
    {more_link}
  </section>
  <aside class="workspace-sidebar" id="recycle-sidebar">
    <section class="workspace-sidebar-section">
      <h2>篩選資源回收區</h2>
      <form class="filter-panel" method="get" action="/recycle-bin">
        {'<input type="hidden" name="show" value="all">' if show_all else ''}
        <div class="form-grid">
          <div>
            <label>主線</label>
            <select name="track">{option_list(track_options, track_filter)}</select>
          </div>
          <div>
            <label>紀錄類型</label>
            <select name="origin">{option_list(origin_options, origin_filter)}</select>
          </div>
        </div>
        <label>來源</label>
        <select name="source_id">{option_list(source_options, source_filter)}</select>
        <label>不收原因</label>
        <select name="reason">{option_list(reason_options, reason_filter)}</select>
        <label>搜尋</label>
        <input type="search" name="q" value="{h(text_filter)}" placeholder="標題、摘要、來源、URL、tag">
        <div class="button-row">
          <button type="submit">{button_content("套用篩選", "filter")}</button>
          <a class="button secondary" href="/recycle-bin">清除篩選</a>
        </div>
        <p class="help">重新收錄會把項目移回入庫建檔區，並從不收學習檔與 RSS 略過清單移除同一個 id。</p>
      </form>
    </section>
  </aside>
</div>
"""
        self.send_html("資源回收區", body)

    @with_db_write_lock
    def restore_recycle_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "/recycle-bin")
        if not item_id:
            self.redirect(f"{redirect_to}{'&' if '?' in redirect_to else '?'}error=not-found")
            return

        rejected_records = load_jsonl(REJECTED_ITEMS)
        dismissed_records = load_jsonl(DISMISSED)
        matching_records = [
            {**record, "_recycle_origin": "rejected"}
            for record in rejected_records
            if clean_text(record.get("id")) == item_id
        ] + [
            {**record, "_recycle_origin": "dismissed"}
            for record in dismissed_records
            if clean_text(record.get("id")) == item_id
        ]
        if not matching_records:
            self.redirect(f"{redirect_to}{'&' if '?' in redirect_to else '?'}error=not-found")
            return

        restored_record = max(
            matching_records,
            key=lambda record: (
                1 if record.get("_recycle_origin") == "rejected" else 0,
                len(json.dumps(record, ensure_ascii=False)),
            ),
        )
        decided_at = now_iso()
        note = "從資源回收區重新收錄，回到入庫建檔區。"
        restored = clean_restored_recycle_record(restored_record, decided_at, "資源回收區重新收錄")
        restored["review"] = append_review_note(restored.get("review") or {}, f"{decided_at} {note}")

        upsert_jsonl(ITEMS, restored)
        write_jsonl(REJECTED_ITEMS, [record for record in rejected_records if clean_text(record.get("id")) != item_id])
        write_jsonl(DISMISSED, [record for record in dismissed_records if clean_text(record.get("id")) != item_id])
        append_jsonl(REVIEW_EVENTS, review_event(restored, "restored", note))

        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=restored&count=1")

    def show_item_reject_form(self, query: dict[str, list[str]]) -> None:
        item_id = form_value(query, "id")
        items = load_jsonl(ITEMS)
        item = next((row for row in items if row.get("id") == item_id), None)
        if not item:
            self.send_html("找不到項目", "<h1>找不到入庫建檔項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return

        error = ""
        if (query.get("error") or [""])[0] == "reason":
            error = '<div class="notice">請先寫一點原因，再標記不收。</div>'
        reason_buttons = "\n".join(
            f'<button type="button" class="secondary reason-preset" data-reason="{h(reason)}">{h(reason)}</button>'
            for reason in prioritized_rejection_reasons(item, rejection_reason_options(items))
        )
        triage = item.get("triage") or {}
        body = f"""
<h1>不收原因</h1>
<p class="lede">這一步會把項目移出 items 主資料庫，存到 rejected-items 學習檔並保留原因。這些原因之後會出現在快捷按鈕裡，幫你更快整理不要看的資料。</p>
{error}
<article class="card candidate-card candidate-card--{h(candidate_recommendation(item))}">
  <div>
    {badge(track_meta(item.get("track", "unclassified"))["short"], track_class(item.get("track", "unclassified")))}
    {badge(recommendation_label(candidate_recommendation(item)), candidate_recommendation(item))}
    <strong><a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))} · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 420))}</p>
  <p class="help">系統判斷：{h(workflow_display_text(triage.get('reason', '未標示')))}</p>
</article>
<form class="form-panel" method="post" action="/items/reject">
  <input type="hidden" name="id" value="{h(item_id)}">
  <label>常用原因</label>
  <div class="reason-presets">{reason_buttons}</div>
  <p class="help">點一個原因會先放進文字框；你可以再補自己的判斷。</p>
  <label>這次不收的原因</label>
  <textarea id="reject-reason" name="reason" required></textarea>
  <p class="help">例：和主線關聯太弱、重複、只是活動公告、缺少可查證來源。這會寫進不收學習檔和 review event。</p>
  <div class="button-row">
    <button type="submit" class="danger">{button_content("確認不收並記錄原因", "reject", "X")}</button>
    <a class="button secondary" href="/items">先不要決定</a>
  </div>
</form>
<script>
document.querySelectorAll(".reason-preset").forEach((button) => {{
  button.addEventListener("click", () => {{
    const target = document.getElementById("reject-reason");
    target.value = button.dataset.reason;
    target.focus();
  }});
}});
</script>
"""
        self.send_html("不收原因", body)

    def show_candidates(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        skill_candidates = [item for item in items if is_skill_candidate(item)]
        track_filter = (query.get("track") or ["all"])[0]
        text_filter = clean_text((query.get("q") or [""])[0], 180)
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}

        def matches_basic(item: dict) -> bool:
            if track_filter != "all" and item.get("track") != track_filter:
                return False
            if text_filter and not item_matches_text_filter(item, text_filter):
                return False
            return True

        def matches(item: dict) -> bool:
            if not matches_basic(item):
                return False
            if selected_keywords and not (item_triage_keywords(item) & selected_keywords):
                return False
            return True

        keyword_source_items = [item for item in skill_candidates if matches_basic(item)]
        keyword_counts = Counter(keyword for item in keyword_source_items for keyword in item_triage_keywords(item))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)
        filtered_skill = [item for item in skill_candidates if matches(item)]
        filtered_skill.sort(
            key=lambda item: ((item.get("local_decision") or {}).get("decided_at", ""), item.get("captured_at", "")),
            reverse=True,
        )
        filtered_skill.sort(key=lambda item: item_skill_priority_tuple(item)[0])
        metric_source_items = [
            item
            for item in skill_candidates
            if (not text_filter or item_matches_text_filter(item, text_filter))
            and (not selected_keywords or (item_triage_keywords(item) & selected_keywords))
        ]
        track_counts = Counter(item.get("track", "unclassified") for item in metric_source_items)
        skill_rows = []
        for item in filtered_skill:
            triage = item.get("triage") or {}
            recommendation = candidate_recommendation(item)
            css_class = track_class(item.get("track", "unclassified"))
            decided_at = (item.get("local_decision") or {}).get("decided_at", "未標示時間")
            detail_href = item_detail_href(item)
            detail_panel_id = item_detail_panel_id(item)
            skill_rows.append(
                f"""
<article class="card candidate-card">
  <div class="candidate-detailed" id="{h(detail_panel_id)}">
  <div class="candidate-detailed-heading">
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge("可進編輯台", "neutral")}
    {badge(recommendation_label(recommendation), recommendation)}
    {reader_flag_badges(item)}
    <strong><a href="{h(detail_href)}">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · 確認收：{h(decided_at)} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  {tag_chips_html(item_visible_tags(item))}
  {editorial_triage_html(item, compact=True)}
  <div class="button-row">
    <a class="button button-small" href="/editor?items={quote(str(item.get('id', '')))}">{button_content("送進編輯台草稿庫", "edit")}</a>
    <a class="button button-small secondary" href="{h(detail_href)}">打開單篇整理</a>
  </div>
  <p class="help">下一步：拖進編輯台做選法檢查、撰稿或查核；整理好後才會成為 article。<br>系統原判斷：{h(workflow_display_text(triage.get('reason', '未標示')))}</p>
  </div>
  {item_compact_row(item)}
</article>
"""
            )
        if not skill_rows:
            skill_rows.append('<div class="card"><strong>目前沒有可用材料</strong><p class="muted">在入庫建檔區按「確認收」後，會移到這裡。</p></div>')

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        keyword_filters = []
        for keyword in keyword_options:
            checked = " checked" if keyword in selected_keywords else ""
            count = keyword_counts.get(keyword, 0)
            keyword_filters.append(
                f"""
<label class="keyword-option">
  <input type="checkbox" name="keyword" value="{h(keyword)}"{checked}>
  {h(keyword)} <span class="muted">({count})</span>
</label>
"""
            )
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用關鍵字 / tag。</p>'

        def candidate_metric_href(track: str = "") -> str:
            params = []
            if track:
                params.append(("track", track))
            if text_filter:
                params.append(("q", text_filter))
            for keyword in sorted(selected_keywords):
                params.append(("keyword", keyword))
            return href_with_query("/candidates", params)

        body = f"""
<h1>可用材料區</h1>
<p class="lede">這裡只放你已確認收下、可以拖進編輯台草稿庫的材料。還沒判斷的新資料請先回入庫建檔區處理。</p>
<div class="grid">
  {metric_card(len(metric_source_items), "可進編輯台", candidate_metric_href(), "看全部", "is-active" if track_filter == "all" else "")}
  {metric_card(track_counts.get("open-tech-open-industry", 0), "開放科技", candidate_metric_href("open-tech-open-industry"), "只看開放科技", "is-active" if track_filter == "open-tech-open-industry" else "")}
  {metric_card(track_counts.get("digital-humanities-local-knowledge", 0), "人文知識", candidate_metric_href("digital-humanities-local-knowledge"), "只看人文知識", "is-active" if track_filter == "digital-humanities-local-knowledge" else "")}
  {metric_card(track_counts.get("unclassified", 0), "未分類", candidate_metric_href("unclassified"), "只看未分類", "is-active" if track_filter == "unclassified" else "")}
</div>
<div class="workspace-toolbar">
  {material_layout_toggle("candidates-list")}
  {workspace_sidebar_toggle("candidates-workspace", "candidates-sidebar", "candidates", "篩選工具")}
</div>
<div class="workspace-layout" id="candidates-workspace">
  <section class="workspace-main">
    <h2>已確認收，可進編輯台</h2>
    <p class="muted">符合條件：{len(filtered_skill)} 筆。</p>
    <div class="list" id="candidates-list" data-layout="list" data-layout-persist>{''.join(skill_rows)}</div>
  </section>
  <aside class="workspace-sidebar" id="candidates-sidebar">
    <section class="workspace-sidebar-section">
      <h2>篩選可用材料</h2>
      <form class="filter-panel" method="get" action="/candidates" id="candidate-filter-form"
        data-instant-filter data-instant-filter-targets=".grid,#candidates-workspace .workspace-main,#candidates-sidebar">
        <label>搜尋</label>
        <input type="search" name="q" class="auto-filter" value="{h(text_filter)}" placeholder="標題、來源、URL、摘要、tag">
        <div class="sidebar-field-group">
          <h3>範圍</h3>
          <label>主線</label>
          <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
        </div>
        <label>關鍵字 / tag</label>
        <div class="keyword-filters">{keyword_filter_html}</div>
        <p class="help">搜尋與篩選會同步套用到左側清單與統計。</p>
      </form>
    </section>
    <section class="workspace-sidebar-section">
      <h2>常用動作</h2>
      <div class="card workspace-tool-panel">
        <div class="button-row">
          <a class="button" href="/editor">打開編輯台</a>
          <a class="button secondary" href="/items">回入庫建檔區</a>
        </div>
        <p class="help">確認收後的材料先在這裡整理，再送進編輯台。</p>
      </div>
    </section>
  </aside>
</div>
"""
        self.send_html("可用材料區", body)

    def show_tag_view(self, query: dict[str, list[str]]) -> None:
        selected_tag = canonical_tag_label(form_value(query, "tag"))
        license_filter = clean_text((query.get("license") or ["all"])[0]) or "all"
        all_items = load_jsonl(ITEMS)
        candidates = load_jsonl(CANDIDATES)
        rejected_items = load_jsonl(REJECTED_ITEMS)
        dismissed_items = load_jsonl(DISMISSED)
        tag_reference_records = [*all_items, *candidates, *rejected_items, *dismissed_items]
        if not selected_tag:
            counts = tag_counts_for(tag_reference_records)
            rows = []
            for tag, count in counts.most_common(80):
                rows.append(
                    f'<a class="tag-chip tag-chip--large" href="{h(tag_href(tag))}">{icon_span("tag", "", "tag-chip-icon")}{h(tag)} <span class="muted">({count})</span></a>'
                )
            body = f"""
<h1>Tag 索引</h1>
<p class="lede">點一個 tag 就能看到同一個概念底下的待整理與已收內容。</p>
<section class="card">
  <h2>常用 tag</h2>
  <div class="tag-chip-list">{''.join(rows) or '<p class="muted">目前沒有可用 tag。</p>'}</div>
</section>
"""
            self.send_html("Tag 索引", body)
            return

        matching_items = [item for item in all_items if item_matches_tag(item, selected_tag)]
        matching_candidates = [item for item in candidates if item_matches_tag(item, selected_tag)]
        if license_filter != "all":
            matching_items = [item for item in matching_items if item_license_name(item) == license_filter]
            matching_candidates = [item for item in matching_candidates if item_license_name(item) == license_filter]
        license_options = option_list(license_filter_options([*matching_items, *matching_candidates]), license_filter)

        def sort_records(records: list[dict]) -> list[dict]:
            return sorted(records, key=lambda item: (item_sort_time(item), item_display_title(item)), reverse=True)

        related_counter: Counter[str] = Counter()
        for item in [*matching_items, *matching_candidates]:
            for tag in item_triage_keywords(item):
                if tag_key(tag) != tag_key(selected_tag):
                    related_counter[tag] += 1
        related_html = tag_chips_html([tag for tag, _count in related_counter.most_common(18)], "tag-chip-list tag-chip-list--related")

        def tag_summary(item: dict, limit: int = 260) -> str:
            return item_zh_summary(item, limit)

        def tag_list_row(item: dict) -> str:
            title = item_display_title(item)
            return f"""
<article class="reader-list-card">
  <div class="reader-list-meta">
    {badge(status_label(item.get("status", "RSS 新進")), "neutral")}
    {badge(content_kind_label(item_display_kind(item)), "neutral")}
    {license_badge_html(item)}
    {badge(item_display_time(item, 'published_at', 'captured_at'), "neutral")}
    {reader_flag_badges(item)}
  </div>
  <h3><a href="{h(item_detail_href(item))}">{h(title)}</a></h3>
  <p class="zh-summary">{h(tag_summary(item, 360))}</p>
  {tag_chips_html(item_visible_tags(item, 8))}
</article>
"""

        def tag_compact_row(item: dict) -> str:
            return f"""
<article class="reader-compact-row">
  <span class="reader-dot" aria-hidden="true"></span>
  <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
  <div class="reader-row-time">{h(item_display_time(item, 'published_at', 'captured_at'))}</div>
</article>
"""

        def tag_card(item: dict) -> str:
            image = item_image_url(item)
            css_class = track_class(item.get("track", "unclassified"))
            thumb = (
                f"<div class='reader-thumb'><img src='{h(image)}' alt=''></div>"
                if image
                else f"<div class='reader-thumb reader-thumb--{h(css_class)}'><span>{h(track_meta(item.get('track', 'unclassified'))['short'])}</span></div>"
            )
            kind = item_display_kind(item)
            item_url = clean_text(item.get("url"))
            return f"""
<article class="card reader-card">
  {thumb}
  <div class="reader-body">
    <div>
      {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
      {badge(status_label(item.get("status", "RSS 新進")), "neutral")}
      {badge(content_kind_label(kind), "neutral")}
      {reader_flag_badges(item)}
      {license_badge_html(item)}
    </div>
    <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
    <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))}</p>
    <p class="zh-summary">{h(tag_summary(item, 260))}</p>
    {tag_chips_html(item_visible_tags(item, 6))}
    {f'<div class="button-row reader-card-actions" aria-label="文章操作"><a class="button reader-action-button" href="{h(item_detail_href(item))}" aria-label="閱讀 / 記錄" title="閱讀 / 記錄">{icon_span("read", "O", "icon reader-action-icon")}{action_label("閱讀 / 記錄")}</a><a class="button secondary reader-action-button" href="{h(item_url)}" target="_blank" rel="noreferrer" aria-label="原始連結" title="原始連結">{icon_span("external", "L", "icon reader-action-icon")}{action_label("原始連結")}</a></div>' if item_url else ''}
  </div>
</article>
"""

        featured = sort_records([item for item in matching_items if item_display_kind(item) in {"featured-article", "opinion-article"}])
        small_news = sort_records([item for item in matching_items if item_display_kind(item) == "small-news" and item.get("status") != "inbox"])
        inbox = sort_records([item for item in matching_items if item.get("status") == "inbox"])
        pending = sort_records(matching_candidates)
        other_records = sort_records([item for item in matching_items if item not in featured and item not in small_news and item not in inbox])

        def section(section_id: str, title: str, description: str, records: list[dict], empty: str, default_layout: str = "list") -> str:
            empty_html = f'<div class="card"><p class="muted">{h(empty)}</p></div>'
            period_html = ""
            if records:
                period_groups: list[tuple[str, list[dict]]] = []
                period_index: dict[str, int] = {}
                for item in records:
                    label = reader_period_label(item)
                    if label not in period_index:
                        period_index[label] = len(period_groups)
                        period_groups.append((label, []))
                    period_groups[period_index[label]][1].append(item)
                rendered_periods = []
                for label, period_records in period_groups:
                    cards_html = "".join(tag_card(item) for item in period_records)
                    list_html = "".join(tag_list_row(item) for item in period_records)
                    compact_html = "".join(tag_compact_row(item) for item in period_records)
                    rendered_periods.append(
                        f"""
<details class="reader-period-details" id="{h(section_id)}-{h(reader_period_key(period_records[0]))}" open>
  <summary class="reader-period-heading">
    <span class="reader-period-heading-label">{h(label)}</span>
    <span class="reader-period-count">{len(period_records)} 筆</span>
  </summary>
  <div class="reader-grid">{cards_html}</div>
  <div class="reader-list">{list_html}</div>
  <div class="reader-compact-list">{compact_html}</div>
</details>
"""
                    )
                period_html = "".join(rendered_periods)
            return f"""
<section class="reader-layout-section reader-category" id="{h(section_id)}" data-layout="{h(default_layout)}">
  <div class="layout-bar">
    <h2>{h(title)} {help_dot(description)}</h2>
    {layout_toggle(section_id, default_layout)}
  </div>
  {period_html or empty_html}
</section>
"""

        body = f"""
<h1>Tag：{h(selected_tag)}</h1>
<p class="lede">這裡集中同一個 tag 及同義系列的文章，方便回頭看待整理與已收內容。</p>
<div class="button-row top-back-row">
  <a class="button quiet" href="/tags">{icon_span("back", "", "icon")}所有 tag</a>
  <a class="button secondary" href="{h(href_with_query('/items', [('keyword', selected_tag)]))}">回入庫建檔區篩選</a>
  <a class="button secondary" href="{h(href_with_query('/reader', [('time', 'all'), ('keyword', selected_tag)]))}">回閱讀區篩選</a>
  <form method="get" action="/tags" class="inline-select-form">
    <input type="hidden" name="tag" value="{h(selected_tag)}">
    <select name="license" aria-label="授權篩選" onchange="this.form.submit()">{license_options}</select>
  </form>
</div>
<div class="metric-row">
  {metric_tile(len(featured), "精選 / 觀點", "#tag-featured", "看區塊")}
  {metric_tile(len(small_news), "小消息", "#tag-small-news", "看區塊")}
  {metric_tile(len(inbox) + len(pending), "待整理", "#tag-inbox", "看區塊")}
  {metric_tile(len(other_records), "其他已收", "#tag-other", "看區塊")}
</div>
{f'<section class="card"><h2>相關 tag</h2>{related_html}</section>' if related_html else ''}
{publish_page_card("tag", selected_tag, selected_tag)}
{section("tag-featured", "精選文章與觀點文章", "已確認值得細讀、可能後續撰稿或觀點整理的內容。", featured, "這個 tag 目前沒有精選文章或觀點文章。", "card")}
{section("tag-small-news", "純新聞 / 小消息", "可以快速掃過、查核後短訊處理的內容。", small_news, "這個 tag 目前沒有小消息。", "list")}
{section("tag-inbox", "入庫建檔 / RSS 新進", "還沒完成收或不收判斷的內容，包含已入庫 inbox 和 RSS 新進。", [*inbox, *pending], "這個 tag 目前沒有入庫建檔項目。", "list")}
{section("tag-other", "其他已收項目", "已收但尚未歸入精選、觀點或小消息的內容。", other_records, "這個 tag 目前沒有其他已收項目。", "list")}
"""
        self.send_html(f"Tag：{selected_tag}", body)

    def show_reader(self, query: dict[str, list[str]]) -> None:
        items = [item for item in load_jsonl(ITEMS) if is_reader_item(item)]
        track_filter = (query.get("track") or ["all"])[0]
        kind_filter = (query.get("kind") or ["all"])[0]
        reading_filter = (query.get("reading") or ["all"])[0]
        license_filter = clean_text((query.get("license") or ["all"])[0]) or "all"
        text_filter = clean_text((query.get("q") or [""])[0], 180)
        if reading_filter not in {"all", "current"}:
            reading_filter = "all"
        view_mode = (query.get("view") or ["auto"])[0]
        if view_mode not in {"auto", "card", "list", "compact"}:
            view_mode = "auto"
        time_filter = (query.get("time") or ["all"])[0]
        if time_filter not in {key for key, _ in READER_TIME_FILTERS}:
            time_filter = "all"
        try:
            month_limit = max(1, min(24, int(form_value(query, "months", "1") or "1")))
        except ValueError:
            month_limit = 1
        start_date = clean_text((query.get("start") or [""])[0])
        end_date = clean_text((query.get("end") or [""])[0])
        time_start, time_end = reader_time_bounds(time_filter, start_date, end_date)
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}

        def matches_basic(item: dict) -> bool:
            if track_filter != "all" and item.get("track") != track_filter:
                return False
            kind = item_display_kind(item)
            if kind_filter != "all" and kind != kind_filter:
                return False
            if reading_filter == "current" and not item_is_current_reading(item):
                return False
            if license_filter != "all" and item_license_name(item) != license_filter:
                return False
            if text_filter and not item_matches_text_filter(item, text_filter):
                return False
            return True

        def matches_scope(item: dict) -> bool:
            return matches_basic(item) and item_matches_time_filter(item, time_start, time_end)

        def matches(item: dict) -> bool:
            if not matches_scope(item):
                return False
            if selected_keywords and not (item_triage_keywords(item) & selected_keywords):
                return False
            return True

        keyword_source_items = [item for item in items if matches_scope(item)]
        keyword_counts = Counter(keyword for item in keyword_source_items for keyword in item_triage_keywords(item))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)
        filtered = [item for item in items if matches(item)]
        filtered.sort(
            key=lambda item: (item_sort_time(item), item_display_title(item)),
            reverse=True,
        )
        if kind_filter == "all":
            kind_priority = {"featured-article": 0, "opinion-article": 1, "small-news": 2, "needs-review": 3}
            filtered.sort(key=lambda item: kind_priority.get(item_display_kind(item), 9))
        metric_source_items = [
            item
            for item in items
            if (not text_filter or item_matches_text_filter(item, text_filter))
            and (license_filter == "all" or item_license_name(item) == license_filter)
            and (not selected_keywords or (item_triage_keywords(item) & selected_keywords))
        ]
        track_counts = Counter(item.get("track", "unclassified") for item in metric_source_items)
        kind_counts = Counter(item_display_kind(item) for item in metric_source_items)
        notice = ""
        if (query.get("saved") or [""])[0] == "read_more":
            notice = '<div class="notice">已嘗試載入原始主文與頁面資料；若抓到全文，已寫進閱讀資料庫。</div>'
        elif (query.get("saved") or [""])[0] == "reading_priority":
            notice = '<div class="notice">已更新近期正在閱讀 / 想分享標記。</div>'
        elif (query.get("error") or [""])[0] == "read_more":
            notice = '<div class="notice">這次沒有抓到更多資料，可能是網站擋住讀取、需要登入，或頁面沒有可抽取的主文。</div>'
        redirect_parts = []
        if track_filter != "all":
            redirect_parts.append(f"track={quote(track_filter)}")
        if kind_filter != "all":
            redirect_parts.append(f"kind={quote(kind_filter)}")
        if reading_filter != "all":
            redirect_parts.append(f"reading={quote(reading_filter)}")
        if license_filter != "all":
            redirect_parts.append(f"license={quote(license_filter)}")
        if text_filter:
            redirect_parts.append(f"q={quote(text_filter)}")
        if view_mode != "auto":
            redirect_parts.append(f"view={quote(view_mode)}")
        if time_filter != "all":
            redirect_parts.append(f"time={quote(time_filter)}")
        if month_limit != 1:
            redirect_parts.append(f"months={month_limit}")
        if time_filter == "custom":
            if start_date:
                redirect_parts.append(f"start={quote(start_date)}")
            if end_date:
                redirect_parts.append(f"end={quote(end_date)}")
        for keyword in sorted(selected_keywords):
            redirect_parts.append(f"keyword={quote(keyword)}")
        reader_redirect = "/reader" + (f"?{'&'.join(redirect_parts)}" if redirect_parts else "")

        def reader_card(item: dict, suffix: str = "card") -> str:
            css_class = track_class(item.get("track", "unclassified"))
            kind = item_display_kind(item)
            image = item_image_url(item)
            thumb = (
                f"<div class='reader-thumb'><img src='{h(image)}' alt=''></div>"
                if image
                else f"<div class='reader-thumb reader-thumb--{h(css_class)}'><span>{h(track_meta(item.get('track', 'unclassified'))['short'])}</span></div>"
            )
            note = personal_note_text(item)
            note_html = f"<p class='note-box'>{h(clean_text(note, 160))}</p>" if note else ""
            fulltext_id = f"fulltext-{suffix}-{h(item.get('id'))}"
            return f"""
<article class="card reader-card">
  {thumb}
  <div class="reader-body">
    <div>
      {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
      {badge(status_label(item.get("status", "")), "neutral")}
      {badge(content_kind_label(kind), "neutral")}
      {reader_flag_badges(item)}
      {license_badge_html(item)}
    </div>
    <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
    <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))}</p>
    <p class="zh-summary">{h(item_zh_summary(item, 260))}</p>
    {tag_chips_html(item_visible_tags(item, 5))}
    {note_html}
    <div class="button-row reader-card-actions" aria-label="文章操作">
      <a class="button reader-action-button" href="{h(item_detail_href(item))}" aria-label="閱讀 / 記錄" title="閱讀 / 記錄">{icon_span("read", "O", "icon reader-action-icon")}{action_label("閱讀 / 記錄")}</a>
      {reading_priority_form(item, reader_redirect, compact=True)}
      <form method="post" action="/items/read-more" data-read-more-form data-target="#{fulltext_id}">
        <input type="hidden" name="id" value="{h(item.get('id'))}">
        <input type="hidden" name="redirect" value="{h(reader_redirect)}">
        <button type="submit" class="secondary reader-action-button" aria-label="展開全文" title="展開全文">{icon_span("expand", "E", "icon reader-action-icon")}{action_label("展開全文")}</button>
      </form>
      <a class="button secondary reader-action-button" href="{h(item.get('url'))}" target="_blank" rel="noreferrer" aria-label="原始連結" title="原始連結">{icon_span("external", "L", "icon reader-action-icon")}{action_label("原始連結")}</a>
    </div>
    <section class="fulltext-panel source-card source-card--source" id="{fulltext_id}" hidden>
      <div class="section-kicker">原始主文</div>
      <p class="help" data-fulltext-meta></p>
      <div class="article-text article-markdown" data-fulltext-body></div>
      <div class="button-row" data-translation-actions hidden></div>
    </section>
  </div>
</article>
"""

        def reader_list_row(item: dict) -> str:
            kind = item_display_kind(item)
            return f"""
<article class="reader-list-card">
  <div class="reader-list-meta">
    {badge(content_kind_label(kind), "neutral")}
    {reader_flag_badges(item)}
    {license_badge_html(item)}
    {badge(item_display_time(item, 'published_at', 'captured_at'), "neutral")}
  </div>
  <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
  <p class="zh-summary">{h(item_zh_summary(item, 360))}</p>
  {tag_chips_html(item_visible_tags(item, 6))}
</article>
"""

        def reader_compact_row(item: dict) -> str:
            return f"""
<article class="reader-compact-row">
  <span class="reader-dot" aria-hidden="true"></span>
  <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
  <div class="reader-row-time">{h(item_display_time(item, 'published_at', 'captured_at'))}</div>
</article>
"""

        def reader_section(section_id: str, title: str, description: str, section_items: list[dict], default_layout: str, timeline: bool = False) -> str:
            cards_html = "".join(reader_card(item, f"{section_id}-card") for item in section_items)
            list_html = "".join(reader_list_row(item) for item in section_items)
            compact_html = "".join(reader_compact_row(item) for item in section_items)
            empty = '<div class="card"><p class="muted">目前沒有符合這個區塊的文章。</p></div>'
            if timeline:
                return f"""
<details class="reader-period-details" id="{h(section_id)}" open>
  <summary class="reader-period-heading">
    <span class="reader-period-heading-label">{h(title)}</span>
    <span class="reader-period-count">{h(description)}</span>
  </summary>
  <div class="reader-grid">{cards_html or empty}</div>
  <div class="reader-list">{list_html or empty}</div>
  <div class="reader-compact-list">{compact_html or empty}</div>
</details>
"""
            header_title = "" if timeline else f"<h3>{h(title)}</h3>"
            description_html = f'<p class="muted">{h(description)}</p>' if description else ""
            return f"""
<section class="reader-layout-section" id="{h(section_id)}" data-layout="{h(default_layout)}">
  <div class="layout-bar">
    <div>
      {header_title}
      {description_html}
    </div>
    {layout_toggle(section_id, default_layout)}
  </div>
  <div class="reader-grid">{cards_html or empty}</div>
  <div class="reader-list">{list_html or empty}</div>
  <div class="reader-compact-list">{compact_html or empty}</div>
</section>
"""

        time_sorted_filtered = sorted(filtered, key=lambda item: (item_sort_time(item), item_display_title(item)), reverse=True)
        month_keys: list[str] = []
        for item in time_sorted_filtered:
            key = reader_month_key(item)
            if key not in month_keys:
                month_keys.append(key)
        visible_month_keys = set(month_keys[:month_limit])
        month_filtered = [item for item in filtered if reader_month_key(item) in visible_month_keys]
        visible_items = month_filtered[:180]
        hidden_month_count = max(0, len(month_keys) - month_limit)
        more_link = ""
        if hidden_month_count:
            more_parts = [part for part in redirect_parts if not part.startswith("months=")]
            more_parts.append(f"months={month_limit + 1}")
            more_href = "/reader?" + "&".join(more_parts)
            more_link = f'<p class="reader-more-row"><a class="button secondary" href="{h(more_href)}">more：再載入 1 個月</a> <span class="muted">還有 {hidden_month_count} 個月份未顯示。</span></p>'
        if not visible_items:
            if reading_filter == "current":
                reader_content = reader_section("reader-current", "優先正在閱讀區", "近期特別想讀、想分享，且後續 skill 會優先參考的文章。", [], "card")
            else:
                reader_content = '<div class="card"><strong>目前沒有符合條件的閱讀項目</strong><p class="muted">在入庫建檔區按「確認收」或「直接送 PR（小消息）」後，會出現在這裡。</p></div>'
        else:
            def timeline_sections(category_id: str, title: str, description: str, section_items: list[dict], default_layout: str) -> str:
                if not section_items:
                    return ""
                period_groups: list[tuple[str, list[dict]]] = []
                period_index: dict[str, int] = {}
                for section_item in section_items:
                    label = reader_period_label(section_item)
                    if label not in period_index:
                        period_index[label] = len(period_groups)
                        period_groups.append((label, []))
                    period_groups[period_index[label]][1].append(section_item)
                period_html = []
                for label, period_items in period_groups:
                    layout = view_mode if view_mode != "auto" else default_layout
                    period_html.append(
                        reader_section(
                            f"{category_id}-{reader_period_key(period_items[0])}",
                            label,
                            f"{len(period_items)} 筆",
                            period_items,
                            layout,
                            timeline=True,
                        )
                    )
                category_layout = view_mode if view_mode != "auto" else default_layout
                return f"""
<section class="reader-layout-section reader-category" id="{h(category_id)}" data-layout="{h(category_layout)}">
  <div class="layout-bar">
    <h2>{h(title)} {help_dot(description)}</h2>
    {layout_toggle(category_id, category_layout)}
  </div>
  {''.join(period_html)}
</section>
"""

            current_items = [item for item in visible_items if item_is_current_reading(item)]
            regular_items = [item for item in visible_items if not item_is_current_reading(item)]
            category_items = regular_items if kind_filter == "all" else visible_items
            primary_items = [item for item in category_items if item_display_kind(item) in {"featured-article", "opinion-article"}]
            small_news_items = [item for item in category_items if item_display_kind(item) == "small-news"]
            other_items = [item for item in category_items if item_display_kind(item) not in {"featured-article", "opinion-article", "small-news"}]
            sections = []
            if current_items and kind_filter == "all":
                sections.append(timeline_sections("reader-current", "優先正在閱讀區", "近期特別想讀、想分享，且後續編輯台會優先參考的材料。", current_items, "card"))
            if reading_filter == "current":
                reader_content = timeline_sections("reader-current", "優先正在閱讀區", "近期特別想讀、想分享，且後續編輯台會優先參考的材料。", visible_items, "card")
            else:
                if kind_filter in {"all", "featured-article", "opinion-article"}:
                    sections.append(timeline_sections("reader-primary", "可用材料與觀點材料", "適合細讀、整理觀點或後續放進編輯台的材料。", primary_items, "card"))
                if kind_filter in {"all", "small-news"}:
                    sections.append(timeline_sections("reader-small-news", "小消息列表", "純新聞消息維持列表模式，快速掃讀、必要時點進單篇。", small_news_items, "list"))
                if kind_filter in {"all", "needs-review"}:
                    sections.append(timeline_sections("reader-other", "其他待判斷", "尚未明確落在精選、觀點或小消息的閱讀項目。", other_items, "compact"))
                reader_content = "".join(section for section in sections if section) or '<div class="card"><strong>目前沒有符合條件的閱讀項目</strong></div>'

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        kind_options = [
            ("all", "全部類型"),
            ("featured-article", "可用材料 / 可進編輯台"),
            ("small-news", "純新聞 / 小消息"),
            ("opinion-article", "觀點文章"),
            ("needs-review", "人工判斷"),
        ]
        reading_options = [("all", "全部閱讀標記"), ("current", "優先正在閱讀 / 想分享")]
        license_options = license_filter_options(items)
        view_options = [("auto", "自動：分區預設"), ("card", "卡片"), ("list", "列表"), ("compact", "清單")]
        time_options = READER_TIME_FILTERS
        custom_hidden = "" if time_filter == "custom" else " hidden"
        custom_disabled = "" if time_filter == "custom" else " disabled"
        keyword_filters = []
        for keyword in keyword_options:
            checked = " checked" if keyword in selected_keywords else ""
            count = keyword_counts.get(keyword, 0)
            keyword_filters.append(
                f"""
<label class="keyword-option">
  <input type="checkbox" name="keyword" value="{h(keyword)}"{checked}>
  {h(keyword)} <span class="muted">({count})</span>
</label>
"""
            )
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用關鍵字 / tag。</p>'

        def reader_metric_href(track: str = "", kind: str = "") -> str:
            params = [("time", "all")]
            if track:
                params.append(("track", track))
            if kind:
                params.append(("kind", kind))
            if license_filter != "all":
                params.append(("license", license_filter))
            if text_filter:
                params.append(("q", text_filter))
            for keyword in sorted(selected_keywords):
                params.append(("keyword", keyword))
            return href_with_query("/reader", params)

        def reader_reading_href() -> str:
            params = [("time", "all"), ("reading", "current")]
            if license_filter != "all":
                params.append(("license", license_filter))
            if text_filter:
                params.append(("q", text_filter))
            for keyword in sorted(selected_keywords):
                params.append(("keyword", keyword))
            return href_with_query("/reader", params)

        body = f"""
<h1>閱讀區</h1>
<p class="lede">這裡放已確認收下的精選文章與小消息。你可以像讀線上報一樣瀏覽，也可以在單篇頁留下「我的關鍵紀錄」，再把文章依你的觀點重新送回 skill。</p>
{notice}
<div class="grid">
  {metric_card(len(metric_source_items), "可閱讀項目", reader_metric_href(), "看全部", "is-active" if track_filter == "all" and kind_filter == "all" and reading_filter == "all" and time_filter == "all" else "")}
  {metric_card(sum(1 for item in metric_source_items if item_is_current_reading(item)), "優先正在閱讀", reader_reading_href(), "看正在讀", "is-active" if reading_filter == "current" else "")}
  {metric_card(track_counts.get("open-tech-open-industry", 0), "開放科技", reader_metric_href(track="open-tech-open-industry"), "只看開放科技", "is-active" if track_filter == "open-tech-open-industry" else "")}
  {metric_card(track_counts.get("digital-humanities-local-knowledge", 0), "人文知識", reader_metric_href(track="digital-humanities-local-knowledge"), "只看人文知識", "is-active" if track_filter == "digital-humanities-local-knowledge" else "")}
  {metric_card(kind_counts.get("small-news", 0), "小消息", reader_metric_href(kind="small-news"), "只看小消息", "is-active" if kind_filter == "small-news" else "")}
</div>
<div class="workspace-toolbar">
  {workspace_sidebar_toggle("reader-workspace", "reader-sidebar", "reader", "篩選工具")}
</div>
<div class="workspace-layout" id="reader-workspace">
  <section class="workspace-main">
    <h2>文章</h2>
    <p class="muted">符合條件：{len(filtered)} 筆。時間：{h(reader_time_summary(time_filter, start_date, end_date))}。目前顯示最近 {month_limit} 個月份、至多 180 筆。</p>
    {reader_content}
    {more_link}
  </section>
  <aside class="workspace-sidebar" id="reader-sidebar">
    <section class="workspace-sidebar-section">
      <h2>篩選閱讀</h2>
      <form class="filter-panel" method="get" action="/reader" id="reader-filter-form"
        data-instant-filter data-instant-filter-targets=".grid,#reader-workspace .workspace-main,#reader-sidebar">
        <label>搜尋</label>
        <input type="search" name="q" class="auto-filter" value="{h(text_filter)}" placeholder="標題、來源、URL、摘要、tag">
        <div class="sidebar-field-group">
          <h3>內容</h3>
          <div class="form-grid">
            <div>
              <label>主線</label>
              <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
            </div>
            <div>
              <label>文章類型</label>
              <select name="kind" class="auto-filter">{option_list(kind_options, kind_filter)}</select>
            </div>
            <div>
              <label>閱讀標記</label>
              <select name="reading" class="auto-filter">{option_list(reading_options, reading_filter)}</select>
            </div>
            <div>
              <label>授權</label>
              <select name="license" class="auto-filter">{option_list(license_options, license_filter)}</select>
            </div>
          </div>
        </div>
        <div class="sidebar-field-group">
          <h3>顯示</h3>
          <div class="form-grid">
            <div>
              <label>顯示格式</label>
              <select name="view" class="auto-filter">{option_list(view_options, view_mode)}</select>
            </div>
            <div>
              <label>時間</label>
              <select name="time" class="auto-filter" id="reader-time-filter">{option_list(time_options, time_filter)}</select>
            </div>
          </div>
          <div class="date-range-fields" data-time-custom-fields{custom_hidden}>
            <div>
              <label>開始日期</label>
              <input type="date" name="start" value="{h(start_date)}"{custom_disabled}>
            </div>
            <div>
              <label>結束日期</label>
              <input type="date" name="end" value="{h(end_date)}"{custom_disabled}>
            </div>
          </div>
        </div>
        <label>關鍵字 / tag</label>
        <div class="keyword-filters">{keyword_filter_html}</div>
        <div class="button-row">
          <a class="button secondary" href="/reader">清除篩選</a>
          <a class="button quiet" href="/items">回入庫建檔區</a>
        </div>
        <p class="help">搜尋與篩選會同步套用到左側閱讀清單與統計。</p>
      </form>
    </section>
  </aside>
</div>
<script>
(() => {{
window.syncReaderTimeFields = function syncReaderTimeFields() {{
  const readerTimeFilter = document.getElementById("reader-time-filter");
  const readerTimeFields = document.querySelector("[data-time-custom-fields]");
  if (!readerTimeFilter || !readerTimeFields) return;
  const isCustom = readerTimeFilter.value === "custom";
  readerTimeFields.hidden = !isCustom;
  readerTimeFields.querySelectorAll("input").forEach((field) => {{
    field.disabled = !isCustom;
  }});
}};
window.initReaderPage = function initReaderPage() {{
  window.syncReaderTimeFields();
}};
if (document.readyState === "loading") {{
  document.addEventListener("DOMContentLoaded", window.initReaderPage, {{once: true}});
}} else {{
  window.initReaderPage();
}}
}})();
</script>
"""
        self.send_html("閱讀區", body)

    def show_item_detail(self, query: dict[str, list[str]]) -> None:
        item_id = form_value(query, "id")
        all_items = load_jsonl(ITEMS)
        candidate_records = load_jsonl(CANDIDATES)
        item = next((row for row in all_items if row.get("id") == item_id), None)
        is_rss_candidate = False
        if not item:
            item = next((row for row in candidate_records if row.get("id") == item_id), None)
            is_rss_candidate = bool(item)
            if not item:
                self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
                return
        item, _ = complete_item_metadata(item)

        def sort_detail_context(records: list[dict]) -> list[dict]:
            return sorted(records, key=lambda row: (item_sort_time(row), item_display_title(row)), reverse=True)

        inbox_context = sort_detail_context([*candidate_records, *[row for row in all_items if row.get("status") == "inbox"]])
        reader_context = sort_detail_context([row for row in all_items if is_reader_item(row)])
        all_context = sort_detail_context(all_items)
        if is_rss_candidate or item.get("status") == "inbox":
            context_records = inbox_context
            context_home = "/items"
            context_home_label = "回入庫建檔區"
        elif is_reader_item(item):
            context_records = reader_context
            context_home = "/reader"
            context_home_label = "回閱讀區"
        else:
            context_records = all_context
            context_home = "/items"
            context_home_label = "回入庫建檔區"
        context_ids = [clean_text(row.get("id")) for row in context_records]
        current_index = context_ids.index(item_id) if item_id in context_ids else -1
        previous_item = context_records[current_index - 1] if current_index > 0 else None
        next_item = context_records[current_index + 1] if 0 <= current_index < len(context_records) - 1 else None
        previous_href = item_detail_href(previous_item) if previous_item else ""
        next_href = item_detail_href(next_item) if next_item else ""
        decision_redirect = next_href or context_home

        saved = (query.get("saved") or [""])[0]
        notice = ""
        if saved == "note":
            notice = '<div class="notice">已更新你的個人關鍵紀錄。</div>'
        elif saved == "tags":
            notice = '<div class="notice">已更新概念 tag。後續閱讀區篩選、卡片顯示與本機規則重跑都會看得到。</div>'
        elif saved == "reading_priority":
            notice = '<div class="notice">已更新近期正在閱讀 / 想分享標記。後續挑材料進編輯台時會優先看到這類項目。</div>'
        elif saved == "requeue":
            notice = '<div class="notice">已重新送回可用材料區。你的個人觀點會留在紀錄裡，後續撰稿要一起參考。</div>'
        elif saved == "read_more":
            notice = '<div class="notice">已嘗試載入原始主文與頁面資料；若抓到全文，已寫入閱讀資料庫並顯示在「原始主文」。</div>'
        elif saved == "codex_review":
            notice = '<div class="notice">已補上模型閱讀建議；如果有抓到全文，這次會優先依全文判斷。</div>'
        elif saved == "url":
            notice = '<div class="notice">已更新原始網址。接著可以按「展開全文」重新抓文章內容。</div>'
        elif saved == "title":
            notice = '<div class="notice">已更新這篇的對外顯示標題。</div>'
        elif saved == "metadata":
            notice = '<div class="notice">已更新這篇的原始 metadata。</div>'
        elif saved == "translation":
            notice = '<div class="notice">已完成中文翻譯，並存回閱讀資料庫。</div>'
        elif saved == "newsletter_links":
            created = h((query.get("created") or ["0"])[0])
            duplicates = h((query.get("duplicates") or ["0"])[0])
            skipped = h((query.get("skipped") or ["0"])[0])
            notice = f'<div class="notice">已拆出彙整式電子報 link：新增 {created} 筆到入庫建檔區，重複 {duplicates} 筆，略過 {skipped} 筆功能性或非文章連結。</div>'
        elif saved == "pdf_markdown":
            notice = '<div class="notice">已將 PDF / MarkItDown 文字補成 Markdown 全文；接下來模型建議、翻譯與編輯台會優先使用這份全文。</div>'
        elif saved == "pdf_upload":
            notice = '<div class="notice">PDF 已進入入庫建檔區，全文由 markitdown 抽取完成。請確認跳出的來源與材料關係候選。</div>'
        elif saved == "pdf_duplicate":
            notice = '<div class="notice">這份 PDF 內容已經入庫，已帶你回到原本的材料。</div>'
        elif saved == "pdf_relation":
            notice = '<div class="notice">已更新 PDF 和既有材料的人工確認結果。</div>'
        elif saved == "fulltext":
            notice = '<div class="notice">已補入全文來源，並標明是貼上連結、手動貼文或上傳 PDF。</div>'
        elif saved == "fulltext_edit":
            notice = '<div class="notice">已儲存你線上修正後的全文，閱讀區與編輯台都會用這份。</div>'
        elif saved == "repaginate":
            notice = '<div class="notice">已用 AI 重新分段（只重排段落、未改字詞）。如不滿意可再「編輯 PDF 全文」手動微調。</div>'
        elif (query.get("error") or [""])[0] == "repaginate":
            notice = '<div class="notice">這次沒能順利重新分段（引擎不可用或輸出與原文差太多）。可改用「編輯 PDF 全文」手動分段。</div>'
        elif saved == "pdf_split":
            created = h((query.get("created") or ["0"])[0])
            failed = clean_text((query.get("failed") or ["0"])[0]) or "0"
            failed_note = (
                f"；還有 {h(failed)} 篇沒定位到，已保留你改過的標記在下方提案，修正後可再送一次。"
                if failed != "0"
                else "。"
            )
            notice = f'<div class="notice">已依人工確認的起訖標記拆出 {created} 篇材料，先進入入庫建檔區{failed_note}</div>'
        elif (query.get("error") or [""])[0] == "read_more":
            notice = '<div class="notice">這次沒有抓到更多資料。可能是網站擋住讀取、網址需要登入，或頁面沒有可抽取的主文。</div>'
        elif (query.get("error") or [""])[0] == "codex_review":
            notice = '<div class="notice">這次沒有順利補上模型閱讀建議。可以稍後再試，或先按「展開全文」補資料後再生成。</div>'
        elif (query.get("error") or [""])[0] == "url_resolve":
            notice = '<div class="notice">這次無法解析跳轉後網址。你仍可手動貼上實際文章網址再儲存。</div>'
        elif (query.get("error") or [""])[0] == "translation":
            notice = '<div class="notice">這次沒有順利翻譯。請先確認已展開全文，或稍後再試。</div>'
        elif (query.get("error") or [""])[0] == "pdf_markdown":
            upload_href = f"/items/upload-pdf?parent_item_id={quote(clean_text(item.get('id')))}&relation=full-source&track={quote(clean_text(item.get('track')))}"
            notice = (
                '<div class="notice">沒能抓到完整 PDF 全文。如果來源是 PDF 網址，常見原因是該網站擋掉自動下載'
                '（例如 403／需登入／WAF 防爬）。請在瀏覽器把 PDF 存下來，再用 '
                f'<a href="{h(upload_href)}">上傳全文 PDF</a> 把檔案貼進來，系統會用 markitdown 抽完整全文。</div>'
            )

        css_class = track_class(item.get("track", "unclassified"))
        triage = item.get("triage") or {}
        kind = item_display_kind(item)
        image = item_image_url(item)
        image_html = (
            f"<div class='item-image item-image--compact'><img src='{h(image)}' alt=''></div>"
            if image
            else f"<div class='item-image item-image--compact'>{h(track_meta(item.get('track', 'unclassified'))['short'])}</div>"
        )
        article_text = item_article_text(item)
        article_markdown = item_article_markdown(item)
        article_meta = item_reading_metadata(item)
        display_title = item_display_title(item)
        edited_markdown = item_edited_markdown(item)
        translation_entries = item_translation_entries(item)
        has_translation = bool(translation_entries)
        is_edited = bool(edited_markdown)
        article_html = markdown_to_html(strip_duplicate_leading_heading(article_markdown, display_title)) if article_markdown else ""
        original_title = item_original_title(item)
        original_language = item_original_language(item)
        translate_actions = translation_actions_html(item, item_id, item_detail_href(item))
        translate_actions_row = f'<div class="button-row" data-translation-actions{"" if translate_actions else " hidden"}>{translate_actions}</div>'
        fulltext_hidden = "" if article_markdown or article_text else " hidden"
        fulltext_message = (
            f"Markdown 閱讀版，約 {article_meta.get('article_markdown_chars', len(article_markdown)) or article_meta.get('article_text_chars', len(article_text))} 字；抽取方式：{article_meta.get('article_markdown_method') or article_meta.get('article_text_method', 'metadata')}。"
            if article_markdown or article_text
            else "按「展開全文」後會從原始連結往下抓全文，載入完成後以 Markdown 閱讀版顯示在這裡。"
        )
        # 「編輯全文」入口：任何有全文（原文／翻譯／已編輯）的材料都能改排版或補截斷
        edit_fulltext_label = "編輯中文 Markdown" if has_translation else "編輯全文"
        edit_fulltext_button = (
            f'<a class="button button-small" href="/items/edit-fulltext?id={quote(item_id)}">{button_content(edit_fulltext_label, "edit")}</a>'
            if (article_markdown or article_text or has_translation or is_edited) and not is_rss_candidate
            else ""
        )
        # 原文面板：read-more 目標，永遠帶 #fulltext-panel / data-fulltext-body / 翻譯動作。
        # 原文本身就是主全文時 prominent；有翻譯或已編輯時收合成比對用。
        original_is_primary = not (is_edited or has_translation)
        if original_is_primary:
            original_fulltext_panel = f"""
<section class="card fulltext-panel source-card source-card--source" id="fulltext-panel"{fulltext_hidden}>
  <div class="section-kicker">原始主文</div>
  <p class="help" data-fulltext-meta>{h(fulltext_message)}</p>
  <div class="article-text article-markdown" data-fulltext-body>{article_html}</div>
  {translate_actions_row}
</section>
"""
        else:
            original_translation_row = "" if is_edited else translate_actions_row
            original_fulltext_panel = f"""
<details class="card fulltext-panel source-card source-card--source original-fulltext-collapsible" id="fulltext-panel"{fulltext_hidden}>
  <summary><div class="section-kicker">原始主文（原文）</div></summary>
  <p class="help" data-fulltext-meta>{h(fulltext_message)}</p>
  <div class="article-text article-markdown" data-fulltext-body>{article_html}</div>
  {original_translation_row}
</details>
"""
        # 主全文（編輯版）面板：手動修正後成為要讀的版本
        primary_fulltext_panel = ""
        if is_edited:
            edited_html = markdown_to_html(
                strip_duplicate_leading_heading(edited_markdown, display_title),
                preserve_soft_breaks=True,
            )
            primary_fulltext_panel = f"""
<section class="card fulltext-panel source-card source-card--source" id="primary-fulltext-panel">
  <div class="section-kicker">全文（已手動修正）</div>
  <div class="article-text article-markdown">{edited_html}</div>
  {translate_actions_row}
</section>
"""
        # 自動翻譯：沒編輯時當主全文（prominent + 編輯鈕）；編輯後收合供比對（point 2）
        if has_translation and is_edited:
            translation_panel = translation_panels_html(item, collapsed=True)
        elif has_translation:
            translation_panel = translation_panels_html(item)
        else:
            translation_panel = ""
        # 閱讀區順序：主全文（編輯版）→ 翻譯 → 原文
        reading_panels = primary_fulltext_panel + translation_panel + original_fulltext_panel
        note = personal_note_text(item)
        item_url = clean_text(item.get("url"), 1200)
        online_article_url = public_reader_article_url(item)
        external_title_action = (
            f'<a class="title-icon-button" href="{h(item_url)}" target="_blank" rel="noreferrer" aria-label="開啟原始網頁" title="開啟原始網頁">{icon_span("external", "", "icon reader-action-icon")}</a>'
            if item_url
            else ""
        )
        share_title_action = f"""
    <details class="article-title-menu share-menu">
      <summary class="title-icon-button" aria-label="分享線上版" title="分享線上版">{icon_span("share", "", "icon reader-action-icon")}</summary>
      <div class="title-popover share-panel">
        <label>線上版網址</label>
        <input class="share-url-field" value="{h(online_article_url)}" readonly data-share-url-field onclick="this.select()">
        <div class="button-row">
          <button type="button" class="button button-small" data-copy-share-url="{h(online_article_url)}">{button_content("複製網址", "copy")}</button>
          <a class="button button-small secondary" href="{h(online_article_url)}" target="_blank" rel="noreferrer">{button_content("開啟線上版", "external")}</a>
        </div>
        <p class="copy-status" data-copy-share-status></p>
      </div>
    </details>
"""
        note_updated = ""
        personal_notes = item.get("personal_notes")
        if isinstance(personal_notes, dict) and personal_notes.get("updated_at"):
            note_updated = f"<p class='help'>上次更新：{h(personal_notes.get('updated_at'))}</p>"
        tag_reference_records = [*all_items, *candidate_records, *load_jsonl(REJECTED_ITEMS)]
        tag_panel = tag_editor_html(item, tag_reference_records, item_detail_href(item), autosave=True)
        reading_priority_actions = "" if is_rss_candidate else reading_priority_form(item, item_detail_href(item))

        inbox_actions = ""
        if is_rss_candidate:
            reason_options = rejection_reason_options(load_jsonl(ITEMS))
            inbox_actions = f"""
<div class="card">
  <h2>RSS 新進決定 <span class="help-dot" title="確認收或直接送 PR 會先寫進 database/items.jsonl；不收會寫入學習檔與略過清單。">?</span></h2>
  <div class="button-row">
    <form method="post" action="/candidates/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="decision" value="accept">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
      <button type="submit">{button_content("確認收，放入可用材料區", "accept", "A")}</button>
    </form>
    <form method="post" action="/candidates/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="decision" value="accept_reading">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
      <button type="submit" class="reading-button">{button_content("閱讀中 / 超想看", "bookmark", "B")}</button>
    </form>
    <form method="post" action="/candidates/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="decision" value="direct_pr">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
      <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
    </form>
  </div>
  <p class="help">不收原因</p>
  <div class="reason-presets">{inline_reject_buttons(item_id, prioritized_rejection_reasons(item, reason_options), action="/candidates/dismiss", redirect_to=decision_redirect)}</div>
  <details class="inline-reason">
    <summary>其他原因</summary>
    <form method="post" action="/candidates/dismiss">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
      <label>這次不收的原因</label>
      <textarea name="reason" required></textarea>
      <button type="submit" class="danger">{button_content("確認不收並記錄原因", "reject", "X")}</button>
    </form>
  </details>
</div>
"""
        else:
            action_title = "分流"
            action_help = (
                "這則還在待整理。下方「修改為」可直接分流；Codex、來源與關鍵字判斷在下面供比較。"
                if item.get("status") == "inbox"
                else "可重新分流：標成可進編輯台、近期正在讀、小消息，或改成不收。"
            )
            _flow_status = clean_text(item.get("status"))
            # flow_state 對應下方分流按鈕的 hover 色：
            # accept→primary(紫)、reading→magenda(洋紅)、small-news(secondary)→cyan(青)、reject→danger、inbox→neutral
            if _flow_status in {"rejected", "archived"}:
                flow_current = "不收 / 封存"
                flow_state = "reject"
            elif is_direct_pr_item(item):
                flow_current = "小消息（直接送 PR）"
                flow_state = "small-news"
            elif item_is_current_reading(item):
                flow_current = "閱讀中 / 超想看"
                flow_state = "reading"
            elif _flow_status == "inbox":
                flow_current = "入庫建檔區（待整理）"
                flow_state = "inbox"
            elif is_skill_candidate(item) or _flow_status == "triaged":
                flow_current = "可用材料（可進編輯台）"
                flow_state = "accept"
            else:
                flow_current = status_label(_flow_status) or "待整理"
                flow_state = "inbox"
            # 入庫建檔區（inbox）維持語彙色；可用材料區（已判斷）才用白底→hover 上色
            flow_cls = "flow-options" if _flow_status == "inbox" else "flow-options--review"
            reason_options = rejection_reason_options(load_jsonl(ITEMS))
            inbox_actions = f"""
<div class="card">
  <h2>{h(action_title)} <span class="help-dot" title="{h(action_help)}">?</span></h2>
  <p class="flow-line">目前為：<span class="flow-current flow-current--{h(flow_state)}">{h(flow_current)}</span></p>
  <p class="flow-line flow-line--change">修改為：</p>
  <div class="button-row {flow_cls}">
    <form method="post" action="/items/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
        <button type="submit">{button_content("確認收，放入可用材料區", "accept", "A")}</button>
    </form>
    <form method="post" action="/items/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="mark_reading" value="1">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
        <button type="submit" class="reading-button">{button_content("閱讀中 / 超想看", "bookmark", "B")}</button>
    </form>
    <form method="post" action="/items/direct-pr">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
        <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
    </form>
  </div>
  <p class="help">或改成不收（選原因）</p>
  <div class="reason-presets {flow_cls}">{inline_reject_buttons(item_id, prioritized_rejection_reasons(item, reason_options), action="/items/reject", redirect_to=decision_redirect)}</div>
  <details class="inline-reason">
    <summary>其他原因</summary>
    <form method="post" action="/items/reject">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="redirect" value="{h(decision_redirect)}">
      <label>這次不收的原因</label>
      <textarea name="reason" required></textarea>
      <button type="submit" class="danger">{button_content("確認不收並記錄原因", "reject", "X")}</button>
    </form>
  </details>
</div>
"""

        skill_requests = item.get("skill_requests") if isinstance(item.get("skill_requests"), list) else []
        skill_rows = ""
        if skill_requests:
            rows = []
            for request in skill_requests[-5:]:
                rows.append(f"<li>{h(request.get('requested_at', ''))}：{h(clean_text(request.get('personal_notes'), 160))}</li>")
            skill_rows = f"<div class='card'><h2>送回編輯台紀錄</h2><ul>{''.join(rows)}</ul></div>"

        read_more_actions = f"""
      <form method="post" action="/items/read-more" data-read-more-form data-target="#fulltext-panel">
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
        <button type="submit">展開全文</button>
      </form>
"""
        newsletter_candidates, newsletter_skipped = newsletter_link_candidates(item)
        extraction_meta = article_meta.get("newsletter_link_extraction") if isinstance(article_meta.get("newsletter_link_extraction"), dict) else {}
        extraction_status = ""
        if extraction_meta:
            extraction_status = (
                f"<p class='help'>上次拆出：新增 {h(extraction_meta.get('imported_count', 0))} 筆，"
                f"重複 {h(extraction_meta.get('duplicate_count', 0))} 筆，"
                f"略過 {h(extraction_meta.get('skipped_count', 0))} 筆。"
                f"<br>時間：{h(extraction_meta.get('extracted_at'))}</p>"
            )
        derived_actions: list[str] = []
        if newsletter_candidates:
            nl_cand_rows = "".join(
                f'<label class="nl-cand"><input type="checkbox" name="url" value="{h(clean_text(c.get("url")))}" checked>'
                f'<span class="nl-cand-title">{h(clean_text(c.get("title")) or clean_text(c.get("url")))}</span>'
                f'<span class="nl-cand-host">{h(host_label(clean_text(c.get("url"))))}</span></label>'
                for c in newsletter_candidates
            )
            nl_skip_block = ""
            if newsletter_skipped:
                # 「不像獨立文章」→ 給 unchecked checkbox，讓使用者手動勾選
                # 真正功能性的（subscribe / unsubscribe / social）→ 只列文字，不給 checkbox
                SELECTABLE_SKIP_REASONS = {"不像獨立文章"}
                nl_skip_selectable = [s for s in newsletter_skipped[:40] if s.get("reason") in SELECTABLE_SKIP_REASONS]
                nl_skip_info = [s for s in newsletter_skipped[:40] if s.get("reason") not in SELECTABLE_SKIP_REASONS]
                skip_parts = []
                if nl_skip_selectable:
                    selectable_rows = "".join(
                        f'<label class="nl-cand nl-cand--skip">'
                        f'<input type="checkbox" name="url" value="{h(clean_text(s.get("url")))}">'
                        f'<span class="nl-cand-title">{h(clean_text(s.get("title")) or clean_text(s.get("url")))}</span>'
                        f'<span class="nl-cand-host muted">— {h(s.get("reason", ""))}</span></label>'
                        for s in nl_skip_selectable
                    )
                    skip_parts.append(f'<p class="help">系統未自動選，但你可以手動勾選：</p>{selectable_rows}')
                if nl_skip_info:
                    info_rows = "".join(
                        f'<li>{h(clean_text(s.get("title")) or clean_text(s.get("url")))} <span class="muted">— {h(clean_text(s.get("reason"), 60))}</span></li>'
                        for s in nl_skip_info
                    )
                    skip_parts.append(f'<ul>{info_rows}</ul>')
                nl_skip_block = (
                    f'<details class="nl-skip"><summary>系統判斷略過 {len(newsletter_skipped)} 個</summary>'
                    + "".join(skip_parts)
                    + "</details>"
                )
            derived_actions.append(
                f"""
    <button type="button" class="secondary" onclick="document.getElementById('nl-dialog').showModal()">{button_content(f'拆出文章 link（{len(newsletter_candidates)}）', 'source')}</button>
    <dialog id="nl-dialog" class="pdf-relation-dialog nl-dialog">
      <form method="dialog" class="dialog-close-row"><button class="quiet">{button_content('關閉', 'clear')}</button></form>
      <h2>選要入庫的文章連結</h2>
      <p class="help">先勾選真的想收的連結再入庫，避免彙整電子報裡的雜訊整批進入庫建檔區。預設全勾。</p>
      <form method="post" action="/items/extract-newsletter-links">
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
        <input type="hidden" name="selected" value="1">
        <div class="button-row">
          <button type="button" class="button button-small quiet" onclick="this.closest('form').querySelectorAll('input[name=url]').forEach(b=>b.checked=true)">全選</button>
          <button type="button" class="button button-small quiet" onclick="this.closest('form').querySelectorAll('input[name=url]').forEach(b=>b.checked=false)">全不選</button>
        </div>
        <div class="nl-cand-list">{nl_cand_rows}</div>
        {nl_skip_block}
        <div class="button-row" style="margin-top:12px">
          <button type="submit">{button_content('入庫勾選的連結', 'accept')}</button>
          <button type="button" class="quiet" onclick="this.closest('dialog').close()">取消</button>
        </div>
        <p class="help">入庫的連結會先進入庫建檔區，照單篇材料審核流程處理；重複網址會自動略過。</p>
      </form>
    </dialog>
"""
            )
            derived_actions.append(
                f'<a class="button quiet" href="/editor?items={quote(item_id)}&task=newsletter-extract">{button_content("做彙整萃取報告", "note")}</a>'
            )
        if item_is_pdf_like(item):
            if article_markdown:
                # 已經有全文 → 主要動作是「線上編輯」修正轉檔；重新抽取改成次要。
                derived_actions.append(
                    f'<a class="button" href="/items/edit-fulltext?id={quote(item_id)}">{button_content("編輯 PDF 全文（線上修正）", "edit")}</a>'
                )
                if item_markdown_needs_paragraphs(item):
                    derived_actions.append(
                        f"""
    <form method="post" action="/items/repaginate-fulltext">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="provider" value="claude">
      <button type="submit" class="secondary">{button_content("用 AI 重新分段（快速）", "sparkle")}</button>
    </form>
"""
                    )
                derived_actions.append(
                    f"""
    <form method="post" action="/items/pdf-markdown">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
      <button type="submit" class="quiet">{button_content("重新抽取全文", "text-lines")}</button>
    </form>
"""
                )
            else:
                derived_actions.append(
                    f"""
    <form method="post" action="/items/pdf-markdown">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
      <button type="submit" class="secondary">{button_content("補成 PDF Markdown 全文", "text-lines")}</button>
    </form>
"""
                )
            derived_actions.append(
                f"""
    <button type="button" class="secondary" data-pdf-split-random data-item-id="{h(item_id)}">{button_content("建議拆分方式（隨機兩個 CLI）", "sparkle")}</button>
    <details>
      <summary class="button quiet">指定兩個 CLI</summary>
      <form data-pdf-split-specified>
        <input type="hidden" name="id" value="{h(item_id)}">
        <select name="engine_a">{option_list([(provider, AI_PROVIDER_META[provider]["label"]) for provider in AI_PROVIDER_ORDER], "codex")}</select>
        <select name="engine_b">{option_list([(provider, AI_PROVIDER_META[provider]["label"]) for provider in AI_PROVIDER_ORDER], "claude")}</select>
        <button type="submit" class="button button-small">產生兩份草案</button>
      </form>
    </details>
"""
            )
        fulltext_panel = ""
        if not is_rss_candidate:
            suggested_fulltext_url = clean_text(
                article_meta.get("fulltext_source_url")
                or article_meta.get("preferred_fulltext_url")
                or item.get("url")
            )
            fulltext_issue = clean_text(article_meta.get("fulltext_note") or article_meta.get("access_issue_note"), 500)
            fulltext_issue_html = (
                f'<div class="notice">這篇需要補全文：{h(fulltext_issue)}</div>'
                if fulltext_issue
                else ""
            )
            fulltext_help = (
                "如果自動抓文只抓到摘要、相關文章卡片，或原站還有更多正文，就用這裡補全文。"
                if not fulltext_issue
                else "可以改貼全文頁、手動貼文，或上傳 PDF 來補完整材料。"
            )
            fulltext_panel = f"""
  <details class="card">
    <summary><h2>補全文 <span class="help-dot" title="自動抓文不完整或抓錯段落時，從這裡補上完整來源。">?</span></h2></summary>
    {fulltext_issue_html}
    <p class="help">{h(fulltext_help)}</p>
    <form method="post" action="/items/fulltext-link">
      <input type="hidden" name="id" value="{h(item_id)}">
      <label>貼全文連結</label>
      <input name="url" type="url" value="{h(suggested_fulltext_url)}" placeholder="https://..." required>
      <button type="submit" class="button button-small">抓取這個全文連結</button>
    </form>
    <form method="post" action="/items/fulltext-text">
      <input type="hidden" name="id" value="{h(item_id)}">
      <label>貼上我找到的全文文字</label>
      <textarea name="fulltext" required></textarea>
      <button type="submit" class="button button-small secondary">存成手動貼文全文</button>
    </form>
    <a class="button quiet" href="/items/upload-pdf?parent_item_id={quote(item_id)}&relation=full-source&track={quote(clean_text(item.get('track')))}">{button_content("上傳全文 PDF", "text-lines")}</a>
    <p class="help">全文會清楚標記來源；上傳 PDF 會建立新的材料並以 full-source 關聯連回這篇。</p>
  </details>
"""
        ai_toolbox = ""
        review_redirect = item_detail_href(item)
        review_button_label = "AI 建議有事實錯誤，重跑覆蓋" if record_model_reviews(item) else "隨機補 AI 閱讀建議"
        ai_toolbox = f"""
  <div class="card">
    <h2>AI 工具箱 <span class="help-dot" title="針對這一篇重跑模型閱讀建議，不影響分流狀態。">?</span></h2>
    <form method="post" action="/items/codex-review" data-codex-review-form>
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="redirect" value="{h(review_redirect)}">
      <input type="hidden" name="with_fulltext" value="1">
      <input type="hidden" name="provider" value="random">
      <input type="hidden" name="force" value="1">
      <input type="hidden" name="replace_reviews" value="1">
      <button type="submit" class="secondary">{button_content(review_button_label, "sparkle")}</button>
    </form>
    <p class="help">看到模型硬塞台灣關聯、摘要抓錯或理由怪怪的，就按這裡。會先重新抓一次全文，再用隨機可用 CLI 重跑；新結果成功後會取代既有模型閱讀建議與摘要。</p>
  </div>
"""
        derived_toolbox = ""
        if derived_actions:
            skipped_hint = f"；目前規則會略過 {len(newsletter_skipped)} 個功能性或非文章連結" if newsletter_candidates else ""
            derived_toolbox = f"""
  <div class="card">
    <h2>衍生材料工具箱 <span class="help-dot" title="處理彙整式電子報、PDF MarkItDown 這種不是一般單篇文章的材料。">?</span></h2>
    <div class="button-row article-dock-actions">
      {''.join(derived_actions)}
    </div>
    {extraction_status}
    <p class="help">拆出的文章會先進入入庫建檔區，不會直接變成可用材料{h(skipped_hint)}。</p>
  </div>
"""
        current_license = item_license_name(item)
        license_options = option_list([("", "未設定授權")] + [(name, name) for name in taxonomy_license_names()], current_license)
        license_json_value = ""
        if isinstance(item.get("license"), dict) and item.get("license"):
            license_json_value = json.dumps(item.get("license"), ensure_ascii=False, indent=2)
        metadata_form = f"""
    <details class="card metadata-dock">
      <summary><h2>原始 metadata</h2><span class="help-dot" title="手動修正網站標題、語言、授權與作者；這區需要按儲存。">?</span></summary>
      <form method="post" action="/items/update-metadata">
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
        <label>原始網站標題 {h(metadata_source_label(article_meta, "original_site_title"))}</label>
        <input name="original_site_title" value="{h(article_meta.get('original_site_title') or original_title)}" placeholder="原始網站標題">
        <label>原始語言 {h(metadata_source_label(article_meta, "original_language"))}</label>
        <input name="original_language" value="{h(original_language)}" placeholder="en / zh-Hant / ja">
        <p class="help">目前顯示：{h(language_label(original_language))}</p>
        <label>自動翻譯中文標題 {h(metadata_source_label(article_meta, "translated_zh_title"))}</label>
        <input name="translated_zh_title" value="{h(usable_zh_title(article_meta.get('translated_zh_title')) or item_codex_zh_title(item))}" placeholder="翻譯後的中文標題">
        <label>原始作者 {h(metadata_source_label(article_meta, "original_author"))}</label>
        <input name="original_author" value="{h(article_meta.get('original_author') or item.get('author', ''))}" placeholder="作者或組織">
        <label>原始網站授權 {h(metadata_source_label(article_meta, "original_license"))}</label>
        <input name="original_license" value="{h(article_meta.get('original_license', ''))}" placeholder="Creative Commons / 著作權保護 / 未標示">
        <label>授權連結</label>
        <input name="original_license_url" value="{h(article_meta.get('original_license_url', ''))}" placeholder="https://...">
        <label>正規化授權</label>
        <select name="license_name">{license_options}</select>
        <label>授權 JSON（進階，可保留 evidence / attribution_table）</label>
        <textarea name="license_json" placeholder='{{"name":"CC BY 4.0","attribution_table":[...]}}'>{h(license_json_value)}</textarea>
        <button type="submit">儲存 metadata</button>
      </form>
    </details>
"""
        status_badge = badge("RSS 新進", "neutral") if is_rss_candidate else badge(status_label(item.get("status", "")), "neutral")
        top_navigation = f"""
<nav class="article-top-nav" aria-label="返回">
  <a class="button article-back-button" href="{h(self.same_origin_referer_path(context_home))}">{icon_span("back", "", "icon")}上一頁</a>
  {workspace_sidebar_toggle("article-detail-workspace", "article-detail-sidebar", "article-detail", "文章工具")}
</nav>
"""
        previous_nav = (
            f'<a class="article-sequence-link article-sequence-link--prev" href="{h(previous_href)}">{icon_span("previous", "", "icon")}<span>上一則</span></a>'
            if previous_href
            else ""
        )
        next_nav = (
            f'<a class="article-sequence-link article-sequence-link--next" href="{h(next_href)}"><span>下一則</span>{icon_span("next", "", "icon")}</a>'
            if next_href
            else ""
        )
        bottom_navigation = f'<nav class="article-sequence-nav" aria-label="前後項目">{previous_nav}{next_nav}</nav>' if previous_nav or next_nav else ""
        personal_note_panel = "" if is_rss_candidate else f"""
  <div class="card" id="personal-note-panel">
    <h2>我的關鍵紀錄 <span class="help-dot" title="寫下你的判斷、疑問或想補的觀點；送回編輯台時會一起參考。">?</span></h2>
    <form method="post" action="/items/personal-note">
      <input type="hidden" name="id" value="{h(item_id)}">
      <textarea name="note" placeholder="例如：這篇和 OCF 的資料治理倡議有關，但要補台灣案例。">{h(note)}</textarea>
      <button type="submit">儲存我的紀錄</button>
    </form>
    {note_updated}
  </div>
  <div class="card">
    <h2>送回編輯台 <span class="help-dot" title="不會自動發 PR，只會留下編輯台回流紀錄並把狀態放回可進編輯台。">?</span></h2>
    <form method="post" action="/items/requeue-skill">
      <input type="hidden" name="id" value="{h(item_id)}">
      <button type="submit">用我的觀點送回編輯台</button>
    </form>
  </div>
"""
        existing_links = [link for link in load_jsonl(MATERIAL_LINKS) if clean_text(link.get("item_id")) == item_id]
        link_rows = ""
        for link in existing_links:
            ref = clean_text(link.get("ref"))
            title = clean_text(link.get("title")) or ref
            label = article_link_html(link)
            link_rows += (
                f'<li>{label} <span class="muted">{h(pdf_relation_label(clean_text(link.get("relation"))))}</span>'
                f'<form method="post" action="/editor/unlink-article" style="display:inline">'
                f'<input type="hidden" name="id" value="{h(link.get("id"))}">'
                f'<input type="hidden" name="item_id" value="{h(item_id)}">'
                f'<button type="submit" class="button button-small">移除</button></form></li>'
            )
        links_list = f'<ul class="editor-links">{link_rows}</ul>' if link_rows else '<p class="muted">尚未連結其他材料或 article。</p>'
        cited_articles = [] if is_rss_candidate else articles_citing_item(item_id)
        cited_rows = "".join(
            f'<li><a href="/articles/view?id={quote(clean_text(a.get("id")))}">{h(a.get("title"))}</a> '
            f'{badge(ARTICLE_STATUS_LABELS.get(clean_text(a.get("status")), ""), "neutral")}</li>'
            for a in cited_articles
        )
        cited_block = f'<h3 style="margin-top:14px">被專文引用（{len(cited_articles)}）</h3><ul>{cited_rows}</ul>' if cited_rows else ""
        editor_panel = "" if is_rss_candidate else f"""
  <div class="card" id="editor-panel">
    <h2>編輯台 <span class="help-dot" title="把這篇材料丟進編輯台草稿庫，跑選法檢查、撰稿或查核。只有編輯台產出的稿件才稱為 article。">?</span></h2>
    <a class="button" href="/editor?items={quote(item_id)}">{button_content('送進編輯台草稿庫', 'edit')}</a>
    {cited_block}
    <h3 style="margin-top:14px">連結到 article</h3>
    {links_list}
    <form method="post" action="/editor/link-article">
      <input type="hidden" name="item_id" value="{h(item_id)}">
      <label class="editor-label">article 連結或路徑<input type="text" name="ref" placeholder="docs/reader/articles/… 或 https://…"></label>
      <label class="editor-label">標題（可留空）<input type="text" name="title"></label>
      <button type="submit" class="button button-small">{button_content('建立連結', 'plus')}</button>
    </form>
  </div>
"""
        action_dock = f"""
<aside class="article-action-dock" id="article-detail-sidebar">
  <section class="article-tool-section">
    {inbox_actions}
  </section>
  <section class="article-tool-section">
    <div class="article-tool-section-title">閱讀與紀錄</div>
    <div class="card">
      <h2>閱讀操作 <span class="help-dot" title="這個面板會跟著畫面停在右側，讀到哪裡都能操作。">?</span></h2>
      <div class="button-row article-dock-actions">
        {read_more_actions}
        {edit_fulltext_button}
        {reading_priority_actions}
      </div>
    </div>
    {personal_note_panel}
  </section>
  <section class="article-tool-section">
    <div class="article-tool-section-title">整理與編輯</div>
    {tag_panel}
    {editor_panel}
  </section>
  <section class="article-tool-section">
    <div class="article-tool-section-title">補資料與輔助工具</div>
    {fulltext_panel}
    {ai_toolbox}
    {derived_toolbox}
    {metadata_form}
  </section>
</aside>
"""
        split_proposals = pdf_split_proposals_html(item) if item_is_pdf_like(item) else ""
        relation_modal = pdf_relation_modal_html(
            item,
            auto_open=form_value(query, "pdf_relations") == "1",
        ) if item_is_pdf_like(item) else ""
        body = f"""
{top_navigation}
{notice}
<div class="article-detail-layout" id="article-detail-workspace">
<div class="article-detail-main">
<div class="article-title-grid">
  <div>
    <div class="article-title-block">
      <div class="article-title-heading">
        <h1>{h(display_title)}</h1>
        <div class="article-title-tools">
          {external_title_action}
          <details class="article-title-menu title-editor">
            <summary class="title-icon-button" aria-label="編輯標題與原始網址" title="編輯標題與原始網址">{icon_span("edit", "", "icon reader-action-icon")}</summary>
            <div class="title-popover title-editor-fields">
              <form method="post" action="/items/update-title">
                <input type="hidden" name="id" value="{h(item_id)}">
                <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
                <label>對外顯示標題</label>
                <input name="title" value="{h(display_title)}" placeholder="輸入要顯示的中文標題">
                <button type="submit">儲存標題</button>
              </form>
              <form method="post" action="/items/update-url">
                <input type="hidden" name="id" value="{h(item_id)}">
                <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
                <label>原始網址</label>
                <p class="muted break-anywhere"><a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">{h(item.get('url') or '尚未填寫')}</a></p>
                <input name="url" value="{h(item.get('url', ''))}" placeholder="https://example.com/article">
                <div class="button-row">
                  <button type="submit" name="action" value="save">儲存網址</button>
                  <button type="submit" name="action" value="resolve" class="secondary">帶入跳轉後網址</button>
                </div>
              </form>
            </div>
          </details>
          {share_title_action}
        </div>
      </div>
      <span class="help">原始標題：{h(original_title)}</span>
    </div>
    <p class="lede break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))}</p>
  </div>
  {image_html}
</div>

  <section class="card">
    <div>
      {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
      {status_badge}
      {badge(content_kind_label(kind), "neutral")}
      {badge(recommendation_label(candidate_recommendation(item)), candidate_recommendation(item))}
      {reader_flag_badges(item)}
      {license_badge_html(item)}
    </div>
    <p class="zh-summary">{h(item_zh_summary(item, 780))}</p>
    {tag_chips_html(item_visible_tags(item, 8))}
    <p>{h(clean_text(item.get('summary'), 1800))}</p>
  </section>

{reading_panels}

<section class="article-detail-stack">
  <h2>閱讀建議與判斷來源</h2>
  {editorial_triage_html(item, reject_action='/candidates/dismiss' if is_rss_candidate else '/items/reject')}
  {skill_rows}
</section>
</div>
{action_dock}
</div>
{split_proposals}
{relation_modal}
{bottom_navigation}
"""
        self.send_html("單篇整理", body)

    @with_db_write_lock
    def pop_candidate(self, candidate_id: str) -> dict | None:
        candidates = load_jsonl(CANDIDATES)
        candidate = None
        remaining = []
        for row in candidates:
            if row.get("id") == candidate_id and candidate is None:
                candidate = row
                continue
            remaining.append(row)
        if candidate is None:
            return None
        write_jsonl(CANDIDATES, remaining)
        return candidate

    @with_db_write_lock
    def import_candidate_item(self, candidate_id: str) -> tuple[dict | None, bool]:
        candidate = self.pop_candidate(candidate_id)
        if candidate is None:
            return None, False
        item = remove_local_candidate_fields(candidate)
        items = load_jsonl(ITEMS)
        item_url = item.get("url")
        existing = next(
            (
                row
                for row in items
                if row.get("id") == item.get("id") or (item_url and row.get("url") == item_url)
            ),
            None,
        )
        if existing:
            existing_id = clean_text(existing.get("id"))
            if existing_id:
                remove_jsonl_ids(REJECTED_ITEMS, {existing_id})
                remove_jsonl_ids(DISMISSED, {existing_id})
            return existing, True
        append_jsonl(ITEMS, item)
        item_id = clean_text(item.get("id"))
        if item_id:
            remove_jsonl_ids(REJECTED_ITEMS, {item_id})
            remove_jsonl_ids(DISMISSED, {item_id})
        return item, False

    @with_db_write_lock
    def dismiss_candidate_record(self, candidate_id: str, reason: str = "") -> bool:
        candidate = self.pop_candidate(candidate_id)
        if candidate is None:
            return False
        decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        notes = "入庫建檔區按鈕標記不收。"
        if reason:
            notes = f"{notes}原因：{reason}"
        archived_candidate = rejected_archive_record(
            {
                **candidate,
                "review": append_review_note(candidate.get("review") or {}, f"{decided_at} {notes}"),
            },
            decided_at,
            reason,
            ".cache/rss-candidates.jsonl",
        )
        item_url = clean_text(candidate.get("url"))
        active_items = load_jsonl(ITEMS)
        kept_items = []
        archived_active_items = []
        for item in active_items:
            if item.get("id") == candidate.get("id") or (item_url and clean_text(item.get("url")) == item_url):
                archived_active_items.append(
                    rejected_archive_record(
                        {
                            **item,
                            "review": append_review_note(item.get("review") or {}, f"{decided_at} {notes}"),
                        },
                        decided_at,
                        reason,
                    )
                )
            else:
                kept_items.append(item)
        if archived_active_items:
            write_jsonl(ITEMS, kept_items)
            for archived_item in archived_active_items:
                upsert_jsonl(REJECTED_ITEMS, archived_item)
        else:
            upsert_jsonl(REJECTED_ITEMS, archived_candidate)
        dismissed = {
            "id": candidate.get("id"),
            "track": candidate.get("track"),
            "title": candidate.get("title"),
            "url": candidate.get("url"),
            "source_id": candidate.get("source_id"),
            "source_name": candidate.get("source_name"),
            "reference": candidate.get("reference", {}),
            "triage": candidate.get("triage", {}),
            "dismissed_at": decided_at,
            "notes": notes,
        }
        if reason:
            dismissed["reason"] = reason
        append_jsonl(DISMISSED, dismissed)
        return True

    @with_db_write_lock
    def update_pending_decisions(self, item_ids: list[str], action: str, reason: str = "") -> int:
        selected_ids = [item_id for item_id in item_ids if item_id]
        if not selected_ids:
            return 0

        candidate_ids = {row.get("id") for row in load_jsonl(CANDIDATES)}
        item_ids_to_update = []
        changed = 0
        for selected_id in selected_ids:
            if selected_id in candidate_ids:
                if action in {"accept", "accept_reading", "direct_pr"}:
                    item, _already_exists = self.import_candidate_item(selected_id)
                    if item and item.get("id"):
                        item_ids_to_update.append(str(item.get("id")))
                elif action == "reject" and self.dismiss_candidate_record(selected_id, reason):
                    changed += 1
                continue
            item_ids_to_update.append(selected_id)

        if item_ids_to_update:
            changed += self.update_item_decisions(item_ids_to_update, action, reason)
        return changed

    @with_db_write_lock
    def update_item_decisions(self, item_ids: list[str], action: str, reason: str = "") -> int:
        selected_ids = {item_id for item_id in item_ids if item_id}
        if not selected_ids:
            return 0

        items = load_jsonl(ITEMS)
        updated_items = []
        decided_at = now_iso()
        events = []
        active_ids = set()
        changed = 0
        for item in items:
            if item.get("id") not in selected_ids:
                updated_items.append(item)
                continue
            updated_item = dict(item)
            if action in {"accept", "accept_reading"}:
                if action == "accept_reading":
                    note = "本機確認收下並標記為閱讀中 / 超想看；下一步優先進編輯台做摘要、切角與 article 草稿，整理好後再送 PR。"
                    event_status = "accepted-current-reading"
                    decision_reason = "人工確認值得收，且標記近期正在閱讀 / 超想看。"
                    updated_item["reader_flags"] = current_reading_flags(updated_item, decided_at)
                else:
                    note = "本機確認收下；下一步進編輯台做摘要、切角與 article 草稿，整理好後再送 PR。"
                    event_status = "accepted-for-editing"
                    decision_reason = "人工確認值得收，準備進入 skill 編修。"
                updated_item["status"] = "triaged"
                updated_item["local_decision"] = {
                    "action": "accepted-for-editing",
                    "decided_at": decided_at,
                    "reason": decision_reason,
                    "source": "local_web",
                    "next_step": "run-writing-skill-before-pr",
                }
            elif action == "direct_pr":
                note = "本機標記直接送 PR（小消息）；純事實項目，不進編輯台撰稿。"
                event_status = "direct-pr-small-news"
                updated_item["status"] = "ready"
                updated_item["local_decision"] = {
                    "action": "direct-pr-small-news",
                    "decided_at": decided_at,
                    "reason": "純事實小消息，直接送 PR。",
                    "source": "local_web",
                    "next_step": "direct-pr",
                }
            elif action == "reject":
                note = f"本機標記不收。原因：{reason}"
                event_status = "rejected"
                updated_item["status"] = "archived"
                updated_item["priority"] = "low"
                updated_item["local_decision"] = {
                    "action": "rejected",
                    "decided_at": decided_at,
                    "reason": reason,
                    "source": "local_web",
                }
            else:
                updated_items.append(item)
                continue
            updated_item["review"] = append_review_note(updated_item.get("review") or {}, f"{decided_at} {note}")
            if action == "reject":
                upsert_jsonl(REJECTED_ITEMS, rejected_archive_record(updated_item, decided_at, reason))
            else:
                updated_items.append(updated_item)
                active_ids.add(str(updated_item.get("id")))
            events.append(review_event(updated_item, event_status, note))
            detect_and_log_divergence(updated_item)
            changed += 1

        if changed:
            write_jsonl(ITEMS, updated_items)
            remove_jsonl_ids(REJECTED_ITEMS, active_ids)
            remove_jsonl_ids(DISMISSED, active_ids)
            for event in events:
                append_jsonl(REVIEW_EVENTS, event)
        return changed

    def accept_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        action = "accept_reading" if form_value(data, "mark_reading") == "1" else "accept"
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "")
        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到入庫建檔項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], action)
        if self.is_async_request():
            self.send_no_content()
            return
        saved = "accepted_reading" if action == "accept_reading" else "accepted"
        if redirect_to:
            self.redirect(redirect_to)
            return
        self.redirect(f"/items?saved={saved}&count={count}")

    def direct_pr_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "")
        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到入庫建檔項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "direct_pr")
        if self.is_async_request():
            self.send_no_content()
            return
        if redirect_to:
            self.redirect(redirect_to)
            return
        self.redirect(f"/items?saved=direct_pr&count={count}")

    def reject_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        reason = form_value(data, "reason")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "")
        if not reason:
            if self.is_async_request():
                self.send_no_content(HTTPStatus.BAD_REQUEST)
                return
            self.redirect("/items?error=reason")
            return

        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到入庫建檔項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "reject", reason)
        if self.is_async_request():
            self.send_no_content()
            return
        if redirect_to:
            self.redirect(redirect_to)
            return
        self.redirect(f"/items?saved=rejected&count={count}")

    def batch_items(self, data: dict[str, list[str]]) -> None:
        action = form_value(data, "action")
        raw_ids = ",".join(data.get("ids") or [])
        item_ids = [item_id.strip() for item_id in raw_ids.split(",") if item_id.strip()]
        if not item_ids:
            if self.is_async_request():
                self.send_no_content(HTTPStatus.BAD_REQUEST)
                return
            self.redirect("/items?error=empty-selection")
            return
        if action in {"accept", "accept_reading"}:
            count = self.update_pending_decisions(item_ids, action)
            if self.is_async_request():
                self.send_no_content()
                return
            saved = "accepted_reading" if action == "accept_reading" else "accepted"
            self.redirect(f"/items?saved={saved}&count={count}")
            return
        if action == "direct_pr":
            count = self.update_pending_decisions(item_ids, "direct_pr")
            if self.is_async_request():
                self.send_no_content()
                return
            self.redirect(f"/items?saved=direct_pr&count={count}")
            return
        if action == "reject":
            reason = form_value(data, "reason") or form_value(data, "custom_reason")
            if not reason:
                if self.is_async_request():
                    self.send_no_content(HTTPStatus.BAD_REQUEST)
                    return
                self.redirect("/items?error=reason")
                return
            count = self.update_pending_decisions(item_ids, "reject", reason)
            if self.is_async_request():
                self.send_no_content()
                return
            self.redirect(f"/items?saved=rejected&count={count}")
            return
        self.redirect("/items")

    def auto_batch_skip_items(self, data: dict[str, list[str]]) -> None:
        track_filter = form_value(data, "track", "all")
        license_filter = form_value(data, "license", "all")
        text_filter = clean_text(form_value(data, "q"), 180)
        selected_keywords = {keyword for keyword in (data.get("keyword") or []) if keyword}
        show_all = form_value(data, "show") == "all"
        candidates = load_jsonl(CANDIDATES)
        items = load_jsonl(ITEMS)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        pending_entries = [("rss", candidate) for candidate in candidates] + [("item", item) for item in inbox_items]

        def matches_auto_batch(record: dict) -> bool:
            if track_filter != "all" and record.get("track") != track_filter:
                return False
            if candidate_recommendation(record) != "suggest-skip":
                return False
            if license_filter != "all" and item_license_name(record) != license_filter:
                return False
            if text_filter and not item_matches_text_filter(record, text_filter):
                return False
            if selected_keywords and not (item_triage_keywords(record) & selected_keywords):
                return False
            return True

        targets = [record for _, record in pending_entries if matches_auto_batch(record)]
        count = 0
        for item in targets:
            item_id = clean_text(item.get("id"))
            if not item_id:
                continue
            reason = automatic_batch_rejection_reason(item)
            count += self.update_pending_decisions([item_id], "reject", reason)

        params = []
        if track_filter != "all":
            params.append(("track", track_filter))
        params.append(("recommendation", "suggest-skip"))
        if license_filter != "all":
            params.append(("license", license_filter))
        if text_filter:
            params.append(("q", text_filter))
        for keyword in sorted(selected_keywords):
            params.append(("keyword", keyword))
        if show_all:
            params.append(("show", "all"))
        params.extend([("saved", "auto_rejected"), ("count", str(count))])
        self.redirect(href_with_query("/items", params))

    def auto_batch_keep_items(self, data: dict[str, list[str]]) -> None:
        track_filter = form_value(data, "track", "all")
        license_filter = form_value(data, "license", "all")
        text_filter = clean_text(form_value(data, "q"), 180)
        selected_keywords = {keyword for keyword in (data.get("keyword") or []) if keyword}
        show_all = form_value(data, "show") == "all"
        mode = form_value(data, "mode", "accept_all")
        try:
            threshold = float(form_value(data, "threshold", "65") or 65)
        except ValueError:
            threshold = 65.0
        candidates = load_jsonl(CANDIDATES)
        items = load_jsonl(ITEMS)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        pending_entries = [("rss", candidate) for candidate in candidates] + [("item", item) for item in inbox_items]

        def matches_auto_batch(record: dict) -> bool:
            if track_filter != "all" and record.get("track") != track_filter:
                return False
            if candidate_recommendation(record) != "suggest-keep":
                return False
            if license_filter != "all" and item_license_name(record) != license_filter:
                return False
            if text_filter and not item_matches_text_filter(record, text_filter):
                return False
            if selected_keywords and not (item_triage_keywords(record) & selected_keywords):
                return False
            return True

        targets = [record for _, record in pending_entries if matches_auto_batch(record)]
        count = 0
        if mode == "prune_low_pr":
            for item in targets:
                item_id = clean_text(item.get("id"))
                if not item_id:
                    continue
                score = candidate_priority_scores(item)["overall"] * 10
                if score <= threshold:
                    count += self.update_pending_decisions([item_id], "reject", automatic_low_pr_rejection_reason(item, threshold))
            saved = "auto_pruned"
        else:
            for item in targets:
                item_id = clean_text(item.get("id"))
                if item_id:
                    count += self.update_pending_decisions([item_id], "accept")
            saved = "accepted"

        params = []
        if track_filter != "all":
            params.append(("track", track_filter))
        params.append(("recommendation", "suggest-keep"))
        if license_filter != "all":
            params.append(("license", license_filter))
        if text_filter:
            params.append(("q", text_filter))
        for keyword in sorted(selected_keywords):
            params.append(("keyword", keyword))
        if show_all:
            params.append(("show", "all"))
        params.extend([("saved", saved), ("count", str(count))])
        if mode == "prune_low_pr":
            params.append(("threshold", score_label(threshold)))
        self.redirect(href_with_query("/items", params))

    def save_personal_note(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        note = form_value(data, "note")
        items = load_jsonl(ITEMS)
        changed = False
        updated_items = []
        updated_at = now_iso()
        for item in items:
            if item.get("id") != item_id:
                updated_items.append(item)
                continue
            updated = dict(item)
            updated["personal_notes"] = {
                "body": note,
                "updated_at": updated_at,
                "source": "local_web",
            }
            updated_items.append(updated)
            changed = True
        if not changed:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(ITEMS, updated_items)
        self.redirect(f"/items/view?id={quote(item_id)}&saved=note")

    def selected_tag_values(self, data: dict[str, list[str]]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for raw in data.get("tags") or []:
            for tag in form_lines(raw):
                append_unique_tag(output, seen, tag)
        for tag in form_lines(form_value(data, "new_tags")):
            append_unique_tag(output, seen, tag)
        return output

    def update_tags_record(self, path: Path, item_id: str, tags: list[str]) -> bool:
        records = load_jsonl(path)
        updated_records = []
        found = False
        updated_at = now_iso()
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated = dict(item)
            previous_tags = item_tags(updated)
            updated["tags"] = tags
            tag_metadata = updated.get("tag_metadata") if isinstance(updated.get("tag_metadata"), dict) else {}
            updated["tag_metadata"] = {
                **tag_metadata,
                "updated_at": updated_at,
                "source": "local_web",
                "previous_tags": previous_tags,
            }
            updated_records.append(updated)
        if found:
            write_jsonl(path, updated_records)
        return found

    def update_item_tags(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        tags = self.selected_tag_values(data)
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        found = self.update_tags_record(ITEMS, item_id, tags)
        if not found:
            found = self.update_tags_record(CANDIDATES, item_id, tags)
        if not found:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到可更新 tag 的項目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到項目", "<h1>找不到可更新 tag 的項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        if wants_json:
            self.send_json({"ok": True, "id": item_id, "tags": tags})
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=tags")

    def toggle_reading_priority(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        action = form_value(data, "action", "mark")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        items = load_jsonl(ITEMS)
        updated_items = []
        changed = False
        now = now_iso()
        event_item = None
        event_status = ""
        event_note = ""
        for item in items:
            if item.get("id") != item_id:
                updated_items.append(item)
                continue
            updated = dict(item)
            flags = dict(item_reader_flags(updated))
            if action == "clear":
                flags.update(
                    {
                        "current_reading": False,
                        "share_intent": False,
                        "cleared_at": now,
                        "updated_at": now,
                        "source": "local_web",
                    }
                )
                note = "取消近期正在閱讀 / 想分享標記。"
                event_status = "cleared-current-reading"
            else:
                flags = current_reading_flags(updated, now)
                note = f"標記為近期正在閱讀 / 想分享；後續未指定材料時優先進編輯台參考。"
                event_status = "marked-current-reading"
            updated["reader_flags"] = flags
            updated["review"] = append_review_note(updated.get("review") or {}, f"{now} {note}")
            updated_items.append(updated)
            event_item = updated
            event_note = note
            changed = True
        if not changed or event_item is None:
            self.send_html("找不到項目", "<h1>找不到可標記閱讀狀態的項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(ITEMS, updated_items)
        append_jsonl(REVIEW_EVENTS, review_event(event_item, event_status, event_note))
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=reading_priority")

    def toggle_page_publish(self, data: dict[str, list[str]]) -> None:
        page_type = form_value(data, "type")
        if page_type not in {"tag", "source"}:
            self.send_json({"ok": False, "error": "未知的公開頁類型"}, HTTPStatus.BAD_REQUEST)
            return
        key = canonical_tag_label(form_value(data, "key")) if page_type == "tag" else form_value(data, "key")
        if not key:
            self.send_json({"ok": False, "error": "缺少公開頁 key"}, HTTPStatus.BAD_REQUEST)
            return
        title = canonical_tag_label(form_value(data, "title") or key) if page_type == "tag" else form_value(data, "title", key)
        blurb = clean_text((data.get("blurb") or [""])[0], 1000)
        action = form_value(data, "action", "publish")
        existing = published_page_for(page_type, key)
        published = action != "unpublish"
        now = now_iso()
        slug = clean_text(existing.get("slug")) or published_page_slug(page_type, key, title)
        record = {
            **existing,
            "id": clean_text(existing.get("id")) or published_page_id(page_type, key),
            "type": page_type,
            "key": key,
            "slug": slug,
            "title": title,
            "blurb": blurb or clean_text(existing.get("blurb"), 1000),
            "published": published,
            "updated_at": now,
            "source": "local_web",
        }
        if published and not clean_text(existing.get("published_at")):
            record["published_at"] = now
        elif clean_text(existing.get("published_at")):
            record["published_at"] = clean_text(existing.get("published_at"))
        upsert_jsonl(PUBLISHED_PAGES, record)
        public_url = page_public_url(page_type, slug)
        if self.is_async_request() or form_value(data, "format") == "json":
            self.send_json(
                {
                    "ok": True,
                    "published": published,
                    "public_url": public_url,
                    "blurb": record.get("blurb", ""),
                    "message": "下次更新線上閱讀版後生效。",
                }
            )
            return
        redirect_to = safe_redirect_path(
            form_value(data, "redirect"),
            f"/tags?tag={quote(key)}" if page_type == "tag" else f"/sources/view?id={quote(key)}",
        )
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=publish_page")

    def requeue_skill_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        items = load_jsonl(ITEMS)
        changed = False
        updated_items = []
        requested_at = now_iso()
        event_item = None
        for item in items:
            if item.get("id") != item_id:
                updated_items.append(item)
                continue
            updated = dict(item)
            note = personal_note_text(updated)
            request = {
                "id": stable_id("skill-request", item_id, requested_at),
                "requested_at": requested_at,
                "source": "local_web",
                "personal_notes": note,
                "instruction": "重新用 personal_notes 檢視材料，補切角、摘要、查核重點與可採用觀點。",
            }
            skill_requests = updated.get("skill_requests") if isinstance(updated.get("skill_requests"), list) else []
            updated["skill_requests"] = [*skill_requests, request]
            updated["status"] = "triaged"
            updated["local_decision"] = {
                "action": "revisit-with-personal-notes",
                "decided_at": requested_at,
                "reason": "閱讀後人工要求用個人觀點重新送回編輯台。",
                "source": "local_web",
                "next_step": "run-writing-skill-with-personal-notes",
            }
            updated["review"] = append_review_note(
                updated.get("review") or {},
                f"{requested_at} 閱讀後送回編輯台；個人觀點：{note or '未填'}",
            )
            updated_items.append(updated)
            event_item = updated
            changed = True
        if not changed or event_item is None:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(ITEMS, updated_items)
        append_jsonl(
            REVIEW_EVENTS,
            review_event(event_item, "revisit-with-personal-notes", "閱讀後送回編輯台，後續需納入 personal_notes。"),
        )
        self.redirect(f"/items/view?id={quote(item_id)}&saved=requeue")

    def update_read_more_record(self, path: Path, item_id: str) -> tuple[bool, bool, dict | None, str]:
        records = load_jsonl(path)
        changed = False
        found = False
        response_item: dict | None = None
        updated_records = []
        error = ""
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated, did_change, error = enrich_item_metadata(item)
            updated, markdown_changed = ensure_article_markdown(updated)
            updated_records.append(updated)
            changed = did_change or markdown_changed
            response_item = updated
        if found and changed:
            write_jsonl(path, updated_records)
        return found, changed, response_item, error

    def extract_newsletter_links_record(self, path: Path, item_id: str, selected_urls: list[str] | None = None) -> tuple[bool, dict]:
        target_records = load_jsonl(path)
        parent = next((item for item in target_records if clean_text(item.get("id")) == item_id), None)
        if not parent:
            return False, {}

        candidates, skipped = newsletter_link_candidates(parent)
        # 勾選視窗：selected_urls 不為 None 時只匯入被勾選的連結（空清單＝一筆都不收）；
        # None 代表沒帶選擇（舊行為），維持全部匯入。
        selected_set = None
        if selected_urls is not None:
            selected_set = {canonical_item_url(u) for u in selected_urls if clean_text(u)}
        deselected_count = 0
        existing_items = load_jsonl(ITEMS)
        existing_candidates = load_jsonl(CANDIDATES)
        existing_keys = {key for record in [*existing_items, *existing_candidates] for key in item_url_keys(record)}
        keyword_config = load_json(TRIAGE_KEYWORDS)
        editorial_context = build_editorial_context([*existing_items, *load_jsonl(REJECTED_ITEMS)], keyword_config)
        imported: list[dict] = []
        imported_ids: list[str] = []
        duplicate_links: list[dict] = []
        source_records = load_jsonl(SOURCES)
        sources_changed = False
        extracted_at = now_iso()

        for link in candidates:
            url = canonical_item_url(link.get("url"))
            if not url or url in existing_keys:
                duplicate_links.append(link)
                continue
            if selected_set is not None and url not in selected_set:
                deselected_count += 1
                continue
            child, source_info = build_newsletter_child_item(parent, link, extracted_at, keyword_config, editorial_context)
            source_id, did_source_change = ensure_derived_source(
                source_records,
                clean_text(child.get("track")) or "unclassified",
                clean_text(source_info.get("source_name")) or clean_text(child.get("source_name")) or host_label(url),
                clean_text(source_info.get("site_url")),
            )
            sources_changed = sources_changed or did_source_change
            child["source_id"] = source_id
            imported.append(child)
            imported_ids.append(clean_text(child.get("id")))
            existing_keys.update(item_url_keys(child))

        if sources_changed:
            write_jsonl(SOURCES, source_records)

        stats = {
            "extracted_at": extracted_at,
            "source": "local_web",
            "total_links": len(candidates) + len(skipped),
            "article_candidate_count": len(candidates),
            "imported_count": len(imported),
            "duplicate_count": len(duplicate_links),
            "skipped_count": len(skipped),
            "deselected_count": deselected_count,
            "imported_item_ids": imported_ids,
            "duplicate_urls": [clean_text(link.get("url")) for link in duplicate_links[:12]],
            "skipped_samples": [
                {
                    "title": clean_text(link.get("title"), 180),
                    "url": clean_text(link.get("url"), 500),
                    "reason": clean_text(link.get("reason"), 120),
                }
                for link in skipped[:16]
            ],
        }
        updated_parent = update_newsletter_extraction_metadata(parent, stats)
        updated_target_records = [
            updated_parent if clean_text(item.get("id")) == item_id else item
            for item in target_records
        ]
        if path == ITEMS:
            write_jsonl(ITEMS, [*updated_target_records, *imported])
        else:
            write_jsonl(path, updated_target_records)
            if imported:
                write_jsonl(ITEMS, [*existing_items, *imported])

        append_jsonl(
            REVIEW_EVENTS,
            review_event(
                updated_parent,
                "newsletter-links-extracted",
                f"彙整式電子報拆出 {len(imported)} 筆子文章，重複 {len(duplicate_links)} 筆，略過 {len(skipped)} 筆功能性或非文章連結。",
            ),
        )
        return True, stats

    def extract_newsletter_links_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        # 浮動勾選視窗會帶 selected=1 + 多個 url；沒帶 selected 就維持舊的全部匯入
        selected_urls = data.get("url") or [] if form_value(data, "selected") == "1" else None
        found, stats = self.extract_newsletter_links_record(ITEMS, item_id, selected_urls)
        if not found:
            found, stats = self.extract_newsletter_links_record(CANDIDATES, item_id, selected_urls)
        if not found:
            self.send_html("找不到項目", "<h1>找不到可拆 link 的項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(
            f"{redirect_to}{separator}saved=newsletter_links"
            f"&created={stats.get('imported_count', 0)}"
            f"&duplicates={stats.get('duplicate_count', 0)}"
            f"&skipped={stats.get('skipped_count', 0)}"
        )

    def fetch_remote_pdf_markdown(self, item: dict) -> tuple[dict, bool, str]:
        """遠端 PDF 網址：下載原檔並用 markitdown 抽全文，取代零碎的預抓文字。"""
        url = fetchable_http_url(item.get("url"))
        if not url or not item_is_pdf_like(item):
            return item, False, ""
        metadata = item_reading_metadata(item)
        current = clean_text(metadata.get("article_markdown"))
        method = clean_text(metadata.get("article_markdown_method"))
        # 已經有真正的 markitdown 全文就不重抓。
        if len(current) >= 1200 and method.startswith("markitdown-cli"):
            return item, False, ""
        try:
            pdf_path = download_remote_pdf(url, PDF_UPLOADS)
            markdown, pdf_meta = extract_pdf_markdown(pdf_path, host_label(url))
        except Exception as exc:  # noqa: BLE001 - 下載/抽取失敗要回報給使用者
            return item, False, clean_text(exc, 400)
        if len(markdown) <= len(current):
            return item, False, ""
        updated = dict(item)
        merged = dict(item_reading_metadata(updated))
        merged.update(
            {
                "content_type": "application/pdf",
                "article_markdown": markdown,
                "article_markdown_method": "markitdown-cli-remote",
                "article_markdown_label": "遠端 PDF 全文（markitdown）",
                "article_text_method": "markitdown-cli-remote",
                "fulltext_source": "remote-pdf",
                "fulltext_source_url": url,
            }
        )
        updated["reading_metadata"] = merged
        reference = dict(updated.get("reference") or {})
        reference["pdf_remote_file"] = str(pdf_path.relative_to(ROOT))
        reference["pdf_meta"] = {**(reference.get("pdf_meta") or {}), **pdf_meta}
        updated["reference"] = reference
        return updated, True, ""

    def normalize_pdf_markdown_record(self, path: Path, item_id: str) -> tuple[bool, bool, str]:
        records = load_jsonl(path)
        updated_records = []
        found = False
        changed = False
        error = ""
        event_item = None
        for item in records:
            if clean_text(item.get("id")) != item_id:
                updated_records.append(item)
                continue
            found = True
            item, remote_changed, remote_error = self.fetch_remote_pdf_markdown(item)
            updated, changed, error = normalize_pdf_markdown_item(item)
            changed = changed or remote_changed
            if remote_error and not changed:
                error = remote_error
            updated_records.append(updated)
            event_item = updated
        if found and changed:
            write_jsonl(path, updated_records)
            if event_item:
                append_jsonl(REVIEW_EVENTS, review_event(event_item, "pdf-markdown-normalized", "已將 PDF / MarkItDown 文字補入全文欄位。"))
        return found, changed, error

    def normalize_pdf_markdown(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        found, changed, error = self.normalize_pdf_markdown_record(ITEMS, item_id)
        if not found:
            found, changed, error = self.normalize_pdf_markdown_record(CANDIDATES, item_id)
        if not found:
            self.send_html("找不到項目", "<h1>找不到可轉全文的項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        if error and not changed:
            self.redirect(f"{redirect_to}{separator}error=pdf_markdown")
            return
        self.redirect(f"{redirect_to}{separator}saved=pdf_markdown")

    def save_fulltext_link(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        url = fetchable_http_url(form_value(data, "url"))
        if not url:
            self.redirect(f"/items/view?id={quote(item_id)}&error=read_more")
            return
        records = load_jsonl(ITEMS)
        updated_records = []
        found = False
        changed = False
        error = ""
        for item in records:
            if clean_text(item.get("id")) != item_id:
                updated_records.append(item)
                continue
            found = True
            probe = {**item, "url": url, "reading_metadata": {}}
            enriched, did_change, error = enrich_item_metadata(probe)
            metadata = dict(item_reading_metadata(item))
            fetched = item_reading_metadata(enriched)
            for key, value in fetched.items():
                if value not in (None, "", [], {}):
                    metadata[key] = value
            metadata.update(
                {
                    "fulltext_source": "pasted-link",
                    "fulltext_source_url": url,
                    "fulltext_source_updated_at": now_iso(),
                }
            )
            updated = {**item, "reading_metadata": metadata}
            updated, markdown_changed = ensure_article_markdown(updated)
            updated_records.append(updated)
            changed = did_change or markdown_changed or updated != item
        if not found:
            self.send_html("找不到項目", "<h1>找不到可補全文的項目</h1>", HTTPStatus.NOT_FOUND)
            return
        if changed:
            write_jsonl(ITEMS, updated_records)
        if error and not changed:
            self.redirect(f"/items/view?id={quote(item_id)}&error=read_more")
            return
        self.redirect(f"/items/view?id={quote(item_id)}&saved=fulltext")

    def save_fulltext_text(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        fulltext = str((data.get("fulltext") or [""])[0]).replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(fulltext) < 240:
            self.redirect(f"/items/view?id={quote(item_id)}&error=pdf_markdown")
            return
        records = load_jsonl(ITEMS)
        updated_records = []
        found = False
        for item in records:
            if clean_text(item.get("id")) != item_id:
                updated_records.append(item)
                continue
            found = True
            metadata = dict(item_reading_metadata(item))
            metadata.update(
                {
                    "article_text": fulltext,
                    "article_text_method": "manual-paste",
                    "article_text_label": "手動貼上的全文",
                    "fulltext_source": "manual-paste",
                    "fulltext_source_updated_at": now_iso(),
                }
            )
            updated, _changed, _error = normalize_pdf_markdown_item({**item, "reading_metadata": metadata})
            updated_metadata = dict(item_reading_metadata(updated))
            updated_metadata.update(
                {
                    "article_text_method": "manual-paste",
                    "article_text_label": "手動貼上的全文",
                    "article_markdown_method": "manual-paste-normalized",
                    "article_markdown_label": "手動貼文 Markdown 全文",
                    "fulltext_source": "manual-paste",
                }
            )
            updated["reading_metadata"] = updated_metadata
            updated_records.append(updated)
        if not found:
            self.send_html("找不到項目", "<h1>找不到可補全文的項目</h1>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(ITEMS, updated_records)
        self.redirect(f"/items/view?id={quote(item_id)}&saved=fulltext")

    def pdf_relation_action(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        candidate_id = form_value(data, "candidate_id")
        action = form_value(data, "action")
        relation = form_value(data, "relation", "related")
        records = load_jsonl(ITEMS)
        pdf_item = next((item for item in records if clean_text(item.get("id")) == item_id), None)
        candidate = next((item for item in records if clean_text(item.get("id")) == candidate_id), None)
        if not pdf_item:
            self.send_html("找不到項目", "<h1>找不到 PDF 材料</h1>", HTTPStatus.NOT_FOUND)
            return
        reference = dict(pdf_item.get("reference") or {})
        ignored = set(reference.get("pdf_relation_ignored_ids") or [])
        resolved = set(reference.get("pdf_relation_resolved_ids") or [])
        updated_pdf = dict(pdf_item)

        if action == "new-source":
            ignored.update(clean_text(row.get("item_id")) for row in pdf_relation_candidates(pdf_item))
            reference["source_status"] = "需要出處"
        elif not candidate:
            self.send_html("找不到候選", "<h1>找不到關係候選材料</h1>", HTTPStatus.NOT_FOUND)
            return
        elif action == "source-match":
            candidate_url = clean_text(candidate.get("url"))
            if candidate_url:
                updated_pdf["url"] = candidate_url
                updated_pdf["source_name"] = clean_text(candidate.get("source_name")) or updated_pdf.get("source_name")
                updated_pdf["author"] = clean_text(candidate.get("author")) or updated_pdf.get("author")
                reference["source_status"] = "人工確認既有來源"
                reference["source_item_id"] = candidate_id
                reference["source_url"] = candidate_url
            link_materials(updated_pdf, candidate, "same-source")
            resolved.add(candidate_id)
        elif action == "related":
            link_materials(updated_pdf, candidate, "related")
            resolved.add(candidate_id)
        elif action == "establish":
            link_materials(updated_pdf, candidate, relation)
            resolved.add(candidate_id)
        elif action == "fulltext":
            link_materials(candidate, updated_pdf, "full-source")
            candidate_metadata = dict(item_reading_metadata(candidate))
            candidate_metadata.update(
                {
                    "fulltext_pdf_item_id": item_id,
                    "fulltext_source": "uploaded-pdf",
                    "fulltext_source_updated_at": now_iso(),
                }
            )
            records = [
                {**record, "reading_metadata": candidate_metadata}
                if clean_text(record.get("id")) == candidate_id
                else record
                for record in records
            ]
            resolved.add(candidate_id)
        elif action == "ignore":
            ignored.add(candidate_id)
        else:
            self.send_html("無效動作", "<h1>不支援的 PDF 關係動作</h1>", HTTPStatus.BAD_REQUEST)
            return

        reference["pdf_relation_ignored_ids"] = sorted(item for item in ignored if item)
        reference["pdf_relation_resolved_ids"] = sorted(item for item in resolved if item)
        reference["pdf_relation_reviewed_at"] = now_iso()
        updated_pdf["reference"] = reference
        records = [updated_pdf if clean_text(record.get("id")) == item_id else record for record in records]
        write_jsonl(ITEMS, records)
        remaining = pdf_relation_candidates(updated_pdf)
        suffix = "&pdf_relations=1" if remaining else ""
        self.redirect(f"/items/view?id={quote(item_id)}&saved=pdf_relation{suffix}")

    def pdf_relation_confirm(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        candidate_id = form_value(data, "candidate_id")
        provider = normalize_ai_provider(form_value(data, "provider", "codex"))
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "pdf_relation_confirm.py"),
            "--item-id",
            item_id,
            "--candidate-id",
            candidate_id,
            "--provider",
            provider,
        ]
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=1260)
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(command, 124, stdout=clean_text(exc.stdout or ""), stderr=clean_text(exc.stderr or "CLI 確認逾時。"))
            output = result.stdout + "\nSTDERR:\n" + result.stderr
        ok = result.returncode == 0
        payload = {"ok": ok, "returncode": result.returncode, "output": output, "error": "" if ok else clean_text(output, 1200)}
        if wants_json:
            self.send_json(payload, HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            return
        self.redirect(f"/items/view?id={quote(item_id)}&pdf_relations=1")

    def pdf_split_suggest(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        provider = normalize_ai_provider(form_value(data, "provider", "codex"))
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "pdf_split_suggest.py"),
            "--item-id",
            item_id,
            "--provider",
            provider,
            "--status-file",
            str(PDF_SPLIT_STATUS),
        ]
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=1860)
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(command, 124, stdout=clean_text(exc.stdout or ""), stderr=clean_text(exc.stderr or "PDF 拆分建議逾時。"))
            output = result.stdout + "\nSTDERR:\n" + result.stderr
        ok = result.returncode == 0
        payload = {"ok": ok, "returncode": result.returncode, "provider": provider, "output": output, "error": "" if ok else clean_text(output, 1400)}
        if wants_json:
            self.send_json(payload, HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY)
            return
        self.redirect(f"/items/view?id={quote(item_id)}")

    def pdf_split_apply(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        provider = normalize_ai_provider(form_value(data, "provider", "codex"))
        titles = [clean_text(value, 320) for value in data.get("section_title") or []]
        start_markers = [str(value).strip() for value in data.get("start_marker") or []]
        end_markers = [str(value).strip() for value in data.get("end_marker") or []]
        notes = [clean_text(value, 800) for value in data.get("section_notes") or []]
        if not titles or len(titles) != len(start_markers) or len(titles) != len(end_markers):
            self.send_html("拆分失敗", "<h1>拆分欄位不完整</h1>", HTTPStatus.BAD_REQUEST)
            return
        records = load_jsonl(ITEMS)
        parent = next((item for item in records if clean_text(item.get("id")) == item_id), None)
        if not parent:
            self.send_html("找不到項目", "<h1>找不到 PDF 材料</h1>", HTTPStatus.NOT_FOUND)
            return
        markdown = pdf_split_source_markdown(parent)

        keyword_config = load_json(TRIAGE_KEYWORDS)
        editorial_context = build_editorial_context([*records, *load_jsonl(REJECTED_ITEMS)], keyword_config)
        existing_ids = {clean_text(item.get("id")) for item in records}
        created: list[dict] = []
        failed_sections: list[dict] = []
        captured_at = now_iso()
        for index, title in enumerate(titles):
            start_marker = start_markers[index]
            end_marker = end_markers[index]
            note = notes[index] if index < len(notes) else ""
            display_title = title or f"{item_display_title(parent)}（{index + 1}）"
            body, start_found, end_found, error = slice_markdown_loose(markdown, start_marker, end_marker)
            if error or not body:
                failed_sections.append(
                    {
                        "title": display_title,
                        "start_marker": start_marker,
                        "end_marker": end_marker,
                        "notes": note,
                        "start_found": start_found,
                        "end_found": end_found,
                        "error": error,
                    }
                )
                continue
            child_id = stable_id("item", "pdf-split", item_id, display_title, start_marker, end_marker)
            if child_id in existing_ids:
                continue
            child = {
                "id": child_id,
                "track": clean_text(parent.get("track")) or "unclassified",
                "status": "inbox",
                "priority": "normal",
                "title": display_title,
                "url": clean_text(parent.get("url")),
                "source_id": clean_text(parent.get("source_id")),
                "source_name": clean_text(parent.get("source_name")) or "本機 PDF",
                "author": clean_text(parent.get("author")),
                "published_at": clean_text(parent.get("published_at")),
                "captured_at": captured_at,
                "summary": clean_text(body, 1200),
                "tags": item_visible_tags(parent, 12),
                "origin": "pdf-split",
                "source_type": "pdf-split",
                "reference": {
                    "created_by": "local_web",
                    "created_from": "pdf-split-proposal",
                    "parent_item_id": item_id,
                    "parent_title": item_display_title(parent),
                    "proposal_provider": provider,
                    "start_marker": start_marker,
                    "end_marker": end_marker,
                    "proposal_note": note,
                },
                "reading_metadata": {
                    "article_markdown": body,
                    "article_markdown_method": "pdf-split-markers",
                    "article_markdown_label": "由 PDF 起訖標記拆出的全文",
                    "article_text": body,
                    "article_text_method": "pdf-split-markers",
                    "fulltext_source": "split-from-pdf",
                    "parent_pdf_item_id": item_id,
                },
                "review": default_review("由 PDF 拆分草案人工確認後建立；仍需在入庫建檔區逐篇分流。"),
            }
            child, _changed, _error = normalize_pdf_markdown_item(child)
            child_metadata = dict(item_reading_metadata(child))
            child_metadata.update(
                {
                    "article_markdown_method": "pdf-split-markers",
                    "article_markdown_label": "由 PDF 起訖標記拆出的全文",
                    "article_text_method": "pdf-split-markers",
                    "article_text_label": "由 PDF 起訖標記拆出的文字",
                }
            )
            child["reading_metadata"] = child_metadata
            child["triage"] = evaluate_triage(child, keyword_config)
            child["editorial_triage"] = evaluate_editorial_triage(child, keyword_config, editorial_context)
            created.append(child)
            existing_ids.add(child_id)

        # 把這次編輯後、尚未成功的篇回寫到提案：保留使用者改過的標題與起訖標記，
        # 成功的篇從提案移除，失敗的留著讓使用者續修，避免一來一回就全部不見。
        updated_parent = dict(parent)
        parent_metadata = dict(item_reading_metadata(updated_parent))
        proposals = dict(parent_metadata.get("pdf_split_proposals")) if isinstance(parent_metadata.get("pdf_split_proposals"), dict) else {}
        proposal = dict(proposals.get(provider)) if isinstance(proposals.get(provider), dict) else {}
        if failed_sections:
            proposal["sections"] = failed_sections
            proposal["updated_at"] = captured_at
            proposals[provider] = proposal
        else:
            proposals.pop(provider, None)
        parent_metadata["pdf_split_proposals"] = proposals
        updated_parent["reading_metadata"] = parent_metadata
        final_records = [updated_parent if clean_text(item.get("id")) == item_id else item for item in records]
        write_jsonl(ITEMS, [*final_records, *created])
        for child in created:
            link_materials(child, parent, "split-from")
            append_jsonl(REVIEW_EVENTS, review_event(child, "pdf-split-created", f"由 PDF {item_id} 的 {ai_provider_label(provider)} 拆分草案建立。"))
        self.redirect(f"/items/view?id={quote(item_id)}&saved=pdf_split&created={len(created)}&failed={len(failed_sections)}")

    def _find_item_any(self, item_id: str) -> tuple[dict | None, Path]:
        for it in load_jsonl(ITEMS):
            if clean_text(it.get("id")) == item_id:
                return it, ITEMS
        for it in load_jsonl(CANDIDATES):
            if clean_text(it.get("id")) == item_id:
                return it, CANDIDATES
        return None, ITEMS

    def _apply_fulltext_edit(self, item_id: str, markdown: str, new_title: str, method: str, label: str, note: str) -> bool:
        for path in (ITEMS, CANDIDATES):
            records = load_jsonl(path)
            changed = False
            out = []
            for it in records:
                if clean_text(it.get("id")) != item_id:
                    out.append(it)
                    continue
                updated = dict(it)
                md = dict(item_reading_metadata(updated))
                md["article_markdown"] = markdown
                md["article_markdown_chars"] = len(markdown)
                md["article_markdown_method"] = method
                md["article_markdown_label"] = label
                md["article_markdown_status"] = "ok" if len(markdown) >= 280 else "short"
                md["article_text"] = markdown
                md["article_text_chars"] = len(markdown)
                md["article_text_method"] = method
                md["fulltext_edited_at"] = now_iso()
                # 重新抽取／重新分段會重建原文，清掉舊的手動覆寫層，讓新版本顯示。
                md["edited_markdown"] = ""
                updated["reading_metadata"] = md
                if new_title:
                    updated["title"] = new_title
                updated["review"] = append_review_note(updated.get("review") or {}, note)
                out.append(updated)
                changed = True
            if changed:
                write_jsonl(path, out)
                return True
        return False

    def show_fulltext_editor(self, query: dict[str, list[str]]) -> None:
        item_id = form_value(query, "id")
        item, _path = self._find_item_any(item_id)
        if not item:
            self.send_html("找不到項目", "<h1>找不到可編輯的材料</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        has_translation = bool(item_translation_entries(item))
        is_edited = bool(item_edited_markdown(item))
        # 抓「目前的全文」：已編輯版 > 中文翻譯 > 原文。有中文就編中文、僅原文就編原文。
        markdown = item_edited_markdown(item) or item_translated_markdown(item) or item_article_markdown(item) or str(item.get("summary") or "")
        base_label = "中文全文" if has_translation else "原始全文"
        edited_hint = "（目前載入的是你先前編輯過的版本）" if is_edited else ""
        detail = item_detail_href(item)
        body = f"""
<h1>線上編輯全文</h1>
<p class="lede">修正排版、補上被截斷的內容，或順一下轉檔的小毛病（缺空格、跑版、亂碼、段落黏在一起）。
目前載入的是<strong>{h(base_label)}</strong>{h(edited_hint)}。存檔後單篇頁、線上與線下閱讀版都會以這份編輯後的全文為準；原始翻譯與原文仍會保留在下方可展開比對。</p>
<form method="post" action="/items/save-fulltext" class="easymde-host" id="fulltext-form">
  <input type="hidden" name="id" value="{h(item_id)}">
  <label>標題</label>
  <input name="title" value="{h(item_display_title(item))}">
  <label>全文（Markdown，可用空行分段、## 當小標）</label>
  <textarea name="markdown" id="fulltext-markdown">{h(markdown)}</textarea>
  <div class="button-row" style="margin-top:12px">
    <button type="submit">{button_content('儲存全文', 'accept')}</button>
    <a class="button secondary" href="{h(detail)}">取消</a>
  </div>
  <p class="help">儲存會標記為「線上編輯全文」。</p>
</form>
<link rel="stylesheet" href="/reader/assets/vendor/easymde.min.css">
<script src="/reader/assets/vendor/easymde.min.js"></script>
{EASYMDE_TOOLBAR_CSS}
{EASYMDE_TOOLBAR_ICON_JS}
<script>
(function() {{
  var area = document.getElementById("fulltext-markdown");
  if (!area || !window.EasyMDE) return;
  var editor = new EasyMDE({{
    element: area,
    autoDownloadFontAwesome: false,
    spellChecker: false,
    status: ["lines", "words"],
    minHeight: "60vh",
    toolbar: ["bold","italic","heading","|","quote","unordered-list","ordered-list","|","link","table","code","|","preview","side-by-side","fullscreen","|","guide"]
  }});
  var form = document.getElementById("fulltext-form");
  if (form) form.addEventListener("submit", function() {{ editor.codemirror.save(); }});
}})();
</script>
"""
        self.send_html("編輯全文", body)

    def save_fulltext_edit(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        markdown = (data.get("markdown") or [""])[0].replace("\r\n", "\n").replace("\r", "\n").strip()
        new_title = form_value(data, "title")
        redirect_to = f"/items/view?id={quote(item_id)}"
        if len(markdown) < 1:
            self.redirect(f"/items/edit-fulltext?id={quote(item_id)}")
            return
        item, _path = self._find_item_any(item_id)
        base = "zh" if (item and item_translation_entries(item)) else "original"
        ok = self._apply_edited_markdown(
            item_id, markdown, new_title, base,
            f"{now_iso()} 線上手動編輯全文（修正排版／補截斷，base={base}）。",
        )
        if not ok:
            self.send_html("找不到項目", "<h1>找不到可編輯的材料</h1>", HTTPStatus.NOT_FOUND)
            return
        self.redirect(f"{redirect_to}&saved=fulltext_edit")

    def _apply_edited_markdown(self, item_id: str, markdown: str, new_title: str, base: str, note: str) -> bool:
        """把使用者手動修正後的全文存成 edited_markdown 覆寫層，不動原文與自動翻譯。"""
        for path in (ITEMS, CANDIDATES):
            records = load_jsonl(path)
            changed = False
            out = []
            for it in records:
                if clean_text(it.get("id")) != item_id:
                    out.append(it)
                    continue
                updated = dict(it)
                md = dict(item_reading_metadata(updated))
                md["edited_markdown"] = markdown
                md["edited_markdown_chars"] = len(markdown)
                md["edited_markdown_base"] = base
                md["edited_markdown_at"] = now_iso()
                updated["reading_metadata"] = md
                if new_title:
                    updated["title"] = new_title
                updated["review"] = append_review_note(updated.get("review") or {}, note)
                out.append(updated)
                changed = True
            if changed:
                write_jsonl(path, out)
                return True
        return False

    def repaginate_fulltext(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        provider = clean_text(form_value(data, "provider", "claude")) or "claude"
        redirect_to = f"/items/view?id={quote(item_id)}"
        item, _path = self._find_item_any(item_id)
        if not item:
            self.send_html("找不到項目", "<h1>找不到材料</h1>", HTTPStatus.NOT_FOUND)
            return
        command = [
            sys.executable, str(ROOT / "scripts" / "pdf_paragraph_fix.py"),
            "--id", item_id, "--provider", provider,
        ]
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=600)
            payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError):
            payload = {"ok": False}
        markdown = str(payload.get("markdown") or "").replace("\r\n", "\n").replace("\r", "\n").strip() if payload.get("ok") else ""
        if not payload.get("ok") or len(markdown) < 200:
            self.redirect(f"{redirect_to}&error=repaginate")
            return
        self._apply_fulltext_edit(
            item_id, markdown, "", "ai-repaginate", f"AI 重新分段（{clean_text(payload.get('provider')) or provider}）",
            f"{now_iso()} 以 {clean_text(payload.get('provider')) or provider} 重新分段全文（只重排段落、不改字詞）。",
        )
        self.redirect(f"{redirect_to}&saved=repaginate")

    def read_more_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = form_value(data, "redirect", f"/items/view?id={quote(item_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = f"/items/view?id={quote(item_id)}"
        found, changed, response_item, error = self.update_read_more_record(ITEMS, item_id)
        found_in_items = found
        if not found:
            found, changed, response_item, error = self.update_read_more_record(CANDIDATES, item_id)
            found_in_items = False
        if not found:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到項目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        if wants_json:
            metadata = item_reading_metadata(response_item or {})
            article_text = clean_text(metadata.get("article_text"))
            article_markdown = clean_text(metadata.get("article_markdown")) or (
                text_to_markdown(article_text, title=metadata.get("title") or (response_item or {}).get("title") or "")
                if article_text
                else ""
            )
            article_html = markdown_to_html(article_markdown) if article_markdown else ""
            translation_actions_markup = translation_actions_html(response_item or {}, item_id, redirect_to)
            message = (
                f"Markdown 閱讀版，約 {metadata.get('article_markdown_chars', len(article_markdown)) or metadata.get('article_text_chars', len(article_text))} 字；"
                f"抽取方式：{metadata.get('article_markdown_method') or metadata.get('article_text_method', 'metadata')}。"
                if article_markdown or article_text
                else "已嘗試讀取原始網址，但這次沒有抓到可顯示的主文。"
            )
            self.send_json(
                {
                    "ok": not bool(error) or bool(article_text) or bool(article_markdown),
                    "changed": changed,
                    "error": error,
                    "message": message,
                    "article_text": article_text,
                    "article_markdown": article_markdown,
                    "article_html": article_html,
                    "article_text_status": metadata.get("article_text_status", ""),
                    "article_markdown_status": metadata.get("article_markdown_status", ""),
                    "original_language": item_original_language(response_item or {}),
                    "can_translate": bool(translation_actions_markup),
                    "translation_actions_html": translation_actions_markup,
                    "image_url": metadata.get("image_url", ""),
                    "redirect": redirect_to,
                },
                HTTPStatus.OK if (not error or article_text or article_markdown) else HTTPStatus.BAD_GATEWAY,
            )
            return
        if changed:
            separator = "&" if "?" in redirect_to else "?"
            self.redirect(f"{redirect_to}{separator}saved=read_more")
            return
        separator = "&" if "?" in redirect_to else "?"
        if error:
            self.redirect(f"{redirect_to}{separator}error=read_more")
            return
        self.redirect(f"{redirect_to}{separator}saved=read_more")

    def codex_review_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        provider = normalize_ai_provider(form_value(data, "provider", "codex"), allow_random=True)
        force_review = form_value(data, "force", "") == "1"
        replace_reviews = form_value(data, "replace_reviews", "") == "1"
        redirect_to = form_value(data, "redirect", f"/items/view?id={quote(item_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = f"/items/view?id={quote(item_id)}"

        target = ""
        target_path = ITEMS
        if any(row.get("id") == item_id for row in load_jsonl(ITEMS)):
            target = "items"
            target_path = ITEMS
        elif any(row.get("id") == item_id for row in load_jsonl(CANDIDATES)):
            target = "candidates"
            target_path = CANDIDATES
        else:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到項目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return

        if form_value(data, "with_fulltext", "1") == "1":
            self.update_read_more_record(target_path, item_id)

        command = [
            sys.executable,
            str(ROOT / "scripts" / "codex_enrich_reviews.py"),
            "--provider",
            provider,
            "--target",
            target,
            "--id",
            item_id,
            "--limit",
            "1",
            "--batch-size",
            "1",
        ]
        if force_review:
            command.append("--no-missing-only")
        if replace_reviews:
            command.append("--replace-existing")
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=960)
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
            ok = result.returncode == 0
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + ("\nSTDERR:\n" + exc.stderr if exc.stderr else "")
            output = (output + f"\n{ai_provider_label(provider)} 單篇生成逾時。").strip()
            ok = False
            result = subprocess.CompletedProcess(command, returncode=124, stdout="", stderr=output)

        separator = "&" if "?" in redirect_to else "?"
        final_redirect = f"{redirect_to}{separator}{'saved=codex_review' if ok else 'error=codex_review'}"
        if wants_json:
            self.send_json(
                {
                    "ok": ok,
                    "returncode": result.returncode,
                    "command": command,
                    "output": output,
                    "redirect": final_redirect,
                    "error": "" if ok else clean_text(output, 1000),
                },
                HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY,
            )
            return
        self.redirect(final_redirect)

    def codex_review_batch(self, data: dict[str, list[str]]) -> None:
        """對勾選的多筆項目，用指定引擎批次補 AI 閱讀建議。沿用 runEngineJob（右下角狀態列）。"""
        raw_ids = ",".join(data.get("ids") or [])
        item_ids = [item_id.strip() for item_id in raw_ids.split(",") if item_id.strip()]
        provider = normalize_ai_provider(form_value(data, "provider", "codex"))
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        status_command = "codex_review_batch"
        if not item_ids:
            if wants_json:
                self.send_json({"ok": False, "error": "請先勾選至少一筆項目"}, HTTPStatus.BAD_REQUEST)
                return
            self.redirect("/items?error=empty-selection")
            return

        command = [
            sys.executable,
            str(ROOT / "scripts" / "codex_enrich_reviews.py"),
            "--provider",
            provider,
            "--target",
            "both",
            "--workflow-scope",
            "--no-missing-only",
            "--limit",
            str(len(item_ids)),
            "--batch-size",
            "4",
            "--status-file",
            str(COMMAND_STATUS),
            "--status-command",
            status_command,
        ]
        for item_id in item_ids:
            command += ["--id", item_id]

        started_at = now_iso()
        write_json(
            COMMAND_STATUS,
            {
                "command": status_command,
                "state": "running",
                "message": f"正在用 {ai_provider_label(provider)} 產生 {len(item_ids)} 筆 AI 閱讀建議…",
                "started_at": started_at,
                "provider": provider,
                "total": len(item_ids),
            },
        )
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=1800)
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
            ok = result.returncode == 0
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + ("\nSTDERR:\n" + exc.stderr if exc.stderr else "")
            output = (output + f"\n{ai_provider_label(provider)} 批次生成逾時。").strip()
            ok = False
            result = subprocess.CompletedProcess(command, returncode=124, stdout="", stderr=output)

        if ok:
            final_redirect = f"/items?saved=codex_review_batch&count={len(item_ids)}&provider={quote(provider)}"
        else:
            final_redirect = "/items?error=codex_review"
        write_json(
            COMMAND_STATUS,
            {
                "command": status_command,
                "state": "done" if ok else "failed",
                "message": (
                    f"已用 {ai_provider_label(provider)} 補上 {len(item_ids)} 筆 AI 閱讀建議。"
                    if ok
                    else f"{ai_provider_label(provider)} 批次 AI 閱讀建議失敗。"
                ),
                "returncode": result.returncode,
                "finished_at": now_iso(),
                "provider": provider,
                "total": len(item_ids),
            },
        )
        if wants_json:
            self.send_json(
                {
                    "ok": ok,
                    "returncode": result.returncode,
                    "command": command,
                    "output": output,
                    "redirect": final_redirect,
                    "error": "" if ok else clean_text(output, 1000),
                },
                HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY,
            )
            return
        self.redirect(final_redirect)

    def update_url_record(self, path: Path, item_id: str, new_url: str, action: str) -> tuple[bool, str]:
        records = load_jsonl(path)
        updated_records = []
        found = False
        error = ""
        final_url = unwrap_google_alert_url(new_url)
        if action == "resolve":
            resolved, error = resolve_final_url(new_url)
            if resolved:
                final_url = resolved
        if not final_url:
            return False, error or "網址是空的。"
        updated_at = now_iso()
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated = dict(item)
            previous_url = clean_text(updated.get("url"))
            updated["url"] = final_url
            reference = updated.get("reference") if isinstance(updated.get("reference"), dict) else {}
            updated["reference"] = {
                **reference,
                "url_updated_at": updated_at,
                "url_update_source": "local_web",
                "previous_url": previous_url,
            }
            if action == "resolve":
                updated["reference"]["resolved_from_url"] = new_url
            metadata = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
            if previous_url and previous_url != final_url:
                updated["reading_metadata"] = {
                    **metadata,
                    "url_before_update": previous_url,
                    "url_updated_at": updated_at,
                }
            updated_records.append(updated)
        if found:
            write_jsonl(path, updated_records)
        return found, error

    def update_item_url(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        new_url = form_value(data, "url")
        action = form_value(data, "action", "save")
        redirect_to = form_value(data, "redirect", f"/items/view?id={quote(item_id)}")
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = f"/items/view?id={quote(item_id)}"
        found, error = self.update_url_record(ITEMS, item_id, new_url, action)
        if not found:
            found, error = self.update_url_record(CANDIDATES, item_id, new_url, action)
        if not found:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        if error and action == "resolve":
            self.redirect(f"{redirect_to}{separator}error=url_resolve")
            return
        self.redirect(f"{redirect_to}{separator}saved=url")

    def update_title_record(self, path: Path, item_id: str, title: str) -> bool:
        records = load_jsonl(path)
        updated_records = []
        found = False
        updated_at = now_iso()
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated = dict(item)
            metadata = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
            metadata = dict(metadata)
            clean_title = clean_text(title, 320)
            if clean_title:
                updated["editorial_title"] = clean_title
                metadata["editorial_title"] = clean_title
                metadata["editorial_title_source"] = "manual"
                metadata["editorial_title_updated_at"] = updated_at
            else:
                updated.pop("editorial_title", None)
                metadata.pop("editorial_title", None)
                metadata.pop("editorial_title_source", None)
                metadata["editorial_title_cleared_at"] = updated_at
            updated["reading_metadata"] = metadata
            updated_records.append(updated)
        if found:
            write_jsonl(path, updated_records)
        return found

    def update_item_title(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        title = form_value(data, "title")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        found = self.update_title_record(ITEMS, item_id, title)
        if not found:
            found = self.update_title_record(CANDIDATES, item_id, title)
        if not found:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=title")

    def update_metadata_record(self, path: Path, item_id: str, data: dict[str, list[str]]) -> bool:
        fields = [
            "original_site_title",
            "original_language",
            "translated_zh_title",
            "original_author",
            "original_license",
            "original_license_url",
        ]
        records = load_jsonl(path)
        updated_records = []
        found = False
        updated_at = now_iso()
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated = dict(item)
            metadata = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
            metadata = dict(metadata)
            for field in fields:
                value = clean_text(form_value(data, field), 1200 if field != "translated_zh_title" else 320)
                metadata[field] = value
                if value:
                    metadata[f"{field}_source"] = "manual"
            metadata["metadata_updated_at"] = updated_at
            updated["reading_metadata"] = metadata
            updated["license"] = manual_license_record(
                form_value(data, "license_name"),
                updated.get("license"),
                (data.get("license_json") or [""])[0],
            )
            updated_records.append(updated)
        if found:
            write_jsonl(path, updated_records)
        return found

    def update_item_metadata(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        found = self.update_metadata_record(ITEMS, item_id, data)
        if not found:
            found = self.update_metadata_record(CANDIDATES, item_id, data)
        if not found:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=metadata")

    def translate_item_zh(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        provider = normalize_ai_provider(form_value(data, "provider", "codex"))
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        target_path = ITEMS
        if any(item.get("id") == item_id for item in load_jsonl(ITEMS)):
            target_path = ITEMS
        elif any(item.get("id") == item_id for item in load_jsonl(CANDIDATES)):
            target_path = CANDIDATES
        else:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到可翻譯項目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到項目", "<h1>找不到可翻譯項目</h1><p><a class='button' href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        found, changed, response_item, error = self.update_read_more_record(target_path, item_id)
        article_markdown = item_edited_markdown(response_item or {}) or item_article_markdown(response_item or {})
        if not found or (error and not article_markdown) or not article_markdown:
            if wants_json:
                self.send_json({"ok": False, "error": "還沒有可翻譯的全文，請先展開全文。"}, HTTPStatus.BAD_GATEWAY)
                return
            separator = "&" if "?" in redirect_to else "?"
            self.redirect(f"{redirect_to}{separator}error=translation")
            return
        write_json(TRANSLATE_STATUS, {"state": "running", "item_id": item_id, "message": f"準備翻譯…（{ai_provider_label(provider)}）"})
        command = [
            sys.executable,
            str(ROOT / "scripts" / "codex_translate_article.py"),
            "--provider", provider,
            "--items", str(target_path),
            "--id", item_id,
            "--status-file", str(TRANSLATE_STATUS),
        ]
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=3600)
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
            ok = result.returncode == 0
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + ("\nSTDERR:\n" + (exc.stderr or "") if exc.stderr else "")
            output = (output + f"\n{ai_provider_label(provider)} 翻譯逾時。").strip()
            ok = False
        if not ok:
            print(output, file=sys.stderr)
        separator = "&" if "?" in redirect_to else "?"
        final_redirect = f"{redirect_to}{separator}{'saved=translation' if ok else 'error=translation'}"
        if wants_json:
            status = load_json(TRANSLATE_STATUS)
            self.send_json(
                {
                    "ok": ok,
                    "returncode": 0 if ok else 1,
                    "redirect": final_redirect,
                    "output": clean_text(output, 1200),
                    "done": status.get("done"),
                    "total": status.get("total"),
                    "error": "" if ok else clean_text(status.get("message") or output, 400),
                },
                HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY,
            )
            return
        self.redirect(final_redirect)

    def preview_url(self, data: dict[str, list[str]]) -> None:
        url = form_value(data, "url")
        track = form_value(data, "track", "digital-humanities-local-knowledge")
        title = form_value(data, "title")
        try:
            payload = build_url_preview(url, track, title)
        except Exception as exc:  # noqa: BLE001 - keep the local form from crashing on unusual pages.
            payload = {"ok": False, "error": str(exc)}
        self.send_json(payload, HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_REQUEST)

    def accept_candidate(self, data: dict[str, list[str]]) -> None:
        candidate_id = form_value(data, "id")
        mode = form_value(data, "mode", "accept")
        decision = form_value(data, "decision")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "")
        candidate_exists = any(row.get("id") == candidate_id for row in load_jsonl(CANDIDATES))
        if not candidate_exists:
            self.send_html("找不到候選項目", "<h1>找不到 RSS 新進項目</h1><p><a href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return

        if decision in {"accept", "accept_reading", "direct_pr"}:
            count = self.update_pending_decisions([candidate_id], decision)
            if self.is_async_request():
                self.send_no_content()
                return
            saved = "direct_pr" if decision == "direct_pr" else "accepted_reading" if decision == "accept_reading" else "accepted"
            if redirect_to:
                self.redirect(redirect_to)
                return
            self.redirect(f"/items?saved={saved}&count={count}")
            return

        item, already_exists = self.import_candidate_item(candidate_id)
        if item is None:
            self.send_html("找不到候選項目", "<h1>找不到 RSS 新進項目</h1><p><a href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return

        if mode == "accept_issue":
            returncode, output = create_github_issue(item)
            body = f"""
<h1>已收下候選項目</h1>
<p class="muted">資料庫：{'原本已存在，已從 RSS 新進移除。' if already_exists else '已寫進 database/items.jsonl。'}</p>
<p class="muted">GitHub issue exit code: {returncode}</p>
<pre>{h(output)}</pre>
<p><a class="button" href="/items">回入庫建檔區</a></p>
"""
            self.send_html("已收下候選項目", body)
            return

        if self.is_async_request():
            self.send_no_content()
            return
        if redirect_to:
            self.redirect(redirect_to)
            return
        self.redirect("/items?saved=queued&count=1")

    def dismiss_candidate(self, data: dict[str, list[str]]) -> None:
        candidate_id = form_value(data, "id")
        reason = form_value(data, "reason")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "")
        if not self.dismiss_candidate_record(candidate_id, reason):
            self.send_html("找不到候選項目", "<h1>找不到 RSS 新進項目</h1><p><a href='/items'>回入庫建檔區</a></p>", HTTPStatus.NOT_FOUND)
            return
        if self.is_async_request():
            self.send_no_content()
            return
        if redirect_to:
            self.redirect(redirect_to)
            return
        self.redirect("/items?saved=dismissed&count=1")

    def show_keywords(self) -> None:
        config = load_json(TRIAGE_KEYWORDS)
        track_sections = []
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge"]:
            meta = track_meta(track)
            track_config = (config.get("tracks") or {}).get(track, {})
            keep_keywords = "\n".join(track_config.get("keep_keywords") or [])
            skip_keywords = "\n".join(track_config.get("skip_keywords") or [])
            css_class = track_class(track)
            track_sections.append(
                f"""
<section class="card track-card track-card--{h(css_class)}" id="track-{h(track)}">
  {badge(meta["short"], css_class)}
  <h2>{h(meta["label"])}</h2>
  <label>建議收的關鍵字</label>
  <textarea name="{h(track)}__keep_keywords">{h(keep_keywords)}</textarea>
  <p class="help">一行一個。候選文章標題、摘要、來源或標籤有命中，就會標成建議收。</p>
  <label>建議不要看的關鍵字</label>
  <textarea name="{h(track)}__skip_keywords">{h(skip_keywords)}</textarea>
  <p class="help">一行一個。命中這裡會優先標成建議不要看，例如交通管制、抽獎、停水。</p>
</section>
"""
            )
        body = f"""
<h1>篩選關鍵字</h1>
<p class="lede">這裡控制入庫建檔區的第一層判斷，也會影響本機規則判斷欄位裡的「關鍵字匹配程度」。它不會刪資料，只會更新建議。</p>
<form method="post" action="/keywords">
  <div class="track-grid">{''.join(track_sections)}</div>
  <button type="submit">儲存關鍵字設定</button>
  <p class="help">儲存後會寫進 database/triage-keywords.json。下一次抓 RSS 時會套用。</p>
</form>
<div class="card">
  <h2>套用到目前待整理</h2>
  <p class="muted">如果你剛改完關鍵字，可以立刻重跑目前 RSS 新進與 database/items.jsonl 裡的 inbox 項目，並一起更新「三個建議看的理由」與初步收錄判斷。</p>
  <form method="post" action="/commands/run">
    <input type="hidden" name="command" value="apply_triage_keywords">
    <button type="submit" class="secondary">重新跑本機規則/關鍵字初篩</button>
  </form>
  <p class="help">這只更新 triage 與 editorial_triage 建議，不會自動收下、不會刪資料，也不會開 GitHub issue。</p>
</div>
"""
        self.send_html("篩選關鍵字", body)

    def save_keywords(self, data: dict[str, list[str]]) -> None:
        config = load_json(TRIAGE_KEYWORDS) or {"version": 1, "tracks": {}}
        config.setdefault("version", 1)
        config.setdefault("tracks", {})
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge"]:
            config["tracks"].setdefault(track, {"label": track_meta(track)["label"]})
            keep = [line.strip() for line in form_value(data, f"{track}__keep_keywords").split("\n") if line.strip()]
            skip = [line.strip() for line in form_value(data, f"{track}__skip_keywords").split("\n") if line.strip()]
            config["tracks"][track]["label"] = track_meta(track)["label"]
            config["tracks"][track]["keep_keywords"] = keep
            config["tracks"][track]["skip_keywords"] = skip
        write_json(TRIAGE_KEYWORDS, config)
        configured_keep_keyword_labels.cache_clear()
        self.redirect("/keywords?saved=1")

    def quick_update_source(self, data: dict[str, list[str]]) -> None:
        source_id = form_value(data, "id")
        field = form_value(data, "field")
        value = form_value(data, "value")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "/sources")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        allowed_values = {
            "status": SOURCE_STATUSES,
            "fetch_frequency": FETCH_FREQUENCIES,
        }
        if field not in allowed_values or value not in allowed_values[field]:
            if wants_json:
                self.send_json({"ok": False, "error": "欄位不允許"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_html("欄位不允許", "<h1>欄位不允許</h1>", HTTPStatus.BAD_REQUEST)
            return
        sources = load_jsonl(SOURCES)
        updated_sources = []
        found = False
        for source in sources:
            if source.get("id") != source_id:
                updated_sources.append(source)
                continue
            updated = dict(source)
            updated[field] = value
            updated_sources.append(updated)
            found = True
        if not found:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到來源"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到來源", "<h1>找不到來源</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(SOURCES, updated_sources)
        if wants_json:
            self.send_json({"ok": True, "id": source_id, "field": field, "value": value})
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=source_quick")

    def move_source_group(self, data: dict[str, list[str]]) -> None:
        source_id = form_value(data, "id")
        target_track = form_value(data, "track")
        target_group = form_value(data, "source_group")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "/sources")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if target_track not in TRACK_META or not target_group:
            if wants_json:
                self.send_json({"ok": False, "error": "目標分類不完整"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_html("目標分類不完整", "<h1>目標分類不完整</h1>", HTTPStatus.BAD_REQUEST)
            return
        sources = load_jsonl(SOURCES)
        group_order = source_group_order_for(sources, target_track, target_group)
        if group_order is None:
            group_order = next_source_group_order(sources, target_track)
        updated_sources = []
        found = False
        changed = False
        for source in sources:
            if source.get("id") != source_id:
                updated_sources.append(source)
                continue
            found = True
            updated = dict(source)
            if updated.get("track") != target_track or updated.get("source_group") != target_group:
                updated["track"] = target_track
                updated["source_group"] = target_group
                updated["source_group_order"] = group_order
                changed = True
            updated_sources.append(updated)
        if not found:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到來源"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到來源", "<h1>找不到來源</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return
        if changed:
            write_jsonl(SOURCES, updated_sources)
        if wants_json:
            self.send_json(
                {
                    "ok": True,
                    "updated": 1 if changed else 0,
                    "id": source_id,
                    "track": target_track,
                    "source_group": target_group,
                }
            )
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=source_group_move")

    def reorder_source_groups(self, data: dict[str, list[str]]) -> None:
        track = form_value(data, "track")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "/sources")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if track not in TRACK_META:
            if wants_json:
                self.send_json({"ok": False, "error": "主線不正確"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_html("主線不正確", "<h1>主線不正確</h1>", HTTPStatus.BAD_REQUEST)
            return
        try:
            groups_raw = json.loads(form_value(data, "groups", "[]"))
        except json.JSONDecodeError:
            groups_raw = form_lines(form_value(data, "groups"))
        groups = []
        for group in groups_raw if isinstance(groups_raw, list) else []:
            group_name = clean_text(group)
            if group_name and group_name not in groups:
                groups.append(group_name)
        if not groups:
            if wants_json:
                self.send_json({"ok": False, "error": "沒有可儲存的分類順序"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_html("沒有分類順序", "<h1>沒有可儲存的分類順序</h1>", HTTPStatus.BAD_REQUEST)
            return
        order_map = {group: index for index, group in enumerate(groups)}
        sources = load_jsonl(SOURCES)
        updated_sources = []
        changed = 0
        for source in sources:
            if source.get("track") == track and source.get("source_group") in order_map:
                updated = dict(source)
                updated["source_group_order"] = order_map[source.get("source_group")]
                updated_sources.append(updated)
                changed += 1
            else:
                updated_sources.append(source)
        write_jsonl(SOURCES, updated_sources)
        if wants_json:
            self.send_json({"ok": True, "updated": changed, "groups": groups})
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=source_group_order")

    def rename_source_group(self, data: dict[str, list[str]]) -> None:
        track = form_value(data, "track")
        old_group = form_value(data, "old_group")
        new_group = form_value(data, "new_group")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "/sources")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if track not in TRACK_META or not old_group or not new_group:
            if wants_json:
                self.send_json({"ok": False, "error": "分類資料不完整"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_html("分類資料不完整", "<h1>分類資料不完整</h1>", HTTPStatus.BAD_REQUEST)
            return
        if new_group == old_group:
            if wants_json:
                self.send_json({"ok": True, "updated": 0, "new_group": new_group})
                return
            self.redirect(redirect_to)
            return
        sources = load_jsonl(SOURCES)
        conflict = any(
            source.get("track") == track and source.get("source_group") == new_group
            for source in sources
        )
        if conflict:
            if wants_json:
                self.send_json({"ok": False, "error": "這個分類名稱已經存在"}, HTTPStatus.CONFLICT)
                return
            self.send_html("分類已存在", "<h1>這個分類名稱已經存在</h1>", HTTPStatus.CONFLICT)
            return
        group_order = source_group_order_for(sources, track, old_group)
        updated_sources = []
        changed = 0
        for source in sources:
            if source.get("track") == track and source.get("source_group") == old_group:
                updated = dict(source)
                updated["source_group"] = new_group
                if group_order is not None:
                    updated["source_group_order"] = group_order
                updated_sources.append(updated)
                changed += 1
            else:
                updated_sources.append(source)
        if not changed:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到這個分類"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到分類", "<h1>找不到這個分類</h1>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(SOURCES, updated_sources)
        if wants_json:
            self.send_json({"ok": True, "updated": changed, "new_group": new_group})
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=source_group_name")

    def run_source_fetch(self, source_id: str) -> tuple[bool, str]:
        source = next((row for row in load_jsonl(SOURCES) if row.get("id") == source_id), {})
        report = ROOT / ".cache" / f"rss-fetch-{source_id}.md"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "fetch_rss.py"),
            "--candidate-output",
            str(CANDIDATES),
            "--dismissed",
            str(DISMISSED),
            "--source-id",
            source_id,
            "--include-unclassified",
            "--force",
            "--include-on-update",
            "--report",
            str(report),
            "--status-file",
            str(RSS_FETCH_STATUS),
        ]
        source_type = clean_text(source.get("source_type"))
        if source_type in {"rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor"}:
            command.extend(["--source-type", source_type])
        source_track = clean_text(source.get("track"))
        if source_track:
            command.extend(["--track", source_track])
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
        output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        return result.returncode == 0, output

    def fetch_source_now_post(self, data: dict[str, list[str]]) -> None:
        source_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/sources/view?id={quote(source_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if not any(source.get("id") == source_id for source in load_jsonl(SOURCES)):
            if wants_json:
                self.send_json({"ok": False, "error": "找不到來源", "returncode": 1}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到來源", "<h1>找不到來源</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return
        ok, output = self.run_source_fetch(source_id)
        counts = source_fetch_counts(latest_source_fetch_stats(source_id))
        summary = source_fetch_summary_from_counts(counts)
        if wants_json:
            self.send_json(
                {
                    "ok": ok,
                    "label": "手動更新 RSS",
                    "returncode": 0 if ok else 1,
                    "summary": summary,
                    "output": output,
                    "redirect": redirect_to,
                    **counts,
                },
                HTTPStatus.OK,
            )
            return
        separator = "&" if "?" in redirect_to else "?"
        params = {"saved" if ok else "error": "source_fetch", **{key: str(value) for key, value in counts.items()}}
        self.redirect(f"{redirect_to}{separator}{urlencode(params)}")

    def rescan_source_keyword_exclusions(self, source: dict) -> dict[str, int]:
        source_id = clean_text(source.get("id"))
        if not source_id:
            return {"items": 0, "candidates": 0}
        decided_at = now_iso()
        reason = SOURCE_KEYWORD_EXCLUSION_REASON
        note = f"單一 RSS 來源關鍵字更新後重新盤點；排除原因：{reason}"

        items = load_jsonl(ITEMS)
        kept_items = []
        archived_items = []
        events = []
        for item in items:
            if item.get("source_id") != source_id or item.get("status") != "inbox" or source_record_passes_keywords(item, source):
                kept_items.append(item)
                continue
            updated = dict(item)
            updated["status"] = "archived"
            updated["priority"] = "low"
            updated["local_decision"] = {
                "action": "rejected",
                "decided_at": decided_at,
                "reason": reason,
                "source": "local_web_source_keywords",
            }
            updated["review"] = append_review_note(updated.get("review") or {}, f"{decided_at} {note}")
            archived_items.append(updated)
            events.append(review_event(updated, "rejected", note))
        if archived_items:
            write_jsonl(ITEMS, kept_items)
            for item in archived_items:
                upsert_jsonl(REJECTED_ITEMS, rejected_archive_record(item, decided_at, reason))
            for event in events:
                append_jsonl(REVIEW_EVENTS, event)

        candidate_ids = [
            clean_text(candidate.get("id"))
            for candidate in load_jsonl(CANDIDATES)
            if candidate.get("source_id") == source_id and not source_record_passes_keywords(candidate, source)
        ]
        dismissed_count = 0
        for candidate_id in candidate_ids:
            if candidate_id and self.dismiss_candidate_record(candidate_id, reason):
                dismissed_count += 1
        return {"items": len(archived_items), "candidates": dismissed_count}

    def restore_source_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        source_id = form_value(data, "source_id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/sources/view?id={quote(source_id)}")
        rejected_records = load_jsonl(REJECTED_ITEMS)
        restored_record: dict | None = None
        kept_rejected = []
        for record in rejected_records:
            if record.get("id") == item_id and restored_record is None:
                restored_record = record
                continue
            kept_rejected.append(record)

        dismissed_records = load_jsonl(DISMISSED)
        kept_dismissed = []
        dismissed_record: dict | None = None
        for record in dismissed_records:
            if record.get("id") == item_id and dismissed_record is None:
                dismissed_record = record
                continue
            kept_dismissed.append(record)

        if restored_record is None:
            restored_record = dismissed_record
        if restored_record is None:
            self.send_html("找不到不收紀錄", "<h1>找不到不收紀錄</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return

        decided_at = now_iso()
        note = "從單一 RSS 來源的不收紀錄重新收錄，回到入庫建檔區。"
        restored = dict(restored_record)
        for key in ["archive", "dismissed_at", "candidate_status", "reason"]:
            restored.pop(key, None)
        restored["status"] = "inbox"
        restored["priority"] = "normal"
        restored["local_decision"] = {
            "action": "restored",
            "decided_at": decided_at,
            "reason": "來源頁重新收錄",
            "source": "local_web",
            "next_step": "review-in-rss-inbox",
        }
        restored["review"] = append_review_note(restored.get("review") or {}, f"{decided_at} {note}")
        if source_id and not restored.get("source_id"):
            restored["source_id"] = source_id
        upsert_jsonl(ITEMS, restored)
        write_jsonl(REJECTED_ITEMS, kept_rejected)
        write_jsonl(DISMISSED, kept_dismissed)
        append_jsonl(REVIEW_EVENTS, review_event(restored, "restored", note))

        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=restored")

    def show_track(self, track: str) -> None:
        if track not in TRACK_META:
            self.send_html("找不到主線", "<h1>找不到這條知識主線</h1>", HTTPStatus.NOT_FOUND)
            return

        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        candidates = load_jsonl(CANDIDATES)
        meta = track_meta(track)
        css_class = track_class(track)
        button_class = f"button-{css_class}" if css_class in {"opentech", "humanities"} else "secondary"
        track_items = [item for item in items if item.get("track") == track]
        inbox_items = [item for item in track_items if item.get("status") == "inbox"]
        pending_items = [*inbox_items, *[item for item in candidates if item.get("track") == track]]
        track_sources = [source for source in sources if source.get("track") == track and source.get("status") != "archived"]
        fetchable_sources = [source for source in track_sources if is_fetchable_source(source)]
        source_types = Counter(source.get("source_type", "manual") for source in track_sources)
        source_groups = Counter(source.get("source_group", "未標示群組") for source in track_sources)
        recent_items = sorted(
            pending_items,
            key=lambda item: (item_sort_time(item), item_display_title(item)),
            reverse=True,
        )[:12]

        item_rows = []
        for item in recent_items:
            title = item_display_title(item)
            source_name = item.get("source_name") or item.get("author") or "未標示來源"
            captured = item_display_time(item, "captured_at", "published_at")
            detail_href = item_detail_href(item)
            item_rows.append(
                f"""
<div class="list-item list-item--{h(css_class)}">
  <strong><a href="{h(detail_href)}">{h(title)}</a></strong>
  <p class="muted">{source_name_link(item) if item.get('source_id') else h(source_name)} · {h(captured)} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a></p>
  <p class="break-anywhere">{h(clean_text(item.get('summary'), 180))}</p>
</div>
"""
            )
        if not item_rows:
            item_rows.append('<div class="list-item"><strong>目前沒有入庫建檔項目</strong><p class="muted">等下一次 RSS 抓取或手動入庫後，會出現在這裡。</p></div>')

        type_rows = []
        for source_type, count in source_types.most_common():
            safe_type = source_type.replace("_", "-")
            type_rows.append(
                f"<p>{badge(source_type_label(source_type), safe_type)} <strong>{count}</strong> 個來源<br><span class='help'>{h(SOURCE_TYPE_HELP.get(source_type, '這類來源目前只作為分類註記。'))}</span></p>"
            )
        group_rows = []
        for group, count in source_groups.most_common(10):
            group_rows.append(f"<li>{h(group)} <span class='muted'>({count})</span></li>")

        body = f"""
<h1>{h(meta["label"])}</h1>
<p class="lede">{h(meta["description"])}</p>
<div class="card track-card track-card--{h(css_class)}">
  {badge(meta["short"], css_class)}
  <div class="metric-row">
    {metric_tile(len(track_items), "全部項目", href_with_query("/reader", [("track", track), ("time", "all")]), "看閱讀")}
    {metric_tile(len(pending_items), "待建檔", href_with_query("/items", [("track", track)]), "篩選")}
    {metric_tile(len(track_sources), "來源", href_with_query("/sources", [("track", track)]), "看來源")}
    {metric_tile(len(fetchable_sources), "會自動抓", href_with_query("/sources", [("track", track), ("status", "active")]), "只看啟用")}
  </div>
  <div class="button-row">
    <a class="button {h(button_class)}" href="/items/new?track={quote(track)}">幫這條主線手動入庫</a>
    <a class="button secondary" href="/sources/new?track={quote(track)}">幫這條主線加 RSS</a>
    <a class="button quiet" href="/sources?track={quote(track)}">看這條主線的來源</a>
  </div>
  <p class="help">手動入庫是單篇文章或頁面；加 RSS 是長期追蹤一個網站或 feed；看來源可以檢查目前追蹤清單。</p>
</div>

<div class="two-column">
  <section>
    <h2>入庫建檔項目</h2>
    <div class="list">{''.join(item_rows)}</div>
  </section>
  <aside>
    <h2>來源分類</h2>
    <div class="card">
      {''.join(type_rows) if type_rows else '<p class="muted">這條主線目前還沒有來源。</p>'}
    </div>
    <h2>常見來源群組</h2>
    <div class="card">
      <ul>{''.join(group_rows) if group_rows else '<li class="muted">還沒有來源群組。</li>'}</ul>
    </div>
  </aside>
</div>
"""
        self.send_html(meta["label"], body)

    def show_item_form(self, query: dict[str, list[str]]) -> None:
        title = clean_text(unquote((query.get("title") or [""])[0]))
        url = clean_text(unquote((query.get("url") or [""])[0]))
        # 進表單前先查重複：URL 已在資料庫或退件庫 → 直接顯示警告，不花算力繼續
        if url:
            url_key = canonical_item_url(url)
            if url_key:
                all_items = load_jsonl(ITEMS)
                rejected_items = load_jsonl(REJECTED_ITEMS)
                dup = next(
                    (item for item in [*all_items, *rejected_items] if url_key in item_url_keys(item)),
                    None,
                )
                if dup:
                    dup_id = clean_text(dup.get("id"))
                    dup_title = h(item_display_title(dup))
                    dup_status = h(status_label(clean_text(dup.get("status"))) or clean_text(dup.get("status")) or "未知")
                    dup_href = f"/items/view?id={quote(dup_id)}" if dup_id else ""
                    is_rejected = clean_text(dup.get("status")) in {"rejected", "archived"}
                    notice_class = "notice notice--warn" if is_rejected else "notice notice--info"
                    dup_link = f'<a href="{h(dup_href)}">{dup_title}</a>' if dup_href else dup_title
                    notice_msg = (
                        f"這個網址之前已標記為不收。目前狀態：{dup_status}。如果你想重新審閱，可以開啟原來的紀錄。"
                        if is_rejected
                        else f"這個網址已在知識庫中。目前狀態：{dup_status}。不需要重複入庫，直接開啟現有材料即可。"
                    )
                    body = f"""
<h1>手動入庫</h1>
<div class="{notice_class}">
  <strong>⚠ 重複：{dup_link}</strong><br>
  {h(notice_msg)}
  {f'<div class="button-row" style="margin-top:10px"><a class="button" href="{h(dup_href)}">{button_content("開啟現有材料", "external")}</a><a class="button secondary" href="/items/new">改填其他網址</a></div>' if dup_href else ''}
</div>
"""
                    self.send_html("手動入庫 — 重複", body)
                    return
        current_track = (query.get("track") or ["digital-humanities-local-knowledge"])[0]
        if current_track not in TRACK_META:
            current_track = "digital-humanities-local-knowledge"
        track_autofill = "0"
        if "track" not in query and (title or url):
            keyword_config = load_json(TRIAGE_KEYWORDS) or {"version": 1, "tracks": {}}
            history = [*load_jsonl(ITEMS), *load_jsonl(REJECTED_ITEMS)]
            editorial_context = build_editorial_context(history, keyword_config)
            inferred_track, _reason, _choices = infer_manual_item_track(
                {
                    "title": title,
                    "url": url,
                    "source_name": host_label(url),
                    "author": "",
                    "published_at": "",
                    "summary": "",
                    "tags": [],
                    "origin": "manual-web",
                },
                keyword_config,
                editorial_context,
                current_track,
            )
            if inferred_track in TRACK_META:
                current_track = inferred_track
            track_autofill = "1"
        tag_records = load_jsonl(ITEMS)
        existing_tags = all_tag_options(tag_records, limit=200)
        # 建議＝資料庫實際有的標籤（依分面分群，含同主題的罕見 tag）＋ taxonomy 骨架（確保空主題也露面），
        # 讓人一眼看到「已經有哪些分類/資料」。
        suggestion_tags = []
        _seen = set()
        for tag in [*taxonomy_primary_tags(), *existing_tags]:
            append_unique_tag(suggestion_tags, _seen, tag)
        tag_controls = tag_picker_controls_html(
            [], suggestion_tags, existing_tags,
            placeholder="搜尋或新增標籤（OS、open data 也找得到）",
            collapse_suggestions=True,
        )
        body = f"""
<h1>手動入庫</h1>
<p class="lede">用在你看到一篇文章、一個頁面或一個案例，想先丟進入庫建檔區時。這裡新增的是單筆知識項目，不是長期 RSS 來源。</p>
<div class="button-row"><a class="button secondary" href="/items/upload-pdf">{button_content("上傳 PDF", "text-lines")}</a></div>
<form class="form-panel tag-picker" method="post" action="/items" data-url-preview-form data-preview-kind="item" data-preview-track-autofill="{track_autofill}" data-tag-picker>
  <label>主線</label>
  <select name="track" data-preview-track>{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定它會出現在「開放科技」或「人文與在地知識」哪一個工作台。</p>
  <label>標題</label>
  <input name="title" value="{h(title)}" required data-preview-title>
  <p class="help">通常用原本網頁標題就好，之後審稿時再改成更清楚的標題。</p>
  <label>網址</label>
  <input name="url" value="{h(url)}" required data-preview-url placeholder="https://example.com/article">
  <p class="help">網址很長也沒關係，列表會自動換行。</p>
  <input type="hidden" name="author" data-preview-author>
  <input type="hidden" name="preview_image_url" data-preview-image-url>
  <input type="hidden" name="preview_canonical_url" data-preview-canonical-url>
  <input type="hidden" name="preview_final_url" data-preview-final-url>
  <input type="hidden" name="preview_site_name" data-preview-site-name>
  <div class="preview-panel" data-preview-panel hidden>
    <div class="preview-status" data-preview-status>等待網址。</div>
    <div class="preview-result" data-preview-result></div>
  </div>
  <button type="button" class="secondary" data-preview-button>{button_content("抓取頁面資訊", "preview", "M")}</button>
  <label>來源 / 網站 / 作者</label>
  <input name="source_name" placeholder="例如：報導者、Open Knowledge Foundation" data-preview-source-name>
  <p class="help">不知道作者時，先填網站或組織名稱。</p>
  <label>發布日期</label>
  <input name="published_at" placeholder="YYYY-MM-DD" data-preview-published-at>
  <p class="help">不確定可以留空，之後整理時再補。</p>
  <label>摘要或摘記</label>
  <textarea name="summary" data-preview-summary></textarea>
  <p class="help">先貼一兩句你覺得重要的脈絡，方便未來審稿時想起來為什麼收。</p>
  <label>標籤</label>
  {tag_controls}
  <p class="help">和單篇頁同一套：輸入別名（OS、open source、OD…）會對到正式標籤；下方依分面有建議。</p>
  <label>備註 / 為什麼值得追</label>
  <textarea name="notes" data-preview-notes></textarea>
  <p class="help">寫給未來的自己看：這則資料可能放進哪個議題、有哪些疑問。</p>
  <button type="submit">把這頁存進待整理</button>
  <p class="help">送出後會寫進 database/items.jsonl，狀態是 inbox，還不會自動發布。</p>
</form>
"""
        self.send_html("加入收藏", body)

    def show_pdf_upload_form(self, query: dict[str, list[str]]) -> None:
        current_track = form_value(query, "track", "digital-humanities-local-knowledge")
        if current_track not in TRACK_META:
            current_track = "digital-humanities-local-knowledge"
        parent_item_id = form_value(query, "parent_item_id")
        relation = form_value(query, "relation", "full-source" if parent_item_id else "")
        parent = next((item for item in load_jsonl(ITEMS) if clean_text(item.get("id")) == parent_item_id), None)
        parent_hint = (
            f'<div class="notice">這份 PDF 會作為「{h(item_display_title(parent))}」的全文材料，並建立 {h(pdf_relation_label(relation))} 關聯。</div>'
            if parent
            else ""
        )
        body = f"""
<h1>上傳 PDF 成為材料</h1>
<p class="lede">PDF 會進入既有的入庫建檔區；本體只存在 <code>.cache/uploads/</code>，不進 Git。全文只用本機 <code>markitdown</code> CLI 抽取。</p>
{parent_hint}
<form class="form-panel" method="post" action="/items/upload-pdf" enctype="multipart/form-data">
  <input type="hidden" name="parent_item_id" value="{h(parent_item_id)}">
  <input type="hidden" name="relation" value="{h(relation)}">
  <label>主線</label>
  <select name="track">{option_list(TRACKS, current_track)}</select>
  <label>PDF 檔案</label>
  <input type="file" name="pdf_file" accept="application/pdf,.pdf" required>
  <p class="help">上限 80 MB。檔名會改成日期、標題與內容雜湊，避免覆蓋與暴露原始路徑。</p>
  <label>標題（可留空）</label>
  <input name="title" placeholder="留空會使用 PDF 第一個大標">
  <label>來源 / 作者（可留空）</label>
  <input name="source_name" placeholder="抓不到時會標成「本機 PDF」">
  <label>摘要或備註（可留空）</label>
  <textarea name="notes" placeholder="留空會使用 markitdown 抽到的第一段"></textarea>
  <button type="submit">{button_content("上傳並抽取 PDF 全文", "text-lines")}</button>
  <p class="help">完成後會比對既有材料，跳出候選關係讓你人工確認；不會自動合併或直接產生 article。</p>
</form>
"""
        self.send_html("上傳 PDF", body)

    def save_pdf_upload(self, data: dict[str, list[str]], files: dict[str, list[dict]]) -> None:
        upload = next(iter(files.get("pdf_file") or []), None)
        if not upload:
            self.send_html("PDF 上傳失敗", "<h1>沒有收到 PDF 檔案</h1><p><a class='button' href='/items/upload-pdf'>回上傳表單</a></p>", HTTPStatus.BAD_REQUEST)
            return
        raw = upload.get("content") or b""
        filename = clean_text(upload.get("filename")) or "upload.pdf"
        content_type = clean_text(upload.get("content_type")).casefold()
        if not filename.casefold().endswith(".pdf") and content_type != "application/pdf":
            self.send_html("PDF 上傳失敗", "<h1>檔案不是 PDF</h1><p>請選擇副檔名為 .pdf 的檔案。</p><p><a class='button' href='/items/upload-pdf'>回上傳表單</a></p>", HTTPStatus.BAD_REQUEST)
            return
        if b"%PDF-" not in raw[:1024]:
            self.send_html("PDF 上傳失敗", "<h1>檔案內容不像 PDF</h1><p>沒有找到 PDF 檔頭，未寫入資料庫。</p><p><a class='button' href='/items/upload-pdf'>回上傳表單</a></p>", HTTPStatus.BAD_REQUEST)
            return

        digest = hashlib.sha256(raw).hexdigest()
        existing_items = load_jsonl(ITEMS)
        duplicate = next(
            (
                item
                for item in existing_items
                if isinstance(item.get("reference"), dict)
                and isinstance(item["reference"].get("pdf_meta"), dict)
                and clean_text(item["reference"]["pdf_meta"].get("sha256")) == digest
            ),
            None,
        )
        if duplicate:
            self.redirect(f"/items/view?id={quote(clean_text(duplicate.get('id')))}&saved=pdf_duplicate")
            return

        track = form_value(data, "track", "unclassified")
        if track not in TRACK_META:
            track = "unclassified"
        provisional_title = form_value(data, "title") or Path(filename).stem
        PDF_UPLOADS.mkdir(parents=True, exist_ok=True)
        stored_name = f"{datetime.now(LOCAL_TIMEZONE):%Y-%m-%d}-{pdf_slugify(provisional_title)}-{digest[:10]}.pdf"
        stored_path = PDF_UPLOADS / stored_name
        stored_path.write_bytes(raw)
        try:
            markdown, pdf_meta = extract_pdf_markdown(stored_path, filename)
        except Exception as exc:  # noqa: BLE001 - local CLI error needs to be shown in the form.
            kept_path = str(stored_path.relative_to(ROOT))
            self.send_html(
                "PDF 抽取失敗",
                f"<h1>PDF 已收到，但 markitdown 抽取失敗</h1><pre>{h(exc)}</pre>"
                f"<p>檔案已保留在本機 <code>{h(kept_path)}</code>，可重試或改用其他檔。</p>"
                f"<p><a class='button' href='/items/upload-pdf'>回上傳表單</a></p>",
                HTTPStatus.BAD_GATEWAY,
            )
            return

        title = form_value(data, "title") or clean_text(pdf_meta.get("title"), 320) or Path(filename).stem
        final_stored_name = f"{datetime.now(LOCAL_TIMEZONE):%Y-%m-%d}-{pdf_slugify(title)}-{digest[:10]}.pdf"
        final_stored_path = PDF_UPLOADS / final_stored_name
        if final_stored_path != stored_path:
            stored_path.replace(final_stored_path)
            stored_path = final_stored_path
        source_url = clean_text(next(iter(pdf_meta.get("urls") or []), ""))
        source_name = form_value(data, "source_name") or clean_text(pdf_meta.get("author"), 240) or "本機 PDF"
        summary = form_value(data, "notes") or clean_text(pdf_meta.get("summary_candidate"), 1600)
        sources = load_jsonl(SOURCES)
        source_id, source_changed = ensure_pdf_upload_source(sources, track)
        if source_changed:
            write_jsonl(SOURCES, sources)
        captured_at = now_iso()
        item_id = stable_id("item", "manual-pdf", digest)
        relative_path = str(stored_path.relative_to(ROOT))
        record = {
            "id": item_id,
            "track": track,
            "status": "inbox",
            "priority": "normal",
            "title": title,
            "url": source_url,
            "source_id": source_id,
            "source_name": source_name,
            "author": clean_text(pdf_meta.get("author")) or source_name,
            "published_at": "",
            "captured_at": captured_at,
            "summary": summary,
            "tags": [],
            "origin": "manual-pdf",
            "source_type": "pdf-upload",
            "reference": {
                "created_by": "local_web",
                "created_from": "pdf-upload",
                "file": relative_path,
                "pdf_meta": pdf_meta,
                "source_url_extracted": bool(source_url),
                "source_status": "extracted" if source_url else "需要出處",
            },
            "reading_metadata": {
                "content_type": "application/pdf",
                "article_markdown": markdown,
                "article_markdown_method": "markitdown-cli",
                "article_markdown_label": "上傳 PDF 全文",
                "article_text_method": "markitdown-cli",
                "fulltext_source": "uploaded-pdf",
                "fulltext_source_file": relative_path,
            },
            "review": default_review("由本機 PDF 上傳建立；來源資訊只採用 markitdown 抽取結果，抓不到則需人工補出處。"),
        }
        record, _changed, normalize_error = normalize_pdf_markdown_item(record)
        if normalize_error:
            kept_path = str(stored_path.relative_to(ROOT))
            self.send_html(
                "PDF 抽取失敗",
                f"<h1>PDF 文字不足</h1><p>{h(normalize_error)}</p>"
                f"<p>檔案已保留在本機 <code>{h(kept_path)}</code>。</p>"
                f"<p><a class='button' href='/items/upload-pdf'>回上傳表單</a></p>",
                HTTPStatus.BAD_REQUEST,
            )
            return
        candidates = pdf_relationship_candidates(record, existing_items, bool(source_url))
        reference = dict(record.get("reference") or {})
        reference["pdf_relation_candidates"] = candidates
        reference["pdf_relation_scored_at"] = captured_at
        record["reference"] = reference
        keyword_config = load_json(TRIAGE_KEYWORDS)
        editorial_context = build_editorial_context([*existing_items, *load_jsonl(REJECTED_ITEMS)], keyword_config)
        record["triage"] = evaluate_triage(record, keyword_config)
        record["editorial_triage"] = evaluate_editorial_triage(record, keyword_config, editorial_context)
        append_jsonl(ITEMS, record)

        parent_id = form_value(data, "parent_item_id")
        relation = form_value(data, "relation", "full-source")
        parent = next((item for item in existing_items if clean_text(item.get("id")) == parent_id), None)
        if parent:
            link_materials(parent, record, relation)

        validation = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_database.py")], cwd=ROOT, text=True, capture_output=True)
        if validation.returncode != 0:
            # 先判斷是不是這次上傳的 item 造成的：移除後再驗一次。
            remove_jsonl_ids(ITEMS, {item_id})
            recheck = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_database.py")], cwd=ROOT, text=True, capture_output=True)
            kept_path = str(stored_path.relative_to(ROOT))
            if recheck.returncode == 0:
                # 移除後就過了 → 是這次上傳的資料本身有問題，回滾 item（但保留 PDF 檔）。
                self.send_html(
                    "PDF 入庫失敗",
                    f"<h1>這份 PDF 的資料沒有通過驗證</h1><pre>{h(validation.stderr or validation.stdout)}</pre>"
                    f"<p>已取消入庫；PDF 檔仍保留在本機 <code>{h(kept_path)}</code>。</p>"
                    f"<p><a class='button' href='/items/upload-pdf'>回上傳表單</a></p>",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            # 移除後仍失敗 → 是既有資料的舊問題，不該牽連這次上傳。把 item 加回去照常入庫。
            append_jsonl(ITEMS, record)
            sys.stderr.write(
                "warning: 資料庫有既有驗證問題，但仍接受這次 PDF 上傳。請另外修正既有資料：\n"
                + (recheck.stderr or recheck.stdout or "") + "\n"
            )
        append_jsonl(REVIEW_EVENTS, review_event(record, "pdf-uploaded", "已上傳本機 PDF、用 markitdown 抽取全文並完成本機材料關係比對。"))
        auto_open = "1" if candidates else "0"
        self.redirect(f"/items/view?id={quote(item_id)}&saved=pdf_upload&pdf_relations={auto_open}")

    def save_item(self, data: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        async_request = self.is_async_request() or form_value(data, "format") == "json"
        url = unwrap_google_alert_url(form_value(data, "url"))
        title = form_value(data, "title") or url
        existing = next((item for item in items if item.get("url") == url), None)
        if existing:
            if async_request:
                self.send_json({"ok": True, "duplicate": True, "item_id": clean_text(existing.get("id")),
                                "message": "這個網址已經在資料庫。"})
                return
            self.send_html("已存在", f"<h1>這個網址已經在資料庫</h1><p>{h(url)}</p><p><a href='/'>回總覽</a></p>")
            return
        track = form_value(data, "track", "unclassified")
        if track not in TRACK_META:
            track = "unclassified"
        captured_at = now_iso()
        tags = self.selected_tag_values(data) or [tag.strip() for tag in form_value(data, "tags").split(",") if tag.strip()]
        notes = form_value(data, "notes")
        preview_metadata = {
            "image_url": form_value(data, "preview_image_url"),
            "canonical_url": form_value(data, "preview_canonical_url"),
            "final_url": form_value(data, "preview_final_url"),
            "site_name": form_value(data, "preview_site_name"),
        }
        preview_metadata = {key: value for key, value in preview_metadata.items() if clean_text(value)}
        if preview_metadata:
            preview_metadata["preview_source"] = "local_web"
        record = {
            "id": stable_id("item", "manual-web", url, title),
            "track": track,
            "status": "inbox",
            "priority": "normal",
            "title": title,
            "url": url,
            "source_id": "",
            "source_name": form_value(data, "source_name"),
            "author": form_value(data, "author") or form_value(data, "source_name"),
            "published_at": form_value(data, "published_at"),
            "captured_at": captured_at,
            "summary": form_value(data, "summary"),
            "tags": tags,
            "origin": "manual-web",
            "reference": {"created_by": "local_web", "created_from": "manual-url"},
            "review": default_review(notes),
        }
        if preview_metadata:
            record["reading_metadata"] = preview_metadata
        if preview_metadata.get("image_url"):
            record["image_url"] = preview_metadata["image_url"]
        enriched, _did_change, metadata_error = enrich_item_metadata(record)
        keyword_config = load_json(TRIAGE_KEYWORDS) or {"version": 1, "tracks": {}}
        editorial_context = build_editorial_context([*items, *load_jsonl(REJECTED_ITEMS)], keyword_config)
        record = apply_manual_item_autofill(
            enriched,
            item_reading_metadata(enriched),
            items,
            keyword_config,
            editorial_context,
            metadata_error=metadata_error,
        )
        metadata = item_reading_metadata(record)
        source_name = clean_text(record.get("source_name"), 160) or "Manual bookmark"
        source_id = stable_id("src", "manual-web", source_name)
        record["source_id"] = source_id
        record["source_name"] = source_name
        record["author"] = clean_text(record.get("author"), 240) or source_name
        if not any(source.get("id") == source_id for source in sources):
            append_jsonl(
                SOURCES,
                {
                    "id": source_id,
                    "track": track,
                    "name": source_name,
                    "source_group": "Manual web bookmark",
                    "source_type": "manual",
                    "fetch_frequency": "daily",
                    "feed_url": "",
                    "site_url": metadata_site_url(metadata, url),
                    "status": "active",
                    "required_keywords": [],
                    "excluded_keywords": [],
                    "notes": "由本機網頁加入。",
                },
            )
        append_jsonl(ITEMS, record)
        if async_request:
            self.send_json({"ok": True, "duplicate": False, "item_id": clean_text(record.get("id")),
                            "message": "已加入待整理。"})
            return
        self.redirect("/?saved=item")

    def show_manual_items(self, query: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        items = load_jsonl(ITEMS)
        manual_source_ids = {
            clean_text(source.get("id"))
            for source in sources
            if source.get("source_type") == "manual"
        }
        manual_items = [
            item
            for item in items
            if item.get("origin") == "manual-web" or clean_text(item.get("source_id")) in manual_source_ids
        ]
        track_filter = form_value(query, "track", "all")
        if track_filter not in {track for track, _label in TRACKS} | {"all"}:
            track_filter = "all"
        filtered = [
            item
            for item in manual_items
            if track_filter == "all" or item.get("track") == track_filter
        ]
        filtered.sort(key=lambda item: (item_sort_time(item), item_display_title(item)), reverse=True)
        track_counts = Counter(item.get("track", "unclassified") for item in manual_items)
        rows = []
        for item in filtered:
            rows.append(
                f"""
<article class="reader-list-card">
  <div class="reader-list-meta">
    {badge(track_meta(item.get("track", "unclassified"))["short"], track_class(item.get("track", "unclassified")))}
    {badge(status_label(item.get("status", "")), "neutral")}
    {badge(item_display_time(item, 'published_at', 'captured_at'), "neutral")}
  </div>
  <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
  <p class="zh-summary">{h(item_zh_summary(item, 360))}</p>
  {tag_chips_html(item_visible_tags(item, 8))}
</article>
"""
            )
        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        body = f"""
<h1>單一手動收存網址</h1>
<p class="lede">這裡只放你手動貼進來的單篇頁面。它們不是 RSS，不會在 RSS 來源列表裡混著管理。</p>
<div class="button-row top-back-row">
  <a class="button quiet" href="/sources">{icon_span("back", "", "icon")}回 RSS 來源</a>
  <a class="button secondary" href="/items/new">新增單篇網址</a>
</div>
<div class="metric-row">
  {metric_tile(len(manual_items), "手動收存", "/manual-items", "看全部", "is-active" if track_filter == "all" else "")}
  {metric_tile(track_counts.get("open-tech-open-industry", 0), "開放科技", href_with_query("/manual-items", [("track", "open-tech-open-industry")]), "只看開放科技", "is-active" if track_filter == "open-tech-open-industry" else "")}
  {metric_tile(track_counts.get("digital-humanities-local-knowledge", 0), "人文知識", href_with_query("/manual-items", [("track", "digital-humanities-local-knowledge")]), "只看人文知識", "is-active" if track_filter == "digital-humanities-local-knowledge" else "")}
</div>
<form class="filter-panel" method="get" action="/manual-items">
  <label>主線</label>
  <select name="track">{option_list(track_options, track_filter)}</select>
  <div class="button-row">
    <button type="submit">套用篩選</button>
    <a class="button secondary" href="/manual-items">清除篩選</a>
  </div>
</form>
<h2>手動收存項目</h2>
<p class="muted">符合條件：{len(filtered)} 筆。</p>
<div class="reader-list">{''.join(rows) or '<div class="card"><p class="muted">目前沒有手動收存項目。</p></div>'}</div>
"""
        self.send_html("單一手動收存網址", body)

    def show_sources(self, query: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        items = load_jsonl(ITEMS)
        rejected_items = load_jsonl(REJECTED_ITEMS)
        candidates = load_jsonl(CANDIDATES)
        dismissed = load_jsonl(DISMISSED)
        track_filter = (query.get("track") or ["all"])[0]
        type_filter = (query.get("source_type") or ["all"])[0]
        status_filter = (query.get("status") or ["live"])[0]

        def matches(source: dict) -> bool:
            if track_filter != "all" and source.get("track") != track_filter:
                return False
            if type_filter != "all" and source.get("source_type") != type_filter:
                return False
            if type_filter == "all" and source.get("source_type") == "manual":
                return False
            status = source.get("status")
            if status_filter == "live":
                return status != "archived"
            if status_filter != "all" and status != status_filter:
                return False
            return True

        filtered_sources = [source for source in sources if matches(source)]
        redirect_path = self.path

        def inline_source_select(source: dict, field: str, options: list[tuple[str, str]], current: str) -> str:
            return f"""
<form class="inline-select-form" method="post" action="/sources/quick-update">
  <input type="hidden" name="id" value="{h(source.get('id', ''))}">
  <input type="hidden" name="field" value="{h(field)}">
  <input type="hidden" name="redirect" value="{h(redirect_path)}">
  <select name="value" aria-label="{h(field)}" onchange="this.form.submit()">{option_list(options, current)}</select>
</form>
"""

        def source_fetch_button(source: dict) -> str:
            return f"""
<form class="chip-form" method="post" action="/sources/fetch" data-source-fetch-form>
  <input type="hidden" name="id" value="{h(source.get('id', ''))}">
  <input type="hidden" name="redirect" value="{h(redirect_path)}">
  <button type="submit" class="reason-chip" title="手動更新這個 RSS">更新</button>
</form>
"""

        def source_status_toggle(source: dict) -> str:
            status = clean_text(source.get("status")) or "active"
            source_id = clean_text(source.get("id"))
            if status == "archived":
                return f"""
<form class="source-toggle-form" method="post" action="/sources/quick-update">
  <input type="hidden" name="id" value="{h(source_id)}">
  <input type="hidden" name="field" value="status">
  <input type="hidden" name="value" value="active">
  <input type="hidden" name="redirect" value="{h(redirect_path)}">
  <button type="submit" class="source-toggle source-toggle--archived" aria-label="恢復啟用">{h(source_status_label(status))}</button>
</form>
"""
            next_status = "paused" if status == "active" else "active"
            label = "啟用" if status == "active" else "暫停"
            hint = "點一下暫停抓取" if status == "active" else "點一下恢復啟用"
            active_class = " is-on" if status == "active" else ""
            return f"""
<form class="source-toggle-form" method="post" action="/sources/quick-update" data-source-toggle-form>
  <input type="hidden" name="id" value="{h(source_id)}">
  <input type="hidden" name="field" value="status">
  <input type="hidden" name="value" value="{h(next_status)}" data-source-toggle-value>
  <input type="hidden" name="redirect" value="{h(redirect_path)}">
  <button type="submit" class="source-toggle{active_class}" title="{h(hint)}" aria-label="{h(hint)}" data-source-toggle-button><span class="toggle-dot"></span>{h(label)}</button>
</form>
"""

        def source_archive_button(source: dict) -> str:
            source_id = clean_text(source.get("id"))
            status = clean_text(source.get("status")) or "active"
            if status == "archived":
                return ""
            return f"""
<form class="chip-form" method="post" action="/sources/quick-update">
  <input type="hidden" name="id" value="{h(source_id)}">
  <input type="hidden" name="field" value="status">
  <input type="hidden" name="value" value="archived">
  <input type="hidden" name="redirect" value="{h(redirect_path)}">
  <button type="submit" class="reason-chip reason-chip--danger" title="封存這個來源">封存</button>
</form>
"""

        track_counts = {track: count_sources(sources, track) for track in TRACK_ORDER}
        fetch_counts = {track: count_sources(sources, track, active_only=True) for track in TRACK_ORDER}
        manual_count = sum(1 for source in sources if source.get("source_type") == "manual")
        type_counts = Counter(source.get("source_type", "manual") for source in filtered_sources)
        grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for source in filtered_sources:
            track = source.get("track", "unclassified")
            group = source.get("source_group", "未標示群組")
            grouped[track][group].append(source)

        type_summary = []
        for source_type, count in type_counts.most_common():
            safe_type = source_type.replace("_", "-")
            type_summary.append(f"{badge(source_type_label(source_type), safe_type)} <span class='muted'>{count}</span>")

        source_sections = []
        ordered_tracks = [track for track in TRACK_ORDER if track in grouped]
        ordered_tracks.extend(sorted(track for track in grouped if track not in ordered_tracks))
        for track in ordered_tracks:
            meta = track_meta(track)
            css_class = track_class(track)
            source_sections.append(f"<h2>{badge(meta['short'], css_class)} {h(meta['label'])}</h2>")
            for group, group_sources in sorted(grouped[track].items(), key=lambda item: source_group_sort_key(item[0], item[1])):
                rows = []
                status_order = {"active": 0, "paused": 1, "archived": 2}
                for source in sorted(group_sources, key=lambda row: (status_order.get(row.get("status", ""), 9), row.get("name", ""), row.get("id", ""))):
                    source_type = source.get("source_type", "manual")
                    status = source.get("status", "")
                    frequency = normalize_fetch_frequency(source.get("fetch_frequency", "daily"))
                    feed_url = source.get("feed_url") or ""
                    site_url = source.get("site_url") or ""
                    type_class = source_type.replace("_", "-")
                    status_class = status.replace("_", "-")
                    health = source_health_summary(source, items, rejected_items, candidates, dismissed)
                    site_link = ""
                    if site_url:
                        site_link = f'<br><a class="muted break-anywhere" href="{h(site_url)}" target="_blank" rel="noreferrer">{h(site_url)}</a>'
                    feed_display = '<span class="muted">沒有 feed URL</span>'
                    if feed_url:
                        feed_display = f'<code class="url">{h(feed_url)}</code>'
                    rows.append(
                        f"<tr class='source-row' id='source-{h(source.get('id', ''))}' data-source-row data-source-id='{h(source.get('id', ''))}' data-track='{h(track)}' data-source-group='{h(group)}'>"
                        "<td class='source-drag-cell'>"
                        "<button type='button' class='source-row-grip' data-source-drag draggable='true' title='拖曳到其他分類' aria-label='拖曳到其他分類'>"
                        "<span></span><span></span><span></span><span></span><span></span><span></span>"
                        "</button>"
                        "</td>"
                        f"<td><strong><a href='/sources/view?id={quote(source.get('id', ''))}'>{h(source.get('name'))}</a></strong>"
                        f"{site_link}</td>"
                        f"<td>{badge(source_type_label(source_type), type_class)}</td>"
                        f"<td>{source_status_toggle(source)}</td>"
                        f"<td>{inline_source_select(source, 'fetch_frequency', [(value, FETCH_FREQUENCY_LABELS.get(value, value)) for value in FETCH_FREQUENCIES], frequency)}</td>"
                        f"<td>{source_health_badge(health)}<br><span class='help'>{h(health.get('reason'))}</span></td>"
                        f"<td class='url-cell'>{feed_display}</td>"
                        f"<td><div class='source-action-row'><a class='reason-chip' href='/sources/edit?id={quote(source.get('id', ''))}'>編輯</a>{source_fetch_button(source)}{source_archive_button(source)}</div></td>"
                        "</tr>"
                    )
                source_sections.append(
                    f"""
<details class="source-group" data-source-group data-track="{h(track)}" data-group="{h(group)}" open>
  <summary class="source-group-summary">
    <span class="source-group-heading">
      <button type="button" class="source-group-name-button" data-source-group-edit>{h(group)}</button>
      <form class="source-group-rename-form" method="post" action="/sources/rename-group" data-source-group-rename hidden>
        <input type="hidden" name="track" value="{h(track)}">
        <input type="hidden" name="old_group" value="{h(group)}">
        <input type="hidden" name="redirect" value="{h(redirect_path)}">
        <input name="new_group" value="{h(group)}" aria-label="分類名稱">
        <button type="submit" class="reason-chip">儲存</button>
        <button type="button" class="reason-chip" data-source-group-cancel>取消</button>
      </form>
    </span>
    <span class="muted" data-source-group-count>({len(group_sources)})</span>
    <span class="source-group-status" data-source-group-status></span>
  </summary>
  <table>
    <thead><tr><th></th><th>名稱</th><th>類型</th><th>狀態</th><th>頻率</th><th>健康狀態</th><th>Feed URL</th><th></th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</details>
"""
                )
        if not source_sections:
            source_sections.append('<div class="card"><strong>沒有符合條件的來源</strong><p class="muted">換一個篩選條件，或新增 RSS 來源。</p></div>')

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        type_options = [("all", "全部來源類型")] + [(value, SOURCE_TYPE_LABELS.get(value, value)) for value in SOURCE_TYPES]
        status_options = [
            ("live", "啟用＋暫停"),
            ("active", "只看啟用"),
            ("paused", "只看暫停"),
            ("archived", "只看封存"),
            ("all", "全部狀態"),
        ]
        overview_cards = []
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge", "unclassified"]:
            meta = track_meta(track)
            css_class = track_class(track)
            overview_cards.append(
                f"""
<div class="card track-card track-card--{h(css_class)}">
  {badge(meta["short"], css_class)}
  <div class="metric-row">
    {metric_tile(track_counts.get(track, 0), "來源", href_with_query("/sources", [("track", track)]), "看來源")}
    {metric_tile(fetch_counts.get(track, 0), "會自動抓", href_with_query("/sources", [("track", track), ("status", "active")]), "只看啟用")}
  </div>
  <p class="help">會自動抓代表狀態是啟用，且類型是 RSS、Google 快訊、YouTube 或 Podcast。</p>
</div>
"""
            )
        notice = ""
        saved = form_value(query, "saved")
        error = form_value(query, "error")
        if saved == "source_quick":
            notice = '<div class="notice">來源欄位已更新。</div>'
        elif saved == "source_group_move":
            notice = '<div class="notice">來源已移到新的分類。</div>'
        elif saved == "source_group_order":
            notice = '<div class="notice">來源分類順序已更新。</div>'
        elif saved == "source_group_name":
            notice = '<div class="notice">來源分類名稱已更新。</div>'
        elif saved == "source_fetch":
            notice = f'<div class="notice">已手動更新這個 RSS。{h(source_fetch_summary_from_query(query))}新的項目會進入庫建檔區。</div>'
        elif error == "source_fetch":
            notice = f'<div class="notice">手動更新沒有成功。{h(source_fetch_summary_from_query(query))}請進來源檢視頁看健康狀態或錯誤訊息。</div>'
        body = f"""
<h1>RSS 來源分類</h1>
{notice}
<p class="lede">這裡管理每天會被自動抓取或人工保留追蹤的來源。預設不顯示封存來源；你可以用篩選器切換主線、來源類型和狀態。</p>
<div class="grid">{''.join(overview_cards)}</div>
<h2>篩選來源</h2>
<form class="filter-panel" method="get" action="/sources">
  <div class="form-grid">
    <div>
      <label>主線</label>
      <select name="track">{option_list(track_options, track_filter)}</select>
      <p class="help">用來分開看開放科技、人文與在地知識，或未分類來源。</p>
    </div>
    <div>
      <label>來源類型</label>
      <select name="source_type">{option_list(type_options, type_filter)}</select>
      <p class="help">RSS / Google 快訊 / YouTube / Podcast 會被抓取；Facebook 與 Inoreader 目前保留作對照。</p>
    </div>
    <div>
      <label>狀態</label>
      <select name="status">{option_list(status_options, status_filter)}</select>
      <p class="help">啟用會進入抓取流程；暫停先保留但不抓；封存是歷史資料。</p>
    </div>
  </div>
  <div class="button-row">
    <button type="submit">套用篩選</button>
    <a class="button secondary" href="/sources/new{('?track=' + quote(track_filter)) if track_filter != 'all' else ''}">新增 RSS 來源</a>
    <a class="button quiet" href="/manual-items">單一手動收存網址（{h(str(manual_count))}）</a>
  </div>
  <p class="help">篩選只改變畫面，不會改資料。新增 RSS 才會寫入 database/sources.jsonl；沒有 RSS 的單篇網址請走「單一手動收存網址」。</p>
</form>
<h2>目前列表</h2>
<p class="muted">符合條件：{len(filtered_sources)} 個來源。{''.join(type_summary) if type_summary else ''}</p>
{''.join(source_sections)}
"""
        self.send_html("RSS 來源", body)

    def show_source_view(self, query: dict[str, list[str]]) -> None:
        source_id = form_value(query, "id")
        license_filter = clean_text((query.get("license") or ["all"])[0]) or "all"
        sources = load_jsonl(SOURCES)
        source = next((row for row in sources if row.get("id") == source_id), None)
        if not source:
            self.send_html("找不到來源", "<h1>找不到來源</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return

        items = [item for item in load_jsonl(ITEMS) if item.get("source_id") == source_id]
        candidates = [item for item in load_jsonl(CANDIDATES) if item.get("source_id") == source_id]
        rejected = [item for item in load_jsonl(REJECTED_ITEMS) if item.get("source_id") == source_id]
        dismissed = [item for item in load_jsonl(DISMISSED) if item.get("source_id") == source_id]
        health = source_health_summary(source, load_jsonl(ITEMS), load_jsonl(REJECTED_ITEMS), load_jsonl(CANDIDATES), load_jsonl(DISMISSED))
        license_options = option_list(license_filter_options([*items, *candidates, *rejected, *dismissed]), license_filter)
        if license_filter != "all":
            items = [item for item in items if item_license_name(item) == license_filter]
            candidates = [item for item in candidates if item_license_name(item) == license_filter]
            rejected = [item for item in rejected if item_license_name(item) == license_filter]
            dismissed = [item for item in dismissed if item_license_name(item) == license_filter]

        def sort_items(records: list[dict]) -> list[dict]:
            return sorted(
                records,
                key=lambda item: (item_sort_time(item), item_display_title(item)),
                reverse=True,
            )

        def source_summary(item: dict, archived: bool = False, limit: int = 260) -> str:
            if archived:
                decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
                return clean_text(item.get("reason") or decision.get("reason") or item.get("notes"), limit)
            return item_zh_summary(item, limit)

        def restore_form(item: dict) -> str:
            item_id = clean_text(item.get("id"))
            if not item_id:
                return ""
            return f"""
<form class="chip-form" method="post" action="/sources/restore-item">
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="source_id" value="{h(source_id)}">
  <input type="hidden" name="redirect" value="/sources/view?id={h(quote(source_id))}#source-rejected">
  <button type="submit" class="reason-chip">重新收錄</button>
</form>
"""

        def source_list_row(item: dict, can_open: bool = True, archived: bool = False) -> str:
            kind = item_display_kind(item)
            item_url = clean_text(item.get("url"))
            title = item_display_title(item)
            if archived and item_url:
                title_html = f'<a href="{h(item_url)}" target="_blank" rel="noreferrer">{h(title)}</a>'
            elif can_open:
                title_html = f'<a href="{h(item_detail_href(item))}">{h(title)}</a>'
            else:
                title_html = h(title)
            summary = source_summary(item, archived, 240)
            return f"""
<article class="reader-list-card">
  <div class="reader-list-meta">
    {badge("不收紀錄", "suggest-skip") if archived else badge(content_kind_label(kind), "neutral")}
    {license_badge_html(item)}
    {badge(item_display_time(item, 'published_at', 'captured_at', 'dismissed_at'), "neutral")}
  </div>
  <h3>{title_html}</h3>
  <p class="zh-summary">{h(summary)}</p>
  {f'<div class="source-action-row">{restore_form(item)}</div>' if archived else ''}
</article>
"""

        def source_compact_row(item: dict, can_open: bool = True, archived: bool = False) -> str:
            item_url = clean_text(item.get("url"))
            title = item_display_title(item)
            if archived and item_url:
                title_html = f'<a href="{h(item_url)}" target="_blank" rel="noreferrer">{h(title)}</a>'
            elif can_open:
                title_html = f'<a href="{h(item_detail_href(item))}">{h(title)}</a>'
            else:
                title_html = h(title)
            return f"""
<article class="reader-compact-row">
  <span class="reader-dot" aria-hidden="true"></span>
  <h3>{title_html}</h3>
  <div class="reader-row-tools"><span class="reader-row-time">{h(item_display_time(item, 'published_at', 'captured_at', 'dismissed_at'))}</span>{restore_form(item) if archived else ''}</div>
</article>
"""

        def source_card(item: dict, can_open: bool = True, archived: bool = False) -> str:
            image = item_image_url(item)
            css_class = track_class(item.get("track", source.get("track", "unclassified")))
            thumb = (
                f"<div class='reader-thumb'><img src='{h(image)}' alt=''></div>"
                if image
                else f"<div class='reader-thumb reader-thumb--{h(css_class)}'><span>{h(track_meta(item.get('track', source.get('track', 'unclassified')))['short'])}</span></div>"
            )
            kind = item_display_kind(item)
            item_url = clean_text(item.get("url"))
            title = item_display_title(item)
            if archived and item_url:
                title_html = f'<a href="{h(item_url)}" target="_blank" rel="noreferrer">{h(title)}</a>'
            elif can_open:
                title_html = f'<a href="{h(item_detail_href(item))}">{h(title)}</a>'
            else:
                title_html = h(title)
            return f"""
<article class="card reader-card">
  {thumb}
  <div class="reader-body">
    <div>
      {badge(track_meta(item.get("track", source.get("track", "unclassified")))["short"], css_class)}
      {badge(status_label(item.get("status", "")), "neutral")}
      {badge(content_kind_label(kind), "neutral") if not archived else badge("不收紀錄", "suggest-skip")}
      {license_badge_html(item)}
    </div>
    <h3>{title_html}</h3>
    <p class="muted break-anywhere">{h(item_display_time(item, 'published_at', 'captured_at', 'dismissed_at'))}</p>
    <p class="zh-summary">{h(source_summary(item, archived, 260))}</p>
    {f'<div class="button-row reader-card-actions" aria-label="文章操作"><a class="button reader-action-button" href="{h(item_detail_href(item))}" aria-label="閱讀 / 記錄" title="閱讀 / 記錄">{icon_span("read", "O", "icon reader-action-icon")}{action_label("閱讀 / 記錄")}</a><a class="button secondary reader-action-button" href="{h(item_url)}" target="_blank" rel="noreferrer" aria-label="原始連結" title="原始連結">{icon_span("external", "L", "icon reader-action-icon")}{action_label("原始連結")}</a></div>' if can_open and item_url else ''}
    {f'<div class="source-action-row">{restore_form(item)}</div>' if archived else ''}
  </div>
</article>
"""

        featured = sort_items([item for item in items if item_display_kind(item) in {"featured-article", "opinion-article"}])
        small_news = sort_items([item for item in items if item_display_kind(item) == "small-news" and item.get("status") != "inbox"])
        inbox = sort_items([item for item in items if item.get("status") == "inbox"])
        pending = sort_items(candidates)
        other_items = sort_items([item for item in items if item not in featured and item not in small_news and item not in inbox])
        rejected_records = sort_items([*rejected, *dismissed])

        def section(
            section_id: str,
            title: str,
            description: str,
            records: list[dict],
            empty: str,
            default_layout: str = "list",
            can_open: bool = True,
            archived: bool = False,
        ) -> str:
            empty_html = f'<div class="card"><p class="muted">{h(empty)}</p></div>'
            period_html = ""
            if records:
                period_groups: list[tuple[str, list[dict]]] = []
                period_index: dict[str, int] = {}
                for item in records:
                    label = reader_period_label(item)
                    if label not in period_index:
                        period_index[label] = len(period_groups)
                        period_groups.append((label, []))
                    period_groups[period_index[label]][1].append(item)
                rendered_periods = []
                for label, period_records in period_groups:
                    cards_html = "".join(source_card(item, can_open=can_open, archived=archived) for item in period_records)
                    list_html = "".join(source_list_row(item, can_open=can_open, archived=archived) for item in period_records)
                    compact_html = "".join(source_compact_row(item, can_open=can_open, archived=archived) for item in period_records)
                    rendered_periods.append(
                        f"""
<details class="reader-period-details" id="{h(section_id)}-{h(reader_period_key(period_records[0]))}" open>
  <summary class="reader-period-heading">
    <span class="reader-period-heading-label">{h(label)}</span>
    <span class="reader-period-count">{len(period_records)} 筆</span>
  </summary>
  <div class="reader-grid">{cards_html}</div>
  <div class="reader-list">{list_html}</div>
  <div class="reader-compact-list">{compact_html}</div>
</details>
"""
                    )
                period_html = "".join(rendered_periods)
            return f"""
<section class="reader-layout-section reader-category" id="{h(section_id)}" data-layout="{h(default_layout)}">
  <div class="layout-bar">
    <h2>{h(title)} {help_dot(description)}</h2>
    {layout_toggle(section_id, default_layout)}
  </div>
  {period_html or empty_html}
</section>
"""

        feed_url = clean_text(source.get("feed_url"))
        site_url = clean_text(source.get("site_url"))
        css_class = track_class(source.get("track", "unclassified"))
        notice = ""
        saved = form_value(query, "saved")
        error = form_value(query, "error")
        if saved == "restored":
            notice = '<div class="notice">已重新收錄，項目會回到入庫建檔區。</div>'
        elif saved == "source_fetch":
            notice = f'<div class="notice">已手動更新這個 RSS。{h(source_fetch_summary_from_query(query))}新的項目會進入庫建檔區。</div>'
        elif saved == "source_keywords":
            notice = '<div class="notice">來源已儲存，並已依單一 RSS 關鍵字重盤點與重新抓取。</div>'
        elif error == "source_fetch":
            notice = f'<div class="notice">手動更新沒有成功。{h(source_fetch_summary_from_query(query))}請檢查健康狀態或 feed URL。</div>'
        body = f"""
<h1>{h(source.get("name") or "未命名來源")}</h1>
{notice}
<p class="lede">這裡先看同一個 RSS / 來源底下已收、待整理與不收的內容；要調整抓取頻率、健康狀態或關鍵字，再進編輯頁。</p>
<section class="card track-card track-card--{h(css_class)}">
  <div>
    {badge(track_meta(source.get("track", "unclassified"))["short"], css_class)}
    {badge(source_type_label(source.get("source_type", "manual")), source.get("source_type", "manual").replace("_", "-"))}
  {badge(source_status_label(source.get("status", "")), clean_text(source.get("status", "neutral")).replace("_", "-"))}
    {source_health_badge(health)}
  </div>
  <div class="metric-row">
    {metric_tile(len(featured), "精選 / 觀點", "#source-featured", "看區塊")}
    {metric_tile(len(small_news), "小消息", "#source-small-news", "看區塊")}
    {metric_tile(len(inbox) + len(pending), "待建檔", "#source-inbox", "看區塊")}
    {metric_tile(len(rejected_records), "不收紀錄", "#source-rejected", "看區塊")}
  </div>
  <p class="help">抓取頻率：{h(source_frequency_label(source.get('fetch_frequency', 'daily')))}；健康狀態：{h(health.get('reason'))}</p>
  <p class="muted break-anywhere">{f'Feed：<code>{h(feed_url)}</code><br>' if feed_url else ''}{f'網站：<a href="{h(site_url)}" target="_blank" rel="noreferrer">{h(site_url)}</a>' if site_url else ''}</p>
  <div class="button-row">
    <a class="button secondary" href="/sources/edit?id={quote(source_id)}">編輯 RSS</a>
    <form method="post" action="/sources/fetch" data-source-fetch-form>
      <input type="hidden" name="id" value="{h(source_id)}">
      <input type="hidden" name="redirect" value="/sources/view?id={h(quote(source_id))}">
      <button type="submit" class="secondary">手動更新 RSS</button>
    </form>
    <a class="button quiet" href="/sources?track={quote(source.get('track', 'unclassified'))}">回 RSS 來源</a>
    <form method="get" action="/sources/view" class="inline-select-form">
      <input type="hidden" name="id" value="{h(source_id)}">
      <select name="license" aria-label="授權篩選" onchange="this.form.submit()">{license_options}</select>
    </form>
  </div>
</section>
{publish_page_card("source", source_id, source.get("name") or source_id, clean_text(source.get("description") or ""))}
{section("source-featured", "精選文章與觀點文章", "已確認值得細讀、可能後續撰稿或觀點整理的內容。", featured, "這個來源目前沒有精選文章或觀點文章。", "card")}
{section("source-small-news", "純新聞 / 小消息", "可以快速掃過、查核後短訊處理的內容。", small_news, "這個來源目前沒有小消息。", "list")}
{section("source-inbox", "入庫建檔 / RSS 新進", "還沒完成收或不收判斷的內容，包含已入庫 inbox 和 RSS 新進。", [*inbox, *pending], "這個來源目前沒有入庫建檔項目。", "list")}
{section("source-other", "其他已收項目", "已收但尚未歸入精選、觀點或小消息的內容。", other_items, "這個來源目前沒有其他已收項目。", "list")}
{section("source-rejected", "不收紀錄", "已被標記不收或從入庫建檔區移出的內容，方便判斷這個 RSS 是否該調整或暫停。", rejected_records, "這個來源目前沒有不收紀錄。", "compact", can_open=False, archived=True)}
"""
        self.send_html(str(source.get("name") or "來源內容"), body)

    def show_source_edit(self, query: dict[str, list[str]]) -> None:
        source_id = (query.get("id") or [""])[0]
        source = next((row for row in load_jsonl(SOURCES) if row.get("id") == source_id), None)
        if not source:
            self.send_html("找不到來源", "<h1>找不到來源</h1>", HTTPStatus.NOT_FOUND)
            return
        self.show_source_form(source)

    def show_source_form(self, source: dict) -> None:
        source_id = source.get("id", "")
        title = "編輯來源" if source_id else "新增 RSS 來源"
        current_track = source.get("track", "digital-humanities-local-knowledge")
        if current_track not in TRACK_META:
            current_track = "digital-humanities-local-knowledge"
        current_type = source.get("source_type", "rss")
        current_status = source.get("status", "active")
        current_frequency = normalize_fetch_frequency(source.get("fetch_frequency", "daily"))
        current_group = clean_text(source.get("source_group")) or "Manual RSS"
        existing_sources = load_jsonl(SOURCES)
        current_group_is_new = current_group not in source_group_values(existing_sources)
        group_input_value = current_group if current_group_is_new else ""
        group_input_hidden = "" if current_group_is_new else " hidden"
        health_card = ""
        if source_id:
            health = source_health_summary(
                source,
                load_jsonl(ITEMS),
                load_jsonl(REJECTED_ITEMS),
                load_jsonl(CANDIDATES),
                load_jsonl(DISMISSED),
            )
            rss_health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
            health_card = f"""
<section class="card">
  <h2>健康狀態</h2>
  <p>{source_health_badge(health)}</p>
  <p class="muted">{h(health.get('reason'))}</p>
  <div class="metric-row">
    {metric_tile(health.get('accepted', 0), "已收下", f"/sources/view?id={quote(source_id)}#source-featured", "看已收")}
    {metric_tile(health.get('inbox', 0) + health.get('candidates', 0), "待整理", f"/sources/view?id={quote(source_id)}#source-inbox", "看待整理")}
    {metric_tile(health.get('rejected', 0), "不收 / 刪除", f"/sources/view?id={quote(source_id)}#source-rejected", "看不收")}
    {metric_tile(health.get('duplicate_skips', 0), "近次重複略過")}
  </div>
  <p class="help">最近檢查：{h(health.get('last_checked_at') or '尚未記錄')}；最近資料：{h(health.get('last_seen') or '尚未記錄')}；最近抓取狀態：{h(rss_health.get('last_fetch_status') or '尚未記錄')}。</p>
</section>
"""
        body = f"""
<h1>{h(title)}</h1>
<p class="lede">用在你想長期追蹤一個網站、Google 快訊、YouTube 頻道或 Podcast 時。RSS / Google 快訊 / YouTube / Podcast 會被排程或手動抓取流程處理。</p>
{health_card}
<form class="form-panel" method="post" action="/sources" data-url-preview-form data-preview-kind="source">
  <input type="hidden" name="id" value="{h(source_id)}">
  <label>主線</label>
  <select name="track" data-preview-track>{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定來源會出現在開放科技、人文與在地知識，或未分類清單。</p>
  <label>名稱</label>
  <input name="name" value="{h(source.get('name', ''))}" required data-preview-title>
  <p class="help">填你看得懂的短名稱，例如網站名、作者名或頻道名。</p>
  <label>來源分類</label>
  <div data-source-group-field>
    <select name="source_group_choice" data-source-group-select>{source_group_options(existing_sources, current_group)}</select>
    <input name="source_group_new" value="{h(group_input_value)}" placeholder="輸入新的來源分類" data-source-group-new{group_input_hidden}>
  </div>
  <p class="help">優先選既有分類；只有真的要新增分類時才改用手打。來源列表會用這個分組。</p>
  <label>來源類型</label>
  <select name="source_type" data-preview-source-type>{source_type_options(current_type)}</select>
  <p class="help">{h(SOURCE_TYPE_HELP.get(current_type, "RSS / Google 快訊 / YouTube / Podcast 會被自動抓；其他類型目前用來保留脈絡。"))}</p>
  <label>狀態</label>
  <select name="status">{source_status_options(current_status)}</select>
  <p class="help">啟用會依抓取頻率進入排程或手動更新；暫停會保留但不抓；封存代表這個來源暫時不再顯示。</p>
  <label>抓取頻率</label>
  <select name="fetch_frequency">{source_frequency_options(current_frequency)}</select>
  <p class="help">排程會依最近一次成功抓取時間判斷每 1 小時、每 6 小時、每天、每週或每月是否到期；按更新時抓只會在首頁 RSS 更新或單一來源手動更新時處理；暫停抓取則保留來源但不抓。</p>
  <label>Feed URL</label>
  <input name="feed_url" value="{h(source.get('feed_url', ''))}" placeholder="https://example.com/feed.xml" data-preview-url data-preview-feed-url>
  <p class="help">RSS / Google 快訊 / YouTube / Podcast 請填這欄。Facebook、舊 Inoreader monitor 或既有表格來源可以留空作為紀錄。</p>
  <label>Site URL</label>
  <input name="site_url" value="{h(source.get('site_url', ''))}" placeholder="https://example.com/" data-preview-site-url>
  <p class="help">原始網站首頁，方便之後回去確認來源脈絡。</p>
  <div class="preview-panel" data-preview-panel hidden>
    <div class="preview-status" data-preview-status>等待網址。</div>
    <div class="preview-result" data-preview-result></div>
  </div>
  <button type="button" class="secondary" data-preview-button>{button_content("抓取來源資訊", "rss", "R")}</button>
  <label>必須包含的關鍵字</label>
  <textarea name="required_keywords" placeholder="一行一個；留空代表不限制">{h(source_keywords_text(source, 'required_keywords'))}</textarea>
  <p class="help">若有填，RSS 單篇標題、摘要、標籤、來源或網址至少要命中其中一個才會進入庫建檔區；編輯後存檔會重盤點這個來源的入庫建檔項目並重新抓一次。</p>
  <label>不能包含的關鍵字</label>
  <textarea name="excluded_keywords" placeholder="一行一個；留空代表不限制">{h(source_keywords_text(source, 'excluded_keywords'))}</textarea>
  <p class="help">命中這裡的單篇會在 RSS 抓取階段直接略過；若是既有待整理或候選，存檔重盤點時會以「{h(SOURCE_KEYWORD_EXCLUSION_REASON)}」移到不收紀錄。</p>
  <label>備註</label>
  <textarea name="notes">{h(source.get('notes', ''))}</textarea>
  <p class="help">可以寫為什麼要追、頻率如何、是不是從 Inoreader 舊流程轉來。</p>
  <button type="submit">儲存這個來源</button>
  <p class="help">送出後會寫進 database/sources.jsonl。要抓新資料，可以在來源列表或來源頁按「更新」。</p>
</form>
"""
        self.send_html(title, body)

    def save_source(self, data: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        existing_id = form_value(data, "id")
        existing_source = next((source for source in sources if source.get("id") == existing_id), {}) if existing_id else {}
        source_group = source_group_from_form(data)
        track = form_value(data, "track", "unclassified")
        group_order = source_group_order_for(sources, track, source_group)
        if group_order is None and existing_source.get("source_group") == source_group:
            group_order = source_group_order_value(existing_source)
        if group_order is None:
            group_order = next_source_group_order(sources, track)
        record = {
            "id": existing_id or stable_id("src", source_group, form_value(data, "name"), form_value(data, "feed_url")),
            "track": track,
            "name": form_value(data, "name"),
            "source_group": source_group,
            "source_group_order": group_order,
            "source_type": form_value(data, "source_type", "rss"),
            "fetch_frequency": normalize_fetch_frequency(form_value(data, "fetch_frequency", "daily")),
            "feed_url": form_value(data, "feed_url"),
            "site_url": form_value(data, "site_url"),
            "status": form_value(data, "status", "active"),
            "required_keywords": form_lines(form_value(data, "required_keywords")),
            "excluded_keywords": form_lines(form_value(data, "excluded_keywords")),
            "notes": form_value(data, "notes"),
        }
        keywords_changed = bool(existing_id) and source_keyword_signature(existing_source) != source_keyword_signature(record)
        for preserved_key in ["rss_health", "health_assessment", "last_fetched_at"]:
            if preserved_key in existing_source:
                record[preserved_key] = existing_source[preserved_key]
        if existing_id:
            sources = [record if source.get("id") == existing_id else source for source in sources]
        else:
            if record["feed_url"] and any(source.get("feed_url") == record["feed_url"] for source in sources):
                self.send_html("已存在", f"<h1>這個 RSS 已存在</h1><p>{h(record['feed_url'])}</p><p><a href='/sources'>回來源列表</a></p>")
                return
            sources.append(record)
        sources.sort(key=lambda row: (row.get("source_group", ""), row.get("name", ""), row.get("id", "")))
        write_jsonl(SOURCES, sources)
        if keywords_changed:
            stats = self.rescan_source_keyword_exclusions(record)
            fetch_ok, _output = self.run_source_fetch(record["id"])
            query = urlencode(
                {
                    "id": record["id"],
                    "saved": "source_keywords" if fetch_ok else "source_keywords",
                    "excluded_items": str(stats.get("items", 0)),
                    "excluded_candidates": str(stats.get("candidates", 0)),
                    "fetch": "ok" if fetch_ok else "failed",
                }
            )
            self.redirect(f"/sources/view?{query}")
            return
        self.redirect(f"/sources?track={quote(record['track'])}")

    def show_integrity(self, query: dict[str, list[str]]) -> None:
        report = database_integrity_report()
        issues = report["issues"]
        message = clean_text(unquote((query.get("msg") or [""])[0]))
        flash = f"<div class='notice'>{h(message)}</div>" if message else ""
        if not issues:
            body = (
                "<h1>資料庫健檢</h1>"
                "<p class='lede'>檢查可用材料區與已退件有沒有重複 id，以及審查事件是否指向已不存在的項目。送 PR 前這頁是綠的就沒問題。</p>"
                f"{flash}"
                "<div class='card'><strong>✓ 資料庫健檢通過</strong>"
                "<p class='muted'>目前沒有重複項目，也沒有孤兒審查事件。</p></div>"
                "<p><a class='button quiet' href='/'>回總覽</a></p>"
            )
            self.send_html("資料庫健檢", body)
            return
        cards = "".join(render_integrity_issue(issue) for issue in issues)
        body = (
            "<h1>資料庫健檢</h1>"
            f"<p class='lede'>找到 {len(issues)} 個需要你決斷的問題。每張卡片的按鈕按下去就會直接修好，並回到這頁重新檢查；標「（建議）」的是我推薦的處理方式。</p>"
            f"{flash}"
            f"<div class='grid'>{cards}</div>"
            "<p><a class='button quiet' href='/'>回總覽</a></p>"
        )
        self.send_html("資料庫健檢", body)

    @with_db_write_lock
    def apply_integrity_fix(self, issue_type: str, target_id: str, action: str) -> dict:
        if not target_id:
            return {"ok": False, "message": "缺少要處理的項目 id。"}
        if issue_type == "duplicate_item":
            if action == "keep_active":
                removed = remove_jsonl_ids(REJECTED_ITEMS, {target_id})
                if removed:
                    return {"ok": True, "message": f"已把 {target_id} 保留為可用材料，並從已退件移除。"}
                return {"ok": False, "message": "找不到對應的已退件紀錄，可能已處理過。"}
            if action == "keep_rejected":
                removed = remove_jsonl_ids(ITEMS, {target_id})
                if removed:
                    return {"ok": True, "message": f"已確定退件 {target_id}，從可用材料區移除並保留退件學習檔。"}
                return {"ok": False, "message": "找不到對應的可用材料紀錄，可能已處理過。"}
            return {"ok": False, "message": "未知的處理方式。"}
        if issue_type == "orphan_review":
            if action == "drop_event":
                removed = remove_jsonl_ids(REVIEW_EVENTS, {target_id})
                if removed:
                    return {"ok": True, "message": f"已移除孤兒審查事件 {target_id}。"}
                return {"ok": False, "message": "找不到對應的審查事件，可能已處理過。"}
            return {"ok": False, "message": "未知的處理方式。"}
        return {"ok": False, "message": "未知的健檢項目類型。"}

    def apply_integrity_fix_request(self, data: dict[str, list[str]]) -> None:
        issue_type = clean_text(form_value(data, "issue_type"))
        target_id = clean_text(form_value(data, "target_id"))
        action = clean_text(form_value(data, "action"))
        result = self.apply_integrity_fix(issue_type, target_id, action)
        message = result.get("message") or ("已處理。" if result.get("ok") else "沒有變更。")
        if self.is_async_request():
            report = database_integrity_report()
            self.send_json({"ok": bool(result.get("ok")), "message": message, "count": report["count"]})
            return
        self.redirect(f"/integrity?msg={quote(message)}")

    def run_command(self, data: dict[str, list[str]]) -> None:
        command_name = form_value(data, "command")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        config = COMMANDS.get(command_name)
        if not config:
            if wants_json:
                self.send_json({"ok": False, "error": "不允許的指令"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_html("不允許的指令", "<h1>不允許的指令</h1>", HTTPStatus.BAD_REQUEST)
            return
        if config.get("internal") == "commit_database_state":
            result = commit_database_state("manual")
            ok = result.get("state") in {"committed", "no-changes"}
            output = "\n".join(
                line
                for line in [
                    clean_text(result.get("message")),
                    f"commit: {clean_text(result.get('commit'))}" if result.get("commit") else "",
                    f"message: {clean_text(result.get('commit_message'))}" if result.get("commit_message") else "",
                    clean_text(result.get("output")),
                ]
                if line
            )
            if wants_json:
                self.send_json(
                    {
                        "ok": ok,
                        "label": config["label"],
                        "command": ["internal", "commit_database_state"],
                        "returncode": 0 if ok else 1,
                        "output": output or "(沒有變更需要 commit)",
                    },
                    HTTPStatus.OK,
                )
                return
            body = f"""
<h1>{h(config['label'])}</h1>
<p class="muted">狀態：{h(result.get('state'))}</p>
<pre>{h(output or '(沒有變更需要 commit)')}</pre>
<p><a href="/">回總覽</a></p>
"""
            self.send_html(str(config["label"]), body)
            return
        command = list(config["command"])
        requested_provider = clean_text(form_value(data, "provider")).casefold()
        active_provider = ""
        if requested_provider in {*AI_PROVIDER_META.keys(), "random"} and "--provider" in command:
            idx = command.index("--provider")
            if idx + 1 < len(command):
                command[idx + 1] = requested_provider
                active_provider = requested_provider
        write_json(
            COMMAND_STATUS,
            {
                "command": command_name,
                "state": "running",
                "message": f"正在執行：{config['label']}",
                "started_at": now_iso(),
            },
        )
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=int(config.get("timeout", 600)))
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(
                command,
                124,
                stdout=clean_text(exc.stdout or ""),
                stderr=(clean_text(exc.stderr or "") + "\n指令逾時。").strip(),
            )
        output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        ok = result.returncode == 0
        response_returncode = result.returncode
        status_extra: dict[str, object] = {}
        if ok and command_name == "render_ghpages_reader":
            online_commit = commit_online_reader_output()
            commit_output = "\n".join(
                line
                for line in [
                    clean_text(online_commit.get("message")),
                    f"commit: {clean_text(online_commit.get('commit'))}" if online_commit.get("commit") else "",
                    f"message: {clean_text(online_commit.get('commit_message'))}" if online_commit.get("commit_message") else "",
                    clean_text(online_commit.get("output")),
                ]
                if line
            )
            output = "\n\n".join(part for part in [output.strip(), "線上版 commit：\n" + (commit_output or "(沒有變更需要 commit)")] if part)
            status_extra = {
                "online_reader_commit_state": online_commit.get("state"),
                "online_reader_commit": online_commit.get("commit"),
                "online_reader_commit_message": online_commit.get("commit_message"),
            }
            if online_commit.get("state") == "failed":
                ok = False
                response_returncode = int(online_commit.get("returncode") or 1)
        write_json(
            COMMAND_STATUS,
            {
                "command": command_name,
                "state": "done" if ok else "failed",
                "message": "完成" if ok else "執行失敗",
                "returncode": response_returncode,
                "finished_at": now_iso(),
                **status_extra,
            },
        )
        if wants_json:
            self.send_json(
                {
                    "ok": ok,
                    "label": config["label"],
                    "command": command,
                    "provider": active_provider,
                    "returncode": response_returncode,
                    "output": output,
                },
                HTTPStatus.OK,
            )
            return
        body = f"""
<h1>{h(config['label'])}</h1>
<p class="muted">Exit code: {response_returncode}</p>
<p><code>{h(' '.join(command))}</code></p>
<pre>{h(output)}</pre>
<p><a href="/">回總覽</a></p>
"""
        self.send_html(str(config["label"]), body)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local web UI for Ian Open News")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--port-scan-count", type=int, default=20, help="How many ports to try when the requested port is already in use.")
    args = parser.parse_args()

    server = None
    last_error = None
    for offset in range(max(1, args.port_scan_count)):
        port = args.port + offset
        try:
            server = ThreadingHTTPServer((args.host, port), Handler)
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            last_error = exc
            continue
    if server is None:
        end_port = args.port + max(1, args.port_scan_count) - 1
        raise SystemExit(f"Ports {args.port}-{end_port} are already in use. Last error: {last_error}")

    host = server.server_address[0]
    port = server.server_address[1]
    url = f"http://{host}:{port}"
    if port != args.port:
        print(f"Port {args.port} is in use; using {port} instead.")
    print(f"Local web UI running at {url}")
    start_data_autocommit_worker()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping")


if __name__ == "__main__":
    main()
