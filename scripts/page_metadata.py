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


def normalized(value: object) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).casefold()


def inline_markdown(fragment: str, base_url: str = "") -> str:
    fragment = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment)

    def link_repl(match: re.Match[str]) -> str:
        attrs = attrs_from_tag(match.group(1))
        href = attrs.get("href", "").strip()
        label = clean_text(match.group(2), 220)
        if not href or not label or href.startswith(("javascript:", "mailto:")):
            return label
        return f"[{label}]({urljoin(base_url, href)})"

    fragment = re.sub(r"(?is)<a\b([^>]*)>(.*?)</a>", link_repl, fragment)

    def emphasis_repl(marker: str):
        def repl(match: re.Match[str]) -> str:
            text = clean_text(match.group(1), 320)
            return f"{marker}{text}{marker}" if text else ""

        return repl

    fragment = re.sub(r"(?is)<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>", emphasis_repl("**"), fragment)
    fragment = re.sub(r"(?is)<(?:em|i)\b[^>]*>(.*?)</(?:em|i)>", emphasis_repl("*"), fragment)
    fragment = re.sub(r"(?is)<code\b[^>]*>(.*?)</code>", emphasis_repl("`"), fragment)
    return clean_text(fragment, 1600)


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


def text_to_markdown(text: str, title: str = "", limit: int = 60000) -> str:
    raw = html.unescape(str(text or ""))
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t\f\v]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    paragraphs = [clean_text(part) for part in re.split(r"\n\s*\n", raw) if clean_text(part)]
    lines: list[str] = []
    clean_title = clean_text(title, 220)
    if clean_title:
        lines.extend([f"# {clean_title}", ""])
    for index, paragraph in enumerate(paragraphs):
        if clean_title and normalized(paragraph) == normalized(clean_title):
            continue
        is_heading = (
            index > 0
            and len(paragraph) <= 90
            and not re.search(r"[。！？.!?]$", paragraph)
            and not paragraph.startswith(("-", "•"))
        )
        if is_heading:
            lines.extend([f"## {paragraph.rstrip(':：')}", ""])
        elif re.match(r"^[-•]\s+", paragraph):
            lines.append("- " + re.sub(r"^[-•]\s+", "", paragraph))
        else:
            lines.extend([paragraph, ""])
    return clean_text("\n".join(lines), limit)


def block_to_markdown(block: str, title: str = "", base_url: str = "", limit: int = 60000) -> str:
    lines: list[str] = []
    clean_title = clean_text(title, 220)
    if clean_title:
        lines.extend([f"# {clean_title}", ""])
    last_was_list = False

    def append_block(line: str, is_list: bool = False) -> None:
        nonlocal last_was_list
        if not line:
            return
        if lines and lines[-1] != "" and not (is_list and last_was_list):
            lines.append("")
        lines.append(line)
        if not is_list:
            lines.append("")
        last_was_list = is_list

    for match in re.finditer(r"(?is)<(h[1-6]|p|li|blockquote)\b[^>]*>(.*?)</\1>", block):
        tag = match.group(1).lower()
        text = inline_markdown(match.group(2), base_url)
        plain = clean_text(text)
        if not plain:
            continue
        lowered = plain.casefold()
        if any(pattern in lowered for pattern in BOILERPLATE_PATTERNS):
            continue
        if tag.startswith("h"):
            if clean_title and normalized(plain) == normalized(clean_title):
                continue
            level = min(max(int(tag[1]), 2), 4)
            append_block(f"{'#' * level} {plain.rstrip(':：')}")
        elif tag == "li":
            if len(re.sub(r"\W+", "", plain)) >= 12:
                append_block(f"- {plain}", is_list=True)
        elif tag == "blockquote":
            quote_lines = [f"> {line}" for line in plain.split("\n") if line.strip()]
            append_block("\n".join(quote_lines))
        else:
            if len(plain) >= 28 and len(re.sub(r"\W+", "", plain)) >= 20:
                append_block(plain)

    return clean_text("\n".join(lines), limit)


def extract_article_markdown(html_text: str, final_url: str = "", title: str = "", limit: int = 60000) -> tuple[str, str]:
    jsonld = article_body_from_jsonld(html_text)
    if jsonld:
        return text_to_markdown(jsonld, title=title, limit=limit), "jsonld.articleBody"

    candidates: list[tuple[int, str, str]] = []
    for block in candidate_blocks(html_text):
        paragraphs = paragraph_texts(block)
        chars = sum(len(paragraph) for paragraph in paragraphs)
        if chars >= 300:
            markdown = block_to_markdown(block, title=title, base_url=final_url, limit=limit)
            if markdown:
                candidates.append((chars, markdown, "semantic-block"))
    if candidates:
        _, markdown, method = max(candidates, key=lambda row: row[0])
        return markdown, method

    markdown = block_to_markdown(html_text, title=title, base_url=final_url, limit=limit)
    return markdown, "all-paragraphs"


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
    title = title_from_html(html_text)
    metadata = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": url,
        "final_url": final_url,
        "title": title,
        "description": description,
        "image_url": urljoin(final_url, image) if image else "",
        "canonical_url": urljoin(final_url, canonical) if canonical else "",
        "excerpt": excerpt_from_html(html_text),
        "content_type": content_type,
        "status": "ok",
    }
    article_text, article_method = extract_article_text(html_text)
    article_markdown, article_markdown_method = extract_article_markdown(html_text, final_url=final_url, title=title)
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
    if article_markdown:
        metadata.update(
            {
                "article_markdown": article_markdown,
                "article_markdown_chars": len(article_markdown),
                "article_markdown_method": article_markdown_method,
                "article_markdown_status": "ok" if len(article_markdown) >= 280 else "short",
                "article_markdown_label": "Markdown 閱讀版",
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
