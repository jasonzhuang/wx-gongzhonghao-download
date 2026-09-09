import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from ebooklib import ITEM_DOCUMENT, epub
from fastapi import HTTPException

from routes.admin import _fetch_history_internal
from routes.export import (
    RECOMMENDED_EXPORT_BATCH,
    _validate_time_range,
    count_account_export,
)
from utils.epub_render import build_epub


class ExportCountTests(unittest.TestCase):
    def test_invalid_time_range_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            _validate_time_range(200, 100)
        self.assertEqual(caught.exception.status_code, 400)

    def test_count_endpoint_marks_more_than_100_for_batching(self):
        with (
            patch("routes.export.rss_store.get_subscription", return_value={"nickname": "测试号"}),
            patch("routes.export.rss_store.count_export_articles", return_value=101),
        ):
            result = asyncio.run(count_account_export("MP_WXS_1", since=100, before=200))

        self.assertEqual(result["count"], 101)
        self.assertEqual(result["batch_limit"], RECOMMENDED_EXPORT_BATCH)
        self.assertTrue(result["batch_required"])


class HistoryExportPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_range_still_fetches_content_when_over_100(self):
        articles = [
            {
                "aid": str(i),
                "link": f"https://mp.weixin.qq.com/s/{i}",
                "title": f"文章 {i}",
                "publish_time": 1000 + i,
            }
            for i in range(101)
        ]

        class FakeClient:
            async def list_articles(self, fakeid, offset):
                return articles, None

        async def enrich_content(batch, client):
            return ([{**item, "content": "<p>正文</p>"} for item in batch], [])

        enrich = AsyncMock(side_effect=enrich_content)
        with (
            patch("utils.weread_client.WereadClient", return_value=FakeClient()),
            patch("routes.admin.rss_store.get_subscription", return_value={"fakeid": "MP_WXS_1"}),
            patch("routes.admin.rss_store.get_history_cursor", return_value={"complete": False, "offset": 0}),
            patch("routes.admin.rss_store.save_articles", return_value=101),
            patch("routes.admin.rss_store.update_history_cursor"),
            patch("routes.admin.rss_store.get_export_articles", return_value=[]),
            patch("utils.rss_poller.rss_poller._enrich_articles_content", enrich),
        ):
            result = await _fetch_history_internal(
                "MP_WXS_1", target_count=100, until=900, before=1200, max_articles=100
            )

        self.assertEqual(result[3], 101)
        self.assertEqual(result[4], 101)
        self.assertTrue(result[8])
        self.assertEqual(enrich.await_count, 11)

    async def test_custom_end_date_filters_scanned_articles(self):
        articles = [
            {"aid": "1", "link": "https://mp.weixin.qq.com/s/1", "publish_time": 100},
            {"aid": "2", "link": "https://mp.weixin.qq.com/s/2", "publish_time": 200},
            {"aid": "3", "link": "https://mp.weixin.qq.com/s/3", "publish_time": 300},
        ]

        class FakeClient:
            async def list_articles(self, fakeid, offset):
                return articles, None

        with (
            patch("utils.weread_client.WereadClient", return_value=FakeClient()),
            patch("routes.admin.rss_store.get_subscription", return_value={"fakeid": "MP_WXS_1"}),
            patch("routes.admin.rss_store.get_history_cursor", return_value={"complete": False, "offset": 0}),
            patch("routes.admin.rss_store.save_articles", return_value=2) as save,
            patch("routes.admin.rss_store.update_history_cursor"),
            patch("routes.admin.rss_store.get_export_articles", return_value=[]),
            patch("utils.rss_poller.rss_poller._enrich_articles_content", AsyncMock(return_value=([], []))),
        ):
            result = await _fetch_history_internal(
                "MP_WXS_1", target_count=100, until=100, before=200, max_articles=100
            )

        saved_articles = save.call_args_list[0].args[1]
        self.assertEqual([item["publish_time"] for item in saved_articles], [100, 200])
        self.assertEqual(result[3], 2)
        self.assertFalse(result[8])


class EpubExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_100_article_epub_can_be_read_back(self):
        articles = [
            {
                "id": i,
                "title": f"文章 {i}",
                "author": "作者",
                "publish_time": 1700000000 + i,
                "content": f"<p>第 {i} 篇正文</p>",
            }
            for i in range(100)
        ]
        with patch("utils.epub_render.fetch_images_bytes", AsyncMock(return_value={})):
            content = await build_epub("测试号", articles, "", max_side=800)

        with tempfile.NamedTemporaryFile(suffix=".epub") as output:
            output.write(content)
            output.flush()
            book = epub.read_epub(output.name)

        documents = list(book.get_items_of_type(ITEM_DOCUMENT))
        self.assertGreaterEqual(len(documents), 100)


if __name__ == "__main__":
    unittest.main()
