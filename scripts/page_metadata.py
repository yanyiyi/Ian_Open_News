from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse


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

CODELIKE_PATTERNS = [
    "function(",
    "function (",
    "=>",
    "var ",
    "let ",
    "const ",
    "window.",
    "document.",
    "__next_data__",
    "webpack",
    "gtag(",
    "datalayer",
]


def unwrap_google_alert_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    if host not in {"www.google.com", "google.com"} or parsed.path not in {"/url", "/search"}:
        return url
    query = parse_qs(parsed.query)
    for key in ["url", "q"]:
        target = (query.get(key) or [""])[0].strip()
        if target.startswith(("http://", "https://")):
            return target
    return url


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


def is_code_like_text(value: object) -> bool:
    text = clean_text(value, 2400)
    if len(text) < 20:
        return False
    lowered = text.casefold()
    if any(pattern in lowered for pattern in CODELIKE_PATTERNS):
        symbol_count = sum(text.count(char) for char in "{}[]();=<>")
        if len(text) < 120 and symbol_count >= 5:
            return True
        if symbol_count >= max(12, len(text) // 22):
            return True
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) >= 3:
        code_lines = sum(1 for line in lines if re.search(r"[{}();=<>]{2,}|^\s*(var|let|const|function|import|export)\b", line))
        if code_lines / len(lines) >= 0.45:
            return True
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 180 and sum(char in "{}[]:," for char in compact) / len(compact) >= 0.18:
        return True
    return False


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


def normalize_language(value: object) -> str:
    text = clean_text(value, 80).replace("_", "-").strip().casefold()
    if not text:
        return ""
    if text.startswith("zh"):
        if any(part in text for part in ["tw", "hant", "hk", "mo"]):
            return "zh-Hant"
        if any(part in text for part in ["cn", "hans", "sg"]):
            return "zh-Hans"
        return "zh"
    if text.startswith("en"):
        return "en"
    if text.startswith("ja"):
        return "ja"
    if text.startswith("ko"):
        return "ko"
    if text.startswith("fr"):
        return "fr"
    if text.startswith("de"):
        return "de"
    if text.startswith("es"):
        return "es"
    if text.startswith("pt"):
        return "pt"
    return text.split("-")[0]


def infer_language_from_text(value: object) -> str:
    text = clean_text(value, 6000)
    if len(text) < 80:
        return ""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    kana = len(re.findall(r"[\u3040-\u30ff]", text))
    hangul = len(re.findall(r"[\uac00-\ud7af]", text))
    latin_words = re.findall(r"\b[A-Za-z]{3,}\b", text)
    letters = cjk + kana + hangul + sum(len(word) for word in latin_words)
    if not letters:
        return ""
    if cjk / max(1, len(text)) >= 0.18 or cjk >= 80:
        return "zh"
    if kana >= 30 and kana >= cjk:
        return "ja"
    if hangul >= 30:
        return "ko"
    if len(latin_words) >= 35 and sum(len(word) for word in latin_words) / max(1, letters) >= 0.65:
        return "en"
    return ""


def html_language(html_text: str, fallback_text: str = "") -> tuple[str, str]:
    match = re.search(r"(?is)<html\b([^>]*)>", html_text)
    if match:
        attrs = attrs_from_tag(match.group(1))
        language = normalize_language(attrs.get("lang") or attrs.get("xml:lang"))
        if language:
            return language, "html lang"
    for key in ["og:locale", "language", "content-language", "dc.language", "dcterms.language"]:
        language = normalize_language(first_meta(html_text, key))
        if language:
            return language, key
    language = normalize_language(jsonld_first_value(html_text, "inLanguage"))
    if language:
        return language, "json-ld inLanguage"
    language = infer_language_from_text(fallback_text)
    if language:
        return language, "推斷"
    return "", ""


def jsonld_nodes(html_text: str) -> list[object]:
    nodes: list[object] = []
    for match in re.finditer(r"(?is)<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", html_text):
        raw = html.unescape(match.group(1)).strip()
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            nodes.append(node)
            if isinstance(node, dict):
                graph = node.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
                for key in ["mainEntity", "mainEntityOfPage", "itemListElement"]:
                    child = node.get(key)
                    if isinstance(child, (dict, list)):
                        stack.append(child)
                stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node)
    return nodes


def jsonld_text(value: object) -> str:
    if isinstance(value, str):
        return clean_text(value, 500)
    if isinstance(value, dict):
        for key in ["name", "headline", "@id", "url"]:
            text = clean_text(value.get(key), 500)
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = jsonld_text(item)
            if text:
                return text
    return ""


def jsonld_first_value(html_text: str, *keys: str) -> str:
    wanted = set(keys)
    for node in jsonld_nodes(html_text):
        if not isinstance(node, dict):
            continue
        for key in wanted:
            text = jsonld_text(node.get(key))
            if text:
                return text
    return ""


def author_from_html(html_text: str) -> tuple[str, str]:
    for key in ["author", "article:author", "twitter:creator", "dc.creator", "dcterms.creator", "parsely-author"]:
        author = first_meta(html_text, key)
        if author:
            return author, key
    author = jsonld_first_value(html_text, "author", "creator")
    if author:
        return author, "json-ld"
    byline_match = re.search(r"(?is)<[^>]+class=['\"][^'\"]*(?:author|byline)[^'\"]*['\"][^>]*>(.*?)</[^>]+>", html_text)
    if byline_match:
        author = clean_text(byline_match.group(1), 240)
        if author:
            return author, "頁面 byline"
    return "", ""


def license_from_html(html_text: str, final_url: str = "") -> tuple[str, str, str]:
    license_link = first_link(html_text, "license")
    if license_link:
        license_url = urljoin(final_url, license_link) if final_url else license_link
        return license_url, "rel=license", license_url
    for key in ["license", "dc.rights", "dcterms.rights", "rights", "copyright"]:
        text = first_meta(html_text, key)
        if text:
            return text, key, ""
    text = jsonld_first_value(html_text, "license", "copyrightNotice", "copyrightHolder")
    if text:
        return text, "json-ld", text if text.startswith(("http://", "https://")) else ""
    sample = clean_text(html_text, 300000).casefold()
    cc_match = re.search(r"\bcc[- ]?by(?:[- ](?:sa|nc|nd))*\b|creative commons", sample)
    if cc_match:
        return "Creative Commons（頁面文字推斷）", "推斷", ""
    if "all rights reserved" in sample or "版權所有" in sample or "著作權所有" in sample:
        return "著作權保護（頁面文字推斷）", "推斷", ""
    return "", "", ""


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
    for node in jsonld_nodes(html_text):
        if not isinstance(node, dict):
            continue
        body = node.get("articleBody") or node.get("text")
        if isinstance(body, str) and len(clean_text(body)) >= 300:
            bodies.append(clean_text(body))
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
        if is_code_like_text(text):
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
    while paragraphs and is_code_like_text(paragraphs[0]):
        paragraphs.pop(0)
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
        if is_code_like_text(plain):
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
    url = unwrap_google_alert_url(url)
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
    excerpt = excerpt_from_html(html_text)
    author, author_source = author_from_html(html_text)
    license_text, license_source, license_url = license_from_html(html_text, final_url)
    language, language_source = html_language(html_text, "\n".join([title, description, excerpt]))
    metadata = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": url,
        "final_url": final_url,
        "title": title,
        "original_site_title": title,
        "description": description,
        "image_url": urljoin(final_url, image) if image else "",
        "canonical_url": urljoin(final_url, canonical) if canonical else "",
        "excerpt": excerpt,
        "content_type": content_type,
        "status": "ok",
    }
    if language:
        metadata["original_language"] = language
        metadata["original_language_source"] = language_source
    if author:
        metadata["original_author"] = author
        metadata["original_author_source"] = author_source
    if license_text:
        metadata["original_license"] = license_text
        metadata["original_license_source"] = license_source
    if license_url:
        metadata["original_license_url"] = license_url
    article_text, article_method = extract_article_text(html_text)
    article_markdown, article_markdown_method = extract_article_markdown(html_text, final_url=final_url, title=title)
    if not language:
        language = infer_language_from_text(article_text or article_markdown or "\n".join([title, description, excerpt]))
        if language:
            metadata["original_language"] = language
            metadata["original_language_source"] = "推斷"
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


def codex_zh_title(item: dict) -> str:
    editorial = item.get("editorial_triage")
    if not isinstance(editorial, dict):
        return ""
    codex_review = editorial.get("codex_review")
    if isinstance(codex_review, dict):
        title = clean_text(codex_review.get("zh_title"), 260)
        if title:
            return title
    return clean_text(editorial.get("zh_title"), 260)


def complete_item_metadata(item: dict) -> tuple[dict, bool]:
    current = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    metadata = dict(current)
    if not clean_text(metadata.get("original_site_title")):
        metadata["original_site_title"] = clean_text(metadata.get("title") or item.get("title"), 300)
        metadata.setdefault("original_site_title_source", "RSS/頁面標題")
    if not clean_text(metadata.get("original_language")):
        text = "\n".join(
            clean_text(part, 3000)
            for part in [
                metadata.get("article_text"),
                metadata.get("article_markdown"),
                metadata.get("description"),
                item.get("summary"),
                metadata.get("original_site_title"),
                item.get("title"),
            ]
            if clean_text(part)
        )
        language = infer_language_from_text(text)
        if language:
            metadata["original_language"] = language
            metadata["original_language_source"] = "推斷"
    if not clean_text(metadata.get("original_author")) and clean_text(item.get("author")):
        metadata["original_author"] = clean_text(item.get("author"), 240)
        metadata["original_author_source"] = "RSS"
    if not clean_text(metadata.get("original_license")):
        metadata["original_license"] = "未標示，推定為著作權保護"
        metadata["original_license_source"] = "推斷"
    if not clean_text(metadata.get("translated_zh_title")):
        zh_title = codex_zh_title(item)
        if zh_title:
            metadata["translated_zh_title"] = zh_title
            metadata["translated_zh_title_source"] = "Codex"
    if metadata == current:
        return item, False
    updated = dict(item)
    updated["reading_metadata"] = metadata
    return updated, True


def enrich_item_metadata(item: dict, timeout: int = 8) -> tuple[dict, bool, str]:
    original_url = str(item.get("url") or "").strip()
    url = unwrap_google_alert_url(original_url)
    if not url.startswith(("http://", "https://")):
        updated, changed = complete_item_metadata(item)
        return updated, changed, "no fetchable url"
    try:
        metadata = fetch_page_metadata(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
        updated, changed = complete_item_metadata(item)
        return updated, changed, str(exc)

    updated = dict(item)
    if url != original_url:
        reference = updated.get("reference") if isinstance(updated.get("reference"), dict) else {}
        updated["url"] = url
        updated["reference"] = {**reference, "original_google_url": original_url}
    current = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
    updated["reading_metadata"] = {**current, **metadata}
    if metadata.get("image_url"):
        updated["image_url"] = metadata["image_url"]
    if metadata.get("description") and len(str(updated.get("summary") or "")) < 120:
        updated["summary"] = metadata["description"]
    updated, completion_changed = complete_item_metadata(updated)
    return updated, updated != item or completion_changed, ""
