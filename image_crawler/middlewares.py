import random
from collections import Counter
from urllib.parse import urlparse

from scrapy.utils.defer import deferred_from_coro


class RotateUserAgentMiddleware:
    """Assigns a random desktop/mobile User-Agent to every request.

    Scrapy has no built-in UA rotation, so this is the one custom downloader
    middleware in the project; everything else (retries, throttling, robots.txt,
    compression, caching) uses Scrapy's stock middlewares via settings.py.
    """

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1",
    ]

    def process_request(self, request, spider):
        request.headers["User-Agent"] = random.choice(self.USER_AGENTS)


class BackoffMiddleware:
    """On 429 Too Many Requests / 503: slow the whole site down, then retry.

    Scrapy's RetryMiddleware retries instantly, so a rate-limited site just
    answers 429 again and the file is lost. Here the site's download slot gets
    a delay (the server's Retry-After if it sends one, else 5s, 10s, 20s, ...
    capped at 5 min) that applies to every following request to that host;
    AutoThrottle eases it back down once responses are OK again.

    If a host refuses BACKOFF_STOP_AFTER requests in a row, it isn't a speed
    problem but a quota / access rule (e.g. downloads reserved for members),
    so the crawl is stopped instead of retrying for hours.
    """

    CODES = (429, 503)

    def __init__(self, crawler):
        self.crawler = crawler
        self.max_tries = crawler.settings.getint("BACKOFF_MAX_TRIES", 6)
        self.stop_after = crawler.settings.getint("BACKOFF_STOP_AFTER", 20)
        self.refused_in_a_row: Counter[str] = Counter()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_response(self, request, response, spider=None):
        key = request.meta.get("download_slot") or urlparse(request.url).hostname
        if response.status not in self.CODES:
            self.refused_in_a_row[key] = 0
            return response
        self.refused_in_a_row[key] += 1
        if self.refused_in_a_row[key] >= self.stop_after:
            self.crawler.spider.logger.error(
                "%s refused %d requests in a row (HTTP %s). This site is limiting or "
                "blocking downloads, not just asking us to slow down -- stopping the crawl. "
                "Check whether it offers an official bulk download instead.",
                key, self.refused_in_a_row[key], response.status,
            )
            deferred_from_coro(self.crawler.engine.close_spider_async(reason="rate_limited"))
            return response
        tries = request.meta.get("backoff_tries", 0) + 1
        if tries > self.max_tries:
            return response  # give up; the pipeline logs the failure

        retry_after = response.headers.get("Retry-After", b"").decode(errors="ignore").strip()
        wait = float(retry_after) if retry_after.isdigit() else min(5 * 2 ** (tries - 1), 300)
        wait = min(wait, 300)

        slot = self.crawler.engine.downloader.slots.get(key)
        if slot is not None:
            slot.delay = max(slot.delay, wait)
        self.crawler.spider.logger.info(
            "%s from %s -- waiting %ss between requests, retry %d/%d: %s",
            response.status, key, int(wait), tries, self.max_tries, request.url,
        )
        new_request = request.replace(dont_filter=True)
        new_request.meta["backoff_tries"] = tries
        return new_request
