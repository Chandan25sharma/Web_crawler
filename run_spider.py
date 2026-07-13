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
        "--include-videos", action="store_true",
        help="Also collect direct video files and record iframe embeds (off by default)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    domain = args.domain or urlparse(args.start).netloc

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
    # Explicit either way so the flag is authoritative regardless of what's
    # currently sitting in settings.py.
    settings.set(
        "ALLOWED_VIDEO_EXTENSIONS",
        ["mp4", "webm", "mov", "m4v", "ogv"] if args.include_videos else [],
    )
    settings.set(
        "EMBEDDED_VIDEO_DOMAINS",
        ["youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com"] if args.include_videos else [],
    )

    process = CrawlerProcess(settings)
    process.crawl(ImageSpider, start=args.start, allowed_domain=domain)
    process.start()


if __name__ == "__main__":
    main()
