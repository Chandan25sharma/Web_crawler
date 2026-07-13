"""Small, dependency-free helpers shared by the spider and pipelines.

Kept as plain functions (no classes) so they are trivial to unit test.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from urllib.parse import unquote, urlparse

_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_BACKGROUND_URL_RE = re.compile(
    r"background(?:-image)?\s*:\s*[^;}]*?url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
    re.IGNORECASE,
)


def extract_srcset_urls(srcset: str) -> list[str]:
    """Pull the URL out of each candidate in a `srcset`/`data-srcset` attribute."""
    urls = []
    for candidate in (srcset or "").split(","):
        candidate = candidate.strip()
        if candidate:
            urls.append(candidate.split()[0])
    return urls


def best_srcset_url(srcset: str) -> str | None:
    """Pick the single highest-resolution URL out of a `srcset` list.

    `srcset` commonly lists the same picture at several sizes ("a.jpg 500w,
    a.jpg 1600w, ..."); downloading every entry means downloading duplicates
    of one logical image, so callers should take only this one.
    """
    best_url, best_width = None, -1
    for candidate in (srcset or "").split(","):
        parts = candidate.strip().split()
        if not parts:
            continue
        url = parts[0]
        width = int(parts[1][:-1]) if len(parts) > 1 and parts[1].endswith("w") else 0
        if best_url is None or width >= best_width:
            best_url, best_width = url, width
    return best_url


def extract_background_images(css_text: str) -> list[str]:
    """Find `url(...)` targets inside inline `style` attributes or `<style>` blocks."""
    return _BACKGROUND_URL_RE.findall(css_text or "")


def matches_keywords(texts: list[str], keywords: list[str]) -> bool:
    """True if any keyword appears (case-insensitively) in any of the given texts.

    An empty `keywords` list means "no filter" -- everything matches.
    """
    if not keywords:
        return True
    haystack = " ".join(t for t in texts if t).lower()
    return any(kw.lower() in haystack for kw in keywords if kw)


def is_allowed_extension(url: str, allowed_extensions: list[str]) -> bool:
    """Check the URL path (ignoring query string) against an allow-list of extensions."""
    path = urlparse(url).path.lower()
    return any(path.endswith("." + ext.lower().lstrip(".")) for ext in allowed_extensions)


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Turn an arbitrary URL segment into a safe filename fragment."""
    name = unquote(name or "")
    name = _UNSAFE_FILENAME_RE.sub("_", name).strip("._")
    return (name or "image")[:max_len]


def category_path_from_url(page_url: str) -> tuple[str, str]:
    """Derive (category, subcategory) from the first two path segments of a page URL."""
    segments = [s for s in urlparse(page_url or "").path.split("/") if s]
    category = sanitize_filename(segments[0]) if len(segments) >= 1 else "uncategorized"
    subcategory = sanitize_filename(segments[1]) if len(segments) >= 2 else ""
    return category, subcategory


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Open (and lazily initialize) the SQLite crawl-state database.

    A single `images` table doubles as the resume/dedup index (unique image_url)
    and the source of truth for the CSV/JSON metadata export.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_url TEXT,
            media_url TEXT UNIQUE,
            media_type TEXT,
            local_path TEXT,
            alt_text TEXT,
            title TEXT,
            page_title TEXT,
            crawl_timestamp TEXT,
            http_status INTEGER,
            file_size INTEGER,
            width INTEGER,
            height INTEGER,
            mime_type TEXT,
            content_hash TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON images(content_hash)")
    conn.commit()
    return conn
