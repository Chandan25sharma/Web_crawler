# image_crawler

A Scrapy project that crawls a public website (staying within its domain) and
downloads every image (and, optionally, video) it can find, with resumable
state, CSV/JSON metadata export, keyword filtering, and a local web dashboard.

## What it uses, and why

Almost everything here is stock Scrapy, configured rather than reimplemented:

| Feature | Implementation |
|---|---|
| Domain restriction | `allowed_domains` + Scrapy's built-in `OffsiteMiddleware` (media requests explicitly opt out via `allow_offsite`, since images/videos are commonly served from a separate CDN host) |
| Max crawl depth | Scrapy's built-in `DepthMiddleware` (`DEPTH_LIMIT`) |
| Duplicate page / URL-loop avoidance | Scrapy's default request dupefilter + `w3lib.url.canonicalize_url` |
| Retries | Scrapy's built-in `RetryMiddleware` (`RETRY_TIMES`, `RETRY_HTTP_CODES`) |
| Rate limiting | Scrapy's built-in `AutoThrottle` |
| robots.txt | Scrapy's built-in `ROBOTSTXT_OBEY` (toggle in settings.py or via CLI) |
| HTTP compression / caching | Scrapy's built-in `HttpCompressionMiddleware` / `HttpCacheMiddleware` |
| Image/video download, retry-on-fail | Scrapy's `ImagesPipeline`, subclassed as `DedupImagesPipeline` (SVG and video files bypass Pillow and are stored as raw bytes, since Pillow can't decode them) |
| Embedded video (YouTube/Vimeo iframes) | Recorded as a reference only — never downloaded, since there's no raw file behind an iframe embed, just a link to a third-party player |
| Keyword filtering | Hardcoded `KEYWORDS` list in `settings.py`; matched against alt text / title / page title / URL |
| Proxy support | Scrapy's built-in `HttpProxyMiddleware`, driven by the standard `http_proxy`/`https_proxy` env vars (`--proxy` sets them for you) |
| User-Agent rotation | The one custom downloader middleware (`middlewares.RotateUserAgentMiddleware`) — Scrapy has no built-in for this |
| Crawl state / dedup / resume | SQLite (stdlib `sqlite3`), one `images` table |
| Metadata export | stdlib `csv` + `json`, dumped from the SQLite table on spider close |
| Web dashboard | Flask (`webapp.py`) — start/stop crawls, live log tail, live file grid with thumbnails, filtering, and tagging, all localhost-only |

## Project layout

```
image_crawler/
  scrapy.cfg
  run_spider.py              # CLI entry point
  webapp.py                  # local web dashboard (Flask)
  web/index.html             # dashboard UI (single static page, no build step)
  requirements.txt
  image_crawler/
    settings.py              # all tunables — change ALLOWED_DOMAINS/START_URLS here
    items.py                 # ImageItem, EmbeddedVideoItem
    spiders/imagespider.py   # crawl + image/video extraction logic
    pipelines.py             # DedupImagesPipeline, EmbeddedVideoPipeline, MetadataExportPipeline
    middlewares.py           # RotateUserAgentMiddleware
    utils.py                 # pure helper functions (unit tested)
  tests/
    test_utils.py
    test_spider.py           # exercises extraction against a synthetic HTML page
```

## Setup

Requires Python 3.12+.

### Windows (PowerShell)
```powershell
cd image_crawler
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Linux / macOS
```bash
cd image_crawler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

Only the start URL and domain need to change for a new site:

```bash
python run_spider.py --start https://example.com
```

Or with plain Scrapy (edit `START_URLS` / `ALLOWED_DOMAINS` in `settings.py` first):

```bash
scrapy crawl imagespider
```

### CLI flags

```
--start URL                seed URL (required)
--domain DOMAIN             allowed domain (default: derived from --start)
--depth N                    max crawl depth (default: settings.py DEPTH_LIMIT = 5)
--max-images N              stop after N images are queued (default: unlimited)
--output DIR                  where images are saved (default: downloads/)
--obey-robots / --ignore-robots        override ROBOTSTXT_OBEY for this run
--proxy URL                  route requests through this proxy, e.g. http://user:pass@host:port
--include-videos                also collect direct video files + record iframe embeds (off by default)
```

Example, deeper crawl into a specific site with robots.txt already confirmed
permissive by its ToS:

```bash
python run_spider.py --start https://example.com/gallery --depth 8 --max-images 5000
```

### Keyword filtering

Edit `KEYWORDS` in `settings.py` (hardcoded on purpose, not a CLI flag):

```python
KEYWORDS = ["indian", "basmati", "rice"]   # any one match downloads the file
```

Matched case-insensitively against alt text, title, page title, and the
media's own URL. Leave it `KEYWORDS = []` to disable filtering and download
everything. If a crawl comes back with zero results, this is the first thing
to check — it silently filters out anything that doesn't match.

### Output

- `downloads/<category>/<subcategory>/<filename>` — images and (if
  `--include-videos` was used) videos, in folders derived from the first two
  path segments of the page they were found on
  (`downloads/uncategorized/...` if the page has no such segments)
- `metadata.csv` / `metadata.json` — page URL, media URL, media type
  (image/video), local path, alt text, title, page title, crawl timestamp,
  HTTP status, file size, width, height, MIME type
- `embedded_videos.csv` / `embedded_videos.json` — YouTube/Vimeo iframe
  embeds found on crawled pages (page URL, embed URL, platform); these are
  references only, never downloaded
- `crawl_state.db` — SQLite table backing resume (re-running skips URLs
  already recorded) and content-hash dedup (a byte-identical file found at a
  different URL reuses the existing file instead of saving a second copy)
- `crawl.log` — page/media counts, retries, failures (also visible in stdout)

To resume an interrupted crawl, just re-run the same command — already-seen
media URLs are skipped via `crawl_state.db`. To start clean, delete
`crawl_state.db`, `downloads/`, and the metadata files.

## Web dashboard

A local, single-user, no-login UI for starting crawls and browsing results
without touching the command line:

```bash
python webapp.py
```

Then open **http://127.0.0.1:5000**. It lets you:

- Enter a URL, toggle "include videos", optionally cap max images, and start/stop a crawl
- Watch a live-tailing log panel while it runs
- Browse a live-updating grid of downloaded files with real thumbnails/video previews
- Filter the grid by filename, alt text, page title, or tag
- Add free-form tags to any file, saved to `tags.json`

It works by shelling out to `run_spider.py` as a subprocess and polling
`crawl.log` / `crawl_state.db` — no new crawl logic, just a UI on top of the
same CLI. Runs on `127.0.0.1` only; there's no auth because it's not meant to
be exposed beyond your own machine.

**Not exposed in the UI on purpose:** `--proxy`. Set it from the command line
if you need it — see the CLI flags above.

## Extending image/video extraction

All extraction logic lives in `ImageSpider._extract_media()` (images/direct
videos) and `_extract_embedded_videos()` (iframes) in
`spiders/imagespider.py`. `_extract_media` builds a set of `(url, alt,
title)` candidates from several sources before resolving/filtering them —
add a new source by appending to that same set, e.g. a new attribute name or
a new meta tag:

```python
for value in response.css('meta[name="my-custom-image"]::attr(content)').getall():
    candidates.add((value, "", ""))
```

Everything downstream (URL resolution, extension filtering, keyword
filtering, dedup, folder placement, metadata export) applies automatically —
no other file needs to change. To accept a new file extension, add it to
`ALLOWED_IMAGE_EXTENSIONS` or `ALLOWED_VIDEO_EXTENSIONS` in `settings.py`. To
recognize another embed platform, add its domain to `EMBEDDED_VIDEO_DOMAINS`.

**What Scrapy can't see:** if a page loads its real content via client-side
JavaScript after the initial page load (a common pattern on React/Next.js/Vue
sites — the server sends an empty "loading..." shell, then a background fetch
fills it in), none of the above helps, because the HTML this crawler receives
genuinely doesn't contain the data yet. Check with
`curl -A "Mozilla/5.0" <url> | grep -i "img\|video"` before assuming a page
should work — if you see real tags with real filenames, it'll work; if you
see empty containers or loading skeletons, it won't, and would need a
headless-browser renderer (e.g. Playwright) added as a different kind of
downloader, not an extraction tweak.

## Tests

```bash
python -m unittest discover tests
```

`test_utils.py` covers the pure-function helpers (srcset parsing,
background-image regex, extension filtering, filename sanitizing, category
derivation, keyword matching). `test_spider.py` runs the spider's extraction
methods against a synthetic HTML page (covering image/video tags, keyword
filtering, and embedded-video detection) without needing a live crawl. The
pipeline classes depend on a live Scrapy crawl and are exercised by running
the crawler itself rather than mocked in unit tests.
