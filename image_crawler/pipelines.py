import csv
import json
import mimetypes
import os
from datetime import datetime, timezone
from io import BytesIO

import scrapy
from itemadapter import ItemAdapter
from PIL import Image
from scrapy.pipelines.images import ImagesPipeline
from scrapy.utils.defer import ensure_awaitable

from .items import EmbeddedVideoItem
from .utils import get_db_connection, readable_stem, sha1_hex

# Formats Pillow (and thus the stock ImagesPipeline) can't decode as raster images:
# vector/XML (svg), and video files (mp4/webm/...) which aren't images at all.
# These are stored as raw bytes instead of going through PIL validation/conversion.
_ALWAYS_RAW_EXTENSIONS = (".svg",)


def _content_type(response) -> str:
    return response.headers.get("Content-Type", b"").decode(errors="ignore").split(";")[0].strip().lower()


class DedupImagesPipeline(ImagesPipeline):
    """Scrapy's stock ImagesPipeline, extended with:

    - direct video files (mp4/webm/...) stored as raw bytes alongside images
    - resume support: URLs already recorded in SQLite are not re-downloaded
    - content-hash dedup: a byte-identical image found under a new URL reuses
      the existing file on disk instead of being saved twice
    """

    def open_spider(self, spider):
        super().open_spider(spider)
        self.conn = get_db_connection(spider.settings.get("SQLITE_DB_PATH", "crawl_state.db"))
        self._url_name: dict[str, str] = {}
        self._taken: set[str] = set()
        video_extensions = spider.settings.getlist(
            "ALLOWED_VIDEO_EXTENSIONS", ["mp4", "webm", "mov", "m4v", "ogv"]
        )
        self._document_extensions = tuple(
            f".{ext}" for ext in spider.settings.getlist("ALLOWED_DOCUMENT_EXTENSIONS", [])
        )
        self._raw_extensions = (
            _ALWAYS_RAW_EXTENSIONS + tuple(f".{ext}" for ext in video_extensions) + self._document_extensions
        )

    def close_spider(self, spider):
        self.conn.close()

    def get_media_requests(self, item, info):
        if isinstance(item, EmbeddedVideoItem):
            return  # nothing to download -- see EmbeddedVideoItem / EmbeddedVideoPipeline
        adapter = ItemAdapter(item)
        for url in adapter["image_urls"]:
            already = self.conn.execute(
                "SELECT 1 FROM images WHERE media_url = ?", (url,)
            ).fetchone()
            if already:
                info.spider.logger.debug("Skipping already-downloaded image: %s", url)
                continue
            # Images are commonly served from a CDN/subdomain outside allowed_domains
            # (e.g. upload.wikimedia.org for commons.wikimedia.org pages); the domain
            # restriction is about which pages we crawl, not which hosts serve assets.
            yield scrapy.Request(
                url, meta={"item": item, "allow_offsite": True, "typed_video": adapter.get("typed_video")}
            )

    def file_path(self, request, response=None, info=None, *, item=None):
        # Flat downloads/ folder with human-readable names built from the page
        # (alt text, link text, page title...) -- see utils.readable_stem().
        # file_path() is called several times per request, so the first answer
        # for a URL is cached and reused.
        if request.url in self._url_name:
            return self._url_name[request.url]

        ext = os.path.splitext(os.path.basename(request.url.split("?")[0]))[1].lower()
        if not ext or len(ext) > 6:
            # Extensionless URL (CDN/stream links): pick the extension from the
            # response Content-Type once we have it, else from the tag that found it.
            ctype = _content_type(response) if response else ""
            ext = mimetypes.guess_extension(ctype) if ctype.startswith(("video/", "image/")) else None
            if not ext and request.meta.get("typed_video"):
                ext = ".mp4"
            ext = ext or ".jpg"
            if not response:
                return f"{readable_stem(request.url)}{ext}"  # provisional; not cached

        adapter = ItemAdapter(item) if item else {}
        stem = readable_stem(
            request.url, adapter.get("alt_text") or "", adapter.get("title") or "",
            adapter.get("page_title") or "",
        )
        name, n = f"{stem}{ext}", 2
        while name in self._taken or self.conn.execute(
            "SELECT 1 FROM images WHERE local_path = ?", (name,)
        ).fetchone():
            name, n = f"{stem} ({n}){ext}", n + 1
        self._taken.add(name)
        self._url_name[request.url] = name
        return name

    async def file_downloaded(self, response, request, info, *, item=None):
        url_path = request.url.split("?")[0].lower()
        is_raw = (
            url_path.endswith(self._raw_extensions)
            or request.meta.get("typed_video")
            or _content_type(response).startswith("video/")
        )
        if not is_raw:
            return await super().file_downloaded(response, request, info, item=item)

        path = self.file_path(request, response=response, info=info, item=item)
        buf = BytesIO(response.body)
        await ensure_awaitable(
            self.store.persist_file(path, buf, info, meta={}, headers=None)
        )
        return sha1_hex(response.body)

    def item_completed(self, results, item, info):
        adapter = ItemAdapter(item)
        store_dir = self.store.basedir

        for ok, meta in results:
            if not ok:
                info.spider.crawler.stats.inc_value("images/download_failed")
                continue

            full_path = os.path.join(store_dir, meta["path"])
            file_size = os.path.getsize(full_path)
            with open(full_path, "rb") as fh:
                content_hash = sha1_hex(fh.read())
            mime_type, _ = mimetypes.guess_type(full_path)
            if mime_type and mime_type.startswith("video"):
                media_type = "video"
            elif self._document_extensions and full_path.lower().endswith(self._document_extensions):
                media_type = "document"
            else:
                media_type = "image"
            width = height = None
            if media_type == "image":
                try:
                    with Image.open(full_path) as im:
                        width, height = im.size
                except Exception:
                    info.spider.logger.warning("Could not read image metadata for %s", full_path)

            local_path = meta["path"]
            duplicate = self.conn.execute(
                "SELECT local_path FROM images WHERE content_hash = ? AND local_path != ?",
                (content_hash, meta["path"]),
            ).fetchone()
            if content_hash and duplicate:
                os.remove(full_path)
                local_path = duplicate[0]
                info.spider.crawler.stats.inc_value("images/duplicate_content")

            self.conn.execute(
                """
                INSERT OR REPLACE INTO images
                    (page_url, media_url, media_type, local_path, alt_text, title, page_title,
                     crawl_timestamp, http_status, file_size, width, height, mime_type, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    adapter.get("page_url"),
                    meta["url"],
                    media_type,
                    local_path,
                    adapter.get("alt_text"),
                    adapter.get("title"),
                    adapter.get("page_title"),
                    datetime.now(timezone.utc).isoformat(),
                    200,
                    file_size,
                    width,
                    height,
                    mime_type,
                    content_hash,
                ),
            )
            self.conn.commit()
            info.spider.crawler.stats.inc_value("images/downloaded")

        return item


class EmbeddedVideoPipeline:
    """Collects EmbeddedVideoItem (iframe embeds) and dumps them to CSV/JSON on close.

    These were never downloaded (see EmbeddedVideoItem's docstring), so they don't
    belong in the SQLite `images` table alongside real downloaded files -- a plain
    in-memory list is enough for a report of "these pages embed a video from X".
    """

    FIELDS = ["page_url", "page_title", "embed_url", "platform"]

    def open_spider(self, spider):
        self.csv_path = spider.settings.get("EMBEDDED_VIDEOS_CSV_PATH", "embedded_videos.csv")
        self.json_path = spider.settings.get("EMBEDDED_VIDEOS_JSON_PATH", "embedded_videos.json")
        self.records: list[dict] = []
        self._seen: set[tuple[str, str]] = set()

    def process_item(self, item, spider):
        if not isinstance(item, EmbeddedVideoItem):
            return item
        adapter = ItemAdapter(item)
        key = (adapter.get("page_url"), adapter.get("embed_url"))
        if key not in self._seen:
            self._seen.add(key)
            self.records.append(dict(adapter))
        return item

    def close_spider(self, spider):
        if not self.records:
            return
        with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows(self.records)
        with open(self.json_path, "w", encoding="utf-8") as fh:
            json.dump(self.records, fh, indent=2, ensure_ascii=False)
        spider.logger.info(
            "Recorded %d embedded video(s) to %s and %s",
            len(self.records), self.csv_path, self.json_path,
        )


class MetadataExportPipeline:
    """Dumps the SQLite `images` table to CSV and JSON when the spider closes."""

    FIELDS = [
        "page_url", "media_url", "media_type", "local_path", "alt_text", "title", "page_title",
        "crawl_timestamp", "http_status", "file_size", "width", "height", "mime_type",
    ]

    def open_spider(self, spider):
        self.db_path = spider.settings.get("SQLITE_DB_PATH", "crawl_state.db")
        self.csv_path = spider.settings.get("METADATA_CSV_PATH", "metadata.csv")
        self.json_path = spider.settings.get("METADATA_JSON_PATH", "metadata.json")

    def process_item(self, item, spider):
        return item

    def close_spider(self, spider):
        conn = get_db_connection(self.db_path)
        rows = conn.execute(f"SELECT {', '.join(self.FIELDS)} FROM images").fetchall()
        conn.close()

        records = [dict(zip(self.FIELDS, row)) for row in rows]

        with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows(records)

        with open(self.json_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)

        spider.logger.info(
            "Exported %d media records to %s and %s", len(records), self.csv_path, self.json_path
        )
