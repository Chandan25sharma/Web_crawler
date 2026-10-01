"""All tunables for the image crawler.

Change ALLOWED_DOMAINS / START_URLS for a new site; everything else has a
sane default. CLI flags in run_spider.py can override the most common ones
per-run without editing this file.
"""

BOT_NAME = "image_crawler"
SPIDER_MODULES = ["image_crawler.spiders"]
NEWSPIDER_MODULE = "image_crawler.spiders"

# --- Crawl target: the only two things you must change for a new site ---
START_URLS = ["https://example.com"]
ALLOWED_DOMAINS = ["example.com"]

# --- Crawl scope ---
DEPTH_LIMIT = 5          # 0 = unlimited
MAX_IMAGES = 0           # 0 = unlimited
ROBOTSTXT_OBEY = True    # flip to False only if the target's ToS allows it

# Only download media whose alt text / title / page title / URL contains at least
# one of these words (case-insensitive). Empty list = no filtering, download everything.
KEYWORDS: list[str] = [""]  # type: ignore
# Example: KEYWORDS = ["indian", "basmati", "rice"]

# --- Politeness / performance ---
# Scrapy has no literal "worker" processes to add -- it's a single async event
# loop that already sends many requests concurrently. These are the actual
# speed knobs. Defaults are polite enough for third-party sites (fast sites
# answer "429 Too Many Requests" otherwise). Crawling your OWN site and want
# speed? Use 32 / 16 / 0.1 / 0.1 / 8.0 instead.
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
COMPRESSION_ENABLED = True

# --- Retries (Scrapy's built-in RetryMiddleware) ---
RETRY_ENABLED = True
RETRY_TIMES = 3
# 429 / 503 are handled by BackoffMiddleware instead (waits before retrying).
RETRY_HTTP_CODES = [500, 502, 504, 408]
BACKOFF_MAX_TRIES = 6

# --- HTTP cache: speeds up repeated dev crawls, safe to disable for prod runs ---
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [301, 302, 401, 403, 404, 429, 500, 502, 503]

# --- Images ---
IMAGES_STORE = "downloads"
ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp", "svg", "avif"]
MEDIA_ALLOW_REDIRECTS = True

# --- Videos ---
# On by default. Set both to [] (or pass --no-videos) to collect images only.
ALLOWED_VIDEO_EXTENSIONS = ["mp4", "webm", "mov", "m4v", "ogv"]
EMBEDDED_VIDEO_DOMAINS = ["youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com"]

# --- Documents / ebooks ---
# Off by default so image crawls don't pull large files. Pass --documents
# (or tick "Include PDFs / ebooks" in the dashboard) to turn it on.
ALLOWED_DOCUMENT_EXTENSIONS: list[str] = []
# ALLOWED_DOCUMENT_EXTENSIONS = ["pdf", "epub", "azw3", "mobi"]

# Video files are big: give each download up to 10 minutes (Scrapy default is 3).
DOWNLOAD_TIMEOUT = 600
# Skip any single file bigger than this. Scrapy's default is 1 GB; lower it
# (e.g. 100 * 1024 * 1024) for sites that host huge sample/raw videos.
DOWNLOAD_MAXSIZE = 1024 * 1024 * 1024

# --- Crawl state / metadata output ---
SQLITE_DB_PATH = "crawl_state.db"
METADATA_CSV_PATH = "metadata.csv"
METADATA_JSON_PATH = "metadata.json"
EMBEDDED_VIDEOS_CSV_PATH = "embedded_videos.csv"
EMBEDDED_VIDEOS_JSON_PATH = "embedded_videos.json"

ITEM_PIPELINES = {
    "image_crawler.pipelines.DedupImagesPipeline": 300,
    "image_crawler.pipelines.EmbeddedVideoPipeline": 400,
    "image_crawler.pipelines.MetadataExportPipeline": 800,
}

DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    "image_crawler.middlewares.RotateUserAgentMiddleware": 400,
    # > 550 so it sees 429s before Scrapy's RetryMiddleware does
    "image_crawler.middlewares.BackoffMiddleware": 560,
}

# Scrapy's debug telnet console isn't used, and it logs a one-time password every
# run, which secret scanners (e.g. GitGuardian) flag if a log ever gets committed.
TELNETCONSOLE_ENABLED = False

LOG_LEVEL = "INFO"
LOG_FILE = "crawl.log"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
