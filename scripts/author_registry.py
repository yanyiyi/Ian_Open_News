#!/usr/bin/env python3
"""作者與組織登記層：byline 字串的切分、正規化、雜訊判定與實體解析。

設計原則（作者實體化的中心約定）：
- items.jsonl 不寫 author_ids：作者↔文章靠「byline 字串比對」在讀取時解析，
  build（建庫）、import（回填）、local_web（顯示）三邊共用這裡同一把尺，
  規則只要一致，新文章的 byline 命中既有 byline_names 就自動連上。
- byline_names 存「切分後的正規片段」：item 的原始 byline 可能是
  「廖洲棚\n曾憲立、李天申」這種多作者字串，比對鍵是 split_bylines 切出的
  單人片段，不是整條原始字串。
- 切分寧保守勿誤切：換行、頓號、分號、" and " 一律切；逗號有
  「Lastname, Firstname」與「人名, 職稱, 公司」兩種陷阱，只在每段都像
  人名時才切，切錯比不切難修。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTHORS_PATH = ROOT / "database" / "authors.jsonl"
ORGANIZATIONS_PATH = ROOT / "database" / "organizations.jsonl"

AUTHOR_KINDS = ("person", "organization", "unknown", "noise")
VERIFICATION_STATUSES = ("unverified", "ai-suggested", "verified", "needs-review")
VERIFICATION_METHODS = ("perplexity-batch", "perplexity-single", "manual")
ORG_TYPES = ("media", "academic", "government", "ngo", "company", "community", "other")

# 舊 Excel「收錄者」欄被 import 進 author 的名字；清理與雜訊判定都要靠它，
# 但只在有收錄脈絡（xlsx origin / raw_columns）時才視為雜訊，避免誤殺同名作者。
KNOWN_COLLECTOR_NAMES = {"Cheng", "YH", "Amos"}

# 完整字串（正規化後）等於這些值就是佔位雜訊，不是作者
PLACEHOLDER_BYLINES = {
    "by", "author", "authors", "authors:", "admin", "guest", "unknown",
    "n/a", "none", "-", ".", "查證來源", "作者", "編輯部",
}

_PREFIX_RE = re.compile(r"^(?:by|作者|authors?)\s*[:：]?\s*\n?\s*", re.IGNORECASE)
_STRONG_SEP_RE = re.compile(r"[\n;；、]|\s+(?:and|與|和|及)\s+|\s*&\s*", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)|（[^）]*）")
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE_RES = (
    re.compile(rf"^(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s*\d{{4}}$", re.IGNORECASE),
    re.compile(rf"^\d{{1,2}}\s+(?:{_MONTHS})\.?\s*,?\s*\d{{4}}$", re.IGNORECASE),
    re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}([ T].*)?$"),
    re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$"),
    re.compile(r"^\d{4}\s*年(\s*\d{1,2}\s*月(\s*\d{1,2}\s*日)?)?$"),
)
_OID_RE = re.compile(r"^\d+(\.\d+)+$")
# 職稱/機構詞：出現在逗號片段裡就代表那不是並列人名，而是「人名, 職稱/所屬」
_AFFILIATION_TOKENS = {
    "university", "institute", "institution", "college", "school", "academy",
    "lab", "labs", "laboratory", "foundation", "association", "center", "centre",
    "ministry", "department", "bureau", "council", "committee", "commission",
    "inc", "llc", "ltd", "corp", "corporation", "company", "gmbh",
    "cto", "ceo", "coo", "cio", "vp", "president", "director", "officer",
    "manager", "engineer", "developer", "researcher", "scientist", "analyst",
    "editor", "reporter", "writer", "columnist", "correspondent",
    "professor", "lecturer", "fellow", "chair", "head", "lead", "founder",
    "organizer", "ambassador", "ambassadors", "advocate", "evangelist",
    "at", "of", "for", "from",
}
# 標題常見的小寫功能詞：人名幾乎不含（van/de/von 等姓氏連接詞刻意不列）
_TITLE_FUNCTION_WORDS = {"in", "the", "a", "an", "on", "with", "to", "into", "via"}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_byline(value: object) -> str:
    """比對鍵：NFKC、壓縮空白、去頭尾雜點、casefold（CJK 不受影響）。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("·•|,;:：；、 ").strip()
    return text.casefold()


def strip_byline_prefix(value: str) -> str:
    return _PREFIX_RE.sub("", value or "").strip()


def _clean_part(part: str) -> str:
    part = re.sub(r"\s+", " ", part or "").strip()
    return part.strip("·•|,;:：；、 ").strip()


def _looks_person_name(part: str) -> bool:
    """像單一人名：1-5 個詞、無數字/@/網址、不含職稱機構詞。CJK 姓名天然通過。"""
    text = _clean_part(part)
    if not text or len(text) > 40 or "@" in text or "/" in text:
        return False
    if any(ch.isdigit() for ch in text):
        return False
    tokens = text.split(" ")
    if not 1 <= len(tokens) <= 5:
        return False
    lowered = [tok.casefold().strip(".") for tok in tokens]
    if any(tok in _AFFILIATION_TOKENS for tok in lowered):
        return False
    return not any(tok in _TITLE_FUNCTION_WORDS for tok in lowered)


_LAST_FIRST_RE = re.compile(
    r"^[A-Z][\w'\-]+,\s+[A-Z][\w'\-]*\.?(?:\s+[A-Z][\w'\-]*\.?)?$"
)
_DASH_AFFILIATION_RE = re.compile(r"\s[-–—]\s")


def _strip_dash_affiliation(part: str) -> str:
    """「Name - Title at Org」取左半，左半要像人名才取（保護含破折號的組織名）。"""
    pieces = _DASH_AFFILIATION_RE.split(part, maxsplit=1)
    if len(pieces) == 2 and _looks_person_name(pieces[0]):
        return _clean_part(pieces[0])
    return part


def split_bylines(raw: object) -> list[str]:
    """把一條 byline 字串切成單人片段。

    強分隔符（換行、頓號、分號、and/與/和/&）一律切；逗號只在
    「不是 Lastname, Firstname」且「每段都像人名」時切，否則整段保留
    （「人名, 職稱, 公司」只取第一段當名字）。括號內容（所屬標註）先
    摘除再切，避免括號裡的逗號誤導。
    """
    text = strip_byline_prefix(str(raw or "").strip())
    if not text:
        return []
    text = _PAREN_RE.sub(" ", text)
    parts: list[str] = []
    for segment in _STRONG_SEP_RE.split(text):
        segment = _clean_part(segment)
        if not segment:
            continue
        segment = _strip_dash_affiliation(segment)
        if "," not in segment:
            parts.append(segment)
            continue
        if _LAST_FIRST_RE.match(segment):
            parts.append(segment)
            continue
        comma_parts = [_strip_dash_affiliation(_clean_part(p)) for p in segment.split(",")]
        comma_parts = [p for p in comma_parts if p]
        # 取開頭連續像人名的段（「A, B, 職稱/內文殘渣」只留 A、B；
        # 「人名, 職稱, 公司」只留人名）；開頭就不像人名時退而求其次
        # 收中段像人名的（「組織殘渣, Laura Luttmer - 職稱」撈回 Laura）
        prefix: list[str] = []
        for part in comma_parts:
            if not _looks_person_name(part):
                break
            prefix.append(part)
        if prefix:
            parts.extend(prefix)
        else:
            # 救援限定 ≥2 token 的名字，避免把標題裡的單字（Transparency）當人名
            rescued = [p for p in comma_parts if " " in p and _looks_person_name(p)]
            parts.extend(rescued if rescued else [segment])
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = normalize_byline(part)
        if key and key not in seen:
            seen.add(key)
            deduped.append(part)
    return deduped


def looks_like_noise(value: object) -> bool:
    """整條字串是否為「非作者雜訊」：日期、OID、純數字、網址、佔位詞、疑似標題。"""
    text = _clean_part(str(value or ""))
    if not text:
        return True
    key = normalize_byline(text)
    if key in PLACEHOLDER_BYLINES:
        return True
    if any(pattern.match(text) for pattern in _DATE_RES):
        return True
    if _OID_RE.match(text) or text.isdigit():
        return True
    if "://" in text or text.casefold().startswith(("http", "www.")):
        return True
    # 長字串的標題/內文誤抓判定：先摘除括號所屬標註再量，
    # 切分後完全切不出像人名的片段才視為雜訊
    #（「真作者 + 長所屬標註」如 André Martins (Cilium maintainer...) 要活下來）
    stripped = _clean_part(_PAREN_RE.sub(" ", strip_byline_prefix(text)))
    if len(stripped) > 60 and not any(_looks_person_name(part) for part in split_bylines(text)):
        return True
    return False


def guess_kind(name: str) -> str:
    """建檔時的初步猜測，之後靠 Perplexity 查證修正。"""
    text = _clean_part(name)
    if not text:
        return "unknown"
    if looks_like_noise(text):
        return "noise"
    if text.startswith("@"):
        return "organization"
    lowered = text.casefold()
    if re.search(r"\.[a-z]{2,}$", lowered) and " " not in text:
        return "organization"  # 網域型署名，如 entreprises.gouv.fr
    tokens = [tok.casefold().strip(".") for tok in text.split()]
    if any(tok in _AFFILIATION_TOKENS for tok in tokens):
        return "organization"
    if text.isupper() and 2 <= len(text) <= 12 and " " not in text:
        return "organization"  # 全大寫縮寫，如 ODW
    if _looks_person_name(text):
        return "person"
    return "unknown"


def item_byline_raw(item: dict) -> str:
    """統一取值：reading_metadata.original_author 優先、fallback 頂層 author。"""
    metadata = item.get("reading_metadata")
    if isinstance(metadata, dict):
        original = str(metadata.get("original_author") or "").strip()
        if original:
            return original
    return str(item.get("author") or "").strip()


def item_byline_parts(item: dict) -> list[str]:
    return split_bylines(item_byline_raw(item))


def author_id_for(name: str) -> str:
    digest = hashlib.sha1(normalize_byline(name).encode("utf-8")).hexdigest()[:16]
    return f"author-{digest}"


def org_id_for(name: str) -> str:
    digest = hashlib.sha1(normalize_byline(name).encode("utf-8")).hexdigest()[:16]
    return f"org-{digest}"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_authors() -> list[dict]:
    return load_jsonl(AUTHORS_PATH)


def load_organizations() -> list[dict]:
    return load_jsonl(ORGANIZATIONS_PATH)


def build_author_index(authors: list[dict] | None = None) -> dict[str, dict]:
    """byline 正規化字串 → author record。name 與 byline_names 都是比對鍵。"""
    index: dict[str, dict] = {}
    for author in authors if authors is not None else load_authors():
        keys = list(author.get("byline_names") or [])
        keys.append(author.get("name") or "")
        for key in keys:
            normalized = normalize_byline(key)
            if normalized:
                index.setdefault(normalized, author)
    return index


def resolve_byline_parts(parts: list[str], index: dict[str, dict]) -> list[tuple[str, dict | None]]:
    """回傳 (顯示片段, 命中的 author 或 None)；kind=noise 的命中由呼叫端決定隱藏。"""
    return [(part, index.get(normalize_byline(part))) for part in parts]


def new_author_record(name: str, *, kind: str | None = None) -> dict:
    now = now_utc_iso()
    return {
        "id": author_id_for(name),
        "name": _clean_part(name),
        "kind": kind or guess_kind(name),
        "byline_names": [_clean_part(name)],
        "intro_zh": "",
        "org_ids": [],
        "links": [],
        "verification": {"status": "unverified", "checked_at": "", "method": "", "evidence": ""},
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }


def new_org_record(name: str, *, org_type: str = "other") -> dict:
    now = now_utc_iso()
    return {
        "id": org_id_for(name),
        "name": _clean_part(name),
        "aliases": [],
        "org_type": org_type if org_type in ORG_TYPES else "other",
        "intro_zh": "",
        "links": [],
        "verification": {"status": "unverified", "checked_at": "", "method": "", "evidence": ""},
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }
