import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapy.http import HtmlResponse
from scrapy.utils.test import get_crawler

from image_crawler.items import EmbeddedVideoItem, ImageItem
from image_crawler.spiders.imagespider import ImageSpider

HTML = b"""
<html><head><title>Rice Products</title></head><body>
  <img src="/img/indian-basmati-rice.jpg" alt="Indian Basmati Rice">
  <img src="/img/pakistani-rice.jpg" alt="Pakistani Rice">
  <video src="/media/factory-tour.mp4"></video>
  <video><source src="/media/promo.webm" type="video/webm"></video>
  <iframe src="https://www.youtube.com/embed/abc123"></iframe>
</body></html>
"""


def make_spider(keywords=None):
    crawler = get_crawler(ImageSpider)
    spider = ImageSpider.from_crawler(crawler, start="https://example.com/", allowed_domain="example.com")
    spider.allowed_extensions = ["jpg", "jpeg", "png"]
    spider.allowed_video_extensions = ["mp4", "webm"]
    spider.embedded_video_domains = ["youtube.com", "youtu.be", "vimeo.com"]
    spider.max_images = 0
    spider.keywords = keywords or []
    return spider


class SpiderExtractionTests(unittest.TestCase):
    def _parse(self, spider):
        response = HtmlResponse(
            url="https://example.com/rice",
            body=HTML,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
        return list(spider.parse(response))

    def test_extracts_images_and_direct_videos_without_keyword_filter(self):
        items = self._parse(make_spider())
        image_items = [i for i in items if isinstance(i, ImageItem)]
        urls = {i["image_urls"][0] for i in image_items}
        self.assertIn("https://example.com/img/indian-basmati-rice.jpg", urls)
        self.assertIn("https://example.com/img/pakistani-rice.jpg", urls)
        self.assertIn("https://example.com/media/factory-tour.mp4", urls)
        self.assertIn("https://example.com/media/promo.webm", urls)

    def test_keyword_filter_keeps_only_matching_items(self):
        items = self._parse(make_spider(keywords=["indian"]))
        image_items = [i for i in items if isinstance(i, ImageItem)]
        urls = {i["image_urls"][0] for i in image_items}
        self.assertIn("https://example.com/img/indian-basmati-rice.jpg", urls)
        self.assertNotIn("https://example.com/img/pakistani-rice.jpg", urls)

    def test_extra_video_sources(self):
        html = b"""<html><head><title>Vids</title></head><body>
          <div data-video-urls="/v/bg.mp4,/v/bg.webm" data-poster-url="/v/bg.jpg"></div>
          <a href="/v/tour.mp4">Tour</a>
          <video src="/v/tour.mp4"></video>
          <video><source src="/stream/123" type="video/mp4"></video>
          <a href="/about">About</a>
        </body></html>"""
        response = HtmlResponse(
            url="https://example.com/", body=html, headers={"Content-Type": "text/html"}
        )
        items = [i for i in make_spider().parse(response) if isinstance(i, ImageItem)]
        urls = [i["image_urls"][0] for i in items]
        for expected in ("bg.mp4", "bg.webm", "bg.jpg", "tour.mp4", "stream/123"):
            self.assertIn("https://example.com/" + ("" if "/" in expected else "v/") + expected, urls)
        self.assertEqual(urls.count("https://example.com/v/tour.mp4"), 1)  # deduped
        self.assertNotIn("https://example.com/about", urls)
        stream = next(i for i in items if i["image_urls"][0].endswith("/stream/123"))
        self.assertTrue(stream["typed_video"])

    def test_video_descriptions_from_jsonld_and_link_text(self):
        html = b"""<html><head><title>Files</title>
          <script type="application/ld+json">{"@graph":[{"@type":"Dataset","name":"clip-a.mp4",
            "description":"Clip A for QA","distribution":{"contentUrl":"https://cdn.example.com/clip-a.mp4"}}]}</script>
          <script type="application/ld+json">{not json</script>
        </head><body>
          <a href="https://cdn.example.com/clip-a.mp4">Download</a>
          <a href="/clip-b.mp4">Factory tour  video</a>
        </body></html>"""
        response = HtmlResponse(
            url="https://example.com/", body=html, headers={"Content-Type": "text/html"}
        )
        items = {i["image_urls"][0]: i for i in make_spider().parse(response) if isinstance(i, ImageItem)}
        a = items["https://cdn.example.com/clip-a.mp4"]
        self.assertEqual((a["title"], a["alt_text"]), ("clip-a.mp4", "Clip A for QA"))
        self.assertEqual(items["https://example.com/clip-b.mp4"]["title"], "Factory tour video")

    def test_embedded_video_recorded_not_downloaded(self):
        items = self._parse(make_spider())
        embeds = [i for i in items if isinstance(i, EmbeddedVideoItem)]
        self.assertEqual(len(embeds), 1)
        self.assertEqual(embeds[0]["platform"], "youtube.com")
        self.assertEqual(embeds[0]["embed_url"], "https://www.youtube.com/embed/abc123")


if __name__ == "__main__":
    unittest.main()
