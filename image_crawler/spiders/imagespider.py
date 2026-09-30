"""The single spider: crawl internal pages, pull every image/video reference off each one."""
from __future__ import annotations

import json
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
        # (url, alt, title, is_typed_video). is_typed_video marks URLs that a
        # <video>/<source type="video/..."> tag vouches for, so they're kept even
        # when the URL has no file extension (common with CDN/stream URLs).
        candidates: set[tuple[str, str, str, bool]] = set()

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
                tag = sel.root.tag if isinstance(sel.root.tag, str) else ""
                typed_video = tag == "video" or sel.attrib.get("type", "").startswith("video/")
                alt = sel.attrib.get("alt") or sel.attrib.get("aria-label", "")
                candidates.add((url, alt, sel.attrib.get("title", ""), typed_video))

        # <a href="clip.mp4">: the link's own text / title is the file's description.
        for sel in response.css("a[href]"):
            text = sel.attrib.get("title") or " ".join(" ".join(sel.css("::text").getall()).split())
            candidates.add((sel.attrib["href"], sel.attrib.get("aria-label", ""), text[:300], False))

        # JSON-LD (VideoObject / ImageObject / DataDownload ...): gives name + description,
        # and sometimes lists files that aren't in any tag at all.
        for url, name, description in _jsonld_media(response.css('script[type="application/ld+json"]::text').getall()):
            candidates.add((url, description, name, False))

        # <video poster>, Webflow background videos (data-video-urls="a.mp4,a.webm"),
        # and og:video meta. Anything
        # that isn't an allowed image/video extension is dropped by the filter below.
        extra = response.css("video::attr(poster), [data-poster-url]::attr(data-poster-url)").getall()
        for value in response.css("[data-video-urls]::attr(data-video-urls)").getall():
            extra += value.split(",")
        for prop in (
            "og:image", "og:image:url", "twitter:image", "twitter:image:src",
            "og:video", "og:video:url", "og:video:secure_url",
        ):
            selector = f'meta[property="{prop}"]::attr(content), meta[name="{prop}"]::attr(content)'
            extra += response.css(selector).getall()
        style_text = " ".join(
            response.css("[style]::attr(style)").getall() + response.css("style::text").getall()
        )
        extra += extract_background_images(style_text)
        for url in extra:
            candidates.add((url, "", "", False))

        # Same file can be referenced several ways (e.g. <video src> + <a href>);
        # yield it once, preferring the reference with the most alt/title text.
        yielded: set[str] = set()
        for raw_url, alt, title, typed_video in sorted(candidates, key=lambda c: -(bool(c[1]) + bool(c[2]))):
            if not raw_url:
                continue
            if self.max_images and self.images_seen >= self.max_images:
                break
            abs_url = canonicalize_url(response.urljoin(raw_url.strip()))
            if not abs_url.startswith(("http://", "https://")):
                continue  # data:, blob:, javascript:, mailto: ...
            is_image = is_allowed_extension(abs_url, self.allowed_extensions)
            is_video = bool(self.allowed_video_extensions) and (
                typed_video or is_allowed_extension(abs_url, self.allowed_video_extensions)
            )
            if not (is_image or is_video) or abs_url in yielded:
                continue
            if not matches_keywords([alt, title, page_title, abs_url], self.keywords):
                continue
            yielded.add(abs_url)
            self.images_seen += 1
            yield ImageItem(
                page_url=response.url,
                page_title=page_title,
                image_urls=[abs_url],
                alt_text=alt,
                title=title,
                typed_video=typed_video and not is_image,
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


def _jsonld_media(blocks: list[str]):
    """Yield (url, name, description) for every contentUrl/embedUrl in JSON-LD blocks.

    A file's own name/description wins; otherwise the enclosing object's is used
    (e.g. Dataset.description around a DataDownload.contentUrl).
    """
    def walk(node, name="", description=""):
        if isinstance(node, list):
            for child in node:
                yield from walk(child, name, description)
        elif isinstance(node, dict):
            name = node.get("name") if isinstance(node.get("name"), str) else name
            description = node.get("description") if isinstance(node.get("description"), str) else description
            for key in ("contentUrl", "embedUrl", "thumbnailUrl"):
                if isinstance(node.get(key), str):
                    yield node[key], name, description
            for value in node.values():
                if isinstance(value, (dict, list)):
                    yield from walk(value, name, description)

    for block in blocks:
        try:
            yield from walk(json.loads(block))
        except ValueError:
            continue  # malformed JSON-LD is common; skip it
