#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from editorial_triage import has_cjk, keyword_topic, zh_title_for
from page_metadata import attrs_from_tag, first_link, first_meta, title_from_html


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
TRIAGE_KEYWORDS = ROOT / "database" / "triage-keywords.json"
USER_AGENT = "IanOpenNewsBot/1.0 article summarizer (+local reading database)"

BOILERPLATE_PATTERNS = [
    "cookie",
    "cookies",
    "privacy policy",
    "terms of use",
    "subscribe",
    "sign up",
    "newsletter",
    "advertisement",
    "recommended",
    "related posts",
    "share this",
    "©",
    "all rights reserved",
    "登入",
    "註冊",
    "訂閱",
    "廣告",
    "推薦閱讀",
    "相關文章",
    "分享此文",
    "版權所有",
    "隱私權",
    "圖片來源",
    "資料來源",
    "推薦閱讀",
    "延伸閱讀",
    "購買連結",
    "合購優惠",
    "目前無法從原始網址抽出足夠正文",
]

IMPORTANT_CUES = [
    "開源",
    "開放資料",
    "開放原始碼",
    "資料治理",
    "數據治理",
    "公共",
    "治理",
    "文化記憶",
    "記憶庫",
    "文化資產",
    "數位典藏",
    "社群",
    "研究",
    "報告",
    "指出",
    "表示",
    "宣布",
    "發布",
    "open source",
    "open data",
    "governance",
    "standard",
    "privacy",
    "security",
    "dataset",
    "research",
    "report",
]


def clean_text(value: object, limit: int | None = None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?is)<(script|style|svg|noscript|iframe|form|nav|footer|header).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|blockquote|section|article)>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(value: object) -> str:
    return clean_text(value).casefold()


def existing_item_text(item: dict) -> str:
    values: list[str] = []
    for key in ("title", "summary"):
        text = clean_text(item.get(key), 4000)
        if text and "目前無法從原始網址抽出足夠正文" not in text:
            values.append(text)
    raw_columns = ((item.get("reference") or {}).get("raw_columns") or {})
    if isinstance(raw_columns, dict):
        for key in ("摘要", "（ian 測試中）台灣用語翻譯", "名稱", "備註"):
            text = clean_text(raw_columns.get(key), 4000)
            if text:
                values.append(text)
    unique: list[str] = []
    seen = set()
    for value in values:
        key = normalize(value[:500])
        if key and key not in seen:
            unique.append(value)
            seen.add(key)
    return clean_text("\n\n".join(unique), 12000)


def fetch_html(url: str, timeout: int, max_bytes: int = 2_500_000) -> tuple[str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
        raw = response.read(max_bytes)
    charset_match = re.search(r"charset=([\w.-]+)", content_type, flags=re.I)
    charset = charset_match.group(1) if charset_match else "utf-8"
    return raw.decode(charset, errors="replace"), final_url, content_type


def iter_json_values(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_values(child)


def article_body_from_jsonld(html_text: str) -> str:
    bodies = []
    for match in re.finditer(r"(?is)<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", html_text):
        raw = html.unescape(match.group(1)).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in iter_json_values(data):
            body = node.get("articleBody") or node.get("text")
            if isinstance(body, str) and len(clean_text(body)) >= 300:
                bodies.append(clean_text(body))
    return max(bodies, key=len) if bodies else ""


def candidate_blocks(html_text: str) -> list[str]:
    blocks = []
    for tag in ("article", "main"):
        blocks.extend(match.group(0) for match in re.finditer(fr"(?is)<{tag}\b[^>]*>.*?</{tag}>", html_text))
    for match in re.finditer(r"(?is)<div\b[^>]*(class|id)=['\"][^'\"]*(article|content|entry|post|story|main)[^'\"]*['\"][^>]*>.*?</div>", html_text):
        blocks.append(match.group(0))
    return blocks


def paragraph_texts(block: str) -> list[str]:
    texts = []
    for match in re.finditer(r"(?is)<(h[1-6]|p|li|blockquote)\b[^>]*>(.*?)</\1>", block):
        text = clean_text(match.group(2), 900)
        if len(text) < 28:
            continue
        lowered = normalize(text)
        if any(pattern in lowered for pattern in BOILERPLATE_PATTERNS):
            continue
        if re.search(r"https?://|www\.", text, flags=re.I):
            continue
        if len(re.sub(r"\W+", "", text)) < 20:
            continue
        texts.append(text)
    return texts


def is_low_value_sentence(text: str) -> bool:
    cleaned = clean_text(text)
    lowered = normalize(cleaned)
    if any(pattern in lowered for pattern in BOILERPLATE_PATTERNS):
        return True
    if re.search(r"https?://|www\.", cleaned, flags=re.I):
        return True
    if re.match(r"^[(（]?(註|注)\s*\d*", cleaned):
        return True
    if re.match(r"^\d+[.、]\s*", cleaned) and re.search(r"歌詞|頁|出版|來源|ISBN|作者|譯者", cleaned):
        return True
    if cleaned.count("：") >= 4 and len(cleaned) > 180:
        return True
    return False


def extract_article_text(html_text: str) -> tuple[str, str]:
    jsonld = article_body_from_jsonld(html_text)
    if jsonld:
        return jsonld, "jsonld.articleBody"

    blocks = candidate_blocks(html_text)
    candidates: list[tuple[int, list[str], str]] = []
    for block in blocks:
        paragraphs = paragraph_texts(block)
        chars = sum(len(paragraph) for paragraph in paragraphs)
        if chars >= 300:
            candidates.append((chars, paragraphs, "semantic-block"))
    if candidates:
        _, paragraphs, method = max(candidates, key=lambda row: row[0])
        return clean_text("\n\n".join(paragraphs), 12000), method

    paragraphs = paragraph_texts(html_text)
    return clean_text("\n\n".join(paragraphs), 12000), "all-paragraphs"


def sentence_parts(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    if has_cjk(text):
        raw = re.split(r"(?<=[。！？!?])\s*|\n+", text)
    else:
        raw = re.split(r"(?<=[.!?])\s+|\n+", text)
    sentences = []
    for part in raw:
        part = clean_text(part, 700)
        if len(part) < 30:
            continue
        if is_low_value_sentence(part):
            continue
        sentences.append(part)
    return sentences


def title_terms(title: str) -> list[str]:
    title = clean_text(title)
    if has_cjk(title):
        return [term for term in re.split(r"[，。！？、：:｜|\s／/（）()「」《》\-_]+", title) if len(term) >= 2]
    return [term.casefold() for term in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", title)]


def sentence_score(sentence: str, index: int, keywords: list[str], terms: list[str]) -> float:
    lowered = normalize(sentence)
    score = max(0, 16 - index * 0.25)
    score += min(len(sentence), 260) / 55
    for keyword in keywords:
        if normalize(keyword) and normalize(keyword) in lowered:
            score += 8
    for term in terms[:12]:
        if normalize(term) and normalize(term) in lowered:
            score += 3
    for cue in IMPORTANT_CUES:
        if cue.casefold() in lowered:
            score += 3
    if re.search(r"\d", sentence):
        score += 1.5
    if len(sentence) < 45:
        score -= 3
    if len(sentence) > 420:
        score -= 2
    return score


def select_summary_sentences(text: str, title: str, keywords: list[str], max_chars: int = 520) -> list[str]:
    sentences = sentence_parts(text)
    if not sentences:
        return []
    terms = title_terms(title)
    scored = [
        (sentence_score(sentence, index, keywords, terms), index, sentence)
        for index, sentence in enumerate(sentences[:80])
    ]
    chosen = sorted(scored, reverse=True)[:5]
    chosen.sort(key=lambda row: row[1])
    output = []
    length = 0
    for _, _, sentence in chosen:
        clipped = clean_text(sentence, 240)
        if any(clipped == existing or clipped in existing or existing in clipped for existing in output):
            continue
        if length + len(clipped) > max_chars and output:
            continue
        output.append(clipped)
        length += len(clipped)
        if len(output) >= 3 or length >= max_chars:
            break
    if not output:
        output.append(clean_text(sentences[0], max_chars))
    return output


def zh_summary(title: str, summary_sentences: list[str], fallback_topic: str, used_original: bool) -> str:
    if not summary_sentences:
        return f"中文標題：{title}\n中文摘要：目前無法從原始網址抽出足夠正文，只能先依既有資料判斷主題可能和「{fallback_topic}」有關。"
    body = " ".join(summary_sentences) if not has_cjk("".join(summary_sentences)) else "".join(summary_sentences)
    if has_cjk(body):
        return clean_text(f"中文標題：{title}\n中文摘要：{body}", 780)
    source_label = "原文正文" if used_original else "既有資料"
    return clean_text(
        f"中文標題：{title}\n中文摘要：這篇英文資料的主題和「{fallback_topic}」有關。"
        f"以下是從{source_label}抽出的重點線索：{body}",
        780,
    )


def reading_reasons(record: dict, summary_sentences: list[str], article_text: str, used_original: bool) -> list[str]:
    triage = record.get("triage") or {}
    keywords = [str(keyword) for keyword in triage.get("matched_keywords", []) if str(keyword).strip()]
    topic = keyword_topic(record, triage)
    reasons: list[str] = []
    source_label = "原文" if used_original else "既有資料"
    reason_labels = [
        "掌握主題",
        "補足脈絡",
        "判斷取材價值",
    ]
    reason_tails = [
        "可以先抓住這則資料真正談的問題。",
        "有助於理解事件、人物、制度或案例背後的背景。",
        "方便判斷它適合送 skill 深讀，還是只整理成小消息。",
    ]
    for index, sentence in enumerate(summary_sentences[:3]):
        excerpt = clean_text(sentence, 110)
        label = reason_labels[min(index, len(reason_labels) - 1)]
        tail = reason_tails[min(index, len(reason_tails) - 1)]
        if has_cjk(excerpt):
            reasons.append(f"{label}：{source_label}提到「{excerpt}」，{tail}")
        else:
            reasons.append(f"{label}：{source_label}重點包含「{excerpt}」，{tail}")
    if keywords and len(reasons) < 3:
        reasons.append(f"內容命中子關鍵字「{'、'.join(keywords[:5])}」，和目前待整理主線有直接關聯。")
    if len(article_text) >= 1200 and len(reasons) < 3:
        reasons.append("原文正文資訊量足夠，適合人工判斷是否進一步整理成摘要、brief 或小消息。")
    while len(reasons) < 3:
        reasons.append(f"這則資料可用來補充「{topic}」的來源脈絡，但仍需要人工查核與取捨。")
    return reasons[:3]


def metadata_from_html(html_text: str, final_url: str, content_type: str) -> dict:
    image = first_meta(html_text, "og:image", "og:image:url", "twitter:image", "twitter:image:src")
    canonical = first_link(html_text, "canonical")
    description = first_meta(html_text, "og:description", "description", "twitter:description")
    return {
        "title": title_from_html(html_text),
        "description": description,
        "image_url": urljoin(final_url, image) if image else "",
        "canonical_url": urljoin(final_url, canonical) if canonical else "",
        "final_url": final_url,
        "content_type": content_type,
    }


def enrich_one(item: dict, keyword_config: dict, timeout: int) -> tuple[str, dict, str]:
    url = str(item.get("url") or "").strip()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updated = dict(item)
    editorial = dict(updated.get("editorial_triage") or {})
    triage = updated.get("triage") or {}
    title = zh_title_for(updated, triage)
    keywords = [str(keyword) for keyword in triage.get("matched_keywords", []) if str(keyword).strip()]
    topic = keyword_topic(updated, triage)
    used_original = False
    status = "fallback-existing-summary"
    error = ""
    article_text = existing_item_text(updated)
    extraction_method = "existing-summary"
    metadata = {}

    if url.startswith(("http://", "https://")):
        try:
            html_text, final_url, content_type = fetch_html(url, timeout)
            metadata = metadata_from_html(html_text, final_url, content_type)
            extracted_text, extraction_method = extract_article_text(html_text)
            if len(extracted_text) >= 280 and "login" not in normalize(extracted_text[:400]):
                article_text = extracted_text
                used_original = True
                status = "ok"
            else:
                status = "fallback-short-extraction"
                error = "原始網址正文不足，改用既有資料。"
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
            error = str(exc)
            status = "fallback-fetch-error"
    else:
        error = "no fetchable url"

    effective_title = metadata.get("title") or updated.get("title") or title
    if not used_original:
        effective_title = updated.get("title") or metadata.get("title") or title
    title_record = {**updated, "title": effective_title}
    title = zh_title_for(title_record, triage)
    summary_sentences = select_summary_sentences(article_text, effective_title, keywords)
    summary_text = zh_summary(title, summary_sentences, topic, used_original)
    reasons = reading_reasons(updated, summary_sentences, article_text, used_original)

    editorial.update(
        {
            "zh_title": title,
            "zh_summary": summary_text,
            "view_reasons": reasons,
            "summary_reason": "已從原始網址正文重寫摘要與閱讀理由。" if used_original else "原始網址無法完整讀取，已用既有資料重寫摘要與閱讀理由。",
            "source_summary_status": status,
            "source_summary_method": extraction_method,
            "generated_at": editorial.get("generated_at") or now,
        }
    )
    updated["editorial_triage"] = editorial
    updated["summary"] = clean_text(re.sub(r"^中文標題：.*?\n中文摘要：", "", summary_text, flags=re.S), 900)
    current_meta = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
    merged_meta = {**current_meta, **metadata}
    if metadata:
        merged_meta["fetched_at"] = now
        merged_meta["source_url"] = url
        merged_meta["status"] = "ok"
        updated["reading_metadata"] = merged_meta
        if metadata.get("image_url"):
            updated["image_url"] = metadata["image_url"]
    updated["article_enrichment"] = {
        "status": status,
        "fetched_at": now,
        "source_url": url,
        "final_url": metadata.get("final_url", ""),
        "text_chars": len(article_text),
        "used_original_url_text": used_original,
        "extraction_method": extraction_method,
        "summary_sentences": summary_sentences,
        "error": error,
    }
    return str(item.get("id")), updated, status


def should_process(item: dict, args: argparse.Namespace) -> bool:
    if args.status and item.get("status") not in set(args.status):
        return False
    if args.recommendation and (item.get("triage") or {}).get("recommendation") != args.recommendation:
        return False
    if args.track and item.get("track") not in set(args.track):
        return False
    if args.only_missing and (item.get("article_enrichment") or {}).get("status") == "ok":
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch original URLs and rewrite readable summaries and three reading reasons.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--triage-keywords", type=Path, default=TRIAGE_KEYWORDS)
    parser.add_argument("--status", action="append", default=[])
    parser.add_argument("--recommendation", default="suggest-keep")
    parser.add_argument("--track", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.status:
        args.status = ["inbox"]

    items = load_jsonl(args.items)
    keyword_config = load_json(args.triage_keywords)
    selected = [item for item in items if should_process(item, args)]
    if args.limit:
        selected = selected[: args.limit]
    selected_ids = {item.get("id") for item in selected}
    print(f"selected={len(selected)} status={args.status} recommendation={args.recommendation} dry_run={args.dry_run}")

    results: dict[str, dict] = {}
    statuses = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(enrich_one, item, keyword_config, args.timeout): item for item in selected}
        for future in as_completed(futures):
            item = futures[future]
            try:
                item_id, updated, status = future.result()
            except Exception as exc:  # noqa: BLE001
                print(f"failed {item.get('id')}: {exc}", file=sys.stderr)
                continue
            results[item_id] = updated
            statuses[status] = statuses.get(status, 0) + 1
            print(f"{status} {item_id} {clean_text(updated.get('title'), 80)}")

    output = []
    changed = 0
    for item in items:
        item_id = item.get("id")
        if item_id in selected_ids and item_id in results:
            updated = results[item_id]
            if updated != item:
                changed += 1
            output.append(updated)
        else:
            output.append(item)

    if not args.dry_run:
        write_jsonl(args.items, output)
    print(f"changed={changed} statuses={statuses}")


if __name__ == "__main__":
    main()
