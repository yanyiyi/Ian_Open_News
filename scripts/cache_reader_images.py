#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
DEFAULT_OUTPUT = ROOT / "docs" / "reader" / "assets" / "images"
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".png", ".webp", ".gif", ".avif"}


def clean_text(value: object, limit: int | None = None) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def image_candidates(item: dict) -> list[str]:
    candidates = [item.get("image"), item.get("image_url"), item.get("thumbnail")]
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    candidates.extend([metadata.get("image_url"), metadata.get("og_image"), metadata.get("twitter_image")])
    candidates.extend([reference.get("image"), reference.get("image_url"), reference.get("thumbnail"), reference.get("og_image")])
    raw_columns = reference.get("raw_columns")
    if isinstance(raw_columns, dict):
        candidates.extend([raw_columns.get("image"), raw_columns.get("Image"), raw_columns.get("圖片"), raw_columns.get("封面")])
    summary = str(item.get("summary") or "")
    candidates.extend(re.findall(r"""<img[^>]+src=["']([^"']+)["']""", summary, flags=re.I))
    candidates.extend(re.findall(r"""https?://[^\s"'<>]+?\.(?:png|jpe?g|webp|gif|avif)(?:\?[^\s"'<>]*)?""", summary, flags=re.I))
    output = []
    seen = set()
    for candidate in candidates:
        url = clean_text(candidate)
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        output.append(url)
    return output


def detect_image_extension(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if raw.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    if len(raw) >= 12 and raw[4:8] == b"ftyp" and raw[8:12] in {b"avif", b"avis"}:
        return ".avif"
    return None


def extension_for(url: str, content_type: str, detected_ext: str) -> str:
    if detected_ext in SUPPORTED_IMAGE_EXTENSIONS:
        return detected_ext
    parsed_ext = Path(urlparse(url).path).suffix.lower()
    if parsed_ext in SUPPORTED_IMAGE_EXTENSIONS | {".jpeg"}:
        return ".jpg" if parsed_ext == ".jpeg" else parsed_ext
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
    if guessed in SUPPORTED_IMAGE_EXTENSIONS | {".jpeg"}:
        return ".jpg" if guessed == ".jpeg" else guessed
    return ".jpg"


def request_url(url: str) -> str:
    parts = urlsplit(url)
    path = quote(parts.path, safe="/:%")
    query = quote(parts.query, safe="=&?/:+,%")
    fragment = quote(parts.fragment, safe="")
    return urlunsplit((parts.scheme, parts.netloc.encode("idna").decode("ascii"), path, query, fragment))


def cache_image(item: dict, image_url: str, output_dir: Path, timeout: int, max_bytes: int) -> tuple[dict, str]:
    request = urllib.request.Request(
        request_url(image_url),
        headers={
            "User-Agent": "IanOpenNewsBot/1.0 image cache (+local reader)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("content-type", "")
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return item, "too large"
    if "image" not in content_type.casefold() and not re.search(r"\.(png|jpe?g|webp|gif|avif)(?:\?|$)", image_url, flags=re.I):
        return item, f"not image: {content_type or 'unknown'}"
    detected_ext = detect_image_extension(raw)
    if not detected_ext:
        return item, f"not supported image payload: {content_type or 'unknown'}"
    digest = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:12]
    item_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_text(item.get("id")) or "item").strip("-")
    ext = extension_for(image_url, content_type, detected_ext)
    filename = f"{item_id}-{digest}{ext}"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename
    target.write_bytes(raw)
    relative_path = target.relative_to(ROOT).as_posix()
    updated = dict(item)
    metadata = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
    updated["reading_metadata"] = {
        **metadata,
        "image_cache": {
            "source_url": image_url,
            "path": relative_path,
            "reader_url": f"reader/assets/images/{filename}",
            "content_type": content_type,
            "bytes": len(raw),
            "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }
    return updated, "cached"


def cache_status(item: dict) -> tuple[bool, Path | None, str]:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    cache = metadata.get("image_cache") if isinstance(metadata.get("image_cache"), dict) else {}
    path = clean_text(cache.get("path"))
    if not path:
        return False, None, "missing metadata"
    cache_path = ROOT / path
    if not cache_path.exists():
        return False, cache_path, "missing file"
    try:
        detected_ext = detect_image_extension(cache_path.read_bytes()[:32])
    except OSError as exc:
        return False, cache_path, str(exc)
    if not detected_ext:
        return False, cache_path, "not supported image payload"
    if cache_path.suffix.lower() != detected_ext:
        return False, cache_path, f"extension mismatch: expected {detected_ext}"
    return True, cache_path, "ok"


def clear_image_cache(item: dict) -> dict:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    if "image_cache" not in metadata:
        return item
    updated = dict(item)
    cleaned_metadata = dict(metadata)
    cleaned_metadata.pop("image_cache", None)
    updated["reading_metadata"] = cleaned_metadata
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache remote item images for the static reader.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    items = load_jsonl(args.items)
    updated_items = []
    changed = 0
    attempted = 0
    skipped_cached = 0
    failed = 0
    for item in items:
        is_cached, cache_path, cache_reason = cache_status(item)
        if is_cached:
            skipped_cached += 1
            updated_items.append(item)
            continue
        current = clear_image_cache(item)
        if cache_path and cache_path.exists():
            try:
                cache_path.unlink()
            except OSError as exc:
                print(f"warning: cannot remove stale cache {cache_path}: {exc}")
        candidates = image_candidates(item)
        if not candidates:
            updated_items.append(current)
            continue
        if args.limit and attempted >= args.limit:
            updated_items.append(current)
            continue
        attempted += 1
        result = cache_reason
        for image_url in candidates[:3]:
            try:
                current, result = cache_image(current, image_url, args.output_dir, args.timeout, args.max_bytes)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                result = str(exc)
                continue
            if result == "cached":
                changed += 1
                break
        if result != "cached":
            failed += 1
            print(f"warning: image cache failed for {item.get('id')}: {result}")
        updated_items.append(current)

    if changed:
        write_jsonl(args.items, updated_items)
    print(f"cached: {changed}; already cached: {skipped_cached}; attempted: {attempted}; failed: {failed}")


if __name__ == "__main__":
    main()
