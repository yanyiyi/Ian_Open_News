#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import html
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
import hashlib

from page_metadata import enrich_item_metadata


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
SOURCES = DATABASE / "sources.jsonl"
ITEMS = DATABASE / "items.jsonl"
REVIEW_EVENTS = DATABASE / "review-events.jsonl"
TRIAGE_KEYWORDS = DATABASE / "triage-keywords.json"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
DISMISSED = ROOT / ".cache" / "rss-dismissed.jsonl"

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
SOURCE_TYPES = ["rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor", "spreadsheet", "manual"]
SOURCE_STATUSES = ["active", "paused", "archived"]
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
DEFAULT_REJECTION_REASONS = [
    "資料太舊",
    "已經是建議不要看",
    "和兩條主線關聯太弱。",
    "內容偏活動公告或宣傳，暫不整理。",
    "來源重複，已由其他資料涵蓋。",
    "資訊過舊或缺少可查證來源。",
    "只是短訊或碎片，不足以形成文章。",
    "其他類型文章",
]

COMMANDS = {
    "fetch_rss": {
        "label": "立刻抓 RSS 候選",
        "description": "先抓到本機候選清單，不直接寫進正式資料庫；抓完會接著用 Codex 補閱讀建議、三個理由與中文摘要。",
        "button": "抓到候選清單",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "local_rss_daily.py"),
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
        "description": "把目前候選清單和待整理 inbox 重新套用關鍵字、過去不收紀錄與過去收錄類型。這是本機規則判斷，不是 Codex 生成摘要。",
        "button": "更新初篩建議",
        "command": [sys.executable, str(ROOT / "scripts" / "apply_triage_keywords.py")],
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
    "enrich_reader_metadata": {
        "label": "補閱讀卡圖片、描述與主文",
        "description": "連到閱讀區文章的原始網址，抓封面圖、標題、描述與可抽取的原始主文，讓卡片比較像線上報，也讓單篇頁能閱讀全文。",
        "button": "補閱讀區資料",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "enrich_reading_metadata.py"),
            "--reader-only",
            "--only-missing-image",
            "--limit",
            "40",
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
        "label": "用 Codex 補閱讀建議與摘要",
        "description": "針對 RSS 暫存、待整理與閱讀區中還沒有 Codex review 的項目，產生給 Ian 的一句話推薦、三個閱讀理由、中文標題與中文摘要。",
        "button": "補 Codex 建議",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "codex_enrich_reviews.py"),
            "--target",
            "both",
            "--workflow-scope",
            "--limit",
            "18",
            "--batch-size",
            "6",
        ],
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


def h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = path.exists() and path.stat().st_size > 0
    if needs_newline:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            needs_newline = handle.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def is_fetchable_source(source: dict) -> bool:
    return (
        source.get("status") == "active"
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


def badge(label: str, class_name: str = "neutral") -> str:
    return f'<span class="badge badge--{h(class_name)}">{h(label)}</span>'


def command_card(name: str, config: dict) -> str:
    return (
        "<div class='card command-card'>"
        f"<strong>{h(config['label'])}</strong>"
        f"<p class='muted'>{h(config['description'])}</p>"
        "<form method='post' action='/commands/run'>"
        f"<input type='hidden' name='command' value='{h(name)}'>"
        f"<button type='submit' class='secondary'>{h(config['button'])}</button>"
        "</form>"
        "</div>"
    )


def remove_local_candidate_fields(record: dict) -> dict:
    item = dict(record)
    item.pop("candidate_status", None)
    return item


def candidate_recommendation(candidate: dict) -> str:
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
    keywords = set(triage.get("matched_keywords") or [])
    keywords.update(triage.get("skip_keywords") or [])
    return {str(keyword) for keyword in keywords if str(keyword).strip()}


def recommendation_label(recommendation: str) -> str:
    if recommendation == "suggest-keep":
        return "建議收"
    if recommendation == "suggest-skip":
        return "建議不要看"
    return "未判斷"


def editorial_recommendation_label(recommendation: str) -> str:
    if recommendation == "suggest-collect":
        return "建議收錄"
    if recommendation == "suggest-review":
        return "建議人工看過"
    if recommendation == "suggest-skip":
        return "建議不要看"
    return "尚未初篩"


def content_kind_label(kind: str) -> str:
    if kind == "featured-article":
        return "精選文章 / 待跑 skill"
    if kind == "small-news":
        return "純新聞 / 小消息"
    return "人工判斷"


def status_label(status: str) -> str:
    labels = {
        "inbox": "待整理",
        "triaged": "待跑 skill",
        "researching": "補來源中",
        "drafting": "撰稿中",
        "reviewing": "審稿中",
        "fact-checking": "查核中",
        "ready": "可送 PR / 可讀",
        "published": "已發布",
        "archived": "封存",
    }
    return labels.get(status, status or "未標示")


def editorial_badge_class(recommendation: str) -> str:
    if recommendation == "suggest-collect":
        return "suggest-keep"
    if recommendation == "suggest-review":
        return "neutral"
    if recommendation == "suggest-skip":
        return "suggest-skip"
    return "neutral"


def item_detail_href(item: dict) -> str:
    return f"/items/view?id={quote(str(item.get('id', '')))}"


def personal_note_text(item: dict) -> str:
    notes = item.get("personal_notes")
    if isinstance(notes, dict):
        return clean_text(notes.get("body"))
    return clean_text(notes)


def item_zh_summary(item: dict, limit: int = 420) -> str:
    editorial = item.get("editorial_triage") or {}
    if isinstance(editorial, dict):
        codex_review = editorial.get("codex_review")
        if isinstance(codex_review, dict):
            text = "\n\n".join(
                part
                for part in [
                    clean_text(codex_review.get("one_line_recommendation")),
                    clean_text(codex_review.get("summary")),
                ]
                if part
            )
            if text:
                return clean_text(text, limit)
        text = clean_text(editorial.get("zh_summary"), limit)
        if text:
            return text
    return clean_text(item.get("summary"), limit)


def item_codex_review(item: dict) -> dict:
    editorial = item.get("editorial_triage") or {}
    if not isinstance(editorial, dict):
        return {}
    review = editorial.get("codex_review")
    return review if isinstance(review, dict) else {}


def item_reading_metadata(item: dict) -> dict:
    metadata = item.get("reading_metadata")
    return metadata if isinstance(metadata, dict) else {}


def item_article_text(item: dict) -> str:
    return clean_text(item_reading_metadata(item).get("article_text"))


def item_image_url(item: dict) -> str:
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


def is_reader_item(item: dict) -> bool:
    if item.get("status") in {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}:
        return True
    decision = item.get("local_decision") or {}
    return isinstance(decision, dict) and decision.get("action") in {"accepted-for-editing", "direct-pr-small-news"}


def editorial_triage_html(item: dict, compact: bool = False) -> str:
    editorial = item.get("editorial_triage") or {}
    if not isinstance(editorial, dict):
        editorial = {}
    recommendation = editorial.get("recommendation", "")
    kind = editorial.get("content_kind", "")
    confidence = editorial.get("confidence", "")
    if not editorial:
        return "<p class='help'>自動規則判斷：尚未重跑。可到首頁或關鍵字頁按「重新跑本機規則/關鍵字初篩」。</p>"
    display_kind = item_display_kind(item)
    codex_review = item_codex_review(item)
    codex_html = ""
    if codex_review:
        one_line = clean_text(codex_review.get("one_line_recommendation"), 420)
        summary = clean_text(codex_review.get("summary"), 900)
        reasons = codex_review.get("reasons") or []
        reason_rows = "<ol class='reason-list'>" + "".join(f"<li>{h(reason)}</li>" for reason in reasons[:3]) + "</ol>" if reasons and not compact else ""
        summary_html = f"<p class='zh-summary'>{h(summary)}</p>" if summary and not compact else ""
        codex_html = (
            "<div class='source-card source-card--model'>"
            "<div class='section-kicker'>Codex 生成</div>"
            "<h3>給 Ian 的閱讀建議</h3>"
            f"{badge('來源：Codex', 'suggest-keep')}"
            f"{badge('依主文生成' if codex_review.get('used_article_text') else '依既有資料生成', 'neutral')}"
            f"{badge(str(codex_review.get('generated_at', '')), 'neutral') if codex_review.get('generated_at') and not compact else ''}"
            f"<p class='recommendation-line'>{h(one_line)}</p>"
            f"{reason_rows}"
            f"{summary_html}"
            "</div>"
        )
    elif not compact:
        codex_html = (
            "<div class='source-card source-card--model source-card--empty'>"
            "<div class='section-kicker'>Codex 生成</div>"
            "<h3>給 Ian 的閱讀建議</h3>"
            "<p class='help'>這則還沒有 Codex 生成摘要。首頁的「用本機規則重抓待整理摘要」只會更新規則摘要；需要真正模型文字時可請 Codex 針對這則生成。</p>"
            "</div>"
        )

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

    reasons = editorial.get("view_reasons") or []
    reason_rows = ""
    if reasons and not compact:
        reason_rows = "<ol class='reason-list'>" + "".join(f"<li>{h(reason)}</li>" for reason in reasons[:3]) + "</ol>"
    deletion = editorial.get("deletion_pattern_fit") or {}
    deletion_signals = deletion.get("signals") or []
    deletion_html = ""
    if recommendation == "suggest-skip" and deletion_signals and not compact:
        deletion_html = f"<p class='help'>不要看的線索：{h('；'.join(deletion_signals[:3]))}</p>"
    zh_summary = clean_text(editorial.get("zh_summary"), 620)
    zh_summary_html = f"<p class='zh-summary'>{h(zh_summary)}</p>" if zh_summary and not compact and not codex_review else ""
    rule_html = (
        "<div class='source-card source-card--rules'>"
        "<div class='section-kicker'>自動規則判斷</div>"
        "<h3>關鍵字與過往資料的判斷</h3>"
        f"{badge(editorial_recommendation_label(recommendation), editorial_badge_class(recommendation))}"
        f"{badge(content_kind_label(display_kind), 'neutral')}"
        f"{badge('信心 ' + confidence, 'neutral') if confidence else ''}"
        f"{zh_summary_html}"
        f"<p class='help'>初步判斷：{h(editorial.get('summary_reason', '未標示'))}<br>"
        f"下一步：{h(editorial.get('next_step_hint', '人工判斷下一步。'))}</p>"
        f"{reason_rows}{deletion_html}"
        "</div>"
    )
    return f"<div class='source-stack'>{codex_html}{source_html}{rule_html}</div>"


def append_review_note(review: dict, note: str) -> dict:
    updated = dict(review or default_review())
    current_notes = clean_text(updated.get("notes"))
    updated["notes"] = f"{current_notes}\n{note}".strip() if current_notes else note
    return updated


def rejection_reason_options(items: list[dict]) -> list[str]:
    counts: Counter[str] = Counter()
    for item in items:
        decision = item.get("local_decision") or {}
        if decision.get("action") == "rejected" and decision.get("reason"):
            reason = clean_text(decision["reason"], 90)
            reason = re.sub(r"\s+", " ", reason).strip()
            if reason:
                counts[reason] += 1
    options = [reason for reason, _ in counts.most_common(8)]
    for reason, _ in counts.most_common(8):
        if reason and reason not in options:
            options.append(reason)
    for reason in DEFAULT_REJECTION_REASONS:
        if reason and reason not in options:
            options.append(reason)
    return options


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


def inline_reject_buttons(item_id: str, reasons: list[str], limit: int = 7) -> str:
    buttons = []
    for reason in reasons[:limit]:
        buttons.append(
            f"""
<form class="chip-form" method="post" action="/items/reject" data-decision-form>
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="reason" value="{h(reason)}">
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
            f"- 理由：{triage.get('reason', '未標示')}",
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
    :root {{
      --ocf-primary: #6450dc;
      --ocf-light: #d7dcf0;
      --ocf-dark: #0f1923;
      --ocf-white: #ffffff;
      --ocf-cyan: #0091da;
      --ocf-magenda: #ce0058;
      --bg: #f5f6fb;
      --ink: var(--ocf-dark);
      --muted: #5f6877;
      --line: #c9d0e5;
      --panel: var(--ocf-white);
      --soft: #eef1fb;
      --accent: var(--ocf-primary);
      --humanities: var(--ocf-dark);
      --danger: #9f2525;
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
      z-index: 10;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    nav a {{
      color: var(--ocf-dark);
      text-decoration: none;
      font-weight: 750;
      padding: 7px 10px;
      border-radius: 6px;
      transition: background .16s ease, color .16s ease, transform .16s ease;
    }}
    nav a:hover {{ background: var(--soft); color: var(--ocf-primary); transform: translateY(-1px); }}
    h1 {{ font-size: 28px; margin: 0 0 12px; }}
    h2 {{ font-size: 20px; margin: 30px 0 12px; }}
    h3 {{ font-size: 16px; margin: 0 0 8px; }}
    p {{ margin: 8px 0; }}
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
    .metric-row {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
    .metric {{
      font-size: 27px;
      font-weight: 850;
      color: var(--track-color, var(--accent));
      line-height: 1.1;
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; }}
    .muted {{ color: var(--muted); }}
    .help {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}
    form {{ margin: 0; }}
    .form-panel, .filter-panel {{ padding: 18px; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
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
      transform: translateY(-1px);
      box-shadow: 0 6px 14px rgba(15,25,35,.16);
      filter: brightness(1.03);
    }}
    button:active, .button:active {{ transform: translateY(0); box-shadow: 0 2px 6px rgba(15,25,35,.14); }}
    .button-row {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start; }}
    .button-row .button, .button-row button {{ margin-top: 0; }}
    .button-opentech {{ background: var(--ocf-primary); }}
    .button-humanities {{ background: var(--humanities); }}
    .secondary {{ background: var(--ocf-cyan); }}
    .quiet {{ background: var(--ocf-dark); }}
    input[type="checkbox"] {{ width: auto; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; table-layout: fixed; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ background: var(--soft); color: var(--muted); font-size: 13px; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef1fb; padding: 2px 5px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; background: #162024; color: #eaf1ec; padding: 16px; border-radius: 8px; overflow: auto; }}
    .notice {{ border-left: 4px solid var(--ocf-primary); padding: 10px 14px; background: #eef1fb; border-radius: 6px; margin-bottom: 18px; }}
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
    .source-group {{ margin-bottom: 14px; overflow: hidden; }}
    .source-group summary {{
      cursor: pointer;
      padding: 13px 14px;
      font-weight: 850;
      background: var(--soft);
      border-bottom: 1px solid var(--line);
    }}
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
    .decision-panel {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .reason-presets {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }}
    .reason-presets button {{ margin-top: 0; }}
    .batch-panel {{ border-left: 4px solid var(--ocf-cyan); }}
    .keyword-filters {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
    .keyword-option {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ocf-dark);
      font-size: 12px;
      font-weight: 750;
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
    .reason-chip:hover {{ box-shadow: 0 4px 10px rgba(15,25,35,.12); }}
    .reason-chip--danger {{
      border-color: #f1bfd3;
      background: #fff0f6;
      color: var(--ocf-magenda);
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
    .command-output {{ margin-top: 16px; }}
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
    .reader-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
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
    .item-hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
      gap: 18px;
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
    .item-image img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .note-box {{
      border-left: 4px solid var(--ocf-cyan);
      background: #f7fbfe;
      padding: 10px 12px;
      border-radius: 8px;
    }}
    .fulltext-panel[hidden] {{ display: none; }}
    .article-text {{
      white-space: pre-wrap;
      max-height: 64vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fff;
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
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; padding: 14px 18px; }}
      main {{ padding: 20px 16px; }}
      .two-column {{ grid-template-columns: 1fr; }}
      .item-hero {{ grid-template-columns: 1fr; }}
      .metric-row {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header>
    <a class="brand" href="/">Ian Open News</a>
    <nav>
      <a href="/">共通入口</a>
      <a href="/track/open-tech-open-industry">開放科技</a>
      <a href="/track/digital-humanities-local-knowledge">人文知識</a>
      <a href="/items">待整理</a>
      <a href="/candidates">候選清單</a>
      <a href="/reader">閱讀區</a>
      <a href="/rss-candidates">RSS 暫存</a>
      <a href="/keywords">關鍵字</a>
      <a href="/sources">RSS 來源</a>
      <a href="/items/new">加收藏</a>
      <a href="/sources/new">加 RSS</a>
    </nav>
  </header>
  <main>{body}</main>
  <div class="loading-overlay" id="read-more-loading" aria-live="polite" aria-hidden="true">
    <div class="loading-card">
      <strong>正在載入原始主文</strong>
      <p class="muted">會從原始網址往下抓全文，完成後寫進閱讀資料庫，並在畫面展開「原始主文」。</p>
      <div class="loading-dots" aria-label="載入中"><span></span><span></span><span></span></div>
    </div>
  </div>
  <script>
  document.querySelectorAll("form[data-read-more-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const overlay = document.getElementById("read-more-loading");
      if (overlay) {{
        overlay.classList.add("is-visible");
        overlay.setAttribute("aria-hidden", "false");
      }}
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      try {{
        const response = await fetch(form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        if (!payload.ok) throw new Error(payload.error || "read more failed");
        const targetSelector = form.getAttribute("data-target") || "#fulltext-panel";
        const panel = document.querySelector(targetSelector);
        if (panel) {{
          panel.hidden = false;
          const body = panel.querySelector("[data-fulltext-body]");
          const meta = panel.querySelector("[data-fulltext-meta]");
          if (body) body.textContent = payload.article_text || "這次沒有抓到可顯示的主文。";
          if (meta) meta.textContent = payload.message || "";
          panel.scrollIntoView({{ behavior: "smooth", block: "start" }});
        }} else if (payload.redirect) {{
          window.location.href = payload.redirect;
        }}
      }} catch (error) {{
        const redirect = form.querySelector("input[name='redirect']")?.value || window.location.pathname + window.location.search;
        const separator = redirect.includes("?") ? "&" : "?";
        window.location.href = redirect + separator + "error=read_more";
      }} finally {{
        if (overlay) {{
          overlay.classList.remove("is-visible");
          overlay.setAttribute("aria-hidden", "true");
        }}
      }}
    }});
  }});
  </script>
</body>
</html>"""
    return html_doc.encode("utf-8")


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

    def redirect(self, path: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
        self.end_headers()

    def is_async_request(self) -> bool:
        return self.headers.get("X-Requested-With") == "local-web-fetch"

    def send_no_content(self, status: HTTPStatus = HTTPStatus.NO_CONTENT) -> None:
        self.send_response(status)
        self.end_headers()

    def read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return parse_qs(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            self.show_home(query)
        elif parsed.path.startswith("/track/"):
            self.show_track(parsed.path.removeprefix("/track/"))
        elif parsed.path == "/candidates":
            self.show_candidates(query)
        elif parsed.path == "/reader":
            self.show_reader(query)
        elif parsed.path == "/rss-candidates":
            self.show_rss_candidates(query)
        elif parsed.path == "/keywords":
            self.show_keywords()
        elif parsed.path == "/items":
            self.show_items(query)
        elif parsed.path == "/items/view":
            self.show_item_detail(query)
        elif parsed.path == "/items/reject":
            self.show_item_reject_form(query)
        elif parsed.path == "/items/new":
            self.show_item_form(query)
        elif parsed.path == "/sources":
            self.show_sources(query)
        elif parsed.path == "/sources/new":
            self.show_source_form({"track": (query.get("track") or ["digital-humanities-local-knowledge"])[0]})
        elif parsed.path == "/sources/edit":
            self.show_source_edit(query)
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/items":
            self.save_item(self.read_form())
        elif parsed.path == "/items/accept":
            self.accept_item(self.read_form())
        elif parsed.path == "/items/direct-pr":
            self.direct_pr_item(self.read_form())
        elif parsed.path == "/items/reject":
            self.reject_item(self.read_form())
        elif parsed.path == "/items/batch":
            self.batch_items(self.read_form())
        elif parsed.path == "/items/personal-note":
            self.save_personal_note(self.read_form())
        elif parsed.path == "/items/requeue-skill":
            self.requeue_skill_item(self.read_form())
        elif parsed.path == "/items/read-more":
            self.read_more_item(self.read_form())
        elif parsed.path == "/candidates/accept":
            self.accept_candidate(self.read_form())
        elif parsed.path == "/candidates/dismiss":
            self.dismiss_candidate(self.read_form())
        elif parsed.path == "/keywords":
            self.save_keywords(self.read_form())
        elif parsed.path == "/sources":
            self.save_source(self.read_form())
        elif parsed.path == "/commands/run":
            self.run_command(self.read_form())
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    def show_home(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        candidates = load_jsonl(CANDIDATES)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        skill_candidates = [item for item in items if is_skill_candidate(item)]
        direct_pr_items = [item for item in items if is_direct_pr_item(item)]
        reader_items = [item for item in items if is_reader_item(item)]
        inbox_counts = Counter(candidate_recommendation(item) for item in inbox_items)
        keep_candidates = [candidate for candidate in candidates if candidate_recommendation(candidate) == "suggest-keep"]
        skip_candidates = [candidate for candidate in candidates if candidate_recommendation(candidate) == "suggest-skip"]
        notice = ""
        if query.get("saved"):
            notice = '<div class="notice">已儲存。</div>'
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
            inbox_items = count_items(items, track, "inbox")
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
      <div><div class="metric">{total_items}</div><div class="metric-label">全部項目</div></div>
      <div><div class="metric">{inbox_items}</div><div class="metric-label">待整理</div></div>
      <div><div class="metric">{source_count}</div><div class="metric-label">來源</div></div>
      <div><div class="metric">{fetchable_count}</div><div class="metric-label">會自動抓</div></div>
    </div>
    <div class="button-row">
      <a class="button {h(button_class)}" href="/track/{quote(track)}">{h(meta["entry"])}</a>
      <a class="button secondary" href="/sources?track={quote(track)}">看這類 RSS 來源</a>
    </div>
    <p class="help">第一顆按鈕是看這條主線的待整理資料；第二顆是檢查這條主線目前追蹤哪些網站或 feed。</p>
  </section>
"""
            )
        command_cards = [command_card(name, config) for name, config in COMMANDS.items()]
        body = f"""
<h1>共通入口</h1>
<p class="lede">這裡是每天 RSS 自動抓取、手動收藏、資料檢查與兩條知識主線的起點。資料正本仍在 GitHub 裡的 JSONL，網頁只是讓你比較好操作。</p>
{notice}
<div class="track-grid">{''.join(track_cards)}</div>
<h2>共用工具</h2>
<div class="grid">
  <div class="card">
    <h3>看到好頁面</h3>
    <p class="muted">把這顆拖到瀏覽器書籤列。之後看到想記下來的頁面，點書籤就會開出「加收藏」表單。</p>
    <p><a class="button" href="{h(bookmarklet)}">做成瀏覽器收藏按鈕</a></p>
    <p class="help">這不會直接發布內容，只是先放進待整理 inbox。</p>
  </div>
  <div class="card">
    <h3>待整理清單</h3>
    <p class="muted">這裡是已經收進 database/items.jsonl、狀態還是 inbox 的資料。</p>
    <p>{badge("建議收 " + str(inbox_counts.get("suggest-keep", 0)), "suggest-keep")} {badge("建議不要看 " + str(inbox_counts.get("suggest-skip", 0)), "suggest-skip")}</p>
    <p><a class="button" href="/items">打開待整理清單</a></p>
    <p class="help">你剛剛看到的 696 / 44 就是在這裡。</p>
  </div>
  <div class="card">
    <h3>候選清單</h3>
    <p class="muted">只放你已確認收下、準備跑 skill 編修的文章。</p>
    <p>{badge("待跑 skill " + str(len(skill_candidates)), "neutral")} {badge("直接送 PR " + str(len(direct_pr_items)), "suggest-keep")}</p>
    <p><a class="button" href="/candidates">打開候選清單</a></p>
    <p class="help">RSS 新資料請先在待整理清單處理；純小消息可在待整理頁直接標記送 PR。</p>
  </div>
  <div class="card">
    <h3>閱讀區</h3>
    <p class="muted">閱讀已確認收下的精選文章與小消息，並補你的個人觀點。</p>
    <p>{badge("可閱讀 " + str(len(reader_items)), "suggest-keep")}</p>
    <p><a class="button" href="/reader">打開閱讀區</a></p>
    <p class="help">在閱讀區可寫「我的關鍵紀錄」，也能把好文章重新送回 skill 依你的觀點改寫。</p>
  </div>
  <div class="card">
    <h3>RSS 暫存</h3>
    <p class="muted">每天抓到但還沒收進資料庫的新 RSS 文章。</p>
    <p>{badge("建議收 " + str(len(keep_candidates)), "suggest-keep")} {badge("建議不要看 " + str(len(skip_candidates)), "suggest-skip")}</p>
    <p><a class="button secondary" href="/rss-candidates">看 RSS 暫存</a></p>
    <p class="help">如果每日抓取仍使用暫存模式，就從這裡先收進待整理。</p>
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
</div>
<h2>本機指令</h2>
<p class="lede">這些按鈕只會執行固定 allowlist 指令；每顆按鈕下方都有白話說明，方便你不用記終端機命令。</p>
<div class="grid">{''.join(command_cards)}</div>
"""
        self.send_html("總覽", body)

    def show_items(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        track_filter = (query.get("track") or ["all"])[0]
        recommendation_filter = (query.get("recommendation") or ["all"])[0]
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}
        show_all = (query.get("show") or [""])[0] == "all"

        def matches_basic(item: dict) -> bool:
            if track_filter != "all" and item.get("track") != track_filter:
                return False
            if recommendation_filter != "all" and candidate_recommendation(item) != recommendation_filter:
                return False
            return True

        def matches(item: dict) -> bool:
            if not matches_basic(item):
                return False
            if selected_keywords and not (item_triage_keywords(item) & selected_keywords):
                return False
            return True

        keyword_source_items = [item for item in inbox_items if matches_basic(item)]
        keyword_counts = Counter(keyword for item in keyword_source_items for keyword in item_triage_keywords(item))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)

        filtered = [item for item in inbox_items if matches(item)]
        filtered.sort(
            key=lambda item: (item.get("captured_at", ""), item.get("published_at", ""), item.get("title", "")),
            reverse=True,
        )
        visible = filtered if show_all else filtered[:150]
        counts = Counter(candidate_recommendation(item) for item in inbox_items)
        track_counts = Counter(item.get("track", "unclassified") for item in inbox_items)
        reason_options = rejection_reason_options(items)
        notice = ""
        if (query.get("saved") or [""])[0] == "accepted":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已確認收下 {count} 筆。處理過的項目已離開待整理清單，現在可到候選清單的「待跑 skill」區接著編修。</div>'
        elif (query.get("saved") or [""])[0] == "rejected":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已標記不收 {count} 筆，項目已離開待整理清單，原因也已寫進資料庫與 review event。</div>'
        elif (query.get("error") or [""])[0] == "empty-selection":
            notice = '<div class="notice">請先勾選至少一則，再做批次處理。</div>'
        elif (query.get("error") or [""])[0] == "reason":
            notice = '<div class="notice">批次不收或自訂不收時，請先填原因。</div>'
        elif (query.get("saved") or [""])[0] == "direct_pr":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已標記 {count} 筆直接送 PR 小消息。它們已離開待整理清單，並留下紀錄。</div>'
        rows = []
        for item in visible:
            triage = item.get("triage") or {}
            recommendation = triage.get("recommendation", "unknown")
            matched = "、".join(triage.get("matched_keywords") or []) or "無"
            skipped = "、".join(triage.get("skip_keywords") or []) or "無"
            css_class = track_class(item.get("track", "unclassified"))
            item_id = str(item.get("id") or "")
            detail_href = item_detail_href(item)
            rows.append(
                f"""
<article class="card candidate-card candidate-card--{h(recommendation)}" data-item-id="{h(item_id)}">
  <label class="select-item">
    <input type="checkbox" class="item-select" value="{h(item_id)}">
    選取這則做批次處理
  </label>
  <div>
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge(recommendation_label(recommendation), recommendation)}
    <strong><a href="{h(detail_href)}">{h(item.get('title'))}</a></strong>
  </div>
  <p class="muted break-anywhere">{h(item.get('source_name'))} · {h(item.get('published_at') or item.get('captured_at'))} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">開原文</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  <p class="help">判斷理由：{h(triage.get('reason', '未標示'))}<br>命中關鍵字：{h(matched)}<br>排除關鍵字：{h(skipped)}</p>
  {editorial_triage_html(item)}
  <div class="decision-panel">
    <div class="button-row">
      <form method="post" action="/items/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit">確認收，準備跑 skill</button>
      </form>
      <form method="post" action="/items/direct-pr" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit" class="secondary">直接送 PR（小消息）</button>
      </form>
    </div>
    <p class="help">確認收會移到候選清單待跑 skill；純事實小消息可直接記錄為送 PR，不跑 skill。</p>
    <p class="help">不收原因</p>
    <div class="reason-presets">{inline_reject_buttons(item_id, reason_options)}</div>
    <details class="inline-reason">
      <summary>其他原因</summary>
      <form method="post" action="/items/reject" data-decision-form data-require-reason>
        <input type="hidden" name="id" value="{h(item_id)}">
        <div class="button-row">
          <input name="reason" placeholder="寫一句不收原因">
          <button type="submit" class="reason-chip reason-chip--danger">記錄不收</button>
        </div>
      </form>
    </details>
  </div>
</article>
"""
            )
        if not rows:
            rows.append('<div class="card"><strong>目前沒有符合條件的待整理項目</strong><p class="muted">換一個篩選條件，或先重新跑關鍵字判斷。</p></div>')

        more_link = ""
        if not show_all and len(filtered) > len(visible):
            parts = []
            if track_filter != "all":
                parts.append(f"track={quote(track_filter)}")
            if recommendation_filter != "all":
                parts.append(f"recommendation={quote(recommendation_filter)}")
            for keyword in sorted(selected_keywords):
                parts.append(f"keyword={quote(keyword)}")
            parts.append("show=all")
            more_link = f'<p><a class="button secondary" href="/items?{"&".join(parts)}">顯示全部 {len(filtered)} 筆</a></p>'

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        recommendation_options = [
            ("all", "全部建議"),
            ("suggest-keep", "只看建議收"),
            ("suggest-skip", "只看建議不要看"),
            ("unknown", "只看未判斷"),
        ]
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
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用關鍵字。</p>'
        batch_buttons = batch_reason_buttons(reason_options)
        body = f"""
<h1>待整理清單</h1>
<p class="lede">這裡是本機人工篩選台。資料已在 database/items.jsonl，但狀態仍是 inbox；處理過的項目會立刻離開這裡。確認收後會移到候選清單的「待跑 skill」區，整理好才進 GitHub PR。</p>
{notice}
<div class="grid">
  <div class="card"><div class="metric">{len(inbox_items)}</div><div class="metric-label">全部 inbox</div></div>
  <div class="card"><div class="metric">{counts.get("suggest-keep", 0)}</div><div class="metric-label">建議收</div><p><a href="/items?recommendation=suggest-keep">只看建議收</a></p></div>
  <div class="card"><div class="metric">{counts.get("suggest-skip", 0)}</div><div class="metric-label">建議不要看</div><p><a href="/items?recommendation=suggest-skip">只看建議不要看</a></p></div>
  <div class="card"><div class="metric">{counts.get("unknown", 0)}</div><div class="metric-label">未判斷</div></div>
</div>
<h2>篩選待整理</h2>
<form class="filter-panel" method="get" action="/items" id="items-filter-form">
  {'<input type="hidden" name="show" value="all">' if show_all else ''}
  <div class="form-grid">
    <div>
      <label>主線</label>
      <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
      <p class="help">選完會自動更新。開放科技 {track_counts.get('open-tech-open-industry', 0)}、人文 {track_counts.get('digital-humanities-local-knowledge', 0)}、未分類 {track_counts.get('unclassified', 0)}。</p>
    </div>
    <div>
      <label>系統建議</label>
      <select name="recommendation" class="auto-filter">{option_list(recommendation_options, recommendation_filter)}</select>
      <p class="help">這裡的建議來自目前的關鍵字設定。改完關鍵字後可到關鍵字頁重新跑。</p>
    </div>
  </div>
  <label>關鍵字</label>
  <div class="keyword-filters">{keyword_filter_html}</div>
  <div class="button-row">
    <a class="button secondary" href="/items">清除篩選</a>
    <a class="button quiet" href="/keywords">調整或重跑關鍵字</a>
  </div>
  <p class="help">勾選關鍵字後會自動更新；多個關鍵字是「任一命中」就顯示。</p>
</form>
<h2>批次處理</h2>
<div class="card batch-panel">
  <p><strong id="selected-count">已選取 0 則</strong></p>
  <div class="button-row">
    <button type="button" class="secondary" id="select-visible">全選目前顯示</button>
    <button type="button" class="quiet" id="clear-selection">清除選取</button>
  </div>
  <form id="items-batch-form" method="post" action="/items/batch" data-batch-form>
    <input type="hidden" id="batch-ids" name="ids">
    <input type="hidden" id="batch-reason" name="reason">
    <div class="button-row">
      <button type="submit" name="action" value="accept">批次確認收，準備跑 skill</button>
      <button type="submit" name="action" value="direct_pr" class="secondary">批次直接送 PR（小消息）</button>
    </div>
    <p class="help">批次不收原因</p>
    <div class="reason-presets">{batch_buttons}</div>
    <details class="inline-reason">
      <summary>批次其他原因</summary>
      <div class="button-row">
        <input id="batch-custom-reason" name="custom_reason" placeholder="寫一句批次不收原因">
        <button type="submit" name="action" value="reject" class="reason-chip reason-chip--danger" data-custom-reason="1">用這個原因批次不收</button>
      </div>
    </details>
  </form>
  <p class="help">批次處理只會處理你勾選的項目；處理完會從待整理清單消失。</p>
</div>
<h2>項目列表</h2>
<p class="muted">符合條件：{len(filtered)} 筆。{'' if show_all else f'目前先顯示 {len(visible)} 筆。'}</p>
{more_link}
<div class="list">{''.join(rows)}</div>
{more_link}
<script>
const itemCheckboxes = Array.from(document.querySelectorAll(".item-select"));
const batchIds = document.getElementById("batch-ids");
const batchReason = document.getElementById("batch-reason");
const selectedCount = document.getElementById("selected-count");
const customReason = document.getElementById("batch-custom-reason");

function liveCheckboxes() {{
  return itemCheckboxes.filter((box) => box.isConnected);
}}

function syncSelection() {{
  const ids = liveCheckboxes().filter((box) => box.checked).map((box) => box.value);
  batchIds.value = ids.join(",");
  selectedCount.textContent = `已選取 ${{ids.length}} 則`;
  return ids;
}}

itemCheckboxes.forEach((box) => box.addEventListener("change", syncSelection));
document.querySelectorAll("#items-filter-form .auto-filter, #items-filter-form input[type='checkbox']").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("items-filter-form").submit());
}});
document.getElementById("select-visible").addEventListener("click", () => {{
  liveCheckboxes().forEach((box) => {{ box.checked = true; }});
  syncSelection();
}});
document.getElementById("clear-selection").addEventListener("click", () => {{
  liveCheckboxes().forEach((box) => {{ box.checked = false; }});
  syncSelection();
}});

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
  ids.forEach((id) => {{
    const card = findItemCard(id);
    if (!card || card.classList.contains("is-removing")) {{
      return;
    }}
    card.classList.add("is-removing");
    const remove = () => {{
      if (card.isConnected) {{
        card.remove();
        syncSelection();
      }}
    }};
    card.addEventListener("animationend", remove, {{ once: true }});
    window.setTimeout(remove, 260);
  }});
}}

async function submitWithoutLeaving(form, submitter, idsToRemove) {{
  const body = buildRequestBody(form, submitter);
  const fields = Array.from(form.querySelectorAll("button, input, select, textarea"));
  fields.forEach((field) => {{ field.disabled = true; }});
  try {{
    const response = await fetch(form.action, {{
      method: form.method || "POST",
      body,
      credentials: "same-origin",
      redirect: "follow",
      headers: {{ "X-Requested-With": "local-web-fetch" }},
    }});
    if (!response.ok) {{
      throw new Error(`HTTP ${{response.status}}`);
    }}
    removeCards(idsToRemove);
  }} catch (error) {{
    fields.forEach((field) => {{ field.disabled = false; }});
    alert("剛剛沒有送成功，畫面先保留。可以再按一次。");
  }}
}}

document.querySelectorAll("form[data-decision-form]").forEach((form) => {{
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

document.getElementById("items-batch-form").addEventListener("submit", (event) => {{
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
</script>
"""
        self.send_html("待整理清單", body)

    def show_item_reject_form(self, query: dict[str, list[str]]) -> None:
        item_id = form_value(query, "id")
        items = load_jsonl(ITEMS)
        item = next((row for row in items if row.get("id") == item_id), None)
        if not item:
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回待整理清單</a></p>", HTTPStatus.NOT_FOUND)
            return

        error = ""
        if (query.get("error") or [""])[0] == "reason":
            error = '<div class="notice">請先寫一點原因，再標記不收。</div>'
        reason_buttons = "\n".join(
            f'<button type="button" class="secondary reason-preset" data-reason="{h(reason)}">{h(reason)}</button>'
            for reason in rejection_reason_options(items)
        )
        triage = item.get("triage") or {}
        body = f"""
<h1>不收原因</h1>
<p class="lede">這一步會把項目從 inbox 封存，但保留原因。這些原因之後會出現在快捷按鈕裡，幫你更快整理不要看的資料。</p>
{error}
<article class="card candidate-card candidate-card--{h(candidate_recommendation(item))}">
  <div>
    {badge(track_meta(item.get("track", "unclassified"))["short"], track_class(item.get("track", "unclassified")))}
    {badge(recommendation_label(candidate_recommendation(item)), candidate_recommendation(item))}
    <strong><a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">{h(item.get('title'))}</a></strong>
  </div>
  <p class="muted break-anywhere">{h(item.get('source_name'))} · {h(item.get('published_at') or item.get('captured_at'))} · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 420))}</p>
  <p class="help">系統判斷：{h(triage.get('reason', '未標示'))}</p>
</article>
<form class="form-panel" method="post" action="/items/reject">
  <input type="hidden" name="id" value="{h(item_id)}">
  <label>常用原因</label>
  <div class="reason-presets">{reason_buttons}</div>
  <p class="help">點一個原因會先放進文字框；你可以再補自己的判斷。</p>
  <label>這次不收的原因</label>
  <textarea id="reject-reason" name="reason" required></textarea>
  <p class="help">例：和主線關聯太弱、重複、只是活動公告、缺少可查證來源。這會寫進項目紀錄和 review event。</p>
  <div class="button-row">
    <button type="submit" class="danger">確認不收並記錄原因</button>
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
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}

        def matches_basic(item: dict) -> bool:
            return track_filter == "all" or item.get("track") == track_filter

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
        track_counts = Counter(item.get("track", "unclassified") for item in skill_candidates)
        skill_rows = []
        for item in filtered_skill:
            triage = item.get("triage") or {}
            recommendation = candidate_recommendation(item)
            css_class = track_class(item.get("track", "unclassified"))
            decided_at = (item.get("local_decision") or {}).get("decided_at", "未標示時間")
            detail_href = item_detail_href(item)
            skill_rows.append(
                f"""
<article class="card candidate-card">
  <div>
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge("待跑 skill", "neutral")}
    {badge(recommendation_label(recommendation), recommendation)}
    <strong><a href="{h(detail_href)}">{h(item.get('title'))}</a></strong>
  </div>
  <p class="muted break-anywhere">{h(item.get('source_name'))} · 確認收：{h(decided_at)} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">開原文</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  {editorial_triage_html(item, compact=True)}
  <p class="help">下一步：跑 skill 做摘要、切角與文章編修；整理好後再送 GitHub PR。<br>系統原判斷：{h(triage.get('reason', '未標示'))}</p>
</article>
"""
            )
        if not skill_rows:
            skill_rows.append('<div class="card"><strong>目前沒有待跑 skill 的項目</strong><p class="muted">在待整理清單按「確認收」後，會移到這裡。</p></div>')

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
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用子關鍵字。</p>'
        body = f"""
<h1>候選清單</h1>
<p class="lede">這裡只放你已確認收下、準備跑 skill 編修的資料。RSS 剛抓到的新文章已移到「RSS 暫存」。</p>
<div class="grid">
  <div class="card"><div class="metric">{len(skill_candidates)}</div><div class="metric-label">待跑 skill</div></div>
  <div class="card"><div class="metric">{track_counts.get("open-tech-open-industry", 0)}</div><div class="metric-label">開放科技</div></div>
  <div class="card"><div class="metric">{track_counts.get("digital-humanities-local-knowledge", 0)}</div><div class="metric-label">人文知識</div></div>
  <div class="card"><div class="metric">{track_counts.get("unclassified", 0)}</div><div class="metric-label">未分類</div></div>
</div>
<h2>篩選候選</h2>
<form class="filter-panel" method="get" action="/candidates" id="candidate-filter-form">
  <label>主線</label>
  <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
  <p class="help">選完會自動更新。處理完 skill 後，再把內容整理成 PR。</p>
  <label>子關鍵字</label>
  <div class="keyword-filters">{keyword_filter_html}</div>
  <div class="button-row">
    <a class="button secondary" href="/items">回待整理清單</a>
    <a class="button quiet" href="/rss-candidates">看 RSS 暫存</a>
  </div>
  <p class="help">勾選子關鍵字後會自動更新；多個關鍵字是任一命中就顯示。</p>
</form>
<h2>已確認收，待跑 skill</h2>
<div class="list">{''.join(skill_rows)}</div>
<script>
document.querySelectorAll("#candidate-filter-form .auto-filter").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("candidate-filter-form").submit());
}});
document.querySelectorAll("#candidate-filter-form input[type='checkbox']").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("candidate-filter-form").submit());
}});
</script>
"""
        self.send_html("候選清單", body)

    def show_reader(self, query: dict[str, list[str]]) -> None:
        items = [item for item in load_jsonl(ITEMS) if is_reader_item(item)]
        track_filter = (query.get("track") or ["all"])[0]
        kind_filter = (query.get("kind") or ["all"])[0]
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}

        def matches_basic(item: dict) -> bool:
            if track_filter != "all" and item.get("track") != track_filter:
                return False
            kind = item_display_kind(item)
            if kind_filter != "all" and kind != kind_filter:
                return False
            return True

        def matches(item: dict) -> bool:
            if not matches_basic(item):
                return False
            if selected_keywords and not (item_triage_keywords(item) & selected_keywords):
                return False
            return True

        keyword_source_items = [item for item in items if matches_basic(item)]
        keyword_counts = Counter(keyword for item in keyword_source_items for keyword in item_triage_keywords(item))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)
        filtered = [item for item in items if matches(item)]
        filtered.sort(
            key=lambda item: (item.get("published_at", ""), item.get("captured_at", ""), item.get("title", "")),
            reverse=True,
        )
        track_counts = Counter(item.get("track", "unclassified") for item in items)
        kind_counts = Counter(item_display_kind(item) for item in items)
        notice = ""
        if (query.get("saved") or [""])[0] == "read_more":
            notice = '<div class="notice">已嘗試載入原始主文與頁面資料；若抓到全文，已寫進閱讀資料庫。</div>'
        elif (query.get("error") or [""])[0] == "read_more":
            notice = '<div class="notice">這次沒有抓到更多資料，可能是網站擋住讀取、需要登入，或頁面沒有可抽取的主文。</div>'
        redirect_parts = []
        if track_filter != "all":
            redirect_parts.append(f"track={quote(track_filter)}")
        if kind_filter != "all":
            redirect_parts.append(f"kind={quote(kind_filter)}")
        for keyword in sorted(selected_keywords):
            redirect_parts.append(f"keyword={quote(keyword)}")
        reader_redirect = "/reader" + (f"?{'&'.join(redirect_parts)}" if redirect_parts else "")
        cards = []
        for item in filtered[:180]:
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
            cards.append(
                f"""
<article class="card reader-card">
  {thumb}
  <div class="reader-body">
    <div>
      {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
      {badge(status_label(item.get("status", "")), "neutral")}
      {badge(content_kind_label(kind), "neutral")}
    </div>
    <h3><a href="{h(item_detail_href(item))}">{h(item.get('title'))}</a></h3>
    <p class="muted break-anywhere">{h(item.get('source_name'))} · {h(item.get('published_at') or item.get('captured_at'))}</p>
    <p class="zh-summary">{h(item_zh_summary(item, 260))}</p>
    {note_html}
    <div class="button-row">
      <a class="button" href="{h(item_detail_href(item))}">閱讀 / 記錄</a>
      <form method="post" action="/items/read-more" data-read-more-form data-target="#fulltext-{h(item.get('id'))}">
        <input type="hidden" name="id" value="{h(item.get('id'))}">
        <input type="hidden" name="redirect" value="{h(reader_redirect)}">
        <button type="submit" class="secondary">閱讀更多</button>
      </form>
      <a class="button secondary" href="{h(item.get('url'))}" target="_blank" rel="noreferrer">開原文</a>
    </div>
    <section class="fulltext-panel source-card source-card--source" id="fulltext-{h(item.get('id'))}" hidden>
      <div class="section-kicker">原始主文</div>
      <h3>剛載入的全文</h3>
      <p class="help" data-fulltext-meta></p>
      <div class="article-text" data-fulltext-body></div>
    </section>
  </div>
</article>
"""
            )
        if not cards:
            cards.append('<div class="card"><strong>目前沒有符合條件的閱讀項目</strong><p class="muted">在待整理清單按「確認收」或「直接送 PR（小消息）」後，會出現在這裡。</p></div>')

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        kind_options = [
            ("all", "全部類型"),
            ("featured-article", "精選文章 / 待跑 skill"),
            ("small-news", "純新聞 / 小消息"),
            ("needs-review", "人工判斷"),
        ]
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
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用子關鍵字。</p>'
        body = f"""
<h1>閱讀區</h1>
<p class="lede">這裡放已確認收下的精選文章與小消息。你可以像讀線上報一樣瀏覽，也可以在單篇頁留下「我的關鍵紀錄」，再把文章依你的觀點重新送回 skill。</p>
{notice}
<div class="grid">
  <div class="card"><div class="metric">{len(items)}</div><div class="metric-label">可閱讀項目</div></div>
  <div class="card"><div class="metric">{track_counts.get("open-tech-open-industry", 0)}</div><div class="metric-label">開放科技</div></div>
  <div class="card"><div class="metric">{track_counts.get("digital-humanities-local-knowledge", 0)}</div><div class="metric-label">人文知識</div></div>
  <div class="card"><div class="metric">{kind_counts.get("small-news", 0)}</div><div class="metric-label">小消息</div></div>
</div>
<h2>篩選閱讀</h2>
<form class="filter-panel" method="get" action="/reader" id="reader-filter-form">
  <div class="form-grid">
    <div>
      <label>主線</label>
      <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
      <p class="help">分開閱讀開放科技或人文知識，也可以看全部。</p>
    </div>
    <div>
      <label>文章類型</label>
      <select name="kind" class="auto-filter">{option_list(kind_options, kind_filter)}</select>
      <p class="help">精選文章適合跑 skill；小消息多半只需要查核與短 PR。</p>
    </div>
  </div>
  <label>子關鍵字</label>
  <div class="keyword-filters">{keyword_filter_html}</div>
  <div class="button-row">
    <a class="button secondary" href="/reader">清除篩選</a>
    <a class="button quiet" href="/items">回待整理</a>
  </div>
  <p class="help">勾選子關鍵字後會自動更新；多個關鍵字是任一命中就顯示。</p>
</form>
<h2>文章</h2>
<p class="muted">符合條件：{len(filtered)} 筆。最多先顯示 180 筆，避免頁面太重。</p>
<div class="reader-grid">{''.join(cards)}</div>
<script>
document.querySelectorAll("#reader-filter-form .auto-filter").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("reader-filter-form").submit());
}});
document.querySelectorAll("#reader-filter-form input[type='checkbox']").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("reader-filter-form").submit());
}});
</script>
"""
        self.send_html("閱讀區", body)

    def show_item_detail(self, query: dict[str, list[str]]) -> None:
        item_id = form_value(query, "id")
        item = next((row for row in load_jsonl(ITEMS) if row.get("id") == item_id), None)
        if not item:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回待整理清單</a></p>", HTTPStatus.NOT_FOUND)
            return

        saved = (query.get("saved") or [""])[0]
        notice = ""
        if saved == "note":
            notice = '<div class="notice">已更新你的個人關鍵紀錄。</div>'
        elif saved == "requeue":
            notice = '<div class="notice">已重新送回 skill 候選。你的個人觀點會留在紀錄裡，後續撰稿要一起參考。</div>'
        elif saved == "read_more":
            notice = '<div class="notice">已嘗試載入原始主文與頁面資料；若抓到全文，已寫入閱讀資料庫並顯示在「原始主文」。</div>'
        elif (query.get("error") or [""])[0] == "read_more":
            notice = '<div class="notice">這次沒有抓到更多資料。可能是網站擋住讀取、網址需要登入，或頁面沒有可抽取的主文。</div>'

        css_class = track_class(item.get("track", "unclassified"))
        triage = item.get("triage") or {}
        kind = item_display_kind(item)
        image = item_image_url(item)
        image_html = (
            f"<div class='item-image'><img src='{h(image)}' alt=''></div>"
            if image
            else f"<div class='item-image'>{h(track_meta(item.get('track', 'unclassified'))['short'])}</div>"
        )
        article_text = item_article_text(item)
        article_meta = item_reading_metadata(item)
        fulltext_hidden = "" if article_text else " hidden"
        fulltext_message = (
            f"已載入原始主文，約 {article_meta.get('article_text_chars', len(article_text))} 字；抽取方式：{article_meta.get('article_text_method', 'metadata')}。"
            if article_text
            else "按「閱讀更多」後會從原始網址往下抓全文，載入完成後顯示在這裡。"
        )
        note = personal_note_text(item)
        note_updated = ""
        personal_notes = item.get("personal_notes")
        if isinstance(personal_notes, dict) and personal_notes.get("updated_at"):
            note_updated = f"<p class='help'>上次更新：{h(personal_notes.get('updated_at'))}</p>"

        inbox_actions = ""
        if item.get("status") == "inbox":
            inbox_actions = f"""
<div class="card">
  <h2>待整理決定</h2>
  <p class="muted">這則還在待整理。你可以在這裡先看完整資訊，再回列表或直接分流。</p>
  <div class="button-row">
    <form method="post" action="/items/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <button type="submit">確認收，準備跑 skill</button>
    </form>
    <form method="post" action="/items/direct-pr">
      <input type="hidden" name="id" value="{h(item_id)}">
      <button type="submit" class="secondary">直接送 PR（小消息）</button>
    </form>
    <a class="button quiet" href="/items/reject?id={quote(item_id)}">不收，寫原因</a>
  </div>
  <p class="help">確認收會移到候選清單；直接送 PR 適合純事實小消息；不收會要求留下原因。</p>
</div>
"""

        skill_requests = item.get("skill_requests") if isinstance(item.get("skill_requests"), list) else []
        skill_rows = ""
        if skill_requests:
            rows = []
            for request in skill_requests[-5:]:
                rows.append(f"<li>{h(request.get('requested_at', ''))}：{h(clean_text(request.get('personal_notes'), 160))}</li>")
            skill_rows = f"<div class='card'><h2>重送 skill 紀錄</h2><ul>{''.join(rows)}</ul></div>"

        body = f"""
<h1>{h(item.get('title'))}</h1>
<p class="lede break-anywhere">{h(item.get('source_name'))} · {h(item.get('published_at') or item.get('captured_at'))} · {h(item.get('url'))}</p>
{notice}
<div class="item-hero">
  <section class="card">
    <div>
      {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
      {badge(status_label(item.get("status", "")), "neutral")}
      {badge(content_kind_label(kind), "neutral")}
      {badge(recommendation_label(candidate_recommendation(item)), candidate_recommendation(item))}
    </div>
    <p class="zh-summary">{h(item_zh_summary(item, 780))}</p>
    <p>{h(clean_text(item.get('summary'), 1800))}</p>
    <div class="button-row">
      <form method="post" action="/items/read-more" data-read-more-form data-target="#fulltext-panel">
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
        <button type="submit">閱讀更多</button>
      </form>
      <a class="button secondary" href="{h(item.get('url'))}" target="_blank" rel="noreferrer">開原文</a>
      <a class="button quiet" href="/items">回待整理</a>
      <a class="button quiet" href="/reader">回閱讀區</a>
    </div>
  </section>
  {image_html}
</div>

<section class="card fulltext-panel source-card source-card--source" id="fulltext-panel"{fulltext_hidden}>
  <div class="section-kicker">原始主文</div>
  <h2>閱讀更多載入的全文</h2>
  <p class="help" data-fulltext-meta>{h(fulltext_message)}</p>
  <div class="article-text" data-fulltext-body>{h(article_text)}</div>
</section>

<div class="two-column">
  <section>
    <h2>閱讀建議與判斷來源</h2>
    {editorial_triage_html(item)}
    <div class="card">
      <h2>關鍵字第一層判斷</h2>
      <p class="help">建議：{h(recommendation_label(candidate_recommendation(item)))}<br>理由：{h(triage.get('reason', '未標示'))}<br>命中：{h('、'.join(triage.get('matched_keywords') or []) or '無')}<br>排除：{h('、'.join(triage.get('skip_keywords') or []) or '無')}</p>
    </div>
    {inbox_actions}
    {skill_rows}
  </section>
  <aside>
    <div class="card">
      <h2>我的關鍵紀錄</h2>
      <p class="muted">寫你自己的判斷、疑問或想補的觀點。之後按重新送 skill 時，agent 要用這段重新檢視文章。</p>
      <form method="post" action="/items/personal-note">
        <input type="hidden" name="id" value="{h(item_id)}">
        <textarea name="note" placeholder="例如：這篇和 OCF 的資料治理倡議有關，但要補台灣案例。">{h(note)}</textarea>
        <button type="submit">儲存我的紀錄</button>
      </form>
      {note_updated}
    </div>
    <div class="card">
      <h2>重新送 skill</h2>
      <p class="muted">如果讀完覺得這篇超值得整理，先寫好你的觀點，再按這顆。它會回到候選清單，等待用你的觀點跑撰稿 skill。</p>
      <form method="post" action="/items/requeue-skill">
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit">用我的觀點重新送 skill</button>
      </form>
      <p class="help">這不會自動發 PR，只會留下「重送 skill」紀錄並把狀態放回待跑 skill。</p>
    </div>
  </aside>
</div>
"""
        self.send_html("單篇整理", body)

    def show_rss_candidates(self, query: dict[str, list[str]]) -> None:
        candidates = load_jsonl(CANDIDATES)
        track_filter = (query.get("track") or ["all"])[0]
        recommendation_filter = (query.get("recommendation") or ["all"])[0]
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}

        def matches_basic(candidate: dict) -> bool:
            if track_filter != "all" and candidate.get("track") != track_filter:
                return False
            if recommendation_filter != "all" and candidate_recommendation(candidate) != recommendation_filter:
                return False
            return True

        def matches(candidate: dict) -> bool:
            if not matches_basic(candidate):
                return False
            if selected_keywords and not (item_triage_keywords(candidate) & selected_keywords):
                return False
            return True

        keyword_source_items = [candidate for candidate in candidates if matches_basic(candidate)]
        keyword_counts = Counter(keyword for candidate in keyword_source_items for keyword in item_triage_keywords(candidate))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)
        filtered = [candidate for candidate in candidates if matches(candidate)]
        filtered.sort(
            key=lambda item: (candidate_recommendation(item) == "suggest-skip", item.get("captured_at", ""), item.get("published_at", "")),
            reverse=False,
        )
        counts = Counter(candidate_recommendation(candidate) for candidate in candidates)
        track_counts = Counter(candidate.get("track", "unclassified") for candidate in candidates)
        rows = []
        for candidate in filtered:
            triage = candidate.get("triage") or {}
            recommendation = triage.get("recommendation", "unknown")
            matched = "、".join(triage.get("matched_keywords") or []) or "無"
            skipped = "、".join(triage.get("skip_keywords") or []) or "無"
            css_class = track_class(candidate.get("track", "unclassified"))
            rows.append(
                f"""
<article class="card candidate-card candidate-card--{h(recommendation)}">
  <div>
    {badge(track_meta(candidate.get("track", "unclassified"))["short"], css_class)}
    {badge(recommendation_label(recommendation), recommendation)}
    <strong><a href="{h(candidate.get('url'))}" target="_blank" rel="noreferrer">{h(candidate.get('title'))}</a></strong>
  </div>
  <p class="muted break-anywhere">{h(candidate.get('source_name'))} · {h(candidate.get('published_at') or candidate.get('captured_at'))} · {h(candidate.get('url'))}</p>
  <p>{h(clean_text(candidate.get('summary'), 360))}</p>
  <p class="help">判斷理由：{h(triage.get('reason', '未標示'))}<br>命中關鍵字：{h(matched)}<br>排除關鍵字：{h(skipped)}</p>
  {editorial_triage_html(candidate, compact=True)}
  <div class="button-row">
    <form method="post" action="/candidates/accept">
      <input type="hidden" name="id" value="{h(candidate.get('id'))}">
      <button type="submit" name="mode" value="accept">收進待整理</button>
    </form>
    <form method="post" action="/candidates/dismiss">
      <input type="hidden" name="id" value="{h(candidate.get('id'))}">
      <button type="submit" class="danger">不要看，以後略過</button>
    </form>
  </div>
  <p class="help">收進待整理後，會寫進 database/items.jsonl 的 inbox，再到待整理頁做最後決定。</p>
</article>
"""
            )
        if not rows:
            rows.append('<div class="card"><strong>目前沒有符合條件的 RSS 暫存</strong><p class="muted">可以回首頁按「抓到候選清單」，或放寬篩選條件。</p></div>')

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        recommendation_options = [
            ("all", "全部建議"),
            ("suggest-keep", "只看建議收"),
            ("suggest-skip", "只看建議不要看"),
        ]
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
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用子關鍵字。</p>'
        body = f"""
<h1>RSS 暫存</h1>
<p class="lede">這裡只放每日 RSS 抓到但還沒收進 database/items.jsonl 的文章。真的要看再收進待整理；不要看的就略過。</p>
<div class="grid">
  <div class="card"><div class="metric">{len(candidates)}</div><div class="metric-label">RSS 新候選</div></div>
  <div class="card"><div class="metric">{counts.get("suggest-keep", 0)}</div><div class="metric-label">RSS 建議收</div></div>
  <div class="card"><div class="metric">{counts.get("suggest-skip", 0)}</div><div class="metric-label">RSS 建議不要看</div></div>
</div>
<h2>篩選 RSS 暫存</h2>
<form class="filter-panel" method="get" action="/rss-candidates" id="rss-candidate-filter-form">
  <div class="form-grid">
    <div>
      <label>主線</label>
      <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
      <p class="help">目前暫存：開放科技 {track_counts.get('open-tech-open-industry', 0)}、人文 {track_counts.get('digital-humanities-local-knowledge', 0)}、未分類 {track_counts.get('unclassified', 0)}。</p>
    </div>
    <div>
      <label>系統建議</label>
      <select name="recommendation" class="auto-filter">{option_list(recommendation_options, recommendation_filter)}</select>
      <p class="help">建議只是第一層篩選，你仍然可以收下建議不要看的項目。</p>
    </div>
  </div>
  <label>子關鍵字</label>
  <div class="keyword-filters">{keyword_filter_html}</div>
  <div class="button-row">
    <a class="button secondary" href="/keywords">調整關鍵字</a>
    <a class="button quiet" href="/items">回待整理清單</a>
  </div>
  <p class="help">勾選子關鍵字後會自動更新；多個關鍵字是任一命中就顯示。</p>
</form>
<h2>RSS 新候選</h2>
<p class="help">這一段還沒進 database/items.jsonl。按「收下到資料庫」後會進待整理清單，再由你決定是否確認收。</p>
<div class="list">{''.join(rows)}</div>
<script>
document.querySelectorAll("#rss-candidate-filter-form .auto-filter").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("rss-candidate-filter-form").submit());
}});
document.querySelectorAll("#rss-candidate-filter-form input[type='checkbox']").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("rss-candidate-filter-form").submit());
}});
</script>
"""
        self.send_html("RSS 暫存", body)

    def update_item_decisions(self, item_ids: list[str], action: str, reason: str = "") -> int:
        selected_ids = {item_id for item_id in item_ids if item_id}
        if not selected_ids:
            return 0

        items = load_jsonl(ITEMS)
        updated_items = []
        decided_at = now_iso()
        events = []
        changed = 0
        for item in items:
            if item.get("id") not in selected_ids or item.get("status") != "inbox":
                updated_items.append(item)
                continue
            updated_item = dict(item)
            if action == "accept":
                note = "本機確認收下；下一步跑 skill 做摘要、切角與文章編修，整理好後再送 PR。"
                event_status = "accepted-for-editing"
                updated_item["status"] = "triaged"
                updated_item["local_decision"] = {
                    "action": "accepted-for-editing",
                    "decided_at": decided_at,
                    "reason": "人工確認值得收，準備進入 skill 編修。",
                    "source": "local_web",
                    "next_step": "run-writing-skill-before-pr",
                }
            elif action == "direct_pr":
                note = "本機標記直接送 PR（小消息）；純事實項目，不跑 skill。"
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
            updated_items.append(updated_item)
            events.append(review_event(updated_item, event_status, note))
            changed += 1

        if changed:
            write_jsonl(ITEMS, updated_items)
            for event in events:
                append_jsonl(REVIEW_EVENTS, event)
        return changed

    def accept_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回待整理清單</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "accept")
        if self.is_async_request():
            self.send_no_content()
            return
        self.redirect(f"/items?saved=accepted&count={count}")

    def direct_pr_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回待整理清單</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "direct_pr")
        if self.is_async_request():
            self.send_no_content()
            return
        self.redirect(f"/items?saved=direct_pr&count={count}")

    def reject_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        reason = form_value(data, "reason")
        if not reason:
            if self.is_async_request():
                self.send_no_content(HTTPStatus.BAD_REQUEST)
                return
            self.redirect("/items?error=reason")
            return

        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回待整理清單</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "reject", reason)
        if self.is_async_request():
            self.send_no_content()
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
        if action == "accept":
            count = self.update_item_decisions(item_ids, "accept")
            if self.is_async_request():
                self.send_no_content()
                return
            self.redirect(f"/items?saved=accepted&count={count}")
            return
        if action == "direct_pr":
            count = self.update_item_decisions(item_ids, "direct_pr")
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
            count = self.update_item_decisions(item_ids, "reject", reason)
            if self.is_async_request():
                self.send_no_content()
                return
            self.redirect(f"/items?saved=rejected&count={count}")
            return
        self.redirect("/items")

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
                "instruction": "重新用 personal_notes 檢視文章，補切角、摘要、查核重點與可採用觀點。",
            }
            skill_requests = updated.get("skill_requests") if isinstance(updated.get("skill_requests"), list) else []
            updated["skill_requests"] = [*skill_requests, request]
            updated["status"] = "triaged"
            updated["local_decision"] = {
                "action": "revisit-with-personal-notes",
                "decided_at": requested_at,
                "reason": "閱讀後人工要求用個人觀點重新跑 skill。",
                "source": "local_web",
                "next_step": "run-writing-skill-with-personal-notes",
            }
            updated["review"] = append_review_note(
                updated.get("review") or {},
                f"{requested_at} 閱讀後重新送 skill；個人觀點：{note or '未填'}",
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
            review_event(event_item, "revisit-with-personal-notes", "閱讀後重新送 skill，後續需納入 personal_notes。"),
        )
        self.redirect(f"/items/view?id={quote(item_id)}&saved=requeue")

    def read_more_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = form_value(data, "redirect", f"/items/view?id={quote(item_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = f"/items/view?id={quote(item_id)}"
        items = load_jsonl(ITEMS)
        changed = False
        found = False
        response_item: dict | None = None
        updated_items = []
        error = ""
        for item in items:
            if item.get("id") != item_id:
                updated_items.append(item)
                continue
            found = True
            updated, did_change, error = enrich_item_metadata(item)
            updated_items.append(updated)
            changed = did_change
            response_item = updated
        if not found:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到項目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        if changed:
            write_jsonl(ITEMS, updated_items)
        if wants_json:
            metadata = item_reading_metadata(response_item or {})
            article_text = clean_text(metadata.get("article_text"))
            message = (
                f"已載入原始主文，約 {metadata.get('article_text_chars', len(article_text))} 字；"
                f"抽取方式：{metadata.get('article_text_method', 'metadata')}。"
                if article_text
                else "已嘗試讀取原始網址，但這次沒有抓到可顯示的主文。"
            )
            self.send_json(
                {
                    "ok": not bool(error) or bool(article_text),
                    "changed": changed,
                    "error": error,
                    "message": message,
                    "article_text": article_text,
                    "article_text_status": metadata.get("article_text_status", ""),
                    "image_url": metadata.get("image_url", ""),
                    "redirect": redirect_to,
                },
                HTTPStatus.OK if (not error or article_text) else HTTPStatus.BAD_GATEWAY,
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

    def accept_candidate(self, data: dict[str, list[str]]) -> None:
        candidate_id = form_value(data, "id")
        mode = form_value(data, "mode", "accept")
        candidates = load_jsonl(CANDIDATES)
        candidate = next((row for row in candidates if row.get("id") == candidate_id), None)
        if not candidate:
            self.send_html("找不到候選項目", "<h1>找不到候選項目</h1><p><a href='/rss-candidates'>回 RSS 暫存</a></p>", HTTPStatus.NOT_FOUND)
            return

        item = remove_local_candidate_fields(candidate)
        items = load_jsonl(ITEMS)
        already_exists = any(existing.get("id") == item.get("id") or existing.get("url") == item.get("url") for existing in items)
        candidates = [row for row in candidates if row.get("id") != candidate_id]
        write_jsonl(CANDIDATES, candidates)
        if not already_exists:
            append_jsonl(ITEMS, item)

        if mode == "accept_issue":
            returncode, output = create_github_issue(item)
            body = f"""
<h1>已收下候選項目</h1>
<p class="muted">資料庫：{'原本已存在，已從候選清單移除。' if already_exists else '已寫進 database/items.jsonl。'}</p>
<p class="muted">GitHub issue exit code: {returncode}</p>
<pre>{h(output)}</pre>
<p><a class="button" href="/rss-candidates">回 RSS 暫存</a></p>
"""
            self.send_html("已收下候選項目", body)
            return

        self.redirect("/rss-candidates?saved=accepted")

    def dismiss_candidate(self, data: dict[str, list[str]]) -> None:
        candidate_id = form_value(data, "id")
        candidates = load_jsonl(CANDIDATES)
        candidate = next((row for row in candidates if row.get("id") == candidate_id), None)
        if not candidate:
            self.send_html("找不到候選項目", "<h1>找不到候選項目</h1><p><a href='/rss-candidates'>回 RSS 暫存</a></p>", HTTPStatus.NOT_FOUND)
            return
        candidates = [row for row in candidates if row.get("id") != candidate_id]
        write_jsonl(CANDIDATES, candidates)
        dismissed = {
            "id": candidate.get("id"),
            "track": candidate.get("track"),
            "title": candidate.get("title"),
            "url": candidate.get("url"),
            "source_id": candidate.get("source_id"),
            "source_name": candidate.get("source_name"),
            "reference": candidate.get("reference", {}),
            "triage": candidate.get("triage", {}),
            "dismissed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": "本機候選清單按鈕標記不要看。",
        }
        append_jsonl(DISMISSED, dismissed)
        self.redirect("/rss-candidates?saved=dismissed")

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
<section class="card track-card track-card--{h(css_class)}">
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
<p class="lede">這裡控制 RSS 候選清單的第一層判斷，也會影響本機規則判斷欄位裡的「關鍵字匹配程度」。它不會刪資料，只會更新建議。</p>
<form method="post" action="/keywords">
  <div class="track-grid">{''.join(track_sections)}</div>
  <button type="submit">儲存關鍵字設定</button>
  <p class="help">儲存後會寫進 database/triage-keywords.json。下一次按「抓到候選清單」才會套用。</p>
</form>
<div class="card">
  <h2>套用到目前待整理</h2>
  <p class="muted">如果你剛改完關鍵字，可以立刻重跑目前候選清單與 database/items.jsonl 裡的 inbox 項目，並一起更新「三個建議看的理由」與初步收錄判斷。</p>
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
        self.redirect("/keywords?saved=1")

    def show_track(self, track: str) -> None:
        if track not in TRACK_META:
            self.send_html("找不到主線", "<h1>找不到這條知識主線</h1>", HTTPStatus.NOT_FOUND)
            return

        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        meta = track_meta(track)
        css_class = track_class(track)
        button_class = f"button-{css_class}" if css_class in {"opentech", "humanities"} else "secondary"
        track_items = [item for item in items if item.get("track") == track]
        inbox_items = [item for item in track_items if item.get("status") == "inbox"]
        track_sources = [source for source in sources if source.get("track") == track and source.get("status") != "archived"]
        fetchable_sources = [source for source in track_sources if is_fetchable_source(source)]
        source_types = Counter(source.get("source_type", "manual") for source in track_sources)
        source_groups = Counter(source.get("source_group", "未標示群組") for source in track_sources)
        recent_items = sorted(
            inbox_items,
            key=lambda item: (item.get("captured_at", ""), item.get("published_at", ""), item.get("title", "")),
            reverse=True,
        )[:12]

        item_rows = []
        for item in recent_items:
            title = item.get("title") or item.get("url") or "未命名項目"
            source_name = item.get("source_name") or item.get("author") or "未標示來源"
            captured = item.get("captured_at") or item.get("published_at") or "未標示日期"
            detail_href = item_detail_href(item)
            item_rows.append(
                f"""
<div class="list-item list-item--{h(css_class)}">
  <strong><a href="{h(detail_href)}">{h(title)}</a></strong>
  <p class="muted">{h(source_name)} · {h(captured)} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">開原文</a></p>
  <p class="break-anywhere">{h(clean_text(item.get('summary'), 180))}</p>
</div>
"""
            )
        if not item_rows:
            item_rows.append('<div class="list-item"><strong>目前沒有待整理項目</strong><p class="muted">等下一次 RSS 抓取或手動收藏後，會出現在這裡。</p></div>')

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
    <div><div class="metric">{len(track_items)}</div><div class="metric-label">全部項目</div></div>
    <div><div class="metric">{len(inbox_items)}</div><div class="metric-label">待整理</div></div>
    <div><div class="metric">{len(track_sources)}</div><div class="metric-label">來源</div></div>
    <div><div class="metric">{len(fetchable_sources)}</div><div class="metric-label">會自動抓</div></div>
  </div>
  <div class="button-row">
    <a class="button {h(button_class)}" href="/items/new?track={quote(track)}">幫這條主線加收藏</a>
    <a class="button secondary" href="/sources/new?track={quote(track)}">幫這條主線加 RSS</a>
    <a class="button quiet" href="/sources?track={quote(track)}">看這條主線的來源</a>
  </div>
  <p class="help">加收藏是單篇文章或頁面；加 RSS 是長期追蹤一個網站或 feed；看來源可以檢查目前追蹤清單。</p>
</div>

<div class="two-column">
  <section>
    <h2>待整理項目</h2>
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
        current_track = (query.get("track") or ["digital-humanities-local-knowledge"])[0]
        if current_track not in TRACK_META:
            current_track = "digital-humanities-local-knowledge"
        body = f"""
<h1>加入收藏</h1>
<p class="lede">用在你看到一篇文章、一個頁面或一個案例，想先丟進待整理清單時。這裡新增的是單筆知識項目，不是長期 RSS 來源。</p>
<form class="form-panel" method="post" action="/items">
  <label>主線</label>
  <select name="track">{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定它會出現在「開放科技」或「人文與在地知識」哪一個工作台。</p>
  <label>標題</label>
  <input name="title" value="{h(title)}" required>
  <p class="help">通常用原本網頁標題就好，之後審稿時再改成更清楚的標題。</p>
  <label>網址</label>
  <input name="url" value="{h(url)}" required>
  <p class="help">網址很長也沒關係，列表會自動換行。</p>
  <label>來源 / 網站 / 作者</label>
  <input name="source_name" placeholder="例如：報導者、Open Knowledge Foundation">
  <p class="help">不知道作者時，先填網站或組織名稱。</p>
  <label>發布日期</label>
  <input name="published_at" placeholder="YYYY-MM-DD">
  <p class="help">不確定可以留空，之後整理時再補。</p>
  <label>摘要或摘記</label>
  <textarea name="summary"></textarea>
  <p class="help">先貼一兩句你覺得重要的脈絡，方便未來審稿時想起來為什麼收。</p>
  <label>標籤</label>
  <input name="tags" placeholder="用逗號分隔">
  <p class="help">例如：開放資料, 地方創生, 博物館；不用一開始就很完整。</p>
  <label>備註 / 為什麼值得追</label>
  <textarea name="notes"></textarea>
  <p class="help">寫給未來的自己看：這則資料可能放進哪個議題、有哪些疑問。</p>
  <button type="submit">把這頁存進待整理</button>
  <p class="help">送出後會寫進 database/items.jsonl，狀態是 inbox，還不會自動發布。</p>
</form>
"""
        self.send_html("加入收藏", body)

    def save_item(self, data: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        url = form_value(data, "url")
        title = form_value(data, "title") or url
        if any(item.get("url") == url for item in items):
            self.send_html("已存在", f"<h1>這個網址已經在資料庫</h1><p>{h(url)}</p><p><a href='/'>回總覽</a></p>")
            return
        source_name = form_value(data, "source_name") or "Manual bookmark"
        track = form_value(data, "track", "unclassified")
        source_id = stable_id("src", "manual-web", source_name)
        if not any(source.get("id") == source_id for source in sources):
            append_jsonl(
                SOURCES,
                {
                    "id": source_id,
                    "track": track,
                    "name": source_name,
                    "source_group": "Manual web bookmark",
                    "source_type": "manual",
                    "feed_url": "",
                    "site_url": "",
                    "status": "active",
                    "notes": "由本機網頁加入。",
                },
            )
        tags = [tag.strip() for tag in form_value(data, "tags").split(",") if tag.strip()]
        notes = form_value(data, "notes")
        append_jsonl(
            ITEMS,
            {
                "id": stable_id("item", "manual-web", url, title),
                "track": track,
                "status": "inbox",
                "priority": "normal",
                "title": title,
                "url": url,
                "source_id": source_id,
                "source_name": source_name,
                "author": source_name,
                "published_at": form_value(data, "published_at"),
                "captured_at": datetime.now(timezone.utc).date().isoformat(),
                "summary": form_value(data, "summary"),
                "tags": tags,
                "origin": "manual-web",
                "reference": {"created_by": "local_web"},
                "review": default_review(notes),
            },
        )
        self.redirect("/?saved=item")

    def show_sources(self, query: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        track_filter = (query.get("track") or ["all"])[0]
        type_filter = (query.get("source_type") or ["all"])[0]
        status_filter = (query.get("status") or ["live"])[0]

        def matches(source: dict) -> bool:
            if track_filter != "all" and source.get("track") != track_filter:
                return False
            if type_filter != "all" and source.get("source_type") != type_filter:
                return False
            status = source.get("status")
            if status_filter == "live":
                return status != "archived"
            if status_filter != "all" and status != status_filter:
                return False
            return True

        filtered_sources = [source for source in sources if matches(source)]
        track_counts = {track: count_sources(sources, track) for track in TRACK_ORDER}
        fetch_counts = {track: count_sources(sources, track, active_only=True) for track in TRACK_ORDER}
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
            for group, group_sources in sorted(grouped[track].items()):
                rows = []
                for source in sorted(group_sources, key=lambda row: (row.get("name", ""), row.get("id", ""))):
                    source_type = source.get("source_type", "manual")
                    status = source.get("status", "")
                    feed_url = source.get("feed_url") or ""
                    site_url = source.get("site_url") or ""
                    type_class = source_type.replace("_", "-")
                    status_class = status.replace("_", "-")
                    site_link = ""
                    if site_url:
                        site_link = f'<br><a class="muted break-anywhere" href="{h(site_url)}" target="_blank" rel="noreferrer">{h(site_url)}</a>'
                    feed_display = '<span class="muted">沒有 feed URL</span>'
                    if feed_url:
                        feed_display = f'<code class="url">{h(feed_url)}</code>'
                    rows.append(
                        "<tr>"
                        f"<td><strong>{h(source.get('name'))}</strong>"
                        f"{site_link}</td>"
                        f"<td>{badge(source_type_label(source_type), type_class)}</td>"
                        f"<td>{badge(source_status_label(status), status_class)}</td>"
                        f"<td class='url-cell'>{feed_display}</td>"
                        f"<td><a href='/sources/edit?id={quote(source.get('id', ''))}'>編輯</a></td>"
                        "</tr>"
                    )
                source_sections.append(
                    f"""
<details class="source-group" open>
  <summary>{h(group)} <span class="muted">({len(group_sources)})</span></summary>
  <table>
    <thead><tr><th>名稱</th><th>類型</th><th>狀態</th><th>Feed URL</th><th></th></tr></thead>
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
    <div><div class="metric">{track_counts.get(track, 0)}</div><div class="metric-label">來源</div></div>
    <div><div class="metric">{fetch_counts.get(track, 0)}</div><div class="metric-label">會自動抓</div></div>
  </div>
  <p class="help">會自動抓代表狀態是啟用，且類型是 RSS、Google 快訊、YouTube 或 Podcast。</p>
</div>
"""
            )
        body = f"""
<h1>RSS 來源分類</h1>
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
  </div>
  <p class="help">篩選只改變畫面，不會改資料。新增 RSS 才會寫入 database/sources.jsonl。</p>
</form>
<h2>目前列表</h2>
<p class="muted">符合條件：{len(filtered_sources)} 個來源。{''.join(type_summary) if type_summary else ''}</p>
{''.join(source_sections)}
"""
        self.send_html("RSS 來源", body)

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
        body = f"""
<h1>{h(title)}</h1>
<p class="lede">用在你想長期追蹤一個網站、Google 快訊、YouTube 頻道或 Podcast 時。RSS / Google 快訊 / YouTube / Podcast 會被每天的抓取流程處理。</p>
<form class="form-panel" method="post" action="/sources">
  <input type="hidden" name="id" value="{h(source_id)}">
  <label>主線</label>
  <select name="track">{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定來源會出現在開放科技、人文與在地知識，或未分類清單。</p>
  <label>名稱</label>
  <input name="name" value="{h(source.get('name', ''))}" required>
  <p class="help">填你看得懂的短名稱，例如網站名、作者名或頻道名。</p>
  <label>來源群組</label>
  <input name="source_group" value="{h(source.get('source_group', 'Manual RSS'))}">
  <p class="help">把同一批來源放在一起，例如「OpenTech RSS」「縣市政府文化局」。來源列表會用這個分組。</p>
  <label>來源類型</label>
  <select name="source_type">{source_type_options(current_type)}</select>
  <p class="help">{h(SOURCE_TYPE_HELP.get(current_type, "RSS / Google 快訊 / YouTube / Podcast 會被自動抓；其他類型目前用來保留脈絡。"))}</p>
  <label>狀態</label>
  <select name="status">{source_status_options(current_status)}</select>
  <p class="help">啟用會進入每日抓取；暫停會保留但不抓；封存代表這個來源暫時不再顯示。</p>
  <label>Feed URL</label>
  <input name="feed_url" value="{h(source.get('feed_url', ''))}" placeholder="https://example.com/feed.xml">
  <p class="help">RSS / Google 快訊 / YouTube / Podcast 請填這欄。Facebook、舊 Inoreader monitor 或既有表格來源可以留空作為紀錄。</p>
  <label>Site URL</label>
  <input name="site_url" value="{h(source.get('site_url', ''))}" placeholder="https://example.com/">
  <p class="help">原始網站首頁，方便之後回去確認來源脈絡。</p>
  <label>備註</label>
  <textarea name="notes">{h(source.get('notes', ''))}</textarea>
  <p class="help">可以寫為什麼要追、頻率如何、是不是從 Inoreader 舊流程轉來。</p>
  <button type="submit">儲存這個來源</button>
  <p class="help">送出後會寫進 database/sources.jsonl。要真的抓新資料，可以回首頁按「現在抓新資料」。</p>
</form>
"""
        self.send_html(title, body)

    def save_source(self, data: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        existing_id = form_value(data, "id")
        record = {
            "id": existing_id or stable_id("src", form_value(data, "source_group"), form_value(data, "name"), form_value(data, "feed_url")),
            "track": form_value(data, "track", "unclassified"),
            "name": form_value(data, "name"),
            "source_group": form_value(data, "source_group", "Manual RSS"),
            "source_type": form_value(data, "source_type", "rss"),
            "feed_url": form_value(data, "feed_url"),
            "site_url": form_value(data, "site_url"),
            "status": form_value(data, "status", "active"),
            "notes": form_value(data, "notes"),
        }
        if existing_id:
            sources = [record if source.get("id") == existing_id else source for source in sources]
        else:
            if record["feed_url"] and any(source.get("feed_url") == record["feed_url"] for source in sources):
                self.send_html("已存在", f"<h1>這個 RSS 已存在</h1><p>{h(record['feed_url'])}</p><p><a href='/sources'>回來源列表</a></p>")
                return
            sources.append(record)
        sources.sort(key=lambda row: (row.get("source_group", ""), row.get("name", ""), row.get("id", "")))
        write_jsonl(SOURCES, sources)
        self.redirect(f"/sources?track={quote(record['track'])}")

    def run_command(self, data: dict[str, list[str]]) -> None:
        command_name = form_value(data, "command")
        config = COMMANDS.get(command_name)
        if not config:
            self.send_html("不允許的指令", "<h1>不允許的指令</h1>", HTTPStatus.BAD_REQUEST)
            return
        command = config["command"]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=600)
        output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        body = f"""
<h1>{h(config['label'])}</h1>
<p class="muted">Exit code: {result.returncode}</p>
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping")


if __name__ == "__main__":
    main()
