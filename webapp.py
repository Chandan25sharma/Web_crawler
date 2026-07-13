"""Local dashboard for the image/video crawler: start a crawl, watch it run, browse results.

Single-user, localhost-only tool -- no auth, no multi-crawl queue. Run with:
    ./.venv/Scripts/python.exe webapp.py
then open http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_file, send_from_directory

from scrapy.utils.project import get_project_settings

from image_crawler.utils import get_db_connection

BASE_DIR = Path(__file__).resolve().parent
settings = get_project_settings()
IMAGES_STORE = BASE_DIR / settings.get("IMAGES_STORE", "downloads")
SQLITE_DB_PATH = BASE_DIR / settings.get("SQLITE_DB_PATH", "crawl_state.db")
LOG_FILE = BASE_DIR / settings.get("LOG_FILE", "crawl.log")
TAGS_PATH = BASE_DIR / "tags.json"

app = Flask(__name__, static_folder=None)

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_started_at: float | None = None


def _tags() -> dict[str, list[str]]:
    if TAGS_PATH.exists():
        return json.loads(TAGS_PATH.read_text(encoding="utf-8"))
    return {}


def _save_tags(tags: dict[str, list[str]]) -> None:
    TAGS_PATH.write_text(json.dumps(tags, indent=2, ensure_ascii=False), encoding="utf-8")


@app.get("/")
def index():
    # This page changes often during dev; send_file's default caching headers
    # were making browsers serve a stale copy even on a normal refresh.
    resp = send_file(BASE_DIR / "web" / "index.html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/start")
def start_crawl():
    global _proc, _started_at
    body = request.get_json(force=True)
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify(error="url is required"), 400

    with _lock:
        if _proc is not None and _proc.poll() is None:
            return jsonify(error="a crawl is already running"), 409

        domain = urlparse(url).netloc
        cmd = [
            sys.executable, "run_spider.py",
            "--start", url,
            "--domain", domain,
        ]
        if body.get("include_videos"):
            cmd.append("--include-videos")
        if body.get("max_images"):
            cmd += ["--max-images", str(int(body["max_images"]))]
        if body.get("keywords"):
            cmd += ["--keywords", str(body["keywords"])]

        # crawl.log/crawl_state.db carry all the output the UI needs; the
        # subprocess's own stdout/stderr aren't polled, so just discard them.
        _proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _started_at = time.time()
    return jsonify(status="started")


@app.post("/api/stop")
def stop_crawl():
    with _lock:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
            return jsonify(status="stopping")
    return jsonify(status="not running")


def _tail_log(max_lines: int = 300) -> list[str]:
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 200_000))
        chunk = fh.read().decode("utf-8", errors="ignore")
    lines = chunk.splitlines()
    return lines[-max_lines:]


@app.get("/api/status")
def status():
    with _lock:
        running = _proc is not None and _proc.poll() is None
        elapsed = time.time() - _started_at if running and _started_at else 0

    downloaded = 0
    if SQLITE_DB_PATH.exists():
        conn = get_db_connection(str(SQLITE_DB_PATH))
        downloaded = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        conn.close()

    return jsonify(running=running, elapsed_seconds=round(elapsed), downloaded=downloaded, log=_tail_log())


@app.get("/api/files")
def files():
    if not SQLITE_DB_PATH.exists():
        return jsonify([])

    query = (request.args.get("q") or "").strip().lower()
    conn = get_db_connection(str(SQLITE_DB_PATH))
    rows = conn.execute(
        """
        SELECT page_url, media_url, media_type, local_path, alt_text, title, page_title,
               file_size, width, height, mime_type, crawl_timestamp
        FROM images ORDER BY id DESC LIMIT 500
        """
    ).fetchall()
    conn.close()

    fields = [
        "page_url", "media_url", "media_type", "local_path", "alt_text", "title", "page_title",
        "file_size", "width", "height", "mime_type", "crawl_timestamp",
    ]
    tags = _tags()
    records = []
    for row in rows:
        rec = dict(zip(fields, row))
        rec["tags"] = tags.get(rec["local_path"], [])
        if query:
            haystack = " ".join(
                str(rec.get(k) or "") for k in ("local_path", "alt_text", "title", "page_title")
            ).lower() + " " + " ".join(rec["tags"]).lower()
            if query not in haystack:
                continue
        records.append(rec)
    return jsonify(records)


@app.post("/api/tag")
def add_tag():
    body = request.get_json(force=True)
    local_path = body.get("local_path")
    tag = (body.get("tag") or "").strip()
    if not local_path or not tag:
        return jsonify(error="local_path and tag are required"), 400

    tags = _tags()
    existing = tags.setdefault(local_path, [])
    if tag not in existing:
        existing.append(tag)
    _save_tags(tags)
    return jsonify(tags=existing)


@app.get("/media/<path:subpath>")
def media(subpath):
    return send_from_directory(IMAGES_STORE, subpath)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
