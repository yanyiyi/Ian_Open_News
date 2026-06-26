from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TASTE_PROFILE = Path(__file__).resolve().parents[1] / "database" / "taste-profile.json"


def load_taste_profile() -> dict[str, Any]:
    """讀 taste-profile.json，缺檔或壞檔回安全預設（不影響計分）。"""
    if not TASTE_PROFILE.exists():
        return {"global": {}, "tracks": {}, "learned_signals": []}
    try:
        data = json.loads(TASTE_PROFILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"global": {}, "tracks": {}, "learned_signals": []}
    if not isinstance(data, dict):
        return {"global": {}, "tracks": {}, "learned_signals": []}
    data.setdefault("global", {})
    data.setdefault("tracks", {})
    return data


TRACK_LABELS = {
    "digital-humanities-local-knowledge": "數位人文與在地知識建構",
    "open-tech-open-industry": "開放科技與開放產業發展",
    "unclassified": "未分類",
}

TRACK_CORE_HINTS = {
    "digital-humanities-local-knowledge": "地方知識、文化記憶、典藏、文資或社群共筆脈絡",
    "open-tech-open-industry": "開源、開放資料、資料治理、標準、授權或公共數位基礎建設脈絡",
    "unclassified": "尚待人工分流的知識脈絡",
}

SMALL_NEWS_CUES = [
    "宣布",
    "發布",
    "推出",
    "上線",
    "修法",
    "通過",
    "公告",
    "罰款",
    "fined",
    "launch",
    "release",
    "announces",
]

FEATURED_CUES = [
    "研究",
    "報告",
    "案例",
    "白皮書",
    "指引",
    "指南",
    "框架",
    "dataset",
    "governance",
    "standard",
    "framework",
]

LOW_VALUE_CUES = [
    "抽獎",
    "優惠",
    "促銷",
    "徵才",
    "人事異動",
    "交通管制",
    "交通疏導",
    "停水",
    "停電",
    "天氣",
    "路況",
    "工程公告",
    "報名",
    "活動時間",
    "名額",
]

ENGLISH_TITLE_HINTS = {
    "open source": "開源",
    "open data": "開放資料",
    "data": "資料",
    "ai": "AI",
    "governance": "治理",
    "privacy": "隱私",
    "security": "資安",
    "standard": "標準",
    "standards": "標準",
    "license": "授權",
    "licensing": "授權",
    "government": "政府",
    "public": "公共",
    "digital": "數位",
    "infrastructure": "基礎建設",
    "culture": "文化",
    "heritage": "文化資產",
    "archive": "檔案",
    "museum": "博物館",
    "community": "社群",
    "local": "在地",
}


def clean_text(value: object, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def normalized(value: object) -> str:
    return clean_text(value).casefold()


def has_cjk(value: object) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def mostly_english(value: object) -> bool:
    text = clean_text(value)
    if not text:
        return False
    letters = len(re.findall(r"[A-Za-z]", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return letters >= 8 and letters > cjk * 2


def record_text(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            clean_text(record.get("title")),
            clean_text(record.get("summary")),
            clean_text(record.get("source_name")),
            clean_text(record.get("author")),
            " ".join(clean_text(tag) for tag in record.get("tags", []) if tag),
            clean_text(record.get("url")),
        ]
    )


def tags_for(record: dict[str, Any]) -> list[str]:
    return [clean_text(tag, 80) for tag in record.get("tags", []) if clean_text(tag)]


def source_key(record: dict[str, Any]) -> str:
    return clean_text(record.get("source_name") or record.get("author"), 120)


def local_decision_action(record: dict[str, Any]) -> str:
    decision = record.get("local_decision")
    if not isinstance(decision, dict):
        return ""
    return clean_text(decision.get("action"))


def is_rejected_record(record: dict[str, Any]) -> bool:
    return local_decision_action(record) == "rejected"


def is_prior_collection_record(record: dict[str, Any]) -> bool:
    action = local_decision_action(record)
    if action in {"accepted-for-editing", "direct-pr-small-news", "revisit-with-personal-notes"}:
        return True
    if record.get("status") in {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}:
        return True
    origin = clean_text(record.get("origin"))
    return origin.startswith("xlsx:")


def parse_record_date(record: dict[str, Any]) -> date | None:
    value = clean_text(record.get("published_at") or record.get("captured_at"))
    if not value:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", value):
        number = float(value)
        if 20000 <= number <= 60000:
            return date(1899, 12, 30) + timedelta(days=int(number))
    normalized_value = value.replace("/", "-").replace(".", "-")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized_value)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def build_editorial_context(records: list[dict[str, Any]], keyword_config: dict[str, Any]) -> dict[str, Any]:
    prior_records = [record for record in records if is_prior_collection_record(record)]
    rejected_records = [record for record in records if is_rejected_record(record)]

    prior_tags: Counter[str] = Counter()
    prior_sources: Counter[str] = Counter()
    rejected_tags: Counter[str] = Counter()
    rejected_sources: Counter[str] = Counter()
    rejected_reasons: Counter[str] = Counter()

    for record in prior_records:
        prior_tags.update(tags_for(record))
        source = source_key(record)
        if source:
            prior_sources[source] += 1

    for record in rejected_records:
        rejected_tags.update(tags_for(record))
        source = source_key(record)
        if source:
            rejected_sources[source] += 1
        decision = record.get("local_decision") or {}
        reason = clean_text(decision.get("reason"), 120) if isinstance(decision, dict) else ""
        if reason:
            rejected_reasons[reason] += 1

    taste = load_taste_profile()
    personal_beats = [b.get("beat") or b.get("signal", "") for b in (taste.get("personal_beats") or [])]
    personal_beats = [b for b in personal_beats if b]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "keyword_config_version": keyword_config.get("version", 1),
        "prior_tags": prior_tags,
        "prior_sources": prior_sources,
        "rejected_tags": rejected_tags,
        "rejected_sources": rejected_sources,
        "rejected_reasons": rejected_reasons,
        "prior_count": len(prior_records),
        "rejected_count": len(rejected_records),
        "taste_profile": taste,
        "personal_beats": personal_beats,
    }


def evaluate_taste_fit(text: str, tags: list[str], track: str, taste: dict[str, Any]) -> tuple[int, list[str]]:
    """命中品味偏好主題 +1/個、避開主題 -1/個。回傳 (score, signals)。只用來往「收」的方向微調。"""
    track_meta = (taste.get("tracks") or {}).get(track) or {}
    priority = [t for t in (track_meta.get("priority_themes") or []) if t]
    avoid = [t for t in (track_meta.get("avoid_themes") or []) if t]
    haystack = (text or "") + " " + " ".join(tags or [])
    signals: list[str] = []
    score = 0
    hit_priority = [t for t in priority if t in haystack]
    hit_avoid = [t for t in avoid if t in haystack]
    if hit_priority:
        score += len(hit_priority)
        signals.append("命中偏好主題：" + "、".join(hit_priority[:6]))
    if hit_avoid:
        score -= len(hit_avoid)
        signals.append("命中避開主題：" + "、".join(hit_avoid[:6]))
    g = taste.get("global") or {}
    if g.get("taiwan_context_required") and ("台灣" in haystack or "臺灣" in haystack):
        score += 1
        signals.append("含台灣脈絡（品味設為必要）")
    return score, signals


def cue_matches(text: str, cues: list[str]) -> list[str]:
    haystack = normalized(text)
    matches = [cue for cue in cues if normalized(cue) and normalized(cue) in haystack]
    return list(dict.fromkeys(matches))


def overlap_signals(values: list[str], counter: Counter[str], label: str, limit: int = 4) -> list[str]:
    matches = [value for value in values if counter.get(value, 0)]
    matches.sort(key=lambda value: counter.get(value, 0), reverse=True)
    return [f"{label}「{value}」曾出現 {counter[value]} 次" for value in matches[:limit]]


def content_kind(record: dict[str, Any]) -> str:
    action = local_decision_action(record)
    if action == "direct-pr-small-news":
        return "small-news"
    if action in {"accepted-for-editing", "revisit-with-personal-notes"}:
        return "featured-article"
    text = record_text(record)
    featured = cue_matches(text, FEATURED_CUES)
    news = cue_matches(text, SMALL_NEWS_CUES)
    summary_length = len(clean_text(record.get("summary")))
    if featured or summary_length >= 700:
        return "featured-article"
    if news or summary_length <= 240:
        return "small-news"
    return "needs-review"


def content_kind_label(kind: str) -> str:
    if kind == "featured-article":
        return "值得收錄的精選文章"
    if kind == "small-news":
        return "純事實新聞 / 小消息"
    return "需要人工判斷"


def recommendation_label(recommendation: str) -> str:
    if recommendation == "suggest-collect":
        return "建議收錄"
    if recommendation == "suggest-review":
        return "建議人工看過"
    if recommendation == "suggest-skip":
        return "建議不要看"
    if recommendation == "suggest-ask":
        return "命中個人 beat，請確認"
    return "未判斷"


def sentence_parts(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s+|(?<=[。！？!?])|(?<=\.)\s+", text)
    return [clean_text(part) for part in parts if clean_text(part)]


def keyword_topic(record: dict[str, Any], triage: dict[str, Any]) -> str:
    matched = [clean_text(keyword) for keyword in triage.get("matched_keywords", []) if clean_text(keyword)]
    if matched:
        return "、".join(matched[:4])
    tags = tags_for(record)
    if tags:
        return "、".join(tags[:3])
    return TRACK_LABELS.get(record.get("track", "unclassified"), "這條主線")


def zh_title_for(record: dict[str, Any], triage: dict[str, Any]) -> str:
    title = clean_text(record.get("title"), 180)
    if not title:
        return "未命名資料"
    if has_cjk(title):
        return title
    return title


def zh_summary_for(record: dict[str, Any], triage: dict[str, Any], kind: str, zh_title: str) -> str:
    summary = clean_text(record.get("summary"), 900)
    title = clean_text(record.get("title"), 180)
    topic = keyword_topic(record, triage)
    kind_text = content_kind_label(kind)
    if has_cjk(summary):
        sentences = sentence_parts(summary)
        body = "".join(sentences[:2]) or summary
        return clean_text(f"中文標題：{zh_title}\n中文摘要：{body}", 620)
    if has_cjk(title):
        return clean_text(
            f"中文標題：{zh_title}\n中文摘要：這則資料和「{topic}」有關，初步類型是「{kind_text}」。"
            "原文摘要偏英文或不足，後續若要送 PR，請先補完整中文摘要與查核重點。",
            620,
        )
    english_sentences = sentence_parts(summary)
    evidence = english_sentences[0] if english_sentences else title
    return clean_text(
        f"中文標題：{zh_title}\n中文摘要：這是一篇英文資料，主題可能和「{topic}」有關，初步類型是「{kind_text}」。"
        f"原文重點線索：{evidence}。後續若要整理，請用 skill 補完整中文摘要、台灣/OCF 關聯與查核結果。",
        620,
    )


def evaluate_editorial_triage(
    record: dict[str, Any],
    keyword_config: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    triage = record.get("triage") or {}
    text = record_text(record)
    tags = tags_for(record)
    source = source_key(record)
    track = clean_text(record.get("track") or "unclassified")
    track_label = TRACK_LABELS.get(track, track)
    matched_keywords = [clean_text(keyword) for keyword in triage.get("matched_keywords", []) if clean_text(keyword)]
    skip_keywords = [clean_text(keyword) for keyword in triage.get("skip_keywords", []) if clean_text(keyword)]
    low_value_matches = cue_matches(text, LOW_VALUE_CUES)
    kind = content_kind(record)

    keyword_score = (len(matched_keywords) * 2) - (len(skip_keywords) * 3)
    if triage.get("recommendation") == "suggest-skip" and not matched_keywords:
        keyword_score -= 1

    prior_signals = []
    if source and context["prior_sources"].get(source, 0):
        prior_signals.append(f"來源「{source}」曾被收錄 {context['prior_sources'][source]} 次")
    prior_signals.extend(overlap_signals(tags, context["prior_tags"], "標籤"))
    if clean_text(record.get("origin")).startswith("xlsx:"):
        prior_signals.append("來自舊 Excel 跟追表，屬於既有知識整理來源")
    prior_score = min(5, len(prior_signals))

    deletion_signals = []
    if source and context["rejected_sources"].get(source, 0):
        deletion_signals.append(f"來源「{source}」也曾出現在不收紀錄 {context['rejected_sources'][source]} 次")
    deletion_signals.extend(overlap_signals(tags, context["rejected_tags"], "標籤", limit=3))
    if skip_keywords:
        deletion_signals.append(f"命中排除關鍵字：{'、'.join(skip_keywords[:6])}")
    if low_value_matches:
        deletion_signals.append(f"內容像公告/低價值訊號：{'、'.join(low_value_matches[:6])}")
    published = parse_record_date(record)
    if published and (date.today() - published).days >= 730 and clean_text(record.get("origin")) == "inoreader-starred":
        deletion_signals.append("Inoreader 舊收藏且發布超過兩年，容易只是歷史待清資料")
    deletion_score = min(6, len(deletion_signals) + len(skip_keywords))

    taste_score, taste_signals = evaluate_taste_fit(text, tags, track, context.get("taste_profile") or {})

    if deletion_score >= 3 and keyword_score <= 2:
        recommendation = "suggest-skip"
    elif keyword_score >= 2 and deletion_score == 0 and prior_score >= 1:
        recommendation = "suggest-collect"
    elif keyword_score >= 1 and deletion_score <= 2:
        recommendation = "suggest-review"
    elif prior_score >= 3 and deletion_score <= 1:
        recommendation = "suggest-review"
    else:
        recommendation = "suggest-skip"

    # 品味微調：只往「收」的方向。命中偏好且非明確該刪時，把 skip 升為 review，降低誤刪。
    if taste_score >= 2 and recommendation == "suggest-skip" and deletion_score < 3:
        recommendation = "suggest-review"
        taste_signals.append("因符合個人品味，從建議略過上修為建議人工看過")

    # personal-beat 保護層：命中使用者明示的個人 beat 主題時，輸出 suggest-ask 而非 skip。
    # 只在 deletion_score < 4 且尚為 suggest-skip 時觸發，避免和明確 spam 衝突。
    if recommendation == "suggest-skip" and deletion_score < 4:
        personal_beats = context.get("personal_beats") or []
        beat_hits = [b for b in personal_beats if b and normalized(b) and normalized(b) in normalized(text)]
        if beat_hits:
            recommendation = "suggest-ask"
            taste_signals.append("命中個人 beat 主題：" + "、".join(beat_hits[:4]) + "；請確認是否值得追蹤")

    confidence_points = 0
    confidence_points += 2 if abs(keyword_score) >= 3 else 1 if abs(keyword_score) >= 1 else 0
    confidence_points += 1 if prior_score >= 2 else 0
    confidence_points += 1 if deletion_score >= 2 else 0
    confidence = "high" if confidence_points >= 4 else "medium" if confidence_points >= 2 else "low"

    reasons: list[str] = []
    if matched_keywords:
        reasons.append(f"命中「{track_label}」關鍵字：{'、'.join(matched_keywords[:6])}。")
    else:
        reasons.append(f"尚未命中「{track_label}」保留關鍵字，需要人工補判斷。")
    if prior_signals:
        reasons.append(f"和過去收錄資料相近：{prior_signals[0]}。")
    else:
        reasons.append("和過去已收錄來源或標籤的相似度不高，適合先快速掃讀。")
    if kind == "featured-article":
        reasons.append("摘要或內容訊號偏研究、案例、指引或背景材料，可能值得進入精選文章流程。")
    elif kind == "small-news":
        reasons.append("內容偏事件或短訊，若查核無誤，可走小消息直接 PR 流程。")
    else:
        reasons.append(f"可先確認是否能連到{TRACK_CORE_HINTS.get(track, '主線脈絡')}。")

    if recommendation == "suggest-skip":
        next_step = "若沒有人工補充觀點，建議按不收並記錄原因。"
        view_reasons: list[str] = []
        summary_reason = deletion_signals[0] if deletion_signals else "關鍵字與既有收錄特徵不足，先建議不要看。"
    elif kind == "small-news":
        next_step = "先做事實查核；如果只是短訊，可標記直接送 PR（小消息）。"
        view_reasons = reasons[:3]
        summary_reason = "符合主線或既有收錄線索，可人工判斷是否作為小消息。"
    else:
        next_step = "人工看過後，若值得收錄就送 skill 做切角、摘要與文章編修。"
        view_reasons = reasons[:3]
        summary_reason = "符合主線或既有收錄線索，可人工判斷是否進精選流程。"

    zh_title = zh_title_for(record, triage)
    zh_summary = zh_summary_for(record, triage, kind, zh_title)

    return {
        "version": 1,
        "generated_at": context["generated_at"],
        "method": "local-rules-keywords-history",
        "recommendation": recommendation,
        "recommendation_label": recommendation_label(recommendation),
        "confidence": confidence,
        "content_kind": kind,
        "content_kind_label": content_kind_label(kind),
        "zh_title": zh_title,
        "zh_summary": zh_summary,
        "view_reasons": view_reasons,
        "summary_reason": summary_reason,
        "keyword_fit": {
            "score": keyword_score,
            "matched_keywords": matched_keywords,
            "skip_keywords": skip_keywords,
            "judgement": triage.get("reason", "尚未有關鍵字判斷。"),
        },
        "deletion_pattern_fit": {
            "score": deletion_score,
            "signals": deletion_signals[:6],
            "judgement": "越高越像過去不收或低價值資料。",
        },
        "prior_collection_fit": {
            "score": prior_score,
            "signals": prior_signals[:6],
            "judgement": "越高越像過去已收錄或值得保留的資料。",
        },
        "taste_fit": {
            "score": taste_score,
            "signals": taste_signals[:6],
            "judgement": "越高越符合個人品味；只用來往收的方向微調，降低誤刪。",
        },
        "next_step_hint": next_step,
    }
