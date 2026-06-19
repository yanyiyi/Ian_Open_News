from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin


DEFAULT_USER_AGENT = "IanOpenNewsBot/1.0 metadata fetch (+local reading database)"

BOILERPLATE_PATTERNS = [
    "cookie",
    "cookies",
    "privacy policy",
    "terms of use",
    "subscribe",
    "newsletter",
    "advertisement",
    "recommended",
    "related posts",
    "share this",
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
    "延伸閱讀",
]


def clean_text(value: object, limit: int | None = None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def attrs_from_tag(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"""([:\w-]+)\s*=\s*(['"])(.*?)\2""", tag, flags=re.S):
        attrs[match.group(1).casefold()] = html.unescape(match.group(3).strip())
    return attrs


def first_meta(html_text: str, *names: str) -> str:
    wanted = {name.casefold() for name in names}
    for match in re.finditer(r"<meta\b[^>]*>", html_text, flags=re.I | re.S):
        attrs = attrs_from_tag(match.group(0))
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").casefold()
        if key in wanted and attrs.get("content"):
            return clean_text(attrs["content"], 1200)
    return ""


def first_link(html_text: str, rel_name: str) -> str:
    rel_name = rel_name.casefold()
    for match in re.finditer(r"<link\b[^>]*>", html_text, flags=re.I | re.S):
        attrs = attrs_from_tag(match.group(0))
        rel = attrs.get("rel", "").casefold()
        if rel_name in rel.split() and attrs.get("href"):
            return attrs["href"].strip()
    return ""


def title_from_html(html_text: str) -> str:
    og_title = first_meta(html_text, "og:title", "twitter:title")
    if og_title:
        return og_title
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
    return clean_text(match.group(1), 300) if match else ""


def excerpt_from_html(html_text: str) -> str:
    paragraphs = []
    for match in re.finditer(r"(?is)<p\b[^>]*>(.*?)</p>", html_text):
        text = clean_text(match.group(1), 500)
        if len(text) >= 40:
            paragraphs.append(text)
        if len(paragraphs) >= 3:
            break
    return clean_text("\n\n".join(paragraphs), 1200)


def article_body_from_jsonld(html_text: str) -> str:
    bodies: list[str] = []
    for match in re.finditer(r"(?is)<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", html_text):
        raw = html.unescape(match.group(1)).strip()
        try:
            data = __import__("json").loads(raw)
        except Exception:  # noqa: BLE001
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                body = node.get("articleBody") or node.get("text")
                if isinstance(body, str) and len(clean_text(body)) >= 300:
                    bodies.append(clean_text(body))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return max(bodies, key=len) if bodies else ""


def candidate_blocks(html_text: str) -> list[str]:
    blocks: list[str] = []
    for tag in ("article", "main"):
        blocks.extend(match.group(0) for match in re.finditer(fr"(?is)<{tag}\b[^>]*>.*?</{tag}>", html_text))
    blocks.extend(
        match.group(0)
        for match in re.finditer(
            r"(?is)<div\b[^>]*(class|id)=['\"][^'\"]*(article|content|entry|post|story|main)[^'\"]*['\"][^>]*>.*?</div>",
            html_text,
        )
    )
    return blocks


def paragraph_texts(block: str) -> list[str]:
    texts: list[str] = []
    for match in re.finditer(r"(?is)<(h[1-6]|p|li|blockquote)\b[^>]*>(.*?)</\1>", block):
        text = clean_text(match.group(2), 1200)
        if len(text) < 28:
            continue
        lowered = text.casefold()
        if any(pattern in lowered for pattern in BOILERPLATE_PATTERNS):
            continue
        if len(re.sub(r"\W+", "", text)) < 20:
            continue
        texts.append(text)
    return texts


def extract_article_text(html_text: str, limit: int = 30000) -> tuple[str, str]:
    jsonld = article_body_from_jsonld(html_text)
    if jsonld:
        return clean_text(jsonld, limit), "jsonld.articleBody"

    candidates: list[tuple[int, list[str], str]] = []
    for block in candidate_blocks(html_text):
        paragraphs = paragraph_texts(block)
        chars = sum(len(paragraph) for paragraph in paragraphs)
        if chars >= 300:
            candidates.append((chars, paragraphs, "semantic-block"))
    if candidates:
        _, paragraphs, method = max(candidates, key=lambda row: row[0])
        return clean_text("\n\n".join(paragraphs), limit), method

    paragraphs = paragraph_texts(html_text)
    return clean_text("\n\n".join(paragraphs), limit), "all-paragraphs"


def fetch_page_metadata(url: str, timeout: int = 8, max_bytes: int = 1_500_000) -> dict[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
        raw = response.read(max_bytes)
    charset_match = re.search(r"charset=([\w.-]+)", content_type, flags=re.I)
    charset = charset_match.group(1) if charset_match else "utf-8"
    html_text = raw.decode(charset, errors="replace")
    image = first_meta(html_text, "og:image", "og:image:url", "twitter:image", "twitter:image:src")
    canonical = first_link(html_text, "canonical")
    description = first_meta(html_text, "og:description", "description", "twitter:description")
    metadata = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": url,
        "final_url": final_url,
        "title": title_from_html(html_text),
        "description": description,
        "image_url": urljoin(final_url, image) if image else "",
        "canonical_url": urljoin(final_url, canonical) if canonical else "",
        "excerpt": excerpt_from_html(html_text),
        "content_type": content_type,
        "status": "ok",
    }
    article_text, article_method = extract_article_text(html_text)
    if article_text:
        metadata.update(
            {
                "article_text": article_text,
                "article_text_chars": len(article_text),
                "article_text_method": article_method,
                "article_text_status": "ok" if len(article_text) >= 280 else "short",
                "article_text_label": "原始主文",
            }
        )
    return metadata


def enrich_item_metadata(item: dict, timeout: int = 8) -> tuple[dict, bool, str]:
    url = str(item.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return item, False, "no fetchable url"
    try:
        metadata = fetch_page_metadata(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
        return item, False, str(exc)

    updated = dict(item)
    current = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
    updated["reading_metadata"] = {**current, **metadata}
    if metadata.get("image_url"):
        updated["image_url"] = metadata["image_url"]
    if metadata.get("description") and len(str(updated.get("summary") or "")) < 120:
        updated["summary"] = metadata["description"]
    return updated, updated != item, ""
