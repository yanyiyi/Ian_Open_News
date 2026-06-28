#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


URL_RE = re.compile(r"https://[^\s<>{}\[\]\"']+", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
ARXIV_RE = re.compile(r"\b(?:arXiv\s*:\s*)?(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.I)
AUTHOR_RE = re.compile(r"(?im)^\s*(?:author|authors|作者)\s*[:：]\s*(.+?)\s*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object, limit: int | None = None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def strip_markdown(value: object, limit: int | None = None) -> str:
    text = clean_text(value)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`~]+", "", text)
    text = " ".join(text.split())
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def slugify(value: object, fallback: str = "pdf", limit: int = 64) -> str:
    text = strip_markdown(value).casefold()
    text = re.sub(r"[^\w\u3400-\u9fff]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    return (text[:limit].strip("-_") or fallback)


def markitdown_path() -> str:
    found = shutil.which("markitdown")
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "bin" / "markitdown",
        Path("/opt/homebrew/bin/markitdown"),
        Path("/usr/local/bin/markitdown"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("找不到 markitdown CLI。請先確認 markitdown 已安裝並可執行。")


def markdown_title(markdown: str) -> tuple[str, str]:
    for line in markdown.splitlines():
        match = re.match(r"^\s{0,3}#\s+(.+?)\s*$", line)
        if match:
            return strip_markdown(match.group(1), 320), "markitdown-first-heading"
    for line in markdown.splitlines():
        candidate = strip_markdown(line, 320)
        if 4 <= len(candidate) <= 320:
            return candidate, "markitdown-first-line"
    return "", ""


def markdown_first_paragraph(markdown: str, title: str = "") -> str:
    blocks = re.split(r"\n\s*\n", markdown)
    for block in blocks:
        text = strip_markdown(block, 1200)
        if not text or text == title or len(text) < 40:
            continue
        if URL_RE.fullmatch(text):
            continue
        return text
    return ""


def download_pdf(url: str, dest_dir: Path, timeout: int = 45, max_bytes: int = 80_000_000) -> Path:
    """下載遠端 PDF 到 dest_dir，回傳本機路徑。驗 %PDF- 檔頭，依內容雜湊命名去重。"""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
    if not raw:
        raise RuntimeError("遠端 PDF 下載為空。")
    if len(raw) > max_bytes:
        raise RuntimeError("遠端 PDF 超過下載大小上限。")
    if b"%PDF-" not in raw[:1024]:
        raise RuntimeError("下載的內容不是 PDF（找不到 %PDF- 檔頭）。可能網址不是直接指向 PDF。")
    dest_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    dest = dest_dir / f"remote-{digest[:16]}.pdf"
    dest.write_bytes(raw)
    return dest


def extract_pdf_markdown(pdf_path: Path, original_filename: str = "") -> tuple[str, dict[str, Any]]:
    command = [markitdown_path(), str(pdf_path)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            "markitdown 轉檔失敗。"
            + (f"\n{clean_text(result.stderr, 1600)}" if result.stderr else "")
        )
    markdown = clean_text(result.stdout)
    if len(markdown) < 40:
        raise RuntimeError("markitdown 沒有抽到足夠文字。")
    title, title_source = markdown_title(markdown)
    summary = markdown_first_paragraph(markdown, title)
    urls: list[str] = []
    seen_urls: set[str] = set()
    for match in URL_RE.findall(markdown):
        url = match.rstrip(".,;:!?)]}，。；：！？）】")
        if url and url not in seen_urls:
            seen_urls.add(url)
            urls.append(url)
    dois = list(dict.fromkeys(match.rstrip(".,;:") for match in DOI_RE.findall(markdown)))
    arxiv_ids = list(dict.fromkeys(match for match in ARXIV_RE.findall(markdown)))
    author_match = AUTHOR_RE.search(markdown)
    author = strip_markdown(author_match.group(1), 240) if author_match else ""
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    meta = {
        "original_filename": original_filename or pdf_path.name,
        "sha256": digest,
        "title": title,
        "title_source": title_source,
        "author": author,
        "author_source": "markitdown-text-label" if author else "",
        "summary_candidate": summary,
        "summary_source": "markitdown-first-paragraph" if summary else "",
        "urls": urls[:40],
        "doi": dois[:12],
        "arxiv_id": arxiv_ids[:12],
        "extracted_at": now_iso(),
        "extractor": "markitdown-cli",
    }
    return markdown, meta


def item_title(item: dict[str, Any]) -> str:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    return strip_markdown(
        item.get("editorial_title")
        or metadata.get("editorial_title")
        or editorial.get("zh_title")
        or metadata.get("translated_zh_title")
        or item.get("title")
        or item.get("url"),
        320,
    )


def item_comparison_text(item: dict[str, Any]) -> str:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    for key in (
        "translated_article_markdown_zh",
        "codex_translated_article_markdown_zh",
        "claude_translated_article_markdown_zh",
        "gemini_translated_article_markdown_zh",
        "ollama_translated_article_markdown_zh",
        "ollama_gemma4_translated_article_markdown_zh",
        "ollama_twinkle_translated_article_markdown_zh",
        "article_markdown",
        "article_text",
    ):
        value = clean_text(metadata.get(key))
        if len(value) >= 80:
            return value
    return clean_text(item.get("summary"))


def title_candidates(pdf_item: dict[str, Any], existing_items: list[dict[str, Any]], threshold: float = 0.6) -> list[dict[str, Any]]:
    probe = item_title(pdf_item) or strip_markdown(pdf_item.get("summary"), 500)
    if not probe:
        return []
    rows: list[dict[str, Any]] = []
    for item in existing_items:
        if item.get("id") == pdf_item.get("id"):
            continue
        candidate_title = item_title(item)
        if not candidate_title:
            continue
        score = SequenceMatcher(None, probe.casefold(), candidate_title.casefold()).ratio()
        if score < threshold:
            continue
        rows.append(
            {
                "item_id": str(item.get("id") or ""),
                "title": candidate_title,
                "url": str(item.get("url") or ""),
                "source_name": str(item.get("source_name") or ""),
                "title_similarity": round(score, 4),
                "candidate_kind": "title-source",
            }
        )
    rows.sort(key=lambda row: row["title_similarity"], reverse=True)
    return rows[:6]


def text_shingles(value: object) -> set[str]:
    text = clean_text(value).casefold()
    compact = re.sub(r"[^\w\u3400-\u9fff]+", "", text, flags=re.UNICODE)
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", compact))
    if cjk_count >= max(8, len(compact) // 8):
        size = 4
        return {compact[index : index + size] for index in range(max(0, len(compact) - size + 1))}
    words = re.findall(r"[a-z0-9\u3400-\u9fff]+", text)
    if len(words) < 3:
        return set(words)
    size = 3
    return {" ".join(words[index : index + size]) for index in range(len(words) - size + 1)}


def relationship_score(pdf_text: str, other_text: str) -> dict[str, Any] | None:
    pdf_set = text_shingles(pdf_text)
    other_set = text_shingles(other_text)
    if len(pdf_set) < 18 or len(other_set) < 18:
        return None
    overlap = len(pdf_set & other_set)
    if not overlap:
        return None
    existing_covered_by_pdf = overlap / len(other_set)
    pdf_covered_by_existing = overlap / len(pdf_set)
    jaccard = overlap / len(pdf_set | other_set)
    relation = ""
    score = 0.0
    if existing_covered_by_pdf >= 0.72 and len(pdf_set) >= len(other_set) * 1.08:
        relation = "full-source"
        score = max(existing_covered_by_pdf, jaccard)
    elif pdf_covered_by_existing >= 0.72 or existing_covered_by_pdf >= 0.58:
        relation = "subset"
        score = max(pdf_covered_by_existing, existing_covered_by_pdf)
    elif jaccard >= 0.12 or max(existing_covered_by_pdf, pdf_covered_by_existing) >= 0.3:
        relation = "related"
        score = max(jaccard, min(existing_covered_by_pdf, pdf_covered_by_existing))
    if not relation:
        return None
    confidence = "高" if score >= 0.78 else "中" if score >= 0.48 else "低"
    direction = (
        "existing-in-pdf"
        if existing_covered_by_pdf > pdf_covered_by_existing + 0.08
        else "pdf-in-existing"
        if pdf_covered_by_existing > existing_covered_by_pdf + 0.08
        else "similar-size"
    )
    return {
        "relation": relation,
        "confidence": confidence,
        "score": round(score, 4),
        "existing_covered_by_pdf": round(existing_covered_by_pdf, 4),
        "pdf_covered_by_existing": round(pdf_covered_by_existing, 4),
        "jaccard": round(jaccard, 4),
        "direction": direction,
    }


def content_candidates(pdf_item: dict[str, Any], existing_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pdf_text = item_comparison_text(pdf_item)
    if len(pdf_text) < 120:
        return []
    rows: list[dict[str, Any]] = []
    for item in existing_items:
        if item.get("id") == pdf_item.get("id"):
            continue
        other_text = item_comparison_text(item)
        if len(other_text) < 80:
            continue
        score = relationship_score(pdf_text, other_text)
        if not score:
            continue
        rows.append(
            {
                "item_id": str(item.get("id") or ""),
                "title": item_title(item),
                "url": str(item.get("url") or ""),
                "source_name": str(item.get("source_name") or ""),
                "candidate_kind": "content-relation",
                **score,
            }
        )
    relation_order = {"full-source": 0, "subset": 1, "related": 2}
    rows.sort(key=lambda row: (relation_order.get(str(row.get("relation")), 9), -float(row.get("score") or 0)))
    return rows[:10]


def relationship_candidates(pdf_item: dict[str, Any], existing_items: list[dict[str, Any]], has_source_url: bool) -> list[dict[str, Any]]:
    title_rows = [] if has_source_url else title_candidates(pdf_item, existing_items)
    content_rows = content_candidates(pdf_item, existing_items)
    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for row in [*title_rows, *content_rows]:
        key = (str(row.get("item_id")), str(row.get("candidate_kind")))
        combined[key] = row
    return list(combined.values())
