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

ACTIVITY_PROMOTION_CUES = ["年會", "論壇", "盛大登場", "邀請", "助攻", "立即報名", "早鳥報名", "免費參加", "招商"]
SUBSTANTIVE_GOVERNANCE_CUES = ["法案", "立法", "法規", "規則", "標準", "問責", "調查", "裁罰", "衝突", "制度變動", "修法"]
INSTITUTIONAL_GOVERNANCE_CUES = ["governance architecture", "governance", "制度設計", "治理架構", "標準制定", "rulemaking", "問責", "accountability", "程序", "申訴", "age assurance", "digital sovereignty", "數位主權"]
PLATFORM_DEPENDENCY_CUES = ["runtime", "local llm", "local model", "本地部署", "platform", "平台", "cloud", "雲端", "model access", "模型接入", "ollama"]
DEPENDENCY_CONCERN_CUES = ["vendor lock-in", "供應商鎖定", "switching cost", "轉換成本", "portability", "可攜性", "model choice", "模型選擇", "dependency", "依賴", "keep running", "持續運行", "worst way"]
INTEREST_NOTE_CUES = ["會好奇", "值得看", "很重要"]

# 已知商業／顧問來源：這些來源常觸發語氣負分，但常含可萃取的政策/治理/開源社會責任概念。
# 命中時不直接否決，先查前段是否有可萃取概念（見 evaluate_editorial_triage 商業萃取層）。
COMMERCIAL_SOURCE_HINTS = [
    "mckinsey", "麥肯錫", "deloitte", "勤業眾信", "pwc", "資誠", "kpmg", "安侯",
    "ernst", "安永", "accenture", "埃森哲", "gartner", "forrester", "bcg", "bain",
    "google", "microsoft", "amazon", "aws", "ibm", "oracle", "salesforce",
    "nvidia", "meta", "openai", "anthropic",
]

HISTORY_CALIBRATION_DEFAULTS = {
    "enabled": True,
    "window_days": 45,
    "low_acceptance_rate": 0.08,
    "min_source_total": 20,
    "min_keyword_total": 20,
}

# 跨篇關聯：與庫中 researching/drafting 稿件共用幾個 tag 才算可互為佐證
XREF_TAG_THRESHOLD = 2

# 命名事件串：同一具名事件在短時間內累積多篇後續稿時，即使單篇密度低也先問。
NAMED_EVENT_LOOKBACK_DAYS = 21
NAMED_EVENT_CONTEXT_LIMIT = 5
GENERIC_EVENT_KEYS = {
    "ai",
    "artificial intelligence",
    "data",
    "digital",
    "education",
    "framework",
    "governance",
    "government",
    "hub",
    "model",
    "models",
    "open source",
    "open-source",
    "opensource",
    "program office",
    "registry",
    "rss",
    "security",
    "technology",
    "developer tool",
    "large language model",
    "llm",
    "local model",
    "open source ai",
    "open source governance",
    "responsible ai",
    "cybersecurity",
    "data extraction",
    "data governance",
    "evidence production",
    "the",
    "us",
    "u.s.",
    "uk",
    "eu",
    "editors choice",
    "editor's choice",
    "editors' choice",
    "digital humanities now",
    "anthropic",
    "github",
    "google",
    "microsoft",
    "開放資料",
    "資料治理",
    "數據治理",
    "資料流程",
    "資料抽取",
    "資料抽取治理",
    "結構化抽取",
    "開源",
    "開源 ai",
    "開源 ai 模型",
    "開放原始碼",
    "資安",
    "供應鏈",
    "證據生產",
    "證據品質",
    "ai 教育",
    "本地模型",
    "推論框架",
    "中立市場",
}
EVENT_LEADING_WORDS = {
    "after",
    "before",
    "how",
    "the",
    "a",
    "an",
    "your",
    "our",
    "my",
    "i",
    "why",
    "what",
    "when",
    "where",
    "editors",
    "editor's",
    "editors'",
    "choice",
}

EVENT_ENTITY_PATTERNS = [
    re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:[-.][A-Z0-9]+)*(?:\s+[0-9][A-Za-z0-9.]*)?\b"),
    re.compile(r"\b[A-Z][A-Za-z]+(?:\s+[0-9][A-Za-z0-9.]*)+\b"),
    re.compile(r"\b[A-Z][A-Za-z0-9]+(?:[- ][A-Z][A-Za-z0-9]+){1,4}(?:\s+[0-9][A-Za-z0-9.]*)?\b"),
    re.compile(r"[「『《]([^」』》]{3,40})[」』》]"),
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


def history_calibration_settings(taste: dict[str, Any]) -> dict[str, Any]:
    global_cfg = taste.get("global") if isinstance(taste.get("global"), dict) else {}
    cfg = global_cfg.get("history_calibration") if isinstance(global_cfg, dict) else {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {**HISTORY_CALIBRATION_DEFAULTS, **cfg}


def cfg_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default


def cfg_float(config: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def cfg_terms(config: dict[str, Any], key: str) -> list[str]:
    terms = config.get(key) or []
    if not isinstance(terms, list):
        return []
    return [clean_text(term) for term in terms if clean_text(term)]


def matched_keyword_keys(record: dict[str, Any]) -> list[str]:
    triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
    keys = [normalized(keyword) for keyword in (triage.get("matched_keywords") or []) if normalized(keyword)]
    return list(dict.fromkeys(keys))


def low_acceptance_signal(
    label: str,
    accepted: int,
    rejected: int,
    *,
    min_total: int,
    low_rate: float,
    window_days: int,
) -> str:
    total = accepted + rejected
    if total < min_total:
        return ""
    rate = accepted / total if total else 0
    if rate > low_rate:
        return ""
    return f"{label}近 {window_days} 天收下率 {accepted}/{total}（{rate * 100:.0f}%）"


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


def source_is_blocked(source: str, taste: dict[str, Any]) -> bool:
    global_cfg = taste.get("global") if isinstance(taste.get("global"), dict) else {}
    blocked = global_cfg.get("source_blocklist") if isinstance(global_cfg, dict) else []
    return normalized(source) in {normalized(value) for value in blocked if normalized(value)}


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


def normalize_event_key(value: object) -> str:
    text = clean_text(value)
    text = re.sub(r"^[\s\"'“”‘’《》「」『』()[\]{}:：]+", "", text)
    text = re.sub(r"[\s\"'“”‘’《》「」『』()[\]{}:：,，.。;；!?！？]+$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def trim_event_phrase(value: object) -> str:
    text = clean_text(value)
    text = re.sub(r"^[\s\"'“”‘’《》「」『』()[\]{}:：]+", "", text)
    text = re.sub(r"[\s\"'“”‘’《》「」『』()[\]{}:：,，.。;；!?！？]+$", "", text)
    words = text.split()
    while words and normalize_event_key(words[0]) in EVENT_LEADING_WORDS:
        words.pop(0)
    while words and normalize_event_key(words[-1]) in EVENT_LEADING_WORDS:
        words.pop()
    return " ".join(words) if words else text


def is_named_event_key(value: object, *, from_keyword: bool = False) -> bool:
    text = trim_event_phrase(value)
    norm = normalize_event_key(text)
    if not norm or norm in GENERIC_EVENT_KEYS:
        return False
    if len(norm) < 3:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        event_markers = ("管制", "組織", "法案", "委員會", "聯盟", "制度", "計畫")
        return len(text) >= 4 and any(marker in text for marker in event_markers)
    if re.search(r"\d", text):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9]{2,}(?:[-.][A-Z0-9]+)*", text):
        return True
    if "-" in text and re.search(r"[A-Za-z]", text):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z0-9.']*", text)
    if len(words) >= 2 and len(norm) >= 8:
        meaningful = [w for w in words if normalize_event_key(w) not in GENERIC_EVENT_KEYS]
        return len(meaningful) >= 1
    if from_keyword and len(words) == 1 and len(words[0]) >= 4 and words[0][0].isupper():
        return True
    return False


def add_named_event_key(keys: dict[str, str], value: object, *, from_keyword: bool = False) -> None:
    text = trim_event_phrase(value)
    if not is_named_event_key(text, from_keyword=from_keyword):
        return
    norm = normalize_event_key(text)
    if norm and norm not in keys:
        keys[norm] = clean_text(text, 80)


def track_keyword_pool(keyword_config: dict[str, Any], track: str) -> list[str]:
    tracks = keyword_config.get("tracks") or {}
    configs = []
    if track and isinstance(tracks.get(track), dict):
        configs.append(tracks[track])
    if not configs:
        configs.extend(cfg for cfg in tracks.values() if isinstance(cfg, dict))
    keywords: list[str] = []
    for cfg in configs:
        keywords.extend(cfg.get("keep_keywords") or [])
        keywords.extend(cfg.get("mechanism_keywords") or [])
    return [clean_text(keyword) for keyword in keywords if clean_text(keyword)]


def named_event_keys_for(record: dict[str, Any], keyword_config: dict[str, Any]) -> dict[str, str]:
    keys: dict[str, str] = {}
    triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
    for keyword in [*(triage.get("matched_keywords") or []), *(triage.get("mechanism_keywords") or [])]:
        add_named_event_key(keys, keyword, from_keyword=True)

    text = record_text(record)
    norm_text = normalized(text)
    track = clean_text(record.get("track") or "unclassified")
    for keyword in track_keyword_pool(keyword_config, track):
        if normalized(keyword) and normalized(keyword) in norm_text:
            add_named_event_key(keys, keyword, from_keyword=True)

    title = clean_text(record.get("title") or record.get("editorial_title"))
    for pattern in EVENT_ENTITY_PATTERNS:
        for match in pattern.finditer(title):
            phrase = match.group(1) if match.lastindex else match.group(0)
            add_named_event_key(keys, phrase)
    return keys


def build_named_event_index(
    prior_records: list[dict[str, Any]],
    keyword_config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for record in prior_records:
        record_date = parse_record_date(record)
        if not record_date:
            continue
        keys = named_event_keys_for(record, keyword_config)
        if not keys:
            continue
        entry = {
            "id": clean_text(record.get("id")),
            "title": clean_text(record.get("editorial_title") or record.get("title"), 120),
            "date": record_date,
        }
        for key, label in keys.items():
            index.setdefault(key, []).append({**entry, "label": label})
    for key, entries in index.items():
        entries.sort(key=lambda entry: entry["date"], reverse=True)
        index[key] = entries[:NAMED_EVENT_CONTEXT_LIMIT]
    return index


def named_event_chain_hits(
    record: dict[str, Any],
    keyword_config: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, str]]:
    event_index = context.get("named_event_index") or {}
    if not event_index:
        return []
    cur_id = clean_text(record.get("id"))
    cur_title = normalize_event_key(record.get("editorial_title") or record.get("title"))
    cur_date = parse_record_date(record) or date.today()
    hits: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key, label in named_event_keys_for(record, keyword_config).items():
        for prior in event_index.get(key, []):
            prior_id = clean_text(prior.get("id"))
            if prior_id and prior_id == cur_id:
                continue
            prior_title = normalize_event_key(prior.get("title"))
            if prior_title and prior_title == cur_title:
                continue
            prior_date = prior.get("date")
            if isinstance(prior_date, date) and abs((cur_date - prior_date).days) > NAMED_EVENT_LOOKBACK_DAYS:
                continue
            marker = (key, prior_id or prior_title)
            if marker in seen:
                continue
            seen.add(marker)
            hits.append({
                "label": label,
                "title": clean_text(prior.get("title"), 80),
                "id": prior_id,
            })
            if len(hits) >= 3:
                return hits
    return hits


def build_editorial_context(records: list[dict[str, Any]], keyword_config: dict[str, Any]) -> dict[str, Any]:
    taste = load_taste_profile()
    history_cfg = history_calibration_settings(taste)
    history_window_days = max(0, cfg_int(history_cfg, "window_days", HISTORY_CALIBRATION_DEFAULTS["window_days"]))
    history_since = date.today() - timedelta(days=history_window_days) if history_window_days else None

    def in_history_window(record: dict[str, Any]) -> bool:
        if history_cfg.get("enabled") is False:
            return False
        if history_since is None:
            return True
        record_date = parse_record_date(record)
        return bool(record_date and record_date >= history_since)

    prior_records = [record for record in records if is_prior_collection_record(record)]
    rejected_records = [record for record in records if is_rejected_record(record)]

    prior_tags: Counter[str] = Counter()
    prior_sources: Counter[str] = Counter()
    rejected_tags: Counter[str] = Counter()
    rejected_sources: Counter[str] = Counter()
    rejected_reasons: Counter[str] = Counter()
    history_prior_sources: Counter[str] = Counter()
    history_rejected_sources: Counter[str] = Counter()
    history_prior_keywords: Counter[str] = Counter()
    history_rejected_keywords: Counter[str] = Counter()

    for record in prior_records:
        prior_tags.update(tags_for(record))
        source = source_key(record)
        if source:
            prior_sources[source] += 1
            if in_history_window(record):
                history_prior_sources[source] += 1
        if in_history_window(record):
            history_prior_keywords.update(matched_keyword_keys(record))

    for record in rejected_records:
        rejected_tags.update(tags_for(record))
        source = source_key(record)
        if source:
            rejected_sources[source] += 1
            if in_history_window(record):
                history_rejected_sources[source] += 1
        if in_history_window(record):
            history_rejected_keywords.update(matched_keyword_keys(record))
        decision = record.get("local_decision") or {}
        reason = clean_text(decision.get("reason"), 120) if isinstance(decision, dict) else ""
        if reason:
            rejected_reasons[reason] += 1

    named_event_index = build_named_event_index(prior_records, keyword_config)

    personal_beats = [b.get("beat") or b.get("signal", "") for b in (taste.get("personal_beats") or [])]
    personal_beats = [b for b in personal_beats if b]

    # tracked_beats：長期追蹤線（每條含關鍵字清單），命中時強制 suggest-ask 監測
    tracked_beats = []
    for tb in (taste.get("tracked_beats") or []):
        name = clean_text(tb.get("beat"))
        kws = [normalized(k) for k in (tb.get("keywords") or []) if normalized(k)]
        if name and kws:
            tracked_beats.append({"beat": name, "keywords": kws})

    interest_terms: Counter[str] = Counter()
    for record in prior_records:
        record_date = parse_record_date(record)
        if not record_date or (date.today() - record_date).days > 30:
            continue
        decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
        note = clean_text(decision.get("reason"))
        if not any(cue in note for cue in INTEREST_NOTE_CUES):
            continue
        interest_terms.update(normalized(tag) for tag in tags_for(record) if len(normalized(tag)) >= 4)
        interest_terms.update(matched_keyword_keys(record))
    short_term_interest_clusters = [term for term, count in interest_terms.items() if count >= 2]

    # 進行中稿件（researching/drafting）：供跨篇關聯掃描，找可互為佐證的稿件
    active_research = []
    for r in records:
        if clean_text(r.get("status")) in {"researching", "drafting"}:
            active_research.append({
                "id": clean_text(r.get("id")),
                "title": clean_text(r.get("editorial_title") or r.get("title"), 120),
                "tags": {normalized(t) for t in tags_for(r) if normalized(t)},
            })
    active_research = active_research[:50]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "keyword_config_version": keyword_config.get("version", 1),
        "prior_tags": prior_tags,
        "prior_sources": prior_sources,
        "rejected_tags": rejected_tags,
        "rejected_sources": rejected_sources,
        "rejected_reasons": rejected_reasons,
        "history_prior_sources": history_prior_sources,
        "history_rejected_sources": history_rejected_sources,
        "history_prior_keywords": history_prior_keywords,
        "history_rejected_keywords": history_rejected_keywords,
        "history_window_days": history_window_days,
        "prior_count": len(prior_records),
        "rejected_count": len(rejected_records),
        "taste_profile": taste,
        "personal_beats": personal_beats,
        "tracked_beats": tracked_beats,
        "short_term_interest_clusters": short_term_interest_clusters,
        "active_research": active_research,
        "named_event_index": named_event_index,
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
    de_emphasize = [term for term in (g.get("de_emphasize") or []) if term]
    de_hits = [term for term in de_emphasize if normalized(term) in normalized(haystack)]
    if de_hits:
        score -= len(de_hits)
        signals.append("命中全域淡化詞：" + "、".join(de_hits[:6]))
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
        return "建議先問你（命中個人 beat 或底層機制）"
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
    taste = context.get("taste_profile") or {}
    source_blocked = source_is_blocked(source, taste)
    title = clean_text(record.get("title"))
    activity_hits = cue_matches(title, ACTIVITY_PROMOTION_CUES)
    substantive_hits = cue_matches(text, SUBSTANTIVE_GOVERNANCE_CUES)
    institutional_hits = cue_matches(text, INSTITUTIONAL_GOVERNANCE_CUES)
    platform_hits = cue_matches(text, PLATFORM_DEPENDENCY_CUES)
    dependency_hits = cue_matches(text, DEPENDENCY_CONCERN_CUES)

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
    if source_blocked:
        deletion_signals.append(f"來源「{source}」命中設定的 source_blocklist，直接略過")
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
    deletion_score = 6 if source_blocked else min(6, len(deletion_signals) + len(skip_keywords))

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
    if not source_blocked and taste_score >= 2 and recommendation == "suggest-skip" and deletion_score < 3:
        recommendation = "suggest-review"
        taste_signals.append("因符合個人品味，從建議略過上修為建議人工看過")

    # personal-beat 保護層：命中使用者明示的個人 beat 主題時，輸出 suggest-ask 而非 skip。
    # 只在 deletion_score < 4 且尚為 suggest-skip 時觸發，避免和明確 spam 衝突。
    if not source_blocked and recommendation == "suggest-skip" and deletion_score < 4:
        personal_beats = context.get("personal_beats") or []
        beat_hits = [b for b in personal_beats if b and normalized(b) and normalized(b) in normalized(text)]
        if beat_hits:
            recommendation = "suggest-ask"
            taste_signals.append("命中個人 beat 主題：" + "、".join(beat_hits[:4]) + "；請確認是否值得追蹤")

    # 機制關鍵字保護層：表層主題沒命中主線、但命中底層機制框架詞（FOIA、公共數位基礎建設、
    # 開源永續、貢獻者權利、數位人權等）時，輸出 suggest-ask 而非自主 skip，避免誤刪有切角價值的稿件。
    if not source_blocked and recommendation == "suggest-skip" and deletion_score < 4:
        track_cfg = (keyword_config.get("tracks") or {}).get(track, {})
        mechanism_keywords = track_cfg.get("mechanism_keywords") or []
        mech_hits = [kw for kw in mechanism_keywords if normalized(kw) and normalized(kw) in normalized(text)]
        if mech_hits:
            recommendation = "suggest-ask"
            taste_signals.append("命中底層機制關鍵字：" + "、".join(mech_hits[:4]) + "；表層主題偏移但機制吻合，建議先確認再決定")

    norm_text = normalized(text)

    # keep 正訊號保護層：triage 已命中 keep 關鍵字（正訊號）卻被歷史/負分/共現的 skip 詞壓成 skip 時，
    # 不整篇否決，改 suggest-ask 讓使用者決定。純 spam 不會命中 keep，故即使同時有 skip 詞也安全。
    # 這是提案#3「正訊號不應被語氣/歷史/共現負分壓過」的核心。
    if not source_blocked and recommendation == "suggest-skip" and matched_keywords:
        recommendation = "suggest-ask"
        extra = ("（雖同時命中排除詞「" + "、".join(skip_keywords[:3]) + "」）") if skip_keywords else ""
        taste_signals.append("命中收錄關鍵字「" + "、".join(matched_keywords[:4])
                             + "」屬正訊號" + extra + "，雖被其他負分壓低，建議先確認再決定")

    # 歷史命中率校準層：高價值國際科技政策訊號不因非台灣來源被略過；相反地，
    # 低收下率來源/關鍵字若只命中泛文化詞，就不要讓 keep 泛詞直接推高到 ask/collect。
    history_cfg = history_calibration_settings(context.get("taste_profile") or {})
    if not source_blocked and history_cfg.get("enabled") is not False:
        high_value_hits = cue_matches(text, cfg_terms(history_cfg, "high_value_signals"))
        if high_value_hits:
            high_value_note = (
                "歷史校準：命中高價值政策訊號「"
                + "、".join(high_value_hits[:4])
                + "」"
            )
            if recommendation in {"suggest-skip", "suggest-review"} and deletion_score < 4:
                recommendation = "suggest-ask"
                high_value_note += "，即使非台灣來源也先問再決定"
            else:
                high_value_note += "，避免只因非台灣來源降分"
            taste_signals.append(high_value_note)

        generic_terms = {normalized(term) for term in cfg_terms(history_cfg, "generic_keep_keywords")}
        generic_hits = [keyword for keyword in matched_keywords if normalized(keyword) in generic_terms]
        non_generic_hits = [keyword for keyword in matched_keywords if normalized(keyword) not in generic_terms]
        if generic_hits and not non_generic_hits and not high_value_hits:
            window_days = cfg_int(history_cfg, "window_days", context.get("history_window_days") or HISTORY_CALIBRATION_DEFAULTS["window_days"])
            low_rate = cfg_float(history_cfg, "low_acceptance_rate", HISTORY_CALIBRATION_DEFAULTS["low_acceptance_rate"])
            low_history_signals: list[str] = []
            if source:
                signal = low_acceptance_signal(
                    f"來源「{source}」",
                    context.get("history_prior_sources", Counter()).get(source, 0),
                    context.get("history_rejected_sources", Counter()).get(source, 0),
                    min_total=cfg_int(history_cfg, "min_source_total", HISTORY_CALIBRATION_DEFAULTS["min_source_total"]),
                    low_rate=low_rate,
                    window_days=window_days,
                )
                if signal:
                    low_history_signals.append(signal)
            for keyword in dict.fromkeys(generic_hits):
                key = normalized(keyword)
                signal = low_acceptance_signal(
                    f"關鍵字「{keyword}」",
                    context.get("history_prior_keywords", Counter()).get(key, 0),
                    context.get("history_rejected_keywords", Counter()).get(key, 0),
                    min_total=cfg_int(history_cfg, "min_keyword_total", HISTORY_CALIBRATION_DEFAULTS["min_keyword_total"]),
                    low_rate=low_rate,
                    window_days=window_days,
                )
                if signal:
                    low_history_signals.append(signal)
            if low_history_signals:
                if recommendation in {"suggest-collect", "suggest-ask"}:
                    recommendation = "suggest-review"
                taste_signals.append(
                    "歷史校準："
                    + "；".join(low_history_signals[:3])
                    + "，且只命中泛文化詞「"
                    + "、".join(dict.fromkeys(generic_hits[:4]))
                    + "」；最高只給人工看過"
                )

    # tracked-beat 監測層：命中使用者長期追蹤線（taste_profile.tracked_beats 的關鍵字）時，
    # 即使單篇品質普通也強制把 suggest-skip 升為 suggest-ask，附追蹤線脈絡；命中明確 spam 排除詞則不動。
    if not source_blocked and recommendation == "suggest-skip" and not skip_keywords:
        beat_hit_names = []
        for tb in (context.get("tracked_beats") or []):
            if any(kw in norm_text for kw in tb.get("keywords", [])):
                beat_hit_names.append(tb.get("beat", ""))
        if beat_hit_names:
            recommendation = "suggest-ask"
            taste_signals.append("屬於追蹤線「" + "、".join([b for b in beat_hit_names if b][:3])
                                 + "」：品質普通但符合長期監測，建議先確認")

    # 商業來源前段萃取層：已知商業/顧問來源即使被歷史或語氣壓成 skip，
    # 若摘要前段（前 200 字）含可萃取概念（keep / mechanism / 偏好主題詞），改 suggest-ask，
    # 標「前段有 X 概念可萃取」而不因來源整篇否決；命中明確 spam 排除詞則不動。
    if not source_blocked and recommendation == "suggest-skip" and not skip_keywords:
        commercial_hay = normalized(source) + " " + normalized(record.get("title")) + " " + normalized(record.get("author"))
        if any(cs in commercial_hay for cs in COMMERCIAL_SOURCE_HINTS):
            early = normalized(clean_text(record.get("summary"))[:200] + " " + clean_text(record.get("title")))
            track_cfg = (keyword_config.get("tracks") or {}).get(track, {})
            track_taste = ((context.get("taste_profile") or {}).get("tracks") or {}).get(track) or {}
            concept_pool = ((track_cfg.get("keep_keywords") or [])
                            + (track_cfg.get("mechanism_keywords") or [])
                            + (track_taste.get("priority_themes") or []))
            concept_hits = [k for k in concept_pool if normalized(k) and normalized(k) in early]
            if concept_hits:
                recommendation = "suggest-ask"
                taste_signals.append("商業來源但前段有可萃取概念：" + "、".join(dict.fromkeys(concept_hits[:4]))
                                     + "；先確認再決定，不因來源語氣整篇否決")

    # 命名事件串保護層：同一具名事件近期已有收錄/閱讀中的資料時，後續稿可能補足事件演變。
    # 單篇密度低仍不直接刪，改 suggest-ask；但 deletion_score >= 4 的明確垃圾/低價值訊號不動。
    event_hits = named_event_chain_hits(record, keyword_config, context)
    if event_hits and not source_blocked:
        event_names = "、".join(dict.fromkeys(hit["label"] for hit in event_hits[:3]))
        prior_names = "；".join(
            f"《{hit['title']}》({hit['id']})" if hit.get("id") else f"《{hit['title']}》"
            for hit in event_hits[:2]
            if hit.get("title")
        )
        taste_signals.append("命中近期命名事件串：" + event_names + "；可補足事件演變：" + prior_names)
        if recommendation == "suggest-skip" and deletion_score < 4:
            recommendation = "suggest-ask"

    # 跨篇關聯層：與庫中 researching/drafting 稿件共用 >= XREF_TAG_THRESHOLD 個 tag 時，
    # 標注可互為佐證，並把保留優先度提升一級（suggest-skip → suggest-review）。
    cur_tags = {normalized(t) for t in tags if normalized(t)}
    if cur_tags and not source_blocked:
        cur_id = clean_text(record.get("id"))
        xrefs = []
        for it in (context.get("active_research") or []):
            if it.get("id") and it.get("id") == cur_id:
                continue
            if len(cur_tags & (it.get("tags") or set())) >= XREF_TAG_THRESHOLD:
                xrefs.append(it)
        if xrefs:
            names = "；".join(f"《{x.get('title','')}》({x.get('id','')})" for x in xrefs[:3])
            taste_signals.append("可與進行中稿件互為佐證：" + names)
            if recommendation == "suggest-skip" and not skip_keywords:
                recommendation = "suggest-review"

    # 論述型制度稿、平台依賴結構與短期興趣簇在一般關鍵字不足時先送人工判斷；
    # 明確略過來源、活動 CTA 或垃圾訊號不會被這些保護層救回。
    if not source_blocked and deletion_score < 4 and not skip_keywords:
        if institutional_hits and recommendation == "suggest-skip":
            recommendation = "suggest-ask"
            taste_signals.append("命中制度問題訊號：" + "、".join(institutional_hits[:4]) + "；先判斷治理架構而非文體")
        if platform_hits and dependency_hits and recommendation == "suggest-skip":
            recommendation = "suggest-ask"
            taste_signals.append("命中平台依賴結構：" + "、".join((platform_hits + dependency_hits)[:4]) + "；先判斷控制權與替換成本")
        interest_hits = [term for term in context.get("short_term_interest_clusters", []) if term and term in norm_text]
        if interest_hits and recommendation == "suggest-skip":
            recommendation = "suggest-ask"
            taste_signals.append("命中近 30 天短期興趣簇：" + "、".join(interest_hits[:4]) + "；先保留觀察")

    # 活動宣傳先行降權：沒有制度、問責或規則變動等實質訊號時，不能被一般治理詞直接推成收錄/詢問。
    if activity_hits and not substantive_hits and recommendation in {"suggest-collect", "suggest-ask"}:
        recommendation = "suggest-review"
        taste_signals.append("活動宣傳語氣：" + "、".join(activity_hits[:4]) + "；缺乏實質制度訊號，最高人工看過")
    elif taste_score < 0 and recommendation == "suggest-collect":
        recommendation = "suggest-review"
        taste_signals.append("命中全域淡化偏好；由建議收錄降為人工看過")

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
