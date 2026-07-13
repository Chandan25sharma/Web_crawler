"""The single spider: crawl internal pages, pull every image/video reference off each one."""
from __future__ import annotations

from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from w3lib.url import canonicalize_url

from ..items import EmbeddedVideoItem, ImageItem
from ..utils import best_srcset_url, extract_background_images, is_allowed_extension, matches_keywords


class ImageSpider(scrapy.Spider):
    name = "imagespider"

    def __init__(self, start: str | None = None, allowed_domain: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # -a start=... / -a allowed_domain=... override settings.py; both are optional here
        # because from_crawler() below fills in the settings.py defaults once available.
        self.start_urls = [start] if start else []
        self.allowed_domains = [allowed_domain] if allowed_domain else []
        self.link_extractor = LinkExtractor(allow_domains=self.allowed_domains or (), unique=True)
        self.images_seen = 0

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        # Spider.settings isn't bound until after __init__, so settings-derived
        # fallbacks (start URLs, domains, limits) are filled in here instead.
        spider = super().from_crawler(crawler, *args, **kwargs)
        if not spider.start_urls:
            spider.start_urls = crawler.settings.getlist("START_URLS")
        if not spider.allowed_domains:
            spider.allowed_domains = crawler.settings.getlist("ALLOWED_DOMAINS")
            spider.link_extractor = LinkExtractor(allow_domains=spider.allowed_domains, unique=True)
        spider.allowed_extensions = crawler.settings.getlist(
            "ALLOWED_IMAGE_EXTENSIONS", ["jpg", "jpeg", "png", "gif", "webp", "svg", "avif"]
        )
        spider.allowed_video_extensions = crawler.settings.getlist(
            "ALLOWED_VIDEO_EXTENSIONS", ["mp4", "webm", "mov", "m4v", "ogv"]
        )
        spider.embedded_video_domains = crawler.settings.getlist(
            "EMBEDDED_VIDEO_DOMAINS", ["youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com"]
        )
        spider.max_images = crawler.settings.getint("MAX_IMAGES", 0)
        # Hardcoded in settings.py (KEYWORDS = [...]); empty means "download everything".
        spider.keywords = [k.lower() for k in crawler.settings.getlist("KEYWORDS", []) if k]
        return spider

    def parse(self, response: scrapy.http.Response):
        content_type = response.headers.get("Content-Type", b"").decode(errors="ignore")
        if "text/html" not in content_type:
            return

        page_title = response.css("title::text").get("")
        yield from self._extract_media(response, page_title)
        yield from self._extract_embedded_videos(response, page_title)

        if not self.max_images or self.images_seen < self.max_images:
            for link in self.link_extractor.extract_links(response):
                yield response.follow(link.url, callback=self.parse)

    def _extract_media(self, response: scrapy.http.Response, page_title: str):
        """img/source/video tags -> ImageItem, filtered by extension then by keyword."""
        candidates: set[tuple[str, str, str]] = set()

        for sel in response.css("img, source, video"):
            # One tag = one logical file: take the real src-like attribute if present
            # (lazy-load attrs first, since `src` is often just a placeholder), and only
            # fall back to srcset's largest candidate for tags that have no src at all
            # (e.g. <source> inside <picture>). Otherwise src + every srcset size would
            # all get queued as separate "different" images. A <video><source></video>
            # pair is covered too: "source" matches regardless of its parent tag.
            url = None
            for attr in ("data-src", "data-original", "data-lazy", "src"):
                value = sel.attrib.get(attr)
                if value:
                    url = value
                    break
            if not url:
                srcset = sel.attrib.get("data-srcset") or sel.attrib.get("srcset")
                if srcset:
                    url = best_srcset_url(srcset)
            if url:
                candidates.add((url, sel.attrib.get("alt", ""), sel.attrib.get("title", "")))

        for prop in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            selector = f'meta[property="{prop}"]::attr(content), meta[name="{prop}"]::attr(content)'
            for value in response.css(selector).getall():
                candidates.add((value, "", ""))

        style_text = " ".join(
            response.css("[style]::attr(style)").getall() + response.css("style::text").getall()
        )
        for url in extract_background_images(style_text):
            candidates.add((url, "", ""))

        for raw_url, alt, title in candidates:
            if not raw_url:
                continue
            if self.max_images and self.images_seen >= self.max_images:
                break
            abs_url = canonicalize_url(response.urljoin(raw_url.strip()))
            is_image = is_allowed_extension(abs_url, self.allowed_extensions)
            is_video = is_allowed_extension(abs_url, self.allowed_video_extensions)
            if not (is_image or is_video):
                continue
            if not matches_keywords([alt, title, page_title, abs_url], self.keywords):
                continue
            self.images_seen += 1
            yield ImageItem(
                page_url=response.url,
                page_title=page_title,
                image_urls=[abs_url],
                alt_text=alt,
                title=title,
            )

    def _extract_embedded_videos(self, response: scrapy.http.Response, page_title: str):
        """<iframe> embeds (YouTube, Vimeo, ...) -- recorded, never downloaded.

        There's no raw video file behind an iframe embed, only a third-party
        player URL, so this just logs the reference instead of feeding it into
        the download pipeline.
        """
        urls = response.css("iframe::attr(src), iframe::attr(data-src)").getall()
        seen: set[str] = set()
        for raw_url in urls:
            if not raw_url:
                continue
            abs_url = response.urljoin(raw_url.strip())
            host = urlparse(abs_url).hostname or ""
            platform = next(
                (d for d in self.embedded_video_domains if host == d or host.endswith("." + d)),
                None,
            )
            if not platform or abs_url in seen:
                continue
            if not matches_keywords([page_title, abs_url], self.keywords):
                continue
            seen.add(abs_url)
            yield EmbeddedVideoItem(
                page_url=response.url,
                page_title=page_title,
                embed_url=abs_url,
                platform=platform,
            )
