"""Small, dependency-free helpers shared by the spider and pipelines.

Kept as plain functions (no classes) so they are trivial to unit test.
"""
from __future__ import annotations

import hashlib
import os
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


# Link/label words that say nothing about the file itself ("Download", "Compatible epub").
_GENERIC_WORDS = {
    "download", "downloads", "click", "here", "view", "open", "read", "now", "free", "file",
    "files", "link", "image", "img", "photo", "picture", "video", "play", "watch", "get", "the",
    "pdf", "epub", "kepub", "azw3", "mobi", "kindle", "kobo", "compatible", "advanced", "ebook",
    "book", "mp4", "webm", "mov", "jpg", "jpeg", "png", "gif", "webp", "svg", "untitled", "logo",
}
_HEX_ID_RE = re.compile(r"(?<![0-9a-z])[0-9a-f]{16,}(?![0-9a-z])", re.IGNORECASE)
_SIZE_SUFFIX_RE = re.compile(r"[-_]p[-_]\d+$", re.IGNORECASE)  # Webflow responsive "-p-1080"
_WINDOWS_BAD_RE = re.compile(r'[<>:"/\|?*\x00-\x1f]+')
_PAGE_TITLE_SPLIT_RE = re.compile(r"\s+[-|–—·]\s+")


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", (text or "").lower())


def _meaningful(text: str) -> bool:
    return any(w not in _GENERIC_WORDS and not w.isdigit() for w in _words(text))


def _tidy(text: str, ext: str = "") -> str:
    """Filename-ish label -> words: drop the extension, hex IDs, size suffixes, -/_ separators."""
    text = unquote(text or "").strip()
    if ext and text.lower().endswith(ext.lower()):
        text = text[: -len(ext)]
    if " " not in text:  # looks like a filename, not prose
        text = _SIZE_SUFFIX_RE.sub("", _HEX_ID_RE.sub(" ", text))
        text = re.sub(r"[-_.]+", " ", text)
        if text.islower():
            text = " ".join(w[:1].upper() + w[1:] for w in text.split())
    return " ".join(text.split())


def readable_stem(url: str, alt: str = "", title: str = "", page_title: str = "", max_len: int = 90) -> str:
    """A human-readable filename (no extension) for a downloaded file.

    Order: alt text / link title if they say something (short one first), then the page title when
    it's a nicer spelling of the URL's filename (e.g. "The Final Count, by H. C.
    McNeile" for h-c-mcneile_the-final-count.epub), then the tidied filename,
    then the page title. Always returns something usable on Windows.
    """
    base = os.path.basename(urlparse(url).path)
    ext = os.path.splitext(base)[1]
    from_url = _tidy(base, ext)
    heading = next((p for p in _PAGE_TITLE_SPLIT_RE.split(page_title or "") if p.strip()), "").strip()

    url_words = set(_words(from_url))
    heading_is_nicer = bool(url_words) and url_words <= set(_words(heading))

    alt, title = _tidy(alt, ext), _tidy(title, ext)
    # A long alt is usually a description sentence; a short meaningful title reads better.
    labels = (title, alt) if len(alt) > 60 and _meaningful(title) else (alt, title)
    for label in labels:
        if _meaningful(label):
            break
    else:
        label = heading if heading_is_nicer else (from_url if _meaningful(from_url) else heading or from_url)

    label = _WINDOWS_BAD_RE.sub(" ", label)
    label = " ".join(label.split()).strip(" .")
    if len(label) > max_len:
        label = label[:max_len].rsplit(" ", 1)[0]
    return label or "file"
