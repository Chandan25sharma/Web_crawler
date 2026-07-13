import scrapy


class ImageItem(scrapy.Item):
    """One discovered image or direct video file, plus the page it was found on.

    `image_urls` / `images` follow Scrapy's ImagesPipeline convention; despite the
    name, DedupImagesPipeline stores direct video files (mp4/webm/...) through the
    same field -- see settings.ALLOWED_VIDEO_EXTENSIONS.
    """

    page_url = scrapy.Field()
    page_title = scrapy.Field()
    image_urls = scrapy.Field()
    images = scrapy.Field()
    alt_text = scrapy.Field()
    title = scrapy.Field()


class EmbeddedVideoItem(scrapy.Item):
    """A YouTube/Vimeo-style <iframe> embed found on a page.

    Not a download: an iframe embed points at a third-party player, not a raw
    video file, so there's nothing to fetch here -- this just records that the
    embed exists (page, embed URL, platform) for your own reference.
    """

    page_url = scrapy.Field()
    page_title = scrapy.Field()
    embed_url = scrapy.Field()
    platform = scrapy.Field()
