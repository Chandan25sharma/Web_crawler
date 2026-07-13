import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from image_crawler.utils import (
    best_srcset_url,
    category_path_from_url,
    extract_background_images,
    extract_srcset_urls,
    is_allowed_extension,
    matches_keywords,
    sanitize_filename,
)


class UtilsTests(unittest.TestCase):
    def test_extract_srcset_urls(self):
        srcset = "img-320.jpg 320w, img-640.jpg 640w,img-1024.jpg 1024w"
        self.assertEqual(
            extract_srcset_urls(srcset), ["img-320.jpg", "img-640.jpg", "img-1024.jpg"]
        )

    def test_best_srcset_url_picks_largest_width(self):
        srcset = "img-p-500.jpg 500w, img-p-2000.jpg 2000w, img-p-800.jpg 800w"
        self.assertEqual(best_srcset_url(srcset), "img-p-2000.jpg")

    def test_best_srcset_url_no_width_descriptor_takes_last(self):
        self.assertEqual(best_srcset_url("a.jpg, b.jpg"), "b.jpg")

    def test_matches_keywords(self):
        self.assertTrue(matches_keywords(["Indian Basmati Rice", ""], ["indian", "rice"]))
        self.assertFalse(matches_keywords(["Pakistani Rice"], ["indian"]))
        self.assertTrue(matches_keywords(["anything"], []))  # no keywords = no filter

    def test_extract_background_images(self):
        css = "div{background-image:url('/a/b.png')} .x{background: url(\"c.jpg\") no-repeat}"
        self.assertEqual(extract_background_images(css), ["/a/b.png", "c.jpg"])

    def test_is_allowed_extension(self):
        self.assertTrue(is_allowed_extension("https://x.com/a.JPG", ["jpg", "png"]))
        self.assertFalse(is_allowed_extension("https://x.com/a.bmp", ["jpg", "png"]))

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("weird name?.jpg"), "weird_name_.jpg")

    def test_category_path_from_url(self):
        self.assertEqual(
            category_path_from_url("https://x.com/electronics/phones/iphone"),
            ("electronics", "phones"),
        )
        self.assertEqual(category_path_from_url("https://x.com/"), ("uncategorized", ""))


if __name__ == "__main__":
    unittest.main()
