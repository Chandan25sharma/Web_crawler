"""CLI entry point: python run_spider.py --start https://example.com

Thin wrapper around CrawlerProcess so the crawler can also be run without
`scrapy crawl imagespider -a start=... -a allowed_domain=...`.
"""
from __future__ import annotations

import argparse
import os
from urllib.parse import urlparse

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from image_crawler.spiders.imagespider import ImageSpider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl a public website and download every image.")
    parser.add_argument("--start", required=True, help="Seed URL, e.g. https://example.com")
    parser.add_argument("--domain", help="Allowed domain (defaults to the start URL's host)")
    parser.add_argument("--depth", type=int, help="Maximum crawl depth (default: settings.py DEPTH_LIMIT)")
    parser.add_argument("--max-images", type=int, help="Stop after this many images are queued")
    parser.add_argument("--output", help="Directory to save images into (default: downloads/)")
    parser.add_argument("--obey-robots", dest="robots", action="store_true", default=None)
    parser.add_argument("--ignore-robots", dest="robots", action="store_false")
    parser.add_argument(
        "--proxy", help="Route requests through this proxy, e.g. http://user:pass@host:port"
    )
    parser.add_argument(
        "--include-videos", dest="videos", action="store_true", default=None,
        help="Collect direct video files and record iframe embeds (default: settings.py, on)",
    )
    parser.add_argument("--no-videos", dest="videos", action="store_false", help="Images only")
    parser.add_argument(
        "--documents", nargs="?", const="pdf,epub,azw3,mobi",
        help="Also download documents/ebooks; optional list, e.g. --documents pdf,epub "
        "(bare flag = pdf,epub,azw3,mobi)",
    )
    parser.add_argument("--no-images", action="store_true", help="Skip images (e.g. books/videos only)")
    parser.add_argument(
        "--keywords",
        help='Comma-separated words to filter by, e.g. "rice,basmati" (overrides settings.py KEYWORDS for this run; blank = download everything)',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    domain = args.domain or urlparse(args.start).hostname

    settings = get_project_settings()
    if args.output:
        settings.set("IMAGES_STORE", args.output)
    if args.depth is not None:
        settings.set("DEPTH_LIMIT", args.depth)
    if args.max_images is not None:
        settings.set("MAX_IMAGES", args.max_images)
    if args.robots is not None:
        settings.set("ROBOTSTXT_OBEY", args.robots)
    if args.proxy:
        # Scrapy's built-in HttpProxyMiddleware (on by default) reads these
        # standard env vars -- no custom proxy middleware needed.
        os.environ["http_proxy"] = args.proxy
        os.environ["https_proxy"] = args.proxy
    # No flag = whatever settings.py says (videos on by default).
    if args.videos is True:
        settings.set("ALLOWED_VIDEO_EXTENSIONS", ["mp4", "webm", "mov", "m4v", "ogv"])
        settings.set("EMBEDDED_VIDEO_DOMAINS", ["youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com"])
    elif args.videos is False:
        settings.set("ALLOWED_VIDEO_EXTENSIONS", [])
        settings.set("EMBEDDED_VIDEO_DOMAINS", [])
    if args.documents:
        settings.set(
            "ALLOWED_DOCUMENT_EXTENSIONS",
            [e.strip().lstrip(".") for e in args.documents.split(",") if e.strip()],
        )
    if args.no_images:
        settings.set("ALLOWED_IMAGE_EXTENSIONS", [])
    if args.keywords is not None:
        settings.set("KEYWORDS", [k.strip() for k in args.keywords.split(",") if k.strip()])

    process = CrawlerProcess(settings)
    process.crawl(ImageSpider, start=args.start, allowed_domain=domain)
    process.start()


if __name__ == "__main__":
    main()
