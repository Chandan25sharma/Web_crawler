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
# speed knobs. Values here are raised for crawling your own site; lower them
# back down (16 / 8 / 0.5 / 4.0) before pointing this at a third-party site.
CONCURRENT_REQUESTS = 32
CONCURRENT_REQUESTS_PER_DOMAIN = 16
DOWNLOAD_DELAY = 0.1
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 8.0
COMPRESSION_ENABLED = True

# --- Retries (Scrapy's built-in RetryMiddleware) ---
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# --- HTTP cache: speeds up repeated dev crawls, safe to disable for prod runs ---
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [301, 302, 401, 403, 404, 500, 502, 503]

# --- Images ---
IMAGES_STORE = "downloads"
ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp", "svg", "avif"]
MEDIA_ALLOW_REDIRECTS = True

# --- Videos ---
# Disabled for now -- empty lists mean nothing matches as a video, so the spider
# only ever collects images. Re-add extensions/domains below to turn it back on.
ALLOWED_VIDEO_EXTENSIONS: list[str] = []
EMBEDDED_VIDEO_DOMAINS: list[str] = []
# ALLOWED_VIDEO_EXTENSIONS = ["mp4", "webm", "mov", "m4v", "ogv"]
# EMBEDDED_VIDEO_DOMAINS = ["youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com"]

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
}

LOG_LEVEL = "INFO"
LOG_FILE = "crawl.log"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
